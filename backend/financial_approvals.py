"""Decision 4 (2026-11-20): maker-checker for controlled financial exceptions.

A controlled action (a manual points credit to a member's wallet, a manual vendor-ledger adjustment) is first REQUESTED by one
finance administrator (the maker). Nothing moves until a DIFFERENT finance administrator (the checker) approves it; only
then is the original, idempotent operation executed. A request can be rejected with a reason. The same person can never
create and approve the same action — enforced here, in the backend, not in the screen.

Requests are keyed by their idempotency key, so a retried or double-clicked request never creates a second approval.
Approval is a compare-and-set (pending -> approving), so two checkers clicking together execute the action once.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import create_notification, db, log_audit, now_iso, require_admin

logger = logging.getLogger("homegenies")
STALE_APPROVING = timedelta(minutes=5)

router = APIRouter(prefix="/api/admin/finance/approvals", tags=["finance-approvals"])

FINANCE_ROLES = ("super_admin", "accounts_admin")
KINDS = {"wallet_credit": "Manual wallet credit", "vendor_adjustment": "Vendor ledger adjustment"}


def require_finance_admin(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in FINANCE_ROLES:
        raise HTTPException(status_code=403, detail="Finance access required.")
    return admin


def _public(a: dict) -> dict:
    return {k: a.get(k) for k in ("id", "kind", "label", "status", "summary", "reason", "maker_id", "maker_role", "created_at",
                                  "checker_id", "decided_at", "decision_note", "result")}


async def submit(kind: str, key: str, payload: dict, maker: dict, reason: str, request: Optional[Request], summary: dict) -> dict:
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="Unknown controlled action.")
    aid = f"{kind}:{key}"
    existing = await db.financial_approvals.find_one({"_id": aid})
    if existing:
        if existing.get("payload") != payload:
            raise HTTPException(status_code=409, detail="This request key was already used for a different request.")
        return {"status": existing["status"], "approval": _public(existing), "already": True}
    doc = {"_id": aid, "id": aid, "kind": kind, "label": KINDS[kind], "status": "pending", "payload": payload, "summary": summary,
           "reason": (reason or "").strip(), "maker_id": maker["id"], "maker_role": maker.get("role"), "created_at": now_iso()}
    try:
        await db.financial_approvals.insert_one(doc)
    except Exception:                                     # a concurrent duplicate submission: report the stored one
        existing = await db.financial_approvals.find_one({"_id": aid})
        return {"status": existing["status"], "approval": _public(existing), "already": True}
    await log_audit(maker, "financial_action_requested", kind, aid, new_value={"summary": summary, "reason": doc["reason"]}, request=request)
    return {"status": "pending_approval", "approval": _public(doc),
            "message": "Request recorded. A different finance administrator must approve it before anything moves."}


async def _execute(a: dict, checker: dict, request: Optional[Request]) -> dict:
    p = a["payload"]
    if a["kind"] == "wallet_credit":
        from admin_routes import WalletCreditBody, apply_wallet_credit
        return await apply_wallet_credit(WalletCreditBody(**p), request, checker)
    from finance_routes import AdjustmentIn, apply_vendor_adjustment
    body = AdjustmentIn(**{k: p[k] for k in ("amount", "reason", "idempotency_key", "reverses")})
    out = await apply_vendor_adjustment(p["vendor_id"], body, request, checker)
    return {"entry_id": out["entry"]["id"], "created": out["created"]}


class DecisionIn(BaseModel):
    note: str = Field(default="", max_length=300)


@router.get("")
async def list_approvals(status: str = "pending", admin: dict = Depends(require_finance_admin)):
    # "pending" also lists requests stuck in "approving" (an approval interrupted mid-way), so they can be finished (C-18).
    q = {"status": {"$in": ["pending", "approving"]}} if status == "pending" else {"status": status}
    rows = await db.financial_approvals.find(q, {"_id": 0, "payload": 0}).sort("created_at", -1).to_list(200)
    return [_public(r) for r in rows]


@router.post("/{approval_id}/approve")
async def approve(approval_id: str, body: DecisionIn, request: Request, admin: dict = Depends(require_finance_admin)):
    a = await db.financial_approvals.find_one({"_id": approval_id})
    if not a:
        raise HTTPException(status_code=404, detail="Request not found.")
    if a["maker_id"] == admin["id"]:
        raise HTTPException(status_code=403, detail="You requested this action, so a different finance administrator must approve it.")
    # Batch 12 (audit C-18): an approval interrupted after its claim (crash, timeout) stayed "approving" for ever. Once the claim
    # is older than STALE_APPROVING, any finance admin other than the maker may take it over and finish it. A claim that is
    # still fresh is never taken (so concurrent clicks run the action once). Re-running an interrupted one is safe: both
    # executors are idempotent on the request's own key (request_id / idempotency_key).
    stale = (datetime.now(timezone.utc) - STALE_APPROVING).isoformat()
    claim = await db.financial_approvals.update_one(
        {"_id": approval_id, "$or": [{"status": "pending"}, {"status": "approving", "decided_at": {"$lt": stale}}]},
        {"$set": {"status": "approving", "checker_id": admin["id"], "decided_at": now_iso()}})
    if not claim.modified_count:
        raise HTTPException(status_code=409, detail=f"This request is already {a['status']}.")
    try:
        result = await _execute(a, admin, request)
    except HTTPException as e:
        await db.financial_approvals.update_one({"_id": approval_id}, {"$set": {"status": "failed", "result": {"error": str(e.detail)}}})
        raise
    except Exception:
        logger.exception("financial approval %s interrupted; it stays 'approving' and can be retried", approval_id)
        raise HTTPException(status_code=503, detail="The approval was interrupted. Approve it again in a few minutes to finish it; it will apply once.")
    result = {k: v for k, v in (result or {}).items() if k in ("message", "already", "amount", "distributor_id", "entry_id", "created")}
    await db.financial_approvals.update_one({"_id": approval_id}, {"$set": {"status": "approved", "decision_note": body.note.strip(),
                                                                            "result": result}})
    await log_audit(admin, "financial_action_approved", a["kind"], approval_id,
                    new_value={"maker_id": a["maker_id"], "summary": a["summary"], "note": body.note.strip()}, request=request)
    return {"status": "approved", "result": result}


@router.post("/{approval_id}/reject")
async def reject(approval_id: str, body: DecisionIn, request: Request, admin: dict = Depends(require_finance_admin)):
    if len(body.note.strip()) < 5:
        raise HTTPException(status_code=400, detail="Give a reason (at least 5 characters).")
    a = await db.financial_approvals.find_one({"_id": approval_id})
    if not a:
        raise HTTPException(status_code=404, detail="Request not found.")
    r = await db.financial_approvals.update_one({"_id": approval_id, "status": "pending"},
                                                {"$set": {"status": "rejected", "checker_id": admin["id"], "decided_at": now_iso(),
                                                          "decision_note": body.note.strip()}})
    if not r.modified_count:
        raise HTTPException(status_code=409, detail=f"This request is already {a['status']}.")
    await log_audit(admin, "financial_action_rejected", a["kind"], approval_id, new_value={"note": body.note.strip()}, request=request)
    if a["maker_id"] != admin["id"]:
        await create_notification(a["maker_id"], "finance", "Request rejected", f"{a['label']} was rejected: {body.note.strip()}")
    return {"status": "rejected"}
