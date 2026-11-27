"""Admin panel routes: dashboard, users, products, orders, KYC, withdrawals,
commissions, settings, audit logs, reports (with CSV export)."""
import math
import re
import secrets
from core import hash_password, next_distributor_id, get_or_create_wallet, next_sequence
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator
from decimal import Decimal
from pymongo.errors import DuplicateKeyError
from typing import Optional, List
from datetime import datetime, timezone
from pagination import clamp_page, page_meta
from money import to_paise, paise_to_float, paise_of
from stock import run_intents, intent

from core import (db, now_iso, new_id, require_admin, get_settings, P_PUBLIC, VENDOR_ADMIN_ROLES,
                  add_wallet_transaction, wallet_apply, create_notification, log_audit,
                  clean_user, mask_aadhaar, password_update)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _mask_pan(p: str) -> str:
    p = str(p or "").strip().upper()
    if len(p) < 6:
        return "*" * len(p)
    return "XXXXX" + p[5:9] + "X"  # ABCDE1234F -> XXXXX1234X


def _mask_acct(a: str) -> str:
    a = str(a or "").strip()
    if len(a) <= 4:
        return "*" * len(a)
    return "XXXX" + a[-4:]  # only last 4 visible


def _mask_ifsc(i: str) -> str:
    i = str(i or "").strip().upper()
    if len(i) <= 4:
        return "*" * len(i)
    return i[:4] + "*" * (len(i) - 4)  # keep bank code, hide branch


# ---------------- Protected accounts (SEC-01 / SEC-03) ----------------
# Who may act on whom through the user-management endpoints (reset password, edit profile/contact, block/unblock):
#   * a super_admin account:            nobody here. Its credential is managed through the environment (deploy/ENVIRONMENT.md).
#   * admin / accounts_admin / support_admin accounts: only a super_admin.
#   * every other account (members, vendors, vendor staff): any admin role, as before.
#   * an admin never acts on their own account here; they use "change password" instead.
ADMIN_TARGET_ROLES = ("super_admin", "admin", "accounts_admin", "support_admin")


def _guard_target(actor: dict, target: dict, what: str) -> None:
    if target.get("id") == actor.get("id"):
        raise HTTPException(status_code=403, detail=f"You cannot {what} your own account here.")
    role = target.get("role")
    if role == "super_admin":
        raise HTTPException(status_code=403, detail=f"The super admin account is protected; you cannot {what} it here.")
    if role in ADMIN_TARGET_ROLES and actor.get("role") != "super_admin":
        raise HTTPException(status_code=403, detail=f"Only the super admin can {what} an admin account.")


VENDOR_ACCOUNT_ROLES = ("vendor", "vendor_staff")


def _guard_vendor_account(actor: dict, target: dict, what: str) -> None:
    """Batch 12 (audit C-17): vendor owner and staff accounts follow the vendor lifecycle, which only super_admin and admin may
    change (VENDOR_ADMIN_ROLES - the same roles as vendor suspension). Blocking or deactivating them through the general user
    tools would otherwise let support / accounts admins suspend a vendor's business."""
    if target.get("role") in VENDOR_ACCOUNT_ROLES and actor.get("role") not in VENDOR_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail=f"Only an admin can {what} a vendor account. Use the vendor's lifecycle actions.")


# ---------------- Dashboard ----------------
@router.get("/dashboard")
async def admin_dashboard(admin: dict = Depends(require_admin)):
    settings = await get_settings()
    today = datetime.now(timezone.utc).date().isoformat()

    total_users = await db.users.count_documents({"role": {"$in": ["distributor", "customer", "vendor"]}})
    red_users = await db.users.count_documents({"status": "red", "role": {"$in": ["distributor", "customer", "vendor"]}})
    green_users = await db.users.count_documents({"status": "green", "role": {"$in": ["distributor", "customer", "vendor"]}})
    pending_kyc = await db.kyc_records.count_documents({"status": "pending"})
    pending_wd = await db.withdrawal_requests.count_documents({"status": {"$in": list(REQUESTED_STATES)}})   # requested, awaiting approval

    def today_q(field="created_at"):
        return {field: {"$regex": f"^{today}"}}

    today_regs = await db.users.count_documents({"created_at": {"$regex": f"^{today}"}})
    today_acts = await db.users.count_documents({"status": "green", "approved_at": {"$regex": f"^{today}"}})
    today_orders = await db.orders.count_documents({"created_at": {"$regex": f"^{today}"}, "payment_status": "paid"})

    revenue_docs = await db.orders.find({"payment_status": "paid", "created_at": {"$regex": f"^{today}"}},
                                        {"_id": 0, "total": 1}).to_list(1000)
    today_revenue = sum(o.get("total", 0) for o in revenue_docs)

    all_paid = await db.orders.find({"payment_status": "paid"}, {"_id": 0, "total": 1}).to_list(5000)
    total_revenue = sum(o.get("total", 0) for o in all_paid)

    return {
        "settings": {"currency_symbol": settings.get("currency_symbol", "₹")},
        "stats": {
            "total_users": total_users, "red_users": red_users, "green_users": green_users,
            "today_registrations": today_regs, "today_activations": today_acts,
            "today_orders": today_orders, "today_revenue": today_revenue,
            "total_revenue": total_revenue,
            "pending_kyc": pending_kyc, "pending_withdrawals": pending_wd,
        },
    }


# ---------------- Users ----------------
@router.get("/users")
async def admin_users(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {"role": {"$in": ["distributor", "customer", "vendor"]}}
    if status:
        q["status"] = status
    users = await db.users.find(q, {"_id": 0, "password_hash": 0, "env_credential_marker": 0}).sort("created_at", -1).to_list(1000)
    for u in users:
        if u.get("aadhaar_number"):
            u["aadhaar_masked"] = mask_aadhaar(u["aadhaar_number"])
            u.pop("aadhaar_number", None)
    return users


@router.get("/users/{user_id}")
async def admin_user_detail(user_id: str, admin: dict = Depends(require_admin)):
    u = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "env_credential_marker": 0})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.get("aadhaar_number"):
        u["aadhaar_masked"] = mask_aadhaar(u["aadhaar_number"])
        u.pop("aadhaar_number", None)
    from core import get_or_create_wallet
    wallet = await get_or_create_wallet(user_id)    # exact (paise-derived) balances
    orders = await db.orders.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).to_list(50)
    return {"user": u, "wallet": wallet, "orders": orders}


# ---------------- Products ----------------
VENDOR_PRODUCT_MSG = "This is a vendor's product. The vendor edits it and HOME GENIES approves it under Vendors; it can only be taken down here."


class ProductBody(BaseModel):
    """HOME GENIES-owned products (CAT-06). Vendor products never go through this model."""
    sku: str
    name: str = Field(min_length=2, max_length=160)
    name_hi: str = Field(default="", max_length=160)
    description: str = Field(default="", max_length=4000)
    description_hi: str = Field(default="", max_length=4000)
    images: List[str] = []
    mrp: float = Field(gt=0, le=10_000_000)
    selling_price: float = Field(gt=0, le=10_000_000)
    gst_percent: float = Field(default=5.0, ge=0, le=28)
    hsn_code: str = Field(default="", max_length=8)
    stock: int = Field(default=0, ge=0, le=1_000_000)   # opening stock on CREATE only; later changes go through /stock
    category: str = "Household Essentials"
    is_active: bool = True
    # Optional purchase options, e.g. [{"name": "Size", "values": ["Free Size"]},
    #                                  {"name": "Shade", "values": ["Maroon", "Gold"]}]
    options: List[dict] = []

    @field_validator("sku")
    @classmethod
    def _sku(cls, v):
        v = (v or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._-]{1,39}", v):
            raise ValueError("SKU: 2 to 40 letters, digits, dot, dash or underscore.")
        return v

    @field_validator("category")
    @classmethod
    def _category(cls, v):
        from catalogue import PILLARS
        if v not in PILLARS:
            raise ValueError("Category must be one of: " + ", ".join(PILLARS) + ".")
        return v

    @field_validator("hsn_code")
    @classmethod
    def _hsn(cls, v):
        v = (v or "").strip()
        if v and not re.fullmatch(r"\d{4}|\d{6}|\d{8}", v):
            raise ValueError("HSN code must be 4, 6 or 8 digits.")
        return v

    @field_validator("images")
    @classmethod
    def _images(cls, v):
        from validators import safe_image_refs
        return safe_image_refs(v)

    @field_validator("options")
    @classmethod
    def _options(cls, v):
        if len(v) > 5:
            raise ValueError("At most 5 options.")
        for o in v:
            if not isinstance(o, dict) or not str(o.get("name", "")).strip() or not isinstance(o.get("values", []), list) \
                    or len(o.get("values", [])) > 30 or any(len(str(x)) > 60 for x in o.get("values", [])):
                raise ValueError("Each option needs a name and up to 30 short values.")
        return v

    def check_prices(self):
        if self.selling_price > self.mrp:
            raise HTTPException(status_code=400, detail="Selling price cannot be higher than the MRP.")


async def _sku_taken(sku: str, exclude_id: str = "") -> bool:
    """Case-insensitive, across product SKUs AND variant SKUs (CAT-07)."""
    rx = {"$regex": f"^{re.escape(sku)}$", "$options": "i"}
    return bool(await db.products.find_one({"id": {"$ne": exclude_id}, "$or": [{"sku": rx}, {"variants.sku": rx}]}, {"_id": 1}))


@router.get("/products")
async def admin_list_products(q: str = "", category: str = "", status: str = "", owner: str = "", page: int = 1, page_size: int = 50,
                              admin: dict = Depends(require_admin)):
    """The admin catalogue list (replaces the public /products?active=false the screen used before). Paginated."""
    page, page_size = clamp_page(page, page_size)
    flt = {}
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        flt["$or"] = [{"name": rx}, {"sku": rx}]
    if category:
        flt["category"] = category
    if status == "active":
        flt["is_active"] = True
    elif status == "inactive":
        flt["is_active"] = {"$ne": True}
    if owner == "platform":
        flt["vendor_id"] = None
    elif owner == "vendor":
        flt["vendor_id"] = {"$ne": None}
    total = await db.products.count_documents(flt)
    rows = await db.products.find(flt, P_PUBLIC).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    return {"items": rows, **page_meta(total, page, page_size)}


@router.post("/products")
async def create_product(body: ProductBody, request: Request, admin: dict = Depends(require_admin)):
    body.check_prices()
    if await _sku_taken(body.sku):
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    p = body.model_dump()
    p.update({"id": new_id(), "created_at": now_iso(), "updated_at": now_iso()})
    try:
        await db.products.insert_one(dict(p))
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    if p["stock"]:
        await db.stock_movements.insert_one({"id": new_id(), "product_id": p["id"], "delta": p["stock"], "reason": "initial_stock",
                                             "actor_id": admin["id"], "created_at": now_iso()})
    await log_audit(admin, "product_created", "product", p["id"], new_value={"sku": p["sku"]}, request=request)
    p.pop("_id", None)
    return p


@router.put("/products/{product_id}")
async def update_product(product_id: str, body: ProductBody, request: Request, admin: dict = Depends(require_admin)):
    """Edits everything EXCEPT stock (CAT-03): the form sends the number it loaded, and writing it back would undo orders
    placed since. Stock changes go through POST /admin/products/{id}/stock (atomic, journaled)."""
    existing = await db.products.find_one({"id": product_id}, P_PUBLIC)
    if not existing:
        raise HTTPException(status_code=404, detail="Product not found.")
    if existing.get("vendor_id"):
        # Vendor V1.1: a vendor's product changes only through the vendor's own edit and the admin approval decision, so the
        # review trail and suspension rules cannot be bypassed from the general catalogue screen.
        raise HTTPException(status_code=409, detail=VENDOR_PRODUCT_MSG)
    body.check_prices()
    if body.sku != (existing.get("sku") or "").upper() and await _sku_taken(body.sku, exclude_id=product_id):
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    upd = body.model_dump()
    upd.pop("stock", None)
    if (existing.get("sku") or "").upper() == body.sku:
        upd["sku"] = existing.get("sku")          # a legacy lower-case SKU is not rewritten by an unrelated edit
    upd["updated_at"] = now_iso()
    try:
        await db.products.update_one({"id": product_id}, {"$set": upd})
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    await log_audit(admin, "product_updated", "product", product_id, old_value=existing, new_value=upd, request=request)
    return {**existing, **upd}


class AdminStockIn(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(min_length=3, max_length=120)


@router.post("/products/{product_id}/stock")
async def adjust_platform_stock(product_id: str, body: AdminStockIn, request: Request, admin: dict = Depends(require_admin)):
    """CAT-03: atomic, journaled stock adjustment for HOME GENIES products. Never lets stock go below zero."""
    if body.delta == 0:
        raise HTTPException(status_code=400, detail="Enter a non-zero change.")
    p = await db.products.find_one({"id": product_id}, {"_id": 0, "id": 1, "vendor_id": 1})
    if p is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    if p.get("vendor_id"):
        raise HTTPException(status_code=409, detail="Vendor stock is managed by the vendor in their inventory screen.")
    flt = {"id": product_id} if body.delta > 0 else {"id": product_id, "stock": {"$gte": -body.delta}}
    r = await db.products.find_one_and_update(flt, {"$inc": {"stock": body.delta}, "$set": {"updated_at": now_iso()}},
                                              projection={"_id": 0, "stock": 1}, return_document=True)
    if not r:
        raise HTTPException(status_code=409, detail="Not enough stock to remove that many units.")
    await db.stock_movements.insert_one({"id": new_id(), "product_id": product_id, "delta": body.delta, "reason": body.reason.strip(),
                                         "actor_id": admin["id"], "created_at": now_iso()})
    await log_audit(admin, "product_stock_adjusted", "product", product_id, new_value={"delta": body.delta, "stock": r["stock"],
                                                                                       "reason": body.reason.strip()}, request=request)
    return {"ok": True, "stock": r["stock"]}


@router.delete("/products/{product_id}")
async def deactivate_product(product_id: str, request: Request, reason: str = "", admin: dict = Depends(require_admin)):
    """Take a product off sale. For a VENDOR product this is an admin takedown that the vendor cannot undo by re-listing
    (CAT-05); only a super admin or admin can lift it (POST /admin/products/{id}/takedown/lift)."""
    p = await db.products.find_one({"id": product_id}, {"_id": 0, "id": 1, "vendor_id": 1})
    if p is None:
        raise HTTPException(status_code=404, detail="Product not found.")
    if p.get("vendor_id") and admin.get("role") not in VENDOR_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only a super admin or admin can take down a vendor's product.")
    sets = {"is_active": False, "updated_at": now_iso()}
    if p.get("vendor_id"):
        sets["admin_takedown"] = {"by": admin["id"], "at": now_iso(), "reason": (reason or "").strip()[:300]}
    await db.products.update_one({"id": product_id}, {"$set": sets})
    await log_audit(admin, "product_deactivated", "product", product_id, new_value={"takedown": bool(p.get("vendor_id")),
                                                                                    "reason": (reason or "").strip()[:300]}, request=request)
    return {"ok": True}


@router.post("/products/{product_id}/takedown/lift")
async def lift_takedown(product_id: str, request: Request, admin: dict = Depends(require_admin)):
    if admin.get("role") not in VENDOR_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only a super admin or admin can lift a takedown.")
    r = await db.products.update_one({"id": product_id, "admin_takedown": {"$exists": True}},
                                     {"$unset": {"admin_takedown": ""}, "$set": {"updated_at": now_iso()}})
    if not r.modified_count:
        raise HTTPException(status_code=404, detail="This product has no admin takedown.")
    await log_audit(admin, "product_takedown_lifted", "product", product_id, request=request)
    return {"ok": True, "note": "The vendor can list the product again (it stays unlisted until they do)."}


@router.delete("/products/{product_id}/permanent")
async def delete_product_permanent(product_id: str, request: Request, admin: dict = Depends(require_admin)):
    p = await db.products.find_one({"id": product_id}, P_PUBLIC)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    if p.get("vendor_id"):
        raise HTTPException(status_code=409, detail=VENDOR_PRODUCT_MSG)
    await db.products.delete_one({"id": product_id})
    await log_audit(admin, "product_deleted", "product", product_id,
                    old_value={"sku": p.get("sku"), "name": p.get("name")}, request=request)
    return {"ok": True}


# ---------------- Orders ----------------
@router.get("/orders")
async def admin_orders(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    orders = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    uids = list({o.get("user_id") for o in orders if o.get("user_id")})
    users = await db.users.find({"id": {"$in": uids}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(2000)
    names = {u["id"]: u.get("full_name") for u in users}
    for o in orders:
        o["user_name"] = names.get(o.get("user_id"), "")
    return orders


class OrderStatusBody(BaseModel):
    status: str
    reason: str = Field(default="", max_length=300)     # Batch 13: why the admin changed it (recorded in the audit)


MONEY_ADMIN_ROLES = ("super_admin", "accounts_admin")      # roles that may move money by hand (same set as the finance controls)


def require_money_admin(admin: dict = Depends(require_admin)) -> dict:
    if admin.get("role") not in MONEY_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only a finance administrator can do this.")
    return admin


@router.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, body: OrderStatusBody, request: Request, admin: dict = Depends(require_admin)):
    allowed = ["pending", "payment_pending", "paid", "processing", "packed", "shipped", "delivered", "cancelled", "refunded"]
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status.")
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if body.status == "refunded" and o.get("payment_status") in ("paid", "partially_refunded"):
        raise HTTPException(status_code=400, detail="Use the Refund action (with amount & payment reference) to refund a paid order.")
    if o.get("needs_refund") and o.get("payment_status") in ("paid", "partially_refunded") and body.status != "cancelled":
        raise HTTPException(status_code=400, detail="This order was paid after it expired and cannot be fulfilled. "
                                                    "Refund it from the Needs refund queue.")
    current = o.get("status")
    if body.status != current:
        if body.status in ("pending", "payment_pending", "paid"):
            raise HTTPException(status_code=400, detail="Payment states are set by the payment flow, not by a status change.")
        if current in ("cancelled", "refunded"):
            # its stock has been returned (and its money may have been): re-opening it here would sell stock it no longer holds
            raise HTTPException(status_code=409, detail=f"A {current} order cannot be re-opened. Place a new order instead.")
        unpaid_online = o.get("payment_method") != "cod" and o.get("payment_status") not in ("paid", "partially_refunded")
        if unpaid_online and body.status in ("processing", "packed", "shipped", "delivered"):
            raise HTTPException(status_code=409, detail="This order is not paid yet, so it cannot move into fulfilment.")
    upd = {"$set": {"status": body.status, "updated_at": now_iso()}}
    if body.status == "delivered" and current != "delivered" and not o.get("fulfilments"):
        # goods sold by the platform itself (no vendor fulfilment): this record is the delivery (decisions 2/3 clocks).
        upd["$set"]["delivered_at"] = now_iso()
    if body.status == "delivered" and o.get("fulfilments"):
        # Batch 12 (audit C-5a): for vendor goods the delivery evidence is the vendor fulfilment; an admin status change is
        # recorded but starts no payout clock (eligibility reads the fulfilments). Who may confirm a delivery on a vendor's
        # behalf is an open owner decision (OWNER_DECISION_REGISTER D-04).
        upd["$set"]["status_set_by_admin"] = {"status": "delivered", "by": admin["id"], "at": now_iso()}
    if current == "delivered" and body.status != "delivered":
        upd["$unset"] = {"delivered_at": ""}           # audit C-5b: moving back from delivered withdraws the delivery record
    cancelling = body.status == "cancelled" and o.get("status") != "cancelled"
    # FIN-15: cancelling an order whose money is in (or cash is due) reverses vendor sales and opens a refund case. That is
    # an operations decision for super_admin / admin, not for support or finance-only roles.
    if cancelling and o.get("payment_status") in MONEY_IN_PAYMENT and admin.get("role") not in CANCEL_PAID_ROLES:
        raise HTTPException(status_code=403, detail="Only the super admin or an admin can cancel an order that has been paid or is awaiting cash collection.")
    if cancelling:   # the restock decision is stored atomically with the status change; recovery replays it if interrupted
        upd["$push"] = {"restock_intents": intent("admin_cancel", admin["id"], prev_status=o.get("status", ""))}
        if o.get("payment_status") in ("paid", "partially_refunded") and not o.get("needs_refund"):
            upd["$set"]["refund_due_cancel"] = True      # G1: the refund obligation is recorded with the cancellation itself
    # Programme 03-B: also conditional on the payment state read above - the refund marker is decided from it, so a payment that
    # lands between the read and this claim makes the claim miss (409) instead of cancelling a paid order with no obligation.
    changed = await db.orders.update_one({"id": order_id, "status": current, "payment_status": o.get("payment_status")}, upd)
    if changed.matched_count != 1:
        raise HTTPException(status_code=409, detail="This order was just updated. Refresh and try again.")
    restock = None
    refund_case = None
    if cancelling:
        # Confirmed cancellation: return stock for goods that have not left, stop pre-dispatch fulfilment.
        restock = {"restocked_lines": await run_intents(order_id)}
        from returns_routes import settle_paid_cancellation
        case = await settle_paid_cancellation(order_id)          # paid order: one refund case, cancelled vendors' sales reversed
        refund_case = (case or {}).get("number")
    # NOTE: 'cancelled' on a PAID order does NOT reverse commissions by itself — only a confirmed
    # payment return (Refund action) does. Unpaid cancelled orders never generated commissions.
    await create_notification(o["user_id"], "order", "Order update",
                              f"Your order {o['order_number']} is now {body.status}.",
                              "ऑर्डर अपडेट", f"आपका ऑर्डर {o['order_number']} अब {body.status} है।")
    await log_audit(admin, "order_status_changed", "order", order_id,
                    old_value={"status": o["status"]}, new_value={"status": body.status, "restock": restock, "reason": body.reason.strip()}, request=request)
    return {"ok": True, "restock": restock, "refund_case": refund_case}


class RefundBody(BaseModel):
    amount: Optional[float] = None  # None/omitted = full remaining refund
    reference: str
    reason: str = ""
    cancel_order: bool = False


@router.post("/orders/{order_id}/refund")
async def refund_order(order_id: str, body: RefundBody, request: Request, admin: dict = Depends(require_money_admin)):
    """Record a refund (full or partial) for CONFIRMATION BY A DIFFERENT FINANCE ADMIN.

    Batch 12 (audit C-4): this used to move the money in one step, which let a single person both make and approve a refund
    and bypass the refund-case rule (owner decision 4: the person who initiates cannot confirm). It now opens the order's
    refund case (or the cancellation case when `cancel_order` is set) already INITIATED by this admin, with the reference
    proposed; no money moves and no commission is clawed back until another finance admin confirms the case
    (POST /api/admin/refund-cases/{id}/action, action "confirm")."""
    from returns_routes import open_refund_case, initiate_case_as, settle_paid_cancellation, refundable_paise, _open_case_total
    ref = (body.reference or "").strip()
    if len(ref) < 3:      # the same rule the confirming admin must meet
        raise HTTPException(status_code=400, detail="Refund payment reference (UTR / Razorpay refund id) is required.")
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.get("payment_status") not in ("paid", "partially_refunded"):
        raise HTTPException(status_code=400, detail="Only paid orders can be refunded.")
    if await db.order_refunds.find_one({"id": f"{order_id}:refund:{ref}"}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="A refund with this reference was already recorded for this order.")
    remaining_p = await refundable_paise(o)
    if body.amount is not None and (to_paise(body.amount) <= 0 or to_paise(body.amount) > remaining_p):
        raise HTTPException(status_code=400, detail=f"Refund amount must be between 0 and ₹{paise_to_float(remaining_p)}.")
    case = None
    if body.cancel_order and o.get("status") != "cancelled":
        await db.orders.update_one({"id": order_id, "status": {"$ne": "cancelled"}}, {
            "$set": {"status": "cancelled", "cancel_reason": "admin_refund", "cancelled_at": now_iso(), "updated_at": now_iso(),
                     "refund_due_cancel": True},
            "$push": {"restock_intents": intent("admin_cancel", admin["id"], prev_status=o.get("status", ""))}})
        await run_intents(order_id)
        case = await settle_paid_cancellation(order_id)
    if case is None:
        # an order that already has an open refund case awaiting review (late payment, cancellation, vendor rejection, return):
        # this action initiates THAT case instead of creating a second one for the same money
        want = to_paise(body.amount) if body.amount is not None else None
        async for open_case in db.refund_cases.find({"order_id": order_id, "status": "awaiting_review"}, {"_id": 0}).sort("created_at", 1):
            if want is None or want <= open_case["amount_paise"]:
                case = open_case
                break
    if case is None:
        room = remaining_p - await _open_case_total(order_id)
        amount_p = to_paise(body.amount) if body.amount is not None else room
        if amount_p <= 0 or amount_p > room:
            raise HTTPException(status_code=409, detail="This amount is already covered by an open refund case. Open it from Operations, Refunds.")
        case, _ = await open_refund_case(o, "admin_refund", amount_p, body.reason or "Refund recorded by an admin", f"adminrefund:{order_id}:{ref}")
    elif body.amount is not None and to_paise(body.amount) < case["amount_paise"]:
        case["amount_paise"] = to_paise(body.amount)
    if case["status"] == "awaiting_review":
        case = await initiate_case_as(case, admin, case["amount_paise"], body.reason, proposed_reference=ref)
    elif admin["id"] not in ({case.get("initiated_by")} | set(case.get("initiators") or [])):
        raise HTTPException(status_code=409, detail="This refund is already being handled. Open it from Operations, Refunds.")
    await log_audit(admin, "refund_recorded_for_confirmation", "order", order_id,
                    new_value={"case_id": case["id"], "amount_paise": case["amount_paise"], "reference": ref, "cancel_order": body.cancel_order},
                    request=request)
    return {"ok": True, "status": "pending_confirmation", "case": {k: v for k, v in case.items() if k != "_id"},
            "message": "Refund recorded. A different finance admin must confirm it in Operations, Refunds before it is final."}


@router.get("/refund-queue")
async def refund_queue(state: str = "open", page: int = 1, page_size: int = 25, admin: dict = Depends(require_admin)):
    """Orders paid after they had expired (15-minute rule, stock gone) or been cancelled; they cannot be fulfilled.
    'open' = still awaiting a refund (oldest first); 'resolved' = fully refunded."""
    if state not in ("open", "resolved"):
        raise HTTPException(status_code=400, detail="state must be 'open' or 'resolved'.")
    page, page_size = clamp_page(page, page_size)
    open_q = {"needs_refund": True, "payment_status": {"$in": ["paid", "partially_refunded"]}}
    q = open_q if state == "open" else {"needs_refund": True, "payment_status": "refunded"}
    total = await db.orders.count_documents(q)
    rows = await db.orders.find(q, {"_id": 0}).sort("needs_refund_at", 1 if state == "open" else -1) \
        .skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": [r["user_id"] for r in rows]}},
                                                     {"_id": 0, "id": 1, "full_name": 1, "mobile": 1}).to_list(page_size)}
    now = datetime.now(timezone.utc)
    for r in rows:
        u = users.get(r["user_id"], {})
        r["user_name"], r["user_mobile"] = u.get("full_name", ""), u.get("mobile", "")
        try:
            r["waiting_hours"] = round((now - datetime.fromisoformat(r.get("needs_refund_at") or r["paid_at"])).total_seconds() / 3600, 1)
        except Exception:
            r["waiting_hours"] = None
    return {"items": rows, **page_meta(total, page, page_size), "open_count": await db.orders.count_documents(open_q)}


MONEY_IN_PAYMENT = ("paid", "partially_refunded", "cod_pending", "cod_discrepancy", "claimed")
CANCEL_PAID_ROLES = ("super_admin", "admin")
REMOVABLE_PAYMENT = ("pending", "failed")


@router.delete("/orders/{order_id}")
async def delete_order(order_id: str, request: Request, admin: dict = Depends(require_admin)):
    """FIN-07: "Remove" an abandoned order. NOTHING is erased any more: the order is cancelled through the normal stock path
    (its reserved stock comes back) and archived, and its payment records stay. Only an online order that was never paid,
    never claimed, has no payment attempt and has not entered fulfilment can be removed; everything else is cancelled or
    refunded through its own workflow. super_admin / admin only."""
    if admin.get("role") not in CANCEL_PAID_ROLES:
        raise HTTPException(status_code=403, detail="Only the super admin or an admin can remove an order.")
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    if o.get("archived"):
        return {"ok": True, "already_removed": True}
    blocked = (o.get("payment_method") == "cod" or o.get("payment_status") not in REMOVABLE_PAYMENT
               or any(f.get("status") != "new" for f in o.get("fulfilments") or [])
               or await db.payment_transactions.count_documents({"order_id": order_id, "payment_status": "paid"})
               or await db.commissions.count_documents({"reference_order_id": order_id}))
    if blocked:
        raise HTTPException(status_code=409, detail="This order has payment or fulfilment history and cannot be removed. "
                                                    "Cancel it, or refund it, through its normal workflow; the record stays for audit.")
    now = now_iso()
    upd = {"$set": {"archived": True, "archived_at": now, "archived_by": admin["id"], "updated_at": now}}
    cancelling = o.get("status") != "cancelled"
    if cancelling:
        upd["$set"].update({"status": "cancelled", "cancel_reason": "removed_by_admin"})
        upd["$push"] = {"restock_intents": intent("admin_cancel", admin["id"], prev_status=o.get("status", ""))}
    r = await db.orders.update_one({"id": order_id, "status": o.get("status"), "payment_status": {"$in": list(REMOVABLE_PAYMENT)}}, upd)
    if r.matched_count != 1:
        raise HTTPException(status_code=409, detail="This order was just updated. Refresh and try again.")
    restocked = await run_intents(order_id) if cancelling else []
    await log_audit(admin, "order_removed", "order", order_id,
                    old_value={"order_number": o.get("order_number"), "status": o.get("status"), "payment_status": o.get("payment_status")},
                    new_value={"status": "cancelled", "archived": True, "restocked_lines": restocked}, request=request)
    return {"ok": True, "archived": True, "restocked_lines": restocked}


# ---------------- Payments ----------------
@router.get("/payments")
async def admin_payments(admin: dict = Depends(require_admin)):
    return await db.payment_transactions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


# ---------------- Activations / Referrals / Commissions ----------------
@router.get("/referrals")
async def admin_referrals(admin: dict = Depends(require_admin)):
    return await db.referral_relationships.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@router.get("/commissions")
async def admin_commissions(admin: dict = Depends(require_admin)):
    return await db.commissions.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


class CommissionActionBody(BaseModel):
    action: str  # release / hold
    reason: str = ""


@router.put("/commissions/{commission_id}/status")
async def commission_status(commission_id: str, body: CommissionActionBody, request: Request, admin: dict = Depends(require_money_admin)):
    """`release` is "release now" through the normal release path (same conditions, no override). `hold` sets a flag that keeps a
    commission out of the cron without changing its status, so refunds still claw it back. A hold is not a bypass: releasing a
    held commission needs every normal condition, exactly as for any other."""
    reason = (body.reason or "").strip()
    if len(reason) < 5 or len(reason) > 300:
        raise HTTPException(status_code=422, detail="A reason of 5 to 300 characters is required.")
    c = await db.commissions.find_one({"id": commission_id})
    if not c:
        raise HTTPException(status_code=404, detail="Commission not found.")
    if body.action == "release":
        from commission import release_commission_now
        res = await release_commission_now(commission_id)
        if not res["ok"]:
            raise HTTPException(status_code=res["code"], detail=res["detail"])
        if not res.get("already"):
            await log_audit(admin, "commission_released", "commission", commission_id,
                            old_value={"status": c.get("status")}, new_value={"status": "RELEASED", "released_paise": res.get("released_paise"), "reason": reason}, request=request)
        return {"ok": True, **{k: v for k, v in res.items() if k != "ok"}}
    if body.action == "hold":
        held = await db.commissions.update_one({"id": commission_id, "status": {"$in": ["PENDING", "PARTIALLY_REVERSED"]}, "released_at": None,
                                                 "manual_hold": {"$ne": True}},
                                               {"$set": {"manual_hold": True, "held_at": now_iso(), "held_by": admin["id"], "hold_reason": reason}})
        if held.modified_count != 1:
            raise HTTPException(status_code=409, detail="Only a pending, unreleased, not already held commission can be held.")
        await log_audit(admin, "commission_held", "commission", commission_id,
                        old_value={"status": c.get("status")}, new_value={"manual_hold": True, "reason": reason}, request=request)
        return {"ok": True, "status": c.get("status"), "manual_hold": True}
    raise HTTPException(status_code=400, detail="Invalid action.")


# ---------------- KYC review ----------------
@router.get("/kyc")
async def admin_kyc(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    recs = await db.kyc_records.find(q, {"_id": 0}).sort("submitted_at", -1).to_list(1000)
    for r in recs:
        if r.get("aadhaar"):
            r["aadhaar"] = mask_aadhaar(r["aadhaar"])
        if r.get("pan"):
            r["pan"] = _mask_pan(r["pan"])
        if r.get("bank_account"):
            r["bank_account"] = _mask_acct(r["bank_account"])
        if r.get("ifsc"):
            r["ifsc"] = _mask_ifsc(r["ifsc"])
    return recs


class KycReview(BaseModel):
    action: str  # verify / reject
    reason: Optional[str] = ""
    # The record version the reviewer looked at (GET /admin/kyc returns it). If the record changed since, the review is refused.
    expected_version: Optional[int] = None


class KycEditBody(BaseModel):
    pan: Optional[str] = None
    account_holder_name: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc: Optional[str] = None
    bank_name: Optional[str] = None


KYC_EDIT_FIELDS = ("pan", "account_holder_name", "bank_account", "ifsc", "bank_name")
_KYC_MASK = {"pan": _mask_pan, "bank_account": _mask_acct, "ifsc": _mask_ifsc}


def _kyc_audit_value(field: str, value) -> str:
    """Audit-safe rendering: PAN, account number and IFSC are masked; names are kept so the change stays traceable."""
    return _KYC_MASK.get(field, lambda v: str(v or ""))(value) if value else ""


@router.put("/kyc/{user_id}/edit")
async def admin_edit_kyc(user_id: str, body: KycEditBody, request: Request, admin: dict = Depends(require_money_admin)):
    """FINANCE ROLES ONLY (super_admin, accounts_admin): complete or correct a member's PAN and payout bank details.
    Any real change to a verified (or rejected) record sends it back to "pending": the old verification covered the old
    details, not the new ones. The audit keeps masked old and new values, never the full PAN or account number."""
    upd = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if "pan" in upd:
        upd["pan"] = upd["pan"].upper()
        if upd["pan"] and not re.fullmatch(r"[A-Z]{5}\d{4}[A-Z]", upd["pan"]):
            raise HTTPException(status_code=400, detail="Enter a valid 10-character PAN.")
    if "ifsc" in upd:
        upd["ifsc"] = upd["ifsc"].upper()
        if upd["ifsc"] and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", upd["ifsc"]):
            raise HTTPException(status_code=400, detail="Enter a valid 11-character IFSC.")
    if upd.get("bank_account") and not re.fullmatch(r"\d{6,18}", upd["bank_account"]):
        raise HTTPException(status_code=400, detail="Enter a valid bank account number (6 to 18 digits).")
    now = now_iso()
    existing = await db.kyc_records.find_one({"user_id": user_id})
    if existing:
        changed = [k for k in KYC_EDIT_FIELDS if k in upd and str(upd[k] or "") != str(existing.get(k) or "")]
        if not changed:
            return {"ok": True, "changed": [], "status": existing.get("status")}
        old_status = existing.get("status")
        sets = {k: upd[k] for k in changed}
        sets.update({"updated_at": now, "last_edited_by": admin["id"], "last_edited_at": now})
        reset = old_status != "pending"
        if reset:
            sets.update({"status": "pending", "verification_reset_at": now, "verification_reset_by": admin["id"],
                         "rejection_reason": None})
        await db.kyc_records.update_one({"user_id": user_id}, {"$set": sets, "$inc": {"version": 1}})
        if reset:
            await db.users.update_one({"id": user_id}, {"$set": {"kyc_status": "pending", "updated_at": now}})
            await create_notification(user_id, "kyc", "KYC details updated",
                                      "HOME GENIES updated your KYC details. They will be verified again before your next withdrawal.",
                                      "केवाईसी विवरण अपडेट", "HOME GENIES ने आपके केवाईसी विवरण अपडेट किए हैं। अगली निकासी से पहले इनका फिर से सत्यापन होगा।")
        await log_audit(admin, "kyc_edited_by_admin", "kyc", user_id,
                        old_value={"status": old_status, **{k: _kyc_audit_value(k, existing.get(k)) for k in changed}},
                        new_value={"status": "pending" if reset else old_status, **{k: _kyc_audit_value(k, upd[k]) for k in changed}},
                        request=request)
        return {"ok": True, "changed": changed, "status": "pending" if reset else old_status, "verification_reset": reset}
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="Distributor not found.")
    doc = {k: upd[k] for k in KYC_EDIT_FIELDS if k in upd}
    doc.update({"id": new_id(), "user_id": user_id, "distributor_id": u.get("distributor_id"), "status": "pending", "version": 1,
                "aadhaar": "", "created_at": now, "submitted_at": now, "updated_at": now,
                "last_edited_by": admin["id"], "last_edited_at": now})
    try:
        await db.kyc_records.insert_one(doc)
    except DuplicateKeyError:            # W5: the member submitted at the same moment (one record per member); nothing was changed
        raise HTTPException(status_code=409, detail="This member's KYC record was just created. Reload and edit it.")
    await db.users.update_one({"id": user_id}, {"$set": {"kyc_status": "pending"}})
    await log_audit(admin, "kyc_edited_by_admin", "kyc", user_id, old_value=None,
                    new_value={"status": "pending", **{k: _kyc_audit_value(k, doc.get(k)) for k in KYC_EDIT_FIELDS if k in doc}},
                    request=request)
    return {"ok": True, "changed": [k for k in KYC_EDIT_FIELDS if k in doc], "status": "pending", "verification_reset": False}


@router.put("/kyc/{user_id}")
async def review_kyc(user_id: str, body: KycReview, request: Request, admin: dict = Depends(require_admin)):
    k = await db.kyc_records.find_one({"user_id": user_id}, {"_id": 0})
    if not k:
        raise HTTPException(status_code=404, detail="KYC record not found.")
    new_status = None
    if body.action == "verify":
        new_status = "verified"
    elif body.action == "reject":
        new_status = "rejected"
    else:
        raise HTTPException(status_code=400, detail="Invalid action.")
    stale = HTTPException(status_code=409, detail="These KYC details changed after you opened them. Reload and review the latest details.")
    if new_status == "verified" and k.get("last_edited_by") and k["last_edited_by"] == admin["id"]:
        # Decision 8: material KYC changes need an independent second person; the editor cannot verify their own change.
        raise HTTPException(status_code=403, detail="You changed these KYC details, so another administrator must verify them.")
    version = k.get("version")
    if body.expected_version is not None and body.expected_version != (version or 0):
        raise stale
    # Atomic: the decision applies only to exactly the record that was read (same version AND same status). An edit or a
    # resubmission in between bumps the version, so a stale "verify" can never mark new bank/PAN details verified.
    r = await db.kyc_records.update_one({"user_id": user_id, "status": k.get("status"), "version": version},
                                        {"$set": {"status": new_status, "rejection_reason": body.reason, "updated_at": now_iso(),
                                                  "reviewed_by": admin["id"], "reviewed_at": now_iso()},
                                         "$inc": {"version": 1}})
    if not r.modified_count:
        raise stale
    await db.users.update_one({"id": user_id}, {"$set": {"kyc_status": new_status, "updated_at": now_iso()}})
    await create_notification(user_id, "kyc",
                              "KYC verified" if new_status == "verified" else "KYC rejected",
                              "Your KYC has been verified." if new_status == "verified"
                              else f"Your KYC was rejected: {body.reason}",
                              "केवाईसी सत्यापित" if new_status == "verified" else "केवाईसी अस्वीकृत",
                              "आपकी केवाईसी सत्यापित हो गई है।" if new_status == "verified"
                              else f"आपकी केवाईसी अस्वीकृत: {body.reason}")
    await log_audit(admin, "kyc_reviewed", "kyc", user_id, new_value={"status": new_status}, request=request)
    return {"ok": True, "status": new_status}


# ---------------- Withdrawals review ----------------
@router.get("/withdrawals")
async def admin_withdrawals(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    q = {}
    if status:
        q["status"] = status
    rows = await db.withdrawal_requests.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    ids = {r.get(k) for r in rows for k in ("approved_by", "paid_by", "rejected_by") if r.get(k)}
    names = {u["id"]: u.get("full_name") for u in await db.users.find({"id": {"$in": list(ids)}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(len(ids) or 1)}
    for r in rows:
        for k in ("approved_by", "paid_by", "rejected_by"):
            if r.get(k):
                r[k + "_name"] = names.get(r[k])
    return rows


class WithdrawalReview(BaseModel):
    action: str  # approve / reject / mark_paid
    note: Optional[str] = ""
    payout_reference: Optional[str] = None   # required for mark_paid: the bank / UTR / processor reference the finance user supplies


# The business state REQUESTED is stored as "pending" (what POST /api/withdrawals creates). "under_review" is never created by any
# route; a legacy record in it is treated exactly as requested everywhere (review, dashboard count, finance report, screens).
REQUESTED_STATES = ("pending", "under_review")
PAYOUT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/#:\-]{2,63}$")


def _finalised():
    return HTTPException(status_code=400, detail="This withdrawal has already been finalised.")


@router.put("/withdrawals/{wd_id}")
async def review_withdrawal(wd_id: str, body: WithdrawalReview, request: Request, admin: dict = Depends(require_money_admin)):
    """Withdrawal review: super_admin / accounts_admin only. The workflow is REQUESTED -> APPROVED -> PAID, or -> REJECTED.

    approve   : requested -> approved; the approver and time are recorded (a legacy approval without an approver may be re-recorded).
    reject    : requested or approved -> rejected; the reservation returns to available.
    mark_paid : approved -> paid only, by a DIFFERENT finance user from the approver, with a payout reference that has not been
                used for another withdrawal. The money moves FIRST in one conditional wallet update that re-checks the wallet
                is still safe (available balance not negative, reservation still in pending) and records the operation key, so
                pay and reject exclude each other and neither applies twice. Then the status is claimed. A retry finishes it."""
    wr = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0})
    if not wr:
        raise HTTPException(status_code=404, detail="Withdrawal not found.")
    if body.action not in ("approve", "mark_paid", "reject"):
        raise HTTPException(status_code=400, detail="Invalid action.")
    settings = await get_settings()
    sym = settings.get("currency_symbol", "₹")
    now = now_iso()
    note = (body.note or "").strip()[:300]

    if body.action in ("approve", "mark_paid"):
        # Batch 12 (audit C-13): the KYC rule that admitted the request is re-checked when it is approved and when it is paid.
        # Bank or identity details changed since the request put KYC back to review, and money must not go to unverified details.
        if settings.get("require_kyc_for_withdrawal", True):
            kyc = await db.kyc_records.find_one({"user_id": wr["user_id"]}, {"_id": 0, "status": 1})
            if not kyc or kyc.get("status") != "verified":
                raise HTTPException(status_code=409, detail="The member's identity and bank details are not verified now (they changed "
                                                            "after the request). Verify KYC again before approving or paying.")

    if body.action == "approve":
        if wr.get("status") == "approved" and wr.get("approved_by"):
            if wr["approved_by"] == admin["id"]:
                return {"ok": True, "status": "approved", "already": True}
            raise HTTPException(status_code=409, detail="This withdrawal was already approved by another finance user.")
        flt = {"id": wd_id, "$or": [{"status": {"$in": list(REQUESTED_STATES)}}, {"status": "approved", "approved_by": None}]}
        claimed = await db.withdrawal_requests.update_one(
            flt, {"$set": {"status": "approved", "approved_by": admin["id"], "approved_at": now, "admin_note": note, "updated_at": now}})
        if claimed.modified_count != 1:
            current = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0}) or {}
            if current.get("status") == "approved" and current.get("approved_by") == admin["id"]:
                return {"ok": True, "status": "approved", "already": True}
            if current.get("status") == "approved":
                raise HTTPException(status_code=409, detail="This withdrawal was already approved by another finance user.")
            raise _finalised()
        await log_audit(admin, "withdrawal_approved", "withdrawal", wd_id, old_value={"status": wr["status"]},
                        new_value={"status": "approved", "approved_by": admin["id"]}, request=request)
        await create_notification(wr["user_id"], "withdrawal", "Withdrawal approved",
                                  f"Your withdrawal of {sym}{int(wr['amount'])} is approved and will be paid.",
                                  "निकासी स्वीकृत", f"आपकी {sym}{int(wr['amount'])} की निकासी स्वीकृत हुई।")
        return {"ok": True, "status": "approved"}

    wd_p = paise_of(wr, "amount_paise", "amount")
    pay_op, reject_op = f"withdrawal_paid:{wd_id}", f"withdrawal_rejected:{wd_id}"
    my_op = pay_op if body.action == "mark_paid" else reject_op
    target = "paid" if body.action == "mark_paid" else "rejected"
    # Programme 03 (audit P03-A04): fail closed BEFORE the wallet moves, not only at the ledger row after it (B-004 pattern)
    from money_guard import ensure as _money_guard
    await _money_guard("wallet")
    wallet = await db.wallets.find_one({"user_id": wr["user_id"]}, {"_id": 0, "applied_ops": 1}) or {}
    done = set(wallet.get("applied_ops") or [])
    if (pay_op in done or reject_op in done) and my_op not in done:
        raise _finalised()
    ref = None
    if my_op not in done:                                   # first attempt: every precondition is checked before money moves
        if body.action == "mark_paid":
            if wr.get("status") != "approved":
                raise HTTPException(status_code=409, detail="A withdrawal must be approved before it can be paid."
                                    if wr.get("status") in REQUESTED_STATES else "This withdrawal has already been finalised.")
            if not wr.get("approved_by"):
                raise HTTPException(status_code=409, detail="This approval predates approver records. Approve it again before paying.")
            if wr["approved_by"] == admin["id"]:
                raise HTTPException(status_code=403, detail="The finance user who approved this withdrawal cannot also pay it.")
            ref = (body.payout_reference or "").strip()
            if not PAYOUT_REF_RE.match(ref):
                raise HTTPException(status_code=422, detail="A payout reference (UTR / bank or processor reference, 3-64 characters: "
                                                            "letters, digits, space and . _ / # : -) is required to mark a withdrawal paid.")
            try:                                            # one reference, one withdrawal (the _id makes this race-safe)
                await db.withdrawal_payout_refs.insert_one({"_id": ref.upper(), "withdrawal_id": wd_id, "by": admin["id"], "at": now})
            except DuplicateKeyError:
                owner = await db.withdrawal_payout_refs.find_one({"_id": ref.upper()}) or {}
                if owner.get("withdrawal_id") != wd_id:
                    raise HTTPException(status_code=409, detail="This payout reference is already recorded for another withdrawal.")
            flt = {"available_balance_paise": {"$gte": 0}, "pending_balance_paise": {"$gte": wd_p}}
            inc = {"pending_balance_paise": -wd_p, "pending_balance": paise_to_float(-wd_p),
                   "total_withdrawn_paise": wd_p, "total_withdrawn": paise_to_float(wd_p)}
        else:
            if wr.get("status") not in REQUESTED_STATES + ("approved",):
                raise _finalised()
            flt = {"pending_balance_paise": {"$gte": wd_p}}
            inc = {"pending_balance_paise": -wd_p, "pending_balance": paise_to_float(-wd_p),
                   "available_balance_paise": wd_p, "available_balance": paise_to_float(wd_p)}
        moved = await db.wallets.update_one(
            {"user_id": wr["user_id"], "applied_ops": {"$nin": [pay_op, reject_op]}, **flt},
            {"$inc": inc, "$push": {"applied_ops": my_op}, "$set": {"updated_at": now}})
        if moved.modified_count != 1:
            wallet = await db.wallets.find_one({"user_id": wr["user_id"]}, {"_id": 0}) or {}
            ops = wallet.get("applied_ops") or []
            if my_op not in ops:
                if ref:
                    await db.withdrawal_payout_refs.delete_one({"_id": ref.upper(), "withdrawal_id": wd_id})   # nothing was paid
                if pay_op in ops or reject_op in ops:
                    raise _finalised()
                if body.action == "mark_paid":
                    raise HTTPException(status_code=409, detail=(
                        "This withdrawal cannot be paid: the HomeGenie's earnings were reversed after it was requested, so the "
                        f"wallet is not in a safe state (available {sym}{wallet.get('available_balance', 0)}). Reject it, or wait "
                        "until future earnings cover the shortfall."))
                raise HTTPException(status_code=409, detail="The withdrawal reservation is no longer in the wallet; finance must review it.")
    else:                                                   # a retry after the money already moved: just finish the record
        ref = (await db.withdrawal_payout_refs.find_one({"withdrawal_id": wd_id}) or {}).get("_id") if body.action == "mark_paid" else None
    from financial_ops import ensure_ledger
    await ensure_ledger({"id": new_id(), "user_id": wr["user_id"], "type": "WITHDRAWAL", "status": "PAID" if target == "paid" else "REJECTED",
                         "direction": "debit" if target == "paid" else "credit", "amount": paise_to_float(wd_p), "amount_paise": wd_p,
                         "reference": wd_id, "op_key": my_op, "created_by": admin["id"], "created_at": now,
                         "description": f"Withdrawal paid (ref {ref})" if target == "paid" else "Withdrawal rejected - amount returned"})
    sets = {"status": target, "admin_note": note, "updated_at": now}
    if target == "paid":
        stored_ref = (await db.withdrawal_payout_refs.find_one({"withdrawal_id": wd_id}) or {}).get("_id") or ref
        sets.update({"paid_by": admin["id"], "paid_at": now, "payout_reference": stored_ref})
        from_states = ["approved"]
    else:
        sets.update({"rejected_by": admin["id"], "rejected_at": now})
        from_states = list(REQUESTED_STATES) + ["approved"]
    claimed = await db.withdrawal_requests.update_one({"id": wd_id, "status": {"$in": from_states}}, {"$set": sets})
    if claimed.modified_count != 1:
        current = await db.withdrawal_requests.find_one({"id": wd_id}, {"_id": 0, "status": 1})
        if (current or {}).get("status") == target:
            return {"ok": True, "status": target, "already": True}          # a retry of a finished pay / reject
        raise _finalised()
    await create_notification(wr["user_id"], "withdrawal", f"Withdrawal {target}",
                              f"Your withdrawal of {sym}{int(wr['amount'])} is now {target}.",
                              f"निकासी {target}",
                              f"आपकी {sym}{int(wr['amount'])} की निकासी अब {target} है।")
    await log_audit(admin, f"withdrawal_{target}", "withdrawal", wd_id, old_value={"status": wr["status"]},
                    new_value={"status": target, **({"payout_reference": sets.get("payout_reference"), "approved_by": wr.get("approved_by")}
                                                     if target == "paid" else {})}, request=request)
    return {"ok": True, "status": target, **({"payout_reference": sets["payout_reference"]} if target == "paid" else {})}


# ---------------- Settings ----------------
@router.get("/settings")
async def admin_get_settings(admin: dict = Depends(require_admin)):
    return await get_settings()


class SettingsBody(BaseModel):
    commission_direct_pct: Optional[float] = None
    commission_referral_pct: Optional[float] = None
    commission_team_pct: Optional[float] = None
    return_window_days: Optional[int] = None
    point_value: Optional[float] = None
    points_withdrawal_enabled: Optional[bool] = None
    cod_enabled: Optional[bool] = None
    cod_fee: Optional[float] = None
    badge_t1_sales: Optional[float] = None
    badge_t2_sales: Optional[float] = None
    badge_t3_sales: Optional[float] = None
    badge_t4_sales: Optional[float] = None
    require_kyc_for_withdrawal: Optional[bool] = None
    gst_percent: Optional[float] = None
    company_name: Optional[str] = None
    company_email: Optional[str] = None
    company_phone: Optional[str] = None
    company_address: Optional[str] = None


# Settings that change who is paid how much, when, or under which checks. Any admin may still edit the others.
MONEY_POLICY_SETTINGS = ("commission_direct_pct", "commission_referral_pct", "commission_team_pct", "return_window_days", "point_value",
                         "points_withdrawal_enabled", "cod_enabled", "cod_fee", "require_kyc_for_withdrawal", "gst_percent")
_PCT = ("commission_direct_pct", "commission_referral_pct", "commission_team_pct")


def _settings_problems(new: dict) -> list:
    """Technical validity only (no policy): finite, non-negative, percentages within 0-100 and the three commission rates
    together at most 100% of the base, whole days, a positive point value."""
    out = []
    for k, v in new.items():
        if isinstance(v, float) and not math.isfinite(v):
            out.append(f"{k} must be a finite number")
    for k in _PCT + ("gst_percent",):
        if new.get(k) is not None and not 0 <= new[k] <= 100:
            out.append(f"{k} must be between 0 and 100")
    if sum(float(new.get(k) or 0) for k in _PCT) > 100:
        out.append("the three commission percentages together cannot exceed 100")
    if new.get("return_window_days") is not None and not 0 <= new["return_window_days"] <= 365:
        out.append("return_window_days must be between 0 and 365")
    if new.get("point_value") is not None and not new["point_value"] > 0:
        out.append("point_value must be greater than 0")
    for k in ("cod_fee", "badge_t1_sales", "badge_t2_sales", "badge_t3_sales", "badge_t4_sales"):
        if new.get(k) is not None and new[k] < 0:
            out.append(f"{k} cannot be negative")
    return out


@router.put("/settings")
async def admin_update_settings(body: SettingsBody, request: Request, admin: dict = Depends(require_admin)):
    old = await get_settings()
    upd = {k: v for k, v in body.model_dump().items() if v is not None}
    changed_money = [k for k in MONEY_POLICY_SETTINGS if k in upd and upd[k] != old.get(k)]
    if changed_money and admin.get("role") not in MONEY_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Only a finance administrator can change: " + ", ".join(changed_money) + ".")
    problems = _settings_problems({**{k: old.get(k) for k in _PCT}, **upd})
    if problems:
        raise HTTPException(status_code=422, detail="; ".join(problems))
    await db.business_settings.update_one({"id": "business_settings"}, {"$set": upd})
    await log_audit(admin, "settings_updated", "business_settings", "business_settings",
                    old_value=old, new_value=upd, request=request)
    return await get_settings()


@router.post("/referral-codes")
async def gen_referral_code(request: Request, admin: dict = Depends(require_admin)):
    code = "ANJ" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    doc = {"id": new_id(), "code": code, "active": True, "created_by": admin["id"],
           "created_by_name": admin.get("full_name"), "uses": 0, "created_at": now_iso()}
    await db.referral_codes.insert_one(dict(doc))
    doc.pop("_id", None)
    await log_audit(admin, "referral_code_generated", "referral_code", code, request=request)
    return doc


@router.get("/referral-codes")
async def list_referral_codes(admin: dict = Depends(require_admin)):
    return await db.referral_codes.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@router.delete("/referral-codes/{code}")
async def delete_referral_code(code: str, request: Request, admin: dict = Depends(require_admin)):
    rc = await db.referral_codes.find_one({"code": code})
    if not rc:
        raise HTTPException(status_code=404, detail="Reference code not found.")
    if rc.get("is_master"):
        raise HTTPException(status_code=400, detail="The master reference ID cannot be deleted.")
    await db.referral_codes.delete_one({"code": code})
    await log_audit(admin, "referral_code_deleted", "referral_code", code, request=request)
    return {"ok": True}


class ResetBody(BaseModel):
    confirm: str


@router.get("/registration-requests")
async def list_registration_requests(admin: dict = Depends(require_admin)):
    rows = await db.registration_requests.find({}, {"_id": 0, "password_hash": 0, "env_credential_marker": 0}).sort("created_at", -1).to_list(500)
    for r in rows:                                   # never send the raw Aadhaar number to the admin panel
        a = r.pop("aadhaar_number", None)
        if a:
            r["aadhaar_masked"] = mask_aadhaar(a)
    return rows


async def activate_registration(r: dict, approver: Optional[dict] = None) -> str:
    """Create the account for a registration request (idempotent) and mark the request approved.
    Used on registration itself (no admin approval needed for normal users), by the lazy/sweep activation of
    requests that were left pending, and by the admin Approve button. Never creates a second user for a mobile/email."""
    existing = await db.users.find_one({"$or": [{"mobile": r["mobile"]}] + ([{"email": r["email"]}] if r.get("email") else [])})
    if existing:
        did = existing.get("distributor_id")
    else:
        # Decision 5: a CUSTOMER only shops. It gets its own role and id prefix, no sponsor link and no earning capability.
        # Every other request (the existing sign-up) still creates a RED distributor, exactly as before.
        is_customer = r.get("account_type") == "customer"
        did = await next_sequence("customer", "CU", 6) if is_customer else await next_distributor_id()
        user = {
            "id": new_id(), "distributor_id": did, "full_name": r["full_name"],
            "email": r.get("email") or None, "mobile": r["mobile"], "password_hash": r["password_hash"],
            "role": "customer" if is_customer else "distributor", "status": "customer" if is_customer else "red",
            "account_status": "active",
            "mobile_verified": bool(r.get("mobile_verified")), "email_verified": bool(r.get("email_verified")),
            "google_linked": bool(r.get("google_linked")),
            "sponsor_id": None if is_customer else (r.get("sponsor_id") or None), "sponsor_user_id": None,
            "address": r.get("address", ""), "state": r.get("state", ""), "city": r.get("city", ""),
            "pincode": r.get("pincode", ""), "aadhaar_number": r.get("aadhaar_number", ""), "kyc_status": "not_started",
            "profile_complete": bool(r.get("email")), "created_at": now_iso(), "updated_at": now_iso(),
        }
        try:
            await db.users.insert_one(dict(user))
        except Exception:
            raise HTTPException(status_code=400, detail="Could not create distributor (possibly a duplicate email or mobile). Please check and try again.")
        await get_or_create_wallet(user["id"])
        # HOME GENIES: approval records the sponsor link only. No reward is paid. Customers never get a sponsor link.
        sp_did = None if is_customer else r.get("sponsor_id")
        if sp_did:
            rc = await db.referral_codes.find_one({"code": sp_did, "active": True})
            if rc:
                sponsor = await db.users.find_one({"id": rc.get("created_by")}) or await db.users.find_one({"role": "super_admin"})
                parent_label = rc["code"]  # the referral code itself is the recorded parent
                await db.referral_codes.update_one({"code": sp_did}, {"$inc": {"uses": 1}})  # counted once, when the account is created
            else:
                sponsor = await db.users.find_one({"distributor_id": sp_did})
                parent_label = sp_did
            if sponsor:
                await db.users.update_one({"id": user["id"]},
                                          {"$set": {"sponsor_user_id": sponsor["id"], "sponsor_distributor_id": parent_label}})
                if not await db.referral_relationships.find_one({"referred_user_id": user["id"]}):
                    await db.referral_relationships.insert_one({
                        "id": new_id(), "sponsor_id": sponsor["id"],
                        "sponsor_distributor_id": parent_label,
                        "referred_user_id": user["id"], "referred_distributor_id": did,
                        "commission_paid": False, "created_at": now_iso(),
                    })
                # HOME GENIES: no reward is paid for a registration. Recruitment alone
                # never generates commission — only the sponsor link is recorded above.
    await db.registration_requests.update_one({"id": r["id"]},
        {"$set": {"status": "approved", "distributor_id": did, "approved_by": (approver or {}).get("id") or "auto",
                  "approved_at": now_iso()}})
    return did


async def activate_pending_registrations() -> int:
    """One-off, idempotent sweep: turn requests left 'pending' into accounts (no duplicates). Run at DB init."""
    n = 0
    async for r in db.registration_requests.find({"status": "pending"}):
        try:
            await activate_registration(r)
            n += 1
        except Exception:
            continue
    return n


@router.post("/registration-requests/{req_id}/approve")
async def approve_registration_request(req_id: str, request: Request, admin: dict = Depends(require_admin)):
    r = await db.registration_requests.find_one({"id": req_id})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    if r.get("status") == "approved":
        raise HTTPException(status_code=400, detail="This request is already approved.")
    if await db.users.find_one({"mobile": r["mobile"]}):
        raise HTTPException(status_code=400, detail="A user with this mobile already exists.")
    did = await activate_registration(r, admin)
    await log_audit(admin, "registration_approved", "user", did, new_value={"distributor_id": did}, request=request)
    return {"message": f"Approved. HomeGenie ID {did} created.", "distributor_id": did}


class RejectReqBody(BaseModel):
    reason: str = ""


@router.post("/registration-requests/{req_id}/reject")
async def reject_registration_request(req_id: str, request: Request, body: RejectReqBody = RejectReqBody(), admin: dict = Depends(require_admin)):
    r = await db.registration_requests.find_one({"id": req_id})
    if not r:
        raise HTTPException(status_code=404, detail="Request not found.")
    if r.get("status") == "approved":
        # the account was already created at registration; rejecting the record would contradict the live account
        raise HTTPException(status_code=400, detail="This registration has already created an active account and cannot be rejected.")
    await db.registration_requests.update_one({"id": req_id},
        {"$set": {"status": "rejected", "rejection_reason": (body.reason or "").strip(),
                  "rejected_by": admin["id"], "rejected_at": now_iso()}})
    await log_audit(admin, "registration_rejected", "registration_request", req_id,
                    new_value={"reason": (body.reason or "").strip()}, request=request)
    return {"message": "Request rejected."}


class BlockBody(BaseModel):
    blocked: bool


_NO_PREV = object()
_NOT_DELETED = {"deleted_at": None, "deleted_by": None}   # write-time guard: missing or null deletion markers only


def _deletion_marked(u: dict) -> bool:
    """A deactivation marker wins over everything else. Before Batch 0, blocking a deactivated account overwrote
    account_status "deleted" with "blocked" but left deleted_at / deleted_by behind, so the status alone is not enough."""
    return u.get("account_status") == "deleted" or bool(u.get("deleted_at")) or bool(u.get("deleted_by"))


async def _status_before_legacy_block(u: dict) -> str:
    """For an account blocked before the previous status was recorded (never called for deletion-marked accounts).
    Members, staff and admins had no activation gate, so they return to "active". A vendor owner returns to "active" only
    with evidence that the owner account was activated: users.activated_at (direct activation), users.invite_accepted_at
    (owner invitation accepted) or vendors.owner_activation == "active". An invitation that was only SENT restores
    "invited"; anything else restores "pending_approval". A vendor record existing is never evidence of activation."""
    if u.get("role") != "vendor":
        return "active"
    if u.get("activated_at") or u.get("invite_accepted_at"):
        return "active"
    v = await db.vendors.find_one({"user_id": u["id"]}, {"_id": 0, "owner_activation": 1})
    act = (v or {}).get("owner_activation")
    if act == "active":
        return "active"
    return "invited" if act == "invited" else "pending_approval"


@router.put("/users/{user_id}/block")
async def block_user(user_id: str, body: BlockBody, request: Request, admin: dict = Depends(require_admin)):
    """Block keeps the account's real status in `pre_block_status`; unblock puts exactly that status back. Unblocking never
    activates an account: a vendor owner awaiting approval or an invitation stays not-activated, and a deactivated
    (deleted) account cannot be blocked or unblocked at all."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    _guard_target(admin, u, "block or unblock")
    _guard_vendor_account(admin, u, "block or unblock")
    status = u.get("account_status")
    if _deletion_marked(u):
        raise HTTPException(status_code=409, detail="This account is deactivated. It cannot be blocked or unblocked.")
    is_blocked = bool(u.get("blocked")) or status == "blocked"
    now = now_iso()
    if body.blocked:
        if is_blocked:
            return {"ok": True, "blocked": True, "account_status": status, "unchanged": True}
        r = await db.users.update_one({"id": user_id, "account_status": status, "blocked": {"$ne": True}, **_NOT_DELETED},
                                      {"$set": {"blocked": True, "account_status": "blocked", "pre_block_status": status,
                                                "blocked_at": now, "blocked_by": admin["id"], "updated_at": now}})
        if not r.modified_count:
            raise HTTPException(status_code=409, detail="The account changed while you were blocking it. Please reload.")
        await log_audit(admin, "user_blocked", "user", user_id, old_value={"account_status": status},
                        new_value={"account_status": "blocked"}, request=request)
        return {"ok": True, "blocked": True, "account_status": "blocked"}
    if not is_blocked:
        return {"ok": True, "blocked": False, "account_status": status, "unchanged": True}
    prev = u.get("pre_block_status", _NO_PREV)
    if prev is _NO_PREV:                                   # blocked before the previous status was recorded
        prev = await _status_before_legacy_block(u) if status == "blocked" else status
    if prev == "deleted":
        raise HTTPException(status_code=409, detail="This account is deactivated. It cannot be unblocked.")
    if prev in (None, "", "blocked"):
        prev = "active" if u.get("role") != "vendor" else await _status_before_legacy_block(u)
    r = await db.users.update_one({"id": user_id, "account_status": status, **_NOT_DELETED},
                                  {"$set": {"blocked": False, "account_status": prev, "unblocked_at": now,
                                            "unblocked_by": admin["id"], "updated_at": now},
                                   "$unset": {"pre_block_status": ""}})
    if not r.modified_count:
        raise HTTPException(status_code=409, detail="The account changed while you were unblocking it. Please reload.")
    await log_audit(admin, "user_unblocked", "user", user_id, old_value={"account_status": status},
                    new_value={"account_status": prev}, request=request)
    return {"ok": True, "blocked": False, "account_status": prev}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request, admin: dict = Depends(require_admin)):
    """DEACTIVATES the account; it never erases it. The user document, wallet, ledger, orders, commissions and audit
    references stay, so financial history is kept. The account is blocked and every existing session is refused.
    Repeated requests change nothing. Personal-data anonymisation is not performed: no retention policy is defined yet."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    if u.get("role") in {"super_admin", "admin", "accounts_admin", "support_admin"}:
        raise HTTPException(status_code=400, detail="Admin accounts cannot be deleted.")
    _guard_vendor_account(admin, u, "deactivate")
    if u.get("account_status") == "deleted":
        return {"ok": True, "already_deactivated": True}
    now = now_iso()
    await db.users.update_one({"id": user_id, "account_status": {"$ne": "deleted"}},
                              {"$set": {"account_status": "deleted", "blocked": True, "deleted_at": now,
                                        "deleted_by": admin["id"], "updated_at": now}})
    await log_audit(admin, "user_deactivated", "user", user_id,
                    old_value={"distributor_id": u.get("distributor_id"), "account_status": u.get("account_status")},
                    new_value={"account_status": "deleted"}, request=request)
    return {"ok": True, "deactivated": True}


class AdminUserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    pincode: Optional[str] = None
    aadhaar_number: Optional[str] = None


@router.put("/users/{user_id}")
async def admin_update_user(user_id: str, body: AdminUserUpdate, request: Request, admin: dict = Depends(require_admin)):
    """Admin completes/corrects a member's profile. Admin accounts can be edited only by the super admin, and the super admin
    account not at all (see _guard_target). Name/address/Aadhaar changes apply at once. A mobile or email change is only
    PROPOSED (contact_change.py): the live contact stays the trusted one until the account holder confirms with a code sent to
    that trusted mobile, or a super admin who did not propose it approves a reviewed recovery. So an admin can never point an
    account's OTP/Google login or recovery at a contact they control."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    _guard_target(admin, u, "edit")
    upd = {k: (v.strip() if isinstance(v, str) else v) for k, v in body.model_dump().items() if v is not None}
    if "email" in upd:
        upd["email"] = upd["email"].lower() or None
        if upd["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", upd["email"]):
            raise HTTPException(status_code=400, detail="Enter a valid email address, or leave it blank.")
    if "mobile" in upd and not re.fullmatch(r"[6-9]\d{9}", upd["mobile"] or ""):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    if upd.get("aadhaar_number") and not re.fullmatch(r"\d{12}", upd["aadhaar_number"]):
        raise HTTPException(status_code=400, detail="Enter a valid 12-digit Aadhaar number.")
    if upd.get("aadhaar_number") == "":
        upd.pop("aadhaar_number")                       # blank means "leave unchanged", never "erase"
    proposed = {k: upd.pop(k) for k in ("email", "mobile") if k in upd}
    proposed = {k: v for k, v in proposed.items() if (v or None) != (u.get(k) or None)}
    for k, v in proposed.items():
        if v and await db.users.find_one({k: v, "id": {"$ne": user_id}}, {"_id": 1}):
            raise HTTPException(status_code=409, detail=f"This {k} is already used by another account.")
    if upd:
        await db.users.update_one({"id": user_id}, {"$set": {**upd, "updated_at": now_iso()}})
        aadhaar_changed = "aadhaar_number" in upd and upd["aadhaar_number"] != u.get("aadhaar_number")
        await log_audit(admin, "user_profile_updated", "user", user_id,
                        old_value={"aadhaar_number": mask_aadhaar(u.get("aadhaar_number"))} if aadhaar_changed else None,
                        new_value={"fields": sorted(upd), **({"aadhaar_number": mask_aadhaar(upd["aadhaar_number"])} if aadhaar_changed else {})},
                        request=request)
    contact_change = None
    if proposed:
        from contact_change import propose_contact_change
        contact_change = await propose_contact_change(admin, u, proposed, request)
    updated = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0, "env_credential_marker": 0})
    if updated.get("aadhaar_number"):
        updated["aadhaar_masked"] = mask_aadhaar(updated["aadhaar_number"])
        updated.pop("aadhaar_number", None)
    return {**updated, "contact_change": contact_change}


class WalletCreditBody(BaseModel):
    distributor_id: str
    amount: float = Field(gt=0, le=10_000_000, allow_inf_nan=False)       # technical bound against typing errors, not a policy limit
    reason: str
    request_id: str                                                         # idempotency key: a retry or double click credits once

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: float) -> float:
        exponent = Decimal(str(v)).as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError("amount can have at most 2 decimal places")
        return v

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if not 5 <= len(v) <= 300:
            raise ValueError("reason must be 5 to 300 characters")
        return v

    @field_validator("request_id")
    @classmethod
    def _request_id(cls, v: str) -> str:
        v = v.strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", v):
            raise ValueError("request_id must be 8-64 characters: letters, digits, _ and -")
        return v


@router.post("/wallet/credit")
async def admin_wallet_credit(body: WalletCreditBody, request: Request, admin: dict = Depends(require_money_admin)):
    """Decision 4 (maker-checker): a manual credit is only REQUESTED here; a different finance admin approves it
    (POST /api/admin/finance/approvals/{id}/approve), which runs `apply_wallet_credit`."""
    did = (body.distributor_id or "").strip().upper()
    if not await db.users.find_one({"distributor_id": did}, {"_id": 1}):
        raise HTTPException(status_code=404, detail=f"Distributor {did} not found.")
    from financial_approvals import submit
    return await submit("wallet_credit", body.request_id, body.model_dump(), admin, body.reason, request,
                        summary={"distributor_id": did, "amount": body.amount})


async def apply_wallet_credit(body: WalletCreditBody, request: Optional[Request], admin: dict):
    """Manual points credit. Finance administrators only; exact amount, mandatory reason and idempotency key; one ledger row and
    one wallet move per key (the same pattern as commission release); audited. A repeated key returns the original credit."""
    did = (body.distributor_id or "").strip().upper()
    u = await db.users.find_one({"distributor_id": did})
    if not u:
        raise HTTPException(status_code=404, detail=f"Distributor {did} not found.")
    paise = to_paise(body.amount)
    op = f"admin_credit:{body.request_id}"
    existing = await db.wallet_transactions.find_one({"op_key": op}, {"_id": 0})
    if existing:
        if existing.get("user_id") != u["id"] or existing.get("amount_paise") != paise:
            raise HTTPException(status_code=409, detail="This request_id was already used for a different credit.")
        return {"message": "This credit was already applied.", "already": True, "distributor_id": did, "amount": paise_to_float(paise)}
    from financial_ops import ensure_ledger, move_wallet_once
    await ensure_ledger({"id": new_id(), "user_id": u["id"], "type": "MANUAL_ADMIN_CREDIT", "direction": "credit", "status": "CREDITED",
                         "amount": paise_to_float(paise), "amount_paise": paise, "reference": f"admin:{admin.get('distributor_id', '')}",
                         "description": body.reason, "op_key": op, "created_by": admin["id"], "created_at": now_iso()})
    moved = await move_wallet_once(u["id"], {"available_balance": paise, "total_earned": paise}, op)
    if moved:
        await create_notification(u["id"], "wallet", f"₹{int(paise // 100)} credited",
                                  f"{body.reason} — ₹{paise_to_float(paise)} added to your wallet.",
                                  f"₹{int(paise // 100)} क्रेडिट हुआ", f"{body.reason} — ₹{paise_to_float(paise)} आपके वॉलेट में जोड़े गए।")
        await log_audit(admin, "admin_wallet_credit", "user", u["id"],
                        new_value={"distributor_id": did, "amount_paise": paise, "reason": body.reason, "request_id": body.request_id}, request=request)
    from core import get_or_create_wallet
    w = await get_or_create_wallet(u["id"])
    return {"message": f"₹{paise_to_float(paise)} credited to {did}.", "distributor_id": did, "amount": paise_to_float(paise),
            "available_balance": round(float((w or {}).get("available_balance", 0)), 2)}


class AdminPwBody(BaseModel):
    # The admin chooses a TEMPORARY password and gives it to the member through their own trusted channel. The server never
    # generates or returns a password. The member must choose a new password at the next sign-in (core.PASSWORD_CHANGE_PATHS).
    temporary_password: str = Field(default="", max_length=128)
    reason: str = Field(default="", max_length=300)


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, body: AdminPwBody, request: Request, admin: dict = Depends(require_admin)):
    """Forced password change. Rules: super_admin accounts cannot be reset here; other admin accounts only by the super
    admin; an admin never resets their own account here; not-activated vendor owners are activated only by invitation and
    deactivated accounts are not reset. Every existing session of the member stops working at once. The response and the
    audit trail never contain the password."""
    u = await db.users.find_one({"id": user_id})
    if not u:
        raise HTTPException(status_code=404, detail="User not found.")
    _guard_target(admin, u, "reset the password of")
    if admin.get("role") not in ("super_admin", "admin"):      # Decision 10: support / finance roles never reset credentials
        raise HTTPException(status_code=403, detail="Only the super admin or an admin can reset a password.")
    from core import not_activated
    if not_activated(u):      # a vendor owner gets access ONLY through the owner invitation issued at final approval
        raise HTTPException(status_code=409, detail="This account is not activated yet. It is activated through the vendor owner invitation, not a password reset.")
    if u.get("account_status") == "deleted":
        raise HTTPException(status_code=409, detail="This account is deactivated. Its password cannot be reset.")
    reason = (body.reason or "").strip()
    if len(reason) < 5:
        raise HTTPException(status_code=400, detail="Give a reason for the reset (at least 5 characters).")
    temp = body.temporary_password or ""
    if len(temp) < 10 or not re.search(r"[A-Za-z]", temp) or not re.search(r"\d", temp):
        raise HTTPException(status_code=400, detail="The temporary password needs at least 10 characters with letters and numbers.")
    now = now_iso()
    # password_update stamps password_changed_at, so every session issued before now is refused (core.get_current_user).
    await db.users.update_one({"id": user_id}, {"$set": {**password_update(temp), "must_change_password": True,
                                                         "password_reset_by": admin["id"], "password_reset_at": now,
                                                         "updated_at": now}})
    await db.password_reset_requests.update_many({"user_id": user_id, "status": "pending"},
        {"$set": {"status": "resolved", "resolved_by": admin["id"], "resolved_at": now}})
    await log_audit(admin, "admin_reset_password", "user", user_id,
                    new_value={"target_role": u.get("role"), "reason": reason, "must_change_password": True,
                               "sessions_revoked": True}, request=request)
    await create_notification(user_id, "security", "Your password was reset",
                              "HOME GENIES reset your password. Sign in with the temporary password you were given; you will be asked to choose a new one.",
                              "आपका पासवर्ड रीसेट किया गया", "HOME GENIES ने आपका पासवर्ड रीसेट किया है। दिए गए अस्थायी पासवर्ड से साइन इन करें; फिर नया पासवर्ड चुनना होगा।")
    return {"ok": True, "must_change_password": True, "sessions_revoked": True,
            "message": "Temporary password set. The member must choose a new password when they next sign in. All their existing sessions were signed out.",
            "distributor_id": u.get("distributor_id"), "full_name": u.get("full_name")}


@router.get("/password-reset-requests")
async def list_password_reset_requests(admin: dict = Depends(require_admin)):
    return await db.password_reset_requests.find({"status": "pending"}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/password-reset-requests/{req_id}/dismiss")
async def dismiss_password_reset_request(req_id: str, request: Request, admin: dict = Depends(require_admin)):
    await db.password_reset_requests.update_one({"id": req_id},
        {"$set": {"status": "dismissed", "resolved_by": admin["id"], "resolved_at": now_iso()}})
    return {"ok": True}


# ---------------- Audit logs ----------------
@router.get("/audit-logs")
async def admin_audit(admin: dict = Depends(require_admin)):
    return await db.audit_logs.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.delete("/audit-logs")
async def clear_audit_logs(request: Request, admin: dict = Depends(require_admin)):
    """AUD-01: audit records are append-only. No role, including the super admin, can delete them; the attempt itself is
    recorded. (Retention or archiving, if ever needed, must be an offline, separately approved procedure.)"""
    await log_audit(admin, "audit_logs_delete_refused", "system", "audit_logs", request=request)
    raise HTTPException(status_code=405, detail="Audit records are append-only and cannot be deleted.")


# ---------------- Reports ----------------
REPORTS = {
    "registrations": ("users", {"role": {"$in": ["distributor", "customer", "vendor"]}},
                      ["distributor_id", "full_name", "email", "mobile", "status", "state", "city", "created_at"]),
    "sales": ("orders", {"payment_status": "paid"},
              ["order_number", "distributor_id", "subtotal", "gst_amount", "total", "status", "created_at"]),
    "orders": ("orders", {}, ["order_number", "distributor_id", "total", "status", "payment_status", "created_at"]),
    "payments": ("payment_transactions", {}, ["session_id", "order_id", "amount", "currency", "payment_status", "created_at"]),
    "referrals": ("referral_relationships", {},
                  ["sponsor_distributor_id", "referred_distributor_id", "commission_paid", "created_at"]),
    "commissions": ("commissions", {}, ["sponsor_distributor_id", "referred_distributor_id", "type", "amount", "status", "created_at"]),
    "wallet": ("wallet_transactions", {}, ["user_id", "type", "direction", "amount", "status", "created_at"]),
    "withdrawals": ("withdrawal_requests", {}, ["request_number", "distributor_id", "amount", "status", "created_at"]),
}


def _report_projection(fields: list) -> dict:
    """Only the report's own columns leave the database: never password hashes, Aadhaar, PAN, bank details or tokens. (W4: plus the
    exact paise field of a money column, which is converted and then dropped before the row is returned.)"""
    return {"_id": 0, **{f: 1 for f in fields}, **{REPORT_MONEY[f]: 1 for f in fields if f in REPORT_MONEY}}


# Programme 02 / W4. These are BULK listings, so contact details and payment look-up keys are masked for every role, in the screen
# and in the CSV alike (one record's full contact stays where it already is: the user / order detail for the roles that have it).
# The CSV follows the platform's one export rule (`admin_order_ops.EXPORT_ROLES`: super_admin, admin, accounts_admin; support is
# refused) - interim pending owner decision D-16 (see HOME_GENIES_OWNER_DECISION_REGISTER.md, D-16 W4 table).
REPORT_MASKS = {"email": "email", "mobile": "mobile", "session_id": "reference"}
REPORT_VIEW_ROWS = 2000        # the screen shows the newest rows; `total` and `truncated` say when there are more
REPORT_EXPORT_MAX = 5000       # larger exports are refused (narrow the dates) - never silently cut


# W4 (readiness criterion c): money columns are printed from the exact integer paise field when the document has one (legacy
# documents fall back to their rupee float through money.paise_of), always as a two-decimal string - same column names as before.
REPORT_MONEY = {"subtotal": "subtotal_paise", "gst_amount": "gst_paise", "total": "total_paise", "amount": "amount_paise"}


def _rupees(p: int) -> str:
    return f"{'-' if p < 0 else ''}{abs(p) // 100}.{abs(p) % 100:02d}"


def _mask_report_row(r: dict, fields: list = None) -> dict:
    """One row as it leaves the server (screen and CSV alike): personal fields masked, money from paise, helper keys removed."""
    from exports import mask_email, mask_mobile, mask_reference
    from money import paise_of
    fn = {"email": mask_email, "mobile": mask_mobile, "reference": mask_reference}
    out = {}
    for k, v in r.items():
        if fields is not None and k not in fields:
            continue                                     # the *_paise helper keys read below
        if k in REPORT_MASKS and v:
            out[k] = fn[REPORT_MASKS[k]](v)
        elif k in REPORT_MONEY and (v is not None or REPORT_MONEY[k] in r):
            out[k] = _rupees(paise_of(r, REPORT_MONEY[k], k))
        else:
            out[k] = v
    return out


def _report_query(report: str, date_from: Optional[str], date_to: Optional[str]):
    from exports import date_bounds
    if report not in REPORTS:
        raise HTTPException(status_code=404, detail="Report not found.")
    coll, q, fields = REPORTS[report]
    b = date_bounds(date_from, date_to)
    return coll, ({**q, "created_at": b} if b else dict(q)), fields


@router.get("/reports/{report}")
async def get_report(report: str, request: Request, date_from: Optional[str] = None, date_to: Optional[str] = None,
                     admin: dict = Depends(require_admin)):
    coll, q, fields = _report_query(report, date_from, date_to)
    total = await db[coll].count_documents(q)
    rows = await db[coll].find(q, _report_projection(fields)).sort("created_at", -1).to_list(REPORT_VIEW_ROWS)
    await log_audit(admin, "report_viewed", "report", report, new_value={"role": admin.get("role"), "rows": len(rows), "total": total,
                                                                          "date_from": date_from, "date_to": date_to}, request=request)
    return {"report": report, "fields": fields, "rows": [_mask_report_row(r, fields) for r in rows], "count": len(rows), "total": total,
            "truncated": total > len(rows), "masked": [f for f in fields if f in REPORT_MASKS]}


@router.get("/reports/{report}/export")
async def export_report(report: str, request: Request, date_from: Optional[str] = None, date_to: Optional[str] = None,
                        admin: dict = Depends(require_admin)):
    from admin_order_ops import EXPORT_ROLES
    from exports import audit_export, check_size, csv_response, csv_text, new_export_id
    eid = new_export_id()
    if admin.get("role") not in EXPORT_ROLES:
        await audit_export(admin, request, report, eid, status="refused", reason="role", date_from=date_from, date_to=date_to)
        raise HTTPException(status_code=403, detail="Your role cannot export reports.")
    coll, q, fields = _report_query(report, date_from, date_to)
    ctx = {"date_from": date_from, "date_to": date_to}
    await check_size(admin, request, report, eid, await db[coll].count_documents(q), REPORT_EXPORT_MAX, **ctx)
    try:
        rows = await db[coll].find(q, _report_projection(fields)).sort("created_at", -1).to_list(REPORT_EXPORT_MAX)
        text = csv_text(fields, ([r.get(f, "") for f in fields] for r in (_mask_report_row(x, fields) for x in rows)))
    except Exception as e:
        await audit_export(admin, request, report, eid, status="failed", reason=type(e).__name__, **ctx)
        raise HTTPException(status_code=500, detail="The export could not be created. Nothing was downloaded.")
    await audit_export(admin, request, report, eid, rows=len(rows), **ctx)
    return csv_response(text, f"{report}_report.csv", eid)
