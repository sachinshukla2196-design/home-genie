"""Marketplace merchandising (Batch 13, Phase 10). Spec: docs/MARKETPLACE_MERCHANDISING_SPEC.md.

Sections (`merch_sections`) are configured by super_admin / admin and shown on the shop home:
  banner              desktop + mobile image (uploaded storage references only), alt text, an INTERNAL link
  collection          a hand-ordered list of products
  featured_products   the same, labelled "Featured"
  featured_categories an ordered list of the four pillars
  new_arrivals        the newest products on sale (computed)
  bestsellers         the products sold most in the last N days, from PAID, NON-CANCELLED orders, net of refunded units (computed)
Lifecycle: draft -> published -> unpublished (and back); `starts_at` / `ends_at` are checked on every read, so a campaign
activates and expires on time without any scheduled job. Every change is audited and kept in `history`.

Rules: only products on sale (approved, active, not archived) are ever shown; out-of-stock products are skipped (configuration
kept, so they reappear when restocked); a section with nothing to show is not shown; no ratings, sales counts or popularity claims
are displayed (bestsellers are ordered by real sales but show no numbers); no discounts are created here. Vendors cannot create or
change sections.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from core import db, log_audit, new_id, now_iso, require_admin, require_vendor_admin

router = APIRouter(prefix="/api", tags=["merchandising"])
KINDS = ("banner", "collection", "featured_products", "featured_categories", "new_arrivals", "bestsellers")
STATUSES = ("draft", "published", "unpublished")
MAX_PRODUCTS = 24


def _iso(v: Optional[str]) -> Optional[str]:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("Dates must be ISO date-times, e.g. 2026-12-01T09:00:00+05:30.")
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


class SectionIn(BaseModel):
    kind: str
    title: str = Field(min_length=2, max_length=80)
    subtitle: str = Field(default="", max_length=160)
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    image_desktop: str = ""
    image_mobile: str = ""
    alt: str = Field(default="", max_length=125)
    link: str = Field(default="", max_length=200)
    product_ids: List[str] = Field(default=[], max_length=MAX_PRODUCTS)
    categories: List[str] = Field(default=[], max_length=4)
    limit: int = Field(default=8, ge=1, le=MAX_PRODUCTS)
    window_days: int = Field(default=30, ge=1, le=365)

    @field_validator("kind")
    @classmethod
    def _kind(cls, v):
        if v not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
        return v

    @field_validator("starts_at", "ends_at")
    @classmethod
    def _dates(cls, v):
        return _iso(v)

    @field_validator("link")
    @classmethod
    def _link(cls, v):
        v = (v or "").strip()
        if v and (not v.startswith("/") or v.startswith("//") or any(ch in v for ch in " <>\"'")):
            raise ValueError("The link must be a page of this shop, starting with / (for example /app/products?category=Sarees).")
        return v

    @field_validator("image_desktop", "image_mobile")
    @classmethod
    def _image(cls, v):
        from validators import safe_image_refs
        v = (v or "").strip()
        return safe_image_refs([v], 1)[0] if v else ""

    @field_validator("categories")
    @classmethod
    def _cats(cls, v):
        from catalogue import PILLARS
        if any(c not in PILLARS for c in v):
            raise ValueError("Categories must be HOME GENIES pillars.")
        return list(dict.fromkeys(v))


def _check(body: SectionIn) -> None:
    if body.starts_at and body.ends_at and body.ends_at <= body.starts_at:
        raise HTTPException(status_code=400, detail="The end must be after the start.")
    if body.kind == "banner" and not body.image_desktop:
        raise HTTPException(status_code=400, detail="A banner needs a desktop image (the mobile image is optional).")
    if body.kind == "banner" and not body.alt.strip():
        raise HTTPException(status_code=400, detail="Describe the banner image (alternative text).")
    if body.kind in ("collection", "featured_products") and not body.product_ids:
        raise HTTPException(status_code=400, detail="Add at least one product.")
    if body.kind == "featured_categories" and not body.categories:
        raise HTTPException(status_code=400, detail="Choose at least one category.")


def _shop():
    from shop_routes import P_SHOP, SHOP_VISIBLE
    return dict(SHOP_VISIBLE), P_SHOP


async def resolve(s: dict) -> Optional[dict]:
    """What the section shows right now (None when there is nothing to show)."""
    vis, proj = _shop()
    kind, out = s["kind"], {k: s.get(k) for k in ("id", "kind", "title", "subtitle", "link", "image_desktop", "image_mobile", "alt")}
    if kind == "banner":
        return out
    if kind == "featured_categories":
        return {**out, "categories": s.get("categories") or []}
    if kind in ("collection", "featured_products"):
        ids = s.get("product_ids") or []
        rows = {p["id"]: p for p in await db.products.find({**vis, "id": {"$in": ids}, "stock": {"$gt": 0}}, proj).to_list(MAX_PRODUCTS)}
        items = [rows[i] for i in ids if i in rows]
    elif kind == "new_arrivals":
        items = await db.products.find({**vis, "stock": {"$gt": 0}}, proj).sort([("created_at", -1), ("id", 1)]).limit(s.get("limit") or 8).to_list(MAX_PRODUCTS)
    else:   # bestsellers from real, paid, not cancelled orders in the window, net of refunded orders
        since = (datetime.now(timezone.utc) - timedelta(days=s.get("window_days") or 30)).isoformat()
        sold = await db.orders.aggregate([
            {"$match": {"payment_status": {"$in": ["paid", "partially_refunded"]}, "status": {"$ne": "cancelled"}, "created_at": {"$gte": since}}},
            {"$unwind": "$items"}, {"$group": {"_id": "$items.product_id", "units": {"$sum": "$items.quantity"}}},
            {"$sort": {"units": -1, "_id": 1}}, {"$limit": 100}]).to_list(100)
        order = [r["_id"] for r in sold]
        rows = {p["id"]: p for p in await db.products.find({**vis, "id": {"$in": order}, "stock": {"$gt": 0}}, proj).to_list(100)}
        items = [rows[i] for i in order if i in rows][: s.get("limit") or 8]
    return {**out, "products": items} if items else None


def _live_filter(now: str) -> dict:
    return {"status": "published", "$and": [{"$or": [{"starts_at": None}, {"starts_at": {"$lte": now}}]},
                                            {"$or": [{"ends_at": None}, {"ends_at": {"$gt": now}}]}]}


@router.get("/merch/home")
async def merch_home():
    """Published sections whose time window includes now, in position order, each resolved to what it shows."""
    now = datetime.now(timezone.utc).isoformat()
    rows = await db.merch_sections.find(_live_filter(now), {"_id": 0}).sort([("position", 1), ("created_at", 1)]).to_list(30)
    out = []
    for s in rows:
        r = await resolve(s)
        if r:
            out.append(r)
    return {"sections": out}


# ------------------------------------------------------------------ admin
def _view(s: dict, now: str) -> dict:
    live = s["status"] == "published" and (not s.get("starts_at") or s["starts_at"] <= now) and (not s.get("ends_at") or s["ends_at"] > now)
    state = "live" if live else ("scheduled" if s["status"] == "published" and s.get("starts_at") and s["starts_at"] > now else
                                 "expired" if s["status"] == "published" and s.get("ends_at") and s["ends_at"] <= now else s["status"])
    return {**{k: v for k, v in s.items() if k not in ("_id", "history")}, "state": state, "history": (s.get("history") or [])[-10:]}


@router.get("/admin/merch/sections")
async def list_sections(admin: dict = Depends(require_admin)):
    now = datetime.now(timezone.utc).isoformat()
    rows = await db.merch_sections.find({"status": {"$ne": "deleted"}}, {"_id": 0}).sort([("position", 1), ("created_at", 1)]).to_list(100)
    return {"sections": [_view(s, now) for s in rows], "kinds": list(KINDS)}


async def _get(sid: str) -> dict:
    s = await db.merch_sections.find_one({"id": sid, "status": {"$ne": "deleted"}}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Section not found.")
    return s


async def _validate_products(ids: List[str]) -> None:
    vis, _ = _shop()
    found = set(await db.products.distinct("id", {**vis, "id": {"$in": ids}}))
    bad = [i for i in ids if i not in found]
    if bad:
        raise HTTPException(status_code=400, detail=f"Only approved products on sale can be featured ({len(bad)} are not).")


@router.post("/admin/merch/sections")
async def create_section(body: SectionIn, request: Request, admin: dict = Depends(require_vendor_admin)):
    _check(body)
    from governance_routes import validate_platform_images          # Programme 01 (B-009): validated uploads only
    await validate_platform_images([body.image_desktop, body.image_mobile], request)
    if body.product_ids:
        await _validate_products(body.product_ids)
    n = await db.merch_sections.count_documents({"status": {"$ne": "deleted"}})
    now = now_iso()
    s = {"id": new_id(), **body.model_dump(), "status": "draft", "position": n, "created_by": admin["id"], "updated_by": admin["id"],
         "created_at": now, "updated_at": now, "history": [{"at": now, "by": admin["id"], "action": "created"}]}
    await db.merch_sections.insert_one(dict(s))
    await log_audit(admin, "merch_section_created", "merch_section", s["id"], new_value={"kind": body.kind, "title": body.title}, request=request)
    return _view(s, now)


@router.put("/admin/merch/sections/{sid}")
async def update_section(sid: str, body: SectionIn, request: Request, admin: dict = Depends(require_vendor_admin)):
    s = await _get(sid)
    if body.kind != s["kind"]:
        raise HTTPException(status_code=400, detail="The section type cannot change. Create a new section instead.")
    _check(body)
    from governance_routes import validate_platform_images          # Programme 01 (B-009): validated uploads only
    await validate_platform_images([body.image_desktop, body.image_mobile], request)
    if body.product_ids:
        await _validate_products(body.product_ids)
    now = now_iso()
    await db.merch_sections.update_one({"id": sid}, {"$set": {**body.model_dump(), "updated_by": admin["id"], "updated_at": now},
                                                     "$push": {"history": {"at": now, "by": admin["id"], "action": "edited"}}})
    await log_audit(admin, "merch_section_edited", "merch_section", sid, request=request)
    return _view(await _get(sid), now)


class StatusIn(BaseModel):
    action: str          # publish | unpublish | delete


@router.post("/admin/merch/sections/{sid}/status")
async def section_status(sid: str, body: StatusIn, request: Request, admin: dict = Depends(require_vendor_admin)):
    s = await _get(sid)
    target = {"publish": "published", "unpublish": "unpublished", "delete": "deleted"}.get(body.action)
    if not target:
        raise HTTPException(status_code=400, detail="action must be publish, unpublish or delete.")
    if target == "published":
        _check(SectionIn(**{k: s.get(k) for k in SectionIn.model_fields if k in s}))
        if s.get("product_ids"):
            await _validate_products(s["product_ids"])
    now = now_iso()
    await db.merch_sections.update_one({"id": sid}, {"$set": {"status": target, "updated_by": admin["id"], "updated_at": now},
                                                     "$push": {"history": {"at": now, "by": admin["id"], "action": body.action}}})
    await log_audit(admin, f"merch_section_{body.action}", "merch_section", sid, old_value={"status": s["status"]}, new_value={"status": target},
                    request=request)
    return {"ok": True, "status": target}


class OrderIn(BaseModel):
    ids: List[str] = Field(max_length=100)


@router.post("/admin/merch/sections/order")
async def reorder(body: OrderIn, request: Request, admin: dict = Depends(require_vendor_admin)):
    for i, sid in enumerate(body.ids):
        await db.merch_sections.update_one({"id": sid}, {"$set": {"position": i}})
    await log_audit(admin, "merch_sections_reordered", "merch_section", "", new_value={"ids": body.ids}, request=request)
    return await list_sections(admin)


@router.get("/admin/merch/sections/{sid}/preview")
async def preview(sid: str, admin: dict = Depends(require_admin)):
    """What the section would show now if it were live (whatever its status and dates)."""
    s = await _get(sid)
    return {"section": await resolve(s), "empty": await resolve(s) is None}
