"""Programme 01 / B-004: money-changing writes fail closed (HTTP 503 FIN_INDEX_NOT_READY) while a protective unique index is
missing or defined differently; reads keep working; duplicates are reported by record, never deleted; the migration is
repeatable. The isolated test database is the ONLY database touched (indexes are dropped and recreated here on purpose).

Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_money_guard.py -n 0`.
"""
import logging
import os
import threading

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_money_guard_test", "JWT_SECRET": "p01-guard-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "RAZORPAY_WEBHOOK_SECRET": "p01-guard-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger  # noqa: E402
import money_guard  # noqa: E402
import returns_routes  # noqa: E402
import vendor_lifecycle  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402
from p01_harness import World, seed_world, hdr  # noqa: E402

S = {}


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "MG")
        client.portal.call(seed)
        yield World(client, S, "MGSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


@pytest.fixture(autouse=True)
def restore(w):
    """Every test starts and ends with the full, correct index set."""
    yield
    async def fix():
        for coll, name in (("vendor_ledger", "vendor_ledger_source_key_unique"), ("wallet_transactions", "wallet_transactions_op_key_unique"),
                           ("stock_txns", "stock_txns_key_unique"), ("refund_cases", "refund_cases_source_key_unique"),
                           ("webhook_events", "webhook_events_event_unique")):
            info = await db[coll].index_information()
            spec = next(s for s in db_indexes.SPECS if s["name"] == name)
            if name in info and not db_indexes._matches(info[name], spec):
                await db[coll].drop_index(name)
        await db.vendor_ledger.delete_many({"source_key": {"$regex": "^dup-test:"}})
        rep = await db_indexes.apply()
        assert not rep["failed"], rep["failed"]
    w.run(fix)
    money_guard.reset_cache()


def _drop(w, coll, name):
    w.run(lambda: db[coll].drop_index(name))
    money_guard.reset_cache()


def _ready(w):
    return w.run(lambda: money_guard.readiness(force=True))


# ================================================================ readiness
def test_all_present_means_ready(w):
    st = _ready(w)
    assert st["ready"] and all(v["state"] == "ok" for v in st["areas"].values())
    w.run(lambda: money_guard.ensure(*money_guard.AREAS))          # no exception


def test_a_missing_index_blocks_only_its_own_area(w):
    _drop(w, "vendor_ledger", "vendor_ledger_source_key_unique")
    st = _ready(w)
    assert not st["ready"] and st["areas"]["ledger"] == {"state": "missing", "missing": ["vendor_ledger_source_key_unique"], "conflict": []}
    assert all(v["state"] == "ok" for a, v in st["areas"].items() if a != "ledger")
    with pytest.raises(HTTPException) as e:
        w.run(lambda: ledger.post_entry(S["va"]["id"], ledger.ADJUSTMENT, 100, "guard-test:" + new_id()))
    assert e.value.status_code == 503 and e.value.detail["code"] == "FIN_INDEX_NOT_READY" and e.value.detail["areas"] == ["ledger"]
    assert w.run(lambda: db.vendor_ledger.count_documents({"source_key": {"$regex": "^guard-test:"}})) == 0
    w.run(lambda: money_guard.ensure("refunds", "stock"))          # other areas still work


def test_same_name_and_keys_but_not_unique_is_a_conflict_not_present(w):
    _drop(w, "vendor_ledger", "vendor_ledger_source_key_unique")
    w.run(lambda: db.vendor_ledger.create_index([("source_key", 1)], name="vendor_ledger_source_key_unique"))
    money_guard.reset_cache()
    assert _ready(w)["areas"]["ledger"]["state"] == "conflict"
    with pytest.raises(HTTPException):
        w.run(lambda: money_guard.ensure("ledger"))


def test_a_unique_index_without_its_partial_filter_is_a_conflict(w):
    _drop(w, "wallet_transactions", "wallet_transactions_op_key_unique")
    w.run(lambda: db.wallet_transactions.create_index([("op_key", 1)], name="wallet_transactions_op_key_unique", unique=True, sparse=True))
    money_guard.reset_cache()
    assert _ready(w)["areas"]["wallet"]["state"] == "conflict"


def test_an_identical_index_under_another_name_is_not_accepted(w):
    _drop(w, "stock_txns", "stock_txns_key_unique")
    w.run(lambda: db.stock_txns.create_index([("key", 1)], name="stock_txns_key_unique_v2", unique=True))
    try:
        money_guard.reset_cache()
        assert _ready(w)["areas"]["stock"]["state"] == "conflict"
    finally:
        w.run(lambda: db.stock_txns.drop_index("stock_txns_key_unique_v2"))


# ================================================================ writes fail closed, reads keep working
def test_order_creation_refused_while_stock_or_order_protection_is_missing_and_reads_still_work(w):
    pid = w.product("va", 500)
    _drop(w, "stock_txns", "stock_txns_key_unique")
    before = w.stock(pid)
    r = w.c.post("/api/orders", json={"items": [{"product_id": pid, "quantity": 1}], "address": __import__("p01_harness").ADDR,
                                      "payment_method": "online"}, headers=hdr(S["cust"]["id"]))
    assert r.status_code == 503 and r.json()["detail"]["code"] == "FIN_INDEX_NOT_READY"
    assert w.stock(pid) == before                                     # nothing reserved
    assert w.c.get("/api/products").status_code == 200                 # browsing works
    assert w.c.get("/api/orders", headers=hdr(S["cust"]["id"])).status_code == 200   # order history works
    assert w.c.get(f"/api/products/{pid}").status_code == 200


def test_refund_confirmation_is_refused_before_anything_is_claimed(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    case, _ = w.run(lambda: returns_routes.open_refund_case(o, "goodwill", 20000, "t", "mg:" + o["id"]))
    assert w.act("adm", case["id"], "initiate").status_code == 200
    _drop(w, "vendor_ledger", "vendor_ledger_source_key_unique")
    r = w.confirm("fin2", case["id"], "UTR-MG-" + o["id"][:6])
    assert r.status_code == 503
    got = w.case(case["id"])
    assert got["status"] == "initiated" and "confirming_reference" not in got and w.events(o["id"]) == []


def test_gateway_webhook_is_refused_and_nothing_is_recorded(w):
    import hashlib
    import hmac
    import json
    _drop(w, "webhook_events", "webhook_events_event_unique")
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_x", "order_id": "order_x",
                                                                                         "status": "captured", "currency": "INR", "amount": 100}}}}).encode()
    sig = hmac.new(b"p01-guard-secret", body, hashlib.sha256).hexdigest()
    r = w.c.post("/api/webhook/razorpay", content=body, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_guard",
                                                                   "Content-Type": "application/json"})
    assert r.status_code == 503                                         # the gateway will deliver it again later
    assert w.run(lambda: db.webhook_events.count_documents({"event_id": "evt_guard"})) == 0


def test_a_paid_order_whose_completion_is_blocked_is_finished_once_protection_returns(w):
    import shop_routes
    import order_completion
    o = w.order([(w.product("va", 1000), 1)])
    sid = w.tx(o)
    _drop(w, "vendor_ledger", "vendor_ledger_source_key_unique")
    with pytest.raises(HTTPException):
        w.run(lambda: shop_routes._process_paid_order(sid))
    mid = w.get(o["id"])
    assert mid["payment_status"] == "paid" and mid.get("completion_due") and w.ledger(o["id"]) == []
    w.run(db_indexes.apply)
    money_guard.reset_cache()
    assert w.run(order_completion.repair_incomplete_completions)["updated"] >= 1
    assert len(w.ledger(o["id"], "SALE_COLLECTED")) == 1 and "completion_due" not in w.get(o["id"])


# ================================================================ duplicates and the migration
def test_duplicates_are_reported_by_record_and_never_deleted(w):
    _drop(w, "vendor_ledger", "vendor_ledger_source_key_unique")
    key = "dup-test:" + new_id()
    rows = [{"id": new_id(), "vendor_id": S["va"]["id"], "type": "ADJUSTMENT", "amount_paise": 100, "source_key": key, "posted_at": now_iso()}
            for _ in range(2)]
    w.run(lambda: db.vendor_ledger.insert_many([dict(r) for r in rows]))
    rep = w.run(money_guard.duplicate_report)
    found = rep["indexes"]["vendor_ledger_source_key_unique"]["duplicates"]
    assert not rep["clean"] and any(d["key"] == {"source_key": key} and sorted(d["record_ids"]) == sorted(r["id"] for r in rows) for d in found)
    res = w.run(db_indexes.apply)
    assert any(f["index"] == "vendor_ledger_source_key_unique" for f in res["failed"])
    assert w.run(lambda: db.vendor_ledger.count_documents({"source_key": key})) == 2         # nothing deleted or merged
    money_guard.reset_cache()
    assert _ready(w)["areas"]["ledger"]["state"] == "missing"                                  # and the area stays blocked
    dry = w.run(lambda: vendor_lifecycle.migrate(apply=False))
    assert "vendor_ledger_source_key_unique" in dry["money_duplicates"]["indexes"] and not dry["money_protection"]["ready"]


def test_the_migration_is_repeatable_and_preserves_records(w):
    before = w.run(lambda: db.vendor_ledger.count_documents({}))
    first = w.run(lambda: vendor_lifecycle.migrate(apply=True))
    second = w.run(lambda: vendor_lifecycle.migrate(apply=True))
    assert second["indexes"]["created"] == [] and not second["indexes_failed"] and second["money_protection"]["ready"]
    assert first["money_duplicates"]["clean"] and w.run(lambda: db.vendor_ledger.count_documents({})) == before


def test_concurrent_identical_ledger_posts_write_one_row(w):
    key = "conc-test:" + new_id()
    out = []
    ts = [threading.Thread(target=lambda: out.append(w.run(lambda: ledger.post_entry(S["va"]["id"], ledger.ADJUSTMENT, 500, key))[1]))
          for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count(True) == 1 and w.run(lambda: db.vendor_ledger.count_documents({"source_key": key})) == 1


# ================================================================ diagnostics
def test_startup_names_the_blocked_area_and_finance_can_see_it(w, caplog):
    _drop(w, "refund_cases", "refund_cases_source_key_unique")
    with caplog.at_level(logging.ERROR, logger="homegenies"):
        st = w.run(money_guard.startup_report)
    assert not st["ready"] and any("area refunds is BLOCKED" in r.getMessage() for r in caplog.records)
    r = w.c.get("/api/admin/finance/system-integrity", headers=hdr(S["fin"]["id"]))
    assert r.status_code == 200 and r.json()["money_protection"]["areas"]["refunds"]["state"] == "missing"
    assert w.c.get("/api/admin/finance/system-integrity", headers=hdr(S["support"]["id"])).status_code == 403
    assert w.c.get("/api/admin/finance/system-integrity", headers=hdr(S["cust"]["id"])).status_code in (401, 403)
