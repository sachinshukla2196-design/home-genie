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

# Batch 12, Phase 5: fine-grained permissions. Each has a plain description and a risk level for the owner's role builder.
PERMISSION_INFO = {
    "products.read":    {"module": "Products", "label": "See products", "risk": "low", "description": "View the catalogue, drafts and review results."},
    "products.create":  {"module": "Products", "label": "Prepare new products", "risk": "low", "description": "Start and fill in new product drafts. Does not send them for review."},
    "products.edit":    {"module": "Products", "label": "Prepare product changes", "risk": "low", "description": "Change descriptions, images, details and variants in a draft. Does not send them for review."},
    "products.submit":  {"module": "Products", "label": "Send products for review", "risk": "medium", "description": "Submit new products and changes (including prices) to HOME GENIES for approval."},
    "products.archive": {"module": "Products", "label": "Pause, resume and archive", "risk": "medium", "description": "Take an approved product off sale or put it back on sale."},
    "inventory.read":   {"module": "Inventory", "label": "See stock", "risk": "low", "description": "View stock levels and the stock history."},
    "inventory.adjust": {"module": "Inventory", "label": "Adjust stock", "risk": "medium", "description": "Add or remove stock with a reason. Every change is recorded."},
    "orders.read":      {"module": "Orders", "label": "See orders", "risk": "medium", "description": "View your order lines with the delivery name and address needed to ship them."},
    "orders.accept":    {"module": "Orders", "label": "Accept or decline orders", "risk": "high", "description": "Accept new orders or decline them (a declined paid order is refunded to the customer)."},
    "orders.pack":      {"module": "Orders", "label": "Mark orders packed", "risk": "low", "description": "Record that an accepted order is packed."},
    "orders.dispatch":  {"module": "Orders", "label": "Dispatch and delivery updates", "risk": "medium", "description": "Hand orders to the courier with tracking, and record delivery or a failed delivery."},
    "returns.read":     {"module": "Returns", "label": "See returns", "risk": "low", "description": "View return requests for your products."},
    "returns.respond":  {"module": "Returns", "label": "Respond to returns", "risk": "high", "description": "Approve, contest or mark returns received."},
    "returns.inspect":  {"module": "Returns", "label": "Inspect returned goods", "risk": "medium", "description": "Record the condition of returned goods (decides what goes back into stock)."},
    "reports.read":     {"module": "Reports", "label": "See dashboard and reports", "risk": "medium", "description": "View sales figures and performance reports."},
    "reports.export":   {"module": "Reports", "label": "Download reports", "risk": "medium", "description": "Download report files (CSV)."},
    "finance.read":     {"module": "Money", "label": "See earnings and settlements", "risk": "high", "description": "View the earnings ledger, settlements, COD and commercial terms. Read only."},
    "finance.export":   {"module": "Money", "label": "Download statements", "risk": "high", "description": "Download the earnings statement (CSV)."},
}
PERMISSIONS = tuple(PERMISSION_INFO)
# The original (pre-Batch 12) coarse permissions stay valid in stored memberships and imply the finer ones, so every existing
# member keeps exactly the access it had (no migration, nobody locked out).
LEGACY_IMPLIES = {
    "products.write": ("products.create", "products.edit", "products.submit", "products.archive"),
    "inventory.write": ("inventory.adjust",),
    "orders.fulfil": ("orders.accept", "orders.pack", "orders.dispatch"),
    "returns.act": ("returns.respond", "returns.inspect"),
}


def effective_permissions(perms) -> set:
    out = set(perms or [])
    for p in list(out):
        out.update(LEGACY_IMPLIES.get(p, ()))
    return out


# Presets: least privilege. Nothing here grants team, profile, bank, document or payout control, and money is read-only.
PRESETS = {
    "store_manager": ("products.read", "products.write", "inventory.read", "inventory.write", "orders.read", "orders.fulfil",
                      "returns.read", "returns.act", "reports.read"),
    "catalogue_manager": ("products.read", "products.create", "products.edit", "products.submit", "products.archive", "inventory.read"),
    "product_editor": ("products.read", "products.create", "products.edit"),
    "inventory_manager": ("inventory.read", "inventory.adjust", "products.read"),
    "warehouse_staff": ("orders.read", "orders.pack", "inventory.read"),
    "order_manager": ("orders.read", "orders.fulfil", "returns.read"),
    "packing_staff": ("orders.read", "orders.pack"),
    "dispatch_staff": ("orders.read", "orders.dispatch"),
    "returns_manager": ("returns.read", "returns.respond", "returns.inspect", "orders.read"),
    "support_staff": ("orders.read", "returns.read"),
    "finance_viewer": ("finance.read", "reports.read"),
    "reports_viewer": ("reports.read",),
    # kept for members created before Batch 12 (not offered for new invitations)
    "product_manager": ("products.read", "products.write", "inventory.read"),
    "inventory_staff": ("inventory.read", "inventory.write", "products.read"),
}
PRESET_INFO = {
    "store_manager": {"label": "Store manager", "description": "Runs products, stock, orders and returns day to day. No money or team access."},
    "catalogue_manager": {"label": "Catalogue manager", "description": "Prepares products and changes and sends them for HOME GENIES review; can pause products."},
    "product_editor": {"label": "Product editor", "description": "Prepares product drafts and changes; someone else sends them for review."},
    "inventory_manager": {"label": "Inventory manager", "description": "Keeps stock accurate with recorded adjustments."},
    "warehouse_staff": {"label": "Warehouse staff", "description": "Sees what to pick and marks orders packed. No prices or money."},
    "order_manager": {"label": "Order manager", "description": "Accepts, packs and ships orders and sees returns."},
    "packing_staff": {"label": "Packing staff", "description": "Marks accepted orders packed."},
    "dispatch_staff": {"label": "Dispatch staff", "description": "Hands orders to the courier and records delivery."},
    "returns_manager": {"label": "Returns manager", "description": "Handles return requests and inspects returned goods."},
    "support_staff": {"label": "Customer support", "description": "Looks up orders and returns to answer customers. Cannot change them."},
    "finance_viewer": {"label": "Finance viewer", "description": "Sees earnings, settlements and reports. Cannot change anything."},
    "reports_viewer": {"label": "Reports viewer", "description": "Sees the dashboard and reports only."},
    "product_manager": {"label": "Product manager (older role)", "description": "Earlier role: products and stock viewing.", "legacy": True},
    "inventory_staff": {"label": "Inventory staff (older role)", "description": "Earlier role: stock adjustments.", "legacy": True},
}
ROLES = tuple(PRESETS) + ("custom",)

# (method, path pattern, permission). "" = any active member. Checked in order; the first match decides.
RULES = [
    ("GET", r"^/api/vendor/me$", ""),
    ("GET", r"^/api/vendor/notifications$", ""),
    ("GET", r"^/api/vendor/products/[^/]+/stock-history$", "inventory.read"),
    ("POST", r"^/api/vendor/products/[^/]+/stock$", "inventory.adjust"),
    ("GET", r"^/api/vendor/products(/export\.csv|/import-template\.csv)?$", "products.read"),
    ("GET", r"^/api/vendor/catalogue/spec$", "products.read"),
    ("POST", r"^/api/vendor/products(/import)?$", "products.submit"),          # these create products awaiting review
    ("PUT", r"^/api/vendor/products/[^/]+$", "products.submit"),               # a direct change goes straight to review
    ("POST", r"^/api/vendor/products/[^/]+/(archive|listing)$", "products.archive"),
    ("POST", r"^/api/vendor/uploads/sign$", ("products.create", "products.edit")),
    # Batch 12 (Phase 4): the product studio. Which of create / edit a draft needs is checked in the handler.
    ("GET", r"^/api/vendor/pim/drafts(/[^/]+)?$", "products.read"),
    ("GET", r"^/api/vendor/pim/products/[^/]+/revision$", "products.read"),
    ("POST", r"^/api/vendor/pim/drafts/[^/]+/submit$", "products.submit"),
    ("POST", r"^/api/vendor/pim/drafts$", ("products.create", "products.edit")),
    ("PUT", r"^/api/vendor/pim/drafts/[^/]+$", ("products.create", "products.edit")),
    ("DELETE", r"^/api/vendor/pim/drafts/[^/]+$", ("products.create", "products.edit")),
    ("GET", r"^/api/vendor/orders(/[^/]+)?$", "orders.read"),
    # which fulfilment step needs which permission is checked in the handler (`fulfilment_permission`)
    ("POST", r"^/api/vendor/orders/[^/]+/fulfilment$", ("orders.accept", "orders.pack", "orders.dispatch")),
    ("POST", r"^/api/vendor/orders/[^/]+/return-inspection$", "returns.inspect"),
    ("GET", r"^/api/vendor/returns(/[^/]+)?$", "returns.read"),
    ("POST", r"^/api/vendor/returns/[^/]+/action$", "returns.respond"),
    ("POST", r"^/api/vendor/returns/[^/]+/inspection$", "returns.inspect"),
    ("GET", r"^/api/vendor/dashboard$", "reports.read"),
    ("GET", r"^/api/vendor/reports/.+\.csv$", "reports.export"),
    ("GET", r"^/api/vendor/reports/.+$", "reports.read"),
    ("GET", r"^/api/vendor/finance/.+\.csv$", "finance.export"),
    ("GET", r"^/api/vendor/finance/.+$", "finance.read"),
]

FULFILMENT_PERMISSION = {"accepted": "orders.accept", "rejected": "orders.accept", "cancelled": "orders.accept", "packed": "orders.pack",
                         "dispatched": "orders.dispatch", "delivered": "orders.dispatch", "delivery_failed": "orders.dispatch",
                         "returned_to_origin": "orders.dispatch"}


def member_can(user: dict, perm: str) -> bool:
    """Owner: always. Staff: when the membership's effective permissions include `perm`."""
    m = user.get("_member")
    return m is None or perm in effective_permissions(m.get("permissions"))


def require_member_permission(user: dict, perm: str) -> None:
    if not member_can(user, perm):
        raise HTTPException(status_code=403, detail="Your role does not allow this action.")


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
        if not chosen or any(p not in PERMISSIONS and p not in LEGACY_IMPLIES for p in chosen):
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
    # Batch 12 (audit C-17): staff act on the owner's behalf, so they stop when the owner account is blocked or deactivated.
    owner = await db.users.find_one({"id": v.get("user_id")}, {"_id": 0, "blocked": 1, "account_status": 1, "deleted_at": 1})
    if not owner or owner.get("blocked") or owner.get("deleted_at") or owner.get("account_status") in ("blocked", "deleted", "suspended"):
        raise HTTPException(status_code=403, detail="This vendor's account is not active. Ask the vendor owner to contact HOME GENIES.")
    perm = required_permission(method, path)
    if perm is None:
        raise HTTPException(status_code=403, detail="Staff accounts cannot use this area. Ask the vendor owner.")
    have = effective_permissions(m.get("permissions"))
    if perm and not (any(p in have for p in perm) if isinstance(perm, tuple) else perm in have):
        raise HTTPException(status_code=403, detail="Your role does not allow this action.")
    return {**user, "_vendor": v, "_member": m}
