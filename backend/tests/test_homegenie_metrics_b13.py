"""Batch 13, Phase 8 — HomeGenie dashboard metrics (HG-03): every figure reconciles to the source records.

Records are seeded with known values so each definition in docs/HOMEGENIE_DASHBOARD_METRICS.md can be checked exactly, plus one
real order through the API (attribution, payment, commission) to prove the live path feeds the same figures.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_homegenie_metrics_b13.py -n 0`).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_hg_metrics_b13_test", "JWT_SECRET": "hgmetrics13-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
ADDR = {"full_name": "Meera Iyer", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
NOW = datetime.now(timezone.utc)
D3 = (NOW - timedelta(days=3)).isoformat()
OLD = (NOW - timedelta(days=60)).isoformat()
LONG_AGO_DELIVERED = (NOW - timedelta(days=40)).isoformat()


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


def _order(oid, *, ps="paid", status="processing", goods=100000, fee=0, refunded=0, created=D3, lines=1, vendors=1, delivered=False,
           dup=False):
    items = [{"product_id": f"p{i}", "vendor_id": f"v{i % vendors}", "quantity": 1, "total_paise": goods // lines} for i in range(lines)]
    fl = [{"vendor_id": f"v{i}", "status": "delivered" if delivered else "accepted",
           "events": [{"status": "delivered", "at": LONG_AGO_DELIVERED}] if delivered else []} for i in range(vendors)]
    return {"id": oid, "order_number": oid.upper(), "user_id": "buyer", "seller_user_id": S["hg"]["id"], "payment_status": ps,
            "status": status, "items": items, "fulfilments": fl, "items_total_paise": goods, "cod_fee_paise": fee,
            "total_paise": goods + fee, "total": (goods + fee) / 100, "refunded_paise": refunded, "created_at": created,
            "address": ADDR, "prices_include_gst": True, **({"duplicate_payments": [{"status": "refund_due"}]} if dup else {})}


def _comm(cid, oid, *, amount=30000, reversed_=0, status="PENDING", released=None, created=D3, ctype="COMMISSION_DIRECT", base=95238):
    return {"id": cid, "order_id": oid, "order_number": oid.upper(), "user_id": S["hg"]["id"], "type": ctype, "status": status,
            "amount_paise": amount, "amount": amount / 100, "reversed_paise": reversed_, "base_paise": base, "percent": 30,
            "released_at": released, "release_after_days": 7, "created_at": created}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, did in (("hg", "distributor", "HG130001"), ("cust", "customer", "CU130001"), ("other", "distributor", "HG130002")):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": f"91000170{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green" if role == "distributor" else "customer",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await db.orders.insert_many([
                _order("o_one"),                                                           # one vendor, paid
                _order("o_multi", lines=3, vendors=2, goods=300000),                       # one order, two vendors, three lines
                _order("o_part", ps="partially_refunded", refunded=40000),                 # partial refund
                _order("o_full", ps="refunded", status="refunded", refunded=100000),       # full refund
                _order("o_cancel", ps="pending", status="cancelled"),                      # never paid, cancelled
                _order("o_unpaid", ps="pending", status="pending"),                        # awaiting payment
                _order("o_deliv", delivered=True, fee=4900),                               # delivered, COD fee excluded from sales
                _order("o_dup", dup=True),                                                 # a duplicate capture: still one order
                _order("o_old", created=OLD),                                              # outside a 30-day range
            ])
            await db.return_cases.insert_one({"id": "rc1", "order_id": "o_part", "status": "received", "lines": []})
            await db.commissions.insert_many([
                _comm("c1", "o_one"),                                                      # held (not delivered)
                _comm("c2", "o_deliv", status="RELEASED", released=now_iso()),            # released
                _comm("c3", "o_part", amount=30000, reversed_=12000, status="PARTIALLY_REVERSED"),
                _comm("c4", "o_full", reversed_=30000, status="REVERSED"),                 # fully reversed
                _comm("c5", "o_multi", amount=10000, ctype="COMMISSION_REFERRAL", base=0),
                _comm("c6", "o_old", created=OLD),
            ])
            await db.withdrawal_requests.insert_many([
                {"id": "w1", "user_id": S["hg"]["id"], "amount_paise": 50000, "amount": 500.0, "status": "paid", "created_at": D3},
                {"id": "w2", "user_id": S["hg"]["id"], "amount_paise": 20000, "amount": 200.0, "status": "pending", "created_at": D3},
                {"id": "w3", "user_id": S["hg"]["id"], "amount_paise": 10000, "amount": 100.0, "status": "rejected", "created_at": D3},
            ])
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _m(c, **params):
    r = c.get("/api/homegenie/metrics", params=params, headers=_hdr("hg"))
    assert r.status_code == 200, r.text
    return r.json()


def test_figures_reconcile_to_the_seeded_records(c):
    m = _m(c)["metrics"]
    assert m["attributed_orders"] == 8                     # o_old is outside the default 30 days
    assert m["attributed_order_lines"] == 10               # o_multi contributes 3 lines but is ONE order
    assert m["paid_orders"] == 6                           # one, multi, part, full (paid then refunded), deliv, dup
    assert m["cancelled_orders"] == 1 and m["refunded_orders"] == 1 and m["partially_refunded_orders"] == 1
    assert m["delivered_orders"] == 1 and m["returned_orders"] == 1
    assert m["gross_sales_paise"] == 100000 + 300000 + 100000 + 100000 + 100000 + 100000   # COD fee of o_deliv excluded
    assert m["refunded_sales_paise"] == 40000 + 100000
    assert m["net_sales_paise"] == m["gross_sales_paise"] - 140000
    assert m["commission_earned_paise"] == 30000 * 4 + 10000
    assert m["commission_reversed_paise"] == 12000 + 30000
    assert m["commission_released_paise"] == 30000
    assert m["commission_held_paise"] == 30000 + 18000 + 10000          # c1, c3 net, c5; c4 fully reversed is not held
    assert m["commission_basis_paise"] == 95238 * 4                     # direct commissions only
    assert m["commission_by_type"]["COMMISSION_REFERRAL"] == 10000
    assert m["withdrawal_requests"] == 3 and m["withdrawals_paid_paise"] == 50000 and m["withdrawals_pending_paise"] == 20000


def test_date_ranges_use_indian_day_boundaries(c):
    old_day = datetime.fromisoformat(OLD).astimezone(__import__("zoneinfo").ZoneInfo("Asia/Kolkata")).date().isoformat()
    m = _m(c, frm=old_day, to=old_day)["metrics"]
    assert m["attributed_orders"] == 1 and m["commission_earned_paise"] == 30000
    assert c.get("/api/homegenie/metrics", params={"frm": "2026-12-31", "to": "2026-01-01"}, headers=_hdr("hg")).status_code == 400
    assert c.get("/api/homegenie/metrics", params={"frm": "2024-01-01", "to": "2026-01-01"}, headers=_hdr("hg")).status_code == 400


def test_trend_sums_match_the_totals(c):
    d = _m(c)
    assert sum(x["orders"] for x in d["trend"]) == d["metrics"]["paid_orders"]
    assert sum(x["sales_paise"] for x in d["trend"]) == d["metrics"]["net_sales_paise"]


def test_held_reasons_come_from_the_finance_rule(c):
    reasons = {r["reason"]: r for r in _m(c)["held_reasons"]}
    assert reasons["not_delivered"]["count"] >= 1
    assert sum(r["amount_paise"] for r in reasons.values()) >= 30000


def test_attributed_orders_are_paged_on_the_server_and_mask_the_customer(c):
    r = c.get("/api/homegenie/orders", params={"page_size": 3}, headers=_hdr("hg")).json()
    assert r["total"] == 8 and len(r["items"]) == 3 and r["pages"] == 3
    states = {x["order_number"]: x["state"] for p in (1, 2, 3)
              for x in c.get("/api/homegenie/orders", params={"page_size": 3, "page": p}, headers=_hdr("hg")).json()["items"]}
    assert states == {"O_ONE": "paid", "O_MULTI": "paid", "O_PART": "returned", "O_FULL": "refunded", "O_CANCEL": "cancelled",
                      "O_UNPAID": "awaiting_payment", "O_DELIV": "delivered", "O_DUP": "paid"}
    first = c.get("/api/homegenie/orders", params={"state": "returned"}, headers=_hdr("hg")).json()["items"][0]
    assert first["customer"] == "Meera" and "mobile" not in str(first)


def test_only_the_member_sees_their_figures(c):
    assert _m(c) and c.get("/api/homegenie/metrics", headers=_hdr("other")).json()["metrics"]["attributed_orders"] == 0
    assert c.get("/api/homegenie/metrics", headers=_hdr("cust")).status_code == 403


def test_a_real_attributed_order_flows_into_the_figures(c):
    async def prod():
        await db.products.insert_one({"id": "real1", "sku": "REAL-1", "name": "Saree", "images": [], "mrp": 1200, "selling_price": 1050,
                                      "gst_percent": 5, "stock": 5, "category": "Sarees", "options": [], "vendor_id": None,
                                      "is_active": True, "approval_status": "approved", "created_at": now_iso()})
    _run(c, prod)
    before = _m(c)["metrics"]
    o = c.post("/api/orders", json={"items": [{"product_id": "real1", "quantity": 2}], "address": ADDR, "payment_method": "online",
                                    "seller_ref": "HG130001"}, headers=_hdr("cust")).json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    after = _m(c)["metrics"]
    assert after["attributed_orders"] == before["attributed_orders"] + 1 and after["paid_orders"] == before["paid_orders"] + 1
    assert after["gross_sales_paise"] - before["gross_sales_paise"] == 210000
    assert after["commission_basis_paise"] - before["commission_basis_paise"] == 200000            # taxable value of 2 x 1050 at 5%
    assert after["commission_earned_paise"] - before["commission_earned_paise"] == 60000           # 30% of the basis, as recorded
