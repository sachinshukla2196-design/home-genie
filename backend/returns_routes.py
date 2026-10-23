"""Customer cancellation, returns & replacements, and the staged refund workflow.

POLICY (configurable, admin-owned): the return window (7 days is only a PROVISIONAL default) and excluded categories live in
`returns_policy`; nothing here hard-codes a legal rule.

RULES KEPT FROM THE APPROVED DESIGN
- A confirmed cancellation before dispatch restores eligible stock once (via the stock engine's durable intents).
- Shipped / delivered goods are never restocked by a cancellation. Returned goods go back into stock ONLY after the vendor has
  physically received and inspected them, only the resellable quantity, exactly once, and never for damaged goods.
- A vendor cannot arbitrarily reject an eligible claim: they may approve it or CONTEST it, and an admin makes the final call.
- A refund is recorded in the books only after an authorised confirmation: provider-verified, or a documented manual
  reconciliation (reference + note). Refund cases move awaiting_review -> initiated -> confirmed (or failed) -> resolved.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

import ledger as L
from core import db, now_iso, new_id, get_current_user, require_admin, log_audit, create_notification, next_sequence
from money import to_paise, paise_to_float, paise_of, mul_ratio
from pagination import clamp_page, page_meta
from stock import PRE_DISPATCH, intent, run_intents, restock_returned_lines, reserve_replacement
from validators import safe_image_refs
from vendor_routes import require_approved_vendor

router = APIRouter(prefix="/api", tags=["returns"])

POLICY_ID = "returns_policy"
DEFAULT_POLICY = {"id": POLICY_ID, "enabled": True, "window_days": 7, "excluded_categories": [], "version": 0,
                  "provisional": True, "notes": "7 days is a provisional default pending legal/commercial approval.",
                  "updated_by": None, "updated_at": None}
POLICY_ROLES = {"super_admin", "admin"}
FINANCE_ROLES = {"super_admin", "accounts_admin"}
ACTIVE_RETURN_STATES = {"requested", "contested", "approved", "in_transit", "received", "inspected", "replacement_due"}


async def get_returns_policy() -> dict:
    return await db.returns_policy.find_one({"id": POLICY_ID}, {"_id": 0}) or dict(DEFAULT_POLICY)


def _view(d: dict) -> dict:
    out = dict(d)
    for k, v in d.items():
        if k.endswith("_paise") and isinstance(v, int):
            out[k[:-6]] = paise_to_float(v)
    return out


def _delivered_at(f: dict) -> Optional[str]:
    return next((e["at"] for e in reversed(f.get("events", [])) if e.get("status") == "delivered"), None)


async def _notify_vendor(vendor_id: str, title: str, msg: str, meta: dict = None):
    v = await db.vendors.find_one({"id": vendor_id}, {"_id": 0, "user_id": 1})
    if v:
        await create_notification(v["user_id"], "vendor", title, msg, meta=meta)


async def _notify_admins(title: str, msg: str, meta: dict = None, roles=("super_admin", "accounts_admin")):
    for a in await db.users.find({"role": {"$in": list(roles)}}, {"_id": 0, "id": 1}).to_list(30):
        await create_notification(a["id"], "order", title, msg, meta=meta)


# ================================================================== policy (admin)
class PolicyIn(BaseModel):
    enabled: bool = True
    window_days: int = Field(default=7, ge=0, le=90)
    excluded_categories: List[str] = []
    notes: str = Field(default="", max_length=500)


@router.get("/returns/policy")
async def public_policy(user: dict = Depends(get_current_user)):
    p = await get_returns_policy()
    return {k: p[k] for k in ("enabled", "window_days", "excluded_categories", "provisional", "notes")}


@router.put("/admin/returns/policy")
async def set_policy(body: PolicyIn, request: Request, admin: dict = Depends(require_admin)):
    if admin.get("role") not in POLICY_ROLES:
        raise HTTPException(status_code=403, detail="Only a super admin can change the returns policy.")
    old = await get_returns_policy()
    new = {**old, **body.model_dump(), "provisional": False, "version": old.get("version", 0) + 1, "updated_by": admin["id"], "updated_at": now_iso()}
    await db.returns_policy.update_one({"id": POLICY_ID}, {"$set": new}, upsert=True)
    await log_audit(admin, "returns_policy_changed", "returns_policy", POLICY_ID, old_value={k: old.get(k) for k in ("enabled", "window_days")},
                    new_value={k: new[k] for k in ("enabled", "window_days", "excluded_categories")}, request=request)
    return new


# ================================================================== refund cases
async def open_refund_case(order: dict, kind: str, amount_paise: int, reason: str, source_key: str, *, return_case_id: str = None,
                           vendor_id: str = None):
    """Open (once per source_key) a refund case in `awaiting_review`. Returns (case, created)."""
    now = now_iso()
    case = {"id": new_id(), "number": await next_sequence("refund", "RFD", 6), "source_key": source_key, "order_id": order["id"],
            "order_number": order.get("order_number"), "user_id": order["user_id"], "kind": kind, "amount_paise": amount_paise,
            "currency": "INR", "status": "awaiting_review", "reason": reason, "return_case_id": return_case_id, "vendor_id": vendor_id,
            "method": "", "reference": "", "events": [{"status": "awaiting_review", "at": now, "by": "system", "note": reason}],
            "created_at": now, "updated_at": now}
    try:
        await db.refund_cases.insert_one(dict(case))
    except DuplicateKeyError:
        return await db.refund_cases.find_one({"source_key": source_key}, {"_id": 0}), False
    await _notify_admins("Refund to review", f"Order {order.get('order_number')}: refund case {case['number']} ({kind}) is waiting for review.",
                         meta={"refund_case": case["id"], "order_id": order["id"]})
    return case, True


async def refundable_paise(order: dict) -> int:
    return paise_of(order, "total_paise", "total") - paise_of(order, "refunded_paise", "refunded_amount")


async def ensure_cases_for_flagged_orders(limit: int = 200):
    """Legacy/late-payment orders flagged `needs_refund` always have a refund case (created once, lazily)."""
    async for o in db.orders.find({"needs_refund": True, "payment_status": {"$in": ["paid", "partially_refunded"]}}, {"_id": 0}).limit(limit):
        if not await db.refund_cases.find_one({"source_key": f"late:{o['id']}"}, {"_id": 1}):
            await open_refund_case(o, "late_payment", await refundable_paise(o), o.get("needs_refund_reason") or "paid_after_cancellation", f"late:{o['id']}")


async def confirm_open_cases_for_order(order_id: str, refund: dict, admin_id: str):
    """The legacy one-step Refund action (reference mandatory) also closes any open case it satisfies."""
    async for c in db.refund_cases.find({"order_id": order_id, "status": {"$in": ["awaiting_review", "initiated"]}}, {"_id": 0}):
        if refund["amount_paise"] >= c["amount_paise"] or refund.get("closes_order"):
            await db.refund_cases.update_one(
                {"id": c["id"], "status": c["status"]},
                {"$set": {"status": "confirmed", "confirmation_type": "manual_reconciliation", "reference": refund.get("reference", ""),
                          "refund_event": refund["id"], "confirmed_by": admin_id, "updated_at": now_iso()},
                 "$push": {"events": {"status": "confirmed", "at": now_iso(), "by": admin_id, "note": "Recorded via the Refund action"}}})
            if c.get("return_case_id"):
                await _return_refunded(c["return_case_id"])


async def _return_refunded(return_case_id: str):
    await db.return_cases.update_one({"id": return_case_id, "status": {"$in": ["inspected", "refund_pending"]}},
                                     {"$set": {"status": "refunded", "updated_at": now_iso()},
                                      "$push": {"events": {"status": "refunded", "at": now_iso(), "by": "system", "note": "Refund confirmed"}}})


@router.get("/admin/refund-cases")
async def list_refund_cases(state: Optional[str] = None, page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    await ensure_cases_for_flagged_orders()
    groups = {"open": ["awaiting_review", "initiated", "failed"], "closed": ["confirmed", "resolved"]}
    if state and state not in groups and state not in ("awaiting_review", "initiated", "confirmed", "failed", "resolved"):
        raise HTTPException(status_code=400, detail="Unknown state.")
    q = {"status": {"$in": groups[state]}} if state in groups else ({"status": state} if state else {})
    total = await db.refund_cases.count_documents(q)
    rows = await db.refund_cases.find(q, {"_id": 0}).sort("created_at", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    counts = {s: await db.refund_cases.count_documents({"status": s}) for s in ("awaiting_review", "initiated", "confirmed", "failed", "resolved")}
    return {"items": [_view(r) for r in rows], "counts": counts, **page_meta(total, page, page_size)}


class RefundAction(BaseModel):
    action: str                         # initiate | confirm | fail | retry | resolve
    method: str = Field(default="", max_length=40)
    reference: str = Field(default="", max_length=120)
    confirmation_type: str = ""         # provider | manual_reconciliation
    note: str = Field(default="", max_length=300)
    amount: Optional[float] = None      # rupees; may lower (never raise) the case amount when initiating


REFUND_FLOW = {"awaiting_review": {"initiated", "resolved"}, "initiated": {"confirmed", "failed", "resolved"}, "failed": {"initiated", "resolved"},
               "confirmed": {"resolved"}, "resolved": set()}


async def verify_provider_refund(order: dict, reference: str):
    """Hook for payment-provider verification. Returns (verified, detail). No provider refund API is wired up yet, so this
    never claims verification it cannot perform."""
    return False, "Provider refund verification is not configured; use manual reconciliation with a reference and note."


@router.post("/admin/refund-cases/{case_id}/action")
async def refund_case_action(case_id: str, body: RefundAction, request: Request, admin: dict = Depends(require_admin)):
    case = await db.refund_cases.find_one({"id": case_id}, {"_id": 0})
    if not case:
        raise HTTPException(status_code=404, detail="Refund case not found.")
    target = {"initiate": "initiated", "retry": "initiated", "confirm": "confirmed", "fail": "failed", "resolve": "resolved"}.get(body.action)
    if not target or target not in REFUND_FLOW[case["status"]]:
        raise HTTPException(status_code=400, detail=f"Cannot {body.action} a refund case that is '{case['status']}'.")
    note = body.note.strip()
    now = now_iso()
    sets = {"status": target, "updated_at": now}
    if target == "initiated":
        order = await db.orders.find_one({"id": case["order_id"]}, {"_id": 0})
        room = await refundable_paise(order)
        amt = to_paise(body.amount) if body.amount is not None else case["amount_paise"]
        if amt <= 0 or amt > min(case["amount_paise"], room):
            raise HTTPException(status_code=400, detail="Amount must be between 0.01 and the original case amount / refundable balance.")
        sets.update({"amount_paise": amt, "method": (body.method or "manual").strip(), "initiated_by": admin["id"]})
    elif target == "failed":
        if len(note) < 5:
            raise HTTPException(status_code=400, detail="A reason is required.")
    elif target == "resolved":
        if len(note) < 5:
            raise HTTPException(status_code=400, detail="A closing note is required.")
        sets.update({"resolved_by": admin["id"], "outcome": "refunded" if case["status"] == "confirmed" else "no_refund"})
    elif target == "confirmed":
        if admin.get("role") not in FINANCE_ROLES:
            raise HTTPException(status_code=403, detail="Finance access required to confirm a refund.")
        ref = body.reference.strip()
        if len(ref) < 3:
            raise HTTPException(status_code=400, detail="The refund reference (UTR / provider refund id) is required.")
        if body.confirmation_type == "provider":
            order = await db.orders.find_one({"id": case["order_id"]}, {"_id": 0})
            ok, detail = await verify_provider_refund(order, ref)
            if not ok:
                raise HTTPException(status_code=409, detail=detail)
        elif body.confirmation_type == "manual_reconciliation":
            if len(note) < 10:
                raise HTTPException(status_code=400, detail="Manual reconciliation needs a note (10+ characters) explaining how the payment return was verified.")
        else:
            raise HTTPException(status_code=400, detail="confirmation_type must be 'provider' or 'manual_reconciliation'.")
        import shop_routes
        res = await shop_routes.reverse_order_financials(case["order_id"], admin, request, refund_amount=paise_to_float(case["amount_paise"]),
                                                         reference=ref, reason=f"{case['number']}: {note or case['kind']}",
                                                         case_id=case["id"], vendor_id=case.get("vendor_id"))
        if res.get("duplicate") and not await db.order_refunds.find_one({"id": f"{case['order_id']}:refund:{ref}", "case_id": case["id"]}, {"_id": 1}):
            raise HTTPException(status_code=409, detail="This reference was already used for a different refund on this order.")
        if res.get("conflict"):
            raise HTTPException(status_code=409, detail="The order was just updated. Try again.")
        sets.update({"reference": ref, "confirmation_type": body.confirmation_type, "confirmed_by": admin["id"],
                     "refund_event": f"{case['order_id']}:refund:{ref}", "amount_refunded_paise": to_paise(res["refund_amount"]) if not res.get("duplicate") else case["amount_paise"]})
    claim = await db.refund_cases.update_one({"id": case_id, "status": case["status"]},
                                             {"$set": sets, "$push": {"events": {"status": target, "at": now, "by": admin["id"], "note": note or body.reference}}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="This refund case was just updated. Refresh and try again.")
    if target == "confirmed":
        if case.get("return_case_id"):
            await _return_refunded(case["return_case_id"])
        await create_notification(case["user_id"], "order", "Refund processed",
                                  f"Your refund for order {case['order_number']} was confirmed (ref {body.reference.strip()}).", meta={"order_id": case["order_id"]})
    elif target == "failed":
        await create_notification(case["user_id"], "order", "Refund delayed", f"We could not complete the refund for order {case['order_number']} yet. We will retry.")
    await log_audit(admin, f"refund_case_{body.action}", "refund_case", case_id, old_value={"status": case["status"]}, new_value={"status": target}, request=request)
    return _view(await db.refund_cases.find_one({"id": case_id}, {"_id": 0}))


# ================================================================== customer cancellation
class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=200)


@router.post("/orders/{order_id}/cancel")
async def customer_cancel(order_id: str, body: CancelIn, request: Request, user: dict = Depends(get_current_user)):
    """Customer cancels their own order. Untouched orders (every vendor group still 'new') are cancelled at once; if a vendor
    already accepted/packed it, a cancellation REQUEST is raised for the vendor/admin to confirm. Dispatched goods cannot be
    cancelled (use a return after delivery)."""
    order = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="This order is already cancelled.")
    if order.get("payment_status") in ("refunded", "partially_refunded", "cod_discrepancy") or order.get("needs_refund"):
        raise HTTPException(status_code=409, detail="Please contact support about this order.")
    fs = [f.get("status") for f in order.get("fulfilments", [])]
    if any(s not in PRE_DISPATCH for s in fs) or (not order.get("fulfilments") and order.get("status") in ("shipped", "delivered")) \
            or order.get("status") in ("shipped", "delivered"):
        raise HTTPException(status_code=409, detail="This order has already been dispatched. You can request a return after it is delivered.")
    now = now_iso()
    if all(s == "new" for s in fs):
        res = await db.orders.update_one(
            {"id": order_id, "status": {"$ne": "cancelled"}, "fulfilments": {"$not": {"$elemMatch": {"status": {"$nin": ["new"]}}}}},
            {"$set": {"status": "cancelled", "cancel_reason": "customer_cancelled", "cancel_note": body.reason.strip(), "cancelled_at": now,
                      "cancelled_by": user["id"], "updated_at": now},
             "$unset": {"cancel_requested": ""},
             "$push": {"restock_intents": intent("confirmed_cancel", user["id"], prev_status=order.get("status", ""))}})
        if res.modified_count != 1:
            raise HTTPException(status_code=409, detail="The order changed just now. Please refresh and try again.")
        await run_intents(order_id)
        fresh = await db.orders.find_one({"id": order_id}, {"_id": 0})
        case = None
        if fresh.get("payment_status") == "paid":
            for f in fresh.get("fulfilments", []):
                await L.post_sale_reversal(fresh, f["vendor_id"])
            amount = await refundable_paise(fresh)
            if amount > 0:
                case, _ = await open_refund_case(fresh, "cancellation", amount, "Customer cancelled a paid order", f"cancel:{order_id}")
        for f in fresh.get("fulfilments", []):
            await _notify_vendor(f["vendor_id"], "Order cancelled by customer", f"Order {fresh.get('order_number')} was cancelled before you accepted it.", {"order_id": order_id})
        await log_audit(user, "order_cancelled_by_customer", "order", order_id, new_value={"reason": body.reason}, request=request)
        return {"order_id": order_id, "outcome": "cancelled", "refund_case": case["number"] if case else None}
    flag = await db.orders.update_one({"id": order_id, "cancel_requested": {"$exists": False}},
                                      {"$set": {"cancel_requested": {"at": now, "by": user["id"], "reason": body.reason.strip()}, "updated_at": now}})
    if flag.modified_count == 1:
        for f in order.get("fulfilments", []):
            await _notify_vendor(f["vendor_id"], "Cancellation requested", f"The customer asked to cancel order {order.get('order_number')}. "
                                 "If you have not dispatched it, please cancel your part with a reason.", {"order_id": order_id})
        await _notify_admins("Cancellation requested", f"Customer asked to cancel order {order.get('order_number')}.", {"order_id": order_id}, roles=("super_admin", "admin"))
        await log_audit(user, "order_cancel_requested", "order", order_id, new_value={"reason": body.reason}, request=request)
    return {"order_id": order_id, "outcome": "requested", "refund_case": None}


# ================================================================== returns & replacements
class ReturnItemIn(BaseModel):
    product_id: str
    variant_sku: Optional[str] = None
    quantity: int = Field(ge=1, le=50)


class ReturnIn(BaseModel):
    kind: str = "return"                # return | replacement
    items: List[ReturnItemIn] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=5, max_length=300)
    photos: List[str] = []

    @field_validator("photos")
    @classmethod
    def _photos(cls, v):
        return safe_image_refs(v, 5)


def _suggested_refund(order: dict, lines: list) -> int:
    """Value of the returned lines plus their share of the order's tax. Delivery/COD fees are not refunded. Admin can lower it."""
    sub = paise_of(order, "subtotal_paise", "subtotal") or 1
    gst = paise_of(order, "gst_paise", "gst_amount")
    total = 0
    for ln in lines:
        value = ln["price_paise"] * ln["quantity"]
        total += value + mul_ratio(gst, value, sub)
    return total


@router.post("/orders/{order_id}/returns")
async def request_return(order_id: str, body: ReturnIn, request: Request, user: dict = Depends(get_current_user)):
    if body.kind not in ("return", "replacement"):
        raise HTTPException(status_code=400, detail="kind must be 'return' or 'replacement'.")
    policy = await get_returns_policy()
    if not policy["enabled"]:
        raise HTTPException(status_code=400, detail="Returns are not available right now.")
    order = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if order.get("needs_refund") or order.get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="This order cannot be returned.")
    now = datetime.now(timezone.utc)
    by_vendor = {}
    for it in body.items:
        idx = next((i for i, li in enumerate(order.get("items", [])) if li["product_id"] == it.product_id
                    and (not it.variant_sku or li.get("variant_sku") == it.variant_sku)), None)
        if idx is None:
            raise HTTPException(status_code=400, detail="That product is not part of this order.")
        li = order["items"][idx]
        vid = li.get("vendor_id")
        if not vid:
            raise HTTPException(status_code=400, detail="Please contact support to return this item.")
        f = next((x for x in order["fulfilments"] if x["vendor_id"] == vid), None)
        if not f or f.get("status") != "delivered":
            raise HTTPException(status_code=400, detail="Only delivered items can be returned.")
        d = _delivered_at(f)
        try:
            age_days = (now - datetime.fromisoformat(d)).total_seconds() / 86400
        except Exception:
            raise HTTPException(status_code=400, detail="Delivery date is missing; please contact support.")
        if age_days > policy["window_days"]:
            raise HTTPException(status_code=400, detail=f"The return window ({policy['window_days']} days after delivery) has closed.")
        prod = await db.products.find_one({"id": li["product_id"]}, {"_id": 0, "returnable": 1, "category": 1})
        if prod and (prod.get("returnable") is False or prod.get("category") in policy.get("excluded_categories", [])):
            raise HTTPException(status_code=400, detail=f"'{li['name']}' is not eligible for return.")
        used = 0
        async for rc in db.return_cases.find({"order_id": order_id, "status": {"$in": list(ACTIVE_RETURN_STATES) + ["refunded", "closed"]}}, {"_id": 0, "lines": 1}):
            used += sum(x["quantity"] for x in rc["lines"] if x["order_line"] == idx)
        if it.quantity > li["quantity"] - used:
            raise HTTPException(status_code=400, detail=f"You can return at most {li['quantity'] - used} of '{li['name']}'.")
        by_vendor.setdefault(vid, []).append({"order_line": idx, "product_id": li["product_id"], "variant_sku": li.get("variant_sku"), "name": li["name"],
                                              "sku": li.get("sku"), "quantity": it.quantity, "price_paise": paise_of(li, "price_paise", "price")})
    cases = []
    for vid, lines in by_vendor.items():
        vname = next(f.get("vendor_name") for f in order["fulfilments"] if f["vendor_id"] == vid)
        ts = now_iso()
        rc = {"id": new_id(), "number": await next_sequence("return", "RTN", 6), "order_id": order_id, "order_number": order.get("order_number"),
              "user_id": user["id"], "vendor_id": vid, "vendor_name": vname, "kind": body.kind, "status": "requested", "lines": lines,
              "reason": body.reason.strip(), "photos": body.photos, "policy_version": policy.get("version", 0),
              "suggested_refund_paise": _suggested_refund(order, lines) if body.kind == "return" else 0,
              "events": [{"status": "requested", "at": ts, "by": user["id"], "note": body.reason.strip()}], "created_at": ts, "updated_at": ts}
        await db.return_cases.insert_one(dict(rc))
        await _notify_vendor(vid, "Return requested", f"{body.kind.title()} requested for order {order.get('order_number')}: {body.reason.strip()}", {"return_case": rc["id"]})
        await log_audit(user, "return_requested", "return_case", rc["id"], new_value={"order": order_id, "kind": body.kind}, request=request)
        rc.pop("_id", None)
        cases.append(_view(rc))
    return {"cases": cases}


@router.get("/returns")
async def my_returns(user: dict = Depends(get_current_user)):
    return [_view(r) for r in await db.return_cases.find({"user_id": user["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)]


async def _own_return(user: dict, rid: str) -> dict:
    rc = await db.return_cases.find_one({"id": rid, "user_id": user["id"]}, {"_id": 0})
    if not rc:
        raise HTTPException(status_code=404, detail="Return not found.")
    return rc


class ShipBackIn(BaseModel):
    carrier: str = Field(default="", max_length=60)
    tracking_number: str = Field(default="", max_length=80)


async def _transition(rid: str, frm: set, to: str, actor: str, note: str = "", extra: dict = None) -> dict:
    """Atomic return-case state change: exactly one caller wins each transition."""
    now = now_iso()
    res = await db.return_cases.find_one_and_update(
        {"id": rid, "status": {"$in": list(frm)}},
        {"$set": {"status": to, "updated_at": now, **(extra or {})}, "$push": {"events": {"status": to, "at": now, "by": actor, "note": note}}},
        projection={"_id": 0}, return_document=True)
    if not res:
        raise HTTPException(status_code=409, detail="This return was just updated or is not in a state that allows that. Refresh and try again.")
    return res


@router.post("/returns/{rid}/ship")
async def customer_ship_back(rid: str, body: ShipBackIn, user: dict = Depends(get_current_user)):
    await _own_return(user, rid)
    rc = await _transition(rid, {"approved"}, "in_transit", user["id"], "Customer sent the goods back",
                           {"return_shipment": {"carrier": body.carrier.strip(), "tracking_number": body.tracking_number.strip(), "at": now_iso()}})
    await _notify_vendor(rc["vendor_id"], "Return on its way", f"Return {rc['number']} was sent back to you.", {"return_case": rid})
    return _view(rc)


@router.post("/returns/{rid}/cancel")
async def customer_cancel_return(rid: str, user: dict = Depends(get_current_user)):
    await _own_return(user, rid)
    return _view(await _transition(rid, {"requested", "contested", "approved"}, "cancelled", user["id"], "Customer withdrew the request"))


# ----------------------------------------------------------- vendor side
@router.get("/vendor/returns")
async def vendor_returns(status: Optional[str] = None, page: int = 1, page_size: int = 25, user: dict = Depends(require_approved_vendor)):
    page, page_size = clamp_page(page, page_size)
    q = {"vendor_id": user["_vendor"]["id"], **({"status": status} if status else {})}
    total = await db.return_cases.count_documents(q)
    rows = await db.return_cases.find(q, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    counts = {}
    async for r in db.return_cases.aggregate([{"$match": {"vendor_id": user["_vendor"]["id"]}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        counts[r["_id"]] = r["n"]
    return {"items": [_view(r) for r in rows], "counts": counts, **page_meta(total, page, page_size)}


async def _vendor_return(user: dict, rid: str) -> dict:
    rc = await db.return_cases.find_one({"id": rid, "vendor_id": user["_vendor"]["id"]}, {"_id": 0})
    if not rc:
        raise HTTPException(status_code=404, detail="Return not found.")
    return rc


@router.get("/vendor/returns/{rid}")
async def vendor_return_detail(rid: str, user: dict = Depends(require_approved_vendor)):
    rc = await _vendor_return(user, rid)
    o = await db.orders.find_one({"id": rc["order_id"]}, {"_id": 0, "address": 1})
    a = (o or {}).get("address") or {}
    return {**_view(rc), "ship_from": {k: a.get(k, "") for k in ("full_name", "city", "state", "pincode")}}


class VendorReturnAction(BaseModel):
    action: str                         # approve | contest | receive | replacement_dispatched
    note: str = Field(default="", max_length=300)
    carrier: str = Field(default="", max_length=60)
    tracking_number: str = Field(default="", max_length=80)


@router.post("/vendor/returns/{rid}/action")
async def vendor_return_action(rid: str, body: VendorReturnAction, request: Request, user: dict = Depends(require_approved_vendor)):
    rc = await _vendor_return(user, rid)
    note = body.note.strip()
    if body.action == "approve":
        out = await _transition(rid, {"requested"}, "approved", user["id"], note or "Approved by vendor")
        await create_notification(rc["user_id"], "order", "Return approved", f"Your return {rc['number']} was approved. Please send the goods back.", meta={"return_case": rid})
    elif body.action == "contest":
        if len(note) < 5:
            raise HTTPException(status_code=400, detail="Please explain why you are contesting (at least 5 characters). An admin will decide.")
        out = await _transition(rid, {"requested"}, "contested", user["id"], note)
        await _notify_admins("Return contested", f"Vendor contested return {rc['number']}: {note}", {"return_case": rid}, roles=("super_admin", "admin"))
    elif body.action == "receive":
        out = await _transition(rid, {"approved", "in_transit"}, "received", user["id"], note or "Goods physically received")
    elif body.action == "replacement_dispatched":
        if rc["kind"] != "replacement":
            raise HTTPException(status_code=400, detail="This is not a replacement request.")
        if not (body.carrier.strip() and body.tracking_number.strip()):
            raise HTTPException(status_code=400, detail="Carrier and tracking number are required.")
        if rc["status"] != "replacement_due":
            raise HTTPException(status_code=409, detail="The replacement is not due yet (inspect the returned goods first).")
        lines = [{"product_id": x["product_id"], "variant_sku": x.get("variant_sku"), "quantity": x["quantity"]} for x in rc["lines"]]
        if not await reserve_replacement(rid, rc["order_id"], lines, user["id"]):
            raise HTTPException(status_code=409, detail="Not enough stock to send the replacement.")
        out = await _transition(rid, {"replacement_due"}, "closed", user["id"], f"Replacement dispatched via {body.carrier.strip()} {body.tracking_number.strip()}",
                                {"replacement_shipment": {"carrier": body.carrier.strip(), "tracking_number": body.tracking_number.strip(), "at": now_iso()}})
        await create_notification(rc["user_id"], "order", "Replacement dispatched", f"Your replacement for {rc['number']} is on its way ({body.carrier.strip()} {body.tracking_number.strip()}).")
    else:
        raise HTTPException(status_code=400, detail="Unknown action.")
    await log_audit(user, f"return_{body.action}", "return_case", rid, new_value={"status": out["status"]}, request=request)
    return _view(out)


class LineInspection(BaseModel):
    index: int = Field(ge=0)
    outcome: str                        # resellable | damaged
    note: str = Field(default="", max_length=200)


class InspectionIn(BaseModel):
    lines: List[LineInspection] = Field(min_length=1)
    note: str = Field(min_length=5, max_length=300)


@router.post("/vendor/returns/{rid}/inspection")
async def vendor_return_inspection(rid: str, body: InspectionIn, request: Request, user: dict = Depends(require_approved_vendor)):
    """Goods are restocked only after the vendor confirms receipt AND records an inspection, only the resellable lines, once."""
    rc = await _vendor_return(user, rid)
    decided = {l.index: l for l in body.lines}
    if sorted(decided) != list(range(len(rc["lines"]))) or any(l.outcome not in ("resellable", "damaged") for l in body.lines):
        raise HTTPException(status_code=400, detail="Inspect every returned line and choose 'resellable' or 'damaged' for each.")
    result = [{"index": i, "outcome": decided[i].outcome, "note": decided[i].note.strip()} for i in range(len(rc["lines"]))]
    out = await _transition(rid, {"received"}, "inspected", user["id"], body.note.strip(),
                            {"inspection": {"lines": result, "note": body.note.strip(), "by": user["id"], "at": now_iso()}})
    await _complete_inspection(out, user["id"])
    await log_audit(user, "return_inspected", "return_case", rid, new_value={"outcomes": [r["outcome"] for r in result]}, request=request)
    return _view(await db.return_cases.find_one({"id": rid}, {"_id": 0}))


async def _complete_inspection(rc: dict, actor_id: str):
    """Idempotent follow-up of an inspected return: restock resellable lines once; open the refund case / replacement."""
    insp = rc.get("inspection") or {}
    good = [{"product_id": rc["lines"][r["index"]]["product_id"], "variant_sku": rc["lines"][r["index"]].get("variant_sku"),
             "quantity": rc["lines"][r["index"]]["quantity"]} for r in insp.get("lines", []) if r["outcome"] == "resellable"]
    if good:
        await restock_returned_lines(rc["id"], rc["order_id"], good, actor_id)
    if rc["kind"] == "return":
        order = await db.orders.find_one({"id": rc["order_id"]}, {"_id": 0})
        amount = min(rc.get("suggested_refund_paise", 0), await refundable_paise(order))
        if amount > 0:
            await open_refund_case(order, "return", amount, f"Return {rc['number']} inspected", f"return:{rc['id']}",
                                   return_case_id=rc["id"], vendor_id=rc["vendor_id"])
            await db.return_cases.update_one({"id": rc["id"], "status": "inspected"}, {"$set": {"status": "refund_pending", "updated_at": now_iso()},
                                             "$push": {"events": {"status": "refund_pending", "at": now_iso(), "by": "system", "note": "Refund case opened"}}})
    else:
        await db.return_cases.update_one({"id": rc["id"], "status": "inspected"}, {"$set": {"status": "replacement_due", "updated_at": now_iso()},
                                         "$push": {"events": {"status": "replacement_due", "at": now_iso(), "by": "system", "note": "Replacement due"}}})
    await create_notification(rc["user_id"], "order", "Return inspected", f"Your return {rc['number']} was inspected.", meta={"return_case": rc["id"]})


async def reconcile_returns(limit: int = 100) -> int:
    """Repair sweep: finish inspections whose restock / refund case / replacement step was interrupted. Idempotent."""
    n = 0
    async for rc in db.return_cases.find({"status": "inspected"}, {"_id": 0}).limit(limit):
        await _complete_inspection(rc, (rc.get("inspection") or {}).get("by", "system"))
        n += 1
    return n


# ----------------------------------------------------------- admin side
@router.get("/admin/returns")
async def admin_returns(status: Optional[str] = None, page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    q = {"status": status} if status else {}
    total = await db.return_cases.count_documents(q)
    rows = await db.return_cases.find(q, {"_id": 0}).sort("created_at", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_view(r) for r in rows], **page_meta(total, page, page_size)}


class AdminReturnDecision(BaseModel):
    decision: str                       # approve | reject
    note: str = Field(min_length=5, max_length=300)


@router.post("/admin/returns/{rid}/decision")
async def admin_return_decision(rid: str, body: AdminReturnDecision, request: Request, admin: dict = Depends(require_admin)):
    rc = await db.return_cases.find_one({"id": rid}, {"_id": 0})
    if not rc:
        raise HTTPException(status_code=404, detail="Return not found.")
    if body.decision == "approve":
        out = await _transition(rid, {"requested", "contested"}, "approved", admin["id"], body.note.strip())
        await create_notification(rc["user_id"], "order", "Return approved", f"Your return {rc['number']} was approved. Please send the goods back.")
        await _notify_vendor(rc["vendor_id"], "Return approved by admin", f"Return {rc['number']} was approved by HOME GENIES.")
    elif body.decision == "reject":
        out = await _transition(rid, {"requested", "contested"}, "rejected", admin["id"], body.note.strip())
        await create_notification(rc["user_id"], "order", "Return declined", f"Your return {rc['number']} was declined: {body.note.strip()}")
    else:
        raise HTTPException(status_code=400, detail="decision must be approve or reject.")
    await log_audit(admin, f"return_admin_{body.decision}", "return_case", rid, new_value={"status": out["status"]}, request=request)
    return _view(out)
