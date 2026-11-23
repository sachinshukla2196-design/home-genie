"""Product discovery (Batch 13, Phase 11): server-side search, filters, sorting, paging, suggestions, facets, related products and
"recently viewed" look-ups. Every query starts from the shop rule (approved, active, not archived — shop_routes.SHOP_VISIBLE) and
returns the shop projection (P_SHOP), so nothing that is not for sale, and no internal field, can leak through search.

Text search uses the `products_text` index ($text, weighted: name > brand / keywords > sub-category > short description); filters
use the `products_shop_category_price` index. No external search service is used.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from core import db

router = APIRouter(prefix="/api", tags=["discovery"])
SORTS = {"relevance": None, "newest": [("created_at", -1)], "price_asc": [("selling_price", 1)], "price_desc": [("selling_price", -1)],
         "name": [("name", 1)]}
MAX_PAGE = 48


def _base() -> dict:
    from shop_routes import SHOP_VISIBLE
    return dict(SHOP_VISIBLE)


def _attr_filters(request: Request) -> dict:
    """`attr.<key>=value` query parameters (repeatable, any-of) -> attribute filters on keys the catalogue knows."""
    from catalogue import ATTRIBUTE_SPECS
    known = {k for spec in ATTRIBUTE_SPECS.values() for k in spec}
    out = {}
    for k, v in request.query_params.multi_items():
        if not k.startswith("attr."):
            continue
        key = k[5:]
        if key not in known:
            raise HTTPException(status_code=400, detail=f"Unknown filter '{key}'.")
        out.setdefault(f"attributes.{key}", []).append(v[:60])
    return {k: {"$in": v} for k, v in out.items()}


@router.get("/catalog/search")
async def search(request: Request, q: Optional[str] = None, category: Optional[str] = None, subcategory: Optional[str] = None,
                 brand: Optional[List[str]] = Query(default=None), min_price: Optional[float] = None, max_price: Optional[float] = None,
                 in_stock: bool = False, sort: str = "relevance", page: int = 1, page_size: int = 24):
    from shop_routes import P_SHOP
    from pagination import page_meta
    if sort not in SORTS:
        raise HTTPException(status_code=400, detail="sort must be relevance, newest, price_asc, price_desc or name.")
    page, page_size = max(int(page or 1), 1), min(max(int(page_size or 24), 1), MAX_PAGE)
    flt = _base()
    if category:
        flt["category"] = category
    if subcategory:
        flt["subcategory"] = subcategory
    if brand:
        flt["brand"] = {"$in": [b[:60] for b in brand][:20]}
    price = {}
    if min_price is not None:
        price["$gte"] = min_price
    if max_price is not None:
        price["$lte"] = max_price
    if price:
        flt["selling_price"] = price
    if in_stock:
        flt["stock"] = {"$gt": 0}
    flt.update(_attr_filters(request))
    text = (q or "").strip()[:80]
    proj = dict(P_SHOP)
    if text:
        flt["$text"] = {"$search": text}
        proj = {**proj, "score": {"$meta": "textScore"}}
    total = await db.products.count_documents(flt)
    order = SORTS[sort] or ([("score", {"$meta": "textScore"})] if text else [("created_at", -1)])
    cur = db.products.find(flt, proj).sort(order + [("id", 1)]).skip((page - 1) * page_size).limit(page_size)
    items = await cur.to_list(page_size)
    for it in items:
        it.pop("score", None)
    return {"items": items, **page_meta(total, page, page_size), "sort": sort}


@router.get("/catalog/facets")
async def facets(category: Optional[str] = None):
    """Brands, price range, sub-categories and attribute values that actually exist among products on sale."""
    match = _base()
    if category:
        match["category"] = category
    rows = await db.products.aggregate([
        {"$match": match},
        {"$group": {"_id": None, "min": {"$min": "$selling_price"}, "max": {"$max": "$selling_price"},
                    "brands": {"$addToSet": "$brand"}, "subs": {"$addToSet": "$subcategory"}, "n": {"$sum": 1}}}]).to_list(1)
    attrs = {}
    if category:
        from catalogue_templates import TEMPLATES
        keys = [f["key"] for g in (TEMPLATES.get(category) or {}).get("groups", []) for f in g["fields"] if f["type"] in ("select", "text", "multi")
                and f["key"] in ("colour", "fabric", "pattern", "material", "occasion", "gender", "fit", "skin_type", "product_type")]
        for k in keys:
            vals = await db.products.distinct(f"attributes.{k}", match)
            vals = sorted({v for v in vals if isinstance(v, str) and v.strip()})[:30]
            if vals:
                attrs[k] = vals
    r = rows[0] if rows else {"min": None, "max": None, "brands": [], "subs": [], "n": 0}
    return {"count": r["n"], "price": {"min": r["min"], "max": r["max"]},
            "brands": sorted(b for b in r["brands"] if b)[:50], "subcategories": sorted(s for s in r["subs"] if s), "attributes": attrs}


@router.get("/catalog/suggest")
async def suggest(q: str = ""):
    """Up to 8 product names plus matching brands and categories for the search box (prefix-friendly, escaped)."""
    from pagination import text_filter
    text = (q or "").strip()[:60]
    if len(text) < 2:
        return {"products": [], "brands": [], "categories": []}
    tf = text_filter(text)
    base = _base()
    prods = await db.products.find({**base, "$or": [{"name": tf}, {"brand": tf}, {"keywords": tf}]}, {"_id": 0, "id": 1, "name": 1, "images": 1,
                                                                                                    "selling_price": 1}).limit(8).to_list(8)
    brands = sorted({b for b in await db.products.distinct("brand", {**base, "brand": tf}) if b})[:5]
    from catalogue import PILLARS
    cats = [c for c in PILLARS if text.lower() in c.lower()]
    return {"products": [{"id": p["id"], "name": p["name"], "image": (p.get("images") or [None])[0], "price": p.get("selling_price")} for p in prods],
            "brands": brands, "categories": cats}


@router.get("/catalog/products/{product_id}/related")
async def related(product_id: str, limit: int = 8):
    """Products on sale from the same sub-category (then category), in stock first, excluding the product itself."""
    from shop_routes import P_SHOP
    limit = min(max(limit, 1), 12)
    p = await db.products.find_one({"id": product_id}, {"_id": 0, "category": 1, "subcategory": 1})
    if not p:
        raise HTTPException(status_code=404, detail="Product not found.")
    out, seen = [], {product_id}
    for flt in ([{"subcategory": p.get("subcategory")}] if p.get("subcategory") else []) + [{"category": p.get("category")}]:
        rows = await db.products.find({**_base(), **flt, "id": {"$nin": list(seen)}}, P_SHOP).sort([("stock", -1), ("created_at", -1)]) \
            .limit(limit - len(out)).to_list(limit)
        for r in rows:
            seen.add(r["id"])
            out.append(r)
        if len(out) >= limit:
            break
    return {"items": out}


@router.get("/catalog/products")
async def by_ids(ids: str = ""):
    """Products on sale by id, in the order given (e.g. a shopper's recently viewed list kept in their own browser). Max 20."""
    from shop_routes import P_SHOP
    wanted = [x for x in (ids or "").split(",") if x.strip()][:20]
    rows = {r["id"]: r for r in await db.products.find({**_base(), "id": {"$in": wanted}}, P_SHOP).to_list(20)}
    return {"items": [rows[i] for i in wanted if i in rows]}
