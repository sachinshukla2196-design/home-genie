"""BETA mobile-OTP auth tests: registration OTP, approved test number, login-with-OTP,
forgot password, change mobile, OTP security (hashing/single-use/attempts/cooldown).

Uses the public REACT_APP_BACKEND_URL. Cleans up created users via direct Mongo access.
"""
import os
import secrets
import time

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

fe = dotenv_values("/app/frontend/.env")
be = dotenv_values("/app/backend/.env")
BASE = (os.environ.get("REACT_APP_BACKEND_URL") or fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE}/api"
TIMEOUT = 30

ADMIN_EMAIL = os.environ["TEST_ADMIN_EMAIL"]
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")
TEST_NUMBER = "9999999999"  # the admin seed mobile: admins never sign in by login-OTP
TEST_OTP = "123456"  # a fixed code that must never be accepted
LOGIN_OTP_GENERIC = {"message": "If this mobile number is registered, an OTP has been sent to it."}
LOGIN_OTP_INVALID = "The OTP is invalid or has expired. Please request a new one."

_created_emails = []
_created_mobiles = []


SPONSOR = os.getenv("TEST_SPONSOR_ID", "MST000001")


def _mongo():
    cli = MongoClient(os.environ.get("MONGO_URL") or be.get("MONGO_URL"), serverSelectionTimeoutMS=5000)
    return cli, cli[os.environ.get("DB_NAME") or be.get("DB_NAME")]


def _last_sms_otp():
    """The code the TEST SMS adapter recorded for the most recent OTP. The API never returns it."""
    cli, db = _mongo()
    try:
        row = db.test_sms_outbox.find_one({}, sort=[("created_at", -1)])
    finally:
        cli.close()
    assert row, "no test SMS recorded (backend needs SMS_TEST_ADAPTER=true on a *_test database)"
    return row["code"]


def rnd_mobile():
    m = f"9{secrets.randbelow(900000000) + 100000000}"
    _created_mobiles.append(m)
    return m


def rnd_email():
    e = f"test_otp_{secrets.randbelow(900000) + 100000}@qa-homegenies.example.com"
    _created_emails.append(e)
    return e


def register_user(sponsor_id=os.getenv("TEST_SPONSOR_ID", "MST000001"), password=os.getenv("TEST_USER_PASSWORD", "Test@1234")):
    """Register a throwaway RED user; returns dict with creds + token."""
    email, mobile = rnd_email(), rnd_mobile()
    r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
    assert r.status_code == 200, f"send-otp failed: {r.status_code} {r.text[:300]}"
    assert "dev_otp" not in r.json()
    otp = _last_sms_otp()
    r = requests.post(f"{API}/auth/register", json={
        "full_name": "TEST QA User", "email": email, "mobile": mobile,
        "password": password, "confirm_password": password, "otp": otp,
        "sponsor_id": sponsor_id, "accept_terms": True,
    }, timeout=TIMEOUT)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text[:300]}"
    d = r.json()
    return {"email": email, "mobile": mobile, "password": password,
            "token": d["token"], "user": d["user"], "otp": otp}


@pytest.fixture(scope="session", autouse=True)
def cleanup():
    yield
    try:
        cli, db = _mongo()
        db.users.delete_many({"email": {"$in": _created_emails}})
        db.otp_sessions.delete_many({"identifier": {"$in": _created_mobiles}})
        cli.close()
    except Exception as e:
        print(f"cleanup skipped: {e}")


# ---------------- Registration OTP ----------------
class TestRegistrationOtp:
    def test_send_otp_delivers_by_sms_and_never_returns_the_code(self):
        r = requests.post(f"{API}/auth/send-otp",
                          json={"email": rnd_email(), "mobile": rnd_mobile(), "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json() == {"message": "OTP sent to your mobile."}
        code = _last_sms_otp()
        assert len(code) == 6 and code.isdigit()

    def test_send_otp_duplicate_email_rejected(self):
        r = requests.post(f"{API}/auth/send-otp",
                          json={"email": ADMIN_EMAIL, "mobile": rnd_mobile()}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]
        assert "already registered" in r.json()["detail"].lower()

    def test_send_otp_duplicate_mobile_rejected(self):
        r = requests.post(f"{API}/auth/send-otp",
                          json={"email": rnd_email(), "mobile": TEST_NUMBER}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]
        assert "mobile" in r.json()["detail"].lower()

    def test_send_otp_invalid_mobile_rejected(self):
        r = requests.post(f"{API}/auth/send-otp",
                          json={"email": rnd_email(), "mobile": "12345"}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]

    def test_register_creates_red_user_with_unique_anj_id(self):
        a = register_user()
        b = register_user()
        for u in (a["user"], b["user"]):
            assert u["status"] == "red"
            assert u["distributor_id"].startswith("HG") and len(u["distributor_id"]) == 8  # HG + 6 digits
            assert "password_hash" not in u and "_id" not in u
        assert a["user"]["distributor_id"] != b["user"]["distributor_id"]
        # /me persistence check
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {a['token']}"}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["email"] == a["email"]
        assert r.json()["mobile_verified"] is True

    def test_register_wrong_otp_rejected(self):
        email, mobile = rnd_email(), rnd_mobile()
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r.status_code == 200
        good = _last_sms_otp()
        bad = "000000" if good != "000000" else "111111"
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Bad OTP", "email": email, "mobile": mobile,
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": bad,
            "accept_terms": True}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]
        assert "otp" in r.json()["detail"].lower()

    def test_register_reused_otp_rejected(self):
        u = register_user()
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Reuse", "email": rnd_email(), "mobile": u["mobile"],
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": u["otp"],
            "accept_terms": True}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]

    def test_register_without_otp_request_rejected(self):
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST NoOtp", "email": rnd_email(), "mobile": rnd_mobile(),
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": "123456",
            "accept_terms": True}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]


# ---------------- Approved test number ----------------
class TestApprovedTestNumber:
    @pytest.fixture(autouse=True)
    def _clear_cooldown(self):
        """Clear prior OTP sessions for the shared approved test number so the 30s
        resend cooldown from earlier runs doesn't mask real behaviour."""
        cli, db = _mongo()
        db.otp_sessions.delete_many({"identifier": TEST_NUMBER})
        cli.close()
        yield

    # Retired by design: the static "approved test number" OTP was removed. Admin accounts never sign in by
    # login-OTP, and no fixed code is accepted for any number.
    def test_login_otp_send_for_admin_number_gives_the_generic_answer_and_no_code(self):
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": TEST_NUMBER}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json() == LOGIN_OTP_GENERIC
        assert "dev_otp" not in r.text

    def test_static_otp_is_never_accepted_for_admin_number(self):
        r = requests.post(f"{API}/auth/login-otp/verify",
                          json={"mobile": TEST_NUMBER, "otp": TEST_OTP}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]
        assert r.json()["detail"] == LOGIN_OTP_INVALID
        assert "token" not in r.json()

    def test_login_otp_unknown_mobile_gets_the_same_send_answer_as_a_registered_one(self):
        unknown = requests.post(f"{API}/auth/login-otp/send", json={"mobile": "6000000001"}, timeout=TIMEOUT)
        assert unknown.status_code == 200, unknown.text[:300]
        assert unknown.json() == LOGIN_OTP_GENERIC

    def test_login_otp_unknown_mobile_verify_gets_the_same_refusal_as_a_wrong_code(self):
        unknown = requests.post(f"{API}/auth/login-otp/verify",
                                json={"mobile": "6000000002", "otp": "123456"}, timeout=TIMEOUT)
        assert unknown.status_code == 400, unknown.text[:300]
        assert unknown.json()["detail"] == LOGIN_OTP_INVALID


# ---------------- Login with OTP (normal user) ----------------
class TestLoginOtpNormalUser:
    def test_login_otp_flow_for_registered_user(self):
        u = register_user()
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        otp = _last_sms_otp()
        assert otp and r.json() == LOGIN_OTP_GENERIC
        r = requests.post(f"{API}/auth/login-otp/verify",
                          json={"mobile": u["mobile"], "otp": otp}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["user"]["email"] == u["email"]
        assert d["user"]["distributor_id"] == u["user"]["distributor_id"]
        # single use
        r = requests.post(f"{API}/auth/login-otp/verify",
                          json={"mobile": u["mobile"], "otp": otp}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]


# ---------------- Forgot password: admin-assisted by design (no OTP, no SMS) ----------------
NEW_PW = "NewPass@9876"


def _admin_headers():
    r = requests.post(f"{API}/auth/admin-login", json={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=TIMEOUT)
    assert r.status_code == 200, r.text[:200]
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _login(identifier, password):
    return requests.post(f"{API}/auth/login", json={"email": identifier, "password": password}, timeout=TIMEOUT)


class TestForgotPassword:
    """Approved recovery design: the member files a request, an admin sets a new password. The UI states there is no OTP."""

    def test_request_reaches_the_admin_queue_and_exposes_no_secret(self):
        u = register_user()
        r = requests.post(f"{API}/auth/forgot/send", json={"identifier": u["mobile"]}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert set(r.json()) == {"message"}                  # no code, token or password field in the response
        queue = requests.get(f"{API}/admin/password-reset-requests", headers=_admin_headers(), timeout=TIMEOUT).json()
        assert any(x["user_id"] == u["user"]["id"] for x in queue)

    def test_unknown_and_known_identifiers_get_the_same_answer(self):
        u = register_user()
        known = requests.post(f"{API}/auth/forgot/send", json={"identifier": u["mobile"]}, timeout=TIMEOUT)
        unknown = requests.post(f"{API}/auth/forgot/send", json={"identifier": "6000000003"}, timeout=TIMEOUT)
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()

    def test_blank_identifier_is_refused(self):
        r = requests.post(f"{API}/auth/forgot/send", json={"identifier": "  "}, timeout=TIMEOUT)
        assert r.status_code == 400

    def test_admin_reset_then_new_password_works_and_old_password_fails(self):
        u = register_user()
        requests.post(f"{API}/auth/forgot/send", json={"identifier": u["mobile"]}, timeout=TIMEOUT)
        r = requests.post(f"{API}/admin/users/{u['user']['id']}/reset-password",
                          json={"password": NEW_PW}, headers=_admin_headers(), timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert _login(u["email"], NEW_PW).status_code == 200
        assert _login(u["email"], u["password"]).status_code == 401
        queue = requests.get(f"{API}/admin/password-reset-requests", headers=_admin_headers(), timeout=TIMEOUT).json()
        assert not any(x["user_id"] == u["user"]["id"] for x in queue)     # the request was resolved

    def test_reset_revokes_sessions_issued_before_it(self):
        u = register_user()
        h = {"Authorization": f"Bearer {u['token']}"}
        assert requests.get(f"{API}/auth/me", headers=h, timeout=TIMEOUT).status_code == 200
        requests.post(f"{API}/admin/users/{u['user']['id']}/reset-password",
                      json={"password": NEW_PW}, headers=_admin_headers(), timeout=TIMEOUT)
        assert requests.get(f"{API}/auth/me", headers=h, timeout=TIMEOUT).status_code == 401

    def test_short_admin_password_is_refused(self):
        u = register_user()
        r = requests.post(f"{API}/admin/users/{u['user']['id']}/reset-password",
                          json={"password": "123"}, headers=_admin_headers(), timeout=TIMEOUT)
        assert r.status_code == 400

    def test_members_cannot_reset_other_passwords(self):
        u, other = register_user(), register_user()
        r = requests.post(f"{API}/admin/users/{other['user']['id']}/reset-password",
                          json={"password": NEW_PW}, headers={"Authorization": f"Bearer {u['token']}"}, timeout=TIMEOUT)
        assert r.status_code in (401, 403), r.text[:200]
        assert _login(other["email"], other["password"]).status_code == 200


# ---------------- Change mobile ----------------
class TestChangeMobile:
    def test_change_mobile_success_and_login_with_new_mobile(self):
        u = register_user()
        h = {"Authorization": f"Bearer {u['token']}"}
        new_mobile = rnd_mobile()
        r = requests.put(f"{API}/auth/change-mobile/send", json={"mobile": new_mobile}, headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        otp = _last_sms_otp()
        r = requests.put(f"{API}/auth/change-mobile/verify",
                         json={"mobile": new_mobile, "otp": otp}, headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["mobile"] == new_mobile
        # persisted
        me = requests.get(f"{API}/auth/me", headers=h, timeout=TIMEOUT)
        assert me.json()["mobile"] == new_mobile
        # old mobile no longer resolves for login-otp
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        assert r.status_code == 200 and r.json() == LOGIN_OTP_GENERIC      # no longer reveals that the number is gone

    def test_change_mobile_duplicate_rejected(self):
        u = register_user()
        h = {"Authorization": f"Bearer {u['token']}"}
        r = requests.put(f"{API}/auth/change-mobile/send", json={"mobile": TEST_NUMBER}, headers=h, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]
        assert "another account" in r.json()["detail"].lower()

    def test_change_mobile_invalid_number_rejected(self):
        u = register_user()
        h = {"Authorization": f"Bearer {u['token']}"}
        r = requests.put(f"{API}/auth/change-mobile/send", json={"mobile": "1234"}, headers=h, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]

    def test_change_mobile_requires_auth(self):
        r = requests.put(f"{API}/auth/change-mobile/send", json={"mobile": rnd_mobile()}, timeout=TIMEOUT)
        assert r.status_code in (401, 403), r.status_code


# ---------------- OTP security ----------------
class TestOtpSecurity:
    def test_otp_stored_hashed_not_plaintext(self):
        email, mobile = rnd_email(), rnd_mobile()
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        otp = _last_sms_otp()
        cli, db = _mongo()
        rec = db.otp_sessions.find_one({"identifier": mobile, "purpose": "register"})
        cli.close()
        assert rec is not None, "otp_sessions record missing"
        assert "code_hash" in rec and len(rec["code_hash"]) == 64
        assert rec["code_hash"] != otp
        assert otp not in str(rec), f"plaintext OTP found in db record: {rec}"
        assert rec["used"] is False and rec["attempts"] == 0
        assert "expires_at" in rec

    def test_attempt_limit_locks_after_5(self):
        email, mobile = rnd_email(), rnd_mobile()
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r.status_code == 200
        good = _last_sms_otp()
        bad = "000000" if good != "000000" else "111111"
        codes = []
        for _ in range(5):
            rr = requests.post(f"{API}/auth/register", json={
                "full_name": "TEST Attempts", "email": email, "mobile": mobile,
                "password": "Test@1234", "confirm_password": "Test@1234", "otp": bad,
                "accept_terms": True}, timeout=TIMEOUT)
            codes.append(rr.status_code)
        assert codes == [400] * 5, codes
        # 6th attempt -> locked out (429), and even the correct OTP must fail now
        rr = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Attempts", "email": email, "mobile": mobile,
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": good,
            "accept_terms": True}, timeout=TIMEOUT)
        assert rr.status_code == 429, f"{rr.status_code} {rr.text[:300]}"

    def test_resend_cooldown_429(self):
        email, mobile = rnd_email(), rnd_mobile()
        r1 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r2.status_code == 429, f"{r2.status_code} {r2.text[:300]}"

    @pytest.mark.slow
    def test_resend_allowed_after_cooldown(self):
        email, mobile = rnd_email(), rnd_mobile()
        r1 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r1.status_code == 200
        first_code = _last_sms_otp()
        time.sleep(int(os.getenv("OTP_RESEND_COOLDOWN", "60")) + 2)  # the configured cooldown, not a fixed guess
        r2 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": SPONSOR}, timeout=TIMEOUT)
        assert r2.status_code == 200, f"{r2.status_code} {r2.text[:300]}"
        second_code = _last_sms_otp()
        # old OTP invalidated, new one works
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Cooldown", "email": email, "mobile": mobile,
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": first_code,
            "accept_terms": True}, timeout=TIMEOUT)
        assert r.status_code == 400, f"old OTP should be invalid: {r.status_code}"
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Cooldown", "email": email, "mobile": mobile,
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": second_code,
            "accept_terms": True}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]


# ---------------- Regression: existing credentials still work ----------------
class TestCredentialRegression:
    def test_admin_password_login(self):
        r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["user"]["role"] == "super_admin"
        t = r.json()["token"]
        d = requests.get(f"{API}/admin/dashboard", headers={"Authorization": f"Bearer {t}"}, timeout=TIMEOUT)
        assert d.status_code == 200

    def test_demo_distributor_login(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": "demo.distributor@homegenies.example.com", "password": "Demo@1234"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        u = r.json()["user"]
        assert u["status"] == "green" and u["mobile"] == "9000000018"

    def test_admin_password_hash_is_bcrypt(self):
        cli, db = _mongo()
        u = db.users.find_one({"email": ADMIN_EMAIL})
        cli.close()
        assert u and u["password_hash"].startswith("$2b$"), u.get("password_hash", "")[:10]
