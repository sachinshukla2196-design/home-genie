"""Vendor reports: the Current Report (sales, earnings, settlements, product and inventory, CSV) and Advancement (growth against
the previous period, KPIs, repeat customers, stock alerts, suggestions).

Sales numbers come from the same function as /api/vendor/dashboard, so every screen agrees on the definitions. Everything else
is a MongoDB aggregation over this vendor's own order lines, products and ledger entries. Money is integer paise.
Repeat-customer figures are counts only: buyer ids never leave the server.
"""
import csv
import io
from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

import ledger as L
from core import db
from finance_routes import _csv_safe
from money import paise_to_float
from vendor_dashboard import EXCLUDED, _line_paise, _range_bounds, vendor_dashboard as _dashboard
from vendor_routes import LOW_STOCK, _orders_base, require_approved_vendor

router = APIRouter(prefix="/api", tags=["vendor"])

MIN_SAMPLE = 10          # rate-based suggestions need at least this many orders (Analytics shows the same small-sample note)
RATE_HIGH_PCT = 10       # cancellation / return rate that triggers a suggestion
REPEAT_LOW_PCT = 20      # share of buyers who ordered twice in the period
GROWTH_TARGET_PCT = 10   # next-period target = previous period + this much (derived, not a goal the vendor typed in)


def _pct(part: int, whole: int) -> Optional[float]:
    return round(part / whole * 100, 1) if whole else None


def _change(now: int, before: int) -> Optional[float]:
    return round((now - before) / before * 100, 1) if before else None


def _window(vid: str, f, t) -> dict:
    return {**_orders_base(vid), "created_at": {"$gte": f.isoformat(), "$lte": f"{t.isoformat()}T23:59:59.999999"}}


def _vendor_status_stage(vid: str) -> dict:
    return {"$addFields": {"f": {"$first": {"$filter": {"input": "$fulfilments", "as": "x", "cond": {"$eq": ["$$x.vendor_id", vid]}}}}}}


async def _product_report(vid: str, f, t) -> list:
    """One row per product of this vendor (archived products only if they sold in the period). Units/value follow the dashboard's best-seller rule."""
    sold = {r["_id"]: r for r in await db.orders.aggregate([
        {"$match": _window(vid, f, t)}, _vendor_status_stage(vid),
        {"$match": {"f.status": {"$nin": EXCLUDED}}}, {"$unwind": "$items"}, {"$match": {"items.vendor_id": vid}},
        {"$group": {"_id": "$items.product_id", "units": {"$sum": "$items.quantity"}, "p": {"$sum": _line_paise("$items")}}},
    ]).to_list(5000)}
    prods = await db.products.find({"vendor_id": vid, "$or": [{"archived": {"$ne": True}}, {"id": {"$in": list(sold)}}]},
                                   {"_id": 0, "id": 1, "name": 1, "sku": 1, "category": 1, "stock": 1, "low_stock_threshold": 1,
                                    "is_active": 1, "approval_status": 1, "archived": 1}).to_list(5000)
    rows = []
    for p in prods:
        s = sold.get(p["id"], {})
        stock = p.get("stock") or 0
        thr = p.get("low_stock_threshold") if p.get("low_stock_threshold") is not None else LOW_STOCK
        rows.append({"product_id": p["id"], "name": p.get("name") or "", "sku": p.get("sku") or "", "category": p.get("category") or "",
                     "units_sold": s.get("units", 0), "value_paise": s.get("p", 0), "value": paise_to_float(s.get("p", 0)),
                     "stock": stock, "low_stock": 0 < stock <= thr, "out_of_stock": stock <= 0,
                     "is_active": bool(p.get("is_active")), "approval_status": p.get("approval_status"), "archived": bool(p.get("archived"))})
    rows.sort(key=lambda r: (-r["value_paise"], -r["units_sold"], r["name"].lower()))
    return rows


async def _ledger_in_period(vid: str, f, t) -> dict:
    """Ledger entries POSTED in the period (not the orders placed in it). Provisional: before commissions and deductions."""
    rows = await db.vendor_ledger.aggregate([
        {"$match": {"vendor_id": vid, "posted_at": {"$gte": f.isoformat(), "$lte": f"{t.isoformat()}T23:59:59.999999"}}},
        {"$group": {"_id": "$type", "n": {"$sum": "$amount_paise"}, "c": {"$sum": 1}}},
    ]).to_list(20)
    by = {r["_id"]: r for r in rows}
    n = lambda k: by.get(k, {}).get("n", 0)
    sales, rev, ref, adj = n(L.SALE), n(L.SALE_REVERSAL), n(L.REFUND), n(L.ADJUSTMENT)
    return {"sales_paise": sales, "reversals_paise": rev, "refunds_paise": ref, "adjustments_paise": adj,
            "net_paise": sales + rev + ref + adj, "settled_paise": -n(L.SETTLEMENT_PAID), "refund_count": by.get(L.REFUND, {}).get("c", 0)}


async def _settlements_in_period(vid: str, f, t) -> dict:
    rows = await db.settlements.aggregate([
        {"$match": {"vendor_id": vid, "created_at": {"$gte": f.isoformat(), "$lte": f"{t.isoformat()}T23:59:59.999999"}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}, "p": {"$sum": "$amount_paise"}}},
    ]).to_list(20)
    bal = await L.balances(vid)
    return {"by_status": {r["_id"]: {"count": r["n"], "amount_paise": r["p"]} for r in rows},
            "pending_paise": bal["pending_settlement_paise"], "in_progress_paise": bal["settlement_in_progress_paise"],
            "available_paise": bal["available_for_settlement_paise"]}


async def _current(user: dict, range: str, date_from: Optional[str], date_to: Optional[str]) -> dict:
    vid = user["_vendor"]["id"]
    d = await _dashboard(range=range, date_from=date_from, date_to=date_to, user=user)
    f, t = _range_bounds(range, date_from, date_to)
    return {
        "range": d["range"],
        "sales": d["sales"],
        "orders_by_status": d["orders_by_status"],
        "cancellation_return": d["cancellation_return"],
        "best_sellers": d["best_sellers"],
        "earnings": await _ledger_in_period(vid, f, t),
        "settlements": await _settlements_in_period(vid, f, t),
        # HomeGenie's platform commission is not recorded on the vendor ledger yet (the settlement policy is not approved).
        "commission": {"available": False},
        "products": await _product_report(vid, f, t),
    }


@router.get("/vendor/reports/current")
async def vendor_current_report(range: str = "30d", date_from: Optional[str] = None, date_to: Optional[str] = None,
                                user: dict = Depends(require_approved_vendor)):
    return await _current(user, range, date_from, date_to)


@router.get("/vendor/reports/current.csv")
async def vendor_current_csv(range: str = "30d", date_from: Optional[str] = None, date_to: Optional[str] = None,
                             user: dict = Depends(require_approved_vendor)):
    r = await _current(user, range, date_from, date_to)
    s, e = r["sales"], r["earnings"]
    inr = lambda p: f"{paise_to_float(p):.2f}"
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["period", f"{r['range']['from']} to {r['range']['to']}"])
    w.writerow([])
    w.writerow(["metric", "value"])
    w.writerow(["orders", s["orders"]])
    w.writerow(["order_value_inr", inr(s["order_value_paise"])])
    w.writerow(["collected_inr", inr(s["collected_paise"])])
    w.writerow(["cod_awaiting_collection_inr", inr(s["cod_awaiting_paise"])])
    w.writerow(["awaiting_confirmation_inr", inr(s["awaiting_confirmation_paise"])])
    w.writerow(["under_review_inr", inr(s["under_review_paise"])])
    w.writerow(["cancelled_or_rejected_orders", r["cancellation_return"]["cancelled_or_rejected"]])
    w.writerow(["returned_or_failed_orders", r["cancellation_return"]["returned_or_failed"]])
    w.writerow(["sales_posted_inr", inr(e["sales_paise"])])
    w.writerow(["reversals_inr", inr(e["reversals_paise"])])
    w.writerow(["refunds_inr", inr(e["refunds_paise"])])
    w.writerow(["refund_entries", e["refund_count"]])
    w.writerow(["adjustments_inr", inr(e["adjustments_paise"])])
    w.writerow(["net_before_settlements_inr", inr(e["net_paise"])])
    w.writerow(["settled_in_period_inr", inr(e["settled_paise"])])
    w.writerow(["platform_commission", "not recorded"])
    w.writerow([])
    w.writerow(["product", "sku", "category", "units_sold", "value_inr", "stock", "listed", "approval"])
    for p in r["products"]:
        w.writerow([_csv_safe(p["name"]), _csv_safe(p["sku"]), _csv_safe(p["category"]), p["units_sold"], inr(p["value_paise"]),
                    p["stock"], "yes" if p["is_active"] else "no", _csv_safe(p["approval_status"] or "")])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=vendor-current-report.csv"})


async def _repeat(vid: str, f, t) -> dict:
    """Buyers who ordered in the period (counted, never identified) and how many of them ordered at least twice in it."""
    res = await db.orders.aggregate([
        {"$match": {**_window(vid, f, t), "user_id": {"$ne": None}}}, _vendor_status_stage(vid),
        {"$match": {"f.status": {"$nin": EXCLUDED}}},
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}},
        {"$group": {"_id": None, "buyers": {"$sum": 1}, "repeat": {"$sum": {"$cond": [{"$gte": ["$n", 2]}, 1, 0]}}}},
    ]).to_list(1)
    buyers, repeat = (res[0]["buyers"], res[0]["repeat"]) if res else (0, 0)
    return {"buyers": buyers, "repeat": repeat, "repeat_rate": _pct(repeat, buyers)}


@router.get("/vendor/reports/advancement")
async def vendor_advancement(range: str = "30d", date_from: Optional[str] = None, date_to: Optional[str] = None,
                             user: dict = Depends(require_approved_vendor)):
    vid = user["_vendor"]["id"]
    d = await _dashboard(range=range, date_from=date_from, date_to=date_to, user=user)
    f, t = _range_bounds(range, date_from, date_to)
    prev_t = f - timedelta(days=1)
    prev_f = prev_t - timedelta(days=(t - f).days)              # same length, directly before the selected period
    prev = await _dashboard(range="custom", date_from=prev_f.isoformat(), date_to=prev_t.isoformat(), user=user)

    n = d["sales"]["orders"]
    value, prev_value = d["sales"]["order_value_paise"], prev["sales"]["order_value_paise"]
    prev_n = prev["sales"]["orders"]
    cancelled, returned = d["cancellation_return"]["cancelled_or_rejected"], d["cancellation_return"]["returned_or_failed"]
    value_change, orders_change = _change(value, prev_value), _change(n, prev_n)
    repeat = await _repeat(vid, f, t)
    cancel_pct, return_pct = _pct(cancelled, n), _pct(returned, n)
    stock = d["products"]

    # best sellers in the period that are low or out of stock right now
    best_ids = [b["product_id"] for b in d["best_sellers"]]
    best_low = await db.products.count_documents({"vendor_id": vid, "id": {"$in": best_ids}, "$expr": {"$lte": ["$stock", {"$ifNull": ["$low_stock_threshold", LOW_STOCK]}]}})

    sugg = []
    def add(key: str, link: str, **params):
        sugg.append({"key": key, "link": link, "params": params})
    if n == 0:
        add("no_orders", "/vendor/products")
    if value_change is not None and value_change <= -GROWTH_TARGET_PCT:
        add("sales_down", "/vendor/analytics", change=value_change)
    if value_change is not None and value_change >= GROWTH_TARGET_PCT:
        add("sales_up", "/vendor/products?stock=low", change=value_change)
    if best_low:
        add("restock_best", "/vendor/products?stock=low", count=best_low)
    if stock["out_of_stock"]:
        add("out_of_stock", "/vendor/products?stock=out", count=stock["out_of_stock"])
    if stock["low_stock"]:
        add("low_stock", "/vendor/products?stock=low", count=stock["low_stock"])
    if n >= MIN_SAMPLE and cancel_pct is not None and cancel_pct >= RATE_HIGH_PCT:
        add("cancel_high", "/vendor/orders", pct=cancel_pct)
    if n >= MIN_SAMPLE and return_pct is not None and return_pct >= RATE_HIGH_PCT:
        add("return_high", "/vendor/returns", pct=return_pct)
    if repeat["buyers"] >= MIN_SAMPLE and repeat["repeat_rate"] is not None and repeat["repeat_rate"] < REPEAT_LOW_PCT:
        add("repeat_low", "/vendor/products", pct=repeat["repeat_rate"])

    return {
        "range": d["range"],
        "previous": {"from": prev_f.isoformat(), "to": prev_t.isoformat()},
        "growth": {
            "orders": {"current": n, "previous": prev_n, "change_pct": orders_change},
            "order_value_paise": {"current": value, "previous": prev_value, "change_pct": value_change},
            "target_pct": GROWTH_TARGET_PCT,
            "target_order_value_paise": round(prev_value * (100 + GROWTH_TARGET_PCT) / 100),
        },
        "trend": d["trend"],
        "kpis": {"orders": n, "small_sample": n < MIN_SAMPLE, "cancellation_rate": cancel_pct, "return_rate": return_pct,
                 "delivered_rate": _pct(d["orders_by_status"].get("delivered", 0), n - cancelled),
                 "average_order_value_paise": round(value / n) if n else None},
        "repeat_customers": repeat,
        "stock": {"low_stock": stock["low_stock"], "out_of_stock": stock["out_of_stock"], "items": d["inventory_alerts"]},
        "suggestions": sugg,
    }
