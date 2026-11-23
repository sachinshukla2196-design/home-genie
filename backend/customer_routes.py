"""Customer address book and wishlist (Batch 13, Phase 7).

ADDRESS BOOK (`addresses`)
- Every address belongs to one account (`user_id`); every read and write is filtered by the caller's id, so nobody can see or
  change another person's address (an unknown or foreign id is simply "not found").
- The default is ONE pointer on the user (`users.default_address_id`), so two concurrent "make default" requests can never leave
  two defaults. The first address becomes the default; deleting the default moves it to the most recently used remaining address.
- Deleting is a soft delete (`deleted_at`). Orders never point at the book: checkout copies the address into the order (a
  snapshot), so editing or deleting an address never changes an order that was already placed.
- Validation is on the server: Indian 10-digit mobile, 6-digit PIN (first digit 1-9), a state from the list of states and union
  territories, required name / first line / city. Optional: second line, locality, landmark, district. Country is India
  (payments, mobile and PIN formats are Indian; no other country is offered). No other field is required.

WISHLIST (`wishlist_items`)
- One row per (account, product, variant); a unique index makes repeated or simultaneous adds harmless. Remove is idempotent.
- Only products currently on sale can be added. The list shows each product's CURRENT state (price, availability, variant
  stock, whether it is still sold); being on a wishlist never makes an unavailable product purchasable - the order endpoint
  checks everything again. The price when added is kept only to show "price went up / down" honestly; no alert is sent.
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from pymongo.errors import DuplicateKeyError

from core import db, get_current_user, log_audit, new_id, now_iso

router = APIRouter(prefix="/api", tags=["customer"])

MAX_ADDRESSES = 20
MAX_WISHLIST = 200
LABELS = ("home", "work", "other")
MOBILE_RE = re.compile(r"[6-9]\d{9}")
PIN_RE = re.compile(r"[1-9]\d{5}")


def _states():
    from vendor_onboarding import INDIAN_STATES
    return INDIAN_STATES


def _text(v: str, label: str, lo: int, hi: int, required: bool = True) -> str:
    v = (v or "").strip()
    if not v:
        if required:
            raise ValueError(f"{label} is required.")
        return ""
    if len(v) < lo or len(v) > hi:
        raise ValueError(f"{label} must be {lo}-{hi} characters.")
    if any(ch in v for ch in "<>"):
        raise ValueError(f"{label} cannot contain < or >.")
    return v


class AddressBody(BaseModel):
    label: str = "home"
    full_name: str
    mobile: str
    line1: str
    line2: str = ""
    locality: str = ""
    landmark: str = ""
    city: str
    district: str = ""
    state: str
    pincode: str
    country: str = "India"
    make_default: bool = False

    @field_validator("label")
    @classmethod
    def _label(cls, v):
        v = (v or "home").strip().lower()
        if v not in LABELS:
            raise ValueError("Address type must be Home, Work or Other.")
        return v

    @field_validator("full_name")
    @classmethod
    def _name(cls, v):
        return _text(v, "Recipient name", 2, 80)

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        v = re.sub(r"[\s-]", "", v or "")
        if v.startswith("+91"):
            v = v[3:]
        if not MOBILE_RE.fullmatch(v):
            raise ValueError("Enter a valid 10-digit Indian mobile number.")
        return v

    @field_validator("line1")
    @classmethod
    def _line1(cls, v):
        return _text(v, "Address line 1", 3, 120)

    @field_validator("line2", "locality", "landmark", "district")
    @classmethod
    def _optional(cls, v, info):
        labels = {"line2": "Address line 2", "locality": "Locality", "landmark": "Landmark", "district": "District"}
        return _text(v, labels[info.field_name], 2, 120, required=False)

    @field_validator("city")
    @classmethod
    def _city(cls, v):
        return _text(v, "City", 2, 60)

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        v = (v or "").strip()
        if v not in _states():
            raise ValueError("Choose a state or union territory from the list.")
        return v

    @field_validator("pincode")
    @classmethod
    def _pin(cls, v):
        v = (v or "").strip()
        if not PIN_RE.fullmatch(v):
            raise ValueError("Enter a valid 6-digit PIN code.")
        return v

    @field_validator("country")
    @classmethod
    def _country(cls, v):
        if (v or "India").strip() != "India":
            raise ValueError("Delivery is available in India only.")
        return "India"


ADDRESS_FIELDS = ("label", "full_name", "mobile", "line1", "line2", "locality", "landmark", "city", "district", "state", "pincode", "country")


def _view(a: dict, default_id: Optional[str]) -> dict:
    out = {k: a.get(k, "") for k in ("id", *ADDRESS_FIELDS, "created_at", "updated_at", "last_used_at")}
    out["is_default"] = a["id"] == default_id
    return out


async def _default_id(uid: str) -> Optional[str]:
    u = await db.users.find_one({"id": uid}, {"_id": 0, "default_address_id": 1})
    return (u or {}).get("default_address_id")


async def _own(uid: str, address_id: str) -> dict:
    a = await db.addresses.find_one({"id": address_id, "user_id": uid, "deleted_at": None}, {"_id": 0})
    if not a:
        raise HTTPException(status_code=404, detail="Address not found.")
    return a


async def address_snapshot(uid: str, address_id: str) -> dict:
    """The address as it is NOW, copied into an order (used by checkout). Raises 404 for a missing / foreign / deleted id."""
    a = await _own(uid, address_id)
    await db.addresses.update_one({"id": address_id, "user_id": uid}, {"$set": {"last_used_at": now_iso()}})
    return {"address_id": a["id"], **{k: a.get(k, "") for k in ADDRESS_FIELDS}}


@router.get("/addresses")
async def list_addresses(user: dict = Depends(get_current_user)):
    rows = await db.addresses.find({"user_id": user["id"], "deleted_at": None}, {"_id": 0}).sort("created_at", 1).to_list(MAX_ADDRESSES)
    did = await _default_id(user["id"])
    items = [_view(a, did) for a in rows]
    items.sort(key=lambda x: (not x["is_default"], x["created_at"] or ""))
    return {"items": items, "states": list(_states()), "labels": list(LABELS), "max": MAX_ADDRESSES}


@router.post("/addresses")
async def add_address(body: AddressBody, request: Request, user: dict = Depends(get_current_user)):
    uid = user["id"]
    if await db.addresses.count_documents({"user_id": uid, "deleted_at": None}) >= MAX_ADDRESSES:
        raise HTTPException(status_code=400, detail=f"You can keep up to {MAX_ADDRESSES} addresses. Delete one you no longer use.")
    now = now_iso()
    a = {"id": new_id(), "user_id": uid, **{k: getattr(body, k) for k in ADDRESS_FIELDS}, "deleted_at": None,
         "created_at": now, "updated_at": now, "last_used_at": None}
    await db.addresses.insert_one(dict(a))
    # first address (or an explicit request) becomes the default; "no default yet" is checked in the same write
    if body.make_default:
        await db.users.update_one({"id": uid}, {"$set": {"default_address_id": a["id"]}})
    else:
        await db.users.update_one({"id": uid, "$or": [{"default_address_id": None}, {"default_address_id": {"$exists": False}}]},
                                  {"$set": {"default_address_id": a["id"]}})
    await log_audit(user, "address_added", "address", a["id"], request=request)
    return _view(a, await _default_id(uid))


@router.put("/addresses/{address_id}")
async def edit_address(address_id: str, body: AddressBody, request: Request, user: dict = Depends(get_current_user)):
    uid = user["id"]
    await _own(uid, address_id)
    res = await db.addresses.update_one({"id": address_id, "user_id": uid, "deleted_at": None},
                                        {"$set": {**{k: getattr(body, k) for k in ADDRESS_FIELDS}, "updated_at": now_iso()}})
    if res.matched_count != 1:
        raise HTTPException(status_code=404, detail="Address not found.")
    if body.make_default:
        await db.users.update_one({"id": uid}, {"$set": {"default_address_id": address_id}})
    await log_audit(user, "address_edited", "address", address_id, request=request)
    return _view(await _own(uid, address_id), await _default_id(uid))


@router.post("/addresses/{address_id}/default")
async def make_default(address_id: str, user: dict = Depends(get_current_user)):
    await _own(user["id"], address_id)
    await db.users.update_one({"id": user["id"]}, {"$set": {"default_address_id": address_id}})
    return await list_addresses(user)


@router.delete("/addresses/{address_id}")
async def delete_address(address_id: str, request: Request, user: dict = Depends(get_current_user)):
    uid = user["id"]
    res = await db.addresses.update_one({"id": address_id, "user_id": uid, "deleted_at": None},
                                        {"$set": {"deleted_at": now_iso(), "updated_at": now_iso()}})
    if res.matched_count != 1:
        a = await db.addresses.find_one({"id": address_id, "user_id": uid}, {"_id": 0, "deleted_at": 1})
        if a and a.get("deleted_at"):
            return await list_addresses(user)          # already deleted: same answer (idempotent)
        raise HTTPException(status_code=404, detail="Address not found.")
    # if it was the default, move the default to the most recently used / created remaining address (only if still pointing here)
    rest = await db.addresses.find({"user_id": uid, "deleted_at": None}, {"_id": 0, "id": 1, "last_used_at": 1, "created_at": 1}).to_list(MAX_ADDRESSES)
    rest.sort(key=lambda r: (r.get("last_used_at") or "", r.get("created_at") or ""), reverse=True)
    await db.users.update_one({"id": uid, "default_address_id": address_id},
                              {"$set": {"default_address_id": rest[0]["id"] if rest else None}})
    await log_audit(user, "address_deleted", "address", address_id, request=request)
    return await list_addresses(user)


# ------------------------------------------------------------------ wishlist
class WishIn(BaseModel):
    product_id: str = Field(min_length=1, max_length=64)
    variant_sku: str = Field(default="", max_length=40)


def _variant(p: dict, sku: str) -> Optional[dict]:
    return next((v for v in p.get("variants") or [] if v.get("sku") == sku), None)


def _state(p: Optional[dict], sku: str) -> dict:
    """What a shopper can do with this wishlist item right now (from the live product only)."""
    # the same rule as the shop (shop_routes.SHOP_VISIBLE): approved, active, not archived
    if not p or p.get("archived") or not p.get("is_active") or p.get("approval_status") not in (None, "approved"):
        return {"status": "unavailable", "price": None, "stock": 0}
    if p.get("variants"):
        if sku:
            v = _variant(p, sku)
            if not v:
                return {"status": "unavailable", "price": None, "stock": 0}
            price, stock = v.get("price") or p.get("selling_price"), int(v.get("stock") or 0)
        else:
            price = p.get("selling_price")
            stock = sum(int(v.get("stock") or 0) for v in p["variants"])
            return {"status": "choose_variant" if stock > 0 else "out_of_stock", "price": price, "stock": stock}
    else:
        price, stock = p.get("selling_price"), int(p.get("stock") or 0)
    return {"status": "available" if stock > 0 else "out_of_stock", "price": price, "stock": stock}


@router.get("/wishlist")
async def get_wishlist(user: dict = Depends(get_current_user)):
    from shop_routes import P_SHOP
    rows = await db.wishlist_items.find({"user_id": user["id"]}, {"_id": 0}).sort("added_at", -1).to_list(MAX_WISHLIST)
    prods = {p["id"]: p for p in await db.products.find({"id": {"$in": [r["product_id"] for r in rows]}}, P_SHOP).to_list(None)}
    items = []
    for r in rows:
        p = prods.get(r["product_id"])
        st = _state(p, r.get("variant_sku") or "")
        was = r.get("price_at_add")
        change = None
        if st["price"] is not None and was is not None and st["price"] != was:
            change = "down" if st["price"] < was else "up"
        items.append({"product_id": r["product_id"], "variant_sku": r.get("variant_sku") or "", "added_at": r["added_at"], **st,
                      "price_at_add": was, "price_change": change,
                      "product": None if not p or st["status"] == "unavailable" else
                      {k: p.get(k) for k in ("id", "name", "name_hi", "sku", "images", "mrp", "selling_price", "category", "variants")},
                      "name": (p or {}).get("name") or r.get("name_at_add") or "Product no longer available"})
    return {"items": items, "count": len(items)}


@router.post("/wishlist")
async def add_to_wishlist(body: WishIn, user: dict = Depends(get_current_user)):
    from shop_routes import SHOP_VISIBLE
    p = await db.products.find_one({"id": body.product_id, **SHOP_VISIBLE}, {"_id": 0, "id": 1, "name": 1, "selling_price": 1, "variants": 1})
    if not p:
        raise HTTPException(status_code=404, detail="This product is not available.")
    sku = body.variant_sku.strip().upper()
    if sku and not _variant(p, sku):
        raise HTTPException(status_code=400, detail="That option is not available for this product.")
    if await db.wishlist_items.count_documents({"user_id": user["id"]}) >= MAX_WISHLIST:
        raise HTTPException(status_code=400, detail=f"Your wishlist can hold up to {MAX_WISHLIST} items.")
    price = (_variant(p, sku) or {}).get("price") or p.get("selling_price")
    try:
        await db.wishlist_items.insert_one({"id": new_id(), "user_id": user["id"], "product_id": p["id"], "variant_sku": sku,
                                            "price_at_add": price, "name_at_add": p.get("name"), "added_at": now_iso()})
        added = True
    except DuplicateKeyError:                                     # already saved (double tap, two tabs): same result
        added = False
    return {"ok": True, "added": added, "count": await db.wishlist_items.count_documents({"user_id": user["id"]})}


@router.delete("/wishlist/{product_id}")
async def remove_from_wishlist(product_id: str, variant_sku: str = "", user: dict = Depends(get_current_user)):
    res = await db.wishlist_items.delete_many({"user_id": user["id"], "product_id": product_id, "variant_sku": (variant_sku or "").strip().upper()})
    return {"ok": True, "removed": res.deleted_count > 0, "count": await db.wishlist_items.count_documents({"user_id": user["id"]})}


@router.get("/wishlist/ids")
async def wishlist_ids(user: dict = Depends(get_current_user)):
    """Product ids on the wishlist (for the heart icons in the shop)."""
    rows = await db.wishlist_items.find({"user_id": user["id"]}, {"_id": 0, "product_id": 1, "variant_sku": 1}).to_list(MAX_WISHLIST)
    return {"items": rows}

