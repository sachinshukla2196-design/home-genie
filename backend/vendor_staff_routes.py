"""Vendor staff management: the owner invites, changes, suspends, reactivates and revokes people on their own team.

Only the owner account of a vendor can manage its team. Every lookup is scoped to that owner's vendor, so one vendor can never
reach another vendor's members. Invitations are secret, single-use and expire. Every change is audited.
"""
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core import db, get_current_user, hash_password, new_id, now_iso, next_sequence, log_audit, create_notification, rate_limit, client_ip
from vendor_routes import _mask
from vendor_staff import PERMISSIONS, PRESETS, VENDOR_STAFF_ROLE, validate_role, new_invite_token, hash_token
from vendor_lifecycle import VENDOR_ACCOUNT_STATUS

router = APIRouter(prefix="/api", tags=["vendor"])
INVALID_INVITE = "This invitation is not valid or has expired."
MOBILE = re.compile(r"[6-9]\d{9}")


async def require_owner_account(user: dict = Depends(get_current_user)) -> dict:
    """The vendor owner's account. Staff and every other role are refused."""
    if user.get("role") != "vendor" or user.get("blocked"):
        raise HTTPException(status_code=403, detail="Only the vendor owner can manage staff.")
    v = await db.vendors.find_one({"user_id": user["id"]}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=403, detail="Only the vendor owner can manage staff.")
    return {**user, "_vendor": v}


async def _member_of_owner(owner: dict, mid: str, statuses: tuple) -> dict:
    m = await db.vendor_members.find_one({"id": mid, "vendor_id": owner["_vendor"]["id"]}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=404, detail="Staff member not found.")
    if m["status"] not in statuses:
        raise HTTPException(status_code=400, detail=f"This staff member is '{m['status']}', so this action is not available.")
    return m


async def _claim(mid: str, frm: tuple, changes: dict) -> None:
    """Atomic status change: only succeeds while the member is still in one of the expected states."""
    res = await db.vendor_members.update_one({"id": mid, "status": {"$in": list(frm)}}, {"$set": {**changes, "updated_at": now_iso()}})
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="This staff member was just changed by someone else. Reload and try again.")


def _view(m: dict, user: Optional[dict]) -> dict:
    name = (user or {}).get("full_name") or m.get("full_name", "")
    return {"id": m["id"], "name": name, "mobile": _mask((user or {}).get("mobile") or m.get("mobile")), "role": m["role"],
            "permissions": m.get("permissions", []), "status": m["status"], "invited_at": m.get("invited_at"),
            "accepted_at": m.get("accepted_at"), "invite_expires_at": m.get("invite_expires_at") if m["status"] == "invited" else None,
            "updated_at": m.get("updated_at")}


@router.get("/vendor/staff")
async def list_staff(owner: dict = Depends(require_owner_account)):
    rows = await db.vendor_members.find({"vendor_id": owner["_vendor"]["id"]}, {"_id": 0}).sort("created_at", 1).to_list(200)
    people = {u["id"]: u for u in await db.users.find({"id": {"$in": [r["user_id"] for r in rows if r.get("user_id")]}},
                                                      {"_id": 0, "id": 1, "full_name": 1, "mobile": 1}).to_list(200)}
    return {"staff": [_view(r, people.get(r.get("user_id"))) for r in rows], "presets": PRESETS, "permissions": PERMISSIONS}


class InviteIn(BaseModel):
    mobile: str
    full_name: str = Field(min_length=2, max_length=80)
    role: str
    permissions: List[str] = []


@router.post("/vendor/staff/invitations")
async def invite_staff(body: InviteIn, request: Request, owner: dict = Depends(require_owner_account)):
    mobile = body.mobile.strip()
    if not MOBILE.fullmatch(mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    if await db.users.find_one({"mobile": mobile}):
        raise HTTPException(status_code=400, detail="An account with this mobile already exists. Staff need a new account, so use a different number.")
    vid = owner["_vendor"]["id"]
    if await db.vendor_members.find_one({"vendor_id": vid, "mobile": mobile, "status": {"$in": ["invited", "active", "suspended"]}}):
        raise HTTPException(status_code=409, detail="This number is already on your team or has a pending invitation.")
    perms = validate_role(body.role, body.permissions)
    token, token_hash, expires = new_invite_token()
    now = now_iso()
    m = {"id": new_id(), "vendor_id": vid, "user_id": None, "mobile": mobile, "full_name": body.full_name.strip(), "role": body.role,
         "permissions": perms, "status": "invited", "token_hash": token_hash, "invite_expires_at": expires.isoformat(),
         "invited_by": owner["id"], "invited_at": now, "accepted_at": None, "created_at": now, "updated_at": now}
    await db.vendor_members.insert_one(dict(m))
    await log_audit(owner, "vendor_staff_invited", "vendor_member", m["id"], new_value={"role": body.role, "permissions": perms}, request=request)
    return {"id": m["id"], "token": token, "expires_at": m["invite_expires_at"]}


@router.post("/vendor/staff/{mid}/resend")
async def resend_invite(mid: str, request: Request, owner: dict = Depends(require_owner_account)):
    m = await _member_of_owner(owner, mid, ("invited",))
    token, token_hash, expires = new_invite_token()           # the old link stops working at once
    await _claim(mid, ("invited",), {"token_hash": token_hash, "invite_expires_at": expires.isoformat()})
    await log_audit(owner, "vendor_staff_invite_resent", "vendor_member", mid, request=request)
    return {"id": m["id"], "token": token, "expires_at": expires.isoformat()}


class RoleIn(BaseModel):
    role: str
    permissions: List[str] = []


@router.put("/vendor/staff/{mid}")
async def change_role(mid: str, body: RoleIn, request: Request, owner: dict = Depends(require_owner_account)):
    m = await _member_of_owner(owner, mid, ("invited", "active", "suspended"))
    perms = validate_role(body.role, body.permissions)
    await _claim(mid, ("invited", "active", "suspended"), {"role": body.role, "permissions": perms})
    await log_audit(owner, "vendor_staff_role_changed", "vendor_member", mid,
                    old_value={"role": m["role"], "permissions": m.get("permissions", [])}, new_value={"role": body.role, "permissions": perms}, request=request)
    return {"ok": True, "role": body.role, "permissions": perms}


async def _notify_member(m: dict, title: str, text: str) -> None:
    if m.get("user_id"):
        await create_notification(m["user_id"], "vendor", title, text)


@router.post("/vendor/staff/{mid}/suspend")
async def suspend_staff(mid: str, request: Request, owner: dict = Depends(require_owner_account)):
    m = await _member_of_owner(owner, mid, ("active",))
    await _claim(mid, ("active",), {"status": "suspended"})
    await _notify_member(m, "Access suspended", "The vendor owner has suspended your access.")
    await log_audit(owner, "vendor_staff_suspended", "vendor_member", mid, old_value={"status": "active"}, new_value={"status": "suspended"}, request=request)
    return {"ok": True, "status": "suspended"}


@router.post("/vendor/staff/{mid}/reactivate")
async def reactivate_staff(mid: str, request: Request, owner: dict = Depends(require_owner_account)):
    m = await _member_of_owner(owner, mid, ("suspended",))
    await _claim(mid, ("suspended",), {"status": "active"})
    await _notify_member(m, "Access restored", "The vendor owner has restored your access.")
    await log_audit(owner, "vendor_staff_reactivated", "vendor_member", mid, old_value={"status": "suspended"}, new_value={"status": "active"}, request=request)
    return {"ok": True, "status": "active"}


@router.delete("/vendor/staff/{mid}")
async def revoke_staff(mid: str, request: Request, owner: dict = Depends(require_owner_account)):
    """Revoke is final: the record stays for the audit trail, the login stops working at once, and the invitation is void."""
    m = await _member_of_owner(owner, mid, ("invited", "active", "suspended"))
    await _claim(mid, ("invited", "active", "suspended"), {"status": "revoked", "token_hash": None, "invite_expires_at": None})
    await _notify_member(m, "Access removed", "The vendor owner has removed your access.")
    await log_audit(owner, "vendor_staff_revoked", "vendor_member", mid, old_value={"status": m["status"]}, new_value={"status": "revoked"}, request=request)
    return {"ok": True, "status": "revoked"}


# ------------------------------------------------------------------ public: accepting an invitation
async def _invite_by_token(token: str) -> dict:
    m = await db.vendor_members.find_one({"token_hash": hash_token(token), "status": "invited"}, {"_id": 0})
    if not m or not m.get("invite_expires_at") or datetime.fromisoformat(m["invite_expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail=INVALID_INVITE)
    return m


@router.get("/vendor/staff/invitation")
async def invitation_details(token: str):
    m = await _invite_by_token(token)
    v = await db.vendors.find_one({"id": m["vendor_id"]}, {"_id": 0, "business_name": 1})
    return {"business_name": (v or {}).get("business_name", ""), "role": m["role"], "mobile_hint": _mask(m["mobile"]),
            "expires_at": m["invite_expires_at"]}


class AcceptIn(BaseModel):
    token: str
    mobile: str
    full_name: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=128)


@router.post("/vendor/staff/accept")
async def accept_invitation(body: AcceptIn, request: Request):
    await rate_limit("staff_accept", client_ip(request))
    m = await _invite_by_token(body.token)
    if body.mobile.strip() != m["mobile"]:
        raise HTTPException(status_code=400, detail=INVALID_INVITE)
    if not (re.search(r"[A-Za-z]", body.password) and re.search(r"\d", body.password)):
        raise HTTPException(status_code=400, detail="Use at least 8 characters with letters and numbers.")
    if await db.users.find_one({"mobile": m["mobile"]}):
        raise HTTPException(status_code=400, detail="An account with this mobile already exists. Ask the vendor owner to invite you again.")
    now = now_iso()
    uid = new_id()
    user = {"id": uid, "distributor_id": await next_sequence("staff", "VS", 6), "full_name": body.full_name.strip(), "mobile": m["mobile"],
            "email": None, "password_hash": hash_password(body.password), "role": VENDOR_STAFF_ROLE, "status": VENDOR_ACCOUNT_STATUS,
            "account_status": "active", "created_at": now, "updated_at": now}
    try:
        await db.users.insert_one(dict(user))
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="An account with this mobile already exists. Ask the vendor owner to invite you again.")
    res = await db.vendor_members.update_one({"id": m["id"], "status": "invited", "token_hash": hash_token(body.token)},
                                             {"$set": {"user_id": uid, "status": "active", "accepted_at": now, "token_hash": None,
                                                       "invite_expires_at": None, "updated_at": now}})
    if res.matched_count != 1:                 # the invitation was used or revoked in the meantime
        await db.users.delete_one({"id": uid})
        raise HTTPException(status_code=400, detail=INVALID_INVITE)
    v = await db.vendors.find_one({"id": m["vendor_id"]}, {"_id": 0, "user_id": 1, "business_name": 1})
    if v:
        await create_notification(v["user_id"], "vendor", "Staff joined", f"{body.full_name.strip()} accepted your invitation as {m['role'].replace('_', ' ')}.")
    await log_audit(user, "vendor_staff_joined", "vendor_member", m["id"], new_value={"role": m["role"]}, request=request)
    return {"ok": True}
