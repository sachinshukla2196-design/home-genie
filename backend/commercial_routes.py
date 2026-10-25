"""Commercial agreements: admin configures and approves; the vendor reads and accepts. See commercial_terms.py for the rules."""
from fastapi import APIRouter, Depends, Request

import commercial_terms as CT
from core import db, require_admin
from finance_routes import require_finance
from vendor_routes import require_approved_vendor

router = APIRouter(prefix="/api", tags=["finance"])


@router.post("/admin/finance/vendors/{vendor_id}/agreements")
async def admin_create_agreement(vendor_id: str, body: CT.AgreementIn, request: Request, admin: dict = Depends(require_finance)):
    return await CT.create_draft(vendor_id, body, admin, request)


@router.get("/admin/finance/vendors/{vendor_id}/agreements")
async def admin_list_agreements(vendor_id: str, admin: dict = Depends(require_admin)):
    rows = await db.vendor_agreements.find({"vendor_id": vendor_id}, {"_id": 0}).sort([("version", -1)]).to_list(200)
    people = {u["id"]: u.get("full_name") for u in await db.users.find({"id": {"$in": list({x for r in rows for x in (r.get("created_by"), r.get("approved_by")) if x})}},
                                                                      {"_id": 0, "id": 1, "full_name": 1}).to_list(200)}
    for r in rows:
        r["created_by_name"] = people.get(r.get("created_by"))
        r["approved_by_name"] = people.get(r.get("approved_by"))
    return {"agreements": rows}


@router.post("/admin/finance/agreements/{aid}/approve")
async def admin_approve_agreement(aid: str, request: Request, admin: dict = Depends(require_finance)):
    return await CT.approve(aid, admin, request)


@router.get("/vendor/finance/terms")
async def vendor_terms(user: dict = Depends(require_approved_vendor)):
    """Read-only: the agreement in force today, and every approved version with its acceptance."""
    return await CT.vendor_view(user["_vendor"]["id"])


@router.post("/vendor/finance/terms/{aid}/accept")
async def vendor_accept_terms(aid: str, request: Request, user: dict = Depends(require_approved_vendor)):
    return await CT.accept(user["_vendor"], aid, user, request)
