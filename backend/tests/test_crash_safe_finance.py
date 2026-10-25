"""Phase 18: crash-safe commission release and refund clawback, unresolved-case holds, fault injection.

A simulated crash raises SimulatedCrash at a chosen step. Everything written before that step stays in the database,
exactly as after a real process crash (there are no transactions to roll back). Each scenario then retries and checks
that the wallet, ledger, commission and refund states reconcile and that no money moved twice.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_crash_safe_finance.py -n 0`.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_crash_safe_test", "JWT_SECRET": "crash-safe-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402
import server  # noqa: E402
import commission  # noqa: E402
import financial_ops  # noqa: E402
import shop_routes  # noqa: E402
import wallet_reconcile  # noqa: E402
from commission import distribute_sale_commissions, release_due_points  # noqa: E402
from core import db, hash_password, now_iso, new_id, get_settings  # noqa: E402
import secrets  # noqa: E402

SUBTOTAL_P = 100000
TOTAL_P = 118000
PARTIAL_P = 59000
FUTURE = datetime.now(timezone.utc) + timedelta(days=30)


class SimulatedCrash(Exception):
    """The process died at this point. What was written before it stays written."""


def crash_at(monkeypatch, module, name, nth=1, after=False):
    """Make the nth call of module.name crash: before the call (after=False) or after it has written its state."""
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
    return {"id": uid, "distributor_id": "C" + uid[:7].upper(), "full_name": "Test", "mobile": "9" + f"{secrets.randbelow(10**9):09d}",
            "email": f"c{uid[:8]}@example.com", "password_hash": hash_password("Crash-Pass-1234"), "role": "distributor",
            "status": "green", "account_status": "active", "created_at": now_iso(), "updated_at": now_iso(), **extra}


def _tree(c):
    team = _user()
    referrer = _user(sponsor_user_id=team["id"])
    seller = _user(sponsor_user_id=referrer["id"])
    buyer = _user()
    _run(c, lambda: db.users.insert_many([dict(d) for d in (team, referrer, seller, buyer)]))
    return {"team": team, "referrer": referrer, "seller": seller, "buyer": buyer}


def _order(c, tree):
    oid = new_id()
    order = {"id": oid, "order_number": "CR-" + oid[:6].upper(), "user_id": tree["buyer"]["id"],
             "seller_user_id": tree["seller"]["id"], "payment_status": "paid",
             "subtotal": SUBTOTAL_P / 100, "subtotal_paise": SUBTOTAL_P, "total": TOTAL_P / 100, "total_paise": TOTAL_P,
             "refunded_paise": 0, "refunded_amount": 0.0, "fulfilments": [], "created_at": now_iso()}
    _run(c, lambda: db.orders.insert_one(dict(order)))
    return order


def _distribute(c, tree, order):
    assert _run(c, lambda: distribute_sale_commissions(order, tree["buyer"]))["credited"] == 3


def _commissions(c, order_id):
    return _run(c, lambda: db.commissions.find({"order_id": order_id}, {"_id": 0}).to_list(10))


def _wallet(c, uid):
    return _run(c, lambda: db.wallets.find_one({"user_id": uid}, {"_id": 0}))


def _refund(c, order_id, amount_rupees=None, reference="R1"):
    return _run(c, lambda: shop_routes.reverse_order_financials(order_id, reference=reference, refund_amount=amount_rupees))


def _release(c, when=FUTURE):
    return _run(c, lambda: release_due_points(when))


def _op_rows(c, op_key):
    return _run(c, lambda: db.wallet_transactions.count_documents({"op_key": op_key}))


def _assert_consistent(c):
    """Every wallet matches its ledger, every intent is complete, and every recorded financial row exists."""
    result = _run(c, wallet_reconcile.reconcile)
    assert result["discrepancies"] == [], result["discrepancies"]
    assert result["commission_issues"] == [], result["commission_issues"]


def _seller_amounts(c, tree):
    w = _wallet(c, tree["seller"]["id"])
    return w["available_balance_paise"], w["pending_balance_paise"], w["total_earned_paise"]


# ================================================================ unique reference per logical movement
def test_one_ledger_row_per_operation_key_is_enforced_by_the_database(c):
    key = f"test:unique:{new_id()}"
    _run(c, lambda: db.wallet_transactions.insert_one({"id": new_id(), "user_id": "u", "op_key": key}))
    with pytest.raises(DuplicateKeyError):
        _run(c, lambda: db.wallet_transactions.insert_one({"id": new_id(), "user_id": "u", "op_key": key}))


# ================================================================ 1. crash-safe release
def test_crash_after_the_release_claim_and_before_the_ledger_is_finished_by_the_next_run(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    crash_at(monkeypatch, financial_ops, "ensure_ledger", nth=1)
    with pytest.raises(SimulatedCrash):
        _release(c)
    # the intent exists and says the commission is released, but no ledger row and no money yet
    issues = _run(c, wallet_reconcile.reconcile)["commission_issues"]
    assert any(i["issue"] == "release_ledger_missing" for i in issues)
    assert _seller_amounts(c, t) == (0, 30000, 0)                      # the crash came before any money moved
    monkeypatch.undo()
    result = _release(c)
    assert result["finished_interrupted"] >= 1
    assert _seller_amounts(c, t) == (30000, 0, 30000)
    assert all(_op_rows(c, f"release:{r['id']}") == 1 for r in _commissions(c, order["id"]))
    _assert_consistent(c)


def test_crash_after_the_ledger_but_before_the_applied_marker_does_not_pay_twice(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    crash_at(monkeypatch, financial_ops, "_mark_applied", nth=1)
    with pytest.raises(SimulatedCrash):
        _release(c)
    monkeypatch.undo()
    _release(c)
    _release(c)                                                        # and once more, for good measure
    assert _seller_amounts(c, t) == (30000, 0, 30000)
    _assert_consistent(c)


def test_crash_after_the_wallet_moved_but_before_the_marker_does_not_pay_twice(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    crash_at(monkeypatch, financial_ops, "move_wallet_once", nth=1, after=True)
    with pytest.raises(SimulatedCrash):
        _release(c)
    monkeypatch.undo()
    _release(c)
    assert _seller_amounts(c, t) == (30000, 0, 30000)
    _assert_consistent(c)


def test_the_releases_of_a_partial_refund_are_each_finished_once_after_a_crash(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _refund(c, order["id"], PARTIAL_P / 100)
    crash_at(monkeypatch, financial_ops, "move_wallet_once", nth=2)
    with pytest.raises(SimulatedCrash):
        _release(c)
    monkeypatch.undo()
    _release(c)
    _release(c)
    assert _seller_amounts(c, t) == (15000, 0, 15000)
    assert _run(c, lambda: db.wallets.find_one({"user_id": t["referrer"]["id"]}))["available_balance_paise"] == 5000
    assert _run(c, lambda: db.wallets.find_one({"user_id": t["team"]["id"]}))["available_balance_paise"] == 2500
    _assert_consistent(c)


# ================================================================ 2. crash-safe refund and clawbacks
def test_a_refund_interrupted_between_commissions_resumes_without_clawing_back_twice(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _release(c)
    crash_at(monkeypatch, shop_routes, "_reverse_commission", nth=2)
    with pytest.raises(SimulatedCrash):
        _refund(c, order["id"], PARTIAL_P / 100, reference="RR")
    event = _run(c, lambda: db.order_refunds.find_one({"id": f"{order['id']}:refund:RR"}))
    assert event["status"] == "processing"                              # not completed: the refund is still open
    monkeypatch.undo()
    result = _refund(c, order["id"], PARTIAL_P / 100, reference="RR")
    assert result["reversed"] == 3
    assert _seller_amounts(c, t) == (15000, 0, 15000)
    assert _run(c, lambda: db.orders.find_one({"id": order["id"]}, {"refunded_paise": 1}))["refunded_paise"] == PARTIAL_P
    _assert_consistent(c)


def test_a_crash_inside_the_clawback_of_one_commission_is_finished_by_the_retry(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    crash_at(monkeypatch, financial_ops, "finish_reversal", nth=2, after=False)
    with pytest.raises(SimulatedCrash):
        _refund(c, order["id"], PARTIAL_P / 100, reference="RF")
    monkeypatch.undo()
    _refund(c, order["id"], PARTIAL_P / 100, reference="RF")
    assert _seller_amounts(c, t) == (0, 15000, 0)                      # pending: 30000 less the 15000 reversed
    _assert_consistent(c)


def test_a_crash_after_the_reservation_moves_no_commission_until_the_retry(c, monkeypatch):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    crash_at(monkeypatch, shop_routes, "_reverse_commission", nth=1)
    with pytest.raises(SimulatedCrash):
        _refund(c, order["id"], PARTIAL_P / 100, reference="RS")
    assert _seller_amounts(c, t) == (0, 30000, 0)                      # reserved on the order, nothing clawed back yet
    monkeypatch.undo()
    _refund(c, order["id"], PARTIAL_P / 100, reference="RS")
    assert _seller_amounts(c, t) == (0, 15000, 0)
    _assert_consistent(c)


def test_a_completed_refund_retried_changes_nothing(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _refund(c, order["id"], PARTIAL_P / 100, reference="RD")
    before = _seller_amounts(c, t)
    again = _refund(c, order["id"], PARTIAL_P / 100, reference="RD")
    assert again.get("duplicate") is True
    assert _seller_amounts(c, t) == before
    _assert_consistent(c)


def test_a_retried_reversal_of_a_recorded_commission_is_not_applied_twice(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    stale = _commissions(c, order["id"])[0]
    event = {"id": "direct-retry", "amount_paise": PARTIAL_P, "closes_order": False}
    _run(c, lambda: shop_routes._reverse_commission(stale, event, {"total_paise": TOTAL_P, "order_number": order["order_number"]}))
    before = _run(c, lambda: db.commissions.find_one({"id": stale["id"]}, {"_id": 0}))
    _run(c, lambda: shop_routes._reverse_commission(before, event, {"total_paise": TOTAL_P, "order_number": order["order_number"]}))
    _run(c, lambda: shop_routes._reverse_commission(before, event, {"total_paise": TOTAL_P, "order_number": order["order_number"]}))
    assert _run(c, lambda: db.commissions.find_one({"id": stale["id"]}, {"_id": 0}))["reversed_paise"] == 15000
    _assert_consistent(c)


# ================================================================ concurrent release and refund
@pytest.mark.parametrize("round_no", [1, 2, 3])
def test_concurrent_release_and_partial_refund_end_in_the_same_correct_balances(c, round_no):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)

    async def both():
        return await asyncio.gather(release_due_points(FUTURE),
                                    shop_routes.reverse_order_financials(order["id"], reference="CC", refund_amount=PARTIAL_P / 100))
    _run(c, both)
    _release(c)
    assert _seller_amounts(c, t) == (15000, 0, 15000)                  # whichever ran first, the result is identical
    assert _run(c, lambda: db.wallets.find_one({"user_id": t["team"]["id"]}))["available_balance_paise"] == 2500
    assert all(_op_rows(c, f"release:{r['id']}") <= 1 for r in _commissions(c, order["id"]))
    _assert_consistent(c)


# ================================================================ unresolved return or refund cases hold the remainder
def test_an_open_refund_case_holds_the_remainder_and_releases_it_once_resolved(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    case_id = new_id()
    _run(c, lambda: db.refund_cases.insert_one({"id": case_id, "source_key": f"case:{case_id}", "order_id": order["id"],
                                                "status": "initiated", "created_at": now_iso()}))
    # a case-driven refund leaves its case open (initiated, not yet confirmed), so the remainder must stay on hold
    _run(c, lambda: shop_routes.reverse_order_financials(order["id"], reference="OPEN", refund_amount=PARTIAL_P / 100,
                                                         case_id=case_id))
    result = _release(c)
    assert result["held"] >= 3
    assert all(r["status"] == "PARTIALLY_REVERSED" for r in _commissions(c, order["id"]))
    assert _seller_amounts(c, t) == (0, 15000, 0)
    _run(c, lambda: db.refund_cases.update_one({"id": case_id}, {"$set": {"status": "resolved"}}))
    _release(c)
    assert _seller_amounts(c, t) == (15000, 0, 15000)                  # only the valid remainder, once
    _release(c)
    assert _seller_amounts(c, t) == (15000, 0, 15000)
    _assert_consistent(c)


def test_an_open_return_case_holds_a_commission_until_it_is_closed(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    rc_id = new_id()
    _run(c, lambda: db.return_cases.insert_one({"id": rc_id, "order_id": order["id"], "status": "inspected", "lines": [],
                                                "created_at": now_iso(), "updated_at": now_iso()}))
    _release(c)
    assert _seller_amounts(c, t) == (0, 30000, 0)
    _run(c, lambda: db.return_cases.update_one({"id": rc_id}, {"$set": {"status": "refunded"}}))
    _refund(c, order["id"], None, reference="RC")                      # the return's refund takes the whole order
    _release(c)
    assert _seller_amounts(c, t) == (0, 0, 0)                          # a full refund never releases anything
    _assert_consistent(c)


# ================================================================ detection (a corrupted state is reported, not repaired)
def test_a_release_recorded_as_applied_without_its_ledger_row_is_reported_and_not_repaired(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _release(c)
    cid = _commissions(c, order["id"])[0]["id"]
    _run(c, lambda: db.wallet_transactions.delete_many({"op_key": f"release:{cid}"}))   # simulated corruption
    result = _run(c, wallet_reconcile.reconcile)
    assert any(i["commission_id"] == cid and i["issue"] == "release_ledger_missing" for i in result["commission_issues"])
    assert _wallet(c, t["seller"]["id"])["available_balance_paise"] == 30000    # the balance is left exactly as it was
