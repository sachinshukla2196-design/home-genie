"""Public "Apply to sell" and the admin applications inbox (Vendor Pillar, OWNER-LOCKED Option B).

- An application is a RECORD ONLY: it creates no user, no vendor, no login and no session.
- The public answer is always the same neutral message, whether the application is new, a repeat of an open one, caught by the
  honeypot, or uses a mobile/email that already belongs to a customer, HomeGenie or admin. Nothing reveals who has an account.
- One OPEN application per mobile: `open_mobile` is set while the application is open and removed when it closes; a unique partial
  index makes simultaneous submissions safe.
- super_admin and admin review, decline, mark duplicate, correct details and convert to onboarding. support_admin may only read.
  accounts_admin has no access (finance only).
- Conversion never touches an existing account: if the contact belongs to one, the admin must use the business's own number.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from catalogue import PILLARS
from core import (db, now_iso, new_id, next_sequence, require_admin, require_vendor_admin, log_audit, create_notification, rate_limit,
                  client_ip, hash_password)
from pagination import clamp_page, page_meta, text_filter
from vendor_onboarding import BUSINESS_TYPES, INDIAN_STATES, create_onboarding_vendor

router = APIRouter(prefix="/api", tags=["vendor-applications"])

NEUTRAL = ("Thank you. Your application to sell on HOME GENIES has been received. Our partner team reviews every application and "
           "will contact you on the details you gave if it moves forward.")
OPEN = ("new", "in_review")
STATUSES = ("new", "in_review", "converting", "converted", "declined", "duplicate")
VIEW_ROLES = ("super_admin", "admin", "support_admin")
CONVERT_STALE = timedelta(minutes=2)          # a `converting` claim older than this was interrupted and may be taken over
MOBILE = re.compile(r"[6-9]\d{9}")
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class ApplicationIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    business_type: str
    description: str = Field(min_length=20, max_length=1000)
    categories: List[str] = Field(min_length=1, max_length=4)
    contact_name: str = Field(min_length=2, max_length=80)
    mobile: str
    email: str = Field(default="", max_length=120)
    city: str = Field(min_length=2, max_length=60)
    state: str
    website: str = Field(default="", max_length=200)
    consent: bool = False
    # OWNER DECISION: the applicant chooses the vendor-panel password while applying. It is stored ONLY as a bcrypt hash on the
    # application, and it opens nothing until a super admin approves (the owner account stays `pending_approval` until then).
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(max_length=128)
    company_fax: str = Field(default="", max_length=200)      # honeypot: hidden from people, filled in by bots


def _clean(body: ApplicationIn) -> dict:
    mobile = body.mobile.strip()
    email = body.email.strip().lower()
    website = body.website.strip()
    if body.business_type not in BUSINESS_TYPES:
        raise HTTPException(status_code=400, detail="Choose a business type from the list.")
    if any(c not in PILLARS for c in body.categories):
        raise HTTPException(status_code=400, detail="Choose categories from the four HOME GENIES pillars.")
    if not MOBILE.fullmatch(mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    if email and not EMAIL.fullmatch(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address, or leave it blank.")
    if body.state not in INDIAN_STATES:
        raise HTTPException(status_code=400, detail="Choose a state from the list.")
    if website and (not website.startswith("https://") or any(ch in website for ch in " <>\"'")):
        raise HTTPException(status_code=400, detail="Website must be a full https:// address, or leave it blank.")
    if not body.consent:
        raise HTTPException(status_code=400, detail="Please accept the terms and privacy policy to apply.")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="The passwords do not match.")
    if not (re.search(r"[A-Za-z]", body.password) and re.search(r"\d", body.password)):
        raise HTTPException(status_code=400, detail="Use a password of at least 8 characters with letters and numbers.")
    for label, value in (("Business name", body.business_name), ("Your name", body.contact_name), ("City", body.city)):
        if any(ch in value for ch in "<>") or not value.strip():
            raise HTTPException(status_code=400, detail=f"{label} contains characters that are not allowed.")
    return {"business_name": body.business_name.strip(), "business_type": body.business_type, "description": body.description.strip(),
            "categories": [c for c in PILLARS if c in body.categories], "contact_name": body.contact_name.strip(), "mobile": mobile,
            "email": email or None, "city": body.city.strip(), "state": body.state, "website": website or None}


@router.post("/vendor-applications")
async def apply_to_sell(body: ApplicationIn, request: Request):
    await rate_limit("vendor_apply", client_ip(request))
    data = _clean(body)                                         # input errors are about the form, never about other people
    if body.company_fax.strip():                                # honeypot tripped: same answer, nothing stored
        return {"ok": True, "message": NEUTRAL}
    now = now_iso()
    app = {"id": new_id(), "number": await next_sequence("vendor_application", "VA", 6), **data, "status": "new",
           "password_hash": hash_password(body.password),
           "open_mobile": data["mobile"], "consent_at": now, "source": "public_form",
           "history": [{"at": now, "by": None, "action": "submitted", "note": ""}], "created_at": now, "updated_at": now}
    try:
        await db.vendor_applications.insert_one(dict(app))
    except DuplicateKeyError:                                   # an open application for this mobile already exists
        return {"ok": True, "message": NEUTRAL}
    for a in await db.users.find({"role": {"$in": ["super_admin", "admin"]}}, {"_id": 0, "id": 1}).to_list(30):
        await create_notification(a["id"], "vendor", "New vendor application", f"{data['business_name']} applied to sell ({app['number']}).",
                                  meta={"application_id": app["id"]})
    return {"ok": True, "message": NEUTRAL}


# ------------------------------------------------------------------ admin inbox
async def _require_view(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in VIEW_ROLES:
        raise HTTPException(status_code=403, detail="Your role cannot view vendor applications.")
    return admin


def _view(a: dict) -> dict:
    out = {k: v for k, v in a.items() if k not in ("_id", "open_mobile", "password_hash")}      # the hash never leaves the server
    out["applicant_password_set"] = bool(a.get("password_hash"))
    return out


@router.get("/admin/vendor-applications")
async def list_applications(status: str = "open", q: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None,
                            admin: dict = Depends(_require_view)):
    query = {}
    if status == "open":
        query["status"] = {"$in": list(OPEN)}
    elif status != "all":
        if status not in STATUSES:
            raise HTTPException(status_code=400, detail="Unknown status.")
        query["status"] = status
    tf = text_filter(q)
    if tf:
        query["$or"] = [{"business_name": tf}, {"contact_name": tf}, {"mobile": tf}, {"email": tf}, {"number": tf}, {"city": tf}]
    page, page_size = clamp_page(page, page_size)
    total = await db.vendor_applications.count_documents(query)
    rows = await db.vendor_applications.find(query, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    counts = {r["_id"]: r["n"] for r in await db.vendor_applications.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}]).to_list(10)}
    return {"items": [_view(r) for r in rows], **page_meta(total, page, page_size), "counts": counts}


async def _application(aid: str) -> dict:
    a = await db.vendor_applications.find_one({"id": aid}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Application not found.")
    return a


async def _account_match(a: dict) -> Optional[dict]:
    """Admin-only: does the contact belong to an existing account? (Never shown to the applicant.)"""
    ors = [{"mobile": a["mobile"]}] + ([{"email": a["email"]}] if a.get("email") else [])
    q = {"$or": ors}
    if a.get("converted_vendor_id"):
        v = await db.vendors.find_one({"id": a["converted_vendor_id"]}, {"_id": 0, "user_id": 1})
        if v:
            q["id"] = {"$ne": v["user_id"]}
    u = await db.users.find_one(q, {"_id": 0, "role": 1, "mobile": 1, "email": 1})
    if not u:
        return None
    kind = {"distributor": "customer / HomeGenie", "vendor": "vendor", "vendor_staff": "vendor staff"}.get(u.get("role"), "HOME GENIES staff")
    return {"kind": kind, "matches": [f for f in ("mobile", "email") if a.get(f) and u.get(f) == a.get(f)]}


@router.get("/admin/vendor-applications/{aid}")
async def get_application(aid: str, admin: dict = Depends(_require_view)):
    a = await _application(aid)
    others = await db.vendor_applications.find({"mobile": a["mobile"], "id": {"$ne": aid}}, {"_id": 0, "id": 1, "number": 1, "status": 1,
                                                                                             "created_at": 1}).sort("created_at", -1).to_list(10)
    return {**_view(a), "existing_account": await _account_match(a), "other_applications": others}


class ApplicationEdit(BaseModel):
    business_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    contact_name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    mobile: Optional[str] = None
    email: Optional[str] = Field(default=None, max_length=120)
    city: Optional[str] = Field(default=None, min_length=2, max_length=60)
    state: Optional[str] = None
    note: str = Field(default="", max_length=300)


@router.put("/admin/vendor-applications/{aid}")
async def edit_application(aid: str, body: ApplicationEdit, request: Request, admin: dict = Depends(require_vendor_admin)):
    """Correct the applicant's details (e.g. replace a personal number with the business's own) before converting."""
    a = await _application(aid)
    if a["status"] not in OPEN:
        raise HTTPException(status_code=409, detail="Only an open application can be edited.")
    sets = {}
    for k in ("business_name", "contact_name", "city"):
        val = getattr(body, k)
        if val is not None:
            sets[k] = val.strip()
    if body.mobile is not None:
        if not MOBILE.fullmatch(body.mobile.strip()):
            raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
        sets["mobile"] = sets["open_mobile"] = body.mobile.strip()
    if body.email is not None:
        e = body.email.strip().lower()
        if e and not EMAIL.fullmatch(e):
            raise HTTPException(status_code=400, detail="Enter a valid email address, or leave it blank.")
        sets["email"] = e or None
    if body.state is not None:
        if body.state not in INDIAN_STATES:
            raise HTTPException(status_code=400, detail="Choose a state from the list.")
        sets["state"] = body.state
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to change.")
    event = {"at": now_iso(), "by": admin["id"], "action": "edited", "note": body.note.strip() or ", ".join(sorted(k for k in sets if k != "open_mobile"))}
    try:
        res = await db.vendor_applications.update_one({"id": aid, "status": {"$in": list(OPEN)}},
                                                      {"$set": {**sets, "updated_at": now_iso()}, "$push": {"history": event}})
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="Another open application already uses this mobile number.")
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="This application was just changed. Reload and try again.")
    await log_audit(admin, "vendor_application_edited", "vendor_application", aid, new_value={"fields": sorted(sets)}, request=request)
    return await get_application(aid, admin)


class ApplicationAction(BaseModel):
    action: str                                       # review | decline | duplicate | convert
    reason: str = Field(default="", max_length=500)
    duplicate_of: Optional[str] = None                # application number


async def _close(aid: str, frm: tuple, status: str, admin: dict, note: str, extra: Optional[dict] = None) -> bool:
    res = await db.vendor_applications.update_one(
        {"id": aid, "status": {"$in": list(frm)}},
        {"$set": {"status": status, "decided_by": admin["id"], "decided_at": now_iso(), "updated_at": now_iso(), **(extra or {})},
         "$unset": {"open_mobile": ""}, "$push": {"history": {"at": now_iso(), "by": admin["id"], "action": status, "note": note}}})
    return res.modified_count == 1


@router.post("/admin/vendor-applications/{aid}/action")
async def application_action(aid: str, body: ApplicationAction, request: Request, admin: dict = Depends(require_vendor_admin)):
    a = await _application(aid)
    reason = body.reason.strip()
    if body.action == "review":
        res = await db.vendor_applications.update_one(
            {"id": aid, "status": "new"},
            {"$set": {"status": "in_review", "reviewer_id": admin["id"], "updated_at": now_iso()},
             "$push": {"history": {"at": now_iso(), "by": admin["id"], "action": "in_review", "note": reason}}})
        if res.modified_count != 1:
            raise HTTPException(status_code=409, detail="Only a new application can be moved into review.")
    elif body.action == "decline":
        if len(reason) < 5:
            raise HTTPException(status_code=400, detail="Give a reason for declining (at least 5 characters).")
        if not await _close(aid, OPEN, "declined", admin, reason, {"decline_reason": reason}):
            raise HTTPException(status_code=409, detail="Only an open application can be declined.")
    elif body.action == "duplicate":
        dup = (body.duplicate_of or "").strip().upper()
        other = await db.vendor_applications.find_one({"number": dup, "id": {"$ne": aid}}, {"_id": 0, "id": 1, "number": 1}) if dup else None
        if not other:
            raise HTTPException(status_code=400, detail="Enter the number of the application this one duplicates (e.g. VA000012).")
        if not await _close(aid, OPEN, "duplicate", admin, reason or f"Duplicate of {other['number']}", {"duplicate_of": other["number"]}):
            raise HTTPException(status_code=409, detail="Only an open application can be marked as a duplicate.")
    elif body.action == "convert":
        return await _convert(a, admin, request)
    else:
        raise HTTPException(status_code=400, detail="Unknown action.")
    await log_audit(admin, f"vendor_application_{body.action}", "vendor_application", aid, new_value={"reason": reason}, request=request)
    return await get_application(aid, admin)


async def _convert(a: dict, admin: dict, request: Request) -> dict:
    """Accept the application into onboarding. Atomic claim (one winner); every step is idempotent, so a retry after an
    interruption (status stays `converting`) completes the same vendor instead of creating another."""
    if a["status"] in OPEN:
        if await _account_match(a):
            raise HTTPException(status_code=409, detail="This applicant's mobile or email already belongs to an existing HOME GENIES account. "
                                                        "Existing accounts are never converted: edit the application to use the business's own "
                                                        "mobile number and email, then convert.")
        claim = await db.vendor_applications.update_one(
            {"id": a["id"], "status": {"$in": list(OPEN)}},
            {"$set": {"status": "converting", "converting_by": admin["id"], "converting_at": now_iso(), "updated_at": now_iso()},
             "$push": {"history": {"at": now_iso(), "by": admin["id"], "action": "converting", "note": ""}}})
        if claim.modified_count != 1:
            raise HTTPException(status_code=409, detail="This application was just changed by someone else. Reload and try again.")
    elif a["status"] == "converting":
        # Only an interrupted conversion (stale claim) may be resumed, and only by one request at a time.
        stale = (datetime.now(timezone.utc) - CONVERT_STALE).isoformat()
        takeover = await db.vendor_applications.update_one(
            {"id": a["id"], "status": "converting", "$or": [{"converting_at": {"$lt": stale}}, {"converting_at": {"$exists": False}}]},
            {"$set": {"converting_by": admin["id"], "converting_at": now_iso(), "updated_at": now_iso()},
             "$push": {"history": {"at": now_iso(), "by": admin["id"], "action": "conversion_resumed", "note": ""}}})
        if takeover.modified_count != 1:
            raise HTTPException(status_code=409, detail="This application is being converted right now. Reload in a moment.")
    else:
        raise HTTPException(status_code=409, detail="Only an open application can be converted to onboarding.")
    try:
        vendor = await create_onboarding_vendor(business_name=a["business_name"], contact_name=a["contact_name"], mobile=a["mobile"],
                                                email=a.get("email"), admin=admin, application=a, request=request)
    except HTTPException:
        await db.vendor_applications.update_one({"id": a["id"], "status": "converting"},     # nothing was created: reopen it
                                                {"$set": {"status": "in_review", "updated_at": now_iso()},
                                                 "$push": {"history": {"at": now_iso(), "by": admin["id"], "action": "conversion_failed", "note": ""}}})
        raise
    await _close(a["id"], ("converting",), "converted", admin, f"Onboarding {vendor['vendor_code']}", {"converted_vendor_id": vendor["id"]})
    await log_audit(admin, "vendor_application_converted", "vendor_application", a["id"], new_value={"vendor_id": vendor["id"]}, request=request)
    return {**(await get_application(a["id"], admin)), "vendor_id": vendor["id"], "vendor_code": vendor["vendor_code"]}
