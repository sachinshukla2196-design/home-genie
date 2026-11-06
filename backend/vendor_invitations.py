"""Vendor owner invitations: the owner sets their own password through a secure, time-limited, single-use link.

- The token is 256 random bits, shown once to the admin (and sent by e-mail only when e-mail delivery is configured), and only its
  SHA-256 hash is stored. Tokens are never written to logs or audit entries.
- An invitation expires after INVITE_HOURS. Issuing a new one (resend) revokes the previous one at once, so an old link stops working.
- Accepting uses an atomic claim, so the same link cannot be used twice, even by two requests at the same time.
- A vendor account is created with an unguessable random password and status `invited`, so nobody can sign in until the owner accepts.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from core import db, hash_password, new_id, now_iso, log_audit, rate_limit, client_ip, require_admin, require_vendor_admin, send_email, EMAIL_KEY
from vendor_staff import hash_token

router = APIRouter(prefix="/api", tags=["vendor"])
INVITE_HOURS = 72
GENERIC = "This invitation is not valid or has expired. Ask HOME GENIES for a new one."


def new_token() -> tuple:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token), datetime.now(timezone.utc) + timedelta(hours=INVITE_HOURS)


async def issue(user: dict, vendor: dict, admin: dict, request=None) -> dict:
    """Create a fresh owner invitation and revoke any earlier pending one. Returns the token once, with delivery status."""
    token, digest, expires = new_token()
    await db.account_invitations.update_many({"user_id": user["id"], "status": "pending"},
                                             {"$set": {"status": "revoked", "revoked_at": now_iso(), "revoked_by": admin["id"]}})
    await db.account_invitations.insert_one({"id": new_id(), "kind": "vendor_owner", "user_id": user["id"], "vendor_id": vendor["id"],
                                             "token_hash": digest, "status": "pending", "expires_at": expires.isoformat(),
                                             "created_by": admin["id"], "created_at": now_iso()})
    delivered = False
    if EMAIL_KEY and user.get("email"):
        link = f"/vendor/owner-invite?token={token}"          # the front-end origin is added by the sender configuration
        delivered = await send_email(user["email"], "Set up your HOME GENIES vendor account",
                                     f"<p>Open this link within {INVITE_HOURS} hours to set your password: {link}</p>")
    await log_audit(admin, "vendor_owner_invitation_issued", "vendor", vendor["id"], new_value={"expires_at": expires.isoformat(), "emailed": delivered}, request=request)
    return {"token": None if delivered else token, "expires_at": expires.isoformat(), "delivered": delivered}


async def _pending_by_token(token: str) -> dict:
    inv = await db.account_invitations.find_one({"token_hash": hash_token(token), "status": "pending", "kind": "vendor_owner"}, {"_id": 0})
    if not inv or datetime.fromisoformat(inv["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail=GENERIC)
    return inv


def _mask(m: str) -> str:
    return "*" * max(len(m) - 4, 0) + m[-4:] if m else ""


class AcceptIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


@router.post("/admin/vendors/{vendor_id}/owner-invitation")
async def admin_issue_invitation(vendor_id: str, request: Request, admin: dict = Depends(require_vendor_admin)):
    """(Re)issue the owner invitation. The invitation activates operational access, so it is super_admin only and exists only
    for a vendor that has passed final approval. Issuing again replaces the pending link (the old one stops working)."""
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only a super admin can issue the vendor owner invitation.")
    vendor = await db.vendors.find_one({"id": vendor_id}, {"_id": 0})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    from vendor_lifecycle import SELLING
    if vendor["status"] not in SELLING:
        raise HTTPException(status_code=400, detail="The owner invitation is issued only after final approval.")
    user = await db.users.find_one({"id": vendor["user_id"]}, {"_id": 0})
    if not user or user.get("role") != "vendor":
        raise HTTPException(status_code=400, detail="This vendor has no owner account.")
    if user.get("account_status") == "active":
        raise HTTPException(status_code=409, detail="The owner has already set up their account.")
    from vendor_onboarding import ensure_owner_invitation
    out = await ensure_owner_invitation(vendor_id, admin, request, resend=True)
    return {k: out.get(k) for k in ("token", "expires_at", "delivered", "status")}


@router.post("/admin/vendors/{vendor_id}/owner-invitation/revoke")
async def admin_revoke_invitation(vendor_id: str, request: Request, admin: dict = Depends(require_vendor_admin)):
    res = await db.account_invitations.update_many({"vendor_id": vendor_id, "kind": "vendor_owner", "status": "pending"},
                                                   {"$set": {"status": "revoked", "revoked_at": now_iso(), "revoked_by": admin["id"]}})
    await log_audit(admin, "vendor_owner_invitation_revoked", "vendor", vendor_id, new_value={"revoked": res.modified_count}, request=request)
    return {"ok": True, "revoked": res.modified_count}


@router.get("/admin/vendors/{vendor_id}/owner-invitation")
async def admin_invitation_status(vendor_id: str, admin: dict = Depends(require_admin)):
    """Status only. The token is never returned by a listing."""
    inv = await db.account_invitations.find_one({"vendor_id": vendor_id, "kind": "vendor_owner", "status": "pending"}, {"_id": 0, "expires_at": 1, "created_at": 1})
    if inv and datetime.fromisoformat(inv["expires_at"]) <= datetime.now(timezone.utc):
        return {"status": "expired", "expires_at": inv["expires_at"]}
    if inv:
        return {"status": "pending", "expires_at": inv["expires_at"], "issued_at": inv["created_at"]}
    used = await db.account_invitations.find_one({"vendor_id": vendor_id, "kind": "vendor_owner", "status": "used"}, {"_id": 0, "used_at": 1})
    return {"status": "accepted" if used else "none", "accepted_at": (used or {}).get("used_at")}


@router.get("/vendor/invitation/owner")
async def owner_invitation_details(token: str):
    inv = await _pending_by_token(token)
    vendor = await db.vendors.find_one({"id": inv["vendor_id"]}, {"_id": 0, "business_name": 1})
    user = await db.users.find_one({"id": inv["user_id"]}, {"_id": 0, "mobile": 1})
    return {"business_name": (vendor or {}).get("business_name", ""), "mobile_hint": _mask((user or {}).get("mobile", "")),
            "expires_at": inv["expires_at"]}


@router.post("/vendor/invitation/owner/accept")
async def owner_invitation_accept(body: AcceptIn, request: Request):
    await rate_limit("staff_accept", client_ip(request))
    if not (re.search(r"[A-Za-z]", body.password) and re.search(r"\d", body.password)):
        raise HTTPException(status_code=400, detail="Use at least 8 characters with letters and numbers.")
    inv = await _pending_by_token(body.token)
    claim = await db.account_invitations.update_one({"id": inv["id"], "status": "pending"},
                                                    {"$set": {"status": "used", "used_at": now_iso()}})
    if claim.matched_count != 1:              # used or revoked in the meantime
        raise HTTPException(status_code=400, detail=GENERIC)
    await db.users.update_one({"id": inv["user_id"]}, {"$set": {"password_hash": hash_password(body.password), "account_status": "active",
                                                                "invite_accepted_at": now_iso(), "updated_at": now_iso()}})
    await db.vendors.update_one({"id": inv["vendor_id"]}, {"$set": {"owner_activation": "active", "owner_activated_at": now_iso()}})
    user = await db.users.find_one({"id": inv["user_id"]}, {"_id": 0})
    await log_audit(user, "vendor_owner_invitation_accepted", "vendor", inv["vendor_id"], request=request)
    return {"ok": True}
