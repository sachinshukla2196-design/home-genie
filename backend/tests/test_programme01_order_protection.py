"""Programme 01 / B-006: order creation is protected server-side (per-account and per-IP rate limits, an open-order cap, one order
per identical submission) and stock reservations are released safely: abandoned prepaid orders expire (not while a reported
gateway payment is in its grace period), late payments are handled, accepted cash-on-delivery orders are never expired, and
every release happens exactly once without stock going negative.

Runs at the PRODUCTION default limits (set here before import; tests/conftest.py raises them only for older suites).
Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_order_protection.py -n 0`.
"""
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

PROD = {"ORDER_OPEN_UNPAID_MAX": "5", "ORDER_CREATE_PER_USER_10MIN": "10", "ORDER_CREATE_PER_IP_10MIN": "60", "ORDER_SUBMIT_WINDOW_SECONDS": "60"}
os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_orders_test", "JWT_SECRET": "p01-orders-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret", **PROD})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import order_protection  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from core import db, hash_password, now_iso, new_id, RATE_LIMITS  # noqa: E402
from p01_harness import World, seed_world, hdr, ADDR  # noqa: E402

S = {}
OLD = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
VERY_OLD = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "OP")
            for i in range(12):
                u = {"id": new_id(), "distributor_id": f"OPC{i:03d}", "full_name": f"c{i}", "mobile": f"97000000{i:02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": "customer", "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[f"c{i}"] = u
        client.portal.call(seed)
        yield World(client, S, "OPSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _place(w, who, lines, method="online", ip=None):
    h = hdr(S[who]["id"])
    if ip:
        h["X-Forwarded-For"] = ip
    return w.c.post("/api/orders", json={"items": [{"product_id": p, "quantity": q} for p, q in lines], "address": ADDR,
                                          "payment_method": method}, headers=h)


def _cancel(w, who, oid):
    return w.c.post(f"/api/orders/{oid}/cancel", json={"reason": "changed my mind"}, headers=hdr(S[who]["id"]))


def test_runs_at_the_production_defaults():
    assert {k: str(v) for k, v in order_protection.DEFAULTS.items()} == PROD
    assert order_protection.OPEN_UNPAID_MAX == 5 and RATE_LIMITS["order_create_user"] == (10, 600)
    assert RATE_LIMITS["order_create_ip"] == (60, 600) and order_protection.SUBMIT_WINDOW_SECONDS == 60


# ================================================================ rate limits and the open-order cap
def test_an_account_is_limited_to_ten_orders_in_ten_minutes(w):
    pid = w.product("va", 100, stock=100)
    for i in range(10):
        r = _place(w, "c0", [(pid, i + 1)])                                 # different carts (no duplicate merge)
        assert r.status_code == 200, (i, r.text)
        assert _cancel(w, "c0", r.json()["id"]).status_code == 200          # keep the open-order count low
    r = _place(w, "c0", [(pid, 20)])
    assert r.status_code == 429 and r.headers.get("Retry-After")


def test_several_accounts_behind_one_address_can_all_order(w):
    pid = w.product("va", 100, stock=100)
    for who in ("c1", "c2", "c3", "c4"):                                    # a family / office sharing one IP
        for q in (1, 2):
            assert _place(w, who, [(pid, q)], ip="203.0.113.7").status_code == 200


def test_the_ip_limit_stops_a_flood_across_accounts(w, monkeypatch):
    monkeypatch.setitem(RATE_LIMITS, "order_create_ip", (3, 600))            # the mechanism, at a small number
    pid = w.product("va", 100, stock=100)
    codes = [_place(w, who, [(pid, 1)], ip="198.51.100.9").status_code for who in ("c5", "c6", "c7", "c8")]
    assert codes[:3] == [200, 200, 200] and codes[3] == 429


def test_open_unpaid_orders_are_capped_and_paying_or_cancelling_frees_a_slot(w):
    pid = w.product("va", 100, stock=100)
    ids = [_place(w, "c9", [(pid, q)]).json()["id"] for q in range(1, 6)]
    r = _place(w, "c9", [(pid, 9)])
    assert r.status_code == 429 and "waiting for payment" in r.json()["detail"]
    assert _cancel(w, "c9", ids[0]).status_code == 200
    assert _place(w, "c9", [(pid, 9)]).status_code == 200
    stock_before = w.stock(pid)
    assert _place(w, "c9", [(pid, 7)]).status_code == 429 and w.stock(pid) == stock_before   # a refusal reserves nothing


def test_cod_orders_waiting_for_the_seller_count_and_an_accepted_one_does_not(w):
    pid = w.product("va", 100, stock=100)
    ids = [_place(w, "c10", [(pid, q)], method="cod").json()["id"] for q in range(1, 6)]
    assert _place(w, "c10", [(pid, 9)], method="cod").status_code == 429
    assert w.step("va", ids[0], "accepted").status_code == 200
    assert _place(w, "c10", [(pid, 9)], method="cod").status_code == 200


# ================================================================ duplicate submissions
def test_the_same_cart_submitted_twice_is_one_order_and_one_reservation(w):
    pid = w.product("va", 100, stock=20)
    a = _place(w, "c11", [(pid, 2)])
    b = _place(w, "c11", [(pid, 2)])
    assert a.status_code == b.status_code == 200 and a.json()["id"] == b.json()["id"] and b.json()["duplicate_submission"]
    assert w.stock(pid) == 18
    assert _place(w, "c11", [(pid, 3)]).json()["id"] != a.json()["id"]      # a different cart is a different order


def test_simultaneous_identical_submissions_create_one_order(w):
    pid = w.product("va", 100, stock=20)
    out = []
    ts = [threading.Thread(target=lambda: out.append(_place(w, "cust2", [(pid, 1)]))) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    ids = {r.json()["id"] for r in out if r.status_code == 200}
    assert len(ids) == 1 and all(r.status_code in (200, 409) for r in out)
    assert w.stock(pid) == 19


def test_after_payment_or_a_failed_attempt_the_same_cart_can_be_ordered_again(w):
    pid = w.product("va", 100, stock=2)
    r = _place(w, "seller", [(pid, 3)])                                      # more than is in stock
    assert r.status_code == 409
    assert w.run(lambda: db.order_submissions.count_documents({"order_id": None})) == 0     # the claim was released
    first = _place(w, "seller", [(pid, 1)]).json()
    sid = w.tx(first)
    w.run(lambda: shop_routes._process_paid_order(sid))
    again = _place(w, "seller", [(pid, 1)])
    assert again.status_code == 200 and again.json()["id"] != first["id"]


# ================================================================ prepaid expiry
def _age(w, oid, when=OLD):
    w.run(lambda: db.orders.update_one({"id": oid}, {"$set": {"created_at": when}}))


def test_an_abandoned_prepaid_order_expires_and_its_stock_returns_exactly_once(w):
    pid = w.product("vb", 100, stock=10)
    o = w.order([(pid, 4)], who="cust", seller=False)
    _age(w, o["id"])
    for _ in range(2):
        w.run(lambda: stock.expire_pending_online_orders(limit=10))
    got = w.get(o["id"])
    assert got["status"] == "cancelled" and got["cancel_reason"] == stock.EXPIRY_REASON and w.stock(pid) == 10


def test_a_reported_gateway_payment_keeps_the_stock_through_its_grace_period(w):
    pid = w.product("vb", 100, stock=10)
    o = w.order([(pid, 2)], who="cust", seller=False)
    sid = w.tx(o)
    w.run(lambda: db.payment_transactions.update_one({"session_id": sid}, {"$set": {"razorpay_payment_id": "pay_inflight"}}))
    _age(w, o["id"])
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    assert w.get(o["id"])["status"] == "payment_pending" and w.stock(pid) == 8      # held: the payment is on its way
    _age(w, o["id"], VERY_OLD)                                                         # grace over
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    assert w.get(o["id"])["status"] == "cancelled" and w.stock(pid) == 10


def test_payment_just_before_expiry_wins(w):
    pid = w.product("vb", 100, stock=10)
    o = w.order([(pid, 1)], who="cust", seller=False)
    sid = w.tx(o)
    w.run(lambda: shop_routes._process_paid_order(sid))
    _age(w, o["id"])
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    assert w.get(o["id"])["payment_status"] == "paid" and w.get(o["id"])["status"] != "cancelled" and w.stock(pid) == 9


def test_payment_just_after_expiry_revives_the_order_when_stock_remains_and_a_duplicate_webhook_changes_nothing(w):
    pid = w.product("vb", 100, stock=10)
    o = w.order([(pid, 3)], who="cust", seller=False)
    sid = w.tx(o)
    _age(w, o["id"])
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    assert w.stock(pid) == 10
    for _ in range(2):                                                                  # delayed, then repeated
        w.run(lambda: shop_routes._process_paid_order(sid))
    got = w.get(o["id"])
    assert got["payment_status"] == "paid" and got["status"] == "processing" and not got.get("needs_refund")
    assert w.stock(pid) == 7                                                             # taken again exactly once


def test_a_late_payment_when_the_stock_is_gone_is_owed_back_and_no_stock_goes_negative(w):
    pid = w.product("vb", 100, stock=3)
    o = w.order([(pid, 3)], who="cust", seller=False)
    sid = w.tx(o)
    _age(w, o["id"])
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    other = _place(w, "c1", [(pid, 3)])                                                 # someone else buys the freed stock
    assert other.status_code == 200 and w.stock(pid) == 0
    w.run(lambda: shop_routes._process_paid_order(sid))
    got = w.get(o["id"])
    assert got.get("needs_refund") and got["status"] == "cancelled" and w.stock(pid) == 0


# ================================================================ cash on delivery is never expired
def test_cod_orders_keep_their_stock_through_the_expiry_sweep(w):
    pid = w.product("va", 100, stock=10)
    new = _place(w, "c2", [(pid, 2)], method="cod").json()
    accepted = _place(w, "c3", [(pid, 3)], method="cod").json()
    assert w.step("va", accepted["id"], "accepted").status_code == 200
    for oid in (new["id"], accepted["id"]):
        _age(w, oid, VERY_OLD)
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    assert w.get(new["id"])["status"] != "cancelled" and w.get(accepted["id"])["status"] != "cancelled"
    assert w.stock(pid) == 5


def test_a_cancelled_cod_order_releases_its_stock_once(w):
    pid = w.product("va", 100, stock=10)
    o = _place(w, "c4", [(pid, 4)], method="cod").json()
    assert _cancel(w, "c4", o["id"]).status_code == 200
    assert _cancel(w, "c4", o["id"]).status_code == 400
    assert w.stock(pid) == 10


def test_a_vendor_rejection_releases_only_that_vendors_stock(w):
    pa, pb = w.product("va", 100, stock=10), w.product("vb", 100, stock=10)
    o = _place(w, "c5", [(pa, 2), (pb, 3)], method="cod").json()
    assert w.step("va", o["id"], "rejected", note="Out of this colour").status_code == 200
    assert w.step("va", o["id"], "rejected", note="Out of this colour").status_code == 400
    assert w.stock(pa) == 10 and w.stock(pb) == 7


def test_concurrent_orders_for_the_last_units_never_oversell(w):
    pid = w.product("vb", 100, stock=3)
    who = ["c6", "c7", "c8", "c9", "c10", "c11"]
    out = []
    ts = [threading.Thread(target=lambda u=u: out.append(_place(w, u, [(pid, 1)]).status_code)) for u in who]
    [t.start() for t in ts]
    [t.join() for t in ts]
    # c6, c7, c8 and c11 are under every limit (c9 / c10 are at their open-order cap): four buyers race for three units
    assert out.count(200) == 3 and out.count(409) >= 1 and w.stock(pid) == 0
