"""DEF-03: stock-journal crash recovery and the stuck-expiry self-heal reach EVERY eligible record (no per-run ceiling), resume
from a checkpoint, isolate and record failures, retry them, tolerate concurrent workers and duplicate scheduler calls, skip
records that became ineligible, pick up records that become eligible later, never move stock twice and never touch cash-on-
delivery orders. Every scenario ends with a stock reconciliation:

  product stock == start + sum(stock_movements.delta for the product)            (journal and counter agree)
  product stock == start - units still reserved by live (unreleased) order lines (reservations agree)
  at most one forward and one compensating movement per (transaction, line); stock never negative

Integration, THROWAWAY MongoDB (isolated test server only). Run alone: `pytest tests/test_def03_stock_recovery.py -n 0`.
"""
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_def03_stock_test", "JWT_SECRET": "def03-stock-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from pymongo.errors import PyMongoError  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import stock  # noqa: E402
from core import db, new_id  # noqa: E402
from p01_harness import World, seed_world  # noqa: E402

S = {}
START = 200
OLD = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


class Crash(Exception):
    """Simulated process death at a named engine point."""


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "DF")
        client.portal.call(seed)
        yield World(client, S, "DFSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


@pytest.fixture(autouse=True)
def _clean(w):
    """Each scenario starts with no leftover recovery work, checkpoints, run records or failures."""
    yield
    stock._FAULT = None
    async def go():
        await db.job_checkpoints.delete_many({})
        await db.job_failures.delete_many({})
        await db.job_runs.delete_many({})
        await db.stock_txns.update_many({"status": {"$in": ["pending", "rolling_back"]}}, {"$set": {"updated_at": OLD}})
        await stock.run_recovery(min_age_s=0)               # nothing from one scenario leaks into the next
        await stock.heal_stuck_expiries()
    w.run(go)


# ------------------------------------------------------------------------------------------------------------- helpers
def _crashed_reservations(w, pid, n):
    """n reservations interrupted after their stock lines were applied and before the order was saved (process died)."""
    async def go():
        ids = []
        for _ in range(n):
            oid = new_id()

            def hook(point, **ctx):
                if point == "before_decision":
                    raise Crash(point)
            stock._FAULT = hook
            try:
                await stock.reserve_for_order(oid, [{"product_id": pid, "quantity": 1, "name": "x"}], "test")
            except Crash:
                pass
            finally:
                stock._FAULT = None
            ids.append(oid)
        await db.stock_txns.update_many({"order_id": {"$in": ids}}, {"$set": {"updated_at": OLD}})
        return ids
    return w.run(go)


def _stuck_expiries(w, pid, n, qty=1):
    """n online orders whose expiry was claimed (cancelled, payment timeout) but whose stock was never returned."""
    ids = []
    for _ in range(n):
        o = w.order([(pid, qty)], seller=False)
        ids.append(o["id"])
    w.run(lambda: db.orders.update_many({"id": {"$in": ids}}, {"$set": {"status": "cancelled", "cancel_reason": stock.EXPIRY_REASON,
                                                                         "cancelled_at": OLD, "created_at": OLD}}))
    return ids


def _reconcile(w, pids):
    """Journal, counter and reservations agree for each product."""
    async def go():
        out = {}
        for pid in pids:
            p = await db.products.find_one({"id": pid}, {"_id": 0, "stock": 1})
            moves = await db.stock_movements.find({"product_id": pid}, {"_id": 0, "txn_id": 1, "line": 1, "delta": 1,
                                                                        "compensates": 1}).to_list(10000)
            # at most one forward row and one compensating row (abandoned committed reservation) per journal line
            keys = [(m["txn_id"], m["line"], bool(m.get("compensates"))) for m in moves]
            assert len(keys) == len(set(keys)), "a journal line produced two movements of the same kind"
            held = 0
            async for o in db.orders.find({"items.product_id": pid, "stock_reserved": True}, {"_id": 0, "items": 1}):
                held += sum(li["quantity"] for li in o["items"] if li["product_id"] == pid and not li.get("stock_released"))
            assert p["stock"] >= 0
            assert p["stock"] == START + sum(m["delta"] for m in moves), (pid, p["stock"], sum(m["delta"] for m in moves))
            assert p["stock"] == START - held, (pid, p["stock"], held)
            out[pid] = {"stock": p["stock"], "held": held, "movements": len(moves)}
        return out
    return w.run(go)


def _until_complete(w, fn, cap=20):
    """Call a bounded job repeatedly (as the scheduler would) until a pass completes; returns the number of calls."""
    for i in range(1, cap + 1):
        w.run(fn)
        if w.run(lambda: db.job_checkpoints.count_documents({"_id": {"$in": ["stock_txn_recovery", "stock_restock_intents",
                                                                              "stock_expiry_self_heal"]}})) == 0:
            return i
    raise AssertionError("job never completed")


def _released_all(w, ids):
    return all(all(li.get("stock_released") for li in w.get(i)["items"]) for i in ids)


# ------------------------------------------------------------------------------------------------------------- 1, 2
def test_more_than_20_interrupted_reservations_are_all_recovered_over_bounded_runs(w):
    pid = w.product("va", 100, stock=START)
    _crashed_reservations(w, pid, 45)
    assert w.stock(pid) == START - 45
    calls = _until_complete(w, lambda: stock.run_recovery(limit=20, min_age_s=0, max_seconds=0))
    assert calls >= 3                                                     # 45 records in pages of 20: several bounded runs
    assert w.stock(pid) == START                                          # every abandoned reservation was given back
    runs = w.run(lambda: db.job_runs.find({"job": "stock_txn_recovery"}, {"_id": 0}).to_list(50))
    assert sum(r["updated"] for r in runs) == 45 and any(not r["complete"] for r in runs) and any(r["complete"] for r in runs)
    _reconcile(w, [pid])


def test_more_than_20_stuck_expiries_are_all_healed_over_bounded_runs(w):
    pid = w.product("vb", 100, stock=START)
    ids = _stuck_expiries(w, pid, 25, qty=2)
    assert w.stock(pid) == START - 50
    calls = _until_complete(w, lambda: stock.heal_stuck_expiries(limit=10, max_seconds=0))
    assert calls >= 3 and w.stock(pid) == START and _released_all(w, ids)
    _reconcile(w, [pid])


# ------------------------------------------------------------------------------------------------------------- 3, 4, 5
def test_a_crash_halfway_is_isolated_recorded_and_finished_by_the_retry(w):
    pid = w.product("va", 100, stock=START)
    ids = sorted(_stuck_expiries(w, pid, 12))
    victim = ids[5]
    hit = {"n": 0}

    def hook(point, **ctx):
        if point == "before_line" and ctx["txn"]["order_id"] == victim and hit["n"] == 0:
            hit["n"] += 1
            raise Crash(point)                                            # dies after the release txn exists, before its line
    stock._FAULT = hook
    first = w.run(lambda: stock.heal_stuck_expiries(limit=50))
    stock._FAULT = None
    assert first == 11 and not _released_all(w, [victim]) and _released_all(w, [i for i in ids if i != victim])
    fail = w.run(lambda: db.job_failures.find_one({"_id": f"stock_expiry_self_heal:{victim}"}))
    assert fail and fail["attempts"] == 1 and "Crash" in fail["last_error"]
    _reconcile(w, [pid])                                                  # a pending txn holds nothing it did not apply
    second = w.run(lambda: stock.heal_stuck_expiries(limit=50))
    assert second == 1 and _released_all(w, [victim]) and w.stock(pid) == START
    assert w.run(lambda: db.job_failures.count_documents({})) == 0       # the retry cleared the failure record
    _reconcile(w, [pid])


def test_a_database_error_on_one_record_does_not_stop_the_rest_and_the_record_retries(w, monkeypatch):
    pid = w.product("vb", 100, stock=START)
    ids = sorted(_stuck_expiries(w, pid, 8))
    bad = ids[2]
    real = stock.release_stock

    async def flaky(order_id, *a, **k):
        if order_id == bad:
            raise PyMongoError("simulated database error")
        return await real(order_id, *a, **k)
    monkeypatch.setattr(stock, "release_stock", flaky)
    w.run(lambda: stock.heal_stuck_expiries(limit=3))
    assert _released_all(w, [i for i in ids if i != bad]) and not _released_all(w, [bad])
    runs = w.run(lambda: db.job_runs.find({"job": "stock_expiry_self_heal"}, {"_id": 0}).to_list(10))
    assert runs and runs[-1]["failed"] == 1 and runs[-1]["failures_open"] == 1 and runs[-1]["complete"]
    monkeypatch.undo()
    w.run(lambda: stock.heal_stuck_expiries(limit=3))
    assert _released_all(w, ids) and w.stock(pid) == START
    _reconcile(w, [pid])


def test_an_interrupted_execution_resumes_from_its_checkpoint(w):
    pid = w.product("va", 100, stock=START)
    _crashed_reservations(w, pid, 30)
    first = w.run(lambda: stock.recover_stock_txns(limit=10, min_age_s=0, max_seconds=0))
    assert first == 10
    ck = w.run(lambda: db.job_checkpoints.find_one({"_id": "stock_txn_recovery"}))
    assert ck and ck["last_key"]
    rest = w.run(lambda: stock.recover_stock_txns(limit=10, min_age_s=0))
    assert rest == 20 and w.stock(pid) == START
    assert w.run(lambda: db.job_checkpoints.find_one({"_id": "stock_txn_recovery"})) is None
    _reconcile(w, [pid])


# ------------------------------------------------------------------------------------------------------------- 6, 7
def test_two_workers_on_the_same_records_move_stock_once(w):
    pid = w.product("vb", 100, stock=START)
    _crashed_reservations(w, pid, 15)
    ids = _stuck_expiries(w, pid, 15)
    ts = [threading.Thread(target=lambda: w.run(lambda: stock.run_recovery(limit=4, min_age_s=0))) for _ in range(3)]
    ts += [threading.Thread(target=lambda: w.run(lambda: stock.heal_stuck_expiries(limit=4))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    w.run(lambda: stock.run_recovery(min_age_s=0))
    w.run(stock.heal_stuck_expiries)
    assert w.stock(pid) == START and _released_all(w, ids)
    _reconcile(w, [pid])


def test_a_duplicate_scheduler_invocation_changes_nothing_twice(w):
    pid = w.product("va", 100, stock=START)
    ids = _stuck_expiries(w, pid, 6)
    _crashed_reservations(w, pid, 6)
    out = []
    ts = [threading.Thread(target=lambda: out.append(w.c.get("/api/cron/expire-pending-orders",
                                                             headers={"Authorization": "Bearer cron-test-secret"}).status_code))
          for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [200, 200]
    w.run(lambda: stock.run_recovery(min_age_s=0))      # the cron's recovery honours the 120 s age rule; finish the rest
    assert w.stock(pid) == START and _released_all(w, ids)
    _reconcile(w, [pid])


# ------------------------------------------------------------------------------------------------------------- 8, 9
def test_an_order_that_becomes_ineligible_during_the_run_is_left_alone(w, monkeypatch):
    pid = w.product("vb", 100, stock=START)
    ids = sorted(_stuck_expiries(w, pid, 6))
    revived = ids[-1]
    real = stock.release_stock
    state = {"done": False}

    async def revive_one_first(order_id, *a, **k):
        if not state["done"]:                       # while the batch is in progress a late payment revives the last order
            state["done"] = True
            await db.orders.update_one({"id": revived}, {"$set": {"payment_status": "paid", "status": "processing"},
                                                         "$unset": {"cancel_reason": ""}})
        return await real(order_id, *a, **k)
    monkeypatch.setattr(stock, "release_stock", revive_one_first)
    healed = w.run(lambda: stock.heal_stuck_expiries(limit=50))
    monkeypatch.undo()
    assert healed == 5 and _released_all(w, [i for i in ids if i != revived])
    assert not any(li.get("stock_released") for li in w.get(revived)["items"])     # the live order keeps its stock
    assert w.stock(pid) == START - 1
    _reconcile(w, [pid])


def test_a_txn_finished_by_its_own_request_meanwhile_is_skipped(w, monkeypatch):
    pid = w.product("va", 100, stock=START)
    _crashed_reservations(w, pid, 5)
    txns = w.run(lambda: db.stock_txns.find({"status": "pending", "kind": "reserve"}, {"_id": 0}).sort("id", 1).to_list(50))
    late = txns[-1]
    real = stock._recover_one_txn
    state = {"done": False}

    async def finish_one_elsewhere(t):
        if not state["done"]:
            state["done"] = True
            await real(late)                        # another worker finished the last one meanwhile
        return await real(t)
    monkeypatch.setattr(stock, "_recover_one_txn", finish_one_elsewhere)
    n = w.run(lambda: stock.recover_stock_txns(limit=50, min_age_s=0))
    monkeypatch.undo()
    assert n == 4 and w.stock(pid) == START                           # the finished one was re-checked and skipped
    _reconcile(w, [pid])


def test_records_that_become_eligible_after_a_completed_run_are_picked_up_next_time(w):
    pid = w.product("vb", 100, stock=START)
    first = _stuck_expiries(w, pid, 3)
    w.run(stock.heal_stuck_expiries)
    assert w.run(lambda: db.job_checkpoints.find_one({"_id": "stock_expiry_self_heal"})) is None     # the pass completed
    later = _stuck_expiries(w, pid, 3)
    healed = w.run(stock.heal_stuck_expiries)
    assert healed == 3 and _released_all(w, first + later) and w.stock(pid) == START
    _reconcile(w, [pid])


# ------------------------------------------------------------------------------------------------------------- 10, 11, 12
def test_stock_is_never_released_twice_however_often_the_jobs_run(w):
    pid = w.product("va", 100, stock=START)
    ids = _stuck_expiries(w, pid, 10)
    for _ in range(4):
        w.run(stock.heal_stuck_expiries)
        w.run(lambda: stock.run_recovery(min_age_s=0))
    assert w.stock(pid) == START
    rel = w.run(lambda: db.stock_movements.count_documents({"product_id": pid, "delta": {"$gt": 0}}))
    assert rel == 10                                                      # exactly one release movement per order line
    _reconcile(w, [pid])


def test_live_orders_and_cash_on_delivery_are_never_restored(w):
    pid = w.product("vb", 100, stock=START)
    pending = w.order([(pid, 2)], seller=False)                           # online, still inside its payment window
    cod_new = w.order([(pid, 3)], method="cod", seller=False)
    cod_acc = w.order([(pid, 4)], method="cod", seller=False)
    assert w.step("vb", cod_acc["id"], "accepted").status_code == 200
    paid = w.paid_order([(pid, 5)])
    w.run(lambda: db.orders.update_many({"id": {"$in": [cod_new["id"], cod_acc["id"]]}}, {"$set": {"created_at": OLD}}))
    for _ in range(2):
        w.run(stock.heal_stuck_expiries)
        w.run(lambda: stock.run_recovery(min_age_s=0))
        w.run(lambda: stock.expire_pending_online_orders(limit=50))
    assert w.stock(pid) == START - 14                                     # every live reservation is still held
    for o in (pending, cod_new, cod_acc, paid):
        assert not any(li.get("stock_released") for li in w.get(o["id"])["items"])
    _reconcile(w, [pid])


def test_reservations_and_the_journal_reconcile_after_a_mixed_recovery(w):
    pa, pb = w.product("va", 100, stock=START), w.product("vb", 100, stock=START)
    _crashed_reservations(w, pa, 22)
    _stuck_expiries(w, pa, 21)
    _stuck_expiries(w, pb, 23)
    live = w.order([(pa, 1), (pb, 1)], method="cod", seller=False)
    _until_complete(w, lambda: stock.run_recovery(limit=7, min_age_s=0, max_seconds=0))
    _until_complete(w, lambda: stock.heal_stuck_expiries(limit=7, max_seconds=0))
    r = _reconcile(w, [pa, pb])
    assert r[pa]["held"] == 1 and r[pb]["held"] == 1 and w.stock(pa) == START - 1 and w.stock(pb) == START - 1
    assert all(not li.get("stock_released") for li in w.get(live["id"])["items"])


# ------------------------------------------------------------------------------------------------------------- dry run
def test_a_dry_run_counts_the_work_and_writes_nothing(w):
    pid = w.product("va", 100, stock=START)
    _stuck_expiries(w, pid, 5)                 # first: placing orders runs the request-time sweep, which would recover...
    _crashed_reservations(w, pid, 4)           # ...these aged crashed reservations if they existed already
    before = (w.stock(pid), w.run(lambda: db.stock_movements.count_documents({"product_id": pid})))
    rec = w.run(lambda: stock.run_recovery(limit=2, min_age_s=0, dry_run=True))
    heal = w.run(lambda: stock.heal_stuck_expiries(limit=2, dry_run=True))
    assert rec["txns"] == 4 and heal == 5
    assert (w.stock(pid), w.run(lambda: db.stock_movements.count_documents({"product_id": pid}))) == before
    assert w.run(lambda: db.job_checkpoints.count_documents({})) == 0 and w.run(lambda: db.job_runs.count_documents({})) == 0
    import cron_routes
    dry = w.run(lambda: cron_routes.run_maintenance(budget_seconds=10, dry_run=True))
    assert dry["stuck_expiries"] == 5 and "stock_recovery" in dry


def test_an_idle_run_writes_no_records(w):
    w.run(lambda: stock.run_recovery(min_age_s=0))
    w.run(stock.heal_stuck_expiries)
    w.run(lambda: db.job_runs.delete_many({}))
    w.run(lambda: db.job_checkpoints.delete_many({}))
    for _ in range(3):                                                    # the request-time calls do nothing when idle
        w.run(lambda: stock.run_recovery(min_age_s=0))
        w.run(stock.heal_stuck_expiries)
    assert w.run(lambda: db.job_runs.count_documents({})) == 0
    assert w.run(lambda: db.job_checkpoints.count_documents({})) == 0
