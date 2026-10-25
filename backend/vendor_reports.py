"""Vendor reports: the Current Report (sales, earnings, settlements, product and inventory, CSV) and Advancement (growth against
the previous period, KPIs, repeat customers, stock alerts, suggestions).

Sales numbers come from the same function as /api/vendor/dashboard, so every screen agrees on the definitions. Everything else
is a MongoDB aggregation over this vendor's own order lines, products and ledger entries. Money is integer paise.
Repeat-customer figures are counts only: buyer ids never leave the server.
"""
import csv
import io
from datetime import datetime, timedelta
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
    sales, rev, ref, adj, com = n(L.SALE), n(L.SALE_REVERSAL), n(L.REFUND), n(L.ADJUSTMENT), n(L.COMMISSION)
    return {"sales_paise": sales, "reversals_paise": rev, "refunds_paise": ref, "adjustments_paise": adj, "commissions_paise": com,
            "net_paise": sales + rev + ref + adj + com, "settled_paise": -n(L.SETTLEMENT_PAID), "refund_count": by.get(L.REFUND, {}).get("c", 0)}


async def _dispatch_performance(vid: str, f, t) -> dict:
    """Hours from payment (online) or order (COD) to the dispatch event, for orders placed in the period. Null when none measured."""
    rows = await db.orders.find(_window(vid, f, t), {"_id": 0, "paid_at": 1, "created_at": 1, "payment_method": 1, "fulfilments": 1}).to_list(5000)
    hours, dispatched = [], 0
    for o in rows:
        fl = next((x for x in o.get("fulfilments") or [] if x["vendor_id"] == vid), None)
        disp = next((e.get("at") for e in (fl or {}).get("events", []) if e.get("status") == "dispatched"), None)
        if not disp:
            continue
        dispatched += 1
        base = o.get("paid_at") if o.get("payment_method") == "online" else o.get("created_at")
        try:
            hours.append((datetime.fromisoformat(disp) - datetime.fromisoformat(base)).total_seconds() / 3600)
        except (TypeError, ValueError):
            pass
    return {"dispatched_orders": dispatched, "measured_orders": len(hours),
            "average_hours_to_dispatch": round(sum(hours) / len(hours), 1) if hours else None, "capped_at": 5000 if len(rows) >= 5000 else None}


async def _stock_movement_report(vid: str, f, t) -> dict:
    """Every stock change on this vendor's products in the period (adjustments, newest first, capped for display)."""
    products = {p["id"]: p for p in await db.products.find({"vendor_id": vid}, {"_id": 0, "id": 1, "name": 1, "sku": 1}).to_list(5000)}
    q = {"product_id": {"$in": list(products)}, "created_at": {"$gte": f.isoformat(), "$lte": f"{t.isoformat()}T23:59:59.999999"}}
    total = await db.stock_movements.count_documents(q)
    moves = await db.stock_movements.aggregate([{"$match": q}, {"$group": {"_id": None,
        "added": {"$sum": {"$cond": [{"$gt": ["$delta", 0]}, "$delta", 0]}}, "removed": {"$sum": {"$cond": [{"$lt": ["$delta", 0]}, "$delta", 0]}}}}]).to_list(1)
    agg = moves[0] if moves else {"added": 0, "removed": 0}
    rows = await db.stock_movements.find(q, {"_id": 0, "product_id": 1, "variant_sku": 1, "delta": 1, "before": 1, "after": 1, "reason": 1, "created_at": 1}) \
        .sort("created_at", -1).to_list(200)
    return {"movements": total, "added": agg["added"], "removed": -agg["removed"],
            "rows": [{**r, "name": (products.get(r["product_id"]) or {}).get("name", ""), "sku": (products.get(r["product_id"]) or {}).get("sku", "")} for r in rows]}


async def _settlement_rows(vid: str, f, t) -> list:
    """Payouts requested in the period, with reference and dates. No internal admin identities."""
    return await db.settlements.find({"vendor_id": vid, "created_at": {"$gte": f.isoformat(), "$lte": f"{t.isoformat()}T23:59:59.999999"}},
                                     {"_id": 0, "number": 1, "amount_paise": 1, "status": 1, "reference": 1, "created_at": 1, "paid_at": 1}) \
        .sort("created_at", -1).to_list(100)


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
        "settlement_rows": await _settlement_rows(vid, f, t),
        "dispatch": await _dispatch_performance(vid, f, t),
        "stock_movements": await _stock_movement_report(vid, f, t),
        # Commission is shown only when an approved commercial agreement exists for this vendor; otherwise it is not applicable.
        "commission": {"available": await db.vendor_agreements.count_documents({"vendor_id": vid, "status": "approved"}) > 0,
                       "paise": (await _ledger_in_period(vid, f, t))["commissions_paise"]},
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
    w.writerow(["commission_inr", inr(-e["commissions_paise"]) if r["commission"]["available"] else "not applicable (no approved agreement)"])
    w.writerow(["commission_applies", "yes" if r["commission"]["available"] else "no"])
    w.writerow(["dispatched_orders", r["dispatch"]["dispatched_orders"]])
    w.writerow(["average_hours_to_dispatch", r["dispatch"]["average_hours_to_dispatch"] if r["dispatch"]["average_hours_to_dispatch"] is not None else "no data"])
    w.writerow(["stock_movements", r["stock_movements"]["movements"]])
    w.writerow(["stock_added", r["stock_movements"]["added"]])
    w.writerow(["stock_removed", r["stock_movements"]["removed"]])
    w.writerow([])
    w.writerow(["product", "sku", "category", "units_sold", "value_inr", "stock", "listed", "approval"])
    for p in r["products"]:
        w.writerow([_csv_safe(p["name"]), _csv_safe(p["sku"]), _csv_safe(p["category"]), p["units_sold"], inr(p["value_paise"]),
                    p["stock"], "yes" if p["is_active"] else "no", _csv_safe(p["approval_status"] or "")])
    w.writerow([])
    w.writerow(["settlement", "amount_inr", "status", "reference", "requested_at", "paid_at"])
    for st in r["settlement_rows"]:
        w.writerow([_csv_safe(st["number"]), inr(st["amount_paise"]), st["status"], _csv_safe(st.get("reference") or ""), st["created_at"], st.get("paid_at") or ""])
    w.writerow([])
    w.writerow(["stock_date", "product", "sku", "change", "before", "after", "reason"])
    for m in r["stock_movements"]["rows"]:
        w.writerow([m["created_at"], _csv_safe(m["name"]), _csv_safe(m["sku"]), m["delta"], m["before"], m["after"], _csv_safe(m["reason"])])
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
        # No source exists for these yet, so they are reported as unavailable rather than estimated.
        "ratings": {"available": False, "reason": "HomeGenie does not collect customer ratings yet."},
        "milestones": {"available": False, "reason": "No training or operational milestone records exist yet."},
    }
