"""Vendor portal (roadmap phase 5): onboarding, own products & stock, order fulfilment.

Every route is scoped server-side to the caller's own vendor record — a vendor can never read or
change another vendor's products, orders or customers by changing IDs (those return 404).
Admin-side approval of vendors and vendor products lives at the bottom (/api/admin/vendors...).
"""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

import re
from core import (db, now_iso, new_id, get_current_user, require_admin, create_notification, log_audit,
                  hash_password, create_token, clean_user, next_sequence)

router = APIRouter(prefix="/api", tags=["vendor"])

PILLARS = ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"]

# Allowed fulfilment transitions (server-enforced state machine).
FLOW = {
    "new": {"accepted", "rejected"},
    "accepted": {"packed", "cancelled"},
    "packed": {"dispatched", "cancelled"},
    "dispatched": {"delivered", "delivery_failed"},
    "delivery_failed": {"dispatched", "returned_to_origin"},
    "delivered": set(), "rejected": set(), "cancelled": set(), "returned_to_origin": set(),
}
RESTOCK_ON = {"rejected", "cancelled", "returned_to_origin"}
STATUS_TEXT = {
    "accepted": "accepted by the seller", "packed": "packed", "dispatched": "dispatched",
    "delivered": "delivered", "delivery_failed": "could not be delivered", "rejected": "declined by the seller",
    "cancelled": "cancelled by the seller", "returned_to_origin": "returned to the seller",
}


def _mask(v: str, keep: int = 4) -> str:
    v = str(v or "")
    return ("*" * max(len(v) - keep, 0)) + v[-keep:] if v else ""


def _public_vendor(v: dict) -> dict:
    v = {k: val for k, val in v.items() if k != "_id"}
    v["bank_account"] = _mask(v.get("bank_account"))
    v["pan"] = _mask(v.get("pan"))
    return v


async def require_vendor_user(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "vendor":
        raise HTTPException(status_code=403, detail="Vendor access only.")
    if user.get("blocked"):
        raise HTTPException(status_code=403, detail="Your account has been blocked.")
    return user


async def _vendor_of(user: dict) -> Optional[dict]:
    return await db.vendors.find_one({"user_id": user["id"]}, {"_id": 0})


async def require_approved_vendor(user: dict = Depends(require_vendor_user)) -> dict:
    v = await _vendor_of(user)
    if not v or v.get("status") != "approved":
        raise HTTPException(status_code=403, detail="Your vendor account is not approved yet.")
    return {**user, "_vendor": v}


# ------------------------------------------------------------------ public vendor sign-up
class VendorRegisterIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    full_name: str = Field(min_length=2, max_length=80)
    mobile: str
    email: str = ""
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str
    accept_terms: bool = False


@router.post("/auth/vendor-register")
async def vendor_register(body: VendorRegisterIn, request: Request):
    """Creates a vendor login + a draft vendor application. Selling still needs admin approval of the application."""
    mobile = body.mobile.strip()
    email = (body.email or "").strip().lower()
    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        raise HTTPException(status_code=400, detail="Enter a valid 10-digit Indian mobile number.")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Enter a valid email address, or leave it blank.")
    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")
    if not (re.search(r"[A-Za-z]", body.password) and re.search(r"\d", body.password)):
        raise HTTPException(status_code=400, detail="Use at least 8 characters with letters and numbers.")
    if not body.accept_terms:
        raise HTTPException(status_code=400, detail="Please accept the vendor terms.")
    if await db.users.find_one({"mobile": mobile}) or (email and await db.users.find_one({"email": email})):
        raise HTTPException(status_code=400, detail="An account with this mobile or email already exists. Please log in.")
    if await db.registration_requests.find_one({"status": "pending", "$or": [{"mobile": mobile}] + ([{"email": email}] if email else [])}):
        raise HTTPException(status_code=400, detail="This mobile or email already has a pending HomeGenie registration.")

    vid = await next_sequence("vendor", "VD", 6)
    while await db.users.find_one({"distributor_id": vid}):      # skip IDs issued before the counter existed
        vid = await next_sequence("vendor", "VD", 6)
    now = now_iso()
    user = {"id": new_id(), "distributor_id": vid, "full_name": body.full_name.strip(), "mobile": mobile,
            "email": email or None, "password_hash": hash_password(body.password), "role": "vendor", "status": "green",
            "account_status": "active", "mobile_verified": False, "email_verified": False, "kyc_status": "not_started",
            "sponsor_id": None, "sponsor_user_id": None, "created_at": now, "updated_at": now}
    try:
        await db.users.insert_one(dict(user))
    except Exception:
        raise HTTPException(status_code=400, detail="An account with this mobile or email already exists. Please log in.")
    await db.vendors.insert_one({"id": new_id(), "user_id": user["id"], "vendor_code": vid, "business_name": body.business_name.strip(),
                                 "contact_person": body.full_name.strip(), "phone": mobile, "support_email": email,
                                 "status": "draft", "categories": [], "created_at": now, "updated_at": now})
    await log_audit(user, "vendor_registered", "user", user["id"], new_value={"vendor_code": vid}, request=request)
    admins = await db.users.find({"role": "super_admin"}, {"_id": 0, "id": 1}).to_list(20)
    for a in admins:
        await create_notification(a["id"], "vendor", "New vendor sign-up", f"{body.business_name.strip()} ({vid}) created a vendor account.")
    return {"token": create_token(user["id"]), "user": clean_user(user)}


# ------------------------------------------------------------------ onboarding / profile
class VendorProfileIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=120)
    contact_person: str = Field(min_length=2, max_length=80)
    phone: str = Field(min_length=10, max_length=15)
    support_email: str = ""
    address: str = Field(min_length=5, max_length=300)
    city: str = ""
    state: str = ""
    pincode: str = ""
    return_address: str = ""
    gstin: str = ""
    pan: str = ""
    bank_account_name: str = ""
    bank_account: str = ""
    ifsc: str = ""
    categories: List[str] = []
    agree_terms: bool = False
    submit: bool = False   # False = save draft, True = submit for review


@router.get("/vendor/me")
async def vendor_me(user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    return {"vendor": _public_vendor(v) if v else None, "pillars": PILLARS}


@router.put("/vendor/me")
async def vendor_save(body: VendorProfileIn, request: Request, user: dict = Depends(require_vendor_user)):
    v = await _vendor_of(user)
    if v and v.get("status") in ("approved", "suspended"):
        # Approved/suspended vendors may update contact details only; legal/bank changes go through admin.
        allowed = {k: getattr(body, k) for k in ("contact_person", "phone", "support_email", "address", "city",
                                                  "state", "pincode", "return_address")}
        await db.vendors.update_one({"user_id": user["id"]}, {"$set": {**allowed, "updated_at": now_iso()}})
        await log_audit(user, "vendor_profile_updated", "vendor", v["id"], new_value=allowed, request=request)
        return {"vendor": _public_vendor(await _vendor_of(user))}

    bad = [c for c in body.categories if c not in PILLARS]
    if bad:
        raise HTTPException(status_code=400, detail="Choose categories from the four HOME GENIES pillars only.")
    data = body.model_dump(exclude={"submit", "agree_terms"})
    # The client only ever sees masked bank/PAN values; a blank field means "keep what is stored".
    for k in ("bank_account", "pan"):
        if not data[k].strip() and v and v.get(k):
            data[k] = v[k]
    status = "draft"
    if body.submit:
        if not body.agree_terms:
            raise HTTPException(status_code=400, detail="Please accept the vendor terms to submit.")
        if not body.categories:
            raise HTTPException(status_code=400, detail="Select at least one product category.")
        if not (data["bank_account"] and body.ifsc and body.bank_account_name):
            raise HTTPException(status_code=400, detail="Bank details are required for settlements.")
        status = "submitted"
    if v and v.get("status") == "rejected" and not body.submit:
        status = "rejected"
    now = now_iso()
    doc = {**data, "status": status, "updated_at": now}
    if body.submit:
        doc.update({"submitted_at": now, "terms_accepted_at": now, "rejection_reason": ""})
    if v:
        await db.vendors.update_one({"user_id": user["id"]}, {"$set": doc})
    else:
        await db.vendors.insert_one({"id": new_id(), "user_id": user["id"], "vendor_code": user.get("distributor_id"),
                                     "created_at": now, **doc})
    await log_audit(user, "vendor_submitted" if body.submit else "vendor_draft_saved", "vendor",
                    (v or {}).get("id", user["id"]), request=request)
    return {"vendor": _public_vendor(await _vendor_of(user))}


# ------------------------------------------------------------------ products (own only)
class VendorProductIn(BaseModel):
    sku: str = Field(min_length=2, max_length=40)
    name: str = Field(min_length=2, max_length=140)
    name_hi: str = ""
    description: str = ""
    description_hi: str = ""
    images: List[str] = []
    mrp: float = Field(gt=0)
    selling_price: float = Field(gt=0)
    gst_percent: float = Field(default=5.0, ge=0, le=28)
    stock: int = Field(default=0, ge=0)
    category: str
    options: List[dict] = []
    return_policy: str = ""


REVIEW_FIELDS = ("name", "name_hi", "description", "description_hi", "images", "mrp", "selling_price",
                 "gst_percent", "category", "options", "return_policy")


@router.get("/vendor/products")
async def vendor_products(user: dict = Depends(require_approved_vendor)):
    return await db.products.find({"vendor_id": user["_vendor"]["id"]}, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/vendor/products")
async def vendor_create_product(body: VendorProductIn, request: Request, user: dict = Depends(require_approved_vendor)):
    v = user["_vendor"]
    if body.category not in PILLARS:
        raise HTTPException(status_code=400, detail="Category must be one of the four HOME GENIES pillars.")
    if body.selling_price > body.mrp:
        raise HTTPException(status_code=400, detail="Selling price cannot be higher than MRP.")
    sku = body.sku.strip().upper()
    if await db.products.find_one({"sku": sku}):
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    p = {**body.model_dump(), "sku": sku, "id": new_id(), "vendor_id": v["id"], "vendor_name": v["business_name"],
         "is_active": False, "approval_status": "pending", "rejection_reason": "",
         "created_at": now_iso(), "updated_at": now_iso()}
    await db.products.insert_one(dict(p))
    if body.stock:
        await db.stock_movements.insert_one({"id": new_id(), "product_id": p["id"], "delta": body.stock,
                                             "reason": "initial_stock", "actor_id": user["id"], "created_at": now_iso()})
    await log_audit(user, "vendor_product_submitted", "product", p["id"], new_value={"sku": sku}, request=request)
    p.pop("_id", None)
    return p


async def _own_product(user: dict, product_id: str) -> dict:
    p = await db.products.find_one({"id": product_id, "vendor_id": user["_vendor"]["id"]}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    return p


@router.put("/vendor/products/{product_id}")
async def vendor_update_product(product_id: str, body: VendorProductIn, request: Request,
                                user: dict = Depends(require_approved_vendor)):
    p = await _own_product(user, product_id)
    if body.category not in PILLARS:
        raise HTTPException(status_code=400, detail="Category must be one of the four HOME GENIES pillars.")
    if body.selling_price > body.mrp:
        raise HTTPException(status_code=400, detail="Selling price cannot be higher than MRP.")
    new = body.model_dump(exclude={"sku", "stock"})  # SKU is fixed; stock changes go through /stock
    upd = {**new, "updated_at": now_iso()}
    # Material changes (price, claims, category, images…) go back to review and are hidden until approved.
    if any(p.get(k) != new.get(k) for k in REVIEW_FIELDS):
        upd.update({"approval_status": "pending", "is_active": False, "rejection_reason": ""})
    await db.products.update_one({"id": product_id}, {"$set": upd})
    await log_audit(user, "vendor_product_updated", "product", product_id,
                    old_value={k: p.get(k) for k in REVIEW_FIELDS}, new_value={k: new.get(k) for k in REVIEW_FIELDS},
                    request=request)
    return await _own_product(user, product_id)


class StockIn(BaseModel):
    delta: int
    reason: str = Field(min_length=3, max_length=120)


@router.post("/vendor/products/{product_id}/stock")
async def vendor_adjust_stock(product_id: str, body: StockIn, request: Request, user: dict = Depends(require_approved_vendor)):
    p = await _own_product(user, product_id)
    if body.delta == 0:
        raise HTTPException(status_code=400, detail="Enter a quantity to add or remove.")
    res = await db.products.update_one({"id": product_id, "stock": {"$gte": -body.delta}}, {"$inc": {"stock": body.delta}})
    if res.modified_count != 1:
        raise HTTPException(status_code=400, detail="Stock cannot go below zero.")
    after = (p.get("stock") or 0) + body.delta
    await db.stock_movements.insert_one({"id": new_id(), "product_id": product_id, "delta": body.delta,
                                         "before": p.get("stock") or 0, "after": after, "reason": body.reason,
                                         "actor_id": user["id"], "created_at": now_iso()})
    await log_audit(user, "vendor_stock_adjusted", "product", product_id, new_value={"delta": body.delta, "reason": body.reason}, request=request)
    return await _own_product(user, product_id)


@router.get("/vendor/products/{product_id}/stock-history")
async def vendor_stock_history(product_id: str, user: dict = Depends(require_approved_vendor)):
    await _own_product(user, product_id)
    return await db.stock_movements.find({"product_id": product_id}, {"_id": 0}).sort("created_at", -1).to_list(100)


class ListingIn(BaseModel):
    active: bool


@router.post("/vendor/products/{product_id}/listing")
async def vendor_toggle_listing(product_id: str, body: ListingIn, request: Request, user: dict = Depends(require_approved_vendor)):
    p = await _own_product(user, product_id)
    if body.active and p.get("approval_status") != "approved":
        raise HTTPException(status_code=400, detail="This product must be approved before it can be listed.")
    await db.products.update_one({"id": product_id}, {"$set": {"is_active": body.active, "updated_at": now_iso()}})
    await log_audit(user, "vendor_listing_" + ("resumed" if body.active else "paused"), "product", product_id, request=request)
    return await _own_product(user, product_id)


# ------------------------------------------------------------------ orders (own lines only)
def _vendor_view(order: dict, vendor_id: str) -> Optional[dict]:
    """Only this vendor's lines + what it needs to ship. No other vendor's items, payment refs or HomeGenie data."""
    f = next((x for x in order.get("fulfilments") or [] if x["vendor_id"] == vendor_id), None)
    if not f:
        return None
    lines = [li for li in order.get("items", []) if li.get("vendor_id") == vendor_id]
    a = order.get("address") or {}
    return {
        "id": order["id"], "order_number": order.get("order_number"), "created_at": order.get("created_at"),
        "payment_method": order.get("payment_method"), "payment_status": order.get("payment_status"),
        "order_status": order.get("status"),
        "items": lines, "items_total": round(sum(li.get("total", 0) for li in lines), 2),
        "ship_to": {k: a.get(k, "") for k in ("full_name", "mobile", "line1", "city", "state", "pincode")},
        "fulfilment": f,
    }


@router.get("/vendor/orders")
async def vendor_orders(status: Optional[str] = None, user: dict = Depends(require_approved_vendor)):
    vid = user["_vendor"]["id"]
    q = {"fulfilments.vendor_id": vid, "payment_status": {"$nin": ["pending", "failed"]}}
    orders = await db.orders.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    out = [v for v in (_vendor_view(o, vid) for o in orders) if v]
    if status:
        out = [o for o in out if o["fulfilment"]["status"] == status]
    return out


@router.get("/vendor/orders/{order_id}")
async def vendor_order(order_id: str, user: dict = Depends(require_approved_vendor)):
    o = await db.orders.find_one({"id": order_id, "fulfilments.vendor_id": user["_vendor"]["id"]}, {"_id": 0})
    view = _vendor_view(o, user["_vendor"]["id"]) if o else None
    if not view:
        raise HTTPException(status_code=404, detail="Order not found.")
    return view


class FulfilIn(BaseModel):
    status: str
    note: str = ""
    carrier: str = ""
    tracking_number: str = ""
    tracking_url: str = ""


@router.post("/vendor/orders/{order_id}/fulfilment")
async def vendor_update_fulfilment(order_id: str, body: FulfilIn, request: Request, user: dict = Depends(require_approved_vendor)):
    vid = user["_vendor"]["id"]
    o = await db.orders.find_one({"id": order_id, "fulfilments.vendor_id": vid}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found.")
    f = next(x for x in o["fulfilments"] if x["vendor_id"] == vid)
    cur, nxt = f["status"], body.status
    if nxt not in FLOW.get(cur, set()):
        raise HTTPException(status_code=400, detail=f"Cannot move this order from '{cur}' to '{nxt}'.")
    if nxt in ("rejected", "cancelled", "delivery_failed") and len(body.note.strip()) < 5:
        raise HTTPException(status_code=400, detail="Please give a reason (at least 5 characters).")
    if nxt == "dispatched" and not (body.carrier.strip() and body.tracking_number.strip()):
        raise HTTPException(status_code=400, detail="Carrier and tracking number are required to dispatch.")
    if nxt == "delivered" and len(body.note.strip()) < 3:
        raise HTTPException(status_code=400, detail="Add delivery evidence (e.g. recipient name / OTP / courier proof).")

    event = {"status": nxt, "at": now_iso(), "by": user["id"], "note": body.note.strip()}
    sets = {"fulfilments.$.status": nxt, "updated_at": now_iso()}
    if nxt == "dispatched":
        sets.update({"fulfilments.$.carrier": body.carrier.strip(), "fulfilments.$.tracking_number": body.tracking_number.strip(),
                     "fulfilments.$.tracking_url": body.tracking_url.strip()})
    # Conditional on the current status, so double-clicks/races cannot apply a transition twice.
    res = await db.orders.update_one({"id": order_id, "fulfilments": {"$elemMatch": {"vendor_id": vid, "status": cur}}},
                                     {"$set": sets, "$push": {"fulfilments.$.events": event}})
    if res.modified_count != 1:
        raise HTTPException(status_code=409, detail="This order was just updated. Please refresh.")

    if nxt in RESTOCK_ON and o.get("stock_reserved"):
        for li in o.get("items", []):
            if li.get("vendor_id") == vid:
                await db.products.update_one({"id": li["product_id"]}, {"$inc": {"stock": li["quantity"]}})
                await db.stock_movements.insert_one({"id": new_id(), "product_id": li["product_id"], "delta": li["quantity"],
                                                     "reason": f"order_{nxt}", "order_id": order_id, "actor_id": user["id"],
                                                     "created_at": now_iso()})

    # Roll the overall order status forward when every vendor group has delivered.
    fresh = await db.orders.find_one({"id": order_id}, {"_id": 0, "fulfilments": 1})
    states = [x["status"] for x in fresh.get("fulfilments", [])]
    if states and all(s == "delivered" for s in states):
        await db.orders.update_one({"id": order_id}, {"$set": {"status": "delivered", "delivered_at": now_iso()}})
    elif nxt == "dispatched":
        await db.orders.update_one({"id": order_id, "status": {"$nin": ["delivered", "cancelled", "refunded"]}}, {"$set": {"status": "shipped"}})

    msg = f"Your order {o.get('order_number')} from {f.get('vendor_name') or 'the seller'} was {STATUS_TEXT.get(nxt, nxt)}."
    if nxt == "dispatched":
        msg += f" {body.carrier.strip()} tracking: {body.tracking_number.strip()}."
    await create_notification(o["user_id"], "order", "Order update", msg, meta={"order_id": order_id})
    await log_audit(user, f"fulfilment_{nxt}", "order", order_id, old_value={"status": cur}, new_value=event, request=request)
    return await vendor_order(order_id, user)


# ------------------------------------------------------------------ dashboard
@router.get("/vendor/dashboard")
async def vendor_dashboard(user: dict = Depends(require_approved_vendor)):
    v = user["_vendor"]
    orders = await vendor_orders(None, user)
    by = {}
    for o in orders:
        by[o["fulfilment"]["status"]] = by.get(o["fulfilment"]["status"], 0) + 1
    products = await db.products.find({"vendor_id": v["id"]}, {"_id": 0, "stock": 1, "approval_status": 1, "is_active": 1}).to_list(1000)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    delivered = [o for o in orders if o["fulfilment"]["status"] == "delivered"]
    return {
        "vendor": _public_vendor(v),
        "queue": {"new": by.get("new", 0), "to_pack": by.get("accepted", 0), "to_dispatch": by.get("packed", 0),
                  "in_transit": by.get("dispatched", 0), "exceptions": by.get("delivery_failed", 0)},
        "products": {"total": len(products), "live": sum(1 for p in products if p.get("is_active") and p.get("approval_status") == "approved"),
                     "pending_review": sum(1 for p in products if p.get("approval_status") == "pending"),
                     "rejected": sum(1 for p in products if p.get("approval_status") == "rejected"),
                     "low_stock": sum(1 for p in products if (p.get("stock") or 0) <= 5)},
        "sales": {"orders": len(orders), "delivered": len(delivered),
                  "gross_this_month": round(sum(o["items_total"] for o in orders if (o.get("created_at") or "").startswith(month)
                                                and o["fulfilment"]["status"] not in ("rejected", "cancelled")), 2)},
        "recent": orders[:5],
    }


# ------------------------------------------------------------------ admin: vendor + product approval
@router.get("/admin/vendors")
async def admin_vendors(admin: dict = Depends(require_admin)):
    vs = await db.vendors.find({}, {"_id": 0}).sort("updated_at", -1).to_list(500)
    users = {u["id"]: u for u in await db.users.find({"id": {"$in": [v["user_id"] for v in vs]}},
                                                     {"_id": 0, "id": 1, "email": 1, "mobile": 1, "distributor_id": 1}).to_list(500)}
    out = []
    for v in vs:
        pv = _public_vendor(v)
        pv["account"] = users.get(v["user_id"], {})
        pv["product_count"] = await db.products.count_documents({"vendor_id": v["id"]})
        out.append(pv)
    return out


class VendorDecision(BaseModel):
    action: str          # approve / reject / suspend / reinstate
    reason: str = ""


@router.post("/admin/vendors/{vendor_id}/decision")
async def admin_vendor_decision(vendor_id: str, body: VendorDecision, request: Request, admin: dict = Depends(require_admin)):
    v = await db.vendors.find_one({"id": vendor_id}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    allowed = {"approve": ({"submitted", "rejected"}, "approved"), "reject": ({"submitted"}, "rejected"),
               "suspend": ({"approved"}, "suspended"), "reinstate": ({"suspended"}, "approved")}
    if body.action not in allowed:
        raise HTTPException(status_code=400, detail="Unknown action.")
    frm, to = allowed[body.action]
    if v["status"] not in frm:
        raise HTTPException(status_code=400, detail=f"Cannot {body.action} a vendor that is '{v['status']}'.")
    if body.action in ("reject", "suspend") and len(body.reason.strip()) < 5:
        raise HTTPException(status_code=400, detail="A reason is required.")
    await db.vendors.update_one({"id": vendor_id, "status": v["status"]},
                                {"$set": {"status": to, "rejection_reason": body.reason.strip() if body.action == "reject" else v.get("rejection_reason", ""),
                                          "status_reason": body.reason.strip(), "reviewed_by": admin["id"],
                                          "reviewed_at": now_iso(), "updated_at": now_iso()}})
    if to == "suspended":   # hide all listings; history stays intact
        await db.products.update_many({"vendor_id": vendor_id}, {"$set": {"is_active": False}})
    await create_notification(v["user_id"], "vendor", "Vendor account update",
                              f"Your vendor account is now {to}." + (f" Reason: {body.reason.strip()}" if body.reason.strip() else ""))
    await log_audit(admin, f"vendor_{body.action}", "vendor", vendor_id, old_value={"status": v["status"]},
                    new_value={"status": to, "reason": body.reason}, request=request)
    return _public_vendor(await db.vendors.find_one({"id": vendor_id}, {"_id": 0}))


@router.get("/admin/vendor-products")
async def admin_vendor_products(status: str = "pending", admin: dict = Depends(require_admin)):
    q = {"vendor_id": {"$ne": None}}
    if status != "all":
        q["approval_status"] = status
    return await db.products.find(q, {"_id": 0}).sort("updated_at", -1).to_list(500)


class ProductDecision(BaseModel):
    action: str          # approve / reject
    reason: str = ""


@router.post("/admin/vendor-products/{product_id}/decision")
async def admin_product_decision(product_id: str, body: ProductDecision, request: Request, admin: dict = Depends(require_admin)):
    p = await db.products.find_one({"id": product_id, "vendor_id": {"$ne": None}}, {"_id": 0})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    if p.get("approval_status") != "pending":
        raise HTTPException(status_code=400, detail="Only products awaiting review can be decided.")
    if body.action == "approve":
        v = await db.vendors.find_one({"id": p["vendor_id"]}, {"_id": 0, "status": 1, "user_id": 1})
        sets = {"approval_status": "approved", "is_active": (v or {}).get("status") == "approved", "rejection_reason": ""}
    elif body.action == "reject":
        if len(body.reason.strip()) < 5:
            raise HTTPException(status_code=400, detail="A reason is required.")
        sets = {"approval_status": "rejected", "is_active": False, "rejection_reason": body.reason.strip()}
    else:
        raise HTTPException(status_code=400, detail="Unknown action.")
    sets.update({"reviewed_by": admin["id"], "reviewed_at": now_iso(), "updated_at": now_iso()})
    await db.products.update_one({"id": product_id, "approval_status": "pending"}, {"$set": sets})
    v = await db.vendors.find_one({"id": p["vendor_id"]}, {"_id": 0, "user_id": 1})
    if v:
        await create_notification(v["user_id"], "vendor", "Product review",
                                  f"{p['name']} was {sets['approval_status']}." + (f" Reason: {body.reason.strip()}" if body.action == "reject" else ""))
    await log_audit(admin, f"product_{sets['approval_status']}", "product", product_id, new_value={"reason": body.reason}, request=request)
    return await db.products.find_one({"id": product_id}, {"_id": 0})


class VendorInvite(BaseModel):
    identifier: str = Field(min_length=3)   # email, mobile or HomeGenie ID of an existing account


@router.post("/admin/vendors/invite")
async def admin_vendor_invite(body: VendorInvite, request: Request, admin: dict = Depends(require_admin)):
    ident = body.identifier.strip()
    u = await db.users.find_one({"$or": [{"email": ident.lower()}, {"mobile": ident}, {"distributor_id": ident.upper()}]}, {"_id": 0})
    if not u:
        raise HTTPException(status_code=404, detail="No account found. The person must register first.")
    if u.get("role") in ("super_admin", "admin", "accounts_admin", "support_admin"):
        raise HTTPException(status_code=400, detail="Admin accounts cannot be vendors.")
    if u.get("role") == "vendor":
        raise HTTPException(status_code=400, detail="This account is already a vendor.")
    await db.users.update_one({"id": u["id"]}, {"$set": {"role": "vendor", "status": "green", "updated_at": now_iso()}})
    await create_notification(u["id"], "vendor", "Vendor access enabled",
                              "You can now complete your vendor application in the Vendor portal.")
    await log_audit(admin, "vendor_role_granted", "user", u["id"], old_value={"role": u.get("role")}, new_value={"role": "vendor"}, request=request)
    return {"ok": True, "user_id": u["id"], "distributor_id": u.get("distributor_id")}
