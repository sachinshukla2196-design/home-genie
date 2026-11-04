"""Vendor finance: ledger, settlements, statements and COD reconciliation.

VENDORS can only READ their own ledger / settlements / COD records. They cannot create, approve or mark anything paid.
ADMINS (finance roles) manage policy, adjustments and settlements. Settlements stay disabled until an admin explicitly
activates the settlement policy; nothing here invents a commission, fee, deduction or schedule.
"""
import csv
import io
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

import ledger as L
from core import db, now_iso, new_id, require_admin, log_audit, create_notification, next_sequence
from money import to_paise, paise_to_float, paise_of
from cod_rules import refuse_own_sale, parse_resolution, check_resolution_amount
from pagination import clamp_page, page_meta
from vendor_routes import require_approved_vendor

router = APIRouter(prefix="/api", tags=["finance"])

FINANCE_ROLES = {"super_admin", "accounts_admin"}
POLICY_ID = "settlement_policy"
DEFAULT_POLICY = {"id": POLICY_ID, "active": False, "version": 0, "require_dual_approval": False, "min_settlement_paise": 0,
                  "cod_overdue_days": 7, "notes": "", "updated_by": None, "updated_at": None}


async def require_finance(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Finance access required.")
    return admin


async def get_policy() -> dict:
    p = await db.finance_policy.find_one({"id": POLICY_ID}, {"_id": 0})
    return p or dict(DEFAULT_POLICY)


def _money_view(d: dict) -> dict:
    """Add rupee floats next to every *_paise field (display only)."""
    out = dict(d)
    for k, v in d.items():
        if k.endswith("_paise") and isinstance(v, int):
            out[k[:-6]] = paise_to_float(v)
    return out


# ================================================================== vendor (read-only)
@router.get("/vendor/finance/summary")
async def vendor_finance_summary(user: dict = Depends(require_approved_vendor)):
    vid = user["_vendor"]["id"]
    policy = await get_policy()
    return {"balances": _money_view(await L.balances(vid)),
            "policy": {"active": policy["active"], "version": policy["version"],
                       "message": None if policy["active"] else "Settlements start after HOME GENIES approves the settlement policy. "
                                                                 "Your sales and refunds are already recorded below."},
            "cod": await _cod_summary(vid, policy)}


@router.get("/vendor/finance/ledger")
async def vendor_ledger(type: Optional[str] = None, page: int = 1, page_size: int = 25, user: dict = Depends(require_approved_vendor)):
    if type and type not in L.TYPES:
        raise HTTPException(status_code=400, detail="Unknown entry type.")
    page, page_size = clamp_page(page, page_size)
    q = {"vendor_id": user["_vendor"]["id"], **({"type": type} if type else {})}
    total = await db.vendor_ledger.count_documents(q)
    rows = await db.vendor_ledger.find(q, {"_id": 0}).sort("posted_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_money_view(r) for r in rows], **page_meta(total, page, page_size)}


@router.get("/vendor/finance/settlements")
async def vendor_settlements(page: int = 1, page_size: int = 25, user: dict = Depends(require_approved_vendor)):
    page, page_size = clamp_page(page, page_size)
    q = {"vendor_id": user["_vendor"]["id"]}
    total = await db.settlements.count_documents(q)
    rows = await db.settlements.find(q, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_vendor_settlement_view(r) for r in rows], **page_meta(total, page, page_size)}



def _vendor_settlement_view(s: dict) -> dict:
    """What a vendor may see of a payout: amounts, dates, status and reference. Not which admin created, approved or paid it."""
    v = _money_view(s)
    for k in ("created_by", "approved_by", "paid_by"):
        v.pop(k, None)
    v["events"] = [{"status": e.get("status"), "at": e.get("at"), "note": e.get("note", "")} for e in (s.get("events") or [])]
    return v


@router.get("/vendor/finance/statement.csv")
async def vendor_statement(date_from: Optional[str] = None, date_to: Optional[str] = None, user: dict = Depends(require_approved_vendor)):
    """The vendor's own ledger as a CSV statement (exact amounts, one row per entry)."""
    from pagination import date_range
    try:
        dr = date_range(date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e} must be a date like 2026-10-23.")
    q = {"vendor_id": user["_vendor"]["id"], **({"posted_at": dr} if dr else {})}
    rows = await db.vendor_ledger.find(q, {"_id": 0}).sort("posted_at", 1).to_list(20000)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["posted_at", "entry_id", "type", "order_id", "amount_inr", "amount_paise", "reason", "reverses"])
    for r in rows:
        w.writerow([r["posted_at"], r["id"], r["type"], r.get("order_id") or "", f"{paise_to_float(r['amount_paise']):.2f}",
                    r["amount_paise"], _csv_safe(r.get("reason", "")), r.get("reverses") or ""])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=vendor-statement.csv"})


def _csv_safe(v: str) -> str:
    """Neutralise spreadsheet formula injection in exported text."""
    v = str(v or "")
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


# ================================================================== COD reconciliation (vendor view)
def _days_since(iso: Optional[str]) -> int:
    try:
        return max((datetime.now(timezone.utc) - datetime.fromisoformat(iso)).days, 0)
    except Exception:
        return 0


def _cod_state(o: dict, f: dict, overdue_days: int) -> dict:
    ps = o.get("payment_status")
    delivered_at = next((e["at"] for e in reversed(f.get("events", [])) if e.get("status") == "delivered"), None)
    if ps == "cod_discrepancy":
        state = "discrepancy"
    elif ps in ("paid", "partially_refunded", "refunded"):
        state = "collected"
    elif f.get("status") == "delivered":
        state = "delivered_awaiting_cash"
    elif f.get("status") in ("rejected", "cancelled", "returned_to_origin"):
        state = "not_applicable"
    else:
        state = "awaiting_delivery"
    waiting = _days_since(delivered_at) if state == "delivered_awaiting_cash" else 0
    return {"state": state, "days_waiting": waiting, "overdue": state == "delivered_awaiting_cash" and waiting >= overdue_days}


async def _cod_summary(vid: str, policy: dict) -> dict:
    orders = await db.orders.find({"payment_method": "cod", "fulfilments.vendor_id": vid, "needs_refund": {"$ne": True}},
                                  {"_id": 0}).sort("created_at", -1).to_list(2000)
    out = {"awaiting_delivery_paise": 0, "delivered_awaiting_cash_paise": 0, "overdue_paise": 0, "discrepancy_paise": 0,
           "collected_paise": 0, "overdue_days": policy.get("cod_overdue_days", 7)}
    for o in orders:
        f = next((x for x in o["fulfilments"] if x["vendor_id"] == vid), None)
        if not f:
            continue
        st = _cod_state(o, f, policy.get("cod_overdue_days", 7))
        amt = L.vendor_lines_paise(o, vid)
        key = {"awaiting_delivery": "awaiting_delivery_paise", "delivered_awaiting_cash": "delivered_awaiting_cash_paise",
               "discrepancy": "discrepancy_paise", "collected": "collected_paise"}.get(st["state"])
        if key:
            out[key] += amt
        if st["overdue"]:
            out["overdue_paise"] += amt
    return _money_view(out)


@router.get("/vendor/finance/cod")
async def vendor_cod(state: Optional[str] = None, page: int = 1, page_size: int = 25, user: dict = Depends(require_approved_vendor)):
    vid = user["_vendor"]["id"]
    policy = await get_policy()
    page, page_size = clamp_page(page, page_size)
    orders = await db.orders.find({"payment_method": "cod", "fulfilments.vendor_id": vid, "needs_refund": {"$ne": True}},
                                  {"_id": 0}).sort("created_at", -1).to_list(2000)
    rows = []
    for o in orders:
        f = next((x for x in o["fulfilments"] if x["vendor_id"] == vid), None)
        if not f:
            continue
        st = _cod_state(o, f, policy.get("cod_overdue_days", 7))
        if state and st["state"] != state:
            continue
        rows.append({"order_id": o["id"], "order_number": o.get("order_number"), "created_at": o.get("created_at"),
                     "amount_paise": L.vendor_lines_paise(o, vid), "amount": paise_to_float(L.vendor_lines_paise(o, vid)),
                     "fulfilment_status": f.get("status"), "payment_status": o.get("payment_status"),
                     "cod_discrepancy": o.get("cod_discrepancy"), **st})
    total = len(rows)
    return {"items": rows[(page - 1) * page_size: page * page_size], **page_meta(total, page, page_size), "summary": await _cod_summary(vid, policy)}


# ================================================================== admin: policy
class PolicyIn(BaseModel):
    active: bool
    require_dual_approval: bool = False
    min_settlement: float = Field(default=0, ge=0)
    cod_overdue_days: int = Field(default=7, ge=1, le=90)
    notes: str = Field(default="", max_length=500)


@router.get("/admin/finance/policy")
async def admin_get_policy(admin: dict = Depends(require_admin)):
    return await get_policy()


@router.put("/admin/finance/policy")
async def admin_set_policy(body: PolicyIn, request: Request, admin: dict = Depends(require_finance)):
    """Activating the policy is an explicit finance decision; it stays OFF by default."""
    old = await get_policy()
    new = {**old, "id": POLICY_ID, "active": body.active, "require_dual_approval": body.require_dual_approval,
           "min_settlement_paise": to_paise(body.min_settlement), "cod_overdue_days": body.cod_overdue_days, "notes": body.notes,
           "version": old.get("version", 0) + 1, "updated_by": admin["id"], "updated_at": now_iso()}
    await db.finance_policy.update_one({"id": POLICY_ID}, {"$set": new}, upsert=True)
    await log_audit(admin, "finance_policy_changed", "finance_policy", POLICY_ID,
                    old_value={k: old.get(k) for k in ("active", "version", "require_dual_approval", "min_settlement_paise")},
                    new_value={k: new[k] for k in ("active", "version", "require_dual_approval", "min_settlement_paise")}, request=request)
    return new


# ================================================================== admin: ledger, adjustments
@router.get("/admin/finance/vendors")
async def admin_vendor_balances(page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    total = await db.vendors.count_documents({"status": {"$in": ["approved", "suspended"]}})
    vs = await db.vendors.find({"status": {"$in": ["approved", "suspended"]}}, {"_id": 0, "id": 1, "business_name": 1, "vendor_code": 1, "status": 1}) \
        .sort("business_name", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [{**v, "balances": _money_view(await L.balances(v["id"]))} for v in vs], **page_meta(total, page, page_size)}


@router.get("/admin/finance/vendors/{vendor_id}/ledger")
async def admin_vendor_ledger(vendor_id: str, page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    q = {"vendor_id": vendor_id}
    total = await db.vendor_ledger.count_documents(q)
    rows = await db.vendor_ledger.find(q, {"_id": 0}).sort("posted_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_money_view(r) for r in rows], "balances": _money_view(await L.balances(vendor_id)), **page_meta(total, page, page_size)}


class AdjustmentIn(BaseModel):
    amount: float                                   # rupees, signed, non-zero
    reason: str = Field(min_length=5, max_length=300)
    idempotency_key: Optional[str] = Field(default=None, max_length=80)
    reverses: Optional[str] = None                  # ledger entry id this corrects, if any


@router.post("/admin/finance/vendors/{vendor_id}/adjustments")
async def admin_adjustment(vendor_id: str, body: AdjustmentIn, request: Request, admin: dict = Depends(require_finance)):
    if not await db.vendors.find_one({"id": vendor_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Vendor not found.")
    p = to_paise(body.amount)
    if p == 0:
        raise HTTPException(status_code=400, detail="Adjustment amount cannot be zero.")
    if body.reverses and not await db.vendor_ledger.find_one({"id": body.reverses, "vendor_id": vendor_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="The entry to reverse was not found for this vendor.")
    key = f"adj:{vendor_id}:{body.idempotency_key or new_id()}"
    entry, created = await L.post_entry(vendor_id, L.ADJUSTMENT, p, key, actor=admin["id"], reason=body.reason.strip(), reverses=body.reverses)
    if created:
        await log_audit(admin, "vendor_ledger_adjustment", "vendor", vendor_id, new_value={"entry": entry["id"], "amount_paise": p, "reason": body.reason}, request=request)
        v = await db.vendors.find_one({"id": vendor_id}, {"_id": 0, "user_id": 1})
        await create_notification(v["user_id"], "vendor", "Ledger adjustment", f"A ledger adjustment was recorded: {body.reason.strip()}")
    return {"entry": _money_view(entry), "created": created}


# ================================================================== admin: settlements
SETTLE_FLOW = {"requested": {"approved", "rejected"}, "approved": {"paid", "rejected", "failed"},
               "paid": set(), "rejected": set(), "failed": set()}


class SettlementIn(BaseModel):
    vendor_id: str
    amount: Optional[float] = None                  # rupees; omitted = everything currently available
    note: str = Field(default="", max_length=300)


async def _settle_view(s: dict) -> dict:
    return _money_view(s)


@router.post("/admin/finance/settlements")
async def create_settlement(body: SettlementIn, request: Request, admin: dict = Depends(require_finance)):
    policy = await get_policy()
    if not policy["active"]:
        raise HTTPException(status_code=409, detail="Settlement policy is not approved yet. Activate it in Finance policy first.")
    from vendor_lifecycle import SELLING
    v = await db.vendors.find_one({"id": body.vendor_id, "status": {"$in": list(SELLING)}}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Approved vendor not found.")
    bal = await L.balances(body.vendor_id)
    amt = to_paise(body.amount) if body.amount is not None else bal["available_for_settlement_paise"]
    if amt <= 0 or amt > bal["available_for_settlement_paise"]:
        raise HTTPException(status_code=400, detail="Amount must be between 0.01 and the available balance.")
    if amt < policy.get("min_settlement_paise", 0):
        raise HTTPException(status_code=400, detail="Amount is below the minimum settlement.")
    num = await next_sequence("settlement", "STL", 6)
    now = now_iso()
    s = {"id": new_id(), "number": num, "vendor_id": body.vendor_id, "vendor_name": v["business_name"], "amount_paise": amt,
         "currency": "INR", "status": "requested", "policy_version": policy["version"], "note": body.note.strip(),
         "created_by": admin["id"], "approved_by": None, "paid_by": None, "reference": "",
         "events": [{"status": "requested", "at": now, "by": admin["id"], "note": body.note.strip()}], "created_at": now, "updated_at": now}
    try:
        await db.settlements.insert_one(dict(s))
    except DuplicateKeyError:     # one open settlement per vendor at a time (unique partial index)
        raise HTTPException(status_code=409, detail="This vendor already has an open settlement. Finish or reject it first.")
    await log_audit(admin, "settlement_created", "settlement", s["id"], new_value={"vendor_id": body.vendor_id, "amount_paise": amt}, request=request)
    s.pop("_id", None)
    return _money_view(s)


class SettlementAction(BaseModel):
    action: str                                     # approve | reject | mark_paid | fail
    reference: str = Field(default="", max_length=120)
    note: str = Field(default="", max_length=300)


@router.post("/admin/finance/settlements/{sid}/action")
async def settlement_action(sid: str, body: SettlementAction, request: Request, admin: dict = Depends(require_finance)):
    s = await db.settlements.find_one({"id": sid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Settlement not found.")
    target = {"approve": "approved", "reject": "rejected", "mark_paid": "paid", "fail": "failed"}.get(body.action)
    if not target or target not in SETTLE_FLOW.get(s["status"], set()):
        raise HTTPException(status_code=400, detail=f"Cannot {body.action} a settlement that is '{s['status']}'.")
    policy = await get_policy()
    if target == "approved" and policy.get("require_dual_approval") and s["created_by"] == admin["id"]:
        raise HTTPException(status_code=403, detail="A different finance admin must approve this settlement.")
    if target in ("rejected", "failed") and len(body.note.strip()) < 5:
        raise HTTPException(status_code=400, detail="A reason is required.")
    if target == "paid":
        if len(body.reference.strip()) < 3:
            raise HTTPException(status_code=400, detail="The payment reference (UTR / transfer id) is required.")
        if policy.get("require_dual_approval") and s.get("approved_by") == admin["id"]:
            raise HTTPException(status_code=403, detail="A different finance admin must mark this settlement paid.")
        bal = await L.balances(s["vendor_id"])
        if s["amount_paise"] > bal["pending_settlement_paise"]:        # balance fell since it was requested (e.g. a refund)
            raise HTTPException(status_code=409, detail="The vendor's balance changed since this settlement was requested. Reject it and create a new one.")
    now = now_iso()
    sets = {"status": target, "updated_at": now}
    if target == "approved":
        sets["approved_by"] = admin["id"]
    if target == "paid":
        sets.update({"paid_by": admin["id"], "reference": body.reference.strip(), "paid_at": now})
    claim = await db.settlements.update_one({"id": sid, "status": s["status"]},      # atomic: one winner per transition
                                            {"$set": sets, "$push": {"events": {"status": target, "at": now, "by": admin["id"], "note": (body.note or body.reference).strip()}}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="This settlement was just updated. Refresh and try again.")
    if target == "paid":
        await _post_settlement_paid(sid)
    await log_audit(admin, f"settlement_{body.action}", "settlement", sid, old_value={"status": s["status"]}, new_value={"status": target, "reference": body.reference}, request=request)
    v = await db.vendors.find_one({"id": s["vendor_id"]}, {"_id": 0, "user_id": 1})
    await create_notification(v["user_id"], "vendor", f"Settlement {s['number']} {target}", f"Your settlement {s['number']} is now {target}.")
    return _money_view(await db.settlements.find_one({"id": sid}, {"_id": 0}))


async def _post_settlement_paid(sid: str):
    s = await db.settlements.find_one({"id": sid}, {"_id": 0})
    if s and s["status"] == "paid":
        await L.post_entry(s["vendor_id"], L.SETTLEMENT_PAID, -s["amount_paise"], f"settle:{sid}", actor=s.get("paid_by") or "system",
                           reason=f"Settlement {s['number']} paid", meta={"settlement": sid, "reference": s.get("reference")})


async def reconcile_settlements() -> int:
    """Repair: a settlement marked paid always has its ledger entry (covers a crash between the two writes)."""
    n = 0
    async for s in db.settlements.find({"status": "paid"}, {"_id": 0, "id": 1}):
        if not await db.vendor_ledger.find_one({"source_key": f"settle:{s['id']}"}, {"_id": 1}):
            await _post_settlement_paid(s["id"])
            n += 1
    return n


@router.get("/admin/finance/settlements")
async def admin_settlements(status: Optional[str] = None, page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    q = {"status": status} if status in SETTLE_FLOW else {}
    total = await db.settlements.count_documents(q)
    rows = await db.settlements.find(q, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_money_view(r) for r in rows], **page_meta(total, page, page_size)}


@router.post("/admin/finance/reconcile")
async def admin_reconcile(admin: dict = Depends(require_finance)):
    """Rebuild any missing ledger entries from the order records (safe to run repeatedly)."""
    r = await L.reconcile_ledger()
    r["settlements"] = await reconcile_settlements()
    return r


# ================================================================== admin: COD discrepancies
@router.post("/admin/finance/cod-discrepancies/{order_id}/resolve")
async def resolve_cod_discrepancy(order_id: str, request: Request, admin: dict = Depends(require_finance), body: Any = Body(default=None)):
    """Close a held COD order after independent review. Rules live in `cod_rules`.
    The role gate (`require_finance`) has already run. Then: the order must be an open discrepancy, the reviewer must not be
    the reporter or the attributed HomeGenie, and only then is the body validated (reason, collected amount, courier or
    provider evidence type and reference; a note alone is not evidence). All of that happens before any write.
    confirm_full : the reviewer records that the full total was collected; commission is distributed once, as for any paid order.
    accept_short : a lower amount was collected; the order is closed, the vendor sale is recorded pro rata, and commission stays
                   held (`short_collection_held`) because the owner has not set a policy for short collections."""
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o or o.get("payment_status") != "cod_discrepancy":
        raise HTTPException(status_code=404, detail="No open COD discrepancy on this order.")
    d = o["cod_discrepancy"]
    if d.get("reported_by") == admin["id"]:
        # maker and checker must differ: whoever reported the mismatch or exception cannot also close it
        raise HTTPException(status_code=403, detail="A different finance admin must resolve this COD discrepancy.")
    refuse_own_sale(admin, o)
    r = parse_resolution(body)
    expected_p = d["expected_paise"]
    collected_p = to_paise(r.collected_amount)
    check_resolution_amount(r.resolution, collected_p, expected_p)
    now = now_iso()
    collection = {"type": r.evidence_type, "reference": r.evidence_reference, "note": r.reason, "recorded_by": admin["id"],
                  "recorded_at": now, "verified_by_system": False,       # recorded at review; no courier or provider integration verifies it
                  "expected_paise": expected_p, "collected_paise": collected_p}
    claim = await db.orders.update_one(
        {"id": order_id, "payment_status": "cod_discrepancy"},
        {"$set": {"payment_status": "paid", "status": "delivered", "cod_collected_paise": collected_p, "cod_collected_by": admin["id"],
                  "cod_collected_role": "admin", "cod_collected_at": now, "paid_at": now, "updated_at": now,
                  "cod_collection": collection,
                  "cod_discrepancy.status": "resolved", "cod_discrepancy.resolution": r.resolution,
                  "cod_discrepancy.resolved_by": admin["id"], "cod_discrepancy.resolved_at": now, "cod_discrepancy.note": r.reason,
                  "cod_discrepancy.resolution_evidence": {"type": r.evidence_type, "reference": r.evidence_reference,
                                                          "collected_paise": collected_p, "reviewer": admin["id"], "reviewed_at": now},
                  **({"commission_note": "short_collection_held", "cod_short_collected": True,
                      "cod_shortfall_paise": expected_p - collected_p} if r.resolution == "accept_short" else {})}})
    if claim.modified_count != 1:
        raise HTTPException(status_code=409, detail="This discrepancy was just resolved.")
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o.get("invoice_number"):
        inv = await next_sequence("invoice", "INV", 6)
        await db.orders.update_one({"id": order_id, "invoice_number": None}, {"$set": {"invoice_number": inv}})
    commissions = None
    if r.resolution == "confirm_full":
        buyer = await db.users.find_one({"id": o["user_id"]}, {"_id": 0})
        from commission import distribute_sale_commissions      # itself refuses unless collection_is_proven(order)
        commissions = await distribute_sale_commissions(o, buyer or {}, request)
    await L.post_order_collected(await db.orders.find_one({"id": order_id}, {"_id": 0}))
    await log_audit(admin, "cod_discrepancy_resolved", "order", order_id, old_value=d,
                    new_value={"resolution": r.resolution, "reason": r.reason, "collected_paise": collected_p,
                               "evidence_type": r.evidence_type, "evidence_reference": r.evidence_reference}, request=request)
    return {"ok": True, "resolution": r.resolution, "commissions": commissions}


@router.get("/admin/finance/commission-funding")
async def commission_funding_report(only_insufficient: bool = True, page: int = 1, page_size: int = 25, admin: dict = Depends(require_finance)):
    """Read-only: commission plans whose commission exceeds the platform revenue recorded at freeze time (see
    commission.funding_snapshot). Plans frozen before the snapshot existed are counted as `unassessed`, never guessed."""
    page, page_size = clamp_page(page, page_size)
    q = {"funding.sufficient": False} if only_insufficient else {"funding": {"$exists": True}}
    total = await db.commission_plans.count_documents(q)
    rows = await db.commission_plans.find(q, {"_id": 0, "order_id": 1, "order_number": 1, "funding": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    unassessed = await db.commission_plans.count_documents({"funding": {"$exists": False}})
    return {"items": rows, "unassessed_plans": unassessed, **page_meta(total, page, page_size)}


@router.get("/admin/finance/non-distributor-commissions")
async def non_distributor_commissions(page: int = 1, page_size: int = 50, admin: dict = Depends(require_finance)):
    """Read-only: commissions credited to accounts that are NOT currently distributors (vendors, vendor staff, admins, or a
    distributor later converted). They are honoured as frozen (Phase 3B.4, option 2a); this list is for review only.
    `created_before_enforcement` = the plan was frozen before the distributor-and-green rule was recorded on plans."""
    from commission import ELIGIBILITY_RULE
    page, page_size = clamp_page(page, page_size)
    others = await db.users.find({"role": {"$ne": "distributor"}}, {"_id": 0, "id": 1, "role": 1, "status": 1,
                                                                     "distributor_id": 1, "full_name": 1}).to_list(100000)
    by_id = {u["id"]: u for u in others}
    q = {"user_id": {"$in": list(by_id)}}
    total = await db.commissions.count_documents(q)
    rows = await db.commissions.find(q, {"_id": 0, "id": 1, "user_id": 1, "order_id": 1, "order_number": 1, "type": 1, "status": 1,
                                         "amount_paise": 1, "amount": 1, "reversed_paise": 1, "released_at": 1, "created_at": 1}) \
        .sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    plans = {pl["_id"]: pl.get("eligibility_rule") for pl in await db.commission_plans.find(
        {"_id": {"$in": list({r["order_id"] for r in rows})}}, {"_id": 1, "eligibility_rule": 1}).to_list(len(rows) or 1)}
    items = []
    for r in rows:
        u = by_id.get(r["user_id"], {})
        items.append({**r, "recipient_role": u.get("role"), "recipient_status": u.get("status"), "recipient_distributor_id": u.get("distributor_id"),
                      "recipient_name": u.get("full_name"), "frozen": True,
                      "created_before_enforcement": plans.get(r["order_id"]) != ELIGIBILITY_RULE})
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/admin/finance/negative-wallets")
async def negative_wallets(page: int = 1, page_size: int = 50, admin: dict = Depends(require_finance)):
    """Read-only: wallets whose available balance is below zero (a refund clawed back points that were already released).
    The deficit is netted automatically by future earnings; new withdrawals are refused and reserved ones cannot be paid
    while it lasts. Nothing here changes a balance."""
    page, page_size = clamp_page(page, page_size)
    q = {"available_balance_paise": {"$lt": 0}}
    total = await db.wallets.count_documents(q)
    rows = await db.wallets.find(q, {"_id": 0, "user_id": 1, "available_balance_paise": 1, "pending_balance_paise": 1,
                                     "total_earned_paise": 1, "total_withdrawn_paise": 1, "updated_at": 1}) \
        .sort("available_balance_paise", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    items = []
    for w in rows:
        u = await db.users.find_one({"id": w["user_id"]}, {"_id": 0, "distributor_id": 1, "full_name": 1, "role": 1, "status": 1}) or {}
        claws = await db.wallet_transactions.find({"user_id": w["user_id"], "type": "COMMISSION_CLAWBACK"},
                                                   {"_id": 0, "amount_paise": 1, "reference": 1, "status": 1, "created_at": 1}) \
            .sort("created_at", -1).limit(5).to_list(5)
        open_wd = await db.withdrawal_requests.find({"user_id": w["user_id"], "status": {"$in": ["pending", "under_review", "approved"]}},
                                                    {"_id": 0, "id": 1, "request_number": 1, "amount_paise": 1, "status": 1}).to_list(20)
        items.append({**w, **{"user": u}, "deficit_paise": -w["available_balance_paise"], "recent_clawbacks": claws,
                      "open_withdrawals": open_wd})
    return {"items": items, **page_meta(total, page, page_size)}


@router.get("/admin/finance/cod-discrepancies")
async def list_cod_discrepancies(page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    page, page_size = clamp_page(page, page_size)
    q = {"payment_status": "cod_discrepancy"}
    total = await db.orders.count_documents(q)
    rows = await db.orders.find(q, {"_id": 0, "id": 1, "order_number": 1, "total": 1, "total_paise": 1, "cod_discrepancy": 1, "user_id": 1, "created_at": 1}) \
        .sort("created_at", 1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": [_money_view(r) for r in rows], **page_meta(total, page, page_size)}
