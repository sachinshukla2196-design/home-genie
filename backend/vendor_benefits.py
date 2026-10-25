"""Vendor advancement: admin-configured benefit programmes, eligibility over a documented review window, and approval of benefits.

Rules:
- A programme lists criteria an admin configured (for example, a minimum number of orders or a maximum cancellation rate) and a
  review window in days. The window ends today (UTC) and covers the last `review_days` days, inclusive.
- Metrics come from the same calculations as the vendor dashboard. A metric with no data is reported as null and its criterion is
  unmet, so a vendor with no history is never shown as meeting a target.
- A benefit is proposed by one finance admin and approved by a different one. Approval re-checks eligibility on the server.
- Approving a benefit only records it. It does not change any ledger entry, commission or agreement. Money rules are changed only
  through the commercial agreements in commercial_terms.py, by an admin.
- Vendors can read their own eligibility and benefit status. They cannot propose, approve or edit anything.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core import db, new_id, now_iso, log_audit
from finance_routes import require_finance
from vendor_dashboard import vendor_dashboard as _dashboard
from vendor_routes import require_approved_vendor

router = APIRouter(prefix="/api", tags=["vendor"])

METRICS = {"orders": "min", "order_value_paise": "min", "delivered_rate": "min", "cancellation_rate": "max", "return_rate": "max"}
GRANT_OPEN = ("proposed", "review_requested")


class Criterion(BaseModel):
    metric: str
    value: float = Field(ge=0)


class ProgrammeIn(BaseModel):
    key: str = Field(min_length=3, max_length=40, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=500)
    review_days: int = Field(ge=1, le=365)
    criteria: List[Criterion] = Field(min_length=1, max_length=8)
    benefit_text: str = Field(min_length=5, max_length=500)


class DecisionIn(BaseModel):
    action: str                          # approve / reject / request_review
    note: str = Field(default="", max_length=500)
    effective_from: Optional[str] = None  # YYYY-MM-DD, approvals only (defaults to today)
    expires_at: Optional[str] = None      # YYYY-MM-DD, approvals only, optional


class ProposalIn(BaseModel):
    vendor_id: str
    programme_id: str
    note: str = Field(default="", max_length=500)


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


async def metrics_for(vendor: dict, date_from: str, date_to: str) -> dict:
    """The review-window metrics, from the dashboard calculation. Null where there is no data to measure."""
    d = await _dashboard(range="custom", date_from=date_from, date_to=date_to, user={"_vendor": vendor})
    n = d["sales"]["orders"]
    cancelled = d["cancellation_return"]["cancelled_or_rejected"]
    returned = d["cancellation_return"]["returned_or_failed"]
    delivered = d["orders_by_status"].get("delivered", 0)
    return {"orders": n, "order_value_paise": d["sales"]["order_value_paise"],
            "delivered_rate": _rate(delivered, n - cancelled), "cancellation_rate": _rate(cancelled, n), "return_rate": _rate(returned, n)}


def review_window(review_days: int) -> tuple:
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=review_days - 1)).isoformat(), today.isoformat()


async def evaluate(programme: dict, vendor: dict) -> dict:
    date_from, date_to = review_window(programme["review_days"])
    m = await metrics_for(vendor, date_from, date_to)
    crit = []
    for c in programme["criteria"]:
        measured = m.get(c["metric"])
        met = measured is not None and (measured >= c["value"] if METRICS[c["metric"]] == "min" else measured <= c["value"])
        crit.append({"metric": c["metric"], "rule": METRICS[c["metric"]], "required": c["value"], "measured": measured, "met": met,
                     "reason": None if measured is not None else "No data in the review period."})
    return {"programme_id": programme["id"], "key": programme["key"], "title": programme["title"], "review_from": date_from,
            "review_to": date_to, "criteria": crit, "eligible": bool(crit) and all(c["met"] for c in crit), "metrics": m}


# ------------------------------------------------------------------ admin: programmes and proposals
@router.post("/admin/benefits/programmes")
async def create_programme(body: ProgrammeIn, request: Request, admin: dict = Depends(require_finance)):
    for c in body.criteria:
        if c.metric not in METRICS:
            raise HTTPException(status_code=400, detail=f"Unknown metric '{c.metric}'.")
    if METRICS and any(c.metric in ("cancellation_rate", "return_rate", "delivered_rate") and c.value > 100 for c in body.criteria):
        raise HTTPException(status_code=400, detail="Rates are percentages between 0 and 100.")
    doc = {"id": new_id(), "key": body.key, "title": body.title.strip(), "description": body.description.strip(), "review_days": body.review_days,
           "criteria": [c.model_dump() for c in body.criteria], "benefit_text": body.benefit_text.strip(), "active": True,
           "created_by": admin["id"], "created_at": now_iso()}
    try:
        await db.benefit_programmes.insert_one(dict(doc))
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="A programme with this key already exists.")
    await log_audit(admin, "benefit_programme_created", "benefit_programme", doc["id"], new_value={"key": body.key}, request=request)
    return doc


@router.get("/admin/benefits/programmes")
async def list_programmes(admin: dict = Depends(require_finance)):
    return {"programmes": await db.benefit_programmes.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)}


@router.post("/admin/benefits/proposals")
async def propose(body: ProposalIn, request: Request, admin: dict = Depends(require_finance)):
    vendor = await db.vendors.find_one({"id": body.vendor_id}, {"_id": 0})
    programme = await db.benefit_programmes.find_one({"id": body.programme_id, "active": True}, {"_id": 0})
    if not vendor or not programme:
        raise HTTPException(status_code=404, detail="Vendor or programme not found.")
    if await db.benefit_grants.find_one({"vendor_id": body.vendor_id, "programme_id": body.programme_id, "status": {"$in": list(GRANT_OPEN)}}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="This benefit already has an open proposal for this vendor.")
    snapshot = await evaluate(programme, vendor)                # recorded from the server's own numbers, never from the request
    doc = {"id": new_id(), "vendor_id": body.vendor_id, "programme_id": body.programme_id, "programme_key": programme["key"],
           "status": "proposed", "proposed_by": admin["id"], "proposed_at": now_iso(), "proposal_note": body.note.strip(),
           "evaluation": snapshot, "decided_by": None, "decided_at": None, "decision_note": "", "applied": False}
    await db.benefit_grants.insert_one(dict(doc))
    await log_audit(admin, "benefit_proposed", "benefit_grant", doc["id"], new_value={"vendor_id": body.vendor_id, "programme": programme["key"], "eligible": snapshot["eligible"]}, request=request)
    return doc


@router.post("/admin/benefits/proposals/{gid}/decide")
async def decide(gid: str, body: DecisionIn, request: Request, admin: dict = Depends(require_finance)):
    g = await db.benefit_grants.find_one({"id": gid}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Proposal not found.")
    if g["status"] not in GRANT_OPEN:
        raise HTTPException(status_code=400, detail=f"This proposal is already '{g['status']}'.")
    if body.action not in ("approve", "reject", "request_review"):
        raise HTTPException(status_code=400, detail="Unknown action.")
    if body.action != "approve" and len(body.note.strip()) < 5:
        raise HTTPException(status_code=400, detail="Please give a reason (at least 5 characters).")
    target = {"approve": "approved", "reject": "rejected", "request_review": "review_requested"}[body.action]
    dates = {}
    if body.action == "approve":
        today = datetime.now(timezone.utc).date()
        try:
            eff = datetime.strptime(body.effective_from, "%Y-%m-%d").date() if body.effective_from else today
            exp = datetime.strptime(body.expires_at, "%Y-%m-%d").date() if body.expires_at else None
        except ValueError:
            raise HTTPException(status_code=400, detail="Dates must look like 2026-11-01.")
        if exp and exp <= eff:
            raise HTTPException(status_code=400, detail="The expiry must be after the effective date.")
        dates = {"effective_from": eff.isoformat(), "expires_at_date": exp.isoformat() if exp else None}
    if body.action == "approve":
        if g["proposed_by"] == admin["id"]:
            raise HTTPException(status_code=403, detail="A different finance admin must approve this benefit.")
        programme = await db.benefit_programmes.find_one({"id": g["programme_id"]}, {"_id": 0})
        vendor = await db.vendors.find_one({"id": g["vendor_id"]}, {"_id": 0})
        if not programme or not vendor:
            raise HTTPException(status_code=404, detail="Vendor or programme not found.")
        now = await evaluate(programme, vendor)
        if not now["eligible"]:
            raise HTTPException(status_code=400, detail="The vendor does not meet every criterion in the current review period.")
    else:
        now = g["evaluation"]
    changes = {"status": target, "decided_by": admin["id"], "decided_at": now_iso(), "decision_note": body.note.strip(), "evaluation": now, **dates}
    res = await db.benefit_grants.update_one({"id": gid, "status": {"$in": list(GRANT_OPEN)}}, {"$set": changes})
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="This proposal was just decided by someone else. Reload and try again.")
    await log_audit(admin, f"benefit_{target}", "benefit_grant", gid, old_value={"status": g["status"]}, new_value={"status": target}, request=request)
    return await db.benefit_grants.find_one({"id": gid}, {"_id": 0})


def _view(g: dict) -> dict:
    """A grant as shown to admins and vendors. An approved benefit past its expiry date reads as expired."""
    today = datetime.now(timezone.utc).date().isoformat()
    status = g["status"]
    if status == "approved" and g.get("expires_at_date") and g["expires_at_date"] < today:
        status = "expired"
    return {**{k: v for k, v in g.items() if k not in ("_id",)}, "status": status, "applied": False}


@router.get("/admin/benefits/proposals")
async def list_proposals(status: Optional[str] = None, admin: dict = Depends(require_finance)):
    q = {"status": status} if status else {}
    rows = await db.benefit_grants.find(q, {"_id": 0}).sort("proposed_at", -1).to_list(300)
    names = {v["id"]: v for v in await db.vendors.find({"id": {"$in": list({r["vendor_id"] for r in rows})}}, {"_id": 0, "id": 1, "vendor_code": 1, "business_name": 1}).to_list(300)}
    return {"proposals": [{**_view(r), "vendor_code": (names.get(r["vendor_id"]) or {}).get("vendor_code"),
                           "business_name": (names.get(r["vendor_id"]) or {}).get("business_name")} for r in rows]}


@router.get("/admin/benefits/eligibility")
async def eligibility_for_programme(programme_id: str, admin: dict = Depends(require_finance)):
    """Every approved or active vendor, measured against one programme over its review window. Null metrics mean no data."""
    programme = await db.benefit_programmes.find_one({"id": programme_id}, {"_id": 0})
    if not programme:
        raise HTTPException(status_code=404, detail="Programme not found.")
    vendors = await db.vendors.find({"status": {"$in": ["approved", "active"]}}, {"_id": 0}).sort("vendor_code", 1).to_list(200)
    rows = []
    for v in vendors:
        ev = await evaluate(programme, v)
        open_grant = await db.benefit_grants.find_one({"vendor_id": v["id"], "programme_id": programme_id, "status": {"$in": list(GRANT_OPEN)}}, {"_id": 0, "id": 1, "status": 1})
        rows.append({"vendor_id": v["id"], "vendor_code": v["vendor_code"], "business_name": v["business_name"], **ev,
                     "open_proposal": open_grant})
    return {"programme": programme, "vendors": rows, "review_from": review_window(programme["review_days"])[0],
            "review_to": review_window(programme["review_days"])[1]}


# ------------------------------------------------------------------ vendor: read-only
@router.get("/vendor/advancement/eligibility")
async def vendor_eligibility(user: dict = Depends(require_approved_vendor)):
    v = user["_vendor"]
    programmes = await db.benefit_programmes.find({"active": True}, {"_id": 0}).sort("created_at", 1).to_list(100)
    results = [await evaluate(p, v) for p in programmes]
    grants = await db.benefit_grants.find({"vendor_id": v["id"]}, {"_id": 0, "id": 1, "programme_key": 1, "status": 1, "proposed_at": 1,
                                                                  "decided_at": 1, "decision_note": 1, "effective_from": 1, "expires_at_date": 1,
                                                                  "programme_id": 1}).sort("proposed_at", -1).to_list(100)
    text = {p["key"]: p["benefit_text"] for p in programmes}
    grants = [{**_view(g), "benefit_text": text.get(g["programme_key"], "")} for g in grants]
    return {"programmes": results, "benefits": grants, "note": "Benefits are recorded only after HOME GENIES approves them."}
