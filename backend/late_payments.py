"""Programme 03-B (P03-A02): crash-safe handling of a payment that lands on an order that is already cancelled.

Every payment path (Stripe webhook / status poll, Razorpay webhook / verify, UPI confirmation, manual payment) applies money only
through `shop_routes._process_paid_order`. When that claim lands on a cancelled order it now writes, IN THE SAME conditional
update as `payment_status: paid`, a durable marker:

    late_payment_due = {session_id, revivable, at, lease_until, attempts}

The marker means "money was captured for a cancelled order and its outcome is not decided yet". The outcome is the existing,
unchanged rule (`stock.handle_late_payment`): an order cancelled by the 15-minute payment expiry is restored if its stock can be
taken back; anything else (or no stock) is flagged `needs_refund`, which the refund-obligation sweep turns into exactly one
`late:<order>` refund case. Only after that outcome is durable is the marker removed.

Crash safety: a crash anywhere after the claim leaves the marker; `repair_late_payments` (daily maintenance, before the completion
repair) finishes it. While the marker is present `order_completion.complete_paid_order` waits (it would otherwise skip the cancelled
order and clear `completion_due`, losing the sales / commission of an order that is about to be restored).

Concurrency: the marker carries a lease. The request that made the claim holds it from the claim; the repair (and a redelivery of the
same payment) takes it only after it has expired, with a conditional update. The lease is NOT relied on as a fence: if it expires
while its holder is still running, the steps underneath are fenced by state - the late release touches only the expiry's own stock
generation, a revival is a keyed stock transaction and restores only a still-cancelled order, `_flag_refund` marks only a cancelled
order, a started revival is finished rather than re-decided, and the refund case has a unique source key (review P03B-R01/R02).
Nothing here moves money or calls a payment provider.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from core import db, now_iso

logger = logging.getLogger("homegenies")
LEASE_SECONDS = 120


def _fault(point: str, **ctx):
    """Crash-injection hook for tests (no-op in the application)."""
    return None


def lease_until(seconds: int = LEASE_SECONDS) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def marker(session_id: str, revivable: bool) -> dict:
    """The marker written with the paid claim on a cancelled order (the claiming request holds the lease)."""
    return {"session_id": session_id, "revivable": bool(revivable), "at": now_iso(), "lease_until": lease_until(), "attempts": 0}


async def resolve_late_payment(order_id: str, session_id: str, own_lease: bool = False) -> Optional[bool]:
    """Decide the late payment's outcome once and remove the marker. Returns True when the order was restored (it continues as a
    normal paid order), False when a refund is owed, None when another actor holds the lease (or the marker is gone)."""
    from stock import handle_late_payment
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    m = (o or {}).get("late_payment_due")
    if not o or not m or m.get("session_id") != session_id:
        return None
    if not own_lease:
        now = now_iso()
        took = await db.orders.update_one({"id": order_id, "late_payment_due.session_id": session_id,
                                           "late_payment_due.lease_until": {"$lt": now}},
                                          {"$set": {"late_payment_due.lease_until": lease_until(), "late_payment_due.last_attempt_at": now},
                                           "$inc": {"late_payment_due.attempts": 1}})
        if took.modified_count != 1:
            return None
        o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    _fault("late_before_decision", order_id=order_id)
    if o.get("status") == "cancelled" and not o.get("needs_refund"):
        revived = await _decide(o, bool(m.get("revivable")), handle_late_payment)
    else:
        revived = o.get("status") != "cancelled" and not o.get("needs_refund")    # decided by an earlier, interrupted attempt
    _fault("late_before_marker_clear", order_id=order_id)
    await db.orders.update_one({"id": order_id, "late_payment_due.session_id": session_id}, {"$unset": {"late_payment_due": ""}})
    return revived


async def _decide(o: dict, revivable: bool, handle_late_payment) -> bool:
    """The unchanged late-payment rule, made safe to run again after an interruption (review P03B-R01 / R03):
    - a revival that already STARTED (its keyed stock transaction exists) is finished by the stock engine's own recovery -
      never decided afresh (re-running the release + re-reserve would hand back the stock the revival took);
    - an order that already has a refund recorded or a refund case is never restored: the payment is owed back
      (fully refunded: nothing more is owed, so nothing is flagged);
    - otherwise the decision runs exactly as the paying request would have run it."""
    from stock import _flag_refund, _recover_one_txn
    oid = o["id"]
    t = await db.stock_txns.find_one({"key": f"revive:{oid}:{o.get('revive_count', 0)}"}, {"_id": 0})
    if t:
        await _recover_one_txn(t)                    # committed -> finish_revival; otherwise refund owed; idempotent
        cur = await db.orders.find_one({"id": oid}, {"_id": 0, "status": 1, "needs_refund": 1}) or {}
        return cur.get("status") != "cancelled" and not cur.get("needs_refund")
    if o.get("payment_status") == "refunded":
        return False
    refund_seen = int(o.get("refunded_paise") or 0) > 0 or o.get("payment_status") != "paid" \
        or bool(await db.refund_cases.find_one({"order_id": oid}, {"_id": 1}))
    if refund_seen:
        await _flag_refund(oid, "paid_after_cancellation_refund_already_recorded")
        return False
    return await handle_late_payment(o, allow_revive=revivable)


async def repair_late_payments(dry_run: bool = False, max_seconds: Optional[float] = None, batch: int = 200) -> dict:
    """Repair sweep: every late payment whose lease has expired (the request that claimed it was interrupted). Drives the same
    decision as the request would have, then finishes the order's completion (restored order: sales / commission; refund owed:
    nothing earns). Keyset, checkpointed, per-record isolation and failure records (`sweeps.run_sweep`); dry run writes nothing."""
    from sweeps import run_sweep
    from order_completion import complete_paid_order

    async def handle(o, dry):
        m = o.get("late_payment_due") or {}
        if dry:
            return "eligible"
        revived = await resolve_late_payment(o["id"], m.get("session_id"), own_lease=False)
        if revived is None:
            return "skipped"
        await complete_paid_order(o["id"], None, source="late_payment_repair")
        return "updated"
    return await run_sweep("late_payment_repair", "orders", {"late_payment_due.lease_until": {"$lt": now_iso()}}, handle,
                           dry_run=dry_run, max_seconds=max_seconds, batch=batch,
                           projection={"_id": 0, "id": 1, "late_payment_due": 1})
