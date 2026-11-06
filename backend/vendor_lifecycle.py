"""Vendor lifecycle: the only place where a vendor's status may change.

Every change goes through `move()`. It checks the transition table, then updates the vendor only while its status is still the
one that was checked (an atomic compare-and-set), then appends to the append-only vendor status history.

Roles (enforced by `vendor_routes.require_vendor_user`, `require_approved_vendor` and `require_admin`):
- platform admin: decides applications and status changes, never acts as a vendor on vendor data;
- vendor owner: role `vendor`, owns the vendor record through `vendors.user_id`;
- vendor staff: role `vendor_staff` with a `vendor_members` row; every staff request passes vendor_staff.authorize_staff;
- customers: role `distributor`, never vendor privileges.
"""
import re
from typing import Optional

from fastapi import HTTPException

from core import db, next_sequence, now_iso
from vendor_history import record_vendor_status

STATUSES = ("onboarding", "ready_for_review",                                   # Vendor Pillar: admin-run onboarding
            "invited", "draft", "pending_documents", "submitted", "under_review", "changes_requested",   # legacy self-onboarding
            "approved", "active", "rejected", "suspended")
# Admin-run onboarding (application -> onboarding -> ready_for_review -> super_admin decision). The owner has NO access in these.
ONBOARDING = ("onboarding", "ready_for_review")
# Statuses in which a vendor may sell: products, orders, settlements.
SELLING = ("approved", "active")
# Statuses in which the vendor may only edit contact details (legal and bank changes go through admin).
CONTACT_ONLY = ("approved", "active", "suspended")
# (from, to) -> the minimum actor allowed to make that change: "vendor", "admin" (admin or super_admin) or "super_admin".
TRANSITIONS = {
    ("onboarding", "ready_for_review"): "admin",          # admin submits a complete registration (checklist enforced)
    ("ready_for_review", "approved"): "super_admin",      # final approval
    ("ready_for_review", "onboarding"): "super_admin",    # request changes: back to the admin's onboarding work
    ("ready_for_review", "rejected"): "super_admin",      # final rejection
    ("rejected", "onboarding"): "super_admin",            # reopen a rejected onboarding registration
    ("invited", "draft"): "vendor",
    ("draft", "pending_documents"): "admin",
    ("draft", "submitted"): "vendor",
    ("pending_documents", "submitted"): "vendor",
    ("submitted", "under_review"): "admin",
    ("submitted", "changes_requested"): "admin",
    ("submitted", "approved"): "super_admin",
    ("submitted", "rejected"): "super_admin",
    ("under_review", "changes_requested"): "admin",
    ("under_review", "approved"): "super_admin",
    ("under_review", "rejected"): "super_admin",
    ("changes_requested", "submitted"): "vendor",
    ("rejected", "submitted"): "vendor",
    ("rejected", "approved"): "super_admin",
    ("approved", "active"): "super_admin",
    ("approved", "suspended"): "admin",
    ("active", "suspended"): "admin",
    ("suspended", "approved"): "super_admin",
}
# Admin decision name -> target status. Each needs a reason when `REASON_REQUIRED`.
ADMIN_ACTIONS = {"start_review": "under_review", "request_documents": "pending_documents", "request_changes": "changes_requested",
                 "approve": "approved", "reject": "rejected", "suspend": "suspended", "reinstate": "approved", "activate": "active"}
REASON_REQUIRED = ("request_documents", "request_changes", "reject", "suspend")
# OWNER-LOCKED (Vendor Pillar): final approval, final rejection and reinstatement (and the legacy "activate") restore or refuse
# operational access, so they belong to super_admin alone. admin prepares; support_admin and accounts_admin never decide.
SUPER_ADMIN_ACTIONS = ("approve", "reject", "reinstate", "activate")
# Vendor and vendor-staff logins never carry a HomeGenie status: "green"/"red" mean HomeGenie selling eligibility only.
VENDOR_ACCOUNT_STATUS = "not_applicable"

VENDOR_STAFF_ROLE = "vendor_staff"

def transition_allowed(frm: Optional[str], to: str, actor: str) -> bool:
    need = TRANSITIONS.get((frm, to))
    return need is not None and (need == actor or (need == "admin" and actor == "super_admin"))


def admin_actor(admin: dict) -> str:
    return "super_admin" if admin.get("role") == "super_admin" else "admin"


async def move(vendor: dict, to: str, actor: str, actor_id: str, reason: str = "", internal_note: str = "",
               extra: Optional[dict] = None) -> str:
    """Change a vendor's status. `extra` are profile fields saved in the same atomic update (never a status)."""
    frm = vendor.get("status")
    if not transition_allowed(frm, to, actor):
        raise HTTPException(status_code=400, detail=f"This status change is not allowed: '{frm}' to '{to}'.")
    fields = {**(extra or {}), "status": to, "status_reason": reason, "updated_at": now_iso()}
    res = await db.vendors.update_one({"id": vendor["id"], "status": frm}, {"$set": fields})
    if res.matched_count != 1:
        raise HTTPException(status_code=409, detail="This vendor was just changed by someone else. Reload and try again.")
    await record_vendor_status(vendor["id"], frm, to, actor_id, reason, internal_note)
    return to


VENDOR_CODE = re.compile(r"^VD\d{6}$")


async def migrate(apply: bool = False) -> dict:
    """Repeatable, non-destructive foundation migration. A dry run unless `apply` is True. It never deletes or overwrites data
    except filling a missing vendor_code, and it reports duplicates instead of fixing them."""
    report = {"apply": apply, "duplicates": {}, "backfilled": [], "sequence_moved_to": None, "indexes_failed": []}
    for field in ("id", "user_id", "vendor_code"):
        dups = await db.vendors.aggregate([
            {"$match": {field: {"$type": "string"}}}, {"$group": {"_id": f"${field}", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}]).to_list(100)
        if dups:
            report["duplicates"][field] = [d["_id"] for d in dups]
    missing = await db.vendors.find({"$or": [{"vendor_code": {"$exists": False}}, {"vendor_code": None}, {"vendor_code": ""}]},
                                    {"_id": 0, "id": 1}).to_list(10000)
    for v in missing:
        if apply:
            code = await next_sequence("vendor", "VD", 6)
            await db.vendors.update_one({"id": v["id"]}, {"$set": {"vendor_code": code, "updated_at": now_iso()}})
            report["backfilled"].append(code)
        else:
            report["backfilled"].append("(would assign)")
    codes = [c["vendor_code"] for c in await db.vendors.find({"vendor_code": {"$type": "string"}}, {"_id": 0, "vendor_code": 1}).to_list(100000)]
    top = max((int(c[2:]) for c in codes if VENDOR_CODE.match(c)), default=0)
    counter = await db.counters.find_one({"id": "vendor"}, {"_id": 0, "seq": 1}) or {}
    if top > counter.get("seq", 0):
        report["sequence_moved_to"] = top
        if apply:
            await db.counters.update_one({"id": "vendor"}, {"$max": {"seq": top}}, upsert=True)
    from db_indexes import apply as apply_indexes, plan as plan_indexes     # the single place where indexes change
    if apply:
        result = await apply_indexes()
        report["indexes"] = result
        report["indexes_failed"] = [f["index"] for f in result["failed"]]
    else:
        report["indexes_plan"] = await plan_indexes()                       # read-only
    return report
