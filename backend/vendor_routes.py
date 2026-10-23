"""Vendor portal (roadmap phase 5): onboarding, own products & stock, order fulfilment.

Every route is scoped server-side to the caller's own vendor record — a vendor can never read or
change another vendor's products, orders or customers by changing IDs (those return 404).
Admin-side approval of vendors and vendor products lives at the bottom (/api/admin/vendors...).
"""
from datetime import datetime, timezone
from typing import List, Optional

from pymongo.errors import DuplicateKeyError
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field, field_validator

import re
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta
from money import paise_of
from pagination import clamp_page, page_meta, text_filter, date_range
from stock import release_stock, run_intents, intent
from validators import safe_image_refs
from vendor_history import record_vendor_status, missing_required_documents
import catalogue as cat
from fastapi.responses import Response
from core import (db, now_iso, new_id, get_current_user, require_admin, create_notification, log_audit,
                  hash_password, create_token, clean_user, next_sequence, P_PUBLIC)

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
# Stock returns automatically only when the goods never left (reject / pre-dispatch cancel). Goods that come BACK
# (returned_to_origin) are restocked only after the vendor records receipt + inspection (see return-inspection).
RESTOCK_ON = {"rejected", "cancelled"}
LOW_STOCK = 5
STATUS_TEXT = {
    "accepted": "accepted by the seller", "packed": "packed", "dispatched": "dispatched",
    "delivered": "delivered", "delivery_failed": "could not be delivered", "rejected": "declined by the seller",
    "cancelled": "cancelled by the seller", "returned_to_origin": "returned to the seller",
}


def _mask(v: str, keep: int = 4) -> str:
    v = str(v or "")
    return ("*" * max(len(v) - keep, 0)) + v[-keep:] if v else ""


def _public_vendor(v: dict) -> dict:
    v = {k: val for k, val in v.items() if k not in ("_id", "reviewed_by")}
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
    from core import rate_limit, client_ip
    await rate_limit("vendor_register", client_ip(request))
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
    vrec = {"id": new_id(), "user_id": user["id"], "vendor_code": vid, "business_name": body.business_name.strip(),
            "contact_person": body.full_name.strip(), "phone": mobile, "support_email": email,
            "status": "draft", "categories": [], "created_at": now, "updated_at": now}
    await db.vendors.insert_one(dict(vrec))
    await record_vendor_status(vrec["id"], None, "draft", user["id"], "Vendor account created")
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
    if v and v.get("status") in ("submitted", "under_review"):
        raise HTTPException(status_code=409, detail="Your application is with the HOME GENIES team. You can edit it again if changes are requested.")
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
        if v:
            missing = await missing_required_documents(v["id"])
            if missing:
                raise HTTPException(status_code=400, detail="Please upload the required document(s) first: " + ", ".join(missing) + ".")
        status = "submitted"
    if v and v.get("status") == "rejected" and not body.submit:
        status = "rejected"
    now = now_iso()
    doc = {**data, "status": status, "updated_at": now}
    if body.submit:
        import governance_routes as _g
        doc.update({"submitted_at": now, "terms_accepted_at": now, "terms_version": _g.TERMS_VERSION, "rejection_reason": ""})
    if v:
        await db.vendors.update_one({"user_id": user["id"]}, {"$set": doc})
    else:
        await db.vendors.insert_one({"id": new_id(), "user_id": user["id"], "vendor_code": user.get("distributor_id"),
                                     "created_at": now, **doc})
    if body.submit:
        await record_vendor_status((v or {}).get("id", user["id"]), (v or {}).get("status", "draft"), "submitted", user["id"],
                                   "Resubmitted after changes" if v and v.get("status") == "rejected" else "Submitted for review")
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
    short_description: str = Field(default="", max_length=200)
    images: List[str] = []
    mrp: float = Field(gt=0)
    selling_price: float = Field(gt=0)
    gst_percent: float = Field(default=5.0, ge=0, le=28)
    hsn_code: str = Field(default="", max_length=10)
    stock: int = Field(default=0, ge=0)
    low_stock_threshold: int = Field(default=5, ge=0, le=100000)
    category: str
    subcategory: str = Field(default="", max_length=60)
    brand: str = Field(default="", max_length=60)
    keywords: List[str] = Field(default=[], max_length=10)
    options: List[dict] = []
    attributes: dict = {}                 # validated per pillar (see catalogue.ATTRIBUTE_SPECS)
    package: dict = {}                    # weight / dimensions / handling / fragile
    variants: List[dict] = []             # each with its own SKU, optional price, own stock
    compliance_documents: List[dict] = []
    declarations: List[str] = Field(default=[], max_length=10)
    returnable: bool = True
    return_policy: str = ""

    @field_validator("images")
    @classmethod
    def _safe_images(cls, v: List[str]) -> List[str]:
        return safe_image_refs(v, 8)


# Material changes send an approved product back to admin review and hide it until approved.
REVIEW_FIELDS = ("name", "name_hi", "description", "description_hi", "short_description", "images", "mrp", "selling_price",
                 "gst_percent", "hsn_code", "category", "subcategory", "brand", "options", "attributes", "compliance_documents",
                 "declarations", "returnable", "return_policy")


def _variant_identity(variants: list) -> list:
    """The reviewable part of variants (everything except live stock)."""
    return sorted(({k: v for k, v in x.items() if k != "stock"} for x in variants or []), key=lambda x: x["sku"])


def _clean_product_payload(body: VendorProductIn, existing_variants: Optional[list] = None, vendor_id: Optional[str] = None) -> dict:
    """Server-side validation of the catalogue fields. Raises HTTPException(400/422) with a readable message."""
    if body.category not in PILLARS:
        raise HTTPException(status_code=400, detail="Category must be one of the four HOME GENIES pillars.")
    if body.selling_price > body.mrp:
        raise HTTPException(status_code=400, detail="Selling price cannot be higher than MRP.")
    data = body.model_dump()
    try:
        data["attributes"] = cat.validate_attributes(body.category, body.attributes)
        data["package"] = cat.validate_package(body.package)
        data["variants"] = cat.validate_variants(body.variants, body.sku.strip(), existing_variants)
        data["compliance_documents"] = cat.validate_documents(body.compliance_documents)
        if vendor_id:
            import governance_routes as _g
            _g.validate_image_ownership(body.images, vendor_id)
        data["keywords"] = [k.strip()[:30] for k in body.keywords if k.strip()]
        data["declarations"] = [d.strip()[:200] for d in body.declarations if d.strip()]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    for pk in ("price", "mrp"):
        pass
    if data["variants"]:
        data["stock"] = sum(v["stock"] for v in data["variants"])      # product stock is the sum of its variants
    return data


SORTS = {"updated": "updated_at", "created": "created_at", "name": "name", "price": "selling_price", "stock": "stock"}


@router.get("/vendor/products")
async def vendor_products(q: Optional[str] = None, approval: Optional[str] = None, stock: Optional[str] = None,
                          category: Optional[str] = None, archived: Optional[bool] = None, sort: Optional[str] = None,
                          order: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None,
                          user: dict = Depends(require_approved_vendor)):
    """Own products. No query parameters = the original plain list (up to 500, archived hidden). With `page` (or any filter) the
    reply is {items, total, page, page_size, pages, counts}. Filters: q (name / SKU / variant SKU), approval, stock (low|out),
    category (one of the four pillars), archived. Sorting: sort=updated|created|name|price|stock, order=asc|desc."""
    vid = user["_vendor"]["id"]
    base = {"vendor_id": vid}
    live = {**base, "archived": {"$ne": True}}
    if page is None and not (q or approval or stock or category or archived is not None or sort):
        return await db.products.find(live, P_PUBLIC).sort("created_at", -1).to_list(500)
    if approval and approval not in ("pending", "approved", "rejected"):
        raise HTTPException(status_code=400, detail="approval must be pending, approved or rejected.")
    if stock and stock not in ("low", "out"):
        raise HTTPException(status_code=400, detail="stock must be low or out.")
    if category and category not in PILLARS:
        raise HTTPException(status_code=400, detail="category must be one of the four pillars.")
    if sort and sort not in SORTS:
        raise HTTPException(status_code=400, detail="sort must be one of: " + ", ".join(SORTS))
    if order and order not in ("asc", "desc"):
        raise HTTPException(status_code=400, detail="order must be asc or desc.")
    query = dict(live) if not archived else dict(base, archived=True)
    if approval:
        query["approval_status"] = approval
    if category:
        query["category"] = category
    if stock == "out":
        query["stock"] = {"$lte": 0}
    elif stock == "low":
        query["$expr"] = {"$and": [{"$gt": ["$stock", 0]}, {"$lte": ["$stock", {"$ifNull": ["$low_stock_threshold", LOW_STOCK]}]}]}
    tf = text_filter(q)
    if tf:
        query["$or"] = [{"name": tf}, {"sku": tf}, {"name_hi": tf}, {"variants.sku": tf}, {"brand": tf}]
    page, page_size = clamp_page(page, page_size)
    total = await db.products.count_documents(query)
    direction = 1 if order == "asc" else -1
    items = await db.products.find(query, P_PUBLIC).sort([(SORTS.get(sort or "created", "created_at"), direction), ("id", 1)]) \
        .skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    low_expr = {"$expr": {"$and": [{"$gt": ["$stock", 0]}, {"$lte": ["$stock", {"$ifNull": ["$low_stock_threshold", LOW_STOCK]}]}]}}
    counts = {"all": await db.products.count_documents(live),
              "pending": await db.products.count_documents({**live, "approval_status": "pending"}),
              "approved": await db.products.count_documents({**live, "approval_status": "approved"}),
              "rejected": await db.products.count_documents({**live, "approval_status": "rejected"}),
              "low": await db.products.count_documents({**live, **low_expr}),
              "out": await db.products.count_documents({**live, "stock": {"$lte": 0}}),
              "archived": await db.products.count_documents({**base, "archived": True})}
    return {"items": items, **page_meta(total, page, page_size), "counts": counts}


@router.get("/vendor/catalogue/spec")
async def catalogue_spec(user: dict = Depends(require_vendor_user)):
    """Single source of truth for the product form: pillars, per-pillar attribute fields, variant attributes, document types."""
    return {"pillars": cat.PILLARS,
            "attributes": {p: [{"key": k, "type": spec[0], "max": spec[1]} for k, spec in fields.items()] for p, fields in cat.ATTRIBUTE_SPECS.items()},
            "variant_attributes": sorted(cat.VARIANT_ATTRIBUTES), "document_types": sorted(cat.DOC_TYPES)}


@router.post("/vendor/products")
async def vendor_create_product(body: VendorProductIn, request: Request, user: dict = Depends(require_approved_vendor)):
    v = user["_vendor"]
    data = _clean_product_payload(body, None, v["id"])
    sku = body.sku.strip().upper()
    all_skus = [sku] + [x["sku"] for x in data["variants"]]
    if await db.products.find_one({"$or": [{"sku": {"$in": all_skus}}, {"variants.sku": {"$in": all_skus}}]}):
        raise HTTPException(status_code=400, detail="A product or variant with this SKU already exists.")
    p = {**data, "sku": sku, "id": new_id(), "vendor_id": v["id"], "vendor_name": v["business_name"],
         "is_active": False, "approval_status": "pending", "rejection_reason": "", "archived": False,
         "created_at": now_iso(), "updated_at": now_iso()}
    try:
        await db.products.insert_one(dict(p))
    except DuplicateKeyError:   # two simultaneous submits of the same SKU: unique index decides
        raise HTTPException(status_code=400, detail="A product with this SKU already exists.")
    initial = [(x["sku"], x["stock"]) for x in data["variants"]] if data["variants"] else [(None, body.stock)]
    for vsku, qty in initial:
        if qty:
            await db.stock_movements.insert_one({"id": new_id(), "product_id": p["id"], "variant_sku": vsku, "delta": qty,
                                                 "reason": "initial_stock", "actor_id": user["id"], "created_at": now_iso()})
    await log_audit(user, "vendor_product_submitted", "product", p["id"], new_value={"sku": sku}, request=request)
    p.pop("_id", None)
    return p


async def _own_product(user: dict, product_id: str) -> dict:
    p = await db.products.find_one({"id": product_id, "vendor_id": user["_vendor"]["id"]}, P_PUBLIC)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    return p


@router.put("/vendor/products/{product_id}")
async def vendor_update_product(product_id: str, body: VendorProductIn, request: Request,
                                user: dict = Depends(require_approved_vendor)):
    p = await _own_product(user, product_id)
    if p.get("archived"):
        raise HTTPException(status_code=409, detail="Restore this product from the archive before editing it.")
    data = _clean_product_payload(body, p.get("variants"), user["_vendor"]["id"])
    new_skus = [x["sku"] for x in data["variants"] if x["sku"] not in {y["sku"] for y in p.get("variants") or []}]
    if new_skus and await db.products.find_one({"id": {"$ne": product_id}, "$or": [{"sku": {"$in": new_skus}}, {"variants.sku": {"$in": new_skus}}]}):
        raise HTTPException(status_code=400, detail="A variant SKU already exists on another product.")
    new = {k: v for k, v in data.items() if k not in ("sku", "stock")}    # SKU is fixed; stock changes go through /stock
    if not data["variants"] and p.get("variants"):
        raise HTTPException(status_code=400, detail="A product that has variants cannot go back to a single stock number.")
    changed = [k for k in REVIEW_FIELDS if p.get(k) != new.get(k)] + (["variants"] if _variant_identity(p.get("variants")) != _variant_identity(data["variants"]) else [])
    upd = {**new, "updated_at": now_iso()}
    if data["variants"]:
        upd["stock"] = data["stock"]
    if changed:   # material change: back to review, hidden until approved
        upd.update({"approval_status": "pending", "is_active": False, "rejection_reason": ""})
    await db.products.update_one({"id": product_id}, {"$set": upd})
    for x in data["variants"]:       # brand-new variants record their opening stock
        if x["sku"] in new_skus and x["stock"]:
            await db.stock_movements.insert_one({"id": new_id(), "product_id": product_id, "variant_sku": x["sku"], "delta": x["stock"],
                                                 "reason": "initial_stock", "actor_id": user["id"], "created_at": now_iso()})
    await log_audit(user, "vendor_product_updated", "product", product_id,
                    old_value={k: p.get(k) for k in changed if k in p}, new_value={"changed": changed}, request=request)
    return await _own_product(user, product_id)


class StockIn(BaseModel):
    delta: int
    reason: str = Field(min_length=3, max_length=120)
    variant_sku: Optional[str] = None


@router.post("/vendor/products/{product_id}/stock")
async def vendor_adjust_stock(product_id: str, body: StockIn, request: Request, user: dict = Depends(require_approved_vendor)):
    p = await _own_product(user, product_id)
    if body.delta == 0:
        raise HTTPException(status_code=400, detail="Enter a quantity to add or remove.")
    if p.get("variants"):
        if not body.variant_sku:
            raise HTTPException(status_code=400, detail="Choose which variant to adjust.")
        vs = body.variant_sku.strip().upper()
        flt = {"id": product_id, "variants": {"$elemMatch": {"sku": vs, "stock": {"$gte": -body.delta}}}}
        res = await db.products.update_one(flt, {"$inc": {"variants.$.stock": body.delta, "stock": body.delta}, "$set": {"updated_at": now_iso()}})
        before = next((x["stock"] for x in p["variants"] if x["sku"] == vs), None)
        if before is None:
            raise HTTPException(status_code=404, detail="Variant not found.")
    else:
        vs = None
        res = await db.products.update_one({"id": product_id, "stock": {"$gte": -body.delta}}, {"$inc": {"stock": body.delta}})
        before = p.get("stock") or 0
    if res.modified_count != 1:
        raise HTTPException(status_code=400, detail="Stock cannot go below zero.")
    await db.stock_movements.insert_one({"id": new_id(), "product_id": product_id, "variant_sku": vs, "delta": body.delta,
                                         "before": before, "after": before + body.delta, "reason": body.reason,
                                         "actor_id": user["id"], "created_at": now_iso()})
    await log_audit(user, "vendor_stock_adjusted", "product", product_id,
                    new_value={"delta": body.delta, "reason": body.reason, "variant": vs}, request=request)
    return await _own_product(user, product_id)


class ArchiveIn(BaseModel):
    archived: bool


@router.post("/vendor/products/{product_id}/archive")
async def vendor_archive(product_id: str, body: ArchiveIn, request: Request, user: dict = Depends(require_approved_vendor)):
    """Archiving hides a product from the shop and the default list; history is kept. Restoring leaves it paused."""
    p = await _own_product(user, product_id)
    if bool(p.get("archived")) == body.archived:
        return p
    await db.products.update_one({"id": product_id}, {"$set": {"archived": body.archived, "is_active": False, "updated_at": now_iso()}})
    await log_audit(user, "vendor_product_" + ("archived" if body.archived else "restored"), "product", product_id, request=request)
    return await _own_product(user, product_id)


# ---------------- CSV import / export (own catalogue only)
@router.get("/vendor/products/export.csv")
async def vendor_export_products(user: dict = Depends(require_approved_vendor)):
    rows = await db.products.find({"vendor_id": user["_vendor"]["id"]}, P_PUBLIC).sort("created_at", 1).to_list(5000)
    return Response(cat.products_to_csv(rows), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=my-products.csv"})


@router.get("/vendor/products/import-template.csv")
async def vendor_import_template(mode: str = "products", user: dict = Depends(require_approved_vendor)):
    if mode not in ("products", "stock"):
        raise HTTPException(status_code=400, detail="mode must be products or stock.")
    return Response(cat.template_csv(mode), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=import-{mode}.csv"})


class ImportIn(BaseModel):
    mode: str = "products"                # products | stock
    csv: str = Field(max_length=1_000_000)
    commit: bool = False                  # False = validate only (preview)


@router.post("/vendor/products/import")
async def vendor_import(body: ImportIn, request: Request, user: dict = Depends(require_approved_vendor)):
    """All-or-nothing: every row is validated first. If ANY row is invalid nothing is written and a row-by-row error report is
    returned (never a silent skip). With commit=false the same report is returned as a preview."""
    if body.mode not in ("products", "stock"):
        raise HTTPException(status_code=400, detail="mode must be products or stock.")
    vid = user["_vendor"]["id"]
    try:
        rows = cat.parse_csv(body.csv, ["sku", "name"] if body.mode == "products" else ["sku", "delta", "reason"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    report, plans, seen = [], [], set()
    own = {p["sku"]: p async for p in db.products.find({"vendor_id": vid}, P_PUBLIC)}
    for r in rows:
        errs = []
        sku = r.get("sku", "").strip().upper()
        if not sku:
            errs.append("sku is required")
        elif sku in seen:
            errs.append("duplicate SKU in this file")
        seen.add(sku)
        existing = own.get(sku)
        try:
            if body.mode == "stock":
                if not existing:
                    errs.append("unknown SKU (stock import only changes your own existing products)")
                delta = int(r.get("delta", ""))
                if delta == 0:
                    errs.append("delta cannot be 0")
                if len(r.get("reason", "")) < 3:
                    errs.append("reason is required (3+ characters)")
                vsku = r.get("variant_sku", "").strip().upper() or None
                if existing and existing.get("variants") and not vsku:
                    errs.append("variant_sku is required for a product with variants")
                if existing and vsku:
                    cur = next((x["stock"] for x in existing.get("variants") or [] if x["sku"] == vsku), None)
                    if cur is None:
                        errs.append("unknown variant_sku")
                elif existing:
                    cur = existing.get("stock", 0)
                if existing and not errs and cur + delta < 0:
                    errs.append(f"stock would go below zero (current {cur})")
                if not errs:
                    plans.append(("stock", existing, delta, r["reason"], vsku))
            else:
                if existing and existing.get("variants"):
                    errs.append("products with variants are edited in the product form, not by CSV")
                payload = dict(sku=sku, name=r.get("name", ""), name_hi=r.get("name_hi", ""), description=r.get("description", ""),
                               category=r.get("category", ""), subcategory=r.get("subcategory", ""), brand=r.get("brand", ""),
                               mrp=float(r.get("mrp") or 0), selling_price=float(r.get("selling_price") or 0),
                               gst_percent=float(r.get("gst_percent") or 5), stock=int(r.get("stock") or 0),
                               low_stock_threshold=int(r.get("low_stock_threshold") or 5),
                               images=[x for x in r.get("images", "").split("|") if x.strip()],
                               package={"weight_g": float(r["weight_g"])} if r.get("weight_g") else {}, return_policy=r.get("return_policy", ""))
                m = VendorProductIn(**payload)
                data = _clean_product_payload(m, existing.get("variants") if existing else None)
                if not existing and await db.products.find_one({"$or": [{"sku": sku}, {"variants.sku": sku}]}):
                    errs.append("this SKU belongs to another seller")
                if existing and body.mode == "products":
                    data.pop("stock", None)                 # existing stock changes only through reasoned adjustments / stock mode
                if not errs:
                    plans.append(("upsert", existing, data, sku))
        except ValueError as e:
            errs.append(str(e).split("\n")[0][:160])
        except HTTPException as e:
            errs.append(str(e.detail))
        except Exception as e:     # pydantic validation etc.
            msg = getattr(e, "errors", lambda: [{"msg": str(e)}])()
            errs.append("; ".join(f"{'.'.join(map(str, x.get('loc', [])))}: {x.get('msg')}" for x in msg)[:200])
        report.append({"row": r["_row"], "sku": sku, "status": "error" if errs else "ok", "errors": errs})
    bad = sum(1 for x in report if x["status"] == "error")
    result = {"rows": len(report), "valid": len(report) - bad, "invalid": bad, "report": report, "committed": False}
    if bad:
        if body.commit:
            raise HTTPException(status_code=400, detail={"message": "Nothing was imported because some rows have errors.", **result})
        return result
    if not body.commit:
        return result
    for kind, existing, *rest in plans:
        if kind == "stock":
            delta, reason, vsku = rest
            inc = {"stock": delta, **({"variants.$.stock": delta} if vsku else {})}
            flt = {"id": existing["id"], "vendor_id": vid, **({"variants": {"$elemMatch": {"sku": vsku, "stock": {"$gte": -delta}}}} if vsku else {"stock": {"$gte": -delta}})}
            res = await db.products.update_one(flt, {"$inc": inc})
            if res.modified_count == 1:
                await db.stock_movements.insert_one({"id": new_id(), "product_id": existing["id"], "variant_sku": vsku, "delta": delta, "reason": reason,
                                                     "actor_id": user["id"], "created_at": now_iso(), "source": "csv"})
        else:
            data, sku = rest
            if existing:
                changed = any(existing.get(k) != data.get(k) for k in REVIEW_FIELDS)
                upd = {k: v for k, v in data.items() if k not in ("sku", "stock")}
                upd["updated_at"] = now_iso()
                if changed:
                    upd.update({"approval_status": "pending", "is_active": False, "rejection_reason": ""})
                await db.products.update_one({"id": existing["id"], "vendor_id": vid}, {"$set": upd})
            else:
                p = {**data, "sku": sku, "id": new_id(), "vendor_id": vid, "vendor_name": user["_vendor"]["business_name"], "is_active": False,
                     "approval_status": "pending", "rejection_reason": "", "archived": False, "created_at": now_iso(), "updated_at": now_iso()}
                await db.products.insert_one(dict(p))
                if p["stock"]:
                    await db.stock_movements.insert_one({"id": new_id(), "product_id": p["id"], "delta": p["stock"], "reason": "initial_stock",
                                                         "actor_id": user["id"], "created_at": now_iso(), "source": "csv"})
    await log_audit(user, "vendor_csv_import", "vendor", vid, new_value={"mode": body.mode, "rows": len(plans)}, request=request)
    return {**result, "committed": True}


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
def _dispatch_deadline(order: dict, lines: list, f: dict) -> dict:
    """Dispatch deadline = (payment time for prepaid, order time for COD) + the longest handling time among this vendor's lines."""
    base = order.get("paid_at") if order.get("payment_method") == "online" else order.get("created_at")
    days = max([int(li.get("handling_days", 3)) for li in lines] or [3])
    try:
        due = datetime.fromisoformat(base) + timedelta(days=days)
    except Exception:
        return {"dispatch_due_at": None, "dispatch_overdue": False}
    open_state = f.get("status") in ("new", "accepted", "packed")
    return {"dispatch_due_at": due.isoformat(), "dispatch_overdue": open_state and datetime.now(timezone.utc) > due}


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
        "paid_at": order.get("paid_at"), "order_status": order.get("status"),
        "items": lines, "items_total": round(sum(li.get("total", 0) for li in lines), 2),
        "items_total_paise": sum(paise_of(li, "total_paise", "total") for li in lines),
        "ship_to": {k: a.get(k, "") for k in ("full_name", "mobile", "line1", "city", "state", "pincode")},
        "fulfilment": f, "cancel_requested": order.get("cancel_requested"),
        **_dispatch_deadline(order, lines, f),
    }


def _orders_base(vid: str) -> dict:
    """Orders this vendor may see: payment not pending/failed, and not on hold for a refund (paid after expiry)."""
    return {"fulfilments.vendor_id": vid, "payment_status": {"$nin": ["pending", "failed"]}, "needs_refund": {"$ne": True}}


@router.get("/vendor/orders")
async def vendor_orders(status: Optional[str] = None, q: Optional[str] = None, date_from: Optional[str] = None,
                        date_to: Optional[str] = None, page: Optional[int] = None, page_size: Optional[int] = None,
                        user: dict = Depends(require_approved_vendor)):
    """Own order lines. No `page`/`q`/dates = the original plain list (up to 500, optional `status`). With `page` (or q /
    dates) the reply is {items, total, page, page_size, pages, counts} where counts is per fulfilment status for the same
    search/date window. Search matches order number, product name or SKU of THIS vendor's lines only."""
    vid = user["_vendor"]["id"]
    if status and status not in FLOW:
        raise HTTPException(status_code=400, detail="Unknown status.")
    base = _orders_base(vid)
    try:
        dr = date_range(date_from, date_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"{e} must be a date like 2026-10-23.")
    tf = text_filter(q)
    window = dict(base)
    if dr:
        window["created_at"] = dr
    if tf:
        window["$or"] = [{"order_number": tf}, {"items": {"$elemMatch": {"vendor_id": vid, "$or": [{"name": tf}, {"sku": tf}]}}}]
    query = dict(window)
    if status:
        query["fulfilments"] = {"$elemMatch": {"vendor_id": vid, "status": status}}
    if page is None and not (q or date_from or date_to):
        orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
        return [v for v in (_vendor_view(o, vid) for o in orders) if v]
    page, page_size = clamp_page(page, page_size)
    total = await db.orders.count_documents(query)
    rows = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).skip((page - 1) * page_size).limit(page_size).to_list(page_size)
    agg = await db.orders.aggregate([{"$match": window}, {"$unwind": "$fulfilments"}, {"$match": {"fulfilments.vendor_id": vid}},
                                     {"$group": {"_id": "$fulfilments.status", "n": {"$sum": 1}}}]).to_list(20)
    counts = {r["_id"]: r["n"] for r in agg}
    counts["all"] = sum(counts.values())
    return {"items": [v for v in (_vendor_view(o, vid) for o in rows) if v], **page_meta(total, page, page_size), "counts": counts}


@router.get("/vendor/orders/{order_id}")
async def vendor_order(order_id: str, user: dict = Depends(require_approved_vendor), detail: bool = False):
    vid = user["_vendor"]["id"]
    o = await db.orders.find_one({"id": order_id, "fulfilments.vendor_id": vid, "needs_refund": {"$ne": True}}, {"_id": 0})
    view = _vendor_view(o, vid) if o else None
    if not view:
        raise HTTPException(status_code=404, detail="Order not found.")
    if not detail:
        return view
    # ---- full order-detail view: timeline, shipment, returns, this vendor's ledger entries (never other vendors' data)
    who = lambda by: "you" if by == user["id"] else ("system" if by in ("system", None) else "platform")
    tl = [{"at": o.get("created_at"), "type": "placed", "label": "Order placed", "by": "customer"}]
    if o.get("paid_at"):
        tl.append({"at": o["paid_at"], "type": "payment", "label": "Payment confirmed", "by": "system"})
    for e in view["fulfilment"].get("events", []):
        tl.append({"at": e.get("at"), "type": "fulfilment", "status": e.get("status"), "note": e.get("note", ""), "by": who(e.get("by"))})
    insp = view["fulfilment"].get("return_inspection")
    if insp:
        tl.append({"at": insp.get("at"), "type": "return_inspection", "label": f"Return inspected: {insp.get('outcome')}", "note": insp.get("note", ""), "by": "you"})
    returns = await db.return_cases.find({"order_id": order_id, "vendor_id": vid}, {"_id": 0}).sort("created_at", 1).to_list(20)
    for r in returns:
        tl.append({"at": r["created_at"], "type": "return", "label": f"{r['kind'].title()} {r['number']} requested", "by": "customer"})
    ledger_rows = await db.vendor_ledger.find({"vendor_id": vid, "order_id": order_id}, {"_id": 0}).sort("posted_at", 1).to_list(50)
    tl.sort(key=lambda x: x.get("at") or "")
    f = view["fulfilment"]
    exceptions = [e for e in f.get("events", []) if e.get("status") in ("delivery_failed", "returned_to_origin", "rejected", "cancelled")]
    return {**view, "timeline": tl, "returns": returns, "ledger": ledger_rows, "exceptions": exceptions,
            "shipment": {"carrier": f.get("carrier", ""), "tracking_number": f.get("tracking_number", ""), "tracking_url": f.get("tracking_url", ""),
                         "dispatched_at": next((e["at"] for e in f.get("events", []) if e.get("status") == "dispatched"), None)},
            "financial": {"items_total_paise": view["items_total_paise"], "payment_method": o.get("payment_method"), "payment_status": o.get("payment_status"),
                          "cod_discrepancy": o.get("cod_discrepancy")}}


async def sweep_dispatch_deadlines(limit: int = 500) -> int:
    """Once per fulfilment: tell the vendor an order has passed its dispatch deadline. Idempotent (flag on the fulfilment)."""
    n = 0
    q = {"payment_status": {"$nin": ["pending", "failed"]}, "needs_refund": {"$ne": True}, "status": {"$nin": ["cancelled"]},
         "fulfilments": {"$elemMatch": {"status": {"$in": ["new", "accepted", "packed"]}, "deadline_notified": {"$ne": True}}}}
    async for o in db.orders.find(q, {"_id": 0}).limit(limit):
        for f in o["fulfilments"]:
            if f.get("status") not in ("new", "accepted", "packed") or f.get("deadline_notified"):
                continue
            lines = [li for li in o.get("items", []) if li.get("vendor_id") == f["vendor_id"]]
            if not _dispatch_deadline(o, lines, f)["dispatch_overdue"]:
                continue
            claim = await db.orders.update_one({"id": o["id"], "fulfilments": {"$elemMatch": {"vendor_id": f["vendor_id"], "deadline_notified": {"$ne": True}}}},
                                               {"$set": {"fulfilments.$.deadline_notified": True}})
            if claim.modified_count == 1:
                v = await db.vendors.find_one({"id": f["vendor_id"]}, {"_id": 0, "user_id": 1})
                await create_notification(v["user_id"], "order", "Dispatch deadline passed", f"Order {o.get('order_number')} is past its dispatch deadline. Please dispatch it or tell the customer why.", meta={"order_id": o["id"]})
                n += 1
    return n


class FulfilIn(BaseModel):
    status: str
    note: str = ""
    carrier: str = ""
    tracking_number: str = ""
    tracking_url: str = ""


@router.post("/vendor/orders/{order_id}/fulfilment")
async def vendor_update_fulfilment(order_id: str, body: FulfilIn, request: Request, user: dict = Depends(require_approved_vendor)):
    vid = user["_vendor"]["id"]
    o = await db.orders.find_one({"id": order_id, "fulfilments.vendor_id": vid, "needs_refund": {"$ne": True}}, {"_id": 0})
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
    push = {"fulfilments.$.events": event}
    if nxt in RESTOCK_ON:   # the restock decision is recorded atomically with the transition, so a crash cannot lose it
        push["restock_intents"] = intent("vendor_release", user["id"], vendor_id=vid, reason=f"order_{nxt}")
    res = await db.orders.update_one({"id": order_id, "fulfilments": {"$elemMatch": {"vendor_id": vid, "status": cur}}},
                                     {"$set": sets, "$push": push})
    if res.modified_count != 1:
        raise HTTPException(status_code=409, detail="This order was just updated. Please refresh.")

    if nxt in RESTOCK_ON:   # exactly once per line; an interrupted run is replayed by recovery
        await run_intents(order_id)
        from ledger import post_sale_reversal       # a paid order the vendor did not fulfil: take the recorded sale back
        await post_sale_reversal(o, vid)

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


class InspectionIn(BaseModel):
    received: bool
    outcome: str                    # "resellable" -> goes back into stock; "damaged" -> does not
    note: str = Field(min_length=5, max_length=300)


@router.post("/vendor/orders/{order_id}/return-inspection")
async def vendor_return_inspection(order_id: str, body: InspectionIn, request: Request, user: dict = Depends(require_approved_vendor)):
    """Goods that came back (returned_to_origin) are restocked ONLY after the vendor confirms receipt and inspection.
    One decision per order; resellable units are restocked atomically and at most once."""
    vid = user["_vendor"]["id"]
    if not body.received:
        raise HTTPException(status_code=400, detail="Confirm that you have physically received the goods.")
    if body.outcome not in ("resellable", "damaged"):
        raise HTTPException(status_code=400, detail="Outcome must be 'resellable' or 'damaged'.")
    rec = {"outcome": body.outcome, "note": body.note.strip(), "by": user["id"], "at": now_iso()}
    # Orders returned BEFORE this rule existed were restocked automatically at return time (movement reason
    # "order_returned_to_origin"); restocking them again would double-count, so only the decision is recorded.
    already = await db.stock_movements.find_one({"order_id": order_id, "reason": "order_returned_to_origin"}, {"_id": 1})
    upd = {"$set": {"fulfilments.$.return_inspection": rec, "updated_at": now_iso()}}
    if body.outcome == "resellable" and not already:   # decision + restock intent recorded in ONE atomic update
        upd["$push"] = {"restock_intents": intent("vendor_release", user["id"], vendor_id=vid, reason="return_inspected_resellable")}
    # Atomic one-shot claim: only a fulfilment that is returned_to_origin and not yet inspected can be decided.
    res = await db.orders.update_one(
        {"id": order_id, "needs_refund": {"$ne": True},
         "fulfilments": {"$elemMatch": {"vendor_id": vid, "status": "returned_to_origin", "return_inspection": {"$exists": False}}}}, upd)
    if res.modified_count != 1:
        if not await db.orders.find_one({"id": order_id, "fulfilments.vendor_id": vid}, {"_id": 1}):
            raise HTTPException(status_code=404, detail="Order not found.")
        raise HTTPException(status_code=400, detail="This order is not awaiting a return inspection (or it was already recorded).")
    restocked = await run_intents(order_id) if "$push" in upd else 0
    await log_audit(user, "return_inspected", "order", order_id, new_value={**rec, "restocked_lines": restocked}, request=request)
    return {"order": await vendor_order(order_id, user), "restocked_lines": restocked}


# ------------------------------------------------------------------ dashboard
def _money(values) -> float:
    """Exact (Decimal) sum of rupee amounts, rounded to paise."""
    return float(sum((Decimal(str(v or 0)) for v in values), Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


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
    action: str          # start_review / approve / reject / suspend / reinstate
    reason: str = ""     # shown to the vendor
    internal_note: str = Field(default="", max_length=500)   # admin-only, never returned to vendors


@router.post("/admin/vendors/{vendor_id}/decision")
async def admin_vendor_decision(vendor_id: str, body: VendorDecision, request: Request, admin: dict = Depends(require_admin)):
    v = await db.vendors.find_one({"id": vendor_id}, {"_id": 0})
    if not v:
        raise HTTPException(status_code=404, detail="Vendor not found.")
    allowed = {"start_review": ({"submitted"}, "under_review"), "approve": ({"submitted", "under_review", "rejected"}, "approved"),
               "reject": ({"submitted", "under_review"}, "rejected"),
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
    await record_vendor_status(vendor_id, v["status"], to, admin["id"], body.reason.strip(), body.internal_note.strip())
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
    return await db.products.find(q, P_PUBLIC).sort("updated_at", -1).to_list(500)


class ProductDecision(BaseModel):
    action: str          # approve / reject
    reason: str = ""


@router.post("/admin/vendor-products/{product_id}/decision")
async def admin_product_decision(product_id: str, body: ProductDecision, request: Request, admin: dict = Depends(require_admin)):
    p = await db.products.find_one({"id": product_id, "vendor_id": {"$ne": None}}, P_PUBLIC)
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
    return await db.products.find_one({"id": product_id}, P_PUBLIC)


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
