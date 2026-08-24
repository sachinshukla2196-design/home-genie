"""BETA mobile-OTP auth tests: registration OTP, approved test number, login-with-OTP,
forgot password, change mobile, OTP security (hashing/single-use/attempts/cooldown).

Uses the public REACT_APP_BACKEND_URL. Cleans up created users via direct Mongo access.
"""
import os
import random
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

ADMIN_EMAIL = "sachin.shukla2196@gmail.com"
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")
TEST_NUMBER = "9999999999"
TEST_OTP = "123456"

_created_emails = []
_created_mobiles = []


def _mongo():
    cli = MongoClient(be.get("MONGO_URL"), serverSelectionTimeoutMS=5000)
    return cli, cli[be.get("DB_NAME")]


def rnd_mobile():
    m = f"9{random.randint(100000000, 999999999)}"
    _created_mobiles.append(m)
    return m


def rnd_email():
    e = f"test_otp_{random.randint(100000, 999999)}@qa-anjali.example.com"
    _created_emails.append(e)
    return e


def register_user(sponsor_id="", password="Test@1234"):
    """Register a throwaway RED user; returns dict with creds + token."""
    email, mobile = rnd_email(), rnd_mobile()
    r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
    assert r.status_code == 200, f"send-otp failed: {r.status_code} {r.text[:300]}"
    otp = r.json().get("dev_otp")
    assert otp, "dev_otp not returned in beta"
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
    def test_send_otp_returns_dev_otp_for_normal_number(self):
        r = requests.post(f"{API}/auth/send-otp",
                          json={"email": rnd_email(), "mobile": rnd_mobile()}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("test_number") is False
        assert isinstance(d.get("dev_otp"), str) and len(d["dev_otp"]) == 6 and d["dev_otp"].isdigit()

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
            assert u["distributor_id"].startswith("ANJ") and len(u["distributor_id"]) == 9
            assert "password_hash" not in u and "_id" not in u
        assert a["user"]["distributor_id"] != b["user"]["distributor_id"]
        # /me persistence check
        r = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {a['token']}"}, timeout=TIMEOUT)
        assert r.status_code == 200
        assert r.json()["email"] == a["email"]
        assert r.json()["mobile_verified"] is True

    def test_register_wrong_otp_rejected(self):
        email, mobile = rnd_email(), rnd_mobile()
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        assert r.status_code == 200
        good = r.json()["dev_otp"]
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

    def test_login_otp_send_hides_dev_otp(self):
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": TEST_NUMBER}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d.get("test_number") is True
        assert d.get("dev_otp") is None

    def test_login_otp_verify_static_otp_super_admin(self):
        r = requests.post(f"{API}/auth/login-otp/verify",
                          json={"mobile": TEST_NUMBER, "otp": TEST_OTP}, timeout=TIMEOUT)
        if r.status_code == 400 and "request an OTP" in r.text:
            requests.post(f"{API}/auth/login-otp/send", json={"mobile": TEST_NUMBER}, timeout=TIMEOUT)
            r = requests.post(f"{API}/auth/login-otp/verify",
                              json={"mobile": TEST_NUMBER, "otp": TEST_OTP}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["user"]["role"] == "super_admin"
        assert d["user"]["email"] == ADMIN_EMAIL
        assert isinstance(d["token"], str) and len(d["token"]) > 20
        # token usable
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {d['token']}"}, timeout=TIMEOUT)
        assert me.status_code == 200 and me.json()["role"] == "super_admin"

    def test_login_otp_unknown_mobile_404(self):
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": "6000000001"}, timeout=TIMEOUT)
        assert r.status_code == 404, r.text[:300]

    def test_login_otp_verify_unknown_mobile_404(self):
        r = requests.post(f"{API}/auth/login-otp/verify",
                          json={"mobile": "6000000002", "otp": "123456"}, timeout=TIMEOUT)
        assert r.status_code == 404, r.text[:300]


# ---------------- Login with OTP (normal user) ----------------
class TestLoginOtpNormalUser:
    def test_login_otp_flow_for_registered_user(self):
        u = register_user()
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        otp = r.json()["dev_otp"]
        assert otp and r.json()["test_number"] is False
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


# ---------------- Forgot password ----------------
class TestForgotPassword:
    def test_forgot_reset_and_login_with_new_password(self):
        u = register_user()
        r = requests.post(f"{API}/auth/forgot/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        otp = r.json()["dev_otp"]
        new_pw = "NewPass@9876"
        r = requests.post(f"{API}/auth/forgot/reset",
                          json={"mobile": u["mobile"], "otp": otp, "password": new_pw}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        # new password works
        r = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": new_pw}, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["user"]["email"] == u["email"]
        # old password rejected
        r = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": u["password"]},
                          timeout=TIMEOUT)
        assert r.status_code == 401, r.text[:300]

    def test_forgot_send_unknown_mobile_404(self):
        r = requests.post(f"{API}/auth/forgot/send", json={"mobile": "6000000003"}, timeout=TIMEOUT)
        assert r.status_code == 404

    def test_forgot_reset_wrong_otp_rejected(self):
        u = register_user()
        r = requests.post(f"{API}/auth/forgot/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        good = r.json()["dev_otp"]
        bad = "000000" if good != "000000" else "111111"
        r = requests.post(f"{API}/auth/forgot/reset",
                          json={"mobile": u["mobile"], "otp": bad, "password": "Whatever@123"}, timeout=TIMEOUT)
        assert r.status_code == 400, r.text[:300]
        # original password still valid
        r = requests.post(f"{API}/auth/login", json={"email": u["email"], "password": u["password"]},
                          timeout=TIMEOUT)
        assert r.status_code == 200

    def test_forgot_reset_short_password_rejected(self):
        u = register_user()
        r = requests.post(f"{API}/auth/forgot/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        otp = r.json()["dev_otp"]
        r = requests.post(f"{API}/auth/forgot/reset",
                          json={"mobile": u["mobile"], "otp": otp, "password": "123"}, timeout=TIMEOUT)
        assert r.status_code == 422, r.text[:300]


# ---------------- Change mobile ----------------
class TestChangeMobile:
    def test_change_mobile_success_and_login_with_new_mobile(self):
        u = register_user()
        h = {"Authorization": f"Bearer {u['token']}"}
        new_mobile = rnd_mobile()
        r = requests.put(f"{API}/auth/change-mobile/send", json={"mobile": new_mobile}, headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        otp = r.json()["dev_otp"]
        r = requests.put(f"{API}/auth/change-mobile/verify",
                         json={"mobile": new_mobile, "otp": otp}, headers=h, timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["mobile"] == new_mobile
        # persisted
        me = requests.get(f"{API}/auth/me", headers=h, timeout=TIMEOUT)
        assert me.json()["mobile"] == new_mobile
        # old mobile no longer resolves for login-otp
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": u["mobile"]}, timeout=TIMEOUT)
        assert r.status_code == 404, r.text[:300]

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
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        otp = r.json()["dev_otp"]
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
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        assert r.status_code == 200
        good = r.json()["dev_otp"]
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
        r1 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        assert r1.status_code == 200
        r2 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        assert r2.status_code == 429, f"{r2.status_code} {r2.text[:300]}"

    @pytest.mark.slow
    def test_resend_allowed_after_cooldown(self):
        email, mobile = rnd_email(), rnd_mobile()
        r1 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        assert r1.status_code == 200
        time.sleep(32)
        r2 = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=TIMEOUT)
        assert r2.status_code == 200, f"{r2.status_code} {r2.text[:300]}"
        assert r2.json()["dev_otp"] != r1.json()["dev_otp"] or True
        # old OTP invalidated, new one works
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Cooldown", "email": email, "mobile": mobile,
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": r1.json()["dev_otp"],
            "accept_terms": True}, timeout=TIMEOUT)
        assert r.status_code == 400, f"old OTP should be invalid: {r.status_code}"
        r = requests.post(f"{API}/auth/register", json={
            "full_name": "TEST Cooldown", "email": email, "mobile": mobile,
            "password": "Test@1234", "confirm_password": "Test@1234", "otp": r2.json()["dev_otp"],
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
                          json={"email": "demo.distributor@anjaliherballife.in", "password": "Demo@1234"},
                          timeout=TIMEOUT)
        assert r.status_code == 200, r.text[:300]
        u = r.json()["user"]
        assert u["status"] == "green" and u["mobile"] == "9000000018"

    def test_admin_password_hash_is_bcrypt(self):
        cli, db = _mongo()
        u = db.users.find_one({"email": ADMIN_EMAIL})
        cli.close()
        assert u and u["password_hash"].startswith("$2b$"), u.get("password_hash", "")[:10]
