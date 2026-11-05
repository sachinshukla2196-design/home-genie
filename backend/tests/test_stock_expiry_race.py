"""Phase 3B.5: stock reservation expiry races. Integration: THROWAWAY MongoDB (real concurrency on the motor client).

Invariant: a reservation consumes stock once and returns it at most once, and the movement log matches the stock counter.
Run in its own process: `pytest tests/test_stock_expiry_race.py -n 0`.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_stock_race_test", "JWT_SECRET": "stock-race-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
CRON = {"Authorization": "Bearer cron-test-secret"}
S = {}
INITIAL = 10


class Crash(Exception):
    """Simulated process death."""


def crash_at(point):
    def hook(p, **ctx):
        if p == point:
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
            await db_indexes.apply()
            for key, role in (("cust", "distributor"), ("admin", "super_admin")):
                u = {"id": new_id(), "distributor_id": key.upper() + "R1", "full_name": key, "mobile": "95" + new_id()[:8].replace("-", "0"),
                     "email": None, "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _product(c, qty=INITIAL):
    p = {"id": new_id(), "sku": "SR-" + new_id()[:6], "name": "Saree", "images": [], "mrp": 1000, "selling_price": 800, "gst_percent": 5,
         "stock": qty, "category": "Sarees", "options": [], "vendor_id": None, "is_active": True, "approval_status": "approved",
         "created_at": now_iso()}
    _run(c, lambda: db.products.insert_one(dict(p)))
    return p["id"]


def _order(c, pid, qty=2):
    r = c.post("/api/orders", json={"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": "online"},
               headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _expired_order(c, pid, qty=2):
    o = _order(c, pid, qty)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"created_at": ts}}))
    return o


def _tx(c, o):
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    return sid


def _stock(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}))["stock"]


def _moves(c, oid):
    return sorted(m["delta"] for m in _run(c, lambda: db.stock_movements.find({"order_id": oid}).to_list(50)))


def _ledger_matches_counter(c, pid):
    """The stock counter equals the opening stock plus every logged movement for the product (no missing or extra rows)."""
    total = sum(m["delta"] for m in _run(c, lambda: db.stock_movements.find({"product_id": pid}).to_list(500)))
    return _stock(c, pid) == INITIAL + total


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


# ================================================================ reservation
def test_a_reservation_consumes_stock_once_even_if_repeated(c):
    pid = _product(c)
    o = _order(c, pid, 3)
    assert _stock(c, pid) == INITIAL - 3 and _moves(c, o["id"]) == [-3]
    lines = [{"product_id": pid, "quantity": 3, "name": "Saree"}]
    assert _run(c, lambda: stock.reserve_for_order(o["id"], lines, "x")) is None                 # same reservation again: a no-op
    assert _stock(c, pid) == INITIAL - 3 and _moves(c, o["id"]) == [-3] and _ledger_matches_counter(c, pid)


# ================================================================ expiry
def test_one_expiry_returns_stock_once_and_a_rerun_changes_nothing(c):
    pid = _product(c)
    o = _expired_order(c, pid)
    assert _run(c, stock.expire_pending_online_orders) >= 1
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2]
    for _ in range(3):
        _run(c, stock.expire_pending_online_orders)
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2] and _ledger_matches_counter(c, pid)
    assert _get(c, o["id"])["status"] == "cancelled" and _get(c, o["id"])["items"][0]["stock_released"] is True


def test_concurrent_finalizers_of_one_release_log_one_movement(c):
    """The original defect, made deterministic: several runners finalize the SAME committed release at once."""
    pid = _product(c)
    o = _expired_order(c, pid)
    _run(c, stock.expire_pending_online_orders)
    txn = _run(c, lambda: db.stock_txns.find_one({"order_id": o["id"], "kind": "release"}, {"_id": 0}))
    for _ in range(5):
        _run(c, lambda: db.stock_movements.delete_many({"txn_id": txn["id"]}))
        _run(c, lambda: db.stock_txns.update_one({"id": txn["id"]}, {"$set": {"finalized": False}}))

        async def race():
            await asyncio.gather(*[stock._finalize(dict(txn)) for _ in range(8)])
        _run(c, race)
        assert _run(c, lambda: db.stock_movements.count_documents({"txn_id": txn["id"]})) == 1
    assert _stock(c, pid) == INITIAL and _ledger_matches_counter(c, pid)


@pytest.mark.parametrize("round_", range(15))
def test_concurrent_expiry_sweeps_return_stock_exactly_once(c, round_):
    pid = _product(c)
    o = _expired_order(c, pid)

    async def race():
        return await asyncio.gather(*[stock.expire_pending_online_orders() for _ in range(4)])
    _run(c, race)
    with ThreadPoolExecutor(max_workers=3) as ex:                                              # and through the cron endpoint
        for f in [ex.submit(lambda: c.get("/api/cron/expire-pending-orders", headers=CRON)) for _ in range(3)]:
            assert f.result().status_code == 200
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2] and _ledger_matches_counter(c, pid)
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and got["cancel_reason"] == "payment_timeout" and got["items"][0]["stock_released"] is True
    assert _run(c, lambda: db.stock_txns.count_documents({"order_id": o["id"], "kind": "release"})) == 1


# ================================================================ competing paths
@pytest.mark.parametrize("round_", range(5))
def test_expiry_racing_a_confirmed_cancellation_returns_stock_once(c, round_):
    pid = _product(c)
    o = _expired_order(c, pid)

    async def race():
        return await asyncio.gather(stock.expire_one(o["id"]),
                                    stock.restock_on_confirmed_cancellation(o["id"], "payment_pending", {"id": S["admin"]["id"]}),
                                    stock.expire_pending_online_orders())
    _run(c, race)
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2] and _ledger_matches_counter(c, pid)


@pytest.mark.parametrize("round_", range(10))
def test_expiry_racing_a_payment_never_leaves_an_active_order_without_stock(c, round_):
    pid = _product(c)
    o = _expired_order(c, pid)
    sid = _tx(c, o)

    async def race():
        return await asyncio.gather(stock.expire_one(o["id"]), shop_routes._process_paid_order(sid), return_exceptions=True)
    _run(c, race)
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    _run(c, stock.expire_pending_online_orders)
    got = _get(c, o["id"])
    active = got["payment_status"] == "paid" and got["status"] != "cancelled" and not got.get("needs_refund")
    assert _stock(c, pid) == (INITIAL - 2 if active else INITIAL), got
    assert sum(_moves(c, o["id"])) == (-2 if active else 0) and _ledger_matches_counter(c, pid)


def test_a_late_payment_while_the_expiry_release_is_in_flight_re_reserves_the_stock(c):
    """Deterministic version of the oversell race: expiry claimed and its release transaction recorded but not yet run, then
    the payment lands. The revival must first finish that release, then re-reserve; recovery afterwards changes nothing."""
    pid = _product(c)
    o = _expired_order(c, pid)
    sid = _tx(c, o)
    crash_at("after_txn_created")
    with pytest.raises(Crash):
        _run(c, lambda: stock.expire_one(o["id"]))
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, pid) == INITIAL - 2         # claimed; stock not yet back
    _run(c, lambda: shop_routes._process_paid_order(sid))
    got = _get(c, o["id"])
    assert got["payment_status"] == "paid" and got["status"] == "processing" and not got.get("needs_refund")
    assert _stock(c, pid) == INITIAL - 2                                                       # the paid order holds its stock
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    _run(c, stock.expire_pending_online_orders)
    assert _stock(c, pid) == INITIAL - 2 and sum(_moves(c, o["id"])) == -2 and _ledger_matches_counter(c, pid)


def test_two_independent_release_triggers_cannot_both_restore(c):
    pid = _product(c)
    o = _expired_order(c, pid)

    async def race():
        return await asyncio.gather(stock.release_stock(o["id"], "order_payment_timeout", "system"),
                                    stock.release_stock(o["id"], "order_cancelled_confirmed", S["admin"]["id"]),
                                    stock.run_intents(o["id"]))
    _run(c, race)
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2] and _ledger_matches_counter(c, pid)


# ================================================================ crash and recovery
def test_a_claimed_but_unreleased_expiry_recovers_exactly_once(c):
    pid = _product(c)
    o = _expired_order(c, pid)
    crash_at("after_expiry_claim")
    with pytest.raises(Crash):
        _run(c, lambda: stock.expire_one(o["id"]))
    assert _stock(c, pid) == INITIAL - 2
    for _ in range(3):
        _run(c, stock.expire_pending_online_orders)                                            # the sweep's self-heal finishes it
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2] and _ledger_matches_counter(c, pid)


@pytest.mark.parametrize("point", ["before_finalize_line", "before_finalized_flag"])
def test_a_restored_but_unfinished_release_is_never_repeated(c, point):
    pid = _product(c)
    o = _expired_order(c, pid)
    crash_at(point)
    with pytest.raises(Crash):
        _run(c, lambda: stock.expire_one(o["id"]))
    assert _stock(c, pid) == INITIAL                                                           # the counter already moved, once

    async def recover_concurrently():
        await asyncio.gather(stock.run_recovery(min_age_s=0), stock.expire_pending_online_orders(), stock.run_recovery(min_age_s=0))
    _run(c, recover_concurrently)
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    assert _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2] and _ledger_matches_counter(c, pid)
    assert _get(c, o["id"])["items"][0]["stock_released"] is True


def test_a_stale_release_finalizer_cannot_mark_a_revived_line_released(c):
    """After a release is finalized and the order revived, replaying the OLD release's finalizer must not flip the line back
    to released (which would make a later cancellation skip returning stock the order really holds)."""
    pid = _product(c)
    o = _expired_order(c, pid)
    sid = _tx(c, o)
    _run(c, lambda: stock.expire_one(o["id"]))
    _run(c, lambda: shop_routes._process_paid_order(sid))                                     # revived: stock re-reserved
    assert _stock(c, pid) == INITIAL - 2 and _get(c, o["id"])["items"][0]["stock_released"] is False
    old = _run(c, lambda: db.stock_txns.find_one({"order_id": o["id"], "kind": "release"}, {"_id": 0}))
    _run(c, lambda: db.stock_txns.update_one({"id": old["id"]}, {"$set": {"finalized": False}}))
    _run(c, lambda: stock._finalize(old))                                                      # a late, stale finalizer
    assert _get(c, o["id"])["items"][0]["stock_released"] is False
    assert _stock(c, pid) == INITIAL - 2 and sum(_moves(c, o["id"])) == -2 and _ledger_matches_counter(c, pid)
