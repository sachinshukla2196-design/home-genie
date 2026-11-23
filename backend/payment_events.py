"""Payment webhook reconciliation (Batch 14, P0). Spec: docs/PAYMENT_RECONCILIATION_SPEC.md.

Every Razorpay webhook delivery is:
1. AUTHENTICATED  HMAC-SHA256 of the raw body with RAZORPAY_WEBHOOK_SECRET (`X-Razorpay-Signature`); anything else -> 400, nothing
                  recorded. Missing secret -> 503 (the provider retries later).
2. NORMALISED     into a small, PII-free summary: event id, type, gateway order id, payment id, amount (paise), currency, status.
                  An event without an id or type is malformed -> 400.
3. RECORDED       once in `webhook_events` (unique `event_id`) with status, reason, the order / payment attempt it matched,
                  and every processing attempt (`attempts`). Concurrent deliveries of one event: exactly one claims it.
4. MATCHED        to OUR payment attempt by the gateway order id we created (`payment_transactions.session_id`, provider
                  razorpay) and through it to our order. Never by amount, e-mail or anything the payer controls.
5. VALIDATED      before any money state changes: currency INR, amount == the order total we asked the gateway for, payment
                  status captured (payment.captured) / order paid (order.paid), the attempt's order exists.
6. APPLIED        only through `shop_routes._process_paid_order` - the single idempotent state machine also used by the
                  client verify and the UPI / manual confirmations (order claim by compare-and-set, vendor sales posted once
                  per (order, vendor) by unique ledger keys, commission plan frozen once per order).

Outcomes: processed · ignored (an event type we do not act on, or a non-final status) · unmatched (unknown payment attempt or
order) · rejected (amount / currency / reference mismatch) · failed (an error while applying; retried by the provider, or by a
finance admin through /api/admin/payment-events/{id}/retry). `payment.failed` is recorded on the payment attempt's history and
never changes the order. Nothing here creates payout eligibility: that still needs delivery + the return window.
"""
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pymongo.errors import DuplicateKeyError

from core import db, log_audit, now_iso, require_admin
from money import paise_of

logger = logging.getLogger("homegenies")
router = APIRouter(prefix="/api", tags=["payment-events"])
STALE_SECONDS = 120
ACT_ON = ("payment.captured", "order.paid", "payment.failed")
FINANCE_ROLES = ("super_admin", "accounts_admin")


class Malformed(Exception):
    pass


def verify_signature(raw: bytes, signature: str, secret: str) -> bool:
    if not signature:
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def normalise(event: dict, header_event_id: str = "") -> dict:
    """The only fields we keep. No card, contact or e-mail data is stored."""
    if not isinstance(event, dict):
        raise Malformed("payload is not an object")
    etype = event.get("event")
    eid = header_event_id or event.get("id") or ""
    if not etype or not eid:
        raise Malformed("missing event id or type")
    payload = event.get("payload") or {}
    pay = ((payload.get("payment") or {}).get("entity")) or {}
    order = ((payload.get("order") or {}).get("entity")) or {}
    amount = pay.get("amount") if pay else order.get("amount_paid", order.get("amount"))
    return {"event_id": str(eid)[:120], "type": str(etype)[:60], "gateway_order_id": pay.get("order_id") or order.get("id"),
            "payment_id": pay.get("id"), "amount_paise": amount if isinstance(amount, int) and not isinstance(amount, bool) else None,
            "currency": pay.get("currency") or order.get("currency"),
            "gateway_status": pay.get("status") if pay else order.get("status"),
            "error_code": (pay.get("error_code") or None) if pay else None}


async def claim(ev: dict) -> bool:
    """True when THIS delivery should process the event (exactly one concurrent delivery wins)."""
    now = datetime.now(timezone.utc)
    try:
        await db.webhook_events.insert_one({**ev, "provider": "razorpay", "status": "processing", "claimed_at": now.isoformat(),
                                            "created_at": now.isoformat(), "attempts": []})
        return True
    except DuplicateKeyError:
        pass
    cur = await db.webhook_events.find_one({"event_id": ev["event_id"]}, {"_id": 0})
    status, claimed_at = cur.get("status"), cur.get("claimed_at") or ""
    if status in (None, "processed", "ignored", "unmatched", "rejected", "duplicate"):
        return False                                   # final outcomes are never re-applied by a repeated delivery
    if status == "processing" and claimed_at >= (now - timedelta(seconds=STALE_SECONDS)).isoformat():
        return False                                   # another delivery is processing it right now
    r = await db.webhook_events.update_one({"event_id": ev["event_id"], "status": status, "claimed_at": cur.get("claimed_at")},
                                           {"$set": {"status": "processing", "claimed_at": now.isoformat()}})
    return r.modified_count == 1


async def _finish(event_id: str, status: str, reason: str = "", **extra) -> dict:
    now = now_iso()
    await db.webhook_events.update_one({"event_id": event_id}, {"$set": {"status": status, "reason": reason, "updated_at": now,
                                                                       **({"processed_at": now} if status == "processed" else {}), **extra},
                                                              "$push": {"attempts": {"at": now, "outcome": status, "reason": reason}}})
    if status in ("rejected", "unmatched", "failed"):
        logger.warning("payment event %s %s: %s", event_id, status, reason)
    return {"status": status, "reason": reason}


async def apply(ev: dict, request: Optional[Request] = None) -> dict:
    """Validate and apply one claimed event. Returns the outcome (also stored on the event)."""
    from shop_routes import _process_paid_order
    eid = ev["event_id"]
    if ev["type"] not in ACT_ON:
        return await _finish(eid, "ignored", f"event type {ev['type']} is not acted on")
    gid = ev.get("gateway_order_id")
    tx = await db.payment_transactions.find_one({"session_id": gid, "provider": "razorpay"}, {"_id": 0}) if gid else None
    if not tx:
        return await _finish(eid, "unmatched", "unknown payment attempt (no Razorpay order created by HOME GENIES has this id)")
    order = await db.orders.find_one({"id": tx["order_id"]}, {"_id": 0})
    link = {"order_id": tx["order_id"], "session_id": gid}
    if not order:
        return await _finish(eid, "unmatched", "the payment attempt points at an order that does not exist", **link)
    if order.get("razorpay_order_id") not in (None, gid) and order.get("paid_session_id") != gid:
        # the order has since been sent to the gateway again; this attempt is still OURS and is checked like any other
        logger.info("event %s for an earlier attempt %s of order %s", eid, gid, order["id"])
    if ev["type"] == "payment.failed":
        await db.payment_transactions.update_one({"session_id": gid}, {"$push": {"gateway_events": {
            "at": now_iso(), "event_id": eid, "type": "payment.failed", "payment_id": ev.get("payment_id"), "error_code": ev.get("error_code")}},
            "$set": {"last_failure_at": now_iso(), "updated_at": now_iso()}})
        return await _finish(eid, "processed", "payment attempt failed at the gateway; the order is unchanged", **link)
    final_status = "captured" if ev["type"] == "payment.captured" else "paid"
    if ev.get("gateway_status") != final_status:
        return await _finish(eid, "ignored", f"status {ev.get('gateway_status')!r} is not a completed payment", **link)
    if (ev.get("currency") or "") != "INR":
        return await _finish(eid, "rejected", f"currency {ev.get('currency')!r} does not match INR", **link)
    expected = paise_of(order, "total_paise", "total")
    if ev.get("amount_paise") != expected:
        return await _finish(eid, "rejected", f"amount {ev.get('amount_paise')} paise does not match the order total {expected} paise", **link)
    if ev.get("payment_id"):
        await db.payment_transactions.update_one({"session_id": gid}, {"$set": {"razorpay_payment_id": ev["payment_id"], "updated_at": now_iso()}})
    await _process_paid_order(gid, request)
    fresh = await db.orders.find_one({"id": order["id"]}, {"_id": 0})
    applied = (fresh or {}).get("paid_session_id") == gid
    if applied:
        await complete_paid_order(fresh, request)
    dup = any(d.get("session_id") == gid for d in (fresh or {}).get("duplicate_payments") or [])
    note = "applied to the order" if applied else ("captured money not applied: recorded as a duplicate payment to refund" if dup
                                                   else f"order is {(fresh or {}).get('payment_status')}; handled by the order's own rules")
    return await _finish(eid, "processed", note, **link, applied=applied)


async def complete_paid_order(order: dict, request: Optional[Request] = None) -> None:
    """Finish the money effects of a payment that THIS attempt applied, so a retry completes what a crash interrupted.
    Both steps are idempotent: the vendor sale per (order, vendor) has a unique ledger key, and the commission plan is
    frozen once per order. An order that must be refunded (late / cancelled) earns nothing here."""
    if order.get("needs_refund") or order.get("status") == "cancelled" or order.get("payment_status") not in ("paid", "partially_refunded"):
        return
    from ledger import post_order_collected
    from commission import distribute_sale_commissions
    await post_order_collected(order)
    buyer = await db.users.find_one({"id": order.get("user_id")}, {"_id": 0}) or {}
    await distribute_sale_commissions(order, buyer, request)


@router.post("/webhook/razorpay")
async def razorpay_webhook(request: Request):
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Razorpay-Signature", ""), secret):
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        ev = normalise(json.loads(raw.decode()), request.headers.get("X-Razorpay-Event-Id", ""))
    except (ValueError, Malformed):
        raise HTTPException(status_code=400, detail="Invalid payload")
    if not await claim(ev):
        return {"status": "duplicate"}
    try:
        out = await apply(ev, request)
    except Exception as e:                                       # partial failure: recorded; the provider (or finance) retries
        await _finish(ev["event_id"], "failed", f"{type(e).__name__}: {str(e)[:200]}")
        raise HTTPException(status_code=500, detail="Event could not be processed; it will be retried.")
    return {"status": out["status"]}


# ------------------------------------------------------------------ admin: inspect and retry
def _finance(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Finance access required.")
    return admin


@router.get("/admin/payment-events")
async def list_events(status: Optional[str] = None, q: Optional[str] = None, page: int = 1, page_size: int = 25,
                      admin: dict = Depends(_finance)):
    from pagination import clamp_page, page_meta
    flt: dict = {}
    if status:
        flt["status"] = status
    if q:
        q = q.strip()[:120]
        flt["$or"] = [{"event_id": q}, {"session_id": q}, {"gateway_order_id": q}, {"payment_id": q}, {"order_id": q}]
    page, page_size = clamp_page(page, page_size)
    total = await db.webhook_events.count_documents(flt)
    rows = await db.webhook_events.find(flt, {"_id": 0}).sort([("created_at", -1), ("event_id", 1)]).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    counts = {s: await db.webhook_events.count_documents({"status": s}) for s in ("failed", "rejected", "unmatched", "processing")}
    return {"items": rows, **page_meta(total, page, page_size), "attention": counts}


@router.post("/admin/payment-events/{event_id}/retry")
async def retry_event(event_id: str, request: Request, admin: dict = Depends(_finance)):
    """Re-run a FAILED (or stuck processing) event from its stored summary. Processed / rejected / unmatched / ignored events are
    final and are refused: re-running them could never be correct without new information."""
    ev = await db.webhook_events.find_one({"event_id": event_id}, {"_id": 0})
    if not ev:
        raise HTTPException(status_code=404, detail="Event not found.")
    if ev.get("status") not in ("failed", "processing") or not ev.get("type"):
        raise HTTPException(status_code=409, detail=f"This event is {ev.get('status')}; only failed or stuck events can be retried.")
    summary = {k: ev.get(k) for k in ("event_id", "type", "gateway_order_id", "payment_id", "amount_paise", "currency", "gateway_status", "error_code")}
    if not await claim(summary):
        raise HTTPException(status_code=409, detail="This event is being processed right now.")
    try:
        out = await apply(summary, request)
    except Exception as e:
        await _finish(event_id, "failed", f"{type(e).__name__}: {str(e)[:200]}")
        raise HTTPException(status_code=500, detail="The retry failed again; see the event's attempts.")
    await log_audit(admin, "payment_event_retried", "payment_event", event_id, new_value=out, request=request)
    return {**out, "event": await db.webhook_events.find_one({"event_id": event_id}, {"_id": 0})}

