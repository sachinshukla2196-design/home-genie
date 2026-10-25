"""Index safety: importing and starting the app change no indexes; the migration's dry run is read-only; apply creates exactly the
intended indexes; re-running is idempotent; duplicates and conflicts fail safely without touching data.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_db_indexes.py -n 0`.
"""
import hashlib
import json
import os
import subprocess
import sys

import pytest

DB = "homegenies_index_test"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ.update({"VERCEL": "1", "DB_NAME": DB, "JWT_SECRET": "index-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorCollection  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import vendor_lifecycle as VL  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402

WRITE_METHODS = ["insert_one", "insert_many", "update_one", "update_many", "delete_one", "delete_many", "replace_one",
                 "create_index", "create_indexes", "drop_index", "drop_indexes", "find_one_and_update", "find_one_and_replace",
                 "find_one_and_delete", "bulk_write"]


@pytest.fixture
def writes(monkeypatch):
    """Records every write-type call the driver receives, as (collection, method)."""
    calls = []
    for name in WRITE_METHODS:
        orig = getattr(AsyncIOMotorCollection, name)

        def make(orig, name):
            def wrapper(self, *a, **k):
                calls.append((self.name, name))
                return orig(self, *a, **k)
            return wrapper
        monkeypatch.setattr(AsyncIOMotorCollection, name, make(orig, name))
    return calls


async def _snapshot():
    """Every collection's documents and indexes, as a digest. Identical digests mean nothing changed."""
    out = {}
    for name in sorted(await db.list_collection_names()):
        docs = await db[name].find({}, {"_id": 1}).sort("_id", 1).to_list(100000)
        full = await db[name].find({}, {"_id": 0}).sort("_id", 1).to_list(100000)
        out[name] = {"docs": hashlib.sha256(json.dumps(full, default=str, sort_keys=True).encode()).hexdigest(),
                     "count": len(docs), "indexes": sorted(str(sorted(v.get("key", []))) + str(v.get("unique", False)) + str(v.get("partialFilterExpression")) + str(v.get("expireAfterSeconds")) for v in (await db[name].index_information()).values())}
    return out


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        async def fresh():
            await server.client.drop_database(DB)
        c.portal.call(fresh)
        yield c
        c.portal.call(lambda: server.client.drop_database(DB))


def _fresh(c):
    c.portal.call(lambda: server.client.drop_database(DB))


# ============================================================ 1. importing changes nothing
def test_importing_the_backend_changes_no_indexes():
    code = (
        "import sys, os\n"
        f"sys.path.insert(0, {BACKEND!r})\n"
        "from motor.motor_asyncio import AsyncIOMotorCollection as C\n"
        "calls = []\n"
        "for n in ['create_index', 'create_indexes', 'drop_index', 'drop_indexes']:\n"
        "    o = getattr(C, n)\n"
        "    setattr(C, n, (lambda o, n: (lambda self, *a, **k: (calls.append(n), o(self, *a, **k))[1]))(o, n))\n"
        "import server, db_indexes, vendor_lifecycle\n"
        "print('INDEX_CALLS', len(calls))\n"
    )
    env = {**os.environ, "DB_NAME": "homegenies_index_import_test", "VERCEL": "1"}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-800:]
    assert "INDEX_CALLS 0" in out.stdout


# ============================================================ 2. starting the app changes nothing (and keeps legacy indexes)
def test_starting_the_app_creates_and_drops_no_indexes(client, writes):
    async def prepare():
        await db.users.create_index("email", name="email_1")          # a legacy index that must survive startup untouched
    client.portal.call(prepare)
    before = client.portal.call(_snapshot)
    writes.clear()
    client.get("/api/health")                                          # the first request runs the startup routine once
    client.get("/api/health")
    index_writes = [w for w in writes if w[1] in ("create_index", "create_indexes", "drop_index", "drop_indexes")]
    assert index_writes == []
    after = client.portal.call(_snapshot)
    assert before["users"]["indexes"] == after["users"]["indexes"]     # the legacy index is still there
    assert "email_1" in client.portal.call(lambda: db.users.index_information())


# ============================================================ 3. the dry run is read-only
def test_dry_run_performs_no_index_or_document_writes(client, writes):
    _fresh(client)

    async def seed():
        await db.vendors.insert_many([
            {"id": new_id(), "user_id": "dup-user", "vendor_code": "VD000101", "status": "draft", "created_at": now_iso()},
            {"id": new_id(), "user_id": "dup-user", "vendor_code": "VD000102", "status": "draft", "created_at": now_iso()},
            {"id": new_id(), "user_id": "solo-user", "status": "approved", "created_at": now_iso()}])
        await db.users.insert_one({"id": new_id(), "distributor_id": "D1", "email": "a@example.test", "mobile": "9100009001", "created_at": now_iso()})
    client.portal.call(seed)
    before = client.portal.call(_snapshot)
    writes.clear()
    client.portal.call(lambda: VL.migrate(apply=False))
    client.portal.call(db_indexes.plan)
    client.portal.call(db_indexes.check_missing)
    assert writes == [], f"dry run wrote: {writes}"
    assert client.portal.call(_snapshot) == before


# ============================================================ 4. apply creates exactly the intended indexes
def test_apply_creates_only_the_intended_missing_indexes(client, writes):
    _fresh(client)
    writes.clear()
    report = client.portal.call(db_indexes.apply)
    created = set(report["created"])
    assert created == {s["name"] for s in db_indexes.SPECS}, report
    assert report["failed"] == [] and report["dropped"] == [] and report["conflict"] == []
    names = set()
    for coll in {s["coll"] for s in db_indexes.SPECS}:
        names |= set(client.portal.call(lambda c=coll: db[c].index_information()).keys())
    assert {s["name"] for s in db_indexes.SPECS} <= names
    assert not [w for w in writes if w[1] in ("insert_one", "insert_many", "update_one", "update_many", "delete_one", "delete_many")]


# ============================================================ 5. re-running is idempotent
def test_rerunning_apply_does_nothing_and_damages_nothing(client, writes):
    before = client.portal.call(_snapshot)
    writes.clear()
    report = client.portal.call(db_indexes.apply)
    assert report["created"] == [] and report["dropped"] == [] and report["failed"] == []
    assert [w for w in writes if w[1] in ("create_index", "create_indexes", "drop_index", "drop_indexes")] == []
    assert client.portal.call(_snapshot) == before


# ============================================================ 6a. duplicates fail safely, with no personal data in the report
def test_duplicate_values_stop_one_index_safely_and_are_not_repeated_in_the_report(client):
    _fresh(client)

    async def seed():
        await db.vendors.insert_many([
            {"id": new_id(), "user_id": "u-a", "vendor_code": "VDDUP999", "status": "draft", "created_at": now_iso()},
            {"id": new_id(), "user_id": "u-b", "vendor_code": "VDDUP999", "status": "draft", "created_at": now_iso()}])
    client.portal.call(seed)
    docs_before = {k: v["docs"] for k, v in client.portal.call(_snapshot).items()}
    report = client.portal.call(db_indexes.apply)
    failed = {f["index"]: f["reason"] for f in report["failed"]}
    assert "vendors_code_unique" in failed and "duplicate" in failed["vendors_code_unique"]
    assert "vendors_code_unique" not in report["created"]
    assert "VDDUP999" not in json.dumps(report)                                  # the duplicated value is never reported
    docs_after = {k: v["docs"] for k, v in client.portal.call(_snapshot).items()}
    assert all(docs_after[k] == docs_before[k] for k in docs_before)                          # no existing document changed
    assert len(client.portal.call(lambda: db.vendors.find({"vendor_code": "VDDUP999"}).to_list(10))) == 2


# ============================================================ 6b. a conflicting index is left alone
def test_a_conflicting_index_is_reported_and_never_dropped(client):
    _fresh(client)

    async def seed():
        await db.vendors.create_index("user_id", name="vendors_user_legacy")          # same keys, no uniqueness
        await db.vendors.insert_one({"id": new_id(), "user_id": "only", "status": "draft", "created_at": now_iso()})
    client.portal.call(seed)
    report = client.portal.call(db_indexes.apply)
    assert any(c["index"] == "vendors_user_unique" for c in report["conflict"])
    assert "vendors_user_unique" not in report["created"]
    assert "vendors_user_legacy" in client.portal.call(lambda: db.vendors.index_information())   # never dropped automatically


# ============================================================ 6c. a legacy index is replaced only after the replacement is safe
def test_a_legacy_index_is_replaced_only_when_the_replacement_is_created(client):
    _fresh(client)

    async def seed():
        await db.users.create_index("email", name="email_1", unique=True)            # the old, non-partial e-mail index
        await db.users.insert_one({"id": new_id(), "distributor_id": "L1", "email": "legacy@example.test", "created_at": now_iso()})
    client.portal.call(seed)
    report = client.portal.call(db_indexes.apply)
    assert any(d["index"] == "email_1" and d["replaced_by"] == "users_email_partial_unique" for d in report["dropped"])
    info = client.portal.call(lambda: db.users.index_information())
    assert "email_1" not in info and info["users_email_partial_unique"].get("partialFilterExpression")
    assert client.portal.call(lambda: db.users.count_documents({})) == 1
