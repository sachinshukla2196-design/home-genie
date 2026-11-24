"""Programme 02 / W5: index verification, migration safety, repair-job completeness, uniqueness under races, hot-path index use
and the read-only retention (TTL eligibility) report.

Integration, THROWAWAY MongoDB (`homegenies_w5_index_test`, dropped at the end). Indexes are dropped / recreated here on purpose.
Run alone: `pytest tests/test_w5_index_integrity.py -n 0`.
"""
import asyncio
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

DB = "homegenies_w5_index_test"
os.environ.update({"VERCEL": "1", "DB_NAME": DB, "JWT_SECRET": "w5-index-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "w5-cron-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorCollection  # noqa: E402
import server  # noqa: E402
import core  # noqa: E402
import db_indexes  # noqa: E402
import money_guard  # noqa: E402
import stock  # noqa: E402
import sweeps  # noqa: E402
import vendor_lifecycle  # noqa: E402
from core import db, now_iso, new_id, hash_password, create_token  # noqa: E402

SPEC = {s["name"]: s for s in db_indexes.SPECS}
OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        client.portal.call(lambda: server.client.drop_database(DB))
        client.portal.call(db_indexes.apply)
        money_guard.reset_cache()
        yield client
        client.portal.call(lambda: server.client.drop_database(DB))


def run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(autouse=True)
def full_index_set(c):
    """Every test starts and ends with the full, correct index set (anything a test broke is put back)."""
    yield

    async def fix():
        for s in db_indexes.SPECS:
            info = await db[s["coll"]].index_information()
            for n, i in info.items():
                if n == "_id_":
                    continue
                same_keys = db_indexes._key(i) == db_indexes._key(s) or (db_indexes._is_text(s) and db_indexes._is_text(i))
                if (n == s["name"] and not db_indexes._matches(i, s)) or (n != s["name"] and same_keys and n not in
                                                                         {x["name"] for x in db_indexes.SPECS}):
                    await db[s["coll"]].drop_index(n)
        rep = await db_indexes.apply()
        assert not rep["failed"] and not rep["conflict"], rep
    run(c, fix)
    money_guard.reset_cache()


def _drop(c, coll, name):
    run(c, lambda: db[coll].drop_index(name))
    money_guard.reset_cache()


def _plan(c):
    return run(c, db_indexes.plan)


def _ready(c):
    return run(c, lambda: money_guard.readiness(force=True))


# =========================================================================== 1. verification (B-004 + plan)
def test_exact_indexes_are_present_and_every_money_area_is_ready(c):
    p = _plan(c)
    assert not p["missing"] and not p["conflict"] and set(p["present"]) == set(SPEC)
    assert _ready(c)["ready"]


def test_a_missing_money_index_is_missing_in_plan_and_blocks_its_area_only(c):
    _drop(c, "settlements", "settlements_one_open_per_vendor")
    assert "settlements_one_open_per_vendor" in _plan(c)["missing"]
    st = _ready(c)
    assert st["areas"]["settlements"]["state"] == "missing" and all(v["state"] == "ok" for a, v in st["areas"].items() if a != "settlements")


def test_an_identical_index_under_another_name_is_a_conflict_in_plan_and_guard_alike(c):
    """W5 defect: plan() counted it as present (so apply() never repaired it) while the money guard refused it -> permanent block."""
    _drop(c, "wallets", "wallets_user_unique")
    run(c, lambda: db.wallets.create_index([("user_id", 1)], name="user_id_1", unique=True))
    p = _plan(c)
    assert "wallets_user_unique" not in p["present"]
    assert any(x["index"] == "wallets_user_unique" and "other name" in x["reason"] for x in p["conflict"])
    assert _ready(c)["areas"]["wallet"]["state"] == "conflict"
    rep = run(c, db_indexes.apply)
    assert "wallets_user_unique" not in rep["created"] and any(x["index"] == "wallets_user_unique" for x in rep["conflict"])
    assert "user_id_1" in run(c, lambda: db.wallets.index_information())             # never dropped automatically


def test_a_unique_index_with_an_unexpected_collation_is_a_conflict(c):
    """W5 defect: collation was not compared, so a case-insensitive unique index passed as the exact index."""
    _drop(c, "wallets", "wallets_user_unique")
    run(c, lambda: db.wallets.create_index([("user_id", 1)], name="wallets_user_unique", unique=True,
                                           collation={"locale": "en", "strength": 2}))
    assert any(x["index"] == "wallets_user_unique" for x in _plan(c)["conflict"])
    assert _ready(c)["areas"]["wallet"]["state"] == "conflict"


def test_a_text_index_with_another_language_is_a_conflict(c):
    _drop(c, "products", "products_text")
    s = SPEC["products_text"]
    run(c, lambda: db.products.create_index(s["keys"], name="products_text", weights=s["weights"], default_language="english"))
    assert any(x["index"] == "products_text" for x in _plan(c)["conflict"])


def test_unrelated_indexes_change_nothing(c):
    run(c, lambda: db.vendor_ledger.create_index([("note", 1)], name="w5_unrelated"))
    run(c, lambda: db.wallets.create_index([("created_at", -1)], name="w5_unrelated_2"))
    try:
        p = _plan(c)
        assert not p["missing"] and not p["conflict"] and _ready(c)["ready"]
    finally:
        run(c, lambda: db.vendor_ledger.drop_index("w5_unrelated"))
        run(c, lambda: db.wallets.drop_index("w5_unrelated_2"))


def test_repeated_verification_is_stable_and_read_only(c, monkeypatch):
    writes = []
    for m in ("create_index", "drop_index", "insert_one", "update_one", "delete_one", "delete_many"):
        orig = getattr(AsyncIOMotorCollection, m)
        monkeypatch.setattr(AsyncIOMotorCollection, m, (lambda o, n: lambda self, *a, **k: (writes.append((self.name, n)), o(self, *a, **k))[1])(orig, m))
    states = [_ready(c) for _ in range(5)] + [run(c, money_guard.readiness) for _ in range(5)]
    plans = [_plan(c) for _ in range(3)]
    assert all(s["ready"] for s in states) and all(p == plans[0] for p in plans) and writes == []


def test_verification_fails_closed_when_mongodb_is_unavailable(c, monkeypatch):
    from pymongo.errors import ServerSelectionTimeoutError

    async def down(self, *a, **k):
        raise ServerSelectionTimeoutError("no servers")
    monkeypatch.setattr(AsyncIOMotorCollection, "index_information", down)
    money_guard.reset_cache()
    st = _ready(c)
    assert st["ready"] is False and st["error"] == "ServerSelectionTimeoutError"
    assert all(v["state"] == "unknown" for v in st["areas"].values())
    with pytest.raises(HTTPException) as e:
        run(c, lambda: money_guard.ensure("ledger"))
    assert e.value.status_code == 503 and e.value.detail["code"] == "FIN_INDEX_NOT_READY"
    monkeypatch.undo()
    money_guard.reset_cache()
    assert _ready(c)["ready"]                                                     # recovers once the database answers


# =========================================================================== 2. duplicate detection
def test_multikey_duplicates_are_counted_per_element_and_block_creation(c):
    """W5 defect: grouping by the whole `variants` array missed a SKU shared by two products with different variant lists."""
    _drop(c, "products", "products_variant_sku_unique")
    a, b = new_id(), new_id()
    run(c, lambda: db.products.insert_many([
        {"id": a, "sku": "W5-A", "variants": [{"sku": "W5-SHARED"}, {"sku": "W5-A2"}], "created_at": now_iso()},
        {"id": b, "sku": "W5-B", "variants": [{"sku": "W5-SHARED"}], "created_at": now_iso()}]))
    try:
        assert run(c, lambda: db_indexes._duplicates(SPEC["products_variant_sku_unique"])) == 1
        dry = run(c, db_indexes.dry_run)
        assert any(x["index"] == "products_variant_sku_unique" and x["duplicates"] == 1 for x in dry["would_fail"])
        rep = run(c, db_indexes.apply)
        assert any(f["index"] == "products_variant_sku_unique" and "duplicate" in f["reason"] for f in rep["failed"])
        assert run(c, lambda: db.products.count_documents({"id": {"$in": [a, b]}})) == 2          # nothing deleted or merged
    finally:
        run(c, lambda: db.products.delete_many({"id": {"$in": [a, b]}}))


def test_missing_and_null_compound_members_count_as_the_same_key(c):
    """MongoDB indexes a missing field as null; the duplicate count must do the same (wishlist: variant_sku absent vs null)."""
    _drop(c, "wishlist_items", "wishlist_user_product_variant_unique")
    run(c, lambda: db.wishlist_items.insert_many([{"user_id": "w5u", "product_id": "w5p"}, {"user_id": "w5u", "product_id": "w5p", "variant_sku": None}]))
    try:
        assert run(c, lambda: db_indexes._duplicates(SPEC["wishlist_user_product_variant_unique"])) == 1
    finally:
        run(c, lambda: db.wishlist_items.delete_many({"user_id": "w5u"}))


def test_money_duplicate_report_names_records_and_never_changes_them(c):
    _drop(c, "wallet_transactions", "wallet_transactions_op_key_unique")
    ids = [new_id(), new_id()]
    run(c, lambda: db.wallet_transactions.insert_many([{"id": i, "user_id": "w5", "op_key": "w5-dup-op", "amount_paise": 1} for i in ids]))
    try:
        rep = run(c, money_guard.duplicate_report)
        d = rep["indexes"]["wallet_transactions_op_key_unique"]["duplicates"][0]
        assert d["key"] == {"op_key": "w5-dup-op"} and d["count"] == 2 and sorted(d["record_ids"]) == sorted(ids)
        assert run(c, lambda: db.wallet_transactions.count_documents({"op_key": "w5-dup-op"})) == 2
    finally:
        run(c, lambda: db.wallet_transactions.delete_many({"op_key": "w5-dup-op"}))


# =========================================================================== 3. migration: dry run, tracking, interruption
def test_dry_run_lists_every_change_and_duplicate_and_writes_nothing(c, monkeypatch):
    _drop(c, "orders", "orders_order_number_unique")
    _drop(c, "commissions", "commissions_order")
    run(c, lambda: db.orders.insert_many([{"id": new_id(), "order_number": "W5-DUP"}, {"id": new_id(), "order_number": "W5-DUP"}]))
    writes = []
    for m in ("create_index", "drop_index", "insert_one", "update_one", "delete_many"):
        orig = getattr(AsyncIOMotorCollection, m)
        monkeypatch.setattr(AsyncIOMotorCollection, m, (lambda o, n: lambda self, *a, **k: (writes.append((self.name, n)), o(self, *a, **k))[1])(orig, m))
    try:
        dry = run(c, db_indexes.dry_run)
        rep = run(c, lambda: vendor_lifecycle.migrate(apply=False))
        assert "commissions_order" in [x["index"] for x in dry["would_create"]]
        assert any(x["index"] == "orders_order_number_unique" and x["duplicates"] == 1 for x in dry["would_fail"])
        assert dry["spec_version"] == db_indexes.spec_version() and rep["index_dry_run"]["spec_version"] == dry["spec_version"]
        assert writes == []
    finally:
        monkeypatch.undo()
        run(c, lambda: db.orders.delete_many({"order_number": "W5-DUP"}))


def test_migration_runs_are_tracked_with_the_spec_version(c):
    first = run(c, lambda: vendor_lifecycle.migrate(apply=True))
    rec = run(c, lambda: db.index_migrations.find_one({"_id": first["migration_run"]["id"]}))
    assert rec["status"] == "done" and rec["spec_version"] == db_indexes.spec_version() and rec["finished_at"]
    assert first["migration_run"]["interrupted_previous"] == []


def test_an_interrupted_migration_is_detected_and_a_rerun_completes_it(c):
    """A process killed between dropping a legacy index and creating its replacement leaves (a) a run record still "running" and
    (b) neither index. That exact state is reproduced here (a real kill cannot be raised through the test client's event loop);
    the next run reports the interrupted run and closes the gap without touching any document."""
    _drop(c, "users", "users_email_partial_unique")                                        # legacy email_1 dropped, replacement not created
    stale_id = "w5-killed-" + new_id()
    run(c, lambda: db.index_migrations.insert_one({"_id": stale_id, "spec_version": "older", "started_at": now_iso(), "status": "running"}))
    users_before = run(c, lambda: db.users.count_documents({}))
    info = run(c, lambda: db.users.index_information())
    assert "email_1" not in info and "users_email_partial_unique" not in info                 # the gap
    again = run(c, lambda: vendor_lifecycle.migrate(apply=True))
    assert run(c, lambda: db.users.count_documents({})) == users_before
    assert run(c, lambda: db.index_migrations.find_one({"_id": stale_id}))["status"] == "interrupted"
    assert again["migration_run"]["interrupted_previous"], again["migration_run"]
    assert "users_email_partial_unique" in again["indexes"]["created"]
    assert "users_email_partial_unique" in run(c, lambda: db.users.index_information())


# =========================================================================== 4. repair jobs
def _txn(kind, bound, pid, days_old=30):
    tid = new_id()
    return tid, {"id": tid, "key": f"w5:{tid}", "kind": kind, "order_id": "w5o", "lines": [{"i": 0, "product_id": pid, "qty": 1}],
                 "status": "committed", "finalized": True, "bound": bound,
                 "updated_at": (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat(), "created_at": OLD}


def _seed_markers(c, txns, pid):
    ops = {}
    for tid, _ in txns:
        ops[stock._mk("m", tid, 0)] = True
        ops[stock._mk("c", tid, 0)] = True
    run(c, lambda: db.products.insert_one({"id": pid, "sku": "W5-M-" + pid[:6], "stock": 5, "stock_ops": ops}))
    run(c, lambda: db.stock_txns.insert_many([dict(t) for _, t in txns]))


def test_marker_pruning_reaches_every_eligible_transaction_in_one_run(c):
    """W5 defect: one maintenance run pruned at most 200 transactions (find().limit(200)); a backlog never drained."""
    pid = new_id()
    txns = [_txn("release", True, pid) for _ in range(450)]
    _seed_markers(c, txns, pid)
    try:
        n = run(c, lambda: stock.prune_stock_markers())
        assert n == 450
        assert run(c, lambda: db.stock_txns.count_documents({"order_id": "w5o", "pruned": True})) == 450
        assert run(c, lambda: db.products.find_one({"id": pid}))["stock_ops"] == {}
        assert run(c, lambda: stock.prune_stock_markers()) == 0                                # idempotent
    finally:
        run(c, lambda: db.stock_txns.delete_many({"order_id": "w5o"}))
        run(c, lambda: db.products.delete_one({"id": pid}))


def test_records_pruning_must_skip_never_starve_the_rest(c):
    """W5 defect: skipped (unbound reservation) records stayed first in the unordered query and filled every 200-record batch."""
    pid = new_id()
    skipped = [_txn("reserve", False, pid, days_old=40) for _ in range(220)]
    prunable = [_txn("release", True, pid, days_old=20) for _ in range(5)]
    _seed_markers(c, skipped + prunable, pid)
    try:
        assert run(c, lambda: stock.prune_stock_markers()) == 5
        assert run(c, lambda: db.stock_txns.count_documents({"order_id": "w5o", "kind": "reserve", "pruned": True})) == 0   # still skipped
    finally:
        run(c, lambda: db.stock_txns.delete_many({"order_id": "w5o"}))
        run(c, lambda: db.products.delete_one({"id": pid}))


def test_marker_pruning_resumes_after_a_time_limit(c):
    pid = new_id()
    txns = [_txn("release", True, pid) for _ in range(30)]
    _seed_markers(c, txns, pid)
    try:
        first = run(c, lambda: stock.prune_stock_markers(limit=10, max_seconds=0))           # stops after one page, checkpoint kept
        assert first == 10
        assert run(c, lambda: db.job_checkpoints.find_one({"_id": "stock_marker_prune"}))
        assert run(c, lambda: stock.prune_stock_markers(limit=10)) == 20
    finally:
        run(c, lambda: db.stock_txns.delete_many({"order_id": "w5o"}))
        run(c, lambda: db.products.delete_one({"id": pid}))


def test_failure_records_beyond_one_thousand_are_cleared_when_they_succeed(c):
    """W5 defect: the runner loaded at most 1,000 open failures, so later successes never cleared the rest."""
    run(c, lambda: db.w5_sweep_probe.insert_many([{"id": f"k{i:05d}"} for i in range(1005)]))
    state = {"fail": True}

    async def handler(d, dry):
        if state["fail"]:
            raise RuntimeError("w5 simulated")
        return "updated"
    try:
        first = run(c, lambda: sweeps.run_sweep("w5_probe", "w5_sweep_probe", {}, handler, batch=500))
        assert first["failed"] == 1005 and first["failures_open"] == 1005
        state["fail"] = False
        second = run(c, lambda: sweeps.run_sweep("w5_probe", "w5_sweep_probe", {}, handler, batch=500))
        assert second["updated"] == 1005 and second["failures_open"] == 0
        assert run(c, lambda: db.job_failures.count_documents({"job": "w5_probe"})) == 0
    finally:
        run(c, lambda: db.w5_sweep_probe.drop())
        run(c, lambda: db.job_failures.delete_many({"job": "w5_probe"}))
        run(c, lambda: db.job_runs.delete_many({"job": "w5_probe"}))


def test_two_concurrent_runs_of_one_job_apply_each_change_once(c):
    """The runner has no lease: concurrent runs may visit the same records. Handlers are claim-based (update with a state filter),
    so each change still happens exactly once and no record is left behind."""
    run(c, lambda: db.w5_sweep_probe.insert_many([{"id": f"c{i:04d}", "done": False, "n": 0} for i in range(600)]))

    async def handler(d, dry):
        r = await db.w5_sweep_probe.update_one({"id": d["id"], "done": False}, {"$set": {"done": True}, "$inc": {"n": 1}})
        return "updated" if r.modified_count else "skipped"

    async def both():
        return await asyncio.gather(*[sweeps.run_sweep("w5_conc", "w5_sweep_probe", {"done": False}, handler, batch=50) for _ in range(2)])
    try:
        a, b = run(c, both)
        assert a["updated"] + b["updated"] == 600
        assert run(c, lambda: db.w5_sweep_probe.count_documents({"n": {"$ne": 1}})) == 0
    finally:
        run(c, lambda: db.w5_sweep_probe.drop())
        run(c, lambda: db.job_checkpoints.delete_many({"_id": {"$regex": "^w5_conc"}}))
        run(c, lambda: db.job_runs.delete_many({"job": "w5_conc"}))


# =========================================================================== 5. uniqueness under races
def test_concurrent_kyc_submissions_create_one_record(c):
    """W5 defect: find-then-insert let a double submission create two KYC records for one member."""
    uid = new_id()
    run(c, lambda: db.users.insert_one({"id": uid, "distributor_id": "W5K" + uid[:5], "full_name": "W5 KYC", "mobile": "93" + uid[:8].replace("-", "3"),
                                        "password_hash": hash_password("Pass-1234x"), "role": "distributor", "status": "green",
                                        "account_status": "active", "created_at": now_iso()}))
    body = {"pan": "ABCDE1234F", "aadhaar": "123412341234", "account_holder_name": "W5 KYC", "bank_account": "12345678901",
            "ifsc": "HDFC0000001", "bank_name": "HDFC"}
    hdr = {"Authorization": f"Bearer {create_token(uid)}"}
    codes = []
    ts = [threading.Thread(target=lambda: codes.append(c.post("/api/kyc", json=body, headers=hdr).status_code)) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert codes and all(x == 200 for x in codes), codes
    assert run(c, lambda: db.kyc_records.count_documents({"user_id": uid})) == 1


def test_concurrent_first_use_of_a_sequence_creates_one_counter(c):
    """Without a unique index two concurrent first upserts can create two counters and issue the same number twice."""
    async def burst(name):
        return await asyncio.gather(*[core.next_sequence(name, "W", 4) for _ in range(12)])
    for k in range(15):
        name = f"w5seq{k}"
        codes = run(c, lambda: burst(name))
        assert len(set(codes)) == 12, codes
        assert run(c, lambda: db.counters.count_documents({"id": name})) == 1


def test_concurrent_cron_deliveries_with_one_run_id_record_one_run(c):
    rid = "w5-run-" + new_id()
    hdr = {"Authorization": "Bearer w5-cron-secret", "x-webhook-id": rid}
    codes = []
    ts = [threading.Thread(target=lambda: codes.append(c.post("/api/cron/release-points", json={}, headers=hdr).status_code)) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(x == 200 for x in codes), codes
    assert run(c, lambda: db.cron_runs.count_documents({"run_id": rid})) == 1


# =========================================================================== 6. hot paths use an index (explain)
HOT = [
    ("stock_txns", {"id": "x"}, None, "stock journal status per step (stock.py _status)"),
    ("stock_movements", {"txn_id": "x", "line": 0}, None, "movement de-duplication per line (stock.py _log_movement)"),
    ("stock_movements", {"product_id": "x"}, [("created_at", -1)], "vendor inventory history"),
    ("stock_movements", {"order_id": "x", "reason": "dispatch"}, None, "dispatch movement lookup"),
    ("commissions", {"id": "x"}, None, "commission release / admin action"),
    ("commissions", {"order_id": "x"}, None, "refund clawback and admin order view"),
    ("order_refunds", {"id": "x"}, None, "refund execution"),
    ("order_refunds", {"order_id": "x", "status": "PENDING"}, [("created_at", 1)], "ledger reconcile per order"),
    ("refund_cases", {"id": "x"}, None, "refund case actions"),
    ("refund_cases", {"order_id": "x"}, [("created_at", 1)], "admin order view"),
    ("return_cases", {"id": "x"}, None, "return actions"),
    ("return_cases", {"order_id": "x"}, [("created_at", 1)], "returns per order"),
    ("settlements", {"id": "x"}, None, "settlement actions"),
    ("withdrawal_requests", {"id": "x"}, None, "withdrawal actions"),
    ("payment_transactions", {"order_id": "x"}, [("created_at", 1)], "payment in progress (expiry) / admin order view"),
    ("users", {"role": "super_admin"}, None, "admin notifications in refund / stock flows"),
    ("users", {"sponsor_user_id": "x", "status": "green"}, None, "member referral dashboard"),
    ("referral_relationships", {"sponsor_id": "x"}, None, "member referral dashboard"),
    ("referral_relationships", {"referred_user_id": "x"}, None, "registration / audit"),
    ("referral_codes", {"code": "X", "active": True}, None, "registration"),
    ("files", {"storage_path": "a/b.png", "is_deleted": False}, None, "every image request (/api/files)"),
    ("audit_logs", {"entity_id": "x"}, [("created_at", -1)], "admin order / entity history"),
    ("audit_logs", {}, [("created_at", -1)], "audit log viewer"),
    ("vendor_agreements", {"vendor_id": "x", "status": "active"}, None, "commercial terms per order line"),
    ("password_reset_tokens", {"token_hash": "x", "used": False}, None, "password reset"),
    ("orders", {"payment_status": "paid", "created_at": {"$gte": "2026-01-01"}}, None, "admin dashboard figures"),
    ("orders", {"user_id": "x"}, None, "customer order history"),
    ("kyc_records", {"user_id": "x"}, None, "KYC look-up"),
    ("counters", {"id": "x"}, None, "sequence numbers"),
    ("cron_runs", {"run_id": "x"}, None, "cron de-duplication"),
    ("users", {"$or": [{"email": "a@x.test"}, {"mobile": "a@x.test"}, {"distributor_id": "A@X.TEST"}]}, None,
     "member login (auth_routes.py login) - scanned every user before W5"),
    ("users", {"$or": [{"username": "admin"}, {"email": "admin"}]}, None, "admin login"),
    ("users", {"$or": [{"email": "a@x.test"}, {"mobile": "9000000001"}, {"username": "a"}]}, None, "admin team duplicate check"),
    ("job_failures", {"job": "x"}, None, "start of every sweep"),
]


def _stages(plan):
    out = []

    def walk(p):
        if isinstance(p, dict):
            if "stage" in p:
                out.append((p["stage"], p.get("indexName")))
            for v in p.values():
                walk(v)
        elif isinstance(p, list):
            for v in p:
                walk(v)
    walk(plan)
    return out


@pytest.mark.parametrize("coll,flt,srt,why", HOT, ids=[f"{h[0]}:{','.join(h[1]) or 'sort'}" for h in HOT])
def test_hot_query_uses_an_index(c, coll, flt, srt, why):
    async def explain():
        await db[coll].insert_one({"w5_explain": True})
        cmd = {"find": coll, "filter": flt}
        if srt:
            cmd["sort"] = dict(srt)
        try:
            return (await db.command({"explain": cmd, "verbosity": "queryPlanner"}))["queryPlanner"]["winningPlan"]
        finally:
            await db[coll].delete_many({"w5_explain": True})
    stages = _stages(run(c, explain))
    assert any(s == "IXSCAN" for s, _ in stages) and not any(s == "COLLSCAN" for s, _ in stages), (why, stages)


# =========================================================================== 6b. request-time sweeps do not scan settled history
def _request_time_sweeps():
    """The selections of the sweeps that run INSIDE requests (stock.expire_pending_online_orders on checkout / order views;
    returns_routes.ensure_cases_for_flagged_orders on the returns page) - taken from the code where it exposes them, otherwise
    copied from returns_routes.ensure_cases_for_flagged_orders (keep in step)."""
    cut = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return [
        ("expire_pending_online", "orders", {"payment_method": "online", "payment_status": "pending", "status": "payment_pending",
                                             "created_at": {"$lt": stock._cutoff_iso()}}, 50),
        ("expire_upi_claims", "orders", {"payment_status": "claimed", "status": {"$ne": "cancelled"},
                                         "$or": [{"claimed_at": {"$lt": cut}}, {"claimed_at": {"$exists": False}, "updated_at": {"$lt": cut}}]}, 50),
        ("stock_expiry_self_heal", "orders", stock.STUCK_EXPIRY_Q, 50),
        ("stock_txn_recovery", "stock_txns", stock._recoverable_txn_q(), 20),
        ("stock_restock_intents", "orders", {"restock_intents.0": {"$exists": True}, "updated_at": {"$lt": stock._age_cutoff(None)}}, 20),
        ("refund_obligations_late", "orders", {"needs_refund": True, "payment_status": {"$in": ["paid", "partially_refunded"]}}, 200),
        ("refund_obligations_not_supplied", "orders", {"fulfilments.refund_due": True}, 200),
        ("refund_obligations_cancel", "orders", {"refund_due_cancel": True}, 200),
    ]


def test_request_time_sweeps_do_not_scan_settled_history(c):
    """W5 defect: with nothing to repair, journal recovery examined every stock_txns row and the restock / refund-obligation sweeps
    every order - on every checkout, order view or returns page (measured: 30,000-120,000 documents per call at 30,000 orders)."""
    tag = "w5scan"

    async def seed():
        await db.orders.insert_many([{"id": f"{tag}{i:05d}", "order_number": f"{tag.upper()}{i:05d}", "payment_method": "online",
                                      "payment_status": "paid", "status": "delivered", "created_at": OLD, "updated_at": OLD,
                                      "stock_reserved": True, "items": [{"product_id": "p", "quantity": 1, "stock_released": False}],
                                      "fulfilments": [{"vendor_id": "v", "status": "delivered"}]} for i in range(3000)])
        await db.stock_txns.insert_many([{"id": f"{tag}{i:05d}", "key": f"{tag}:{i}", "kind": ("reserve", "release")[i % 2],
                                          "status": "committed", "finalized": True, "bound": True, "updated_at": OLD, "lines": []}
                                         for i in range(6000)])
    run(c, seed)
    try:
        for name, coll, q, batch in _request_time_sweeps():
            async def explain(coll=coll, q=q, batch=batch):
                return (await db.command({"explain": {"find": coll, "filter": q, "sort": {"id": 1}, "limit": batch},
                                          "verbosity": "executionStats"}))["executionStats"]
            st = run(c, explain)
            assert st["totalDocsExamined"] <= 5 and st["totalKeysExamined"] <= 10, (name, st["totalDocsExamined"], st["totalKeysExamined"])
    finally:
        run(c, lambda: db.orders.delete_many({"id": {"$regex": f"^{tag}"}}))
        run(c, lambda: db.stock_txns.delete_many({"id": {"$regex": f"^{tag}"}}))


# =========================================================================== 7. retention report (read-only, no periods invented)
def test_retention_report_counts_expired_records_by_their_own_expiry_and_deletes_nothing(c, monkeypatch):
    import retention
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    run(c, lambda: db.otp_sessions.insert_many([{"identifier": "w5", "purpose": "login", "expires_at": past, "used": False, "created_at": OLD},
                                               {"identifier": "w5", "purpose": "login", "expires_at": future, "used": False, "created_at": now_iso()}]))
    writes = []
    for m in ("insert_one", "update_one", "update_many", "delete_one", "delete_many", "create_index", "drop_index"):
        orig = getattr(AsyncIOMotorCollection, m)
        monkeypatch.setattr(AsyncIOMotorCollection, m, (lambda o, n: lambda self, *a, **k: (writes.append((self.name, n)), o(self, *a, **k))[1])(orig, m))
    try:
        rep = run(c, retention.expiry_report)
        otp = next(r for r in rep["collections"] if r["collection"] == "otp_sessions")
        assert otp["documents"] == 2 and otp["past_own_expiry"] == 1 and otp["ttl_capable"] is False
        assert otp["decision"] == "P0-05" and "period" not in otp                       # no retention period is invented
        never = {r["collection"] for r in rep["collections"] if r["class"] == "never auto-delete"}
        assert {"audit_logs", "vendor_ledger", "wallet_transactions", "payment_transactions", "webhook_events", "refund_cases",
                "settlements", "kyc_records"} <= never
        assert writes == []
    finally:
        monkeypatch.undo()
        run(c, lambda: db.otp_sessions.delete_many({"identifier": "w5"}))
