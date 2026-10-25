"""Phase 16: login-OTP enumeration, forgot-password rate limits and reset, and read-only wallet/ledger reconciliation.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_recovery_and_ledger.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_recovery_ledger_test", "JWT_SECRET": "recovery-ledger-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "SMS_TEST_ADAPTER": "true"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import core  # noqa: E402
import providers  # noqa: E402
import auth_routes  # noqa: E402
import commission  # noqa: E402
import wallet_reconcile  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id, add_wallet_transaction  # noqa: E402
from fastapi import HTTPException  # noqa: E402

PW = "Member-Pass-1234"
NEW_PW = "Reset-Pass-5678"
S = {}
RESET_RATE = {"forgot_password": (1000, 3600), "forgot_reset": (1000, 3600), "login_otp_send": (1000, 3600),
              "login_otp_verify": (1000, 3600), "withdraw": (1000, 3600)}


def _h(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            people = (("member", "9100009001", "member@example.com", "distributor", False),
                      ("blocked", "9100009002", "blocked@example.com", "distributor", True),
                      ("admin", "9100009003", "admin@example.com", "super_admin", False),
                      ("ledger", "9100009004", "ledger@example.com", "distributor", False),
                      ("drift", "9100009005", "drift@example.com", "distributor", False))
            for key, mobile, email, role, blocked in people:
                S[key] = {"id": new_id(), "distributor_id": key.upper() + "1", "full_name": key, "mobile": mobile,
                          "email": email, "password_hash": hash_password(PW), "role": role,
                          "status": "green", "account_status": "active", "blocked": blocked,
                          "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(S[key]))
                await core.get_or_create_wallet(S[key]["id"])
        client.portal.call(seed)
        for name, limit in RESET_RATE.items():
            core.RATE_LIMITS[name] = limit
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _clear_rate_limits(c):
    """Counters are per IP and window; a rate-limit test starts from zero so earlier calls cannot decide its outcome."""
    _run(c, lambda: db.rate_limits.delete_many({}))


def _outbox(c, mobile):
    return _run(c, lambda: db.test_sms_outbox.find_one({"mobile": mobile}, sort=[("created_at", -1)]))


def _fresh_otp(c, mobile):
    """Ends any earlier OTP for this number, so the 60-second resend cooldown from a previous test cannot apply."""
    _run(c, lambda: db.otp_sessions.delete_many({"identifier": mobile, "purpose": "login"}))


def _send(c, mobile):
    return c.post("/api/auth/login-otp/send", json={"mobile": mobile})


def _verify(c, mobile, otp):
    return c.post("/api/auth/login-otp/verify", json={"mobile": mobile, "otp": otp})


# ================================================================ 2. login-OTP: no enumeration
def test_known_unknown_admin_and_blocked_numbers_get_the_same_send_response(c):
    answers = {m: _send(c, m) for m in ("9100009001", "9199999999", "9100009003", "9100009002")}
    bodies = {m: r.json() for m, r in answers.items()}
    assert all(r.status_code == 200 for r in answers.values()), {m: r.status_code for m, r in answers.items()}
    assert len({str(b) for b in bodies.values()}) == 1 and bodies["9100009001"] == {"message": auth_routes.LOGIN_OTP_SENT}


def test_an_otp_is_delivered_only_to_eligible_accounts(c):
    assert _outbox(c, "9100009001") is not None                        # ordinary member: delivered
    assert _outbox(c, "9199999999") is None                             # unknown number: nothing sent
    assert _outbox(c, "9100009003") is None                             # admin: nothing sent
    assert _outbox(c, "9100009002") is None                             # blocked: nothing sent


def test_the_send_response_never_contains_a_code(c):
    _fresh_otp(c, "9100009001")
    row = _outbox(c, "9100009001")
    assert row["code"] not in _send(c, "9100009001").text
    assert set(_send(c, "9100009001").json()) == {"message"}


def test_a_second_send_inside_the_cooldown_looks_the_same_as_a_first(c):
    first = _send(c, "9100009004")
    second = _send(c, "9100009004")                                     # cooldown: the provider would refuse (429)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()


def test_known_and_unknown_numbers_with_a_failed_delivery_look_the_same(c, monkeypatch):
    async def down(mobile, code):
        raise HTTPException(status_code=503, detail="Could not send OTP right now. Please try again shortly.")
    monkeypatch.setattr(providers, "_send_sms_otp", down)
    known = _send(c, "9100009005")
    unknown = _send(c, "9199999998")
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()


def test_when_no_sms_provider_is_configured_every_number_gets_the_same_503(c, monkeypatch):
    monkeypatch.setenv("SMS_TEST_ADAPTER", "false")
    monkeypatch.setattr(providers, "TWILIO_ENABLED", False)
    known = _send(c, "9100009001")
    unknown = _send(c, "9199999997")
    assert known.status_code == unknown.status_code == 503
    assert known.json() == unknown.json()


def test_correct_code_signs_in_and_is_single_use(c):
    _fresh_otp(c, "9100009001")
    _send(c, "9100009001")
    code = _outbox(c, "9100009001")["code"]
    ok = _verify(c, "9100009001", code)
    assert ok.status_code == 200 and ok.json()["token"]
    again = _verify(c, "9100009001", code)
    assert again.status_code == 400 and again.json()["detail"] == auth_routes.LOGIN_OTP_INVALID


def test_wrong_unknown_admin_and_blocked_codes_get_the_same_refusal(c):
    _fresh_otp(c, "9100009001")
    _send(c, "9100009001")
    wrong = "000000" if _outbox(c, "9100009001")["code"] != "000000" else "111111"
    answers = [_verify(c, "9100009001", wrong), _verify(c, "9199999996", "123456"),
               _verify(c, "9100009003", "123456"), _verify(c, "9100009002", "123456")]
    assert all(r.status_code == 400 and r.json()["detail"] == auth_routes.LOGIN_OTP_INVALID for r in answers)


def test_an_expired_code_is_refused(c):
    _fresh_otp(c, "9100009004")
    _send(c, "9100009004")
    code = _outbox(c, "9100009004")["code"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _run(c, lambda: db.otp_sessions.update_many({"identifier": "9100009004", "purpose": "login"}, {"$set": {"expires_at": past}}))
    r = _verify(c, "9100009004", code)
    assert r.status_code == 400 and r.json()["detail"] == auth_routes.LOGIN_OTP_INVALID


def test_too_many_wrong_codes_lock_out_even_the_correct_one(c):
    _fresh_otp(c, "9100009005")
    _send(c, "9100009005")
    good = _outbox(c, "9100009005")["code"]
    wrong = "000000" if good != "000000" else "111111"
    for _ in range(providers.OTP_MAX_ATTEMPTS):
        _verify(c, "9100009005", wrong)
    locked = _verify(c, "9100009005", good)
    assert locked.status_code == 400 and locked.json()["detail"] == auth_routes.LOGIN_OTP_INVALID


def test_verify_rate_limit_applies_to_known_and_unknown_numbers_alike(c, monkeypatch):
    monkeypatch.setitem(core.RATE_LIMITS, "login_otp_verify", (3, 3600))
    _clear_rate_limits(c)
    known = [_verify(c, "9100009001", "000000").status_code for _ in range(4)]
    unknown = [_verify(c, "9199999995", "000000").status_code for _ in range(4)]
    assert known[-1] == unknown[-1] == 429, (known, unknown)


def test_send_rate_limit_applies_to_known_and_unknown_numbers_alike(c, monkeypatch):
    monkeypatch.setitem(core.RATE_LIMITS, "login_otp_send", (3, 3600))
    _clear_rate_limits(c)
    known = [_send(c, "9100009001").status_code for _ in range(4)]
    unknown = [_send(c, "9199999994").status_code for _ in range(4)]
    assert known[-1] == unknown[-1] == 429, (known, unknown)


# ================================================================ 3. forgot-password: limits, queue, reset, revocation
def _forgot(c, identifier):
    return c.post("/api/auth/forgot/send", json={"identifier": identifier})


def test_forgot_answers_known_and_unknown_identifiers_identically(c):
    known = _forgot(c, "9100009001")
    unknown = _forgot(c, "9199999993")
    assert known.status_code == unknown.status_code == 200 and known.json() == unknown.json()


def test_forgot_rate_limit_is_enforced_for_known_and_unknown_identifiers(c, monkeypatch):
    monkeypatch.setitem(core.RATE_LIMITS, "forgot_password", (3, 3600))
    _clear_rate_limits(c)
    known = [_forgot(c, "9100009001").status_code for _ in range(4)]
    unknown = [_forgot(c, "9199999992").status_code for _ in range(4)]
    assert known[-1] == unknown[-1] == 429, (known, unknown)


def test_request_reaches_the_admin_queue_and_the_admin_reset_closes_it(c):
    admin = _h(S["admin"]["id"])
    _forgot(c, "9100009001")
    queue = c.get("/api/admin/password-reset-requests", headers=admin).json()
    assert any(x["user_id"] == S["member"]["id"] for x in queue)
    old_session = _h(S["member"]["id"])
    assert c.get("/api/auth/me", headers=old_session).status_code == 200
    reset = c.post(f"/api/admin/users/{S['member']['id']}/reset-password", json={"password": NEW_PW}, headers=admin)
    assert reset.status_code == 200, reset.text
    queue_after = c.get("/api/admin/password-reset-requests", headers=admin).json()
    assert not any(x["user_id"] == S["member"]["id"] for x in queue_after)
    assert c.post("/api/auth/login", json={"email": "member@example.com", "password": NEW_PW}).status_code == 200
    assert c.post("/api/auth/login", json={"email": "member@example.com", "password": PW}).status_code == 401
    assert c.get("/api/auth/me", headers=old_session).status_code == 401       # sessions from before the reset are revoked


def test_members_and_anonymous_callers_cannot_use_the_admin_reset(c):
    target = S["ledger"]["id"]
    assert c.post(f"/api/admin/users/{target}/reset-password", json={"password": NEW_PW}).status_code in (401, 403)
    assert c.post(f"/api/admin/users/{target}/reset-password", json={"password": NEW_PW},
                  headers=_h(S["member"]["id"])).status_code in (401, 403)


def test_admin_reset_refuses_a_short_password(c):
    r = c.post(f"/api/admin/users/{S['ledger']['id']}/reset-password", json={"password": "short"}, headers=_h(S["admin"]["id"]))
    assert r.status_code == 400


# ================================================================ 4. wallet/ledger reconciliation (read-only)
def _ledger_flows(c):
    """Real write paths: a credit, a pending commission released by the job, a withdrawal paid, and a withdrawal rejected."""
    uid = S["ledger"]["id"]
    _run(c, lambda: add_wallet_transaction(uid, "MANUAL_ADMIN_CREDIT", 1000, "CREDITED",
                                           reference=f"test:credit:{uid}", description="test credit"))
    order_id = new_id()
    _run(c, lambda: db.orders.insert_one({"id": order_id, "order_number": "TST-1", "payment_status": "paid", "user_id": uid}))
    _run(c, lambda: add_wallet_transaction(uid, "COMMISSION_REFERRAL", 200, "PENDING", reference=order_id, description="test commission"))
    _run(c, lambda: db.commissions.insert_one({
        "id": new_id(), "order_id": order_id, "order_number": "TST-1", "user_id": uid, "type": "COMMISSION_REFERRAL",
        "amount": 200.0, "amount_paise": 20000, "status": "PENDING", "release_after_days": 1,
        "created_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}))
    _run(c, lambda: commission.release_due_points())
    for amount, action in ((300, "mark_paid"), (100, "reject")):
        r = c.post("/api/withdrawals", json={"amount": amount}, headers=_h(uid))
        assert r.status_code == 200, r.text
        wd = r.json()
        wd_id = wd.get("id") or wd.get("request", {}).get("id")
        review = c.put(f"/api/admin/withdrawals/{wd_id}", json={"action": action}, headers=_h(S["admin"]["id"]))
        assert review.status_code == 200, review.text


async def _ledger_snapshot():
    return (await db.wallets.find({}, {"_id": 0}).to_list(1000), await db.wallet_transactions.find({}, {"_id": 0}).to_list(1000))


def _kyc_verified(c, uid):
    _run(c, lambda: db.kyc_records.insert_one({"id": new_id(), "user_id": uid, "status": "verified", "created_at": now_iso()}))


def test_ledger_and_wallet_reconcile_after_real_write_paths(c):
    _kyc_verified(c, S["ledger"]["id"])
    _ledger_flows(c)
    before = _run(c, _ledger_snapshot)
    result = _run(c, wallet_reconcile.reconcile)
    after = _run(c, _ledger_snapshot)
    assert result["discrepancies"] == [], result
    assert result["wallets_checked"] >= 1
    assert before == after, "reconciliation must be read-only"
    w = _run(c, lambda: db.wallets.find_one({"user_id": S["ledger"]["id"]}))
    assert (w["total_earned_paise"], w["total_withdrawn_paise"], w["pending_balance_paise"], w["available_balance_paise"]) == \
        (120000, 30000, 0, 90000)                                       # 1000 + 200 earned; 300 paid; 100 returned to available


def test_a_direct_balance_write_is_reported_and_not_repaired(c):
    uid = S["drift"]["id"]
    _run(c, lambda: add_wallet_transaction(uid, "MANUAL_ADMIN_CREDIT", 50, "CREDITED", reference=f"test:drift:{uid}"))
    _run(c, lambda: db.wallets.update_one({"user_id": uid}, {"$inc": {"available_balance_paise": 100, "available_balance": 1.0}}))
    result = _run(c, lambda: wallet_reconcile.reconcile(uid))
    fields = {d.get("field"): d for d in result["discrepancies"]}
    assert "available_balance" in fields and fields["available_balance"]["difference_paise"] == 100
    stored = _run(c, lambda: db.wallets.find_one({"user_id": uid}))
    assert stored["available_balance_paise"] == 5100                    # left exactly as written: reported, not repaired


def test_ledger_history_of_a_deleted_wallet_is_reported_as_orphaned_not_as_an_error(c):
    gone = new_id()
    _run(c, lambda: add_wallet_transaction(gone, "MANUAL_ADMIN_CREDIT", 10, "CREDITED", reference=f"test:orphan:{gone}"))
    _run(c, lambda: db.wallets.delete_many({"user_id": gone}))
    result = _run(c, wallet_reconcile.reconcile)
    assert gone in result["orphan_ledger_users"]
    assert not any(d.get("user_id") == gone for d in result["discrepancies"])
