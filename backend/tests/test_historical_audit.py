"""Read-only historical audit: duplicate wallets, legacy commission distribution, index and migration readiness.

The fixtures recreate HISTORICAL states, including the duplicate wallets the old race could produce. They are inputs to
the audit, not repairs. Every test that runs the audit also proves that nothing was written: all write methods are
blocked, and full database snapshots are compared before and after.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_historical_audit.py -n 0`.
"""
import json
import os
import subprocess
import sys

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_historical_audit_test", "JWT_SECRET": "historical-audit-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
from motor.motor_asyncio import AsyncIOMotorCollection  # noqa: E402
import server  # noqa: E402
import historical_audit  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
WRITE_METHODS = ["insert_one", "insert_many", "update_one", "update_many", "delete_one", "delete_many", "replace_one",
                 "create_index", "create_indexes", "drop_index", "drop_indexes", "find_one_and_update", "find_one_and_replace",
                 "find_one_and_delete", "bulk_write"]
S = {}
W = {}
ORDERS = {}


def _user(key, sponsor=None):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": "H" + uid[:7].upper(), "full_name": key, "mobile": "9" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:6]}@example.com", "role": "distributor", "status": "green", "account_status": "active",
            "sponsor_user_id": sponsor, "created_at": now_iso(), "updated_at": now_iso()}


def _ledger(user_id, typ, amount_p, status="PENDING", direction="credit", op=None, reference=""):
    return {"id": new_id(), "user_id": user_id, "type": typ, "direction": direction, "status": status,
            "amount_paise": amount_p, "amount": amount_p / 100, "reference": reference, "op_key": op, "created_at": now_iso()}


def _wallet(user_id, pending=0, available=0, earned=0, withdrawn=0):
    return {"id": new_id(), "user_id": user_id, "active": True, "available_balance_paise": available, "available_balance": available / 100,
            "pending_balance_paise": pending, "pending_balance": pending / 100, "total_earned_paise": earned, "total_earned": earned / 100,
            "total_withdrawn_paise": withdrawn, "total_withdrawn": withdrawn / 100, "applied_ops": [], "created_at": now_iso(), "updated_at": now_iso()}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            # No migration is applied here on purpose: this is the state before the unique indexes exist.
            team = _user("team")
            referrer = _user("referrer", sponsor=team["id"])
            seller = _user("seller", sponsor=referrer["id"])
            buyer = _user("buyer")
            dup_ok = _user("dup_consistent")
            dup_bad = _user("dup_inconsistent")
            drift = _user("drift")
            seller2 = _user("seller2")
            await db.users.insert_many([dict(u) for u in (team, referrer, seller, buyer, dup_ok, dup_bad, drift, seller2)])
            await db.referral_relationships.insert_many([
                {"id": new_id(), "referred_user_id": seller["id"], "sponsor_id": referrer["id"]},
                {"id": new_id(), "referred_user_id": referrer["id"], "sponsor_id": team["id"]}])

            def order(key, seller_id, **extra):
                oid = new_id()
                ORDERS[key] = oid
                return {"id": oid, "order_number": f"HA-{key}", "user_id": buyer["id"], "seller_user_id": seller_id,
                        "payment_status": "paid", "subtotal_paise": 100000, "subtotal": 1000.0, "total_paise": 118000,
                        "total": 1180.0, "refunded_paise": 0, "refunded_amount": 0.0, "commissions_paid": True,
                        "commissions_paid_at": now_iso(), "created_at": now_iso(), **extra}
            # O_OK: every check passes
            o_ok = order("ok", seller["id"])
            # O_BAD: the direct amount does not match its stored rate x subtotal
            o_bad = order("bad", seller["id"])
            # O_NONE: flagged with no commissions, but the reason is recorded
            o_none = order("none", seller2["id"], commission_note="seller_not_approved")
            # O_UNKNOWN: flagged with no commissions and no reason
            o_unknown = order("unknown", seller2["id"])
            await db.orders.insert_many([dict(o) for o in (o_ok, o_bad, o_none, o_unknown)])

            def comm(oid, typ, user, amount_p, percent):
                return {"_id": new_id(), "id": new_id(), "order_id": oid, "type": typ, "user_id": user["id"], "seller_user_id": seller["id"],
                        "percent": percent, "amount_paise": amount_p, "amount": amount_p / 100, "base_paise": 100000,
                        "status": "PENDING", "release_after_days": 7, "created_at": now_iso(), "released_at": None}
            ok_comms = [comm(o_ok["id"], "COMMISSION_DIRECT", seller, 30000, 30.0), comm(o_ok["id"], "COMMISSION_REFERRAL", referrer, 10000, 10.0),
                        comm(o_ok["id"], "COMMISSION_TEAM", team, 5000, 5.0)]
            bad_comms = [comm(o_bad["id"], "COMMISSION_DIRECT", seller, 29999, 30.0)]
            await db.commissions.insert_many([dict(x) for x in ok_comms + bad_comms])
            ledger = [_ledger(seller["id"], "COMMISSION_DIRECT", 30000, reference=o_ok["id"]),
                      _ledger(referrer["id"], "COMMISSION_REFERRAL", 10000, reference=o_ok["id"]),
                      _ledger(team["id"], "COMMISSION_TEAM", 5000, reference=o_ok["id"]),
                      _ledger(seller["id"], "COMMISSION_DIRECT", 29999, reference=o_bad["id"])]
            # duplicate wallet, consistent: one wallet agrees with the ledger, the other is doubled
            ledger.append(_ledger(dup_ok["id"], "COMMISSION_DIRECT", 30000, op="dist:dup-ok:1"))
            ledger.append(_ledger(dup_bad["id"], "COMMISSION_DIRECT", 30000, op="dist:dup-bad:1"))
            ledger.append(_ledger(dup_bad["id"], "COMMISSION_DIRECT", 30000, op="dist:dup-bad:1"))       # a duplicated operation key
            await db.wallet_transactions.insert_many(ledger)
            w_ok_good = _wallet(dup_ok["id"], pending=30000)
            w_ok_double = _wallet(dup_ok["id"], pending=60000)
            w_bad_a = _wallet(dup_bad["id"], pending=60000)
            w_bad_b = _wallet(dup_bad["id"], pending=30000)
            await db.wallets.insert_many([dict(w) for w in (w_ok_good, w_ok_double, w_bad_a, w_bad_b)])
            # the audit reports the wallet document's own _id, so look the identifiers up after insertion
            W["ok_good"] = str((await db.wallets.find_one({"user_id": dup_ok["id"], "pending_balance_paise": 30000}))["_id"])
            W["ok_double"] = str((await db.wallets.find_one({"user_id": dup_ok["id"], "pending_balance_paise": 60000}))["_id"])
            # a single wallet that disagrees with its ledger (not a duplicate, still relevant to migration)
            await db.wallets.insert_one(_wallet(drift["id"], pending=5000))
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


async def _snapshot():
    out = {}
    for name in sorted(await db.list_collection_names()):
        out[name] = json.dumps(await db[name].find({}).sort("_id", 1).to_list(100000), default=str, sort_keys=True)
    return out


@pytest.fixture
def no_writes(monkeypatch):
    """Every write method on every collection now fails the test. Reads still work."""
    attempted = []
    for name in WRITE_METHODS:
        def make(name):
            def blocked(self, *a, **k):
                attempted.append(f"{self.name}.{name}")
                raise AssertionError(f"the audit attempted a write: {self.name}.{name}")
            return blocked
        monkeypatch.setattr(AsyncIOMotorCollection, name, make(name))
    return attempted


# ================================================================ duplicate wallets
def test_duplicate_wallets_are_reported_with_stable_identifiers_and_no_personal_data(c, no_writes):
    report = _run(c, historical_audit.wallet_audit)
    assert report["duplicate_wallet_count"] == 2
    users = {u["user_ref"]: u for u in report["duplicate_wallet_users"]}
    ok = next(u for u in users.values() if u["classification"] == "derivable_candidate")
    assert ok["manual_review"] is True
    assert {w["wallet_id"] for w in ok["wallets"]} == {W["ok_good"], W["ok_double"]}
    assert ok["ledger_expected_paise"]["pending_balance"] == 30000
    text = json.dumps(report)
    assert "@example.com" not in text and "mobile" not in text.lower()


def test_an_inconsistent_duplicate_is_not_derivable_and_duplicate_keys_are_reported(c, no_writes):
    report = _run(c, historical_audit.wallet_audit)
    bad = [u for u in report["duplicate_wallet_users"] if u["classification"] == "not_derivable"]
    assert len(bad) == 1
    assert any("repeats operation keys" in r for r in bad[0]["reasons"])     # the repeated key decides, not the balances
    assert bad[0]["duplicate_operation_keys"] == ["dist:dup-bad:1"]
    assert bad[0]["manual_review"] is True


def test_the_repair_manifest_proposes_but_never_executes(c, no_writes):
    report = _run(c, historical_audit.wallet_audit)
    assert report["proposed_repair_manifest"]
    assert all(m["executed"] is False and m["action"] == "manual_review" for m in report["proposed_repair_manifest"])
    derivable = [m for m in report["proposed_repair_manifest"] if m["canonical_wallet_id"]]
    assert len(derivable) == 1 and derivable[0]["canonical_wallet_id"] == W["ok_good"]
    assert derivable[0]["wallet_ids_to_retire_after_review"] == [W["ok_double"]]


def test_a_single_wallet_that_disagrees_with_its_ledger_is_listed(c, no_writes):
    report = _run(c, historical_audit.wallet_audit)
    assert len(report["single_wallets_drifting_from_ledger"]) == 1


# ================================================================ legacy commission distribution
def test_legacy_orders_are_classified_verified_inconsistent_or_unverifiable(c, no_writes):
    report = _run(c, historical_audit.legacy_distribution_audit)
    by_order = {o["order_ref"]: o for o in report["orders"]}
    assert report["flagged_without_plan"] == 4
    assert by_order[ORDERS["ok"]]["classification"] == "verified"
    assert by_order[ORDERS["ok"]]["reasons"] == ["all recorded checks pass"]
    assert by_order[ORDERS["bad"]]["classification"] == "inconsistent"
    assert by_order[ORDERS["none"]]["classification"] == "verified"
    assert by_order[ORDERS["unknown"]]["classification"] == "unverifiable"
    assert set(report["manual_review_required"]) == {ORDERS["bad"], ORDERS["unknown"]}
    assert report["automatic_payouts_made"] == 0


def test_a_verified_order_lists_its_operation_keys_without_user_data(c, no_writes):
    report = _run(c, historical_audit.legacy_distribution_audit)
    ok = next(o for o in report["orders"] if o["order_ref"] == ORDERS["ok"])
    assert ok["commission_count"] == 3 and ok["ledger_rows"] == 3
    assert "@example.com" not in json.dumps(report)


# ================================================================ index and migration readiness
def test_index_readiness_reports_duplicates_without_applying_anything(c, no_writes):
    report = _run(c, historical_audit.index_readiness)
    dups = {u["index"]: u["duplicate_values"] for u in report["unique_index_duplicates"]}
    assert dups["wallets_user_unique"] == 2
    assert "wallets_user_unique" in report["plan"]["missing"]
    assert report["startup_creates_indexes"] is False
    assert set(report["vendor_migration_dry_run"]) >= {"duplicates", "backfill_needed", "sequence_moved_to"}


def test_the_full_audit_lists_its_production_blockers(c, no_writes):
    report = _run(c, historical_audit.full_audit)
    text = " ".join(report["production_blockers"])
    assert "duplicate wallets" in text and "legacy distributions" in text and "unique index duplicates" in text


# ================================================================ read-only proof and repeatability
def test_the_audit_leaves_every_document_unchanged(c, no_writes):
    before = _run(c, _snapshot)
    _run(c, historical_audit.full_audit)
    assert no_writes == []
    assert _run(c, _snapshot) == before


def test_repeated_audit_runs_produce_identical_results(c, no_writes):
    first = _run(c, historical_audit.full_audit)
    second = _run(c, historical_audit.full_audit)
    assert json.dumps(first, sort_keys=True, default=str) == json.dumps(second, sort_keys=True, default=str)


def test_the_command_line_audit_writes_only_the_report_file(c, tmp_path):
    before = _run(c, _snapshot)
    out = tmp_path / "audit.json"
    env = {**os.environ, "PYTHONPATH": BACKEND}
    result = subprocess.run([sys.executable, os.path.join(BACKEND, "scripts", "historical_audit.py"), "--out", str(out)],
                            capture_output=True, text=True, env=env, timeout=300)
    assert result.returncode == 0, result.stderr[-800:]
    assert json.loads(out.read_text())["production_blockers"]
    assert _run(c, _snapshot) == before
