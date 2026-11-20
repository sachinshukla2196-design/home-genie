"""Admin-initiated contact changes (Batch 0, H2): an admin can PROPOSE a new mobile/email for an account but can never make it
live on their own, so an admin cannot point an account's login contact at a number or Google account they control.

  propose (admin)   ->  contact_change_requests row "pending"; the LIVE users.mobile / users.email stay unchanged, so OTP login,
                        Google login/linking and every recovery path keep using the old, trusted contact only.
  confirm (holder)  ->  the signed-in account holder proves control of the CURRENT (trusted) mobile with an OTP sent to it.
                        An OTP to the NEW contact proves nothing about consent and is never accepted.
  recovery (review) ->  when the trusted mobile is lost: a super admin who did NOT propose the change approves it with recorded
                        independent evidence (e.g. ID document check reference).
  reject / cancel   ->  the holder may reject; any admin may cancel. Requests expire after REQUEST_DAYS.

The audit trail keeps actor, target, masked old/new values, time, status and confirmation method. OTPs are never stored or logged
(providers.py keeps only a peppered hash)."""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core import create_notification, db, get_current_user, log_audit, new_id, now_iso, rate_limit, require_admin

router = APIRouter(prefix="/api", tags=["contact-change"])

REQUEST_DAYS = 7
OTP_PURPOSE = "contact_change"
CONTACT_FIELDS = ("mobile", "email")


def mask_email(e: Optional[str]) -> str:
    e = str(e or "").strip()
    if not e:
        return ""
    if "@" not in e:
        return "*" * len(e)
    name, dom = e.split("@", 1)
    return (name[:1] + "***@" + dom) if name else "***@" + dom


def mask_mobile(m: Optional[str]) -> str:
    m = str(m or "").strip()
    return ("XXXXXX" + m[-4:]) if len(m) > 4 else "*" * len(m)


_MASK = {"mobile": mask_mobile, "email": mask_email}


def _masked(values: dict) -> dict:
    return {k: _MASK[k](v) for k, v in values.items()}


def _public(req: dict) -> dict:
    """What an admin or the holder may see: masked values only."""
    return {"id": req["id"], "user_id": req["user_id"], "status": req["status"], "fields": sorted(req["new"]),
            "old": _masked(req["old"]), "new": _masked(req["new"]), "requested_by": req.get("requested_by"),
            "requested_at": req.get("requested_at"), "expires_at": req.get("expires_at"),
            "confirmation_method": req.get("confirmation_method"), "decided_at": req.get("decided_at")}


async def _notify_trusted(user: dict, title: str, message: str) -> None:
    """In-app notice plus a best-effort SMS to the account's CURRENT (trusted) mobile. Never raises."""
    await create_notification(user["id"], "security", title, message)
    from providers import send_security_notice_sms
    await send_security_notice_sms(user.get("mobile") or "", f"HOME GENIES: {title}. {message}")


async def propose_contact_change(admin: dict, user: dict, new: dict, request: Optional[Request] = None) -> dict:
    """Called by PUT /api/admin/users/{id} after validation and duplicate checks. Supersedes any earlier pending request."""
    now = datetime.now(timezone.utc)
    old = {k: user.get(k) for k in new}
    await db.contact_change_requests.update_many({"user_id": user["id"], "status": "pending"},
                                                 {"$set": {"status": "superseded", "decided_at": now.isoformat()}})
    req = {"id": new_id(), "user_id": user["id"], "status": "pending", "old": old, "new": new,
           "requested_by": admin["id"], "requested_by_role": admin.get("role"), "requested_at": now.isoformat(),
           "expires_at": (now + timedelta(days=REQUEST_DAYS)).isoformat(), "history": [{"status": "pending", "at": now.isoformat(), "by": admin["id"]}]}
    await db.contact_change_requests.insert_one(dict(req))
    await db.users.update_one({"id": user["id"]}, {"$set": {"pending_contact_change": {
        "request_id": req["id"], "fields": sorted(new), "new": _masked(new), "requested_at": req["requested_at"],
        "expires_at": req["expires_at"]}}})
    await log_audit(admin, "contact_change_requested", "user", user["id"],
                    old_value=_masked(old), new_value={**_masked(new), "status": "pending", "request_id": req["id"]}, request=request)
    await _notify_trusted(user, "Contact change requested",
                          f"HOME GENIES asked to change your {' and '.join(sorted(new))}. Nothing changes until you confirm it "
                          "with a code sent to your current mobile. If you did not ask for this, reject it and contact support.")
    return _public(req)


def _expired(req: dict) -> bool:
    try:
        return datetime.fromisoformat(req["expires_at"]) < datetime.now(timezone.utc)
    except (KeyError, ValueError):
        return True


async def _close(req: dict, status: str, actor_id: Optional[str], **extra) -> bool:
    now = now_iso()
    r = await db.contact_change_requests.update_one(
        {"id": req["id"], "status": "pending"},
        {"$set": {"status": status, "decided_at": now, "decided_by": actor_id, **extra},
         "$push": {"history": {"status": status, "at": now, "by": actor_id}}})
    if r.modified_count:
        await db.users.update_one({"id": req["user_id"], "pending_contact_change.request_id": req["id"]},
                                  {"$unset": {"pending_contact_change": ""}})
    return bool(r.modified_count)


async def _pending_for(user_id: str, request_id: Optional[str] = None) -> dict:
    q = {"user_id": user_id, "status": "pending", **({"id": request_id} if request_id else {})}
    req = await db.contact_change_requests.find_one(q, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="There is no pending contact change for this account.")
    if _expired(req):
        await _close(req, "expired", None)
        raise HTTPException(status_code=410, detail="This contact change request has expired. Ask HOME GENIES to request it again.")
    return req


async def _apply(req: dict, method: str, actor: dict, request: Optional[Request], **extra) -> dict:
    """Make the new contact live. Atomic: the request is claimed pending -> confirmed first, and the user is updated only if
    its live contact is still exactly the old one; otherwise the claim is rolled back and nothing changes."""
    new, old = req["new"], req["old"]
    for k, v in new.items():
        if v and await db.users.find_one({k: v, "id": {"$ne": req["user_id"]}}, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"The new {k} is now used by another account. Cancel this request and start again.")
    now = now_iso()
    claim = await db.contact_change_requests.update_one(
        {"id": req["id"], "status": "pending"},
        {"$set": {"status": "confirmed", "decided_at": now, "decided_by": actor["id"], "confirmation_method": method, **extra},
         "$push": {"history": {"status": "confirmed", "at": now, "by": actor["id"], "method": method}}})
    if not claim.modified_count:
        raise HTTPException(status_code=409, detail="This request was already decided. Please reload.")
    flt = {"id": req["user_id"], "pending_contact_change.request_id": req["id"], **{k: old.get(k) for k in new}}
    sets = {**new, "updated_at": now}
    if "mobile" in new:
        sets["mobile_verified"] = False
    if "email" in new:
        sets.update({"email_verified": False, "google_linked": False})
    try:
        r = await db.users.update_one(flt, {"$set": sets, "$unset": {"pending_contact_change": ""}})
    except DuplicateKeyError:
        r = None
    if not r or not r.modified_count:
        await db.contact_change_requests.update_one({"id": req["id"], "status": "confirmed"},
                                                    {"$set": {"status": "pending"}, "$unset": {"decided_at": "", "decided_by": "", "confirmation_method": ""},
                                                     "$push": {"history": {"status": "rolled_back", "at": now_iso(), "by": actor["id"]}}})
        raise HTTPException(status_code=409, detail="The account's contact details changed in the meantime. Cancel this request and start again.")
    await log_audit(actor, "contact_change_confirmed", "user", req["user_id"], old_value=_masked(old),
                    new_value={**_masked(new), "status": "confirmed", "method": method, "request_id": req["id"]}, request=request)
    if "mobile" in new:                       # tell the PREVIOUS trusted number, not the new one
        trusted = old.get("mobile")
    else:
        trusted = (await db.users.find_one({"id": req["user_id"]}, {"_id": 0, "mobile": 1}) or {}).get("mobile")
    await _notify_trusted({"id": req["user_id"], "mobile": trusted}, "Contact details changed",
                          f"Your {' and '.join(sorted(new))} changed. If you did not approve this, contact support immediately.")
    return {"ok": True, "status": "confirmed", "method": method, "fields": sorted(new)}


# ------------------------------------------------------------------ account holder
class ConfirmIn(BaseModel):
    request_id: str
    otp: str = Field(min_length=4, max_length=10)


class RequestRef(BaseModel):
    request_id: str


@router.get("/auth/contact-change")
async def my_contact_change(user: dict = Depends(get_current_user)):
    req = await db.contact_change_requests.find_one({"user_id": user["id"], "status": "pending"}, {"_id": 0})
    if not req or _expired(req):
        return {"pending": None}
    return {"pending": _public(req), "otp_to": mask_mobile(user.get("mobile"))}


@router.post("/auth/contact-change/send-otp")
async def contact_change_send_otp(body: RequestRef, user: dict = Depends(get_current_user)):
    """Sends a code to the account's CURRENT mobile (the trusted contact) — never to the proposed new one."""
    await rate_limit("contact_change_otp", user["id"])
    await _pending_for(user["id"], body.request_id)
    if not user.get("mobile"):
        raise HTTPException(status_code=409, detail="This account has no trusted mobile. Ask HOME GENIES for a reviewed recovery.")
    from providers import otp_create
    await otp_create(user["mobile"], OTP_PURPOSE)
    return {"sent": True, "to": mask_mobile(user["mobile"])}


@router.post("/auth/contact-change/confirm")
async def contact_change_confirm(body: ConfirmIn, request: Request, user: dict = Depends(get_current_user)):
    await rate_limit("contact_change_otp", user["id"])
    req = await _pending_for(user["id"], body.request_id)
    from providers import otp_verify
    try:
        await otp_verify(user.get("mobile") or "", OTP_PURPOSE, body.otp)
    except HTTPException as e:
        if e.status_code in (400, 429):
            await log_audit(user, "contact_change_confirm_failed", "user", user["id"], new_value={"request_id": req["id"]}, request=request)
        raise
    return await _apply(req, "holder_otp_trusted_mobile", user, request)


@router.post("/auth/contact-change/reject")
async def contact_change_reject(body: RequestRef, request: Request, user: dict = Depends(get_current_user)):
    req = await _pending_for(user["id"], body.request_id)
    if not await _close(req, "rejected", user["id"]):
        raise HTTPException(status_code=409, detail="This request was already decided. Please reload.")
    await log_audit(user, "contact_change_rejected", "user", user["id"], new_value={**_masked(req["new"]), "status": "rejected", "request_id": req["id"]}, request=request)
    return {"ok": True, "status": "rejected"}


# ------------------------------------------------------------------ admin
class RecoveryIn(BaseModel):
    evidence: str = Field(min_length=20, max_length=1000)


@router.get("/admin/contact-changes")
async def admin_contact_changes(status: str = "pending", admin: dict = Depends(require_admin)):
    rows = await db.contact_change_requests.find({"status": status}, {"_id": 0}).sort("requested_at", -1).to_list(500)
    return [_public(r) for r in rows]


@router.post("/admin/contact-changes/{request_id}/cancel")
async def admin_cancel_contact_change(request_id: str, request: Request, admin: dict = Depends(require_admin)):
    req = await db.contact_change_requests.find_one({"id": request_id, "status": "pending"}, {"_id": 0})
    if not req or not await _close(req, "cancelled", admin["id"]):
        raise HTTPException(status_code=404, detail="No pending request with this id.")
    await log_audit(admin, "contact_change_cancelled", "user", req["user_id"], new_value={**_masked(req["new"]), "status": "cancelled", "request_id": request_id}, request=request)
    return {"ok": True, "status": "cancelled"}


@router.post("/admin/contact-changes/{request_id}/recovery-approve")
async def admin_recovery_approve(request_id: str, body: RecoveryIn, request: Request, admin: dict = Depends(require_admin)):
    """Reviewed recovery for an account holder who has lost their trusted mobile. Only a super admin, never the admin who
    proposed the change, and only with recorded independent evidence."""
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can approve a contact change without the account holder's code.")
    req = await db.contact_change_requests.find_one({"id": request_id, "status": "pending"}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="No pending request with this id.")
    if req["requested_by"] == admin["id"]:
        raise HTTPException(status_code=403, detail="The admin who requested this change cannot also approve it.")
    if _expired(req):
        await _close(req, "expired", None)
        raise HTTPException(status_code=410, detail="This request has expired.")
    return await _apply(req, "recovery_review", admin, request, evidence=body.evidence.strip())
