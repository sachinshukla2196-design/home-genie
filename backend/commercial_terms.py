"""Vendor commercial agreements: versioned, approved, accepted, effective from a date, and applied to each sale as it happens.

Nothing here invents a rate. Every commission percentage and fixed fee is entered by an authorised finance admin, and an
agreement only applies once a different finance admin has approved it.

Rules this module implements (all from the agreement itself):
- a version is immutable once approved; changes are made by creating the next version as a draft;
- a version applies to orders paid on or after its effective date, and the latest approved version on or before the order date wins;
- the commission for an order is calculated once, when the sale is posted, and stored on the ledger with the agreement version used;
  later agreements never change past commissions;
- a vendor can read their agreements and accept an approved version. A vendor cannot create, change or approve one.

Not defined in the project yet, so NOT implemented here (see the report): commission on refunds, partial cancellations, and any
automatic payout schedule. `settlement_schedule` is a label stored for the agreement only.
"""
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from core import db, now_iso, new_id, log_audit

SCHEDULES = ("weekly", "biweekly", "monthly", "on_request")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class AgreementIn(BaseModel):
    commission_pct: float = Field(ge=0, le=100)
    fixed_fee_paise: int = Field(ge=0, le=10_000_000)      # charged once per vendor order, when the sale is posted
    settlement_schedule: str = "on_request"
    effective_from: str
    notes: str = Field(default="", max_length=500)


def _bp(pct: float) -> int:
    """Percentage to basis points, exact to two decimals."""
    return int(round(pct * 100))


def commission_for(agreement: dict, sale_paise: int) -> int:
    """Commission on one vendor sale, rounded half-up to the paisa and never more than the sale itself."""
    if sale_paise <= 0:
        return 0
    pct = _bp(agreement["commission_pct"])
    amount = (sale_paise * pct + 5000) // 10000 + int(agreement.get("fixed_fee_paise") or 0)
    return min(amount, sale_paise)


async def effective_agreement(vendor_id: str, on_date: str) -> Optional[dict]:
    """The approved version that applies to a date (YYYY-MM-DD), or None."""
    return await db.vendor_agreements.find_one(
        {"vendor_id": vendor_id, "status": "approved", "effective_from": {"$lte": on_date}}, {"_id": 0},
        sort=[("effective_from", -1), ("version", -1)])


def _public(a: dict) -> dict:
    """What a vendor may see: terms and dates, never who approved internally."""
    return {"id": a["id"], "version": a["version"], "status": a["status"], "commission_pct": a["commission_pct"],
            "fixed_fee_paise": a["fixed_fee_paise"], "settlement_schedule": a["settlement_schedule"], "effective_from": a["effective_from"],
            "notes": a.get("notes", ""), "approved_at": a.get("approved_at"), "accepted_at": a.get("accepted_at")}


async def create_draft(vendor_id: str, body: AgreementIn, admin: dict, request=None) -> dict:
    if body.settlement_schedule not in SCHEDULES:
        raise HTTPException(status_code=400, detail="Choose a settlement schedule from the list.")
    if not DATE.fullmatch(body.effective_from):
        raise HTTPException(status_code=400, detail="Effective date must look like 2026-11-01.")
    try:
        eff = datetime.strptime(body.effective_from, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Effective date is not a real date.")
    if eff < datetime.now(timezone.utc).date():
        raise HTTPException(status_code=400, detail="Effective date cannot be in the past.")
    if not await db.vendors.find_one({"id": vendor_id}, {"_id": 1}):
        raise HTTPException(status_code=404, detail="Vendor not found.")
    last = await db.vendor_agreements.find_one({"vendor_id": vendor_id}, {"_id": 0, "version": 1}, sort=[("version", -1)])
    doc = {"id": new_id(), "vendor_id": vendor_id, "version": (last or {}).get("version", 0) + 1, "status": "draft",
           "commission_pct": body.commission_pct, "fixed_fee_paise": body.fixed_fee_paise, "settlement_schedule": body.settlement_schedule,
           "effective_from": body.effective_from, "notes": body.notes.strip(), "created_by": admin["id"], "created_at": now_iso(),
           "approved_by": None, "approved_at": None, "accepted_by": None, "accepted_at": None}
    await db.vendor_agreements.insert_one(dict(doc))
    await log_audit(admin, "agreement_drafted", "vendor_agreement", doc["id"], new_value={"vendor_id": vendor_id, "version": doc["version"]}, request=request)
    return doc


async def approve(agreement_id: str, admin: dict, request=None) -> dict:
    a = await db.vendor_agreements.find_one({"id": agreement_id}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Agreement not found.")
    if a["status"] != "draft":
        raise HTTPException(status_code=400, detail=f"Only a draft can be approved (this one is '{a['status']}').")
    if a["created_by"] == admin["id"]:
        raise HTTPException(status_code=403, detail="A different finance admin must approve this agreement.")
    clash = await db.vendor_agreements.find_one({"vendor_id": a["vendor_id"], "status": "approved", "effective_from": a["effective_from"]}, {"_id": 1})
    if clash:
        raise HTTPException(status_code=409, detail="Another approved agreement already starts on this date. Choose a different effective date.")
    res = await db.vendor_agreements.update_one({"id": agreement_id, "status": "draft"},
                                                {"$set": {"status": "approved", "approved_by": admin["id"], "approved_at": now_iso()}})
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="This agreement was just changed. Reload and try again.")
    await log_audit(admin, "agreement_approved", "vendor_agreement", agreement_id, new_value={"version": a["version"]}, request=request)
    return await db.vendor_agreements.find_one({"id": agreement_id}, {"_id": 0})


async def accept(vendor: dict, agreement_id: str, user: dict, request=None) -> dict:
    a = await db.vendor_agreements.find_one({"id": agreement_id, "vendor_id": vendor["id"]}, {"_id": 0})
    if not a or a["status"] != "approved":
        raise HTTPException(status_code=404, detail="Agreement not found.")
    if a.get("accepted_at"):
        raise HTTPException(status_code=409, detail="You have already accepted this agreement.")
    res = await db.vendor_agreements.update_one({"id": agreement_id, "accepted_at": None},
                                                {"$set": {"accepted_at": now_iso(), "accepted_by": user["id"]}})
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="You have already accepted this agreement.")
    await log_audit(user, "agreement_accepted", "vendor_agreement", agreement_id, new_value={"version": a["version"]}, request=request)
    return _public(await db.vendor_agreements.find_one({"id": agreement_id}, {"_id": 0}))


async def vendor_view(vendor_id: str) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = await db.vendor_agreements.find({"vendor_id": vendor_id, "status": "approved"}, {"_id": 0}).sort([("effective_from", -1), ("version", -1)]).to_list(200)
    current = await effective_agreement(vendor_id, today)
    return {"current": _public(current) if current else None,
            "agreements": [{**_public(r), "is_current": bool(current and current["id"] == r["id"])} for r in rows]}
