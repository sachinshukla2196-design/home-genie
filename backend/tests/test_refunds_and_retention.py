"""Phase 17: partially reversed commissions, refund clawbacks, hold-period policy, deactivation of accounts, reconciliation.

Every money movement uses the real paths (distribute_sale_commissions, release_due_points, reverse_order_financials,
the admin deletion route). Each scenario uses its own seller, referrer, team member and buyer, so balances never mix.
After each scenario the wallet aggregates are reconciled against the ledger.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_refunds_and_retention.py -n 0`.
"""
import asyncio
import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_refund_retention_test", "JWT_SECRET": "refund-retention-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import commission  # noqa: E402
import shop_routes  # noqa: E402
import wallet_reconcile  # noqa: E402
from commission import distribute_sale_commissions, release_due_points, release_days  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id, get_settings  # noqa: E402

PW = "Retention-Pass-1234"
SUBTOTAL_P = 100000      # Rs 1000 before GST
TOTAL_P = 118000         # Rs 1180 paid
PARTIAL_P = 59000        # half of the order is refunded
FUTURE = datetime.now(timezone.utc) + timedelta(days=30)


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


def _user(role="distributor", status="green", **extra):
    uid = new_id()
    doc = {"id": uid, "distributor_id": "T" + uid[:7].upper(), "full_name": "Test", "mobile": "9" + f"{secrets.randbelow(10**9):09d}",
           "email": f"t{uid[:8]}@example.com", "password_hash": hash_password(PW), "role": role, "status": status,
           "account_status": "active", "created_at": now_iso(), "updated_at": now_iso(), **extra}
    return doc


async def _insert_users(docs):
    await db.users.insert_many([dict(d) for d in docs])


def _tree(c):
    """seller -> referrer -> team member, and a buyer. Everyone is approved, so all three commissions are earned."""
    team = _user()
    referrer = _user(sponsor_user_id=team["id"])
    seller = _user(sponsor_user_id=referrer["id"])
    buyer = _user(status="green")
    _run(c, lambda: _insert_users([team, referrer, seller, buyer]))
    return {"team": team, "referrer": referrer, "seller": seller, "buyer": buyer}


def _order(c, tree, payment_status="paid"):
    oid = new_id()
    order = {"id": oid, "order_number": "ORD-" + oid[:6].upper(), "user_id": tree["buyer"]["id"],
             "seller_user_id": tree["seller"]["id"], "payment_status": payment_status,
             "subtotal": SUBTOTAL_P / 100, "subtotal_paise": SUBTOTAL_P, "total": TOTAL_P / 100, "total_paise": TOTAL_P,
             "refunded_paise": 0, "refunded_amount": 0.0, "fulfilments": [], "created_at": now_iso()}
    _run(c, lambda: db.orders.insert_one(dict(order)))
    return order


def _distribute(c, tree, order):
    result = _run(c, lambda: distribute_sale_commissions(order, tree["buyer"]))
    assert result["credited"] == 3, result
    return result


def _commissions(c, order_id):
    return _run(c, lambda: db.commissions.find({"order_id": order_id}, {"_id": 0}).to_list(10))


def _wallet(c, uid):
    return _run(c, lambda: db.wallets.find_one({"user_id": uid}, {"_id": 0}))


def _states(c, order_id):
    """Statuses of one order's commissions, by type. Release runs cover the whole database, so tests assert per order."""
    return {r["type"]: r["status"] for r in _commissions(c, order_id)}


def _points_released_rows(c, order_id):
    return _run(c, lambda: db.wallet_transactions.count_documents({"type": "POINTS_RELEASED", "reference": order_id}))


def _refund(c, order_id, amount_rupees=None, reference="R1"):
    return _run(c, lambda: shop_routes.reverse_order_financials(order_id, reference=reference, refund_amount=amount_rupees))


def _release(c, when=FUTURE):
    return _run(c, lambda: release_due_points(when))


def _assert_reconciles(c):
    result = _run(c, wallet_reconcile.reconcile)
    assert result["discrepancies"] == [], result["discrepancies"]
    assert result["wallets_checked"] >= 1


# ============================================================ 2. the hold-period policy (deterministic)
@pytest.mark.parametrize("value, expected", [(None, 7), (0, 0), (0.0, 0), (1, 1), (30, 30), (2.0, 2),
                                             (-1, None), (1.5, None), (True, None), ("3", None)])
def test_hold_period_policy(value, expected):
    assert release_days(value) == expected


# ============================================================ 1 & 3. refunds before and after release
def test_full_refund_before_release_leaves_nothing_to_release(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _refund(c, order["id"])
    assert all(r["status"] == "REVERSED" for r in _commissions(c, order["id"]))
    assert _release(c)["released"] == 0
    for who in ("seller", "referrer", "team"):
        w = _wallet(c, t[who]["id"])
        assert (w["pending_balance_paise"], w["available_balance_paise"], w["total_earned_paise"]) == (0, 0, 0), who
    _assert_reconciles(c)


def test_partial_refund_before_release_then_release_pays_only_the_remainder(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _refund(c, order["id"], PARTIAL_P / 100)
    rows = _commissions(c, order["id"])
    assert all(r["status"] == "PARTIALLY_REVERSED" and r.get("released_at") is None for r in rows)
    _release(c)
    assert set(_states(c, order["id"]).values()) == {"RELEASED"} and _points_released_rows(c, order["id"]) == 3
    # direct 30000 -> 15000 reversed, referral 10000 -> 5000, team 5000 -> 2500: remainders 15000 + 5000 + 2500
    assert _wallet(c, t["seller"]["id"])["available_balance_paise"] == 15000
    assert _wallet(c, t["referrer"]["id"])["available_balance_paise"] == 5000
    assert _wallet(c, t["team"]["id"])["available_balance_paise"] == 2500
    for who in ("seller", "referrer", "team"):
        assert _wallet(c, t[who]["id"])["pending_balance_paise"] == 0
    released = {r["type"]: r for r in _commissions(c, order["id"])}
    assert all(r["status"] == "RELEASED" and r["released_paise"] == r["amount_paise"] - r["reversed_paise"]
               for r in released.values())
    _assert_reconciles(c)


def test_a_second_release_run_pays_nothing_more(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _refund(c, order["id"], PARTIAL_P / 100)
    _release(c)
    before = _wallet(c, t["seller"]["id"])
    _release(c)
    assert _points_released_rows(c, order["id"]) == 3                 # still one release per commission
    assert _wallet(c, t["seller"]["id"]) == before
    _assert_reconciles(c)


def test_partial_then_remainder_refund_reverses_everything_and_releases_nothing(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _refund(c, order["id"], PARTIAL_P / 100, reference="R1")
    _refund(c, order["id"], None, reference="R2")                      # the final refund takes the exact remainder
    assert all(r["status"] == "REVERSED" for r in _commissions(c, order["id"]))
    _release(c)
    assert _points_released_rows(c, order["id"]) == 0
    assert _wallet(c, t["seller"]["id"])["total_earned_paise"] == 0
    _assert_reconciles(c)


def test_refund_after_release_claws_back_from_available_and_is_not_released_again(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _release(c)
    assert _wallet(c, t["seller"]["id"])["available_balance_paise"] == 30000
    _refund(c, order["id"], PARTIAL_P / 100)
    w = _wallet(c, t["seller"]["id"])
    assert (w["available_balance_paise"], w["total_earned_paise"]) == (15000, 15000)
    _release(c)
    assert _wallet(c, t["seller"]["id"])["available_balance_paise"] == 15000   # not released a second time
    _assert_reconciles(c)


def test_refund_for_an_order_with_nothing_credited_is_harmless(c):
    t = _tree(c)
    order = _order(c, t)                                               # never distributed
    _refund(c, order["id"], None)
    _assert_reconciles(c)


# ============================================================ 5. repeated and concurrent processing
def test_concurrent_release_runs_release_each_commission_once(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)

    async def both():
        return await asyncio.gather(release_due_points(FUTURE), release_due_points(FUTURE))
    _run(c, both)
    assert _points_released_rows(c, order["id"]) == 3                 # exactly one ledger release per commission
    assert set(_states(c, order["id"]).values()) == {"RELEASED"}
    assert _wallet(c, t["seller"]["id"])["available_balance_paise"] == 30000
    assert _wallet(c, t["seller"]["id"])["total_earned_paise"] == 30000
    _assert_reconciles(c)


def test_repeated_refund_with_the_same_reference_claws_back_once(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _release(c)
    first = _refund(c, order["id"], PARTIAL_P / 100, reference="SAME")
    before = _wallet(c, t["seller"]["id"])
    second = _refund(c, order["id"], PARTIAL_P / 100, reference="SAME")
    assert second.get("duplicate") is True, second
    assert _wallet(c, t["seller"]["id"]) == before
    assert first["reversed"] == 3
    _assert_reconciles(c)


def test_a_stale_refund_is_recomputed_after_the_commission_was_released(c):
    """A refund that read the commission while it was pending must re-read it when a release changed it first."""
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    stale = _commissions(c, order["id"])
    direct_stale = next(r for r in stale if r["type"] == commission.TXN_DIRECT)
    _release(c)                                                        # the release wins the race
    event = {"id": "stale-event", "amount_paise": PARTIAL_P, "closes_order": False}
    _run(c, lambda: shop_routes._reverse_commission(direct_stale, event, {"total_paise": TOTAL_P, "order_number": order["order_number"]}))
    w = _wallet(c, t["seller"]["id"])
    assert w["pending_balance_paise"] == 0
    assert w["available_balance_paise"] == 15000                       # 30000 released, 15000 clawed back as released credit
    _assert_reconciles(c)


# ============================================================ 2 (cont.). zero-day and default schedules, end to end
def test_zero_day_schedule_is_released_at_once_and_still_respects_refunds(c):
    _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"return_window_days": 0}}))
    try:
        t = _tree(c)
        order = _order(c, t)
        _distribute(c, t, order)
        rows = _commissions(c, order["id"])
        assert all(r["release_after_days"] == 0 for r in rows)
        _release(c, datetime.now(timezone.utc) + timedelta(seconds=1))
        assert set(_states(c, order["id"]).values()) == {"RELEASED"}
        _assert_reconciles(c)
        refunded = _tree(c)
        order2 = _order(c, refunded)
        _distribute(c, refunded, order2)
        _refund(c, order2["id"], None)                                 # refunded before the job ran
        _release(c, datetime.now(timezone.utc) + timedelta(seconds=1))
        assert set(_states(c, order2["id"]).values()) == {"REVERSED"}  # zero days does not bypass the refund
        assert _wallet(c, refunded["seller"]["id"])["available_balance_paise"] == 0
        _assert_reconciles(c)
    finally:
        _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"return_window_days": 7}}))


def test_default_schedule_waits_seven_days_when_the_value_is_absent(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _run(c, lambda: db.commissions.update_many({"order_id": order["id"]}, {"$unset": {"release_after_days": ""}}))
    created = datetime.fromisoformat(_commissions(c, order["id"])[0]["created_at"])
    _release(c, created + timedelta(days=6))
    assert set(_states(c, order["id"]).values()) == {"PENDING"}
    _release(c, created + timedelta(days=7, hours=1))                 # a few milliseconds separate the three records
    assert set(_states(c, order["id"]).values()) == {"RELEASED"}
    _assert_reconciles(c)


def test_invalid_hold_period_is_never_released_automatically(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _run(c, lambda: db.commissions.update_many({"order_id": order["id"]}, {"$set": {"release_after_days": -1}}))
    result = _release(c)
    assert result["invalid"] >= 3
    assert set(_states(c, order["id"]).values()) == {"PENDING"}
    assert _wallet(c, t["seller"]["id"])["pending_balance_paise"] == 30000


def test_an_invalid_return_window_credits_nothing_and_can_be_retried(c):
    _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"return_window_days": "soon"}}))
    try:
        t = _tree(c)
        order = _order(c, t)
        result = _run(c, lambda: distribute_sale_commissions(order, t["buyer"]))
        assert result == {"credited": 0, "reason": "invalid_return_window"}
        assert _commissions(c, order["id"]) == []
        assert _run(c, lambda: db.orders.find_one({"id": order["id"]}, {"commissions_paid": 1})).get("commissions_paid") is not True
    finally:
        _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"return_window_days": 7}}))
    _assert_reconciles(c)


# ============================================================ 4. account deactivation instead of deletion
def _admin_headers(c):
    admin = _user(role="super_admin")
    _run(c, lambda: _insert_users([admin]))
    return {"Authorization": f"Bearer {create_token(admin['id'])}"}


def test_deleting_a_member_deactivates_and_keeps_every_financial_record(c):
    t = _tree(c)
    order = _order(c, t)
    _distribute(c, t, order)
    _release(c)
    victim = t["seller"]
    token = create_token(victim["id"])
    headers = _admin_headers(c)
    before_wallet = _wallet(c, victim["id"])
    before_ledger = _run(c, lambda: db.wallet_transactions.count_documents({"user_id": victim["id"]}))
    before_commissions = _commissions(c, order["id"])

    first = c.delete(f"/api/admin/users/{victim['id']}", headers=headers)
    assert first.status_code == 200 and first.json() == {"ok": True, "deactivated": True}
    second = c.delete(f"/api/admin/users/{victim['id']}", headers=headers)
    assert second.status_code == 200 and second.json() == {"ok": True, "already_deactivated": True}

    stored = _run(c, lambda: db.users.find_one({"id": victim["id"]}, {"_id": 0}))
    assert stored is not None and stored["account_status"] == "deleted" and stored["blocked"] is True
    assert _wallet(c, victim["id"]) == before_wallet                              # wallet kept, unchanged
    assert _run(c, lambda: db.wallet_transactions.count_documents({"user_id": victim["id"]})) == before_ledger
    assert _commissions(c, order["id"]) == before_commissions
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "user_deactivated", "entity_id": victim["id"]})) == 1

    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401   # the old session stops
    login = c.post("/api/auth/login", json={"email": victim["email"], "password": PW})
    assert login.status_code == 403
    _assert_reconciles(c)


def test_admin_accounts_and_unknown_users_are_handled_safely(c):
    headers = _admin_headers(c)
    target_admin = _user(role="super_admin")
    _run(c, lambda: _insert_users([target_admin]))
    assert c.delete(f"/api/admin/users/{target_admin['id']}", headers=headers).status_code == 400
    assert c.delete("/api/admin/users/does-not-exist", headers=headers).status_code == 404
