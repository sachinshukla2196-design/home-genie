"""Admin review and approval of HomeGenie activation (RED -> GREEN).

Candidates are RED distributors with a qualifying purchase of their own (see activation_rules). Approval is an explicit admin
action. It is one atomic conditional update on the user record, so repeated requests and two admins racing cannot activate
twice. Approving creates no commission and replays none: commission eligibility is decided from the status at each order's
own commission event (the frozen plan), never from a later approval.
"""
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError, field_validator

from activation_rules import ACTIVATION_MIN_PAISE, disqualification, evidence_summary, is_qualifying, qualifying_subtotal_paise
from core import db, get_current_user, log_audit, now_iso, new_id, create_notification
from money import paise_to_float

router = APIRouter(prefix="/api/admin/activations", tags=["activation"])
APPROVER_ROLES = ("admin", "super_admin")          # same authority as confirming COD collection
_ORDER_FIELDS = {"_id": 0, "id": 1, "order_number": 1, "user_id": 1, "subtotal": 1, "subtotal_paise": 1, "total": 1, "total_paise": 1,
                 "payment_method": 1, "payment_status": 1, "status": 1, "paid_at": 1, "cod_collection": 1, "payment_reference": 1,
                 "refunded_paise": 1, "refunded_amount": 1, "needs_refund": 1, "created_at": 1}


async def require_approver(user: dict = Depends(get_current_user)):
    if user.get("role") not in APPROVER_ROLES:
        raise HTTPException(status_code=403, detail="Only an admin can approve HomeGenie activation.")
    return user


class ApproveIn(BaseModel):
    order_id: str
    note: str = ""

    @field_validator("order_id")
    @classmethod
    def _id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("order_id is required")
        return v

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        v = v.strip()
        if len(v) > 300:
            raise ValueError("note must be at most 300 characters")
        return v


def _view(order: dict) -> dict:
    return {"order_id": order["id"], "order_number": order.get("order_number"), "subtotal": paise_to_float(qualifying_subtotal_paise(order)),
            "total": order.get("total"), "payment_method": order.get("payment_method"), "payment_status": order.get("payment_status"),
            "paid_at": order.get("paid_at"), "evidence": evidence_summary(order)}


@router.get("")
async def list_candidates(admin: dict = Depends(require_approver), limit: int = 100):
    """RED distributors with at least one qualifying purchase, oldest first. Read-only."""
    limit = max(1, min(int(limit), 200))
    rows = await db.orders.find({"payment_status": "paid", "subtotal_paise": {"$gte": ACTIVATION_MIN_PAISE}}, _ORDER_FIELDS).sort("created_at", 1).to_list(2000)
    by_user: dict = {}
    for o in rows:
        if is_qualifying(o):
            by_user.setdefault(o["user_id"], []).append(o)
    items = []
    if by_user:
        users = await db.users.find({"id": {"$in": list(by_user)}, "role": "distributor", "status": {"$ne": "green"}},
                                    {"_id": 0, "id": 1, "distributor_id": 1, "full_name": 1, "status": 1, "created_at": 1}).to_list(len(by_user))
        for u in users[:limit]:
            items.append({"user": u, "min_subtotal": paise_to_float(ACTIVATION_MIN_PAISE), "qualifying_orders": [_view(o) for o in by_user[u["id"]]]})
    return {"items": items, "min_subtotal": paise_to_float(ACTIVATION_MIN_PAISE)}


@router.post("/{user_id}/approve")
async def approve_activation(user_id: str, request: Request, admin: dict = Depends(require_approver), body: Any = Body(default=None)):
    """RED -> GREEN on the named qualifying order. Authority first, then body, then everything is re-verified from the database."""
    try:
        data = ApproveIn(**(body if isinstance(body, dict) else {}))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=[{"loc": [str(x) for x in err["loc"]], "msg": err["msg"]} for err in e.errors()])
    if user_id == admin["id"]:
        raise HTTPException(status_code=403, detail="You cannot approve your own activation.")
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user or user.get("role") != "distributor":
        raise HTTPException(status_code=404, detail="HomeGenie not found.")
    if user.get("status") == "green":
        return {"ok": True, "already": True, "status": "green"}
    order = await db.orders.find_one({"id": data.order_id, "user_id": user_id}, _ORDER_FIELDS)
    if not order:
        raise HTTPException(status_code=404, detail="That order does not belong to this HomeGenie.")
    reason = disqualification(order)
    if reason:
        raise HTTPException(status_code=409, detail=f"This order does not qualify for activation ({reason}).")
    now = now_iso()
    activation = {"order_id": order["id"], "order_number": order.get("order_number"), "subtotal_paise": qualifying_subtotal_paise(order),
                  "payment_method": order.get("payment_method"), "evidence": evidence_summary(order),
                  "approved_by": admin["id"], "approved_at": now, "note": data.note}
    claim = await db.users.update_one(
        {"id": user_id, "role": "distributor", "status": {"$ne": "green"}, "activation": {"$exists": False}},
        {"$set": {"status": "green", "approved_at": now, "updated_at": now, "activation": activation}})
    if claim.modified_count != 1:
        return {"ok": True, "already": True, "status": "green"}      # a concurrent approval won; nothing further happens
    await db.activation_history.insert_one({"id": new_id(), "user_id": user_id, "event": "approved", **activation})
    await log_audit(admin, "homegenie_activated", "user", user_id, old_value={"status": user.get("status")},
                    new_value={"status": "green", "order_id": order["id"], "subtotal_paise": activation["subtotal_paise"]}, request=request)
    await create_notification(user_id, "account", "HomeGenie activated",
                              "Your HomeGenie selling role is now active.", "होमजीनी सक्रिय", "आपकी होमजीनी सेलिंग भूमिका अब सक्रिय है।")
    return {"ok": True, "status": "green", "activation": activation}
