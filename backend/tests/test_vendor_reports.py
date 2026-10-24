"""Vendor Current Report + Advancement: date filters, calculations, vendor isolation and CSV export.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/test_vendor_reports.py -n 0`).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_reports_test", "JWT_SECRET": "vendor-reports-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _iso(days_ago):
    """Noon UTC, `days_ago` days back: always inside the day's date window, never on a boundary."""
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()


def _today():
    return datetime.now(timezone.utc).date()


def _product(pid, vid, name, sku, stock, threshold=5, category="Sarees", **kw):
    return {"id": pid, "vendor_id": vid, "name": name, "sku": sku, "category": category, "stock": stock, "low_stock_threshold": threshold,
            "is_active": True, "approval_status": "approved", "archived": False, "created_at": now_iso(), "updated_at": now_iso(), **kw}


def _order(vid, lines, *, status="delivered", days_ago=1, user=None, payment="paid", extra_vendor=None):
    """lines: (product_id, name, sku, line_vendor_id, qty, total_paise). `extra_vendor` adds a second vendor's fulfilment (mixed order)."""
    items = [{"product_id": p, "name": n, "sku": s, "vendor_id": lv, "quantity": q, "total_paise": tp, "total": tp / 100} for p, n, s, lv, q, tp in lines]
    fulfil = [{"vendor_id": vid, "status": status, "events": []}]
    if extra_vendor:
        fulfil.append({"vendor_id": extra_vendor, "status": status, "events": []})
    total = sum(i["total_paise"] for i in items)
    return {"id": new_id(), "order_number": "HG" + new_id()[:8].upper(), "user_id": user, "payment_method": "online",
            "payment_status": payment, "status": status, "created_at": _iso(days_ago), "paid_at": _iso(days_ago),
            "total_paise": total, "total": total / 100, "items": items, "fulfilments": fulfil, "address": ADDR, "needs_refund": False}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()

            async def user(mobile, role, did, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name, status="approved"):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": name, "status": status,
                     "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            S["cust"] = await user("9100000901", "distributor", "HGC", "red")
            S["ua"], S["ub"], S["uc"] = (await user("9100000902", "vendor", "VRA"), await user("9100000903", "vendor", "VRB"),
                                         await user("9100000904", "vendor", "VRC"))
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A Reports"), await vendor(S["ub"], "Vendor B Reports")
            await vendor(S["uc"], "Pending Vendor", status="submitted")
            S["buyer1"], S["buyer2"], S["buyer3"], S["buyer4"] = [new_id() for _ in range(4)]
            A, B = S["va"]["id"], S["vb"]["id"]
            S["pA1"], S["pA2"], S["pA3"], S["pA5"], S["pB1"] = new_id(), new_id(), new_id(), new_id(), new_id()
            await db.products.insert_many([
                _product(S["pA1"], A, "Silk Saree", "A-1", 2),                 # low stock (2 <= 5)
                _product(S["pA2"], A, "Cotton Kurta", "A-2", 0),               # out of stock
                _product(S["pA3"], A, "Dupatta", "A-3", 50),                   # healthy, no sales
                _product(S["pA5"], A, "=2+3 Promo", "A-5", 10),                # formula-looking name: must be escaped in CSV
                _product(S["pB1"], B, "Vendor B Item", "B-1", 1),              # belongs to vendor B
            ])
            S["oA"] = {"pA1": S["pA1"]}
            orders = [
                _order(A, [(S["pA1"], "Silk Saree", "A-1", A, 2, 200000)], days_ago=1, user=S["buyer1"]),
                _order(A, [(S["pA2"], "Cotton Kurta", "A-2", A, 1, 50000)], days_ago=2, user=S["buyer1"]),
                _order(A, [(S["pA1"], "Silk Saree", "A-1", A, 1, 100000)], status="cancelled", days_ago=3, user=S["buyer2"]),
                _order(A, [(S["pA1"], "Silk Saree", "A-1", A, 1, 100000)], status="returned_to_origin", days_ago=4, user=S["buyer3"]),
                # mixed order: vendor A sells 300 INR of it, vendor B sells 700 INR
                _order(A, [(S["pA1"], "Silk Saree", "A-1", A, 1, 30000), (S["pB1"], "Vendor B Item", "B-1", B, 1, 70000)],
                       days_ago=5, user=S["buyer2"], extra_vendor=B),
                _order(A, [(S["pA1"], "Silk Saree", "A-1", A, 9, 900000)], days_ago=35, user=S["buyer4"]),   # previous period
                _order(B, [(S["pB1"], "Vendor B Item", "B-1", B, 3, 300000)], days_ago=2, user=S["buyer1"]),  # B only
            ]
            await db.orders.insert_many(orders)
            now = now_iso()
            await db.vendor_ledger.insert_many([
                {"id": new_id(), "vendor_id": A, "type": "SALE_COLLECTED", "amount_paise": 500000, "order_id": None, "source_key": "t-sale-a1",
                 "status": "posted", "posted_at": _iso(1), "created_at": now},
                {"id": new_id(), "vendor_id": A, "type": "REFUND", "amount_paise": -20000, "order_id": None, "source_key": "t-ref-a1",
                 "status": "posted", "posted_at": _iso(2), "created_at": now},
                {"id": new_id(), "vendor_id": A, "type": "SETTLEMENT_PAID", "amount_paise": -100000, "order_id": None, "source_key": "t-set-a1",
                 "status": "posted", "posted_at": _iso(1), "created_at": now},
                {"id": new_id(), "vendor_id": A, "type": "ADJUSTMENT", "amount_paise": 1000, "order_id": None, "source_key": "t-adj-a-old",
                 "status": "posted", "posted_at": _iso(40), "created_at": now},          # outside the 30d window
                {"id": new_id(), "vendor_id": B, "type": "SALE_COLLECTED", "amount_paise": 999999, "order_id": None, "source_key": "t-sale-b1",
                 "status": "posted", "posted_at": _iso(1), "created_at": now},
            ])
            await db.settlements.insert_many([
                {"id": new_id(), "number": "STL-T1", "vendor_id": A, "amount_paise": 100000, "status": "paid", "created_at": _iso(2)},
                {"id": new_id(), "number": "STL-T2", "vendor_id": A, "amount_paise": 50000, "status": "requested", "created_at": _iso(40)},
                {"id": new_id(), "number": "STL-T3", "vendor_id": B, "amount_paise": 70000, "status": "paid", "created_at": _iso(2)},
            ])
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _cur(c, who="ua", **params):
    return c.get("/api/vendor/reports/current", headers=_hdr(S[who]["id"]), params=params or {"range": "30d"})


def _adv(c, who="ua", **params):
    return c.get("/api/vendor/reports/advancement", headers=_hdr(S[who]["id"]), params=params or {"range": "30d"})


# ====================================================================== date filters
def test_bad_date_filters_are_rejected(c):
    h = _hdr(S["ua"]["id"])
    assert c.get("/api/vendor/reports/current", headers=h, params={"range": "forever"}).status_code == 400
    assert c.get("/api/vendor/reports/current", headers=h, params={"range": "custom"}).status_code == 400
    assert c.get("/api/vendor/reports/current", headers=h, params={"range": "custom", "date_from": "2026-13-01", "date_to": "2026-10-02"}).status_code == 400
    assert c.get("/api/vendor/reports/current", headers=h, params={"range": "custom", "date_from": "2026-10-05", "date_to": "2026-10-02"}).status_code == 400
    assert c.get("/api/vendor/reports/advancement", headers=h, params={"range": "custom", "date_from": "2020-01-01", "date_to": "2026-10-02"}).status_code == 400


def test_custom_range_counts_only_orders_inside_it(c):
    t = _today()
    r = _cur(c, range="custom", date_from=(t - timedelta(days=3)).isoformat(), date_to=(t - timedelta(days=2)).isoformat()).json()
    assert r["range"]["from"] == (t - timedelta(days=3)).isoformat()
    assert r["sales"]["orders"] == 2                                       # 2-day-old and 3-day-old orders only
    assert r["sales"]["order_value_paise"] == 50000                        # the 3-day-old one is cancelled, so excluded


def test_today_with_no_orders_gives_zeros_and_no_orders_suggestion(c):
    r = _adv(c, range="today").json()
    assert r["kpis"]["orders"] == 0 and r["kpis"]["average_order_value_paise"] is None
    assert r["growth"]["order_value_paise"]["previous"] == 200000                        # yesterday's order is the comparison
    keys = [s["key"] for s in r["suggestions"]]
    assert "no_orders" in keys and "sales_down" in keys


def test_current_report_matches_the_dashboard_for_the_same_range(c):
    h = _hdr(S["ua"]["id"])
    dash = c.get("/api/vendor/dashboard", headers=h, params={"range": "30d"}).json()
    rep = _cur(c).json()
    assert rep["sales"]["order_value_paise"] == dash["sales"]["order_value_paise"]
    assert rep["sales"]["orders"] == dash["sales"]["orders"]
    assert rep["orders_by_status"] == dash["orders_by_status"]


# ====================================================================== calculations
def test_current_report_sales_and_status_breakdown(c):
    r = _cur(c).json()
    s = r["sales"]
    assert s["orders"] == 5                                                # 4 vendor-A orders + the mixed one, incl. cancelled
    assert s["order_value_paise"] == 380000                                # 2000 + 500 + 1000 + 300 (cancelled 1000 excluded)
    assert r["cancellation_return"] == {"cancelled_or_rejected": 1, "returned_or_failed": 1, "orders": 5}
    assert r["orders_by_status"]["delivered"] == 3


def test_product_report_units_values_and_stock_flags(c):
    rows = {p["sku"]: p for p in _cur(c).json()["products"]}
    assert rows["A-1"]["units_sold"] == 4 and rows["A-1"]["value_paise"] == 330000   # cancelled order not counted
    assert rows["A-1"]["low_stock"] is True and rows["A-1"]["out_of_stock"] is False
    assert rows["A-2"]["units_sold"] == 1 and rows["A-2"]["out_of_stock"] is True
    assert rows["A-3"]["units_sold"] == 0 and rows["A-3"]["value_paise"] == 0           # zero-sales products still listed
    assert "B-1" not in rows                                                            # other vendor's product never appears
    assert list(rows)[0] == "A-1"                                                        # sorted by value, highest first


def test_earnings_and_settlements_are_the_ledger_posted_in_the_period(c):
    r = _cur(c).json()
    e = r["earnings"]
    assert e["sales_paise"] == 500000 and e["refunds_paise"] == -20000 and e["refund_count"] == 1
    assert e["adjustments_paise"] == 0                                                   # the 40-day-old adjustment is outside 30d
    assert e["net_paise"] == 480000 and e["settled_paise"] == 100000
    assert r["settlements"]["by_status"] == {"paid": {"count": 1, "amount_paise": 100000}}   # 40-day-old request outside the window
    assert r["commission"] == {"available": False}


def test_advancement_growth_targets_and_repeat_customers(c):
    g = _adv(c).json()["growth"]
    assert g["orders"] == {"current": 5, "previous": 1, "change_pct": 400.0}
    assert g["order_value_paise"]["current"] == 380000 and g["order_value_paise"]["previous"] == 900000
    assert g["order_value_paise"]["change_pct"] == -57.8
    assert g["target_order_value_paise"] == 990000                                      # previous period + 10%
    rep = _adv(c).json()["repeat_customers"]
    assert rep == {"buyers": 3, "repeat": 1, "repeat_rate": 33.3}                        # buyer1 ordered twice; buyer2 & buyer3 once


def test_advancement_kpis_and_stock_alert_suggestions(c):
    r = _adv(c).json()
    k = r["kpis"]
    assert k["small_sample"] is True and k["cancellation_rate"] == 20.0 and k["return_rate"] == 20.0
    assert k["delivered_rate"] == 75.0 and k["average_order_value_paise"] == 76000
    assert r["stock"]["low_stock"] == 1 and r["stock"]["out_of_stock"] == 1
    keys = {s["key"]: s for s in r["suggestions"]}
    assert {"sales_down", "restock_best", "out_of_stock", "low_stock"} <= set(keys)
    assert keys["restock_best"]["params"]["count"] == 2
    assert keys["out_of_stock"]["link"] == "/vendor/products?stock=out"
    assert "cancel_high" not in keys and "repeat_low" not in keys                         # below the minimum sample of 10


# ====================================================================== vendor isolation + access
def test_vendor_b_sees_only_its_own_numbers(c):
    rep = _cur(c, who="ub").json()
    assert rep["sales"]["order_value_paise"] == 370000                                  # 700 from the mixed order + 3000 of its own
    assert rep["earnings"]["sales_paise"] == 999999 and rep["earnings"]["refunds_paise"] == 0
    assert rep["settlements"]["by_status"] == {"paid": {"count": 1, "amount_paise": 70000}}
    assert [p["sku"] for p in rep["products"]] == ["B-1"]
    blob = str(rep)
    assert "Silk Saree" not in blob and S["buyer2"] not in blob and S["va"]["id"] not in blob


def test_advancement_never_exposes_other_vendors_or_buyer_ids(c):
    text = _adv(c, who="ub").text
    assert "Silk Saree" not in text and "Cotton Kurta" not in text
    for buyer in ("buyer1", "buyer2", "buyer3", "buyer4"):
        assert S[buyer] not in text


def test_reports_need_an_approved_vendor(c):
    assert c.get("/api/vendor/reports/current", params={"range": "30d"}).status_code in (401, 403)
    assert c.get("/api/vendor/reports/advancement", params={"range": "30d"}).status_code in (401, 403)
    assert c.get("/api/vendor/reports/current.csv", params={"range": "30d"}).status_code in (401, 403)
    assert _cur(c, who="cust").status_code == 403
    assert _cur(c, who="uc").status_code == 403                                          # vendor not approved yet
    assert _adv(c, who="uc").status_code == 403


# ====================================================================== CSV export
def test_csv_export_is_the_authenticated_vendors_report_with_formulas_escaped(c):
    r = c.get("/api/vendor/reports/current.csv", headers=_hdr(S["ua"]["id"]), params={"range": "30d"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.text
    assert "order_value_inr,3800.00" in text
    assert "sales_posted_inr,5000.00" in text and "refunds_inr,-200.00" in text
    assert "Silk Saree,A-1" in text and "'=2+3 Promo" in text                             # formula-looking cell is neutralised
    assert "Vendor B Item" not in text and "B-1" not in text


def test_csv_export_for_vendor_b_has_no_vendor_a_rows(c):
    text = c.get("/api/vendor/reports/current.csv", headers=_hdr(S["ub"]["id"]), params={"range": "30d"}).text
    assert "Vendor B Item,B-1" in text and "Silk Saree" not in text and "A-1" not in text


def test_dashboard_sales_for_today_week_and_month_use_live_order_value(c):
    h = lambda who: _hdr(S[who]["id"])
    a = c.get("/api/vendor/dashboard", headers=h("ua"), params={"range": "30d"}).json()["sales_periods"]
    assert a["today"]["value_paise"] == 0                                              # no seeded order is from today
    assert a["week"]["value_paise"] == 380000                                          # 1, 2, 4 and 5 days ago; cancelled excluded
    b = c.get("/api/vendor/dashboard", headers=h("ub"), params={"range": "30d"}).json()["sales_periods"]
    assert b["week"]["value_paise"] == 370000                                          # only B's lines: 700 mixed + 3000
