"""Vendor staff: roles, permissions and the per-request check that every staff call goes through.

Model (no new identity system): a staff person is a `users` row with role `vendor_staff`. Their link to a vendor is a
`vendor_members` row, which holds the role, the permissions, the status and the invitation token (stored hashed).

Rules, enforced on every request by `authorize_staff` (called from vendor_routes.require_vendor_user):
- the membership must be `active` (suspended or revoked access stops working on the very next request);
- the vendor it points to is the only vendor the request can touch;
- the request path and method must match an explicit rule, and the membership must hold that rule's permission.
  Anything without a rule is refused, so owner-only areas (profile, bank, documents, team, support) stay owner-only by default.
"""
import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException

from core import db

VENDOR_STAFF_ROLE = "vendor_staff"
INVITE_HOURS = 72

PERMISSIONS = ("products.read", "products.write", "inventory.read", "inventory.write", "orders.read", "orders.fulfil",
               "returns.read", "returns.act", "reports.read", "finance.read")
# Presets. The owner picks one of these, or "custom" with a subset of PERMISSIONS. Nothing here grants team, profile,
# bank, document or payout control, and finance is read-only.
PRESETS = {
    "store_manager": ("products.read", "products.write", "inventory.read", "inventory.write", "orders.read", "orders.fulfil",
                      "returns.read", "returns.act", "reports.read"),
    "product_manager": ("products.read", "products.write", "inventory.read"),
    "order_manager": ("orders.read", "orders.fulfil", "returns.read"),
    "inventory_staff": ("inventory.read", "inventory.write", "products.read"),
    "finance_viewer": ("finance.read", "reports.read"),
}
ROLES = tuple(PRESETS) + ("custom",)

# (method, path pattern, permission). "" = any active member. Checked in order; the first match decides.
RULES = [
    ("GET", r"^/api/vendor/me$", ""),
    ("GET", r"^/api/vendor/notifications$", ""),
    ("GET", r"^/api/vendor/products/[^/]+/stock-history$", "inventory.read"),
    ("POST", r"^/api/vendor/products/[^/]+/stock$", "inventory.write"),
    ("GET", r"^/api/vendor/products(/export\.csv|/import-template\.csv)?$", "products.read"),
    ("GET", r"^/api/vendor/catalogue/spec$", "products.read"),
    ("POST", r"^/api/vendor/products(/import)?$", "products.write"),
    ("PUT", r"^/api/vendor/products/[^/]+$", "products.write"),
    ("POST", r"^/api/vendor/products/[^/]+/(archive|listing)$", "products.write"),
    ("POST", r"^/api/vendor/uploads/sign$", "products.write"),
    ("GET", r"^/api/vendor/orders(/[^/]+)?$", "orders.read"),
    ("POST", r"^/api/vendor/orders/[^/]+/fulfilment$", "orders.fulfil"),
    ("POST", r"^/api/vendor/orders/[^/]+/return-inspection$", "returns.act"),
    ("GET", r"^/api/vendor/returns(/[^/]+)?$", "returns.read"),
    ("POST", r"^/api/vendor/returns/[^/]+/(action|inspection)$", "returns.act"),
    ("GET", r"^/api/vendor/dashboard$", "reports.read"),
    ("GET", r"^/api/vendor/reports/.+$", "reports.read"),
    ("GET", r"^/api/vendor/finance/.+$", "finance.read"),
]


def required_permission(method: str, path: str) -> Optional[str]:
    """The permission a staff member needs for this call, "" for any active member, or None when staff are refused."""
    for m, pattern, perm in RULES:
        if m == method and re.match(pattern, path):
            return perm
    return None


def permissions_for(role: str, custom: Optional[list] = None) -> list:
    """Server-side expansion of a role. Custom permissions must be a non-empty subset of PERMISSIONS."""
    if role == "custom":
        return sorted(set(custom or []))
    return sorted(PRESETS[role])


def validate_role(role: str, custom: Optional[list]) -> list:
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Choose a role from the list.")
    if role == "custom":
        chosen = list(custom or [])
        if not chosen or any(p not in PERMISSIONS for p in chosen):
            raise HTTPException(status_code=400, detail="Choose at least one permission from the list.")
    return permissions_for(role, custom)


def new_invite_token() -> tuple:
    """(token shown once to the owner, sha256 stored) and the expiry."""
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest(), datetime.now(timezone.utc) + timedelta(hours=INVITE_HOURS)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


async def authorize_staff(user: dict, method: str, path: str) -> dict:
    """Used for every staff request. Returns the user with the vendor and membership attached, or raises 403."""
    m = await db.vendor_members.find_one({"user_id": user["id"], "status": "active"}, {"_id": 0})
    if not m:
        raise HTTPException(status_code=403, detail="Your access to this vendor has been removed or suspended.")
    v = await db.vendors.find_one({"id": m["vendor_id"]}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=403, detail="Your access to this vendor has been removed or suspended.")
    perm = required_permission(method, path)
    if perm is None:
        raise HTTPException(status_code=403, detail="Staff accounts cannot use this area. Ask the vendor owner.")
    if perm and perm not in (m.get("permissions") or []):
        raise HTTPException(status_code=403, detail="Your role does not allow this action.")
    return {**user, "_vendor": v, "_member": m}
