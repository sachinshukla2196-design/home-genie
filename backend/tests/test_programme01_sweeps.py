"""Programme 01 / B-005: repair and release jobs reach EVERY record - no fixed ceiling (the ledger repair used to stop at the 500
oldest paid orders, the refund-obligation repair at 200, commission release at 5,000) - with keyset pagination, a durable
checkpoint, per-record failure isolation, a dry run that writes nothing, and no duplicate money on repeats or races.

Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_sweeps.py -n 0`.
"""
import os
import threading

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_sweeps_test", "JWT_SECRET": "p01-sweeps-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger  # noqa: E402
import returns_routes  # noqa: E402
import cron_routes  # noqa: E402
from commission import release_due_points  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402
from p01_harness import World, seed_world, OLD  # noqa: E402

S = {}


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "SW")
        client.portal.call(seed)
        yield World(client, S, "SWSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _synthetic_paid_orders(w, n, tag, vendors=("va", "vb"), **extra):
    """n paid multi-vendor orders written directly (the payment path is covered elsewhere); no ledger entries yet."""
    docs = []
    for i in range(n):
        oid = f"{tag}-{i:05d}-{new_id()[:8]}"
        items = [{"product_id": "p-" + v, "vendor_id": S[v]["id"], "quantity": 1, "price": 100.0 + j, "total": 100.0 + j,
                  "total_paise": 10000 + 100 * j} for j, v in enumerate(vendors)]
        tot = sum(li["total_paise"] for li in items)
        docs.append({"id": oid, "order_number": f"{tag}{i:06d}", "user_id": S["cust"]["id"], "payment_method": "online",
                     "payment_status": "paid", "status": "processing", "paid_at": now_iso(), "created_at": now_iso(), "items": items,
                     "fulfilments": [{"vendor_id": S[v]["id"], "status": "new", "events": []} for v in vendors],
                     "total_paise": tot, "total": tot / 100, "subtotal_paise": tot, "subtotal": tot / 100, "prices_include_gst": True,
                     "tag": tag, **extra})
    w.run(lambda: db.orders.insert_many([dict(d) for d in docs]))
    return [d["id"] for d in docs]


@pytest.fixture(autouse=True)
def _drop_synthetic_orders(w):
    """Each ledger test removes its synthetic orders afterwards, so later full passes do not rescan them (test speed only)."""
    yield
    async def go():
        ids = [o["id"] async for o in db.orders.find({"tag": {"$regex": "^L"}}, {"_id": 0, "id": 1})]
        await db.vendor_ledger.delete_many({"order_id": {"$in": ids}})
        await db.orders.delete_many({"id": {"$in": ids}})
    w.run(go)


def _sales(w, tag):
    async def go():
        ids = [o["id"] async for o in db.orders.find({"tag": tag}, {"_id": 0, "id": 1})]
        return await db.vendor_ledger.count_documents({"order_id": {"$in": ids}, "type": "SALE_COLLECTED"})
    return w.run(go)


# ================================================================ the ledger repair: no 500 ceiling
def test_ledger_repair_reaches_more_than_1000_orders_in_one_full_pass(w):
    _synthetic_paid_orders(w, 1100, "L1100")
    dry = w.run(lambda: ledger.reconcile_ledger(dry_run=True))
    assert dry["sweep"]["eligible"] >= 1100 and _sales(w, "L1100") == 0                  # the dry run wrote nothing
    res = w.run(ledger.reconcile_ledger)
    assert res["sweep"]["complete"] and res["sweep"]["failed"] == 0
    assert _sales(w, "L1100") == 2200                                                     # every order, both vendors
    again = w.run(ledger.reconcile_ledger)
    assert again["sales"] == 0 and _sales(w, "L1100") == 2200                             # a repeat adds nothing


def test_an_interrupted_repair_resumes_from_its_checkpoint(w):
    _synthetic_paid_orders(w, 600, "LCKPT", vendors=("va",))
    first = w.run(lambda: ledger.reconcile_ledger(limit=100, max_seconds=0))            # stops after one page
    assert not first["sweep"]["complete"] and first["sweep"]["scanned"] == 100
    ck = w.run(lambda: db.job_checkpoints.find_one({"_id": "ledger_reconcile"}))
    assert ck["last_key"] == first["sweep"]["next_key"]
    rest = w.run(lambda: ledger.reconcile_ledger(limit=100))
    assert rest["sweep"]["resumed_from"] == first["sweep"]["next_key"] and rest["sweep"]["complete"]
    assert w.run(lambda: db.job_checkpoints.find_one({"_id": "ledger_reconcile"})) is None
    w.run(ledger.reconcile_ledger)                                                        # orders before the checkpoint: next pass
    assert _sales(w, "LCKPT") == 600


def test_orders_inserted_during_a_run_are_reached_in_this_pass_or_the_next(w, monkeypatch):
    _synthetic_paid_orders(w, 50, "LINS", vendors=("va",))
    real = ledger.post_order_collected
    added = {"done": False}

    async def hook(o, *a, **k):
        if not added["done"]:
            added["done"] = True
            for prefix in ("LINS-00000-0", "zzzz-LINS"):                                  # one behind the cursor, one ahead
                doc = {"id": prefix + new_id()[:6], "order_number": prefix, "user_id": S["cust"]["id"], "payment_method": "online",
                       "payment_status": "paid", "status": "processing", "paid_at": now_iso(), "tag": "LINS",
                       "items": [{"vendor_id": S["va"]["id"], "total_paise": 5000, "total": 50.0}],
                       "fulfilments": [{"vendor_id": S["va"]["id"], "status": "new"}], "total_paise": 5000, "total": 50.0}
                await db.orders.insert_one(doc)
        return await real(o, *a, **k)
    monkeypatch.setattr(ledger, "post_order_collected", hook)
    w.run(ledger.reconcile_ledger)
    monkeypatch.undo()
    w.run(ledger.reconcile_ledger)
    assert _sales(w, "LINS") == 52


def test_one_failing_order_does_not_stop_the_others_and_is_retried_later(w, monkeypatch):
    ids = sorted(_synthetic_paid_orders(w, 30, "LFAIL", vendors=("va",)))
    bad = ids[11]
    real = ledger.post_order_collected

    async def flaky(o, *a, **k):
        if o["id"] == bad:
            raise RuntimeError("corrupt order record")
        return await real(o, *a, **k)
    monkeypatch.setattr(ledger, "post_order_collected", flaky)
    res = w.run(ledger.reconcile_ledger)
    monkeypatch.undo()
    assert res["sweep"]["failed"] == 1 and res["sweep"]["failures"][0]["key"] == bad and res["sweep"]["complete"]
    assert _sales(w, "LFAIL") == 29
    w.run(ledger.reconcile_ledger)
    assert _sales(w, "LFAIL") == 30


def test_existing_ledger_entries_are_never_changed_and_concurrent_runs_post_once(w):
    ids = _synthetic_paid_orders(w, 80, "LCONC", vendors=("va",))
    mine = {"id": new_id(), "vendor_id": S["va"]["id"], "type": "SALE_COLLECTED", "amount_paise": 12345, "amount": 123.45,
            "order_id": ids[0], "source_key": f"sale:{ids[0]}:{S['va']['id']}", "posted_at": OLD, "status": "posted"}
    w.run(lambda: db.vendor_ledger.insert_one(dict(mine)))
    ts = [threading.Thread(target=lambda: w.run(ledger.reconcile_ledger)) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert _sales(w, "LCONC") == 80
    kept = w.run(lambda: db.vendor_ledger.find_one({"source_key": mine["source_key"]}, {"_id": 0}))
    assert kept == mine                                                                   # the existing entry is untouched


# ================================================================ refund obligations: no 200 ceiling
def test_more_than_200_paid_cancellations_all_get_their_refund_case(w):
    ids = _synthetic_paid_orders(w, 250, "RCAN", vendors=("va",), refund_due_cancel=True)
    w.run(lambda: db.orders.update_many({"tag": "RCAN"}, {"$set": {"status": "cancelled"}}))
    dry = w.run(lambda: returns_routes.ensure_cases_for_flagged_orders(dry_run=True))
    assert dry["paid_cancellation"]["eligible"] == 250 and w.run(lambda: db.refund_cases.count_documents({"order_id": {"$in": ids}})) == 0
    w.run(returns_routes.ensure_cases_for_flagged_orders)
    w.run(returns_routes.ensure_cases_for_flagged_orders)
    assert w.run(lambda: db.refund_cases.count_documents({"order_id": {"$in": ids}, "kind": "cancellation"})) == 250


# ================================================================ commission release across pages, with protected records
def test_release_pages_through_every_commission_and_never_releases_rto_or_pending_refund_orders(w):
    pid = w.product("va", 1000, stock=500)
    pid_b = w.product("vb", 1000, stock=500)
    plain, rto, refund = [], [], []
    for i in range(24):
        o = w.paid_order([(pid, 1), (pid_b, 1)])
        if i % 6 == 0:
            w.deliver("va", o["id"])
            assert w.rto("vb", o["id"]).status_code == 200                               # B's goods never arrived
            rto.append(o["id"])
        elif i % 6 == 1:
            w.deliver("va", o["id"])
            w.deliver("vb", o["id"])
            case, _ = w.run(lambda: returns_routes.open_refund_case(w_get(o["id"]), "goodwill", 10000, "pending", "pr:" + o["id"]))
            refund.append(o["id"])
        else:
            w.deliver("va", o["id"])
            w.deliver("vb", o["id"])
            plain.append(o["id"])
        w.age(o["id"])
    dry = w.run(lambda: release_due_points(dry_run=True, batch=5))
    assert dry["would_release"] == len(plain) and dry["released"] == 0
    assert all(c["released_at"] is None for oid in plain for c in w.comms(oid))           # the dry run wrote nothing
    res = w.run(lambda: release_due_points(batch=5))                                       # 24 commissions, pages of 5
    assert res["complete"] and res["failed"] == 0 and res["released"] == len(plain)
    assert all(c["released_at"] for oid in plain for c in w.comms(oid))
    assert all(c["released_at"] is None for oid in rto + refund for c in w.comms(oid))     # protected
    again = w.run(lambda: release_due_points(batch=5))
    assert again["released"] == 0 and w.wallet_ok()                                        # never twice


_ORDERS = {}


def w_get(oid):
    return _ORDERS[oid]


@pytest.fixture(autouse=True)
def _order_cache(w):
    """Lets a lambda passed to the portal read an order fetched OUTSIDE the event loop (no nested portal calls)."""
    real = w.paid_order

    def paid_order(lines):
        o = real(lines)
        _ORDERS[o["id"]] = o
        return o
    w.paid_order = paid_order
    yield
    w.paid_order = real


# ================================================================ the daily maintenance pass
def test_daily_maintenance_runs_every_sweep_records_itself_and_honours_its_budget(w):
    r = w.c.get("/api/cron/expire-pending-orders", headers={"Authorization": "Bearer cron-test-secret"})
    assert r.status_code == 200, r.text
    body = r.json()
    for k in ("completion_repair", "refund_obligations", "returns_repaired", "ledger", "settlements_repaired", "expired"):
        assert k in body, k
    assert w.run(lambda: db.cron_runs.count_documents({"job": "maintenance"})) >= 1
    dry = w.run(lambda: cron_routes.run_maintenance(budget_seconds=5, dry_run=True))
    assert dry["dry_run"] and "expired" not in dry
