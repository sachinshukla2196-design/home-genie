"""OPS-01: administrator management, super admin only.

The super admin can add admin / accounts_admin / support_admin accounts, change a team member's role among those three, and
(through the existing block endpoint, which already restricts admin targets to the super admin) disable or re-enable them.

Deliberate limits:
  * No endpoint creates, promotes to, demotes from or edits a super_admin. The number of super admins never changes here.
  * A new admin starts with a TEMPORARY password chosen by the super admin and must replace it at first sign-in
    (core.get_current_user forced-change gate). When SMS is available the replacement also needs a code sent to the new
    admin's own mobile (governance_routes.forced_change_needs_otp), so the super admin never ends up knowing a working
    password for someone else's admin account.
  * Every action is audited with the reason; contact details in the audit are masked.
"""
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from core import db, log_audit, new_id, next_sequence, now_iso, password_update, require_admin
from contact_change import mask_email, mask_mobile

router = APIRouter(prefix="/api/admin/team", tags=["admin-team"])

TEAM_ROLES = ("admin", "accounts_admin", "support_admin")
ALL_ADMIN_ROLES = ("super_admin",) + TEAM_ROLES
TeamRole = Literal["admin", "accounts_admin", "support_admin"]


def require_super_admin(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only the super admin can manage the admin team.")
    return admin


def _public(u: dict) -> dict:
    return {"id": u["id"], "full_name": u.get("full_name"), "role": u.get("role"), "email": u.get("email"),
            "mobile_masked": mask_mobile(u.get("mobile")), "account_status": u.get("account_status") or "active",
            "blocked": bool(u.get("blocked")), "must_change_password": bool(u.get("must_change_password")),
            "created_at": u.get("created_at"), "created_by": u.get("created_by"), "distributor_id": u.get("distributor_id")}


@router.get("")
async def list_team(admin: dict = Depends(require_super_admin)):
    rows = await db.users.find({"role": {"$in": list(ALL_ADMIN_ROLES)}}, {"_id": 0, "password_hash": 0, "env_credential_marker": 0}) \
        .sort("created_at", 1).to_list(500)
    return [_public(u) for u in rows]


class NewAdminIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=80)
    email: str = Field(max_length=120)
    mobile: str
    role: TeamRole
    temporary_password: str = Field(min_length=12, max_length=128)
    reason: str = Field(min_length=5, max_length=300)


@router.post("")
async def create_admin(body: NewAdminIn, request: Request, admin: dict = Depends(require_super_admin)):
    email = body.email.strip().lower()
    mobile = body.mobile.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Enter a valid email address (the new admin signs in with it).")
    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    pw = body.temporary_password
    if not (re.search(r"[A-Za-z]", pw) and re.search(r"\d", pw)):
        raise HTTPException(status_code=400, detail="The temporary password needs letters and numbers (at least 12 characters).")
    if await db.users.find_one({"$or": [{"email": email}, {"mobile": mobile}, {"username": email}]}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="An account with this email or mobile already exists. Accounts are never converted into admins.")
    now = now_iso()
    doc = {"id": new_id(), "distributor_id": await next_sequence("admin_team", "HGADM", 4), "full_name": body.full_name.strip(),
           "email": email, "username": email, "mobile": mobile, **password_update(pw), "must_change_password": True,
           "role": body.role, "status": "green", "account_status": "active", "mobile_verified": False, "email_verified": False,
           "sponsor_id": None, "sponsor_user_id": None, "created_at": now, "updated_at": now, "created_by": admin["id"]}
    try:
        await db.users.insert_one(dict(doc))
    except DuplicateKeyError:
        raise HTTPException(status_code=409, detail="An account with this email or mobile already exists.")
    await log_audit(admin, "admin_account_created", "user", doc["id"],
                    new_value={"role": body.role, "email": mask_email(email), "mobile": mask_mobile(mobile),
                               "reason": body.reason.strip(), "must_change_password": True}, request=request)
    return {**_public(doc), "message": "Admin account created. Give the temporary password to the new admin yourself; "
                                       "they must choose their own password at first sign-in."}


class RoleIn(BaseModel):
    role: TeamRole
    reason: str = Field(min_length=5, max_length=300)


@router.put("/{user_id}/role")
async def change_role(user_id: str, body: RoleIn, request: Request, admin: dict = Depends(require_super_admin)):
    if user_id == admin["id"]:
        raise HTTPException(status_code=403, detail="You cannot change your own role.")
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "id": 1, "role": 1})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u["role"] not in TEAM_ROLES:
        raise HTTPException(status_code=403, detail="Only admin, accounts admin and support admin roles can be changed here. "
                                                    "Members, vendors and the super admin are never converted.")
    if u["role"] == body.role:
        return {"ok": True, "role": body.role, "unchanged": True}
    r = await db.users.update_one({"id": user_id, "role": u["role"]}, {"$set": {"role": body.role, "updated_at": now_iso()}})
    if not r.modified_count:
        raise HTTPException(status_code=409, detail="This account changed just now. Please reload.")
    await log_audit(admin, "admin_role_changed", "user", user_id, old_value={"role": u["role"]},
                    new_value={"role": body.role, "reason": body.reason.strip()}, request=request)
    return {"ok": True, "role": body.role}
