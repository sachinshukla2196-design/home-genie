"""Phase 19: crash-safe commission DISTRIBUTION (the credit side of a paid order).

A simulated crash raises SimulatedCrash at a chosen step. Everything written before the step stays in the database, as
after a real process crash (there are no transactions to roll back). Each scenario then retries and verifies: exactly
three commission records, one ledger row per operation key, exact wallet aggregates, the order flag, and reconciliation.

Expected amounts on a Rs 1000 subtotal: direct 30% = 30000 paise to the seller, referral 10% = 10000 to the referrer,
team 5% = 5000 to the team member (all PENDING).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_crash_safe_distribution.py -n 0`.
"""
import asyncio
import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_crash_distribution_test", "JWT_SECRET": "crash-dist-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import commission  # noqa: E402
import financial_ops  # noqa: E402
import wallet_reconcile  # noqa: E402
from commission import distribute_sale_commissions, release_due_points  # noqa: E402
from core import db, hash_password, now_iso, new_id, get_settings  # noqa: E402

FUTURE = datetime.now(timezone.utc) + timedelta(days=30)
SUBTOTAL_P = 100000
EXPECTED = {"direct": 30000, "referral": 10000, "team": 5000}
TYPES = {"direct": "COMMISSION_DIRECT", "referral": "COMMISSION_REFERRAL", "team": "COMMISSION_TEAM"}


class SimulatedCrash(Exception):
    """The process died at this point. What was written before it stays written."""


def crash_at(monkeypatch, module, name, nth=1, after=False):
    orig = getattr(module, name)
    calls = {"n": 0}

    async def wrapper(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] != nth:
            return await orig(*args, **kwargs)
        if after:
            await orig(*args, **kwargs)
        raise SimulatedCrash(f"{name} call {nth}")
    monkeypatch.setattr(module, name, wrapper)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            await get_settings()
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _user(**extra):
    uid = new_id()
    return {"id": uid, "distributor_id": "D" + uid[:7].upper(), "full_name": "Test", "mobile": "9" + f"{secrets.randbelow(10**9):09d}",
            "email": f"d{uid[:8]}@example.com", "password_hash": hash_password("Dist-Pass-1234"), "role": "distributor",
            "status": "green", "account_status": "active", "created_at": now_iso(), "updated_at": now_iso(), **extra}


def _tree(c):
    team = _user()
    referrer = _user(sponsor_user_id=team["id"])
    seller = _user(sponsor_user_id=referrer["id"])
    buyer = _user()
    _run(c, lambda: db.users.insert_many([dict(d) for d in (team, referrer, seller, buyer)]))
    return {"team": team, "referrer": referrer, "seller": seller, "buyer": buyer}


def _order(c, tree, **extra):
    oid = new_id()
    order = {"id": oid, "order_number": "DS-" + oid[:6].upper(), "user_id": tree["buyer"]["id"],
             "seller_user_id": tree["seller"]["id"], "payment_status": "paid", "subtotal": SUBTOTAL_P / 100,
             "subtotal_paise": SUBTOTAL_P, "total": 1180.0, "total_paise": 118000, "refunded_paise": 0, "refunded_amount": 0.0,
             "fulfilments": [], "created_at": now_iso(), **extra}
    _run(c, lambda: db.orders.insert_one(dict(order)))
    return order


def _distribute(c, tree, order):
    return _run(c, lambda: distribute_sale_commissions(order, tree["buyer"]))


def _keys(order):
    return {who: f"dist:{order['id']}:{typ}" for who, typ in TYPES.items()}


def _commission_docs(c, order):
    return _run(c, lambda: db.commissions.find({"order_id": order["id"]}, {"_id": 0}).to_list(10))


def _wallet(c, uid):
    return _run(c, lambda: db.wallets.find_one({"user_id": uid}, {"_id": 0}))


def _ledger_count(c, key):
    return _run(c, lambda: db.wallet_transactions.count_documents({"op_key": key}))


def _assert_complete_and_exact(c, t, order):
    docs = _commission_docs(c, order)
    assert len(docs) == 3, [d["id"] for d in docs]
    assert sorted(d["id"] for d in docs) == sorted(_keys(order).values())           # operation keys are deterministic
    assert all(d["status"] == "PENDING" and (d.get("distribution") or {}).get("applied") for d in docs)
    for who, key in _keys(order).items():
        assert _ledger_count(c, key) == 1, (who, key)                                 # one ledger row per movement
    assert _wallet(c, t["seller"]["id"])["pending_balance_paise"] == EXPECTED["direct"]
    assert _wallet(c, t["referrer"]["id"])["pending_balance_paise"] == EXPECTED["referral"]
    assert _wallet(c, t["team"]["id"])["pending_balance_paise"] == EXPECTED["team"]
    for who in ("seller", "referrer", "team"):
        w = _wallet(c, t[who]["id"])
        assert w["available_balance_paise"] == 0 and w["total_earned_paise"] == 0, who   # nothing released by distribution
    assert _run(c, lambda: db.orders.find_one({"id": order["id"]}, {"commissions_paid": 1}))["commissions_paid"] is True
    result = _run(c, wallet_reconcile.reconcile)
    assert result["discrepancies"] == [], result["discrepancies"]
    assert result["commission_issues"] == [], result["commission_issues"]
    audit = result["distribution_audit"]
    assert all(order["id"] not in str(v) for v in audit.values()), audit


# ================================================================ 1-5. crashes at each step of the flow
def test_1_crash_after_the_intent_and_before_any_commission_record(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, commission, "_apply_item", nth=1)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    assert _commission_docs(c, order) == []                                         # the plan (intent) exists; no records yet
    assert _run(c, lambda: db.commission_plans.find_one({"_id": order["id"]})) is not None
    monkeypatch.undo()
    # the decision is frozen: a referral that later stops being green is still credited, as decided
    _run(c, lambda: db.users.update_one({"id": t["referrer"]["id"]}, {"$set": {"status": "red"}}))
    result = _distribute(c, t, order)
    assert result["credited"] == 3 and result["complete"] is True
    _assert_complete_and_exact(c, t, order)


def test_2_crash_after_the_record_and_before_the_ledger_row(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, financial_ops, "ensure_ledger", nth=1)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    docs = _commission_docs(c, order)
    assert len(docs) == 1 and docs[0]["distribution"]["applied"] is False
    assert _ledger_count(c, docs[0]["distribution"]["op_key"]) == 0
    issues = _run(c, wallet_reconcile.reconcile)["commission_issues"]
    assert any(i["issue"] == "distribution_incomplete" for i in issues)             # reported, not silently ignored
    monkeypatch.undo()
    _distribute(c, t, order)
    _assert_complete_and_exact(c, t, order)


def test_3_crash_after_the_ledger_row_and_before_the_wallet_move(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, financial_ops, "move_wallet_once", nth=1)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    key = _keys(order)["direct"]
    assert _ledger_count(c, key) == 1
    assert (_wallet(c, t["seller"]["id"]) or {}).get("pending_balance_paise", 0) == 0
    monkeypatch.undo()
    _distribute(c, t, order)
    _assert_complete_and_exact(c, t, order)


def test_4_crash_after_the_wallet_move_and_before_the_intent_is_completed(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, commission, "_mark_distribution_applied", nth=1)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    assert _wallet(c, t["seller"]["id"])["pending_balance_paise"] == EXPECTED["direct"]   # moved once already
    monkeypatch.undo()
    _distribute(c, t, order)
    assert _wallet(c, t["seller"]["id"])["pending_balance_paise"] == EXPECTED["direct"]   # not moved again
    _assert_complete_and_exact(c, t, order)


def test_5_crash_after_some_recipients_are_done_and_before_the_others(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, commission, "_apply_item", nth=2)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    done = [d for d in _commission_docs(c, order) if d["distribution"]["applied"]]
    assert len(done) == 1 and _ledger_count(c, done[0]["distribution"]["op_key"]) == 1
    monkeypatch.undo()
    result = _distribute(c, t, order)
    assert result["credited"] == 2                                                   # only the two that were not done
    _assert_complete_and_exact(c, t, order)


# ================================================================ 6-9. concurrency, repeats, flags, completed orders
def test_6_concurrent_distribution_jobs_for_the_same_order_credit_once(c):
    t = _tree(c)
    order = _order(c, t)

    async def both():
        return await asyncio.gather(distribute_sale_commissions(order, t["buyer"]), distribute_sale_commissions(order, t["buyer"]))
    results = _run(c, both)
    assert sum(r["credited"] for r in results) == 3                                  # each movement counted by exactly one job
    _assert_complete_and_exact(c, t, order)


def test_7_repeated_invocation_after_success_credits_nothing(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    before = {who: _wallet(c, t[who]["id"]) for who in ("seller", "referrer", "team")}
    again = _distribute(c, t, order)
    assert again["credited"] == 0 and again["reason"] == "already_processed" and again["complete"] is True
    assert all(_wallet(c, t[who]["id"]) == before[who] for who in before)
    _assert_complete_and_exact(c, t, order)


def test_8_retry_when_the_flag_is_already_true_but_distribution_is_incomplete(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, commission, "_apply_item", nth=2)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    _run(c, lambda: db.orders.update_one({"id": order["id"]}, {"$set": {"commissions_paid": True}}))   # the flag set before completion
    monkeypatch.undo()
    result = _distribute(c, t, order)
    assert result["credited"] == 2 and result["complete"] is True                  # the remaining work is done, not skipped
    _assert_complete_and_exact(c, t, order)


def test_9_a_fully_completed_order_retried_creates_no_additional_credits(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _distribute(c, t, order)
    _distribute(c, t, order)
    _assert_complete_and_exact(c, t, order)


# ================================================================ historical and interplay cases
def test_historical_flag_without_a_plan_is_never_reissued_and_is_reported(c):
    t = _tree(c)
    order = _order(c, t, commissions_paid=True)                                       # flagged before this change
    assert _distribute(c, t, order)["credited"] == 0
    assert _commission_docs(c, order) == []
    audit = _run(c, wallet_reconcile.distribution_audit)
    assert order["id"] in audit["flagged_without_plan"]


def test_an_interrupted_distribution_is_completed_by_the_release_job_before_release(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, commission, "_apply_item", nth=2)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    monkeypatch.undo()
    _run(c, lambda: release_due_points(FUTURE))
    assert all(d["status"] == "RELEASED" for d in _commission_docs(c, order))
    assert _wallet(c, t["seller"]["id"])["available_balance_paise"] == EXPECTED["direct"]
    result = _run(c, wallet_reconcile.reconcile)
    assert result["discrepancies"] == [] and result["commission_issues"] == []


def test_a_full_refund_of_a_half_distributed_order_leaves_every_balance_at_zero(c, monkeypatch):
    import shop_routes
    t = _tree(c)
    order = _order(c, t)
    crash_at(monkeypatch, commission, "_apply_item", nth=2)
    with pytest.raises(SimulatedCrash):
        _distribute(c, t, order)
    monkeypatch.undo()
    _run(c, lambda: shop_routes.reverse_order_financials(order["id"], reference="FULL", refund_amount=None))
    for who in ("seller", "referrer", "team"):
        w = _wallet(c, t[who]["id"])
        assert (w["pending_balance_paise"], w["available_balance_paise"], w["total_earned_paise"]) == (0, 0, 0), who
    result = _run(c, wallet_reconcile.reconcile)
    assert result["discrepancies"] == [] and result["commission_issues"] == []
