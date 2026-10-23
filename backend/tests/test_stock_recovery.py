"""Stock engine: failure-injection and recovery tests (the 'crash window' guarantee).

A crash is simulated by raising from stock._FAULT at a named point inside the engine (the process "dies" there); recovery is
then run (run_recovery with min age 0) and stock is verified to be EXACTLY right: never lost, never doubled, never negative.
In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_recovery_test", "JWT_SECRET": "recovery-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
CRON = {"Authorization": "Bearer cron-test-secret"}
S = {}


class Crash(Exception):
    """Simulated process death."""


def crash_at(point, nth=1, **match):
    """Arm a one-shot crash at the nth time the engine reaches `point` (optionally only for matching context)."""
    state = {"n": 0}

    def hook(p, **ctx):
        if p != point:
            return
        if any(ctx.get(k) is None or (k == "line" and ctx["line"]["i"] != v) for k, v in match.items()):
            return
        state["n"] += 1
        if state["n"] == nth:
            stock._FAULT = None
            raise Crash(point)
    stock._FAULT = hook


@pytest.fixture(autouse=True)
def _no_fault_leaks():
    yield
    stock._FAULT = None


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()

            async def user(mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u
            S["cust"], S["admin"] = await user("9100000401", "distributor", "HGC"), await user("9100000402", "super_admin", "HGADM")
            S["genie"], S["vu"] = await user("9100000403", "distributor", "HGSEL"), await user("9100000404", "vendor", "VDX")
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "VDX", "business_name": "Vendor X", "status": "approved",
                      "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, stock_qty, variants=None, vendor=True):
    async def mk():
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": 1000, "selling_price": 800, "gst_percent": 5,
             "stock": stock_qty if not variants else sum(v["stock"] for v in variants), "category": "Sarees", "options": [],
             "vendor_id": S["v"]["id"] if vendor else None, "vendor_name": "Vendor X" if vendor else None,
             "is_active": True, "approval_status": "approved", "created_at": now_iso()}
        if variants:
            p["variants"] = variants
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _doc(c, pid):
    return c.portal.call(lambda: db.products.find_one({"id": pid}))


def _stock(c, pid):
    return _doc(c, pid)["stock"]


def _order(c, pid, qty=1, method="cod", seller=None):
    body = {"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": method}
    if seller:
        body["seller_ref"] = seller
    r = c.post("/api/orders", json=body, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _get(c, oid):
    return c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _recover(c):
    return c.portal.call(lambda: stock.run_recovery(min_age_s=0))


def _movements(c, oid):
    return c.portal.call(lambda: db.stock_movements.find({"order_id": oid}).to_list(20))


def _age(c, oid, minutes):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": {"created_at": ts}}))


# ====================================================================== release: crash at every engine step
RELEASE_POINTS = ["after_txn_created", "before_line", "after_line", "before_decision", "before_finalize_line", "before_finalized_flag"]


@pytest.mark.parametrize("point", RELEASE_POINTS)
def test_release_crash_then_recovery_restores_stock_exactly_once(c, point):
    p = _product(c, f"RC-{point}", 10)
    o = _order(c, p["id"], 3)
    assert _stock(c, p["id"]) == 7
    crash_at(point)
    with pytest.raises(Crash):
        c.portal.call(lambda: stock.release_stock(o["id"], "test_release", "tester"))
    _recover(c)
    assert _stock(c, p["id"]) == 10                                           # restored, once
    assert _get(c, o["id"])["items"][0]["stock_released"] is True
    assert [m["delta"] for m in _movements(c, o["id"]) if m["reason"] == "test_release"] == [3]
    _recover(c)                                                               # recovery is idempotent
    assert c.portal.call(lambda: stock.release_stock(o["id"], "test_release", "tester")) == 0
    assert _stock(c, p["id"]) == 10
    assert len([m for m in _movements(c, o["id"]) if m["reason"] == "test_release"]) == 1


def test_a_retry_after_a_crash_completes_the_same_transaction_without_doubling(c):
    p = _product(c, "RC-RETRY", 10)
    o = _order(c, p["id"], 4)
    crash_at("before_decision")
    with pytest.raises(Crash):
        c.portal.call(lambda: stock.release_stock(o["id"], "retry_release", "tester"))
    assert _stock(c, p["id"]) == 10                                           # applied before the crash, status still pending
    c.portal.call(lambda: stock.release_stock(o["id"], "retry_release", "tester"))      # a later request resumes it
    assert _stock(c, p["id"]) == 10 and _get(c, o["id"])["items"][0]["stock_released"] is True


def test_two_concurrent_releasers_one_of_them_crashed(c):
    p = _product(c, "RC-CONC", 10)
    o = _order(c, p["id"], 2)
    crash_at("after_line")
    with pytest.raises(Crash):
        c.portal.call(lambda: stock.release_stock(o["id"], "conc_release", "a"))
    with ThreadPoolExecutor(max_workers=3) as ex:
        list(ex.map(lambda _: c.portal.call(lambda: stock.release_stock(o["id"], "conc_release", "b")), range(3)))
    assert _stock(c, p["id"]) == 10
    assert len([m for m in _movements(c, o["id"]) if m["reason"] == "conc_release"]) == 1


# ====================================================================== order placement
def test_crash_after_reservation_before_order_is_saved_gives_the_stock_back(c):
    p = _product(c, "OP-1", 10)
    oid = new_id()
    c.portal.call(lambda: stock.reserve_for_order(oid, [{"product_id": p["id"], "quantity": 4, "name": "x"}], "u"))
    assert _stock(c, p["id"]) == 6                                            # reserved, but the order was never inserted
    _recover(c)
    assert _stock(c, p["id"]) == 10
    _recover(c)
    assert _stock(c, p["id"]) == 10
    assert c.portal.call(lambda: db.stock_txns.find_one({"key": f"reserve:{oid}"}))["status"] == "rolled_back"


def test_failed_order_save_releases_immediately_and_is_idempotent(c):
    p = _product(c, "OP-2", 10)
    oid = new_id()
    c.portal.call(lambda: stock.reserve_for_order(oid, [{"product_id": p["id"], "quantity": 3, "name": "x"}], "u"))
    for _ in range(2):
        c.portal.call(lambda: stock.abandon_reservation(oid))
    assert _stock(c, p["id"]) == 10


def test_recovery_leaves_a_real_orders_reservation_alone(c):
    p = _product(c, "OP-3", 10)
    o = _order(c, p["id"], 3)
    _recover(c)
    assert _stock(c, p["id"]) == 7 and _get(c, o["id"]) is not None


@pytest.mark.parametrize("crash_line,second_available", [(0, True), (0, False)])
def test_multi_line_reservation_crash_resumes_or_rolls_back_as_a_whole(c, crash_line, second_available):
    a = _product(c, f"ML-A{int(second_available)}", 10)
    b = _product(c, f"ML-B{int(second_available)}", 5 if second_available else 1)
    oid = new_id()
    lines = [{"product_id": a["id"], "quantity": 2, "name": "A"}, {"product_id": b["id"], "quantity": 2, "name": "B"}]
    crash_at("after_line", line=crash_line)
    with pytest.raises(Crash):
        c.portal.call(lambda: stock.reserve_for_order(oid, lines, "u"))
    assert _stock(c, a["id"]) == 8                                            # first line applied before the 'crash'
    _recover(c)
    # No order was ever saved, so the whole reservation is abandoned either way: nothing is lost or kept.
    assert _stock(c, a["id"]) == 10 and _stock(c, b["id"]) == (5 if second_available else 1)


def test_short_second_line_rolls_back_the_first_atomically(c):
    a = _product(c, "SL-A", 10)
    b = _product(c, "SL-B", 1)
    r = c.post("/api/orders", json={"items": [{"product_id": a["id"], "quantity": 3}, {"product_id": b["id"], "quantity": 2}],
                                    "address": ADDR, "payment_method": "cod"}, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 409 and "SL-B" in r.json()["detail"]
    assert _stock(c, a["id"]) == 10 and _stock(c, b["id"]) == 1


def test_concurrent_checkouts_never_oversell_or_go_negative(c):
    p = _product(c, "CC-1", 5)
    def buy(_):
        return c.post("/api/orders", json={"items": [{"product_id": p["id"], "quantity": 1}], "address": ADDR, "payment_method": "cod"},
                      headers=_hdr(S["cust"]["id"])).status_code
    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = sorted(ex.map(buy, range(14)))
    assert codes.count(200) == 5 and codes.count(409) == 9
    assert _stock(c, p["id"]) == 0
    assert c.portal.call(lambda: db.orders.count_documents({"items.product_id": p["id"]})) == 5


# ====================================================================== durable restock intents
def test_admin_cancel_crash_before_any_restock_is_replayed(c):
    p = _product(c, "IN-1", 10)
    o = _order(c, p["id"], 2)
    crash_at("before_line")                                                   # dies inside the restock, nothing returned yet
    with pytest.raises(Crash):
        c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr(S["admin"]["id"]))
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and len(got["restock_intents"]) == 1 and _stock(c, p["id"]) == 8
    _recover(c)
    got = _get(c, o["id"])
    assert _stock(c, p["id"]) == 10 and got["restock_intents"] == [] and got["fulfilments"][0]["status"] == "cancelled"
    _recover(c)
    assert _stock(c, p["id"]) == 10


def test_admin_cancel_crash_after_restock_but_before_intent_is_cleared_does_not_double_restock(c):
    p = _product(c, "IN-2", 10)
    o = _order(c, p["id"], 2)
    crash_at("before_intent_clear")
    with pytest.raises(Crash):
        c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr(S["admin"]["id"]))
    assert _stock(c, p["id"]) == 10 and len(_get(c, o["id"])["restock_intents"]) == 1
    _recover(c)
    assert _stock(c, p["id"]) == 10 and _get(c, o["id"])["restock_intents"] == []


def test_vendor_reject_crash_is_replayed(c):
    p = _product(c, "IN-3", 10)
    o = _order(c, p["id"], 3)
    crash_at("before_line")
    with pytest.raises(Crash):
        c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=_hdr(S["vu"]["id"]), json={"status": "rejected", "note": "Out of material"})
    assert _get(c, o["id"])["fulfilments"][0]["status"] == "rejected" and _stock(c, p["id"]) == 7
    _recover(c)
    assert _stock(c, p["id"]) == 10
    _recover(c)
    assert _stock(c, p["id"]) == 10


def test_inspection_resellable_crash_is_replayed_once(c):
    p = _product(c, "IN-4", 10)
    o = _order(c, p["id"], 2)
    h = _hdr(S["vu"]["id"])
    for st in ("accepted", "packed"):
        assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=h, json={"status": st}).status_code == 200
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=h, json={"status": "dispatched", "carrier": "BD", "tracking_number": "T1"}).status_code == 200
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=h, json={"status": "delivery_failed", "note": "Unreachable"}).status_code == 200
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=h, json={"status": "returned_to_origin", "note": "Courier returned"}).status_code == 200
    assert _stock(c, p["id"]) == 8
    crash_at("before_line")
    with pytest.raises(Crash):
        c.post(f"/api/vendor/orders/{o['id']}/return-inspection", headers=h, json={"received": True, "outcome": "resellable", "note": "Inspected OK"})
    assert _stock(c, p["id"]) == 8                                            # decision recorded, restock not yet done
    _recover(c)
    assert _stock(c, p["id"]) == 10
    _recover(c)
    assert _stock(c, p["id"]) == 10


# ====================================================================== expiry + late payment
def test_expiry_crash_after_cancel_is_finished_by_recovery(c):
    p = _product(c, "EX-1", 10)
    o = _order(c, p["id"], 2, method="online")
    _age(c, o["id"], 20)
    crash_at("after_expiry_claim")
    with pytest.raises(Crash):
        c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, p["id"]) == 8
    assert c.get("/api/cron/expire-pending-orders", headers=CRON).status_code == 200      # next sweep self-heals
    assert _stock(c, p["id"]) == 10
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert _stock(c, p["id"]) == 10


def test_late_payment_crash_after_restocking_is_completed_by_recovery(c):
    p = _product(c, "LP-1", 10)
    o = _order(c, p["id"], 2, method="online", seller="HGSEL")
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _age(c, o["id"], 20)
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert _stock(c, p["id"]) == 10 and _get(c, o["id"])["status"] == "cancelled"
    crash_at("before_finish_revival")                                         # stock re-reserved, then the process dies
    with pytest.raises(Crash):
        c.portal.call(lambda: shop_routes._process_paid_order(sid))
    assert _stock(c, p["id"]) == 8 and _get(c, o["id"])["status"] == "cancelled"
    _recover(c)
    got = _get(c, o["id"])
    assert got["status"] == "processing" and got["payment_status"] == "paid" and got.get("invoice_number")
    assert _stock(c, p["id"]) == 8                                            # re-reserved exactly once
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) >= 1   # commissions credited, once
    n = c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]}))
    _recover(c)
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == n and _stock(c, p["id"]) == 8


def test_late_payment_crash_while_out_of_stock_still_ends_in_needs_refund(c):
    p = _product(c, "LP-2", 2)
    o = _order(c, p["id"], 2, method="online", seller="HGSEL")
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _age(c, o["id"], 20)
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    _order(c, p["id"], 2, method="cod")                                       # someone else takes the freed stock
    assert _stock(c, p["id"]) == 0
    crash_at("before_decision")                                               # dies while deciding on the re-reservation
    with pytest.raises(Crash):
        c.portal.call(lambda: shop_routes._process_paid_order(sid))
    _recover(c)
    got = _get(c, o["id"])
    assert got["needs_refund"] is True and got["status"] == "cancelled" and not got.get("invoice_number")
    assert _stock(c, p["id"]) == 0
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0


# ====================================================================== variants, markers, housekeeping
def test_variant_level_reservation_is_atomic_and_keeps_totals_consistent(c):
    p = _product(c, "VR-1", 0, variants=[{"sku": "VR-1-S", "stock": 2}, {"sku": "VR-1-M", "stock": 1}])
    ok = c.portal.call(lambda: stock.reserve_for_order(new_id(), [{"product_id": p["id"], "variant_sku": "VR-1-S", "quantity": 2, "name": "S"}], "u"))
    assert ok is None
    d = _doc(c, p["id"])
    assert {v["sku"]: v["stock"] for v in d["variants"]} == {"VR-1-S": 0, "VR-1-M": 1} and d["stock"] == 1
    short = c.portal.call(lambda: stock.reserve_for_order(new_id(), [{"product_id": p["id"], "variant_sku": "VR-1-M", "quantity": 1, "name": "M"},
                                                                    {"product_id": p["id"], "variant_sku": "VR-1-S", "quantity": 1, "name": "S"}], "u"))
    assert short and short["name"] == "S"                                     # S is sold out
    d = _doc(c, p["id"])
    assert {v["sku"]: v["stock"] for v in d["variants"]} == {"VR-1-S": 0, "VR-1-M": 1} and d["stock"] == 1   # M rolled back
    ghost = c.portal.call(lambda: stock.reserve_for_order(new_id(), [{"product_id": p["id"], "variant_sku": "NOPE", "quantity": 1, "name": "?"}], "u"))
    assert ghost is not None


def test_internal_markers_never_leak_into_api_responses(c):
    p = _product(c, "MK-1", 10)
    _order(c, p["id"], 1)
    assert "stock_ops" in _doc(c, p["id"])                                    # present internally...
    shop = c.get(f"/api/products/{p['id']}").json()
    assert "stock_ops" not in shop
    assert all("stock_ops" not in x for x in c.get("/api/products").json())
    assert all("stock_ops" not in x for x in c.get("/api/vendor/products", headers=_hdr(S["vu"]["id"])).json())


def test_pruning_old_markers_does_not_allow_a_replay_to_apply_twice(c):
    p = _product(c, "PR-1", 10)
    o = _order(c, p["id"], 3)
    c.portal.call(lambda: stock.release_stock(o["id"], "prune_release", "t"))
    assert _stock(c, p["id"]) == 10
    t = c.portal.call(lambda: db.stock_txns.find_one({"order_id": o["id"], "kind": "release"}))
    assert c.portal.call(lambda: stock.prune_stock_markers(days=0)) >= 1
    assert not any(k.startswith(("m_", "c_")) and t["id"] in k for k in (_doc(c, p["id"]).get("stock_ops") or {}))
    c.portal.call(lambda: stock._run_txn(t))                                  # a stray late replay of the finished txn
    c.portal.call(lambda: stock._finalize(t))
    assert _stock(c, p["id"]) == 10
