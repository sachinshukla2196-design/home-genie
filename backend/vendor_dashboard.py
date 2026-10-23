"""Vendor command-centre dashboard: every number is computed by the database (aggregation), never by loading orders in Python.

Definitions (also shown to vendors in the UI):
- order_value   : value of the vendor's own lines on orders PLACED in the selected range, excluding lines the vendor rejected /
                  cancelled and fully refunded orders. It is NOT revenue.
- collected     : the part of order_value whose payment is confirmed (online payment captured or COD cash confirmed).
- cod_awaiting_collection : COD orders whose cash is not confirmed yet.  awaiting_confirmation : UPI claimed, not yet verified.
- under_review  : partially refunded orders or any payment state not classified above.
  order_value = collected + cod_awaiting_collection + awaiting_confirmation + under_review.
Settlement figures come from the vendor ledger (see ledger.py) and are provisional until the settlement policy is approved.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

import ledger as L
from core import db, P_PUBLIC
from money import paise_to_float
from pagination import date_range
from vendor_routes import require_approved_vendor, _orders_base, _vendor_view, _public_vendor, LOW_STOCK

router = APIRouter(prefix="/api", tags=["vendor"])

EXCLUDED = ["rejected", "cancelled"]
RANGES = ("today", "7d", "30d", "month", "custom")


def _range_bounds(rng: str, date_from: Optional[str], date_to: Optional[str]):
    today = datetime.now(timezone.utc).date()
    if rng == "today":
        f, t = today, today
    elif rng == "7d":
        f, t = today - timedelta(days=6), today
    elif rng == "30d":
        f, t = today - timedelta(days=29), today
    elif rng == "month":
        f, t = today.replace(day=1), today
    else:
        try:
            dr = date_range(date_from, date_to)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"{e} must be a date like 2026-10-23.")
        if not dr:
            raise HTTPException(status_code=400, detail="Choose a start and end date.")
        f = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else today - timedelta(days=29)
        t = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
        if f > t or (t - f).days > 366:
            raise HTTPException(status_code=400, detail="The date range must be at most one year and start before it ends.")
    return f, t


def _line_paise(prefix: str = "$$l"):
    """Paise value of one order line: the exact paise field, or (for un-migrated legacy lines) the rupee float x 100."""
    return {"$ifNull": [f"{prefix}.total_paise", {"$toLong": {"$round": [{"$multiply": [f"{prefix}.total", 100]}, 0]}}]}


@router.get("/vendor/dashboard")
async def vendor_dashboard(range: str = "month", date_from: Optional[str] = None, date_to: Optional[str] = None,
                           user: dict = Depends(require_approved_vendor)):
    if range not in RANGES:
        raise HTTPException(status_code=400, detail="range must be one of: " + ", ".join(RANGES))
    v = user["_vendor"]
    vid = v["id"]
    f, t = _range_bounds(range, date_from, date_to)
    window = {**_orders_base(vid), "created_at": {"$gte": f.isoformat(), "$lte": f"{t.isoformat()}T23:59:59.999999"}}
    common = [
        {"$addFields": {"f": {"$first": {"$filter": {"input": "$fulfilments", "as": "x", "cond": {"$eq": ["$$x.vendor_id", vid]}}}},
                        "vlines": {"$filter": {"input": "$items", "as": "l", "cond": {"$eq": ["$$l.vendor_id", vid]}}}}},
        {"$addFields": {"vtotal": {"$sum": {"$map": {"input": "$vlines", "as": "l", "in": _line_paise()}}}}},
    ]
    live = {"f.status": {"$nin": EXCLUDED}, "payment_status": {"$ne": "refunded"}}
    facet = {
        "money": [{"$match": live}, {"$group": {"_id": "$payment_status", "p": {"$sum": "$vtotal"}, "n": {"$sum": 1}}}],
        "trend": [{"$match": {"f.status": {"$nin": EXCLUDED}}},
                  {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}, "p": {"$sum": "$vtotal"}, "n": {"$sum": 1}}}, {"$sort": {"_id": 1}}],
        "by_status": [{"$group": {"_id": "$f.status", "n": {"$sum": 1}}}],
        "by_payment": [{"$group": {"_id": "$payment_method", "n": {"$sum": 1}}}],
        "best": [{"$match": {"f.status": {"$nin": EXCLUDED}}}, {"$unwind": "$vlines"},
                 {"$group": {"_id": "$vlines.product_id", "name": {"$first": "$vlines.name"}, "sku": {"$first": "$vlines.sku"},
                             "qty": {"$sum": "$vlines.quantity"}, "p": {"$sum": _line_paise("$vlines")}}},
                 {"$sort": {"p": -1}}, {"$limit": 5}],
        "cats": [{"$match": {"f.status": {"$nin": EXCLUDED}}}, {"$unwind": "$vlines"},
                 {"$lookup": {"from": "products", "localField": "vlines.product_id", "foreignField": "id", "as": "pr", "pipeline": [{"$project": {"category": 1, "_id": 0}}]}},
                 {"$group": {"_id": {"$first": "$pr.category"}, "p": {"$sum": _line_paise("$vlines")}, "qty": {"$sum": "$vlines.quantity"}}}, {"$sort": {"p": -1}}],
        "delivered": [{"$match": {"f.status": "delivered"}}, {"$count": "n"}],
        "returned": [{"$match": {"f.status": {"$in": ["returned_to_origin", "delivery_failed"]}}}, {"$count": "n"}],
        "cancelled": [{"$match": {"f.status": {"$in": EXCLUDED}}}, {"$count": "n"}],
    }
    res = (await db.orders.aggregate([{"$match": window}, *common, {"$facet": facet}]).to_list(1))[0]

    money = {r["_id"]: r["p"] for r in res["money"]}
    collected = money.get("paid", 0)
    cod_wait = money.get("cod_pending", 0)
    awaiting = money.get("claimed", 0)
    review = sum(p for k, p in money.items() if k not in ("paid", "cod_pending", "claimed"))
    order_value = collected + cod_wait + awaiting + review
    n_orders = sum(r["n"] for r in res["by_status"])

    # all-time work queue (what needs doing now, regardless of the selected range)
    q_all = await db.orders.aggregate([{"$match": _orders_base(vid)}, {"$addFields": {"f": {"$first": {"$filter": {"input": "$fulfilments", "as": "x", "cond": {"$eq": ["$$x.vendor_id", vid]}}}}}},
                                       {"$group": {"_id": "$f.status", "n": {"$sum": 1}}}]).to_list(20)
    by = {r["_id"]: r["n"] for r in q_all}
    awaiting_insp = await db.orders.count_documents({**_orders_base(vid), "fulfilments": {"$elemMatch": {
        "vendor_id": vid, "status": "returned_to_origin", "return_inspection": {"$exists": False}}}})
    today_iso = datetime.now(timezone.utc).date().isoformat()
    today_orders = await db.orders.count_documents({**_orders_base(vid), "created_at": {"$gte": today_iso}})

    # trend: one point per day in the range (zeros are real zeros, not invented data)
    by_day = {r["_id"]: r for r in res["trend"]}
    days, d = [], f
    while d <= t:
        row = by_day.get(d.isoformat())
        days.append({"date": d.isoformat(), "orders": row["n"] if row else 0, "value_paise": row["p"] if row else 0,
                     "value": paise_to_float(row["p"]) if row else 0.0})
        d += timedelta(days=1)

    # best sellers + their pillar (one small lookup for the top 5 only)
    best_ids = [b["_id"] for b in res["best"]]
    cats = {p["id"]: p.get("category") for p in await db.products.find({"id": {"$in": best_ids}}, {"_id": 0, "id": 1, "category": 1}).to_list(10)}
    best = [{"product_id": b["_id"], "name": b["name"], "sku": b.get("sku"), "quantity": b["qty"], "value_paise": b["p"],
             "value": paise_to_float(b["p"]), "category": cats.get(b["_id"])} for b in res["best"]]

    # inventory
    mine = {"vendor_id": vid, "archived": {"$ne": True}}
    low_expr = {"$expr": {"$and": [{"$gt": ["$stock", 0]}, {"$lte": ["$stock", {"$ifNull": ["$low_stock_threshold", LOW_STOCK]}]}]}}
    n_low = await db.products.count_documents({**mine, **low_expr})
    n_out = await db.products.count_documents({**mine, "stock": {"$lte": 0}})
    n_total = await db.products.count_documents(mine)
    n_live = await db.products.count_documents({**mine, "is_active": True, "approval_status": "approved"})
    n_pending = await db.products.count_documents({**mine, "approval_status": "pending"})
    n_rejected = await db.products.count_documents({**mine, "approval_status": "rejected"})
    alerts = await db.products.find({**mine, "$or": [low_expr, {"stock": {"$lte": 0}}]},
                                    {"_id": 0, "id": 1, "name": 1, "sku": 1, "stock": 1, "low_stock_threshold": 1}).sort("stock", 1).limit(8).to_list(8)

    # returns, finance
    rc = {r["_id"]: r["n"] async for r in db.return_cases.aggregate([{"$match": {"vendor_id": vid}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}])}
    bal = await L.balances(vid)
    from finance_routes import _cod_summary, get_policy
    policy = await get_policy()
    cod = await _cod_summary(vid, policy)

    action = []
    def add(key, priority, count, link):
        if count:
            action.append({"key": key, "priority": priority, "count": count, "link": link})
    add("new_orders", "high", by.get("new", 0), "/vendor/orders?status=new")
    add("delivery_exceptions", "high", by.get("delivery_failed", 0), "/vendor/orders?status=delivery_failed")
    add("return_requests", "high", rc.get("requested", 0), "/vendor/returns?status=requested")
    add("returns_to_inspect", "high", rc.get("received", 0) + awaiting_insp, "/vendor/returns?status=received")
    add("replacements_due", "high", rc.get("replacement_due", 0), "/vendor/returns?status=replacement_due")
    add("rejected_products", "high", n_rejected, "/vendor/products?approval=rejected")
    add("to_dispatch", "medium", by.get("accepted", 0) + by.get("packed", 0), "/vendor/orders?status=packed")
    add("out_of_stock", "medium", n_out, "/vendor/products?stock=out")
    add("low_stock", "medium", n_low, "/vendor/products?stock=low")
    add("cod_overdue", "medium", 1 if cod["overdue_paise"] else 0, "/vendor/cod")
    add("cod_discrepancy", "medium", 1 if cod["discrepancy_paise"] else 0, "/vendor/cod")
    add("products_in_review", "low", n_pending, "/vendor/products?approval=pending")

    recent_rows = await db.orders.find(_orders_base(vid), {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)
    recent = [x for x in (_vendor_view(o, vid) for o in recent_rows) if x]
    return {
        "vendor": _public_vendor(v),
        "range": {"key": range, "from": f.isoformat(), "to": t.isoformat()},
        "today": {"orders": today_orders},
        "queue": {"new": by.get("new", 0), "to_pack": by.get("accepted", 0), "to_dispatch": by.get("packed", 0),
                  "in_transit": by.get("dispatched", 0), "exceptions": by.get("delivery_failed", 0),
                  "delivered": by.get("delivered", 0), "awaiting_return_inspection": awaiting_insp},
        "products": {"total": n_total, "live": n_live, "pending_review": n_pending, "rejected": n_rejected,
                     "low_stock": n_low, "out_of_stock": n_out},
        "sales": {"orders": n_orders, "delivered": by.get("delivered", 0), "currency": "INR",
                  "order_value_this_month": paise_to_float(order_value), "collected_this_month": paise_to_float(collected),
                  "cod_awaiting_collection": paise_to_float(cod_wait), "awaiting_confirmation": paise_to_float(awaiting),
                  "under_review": paise_to_float(review), "gross_this_month": paise_to_float(order_value),   # deprecated aliases
                  "order_value": paise_to_float(order_value), "collected": paise_to_float(collected),
                  "order_value_paise": order_value, "collected_paise": collected, "cod_awaiting_paise": cod_wait,
                  "awaiting_confirmation_paise": awaiting, "under_review_paise": review},
        "orders_by_status": {r["_id"]: r["n"] for r in res["by_status"]},
        "orders_by_payment_method": {r["_id"]: r["n"] for r in res["by_payment"]},
        "cancellation_return": {"cancelled_or_rejected": (res["cancelled"] or [{"n": 0}])[0]["n"],
                                "returned_or_failed": (res["returned"] or [{"n": 0}])[0]["n"], "orders": n_orders},
        "trend": days,
        "best_sellers": best,
        "category_performance": [{"category": r["_id"], "value_paise": r["p"], "value": paise_to_float(r["p"]), "units": r["qty"]} for r in res["cats"] if r["_id"]],
        "inventory_alerts": alerts,
        "returns": {"requested": rc.get("requested", 0), "contested": rc.get("contested", 0),
                    "awaiting_receipt": rc.get("approved", 0) + rc.get("in_transit", 0), "to_inspect": rc.get("received", 0),
                    "replacements_due": rc.get("replacement_due", 0), "refund_pending": rc.get("refund_pending", 0)},
        "finance": {"payable_paise": bal["vendor_payable_paise"], "pending_settlement_paise": bal["pending_settlement_paise"],
                    "settled_paise": bal["settled_paise"], "provisional": True, "policy_active": policy["active"],
                    "pending_settlement": paise_to_float(bal["pending_settlement_paise"]), "settled": paise_to_float(bal["settled_paise"])},
        "cod": cod,
        "action_centre": action,
        "recent": recent,
    }
