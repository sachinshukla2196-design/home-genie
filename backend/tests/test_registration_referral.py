"""Phase 14: one registration rule across /send-otp, /register and /register-request.

The referral ID is OPTIONAL. A blank referral creates no sponsor link and no default sponsor. A given referral must
be an active admin code or an active member, and is attributed exactly once when the account is created. OTPs are
delivered only through the TEST adapter (SMS_TEST_ADAPTER=true on a *_test database) and are never in a response.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_registration_referral.py -n 0`.
"""
import os

import pytest

DB = "homegenies_registration_test"
os.environ.update({"VERCEL": "1", "DB_NAME": DB, "JWT_SECRET": "registration-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "SMS_TEST_ADAPTER": "true"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import core  # noqa: E402
import providers  # noqa: E402
from core import db, hash_password, now_iso, new_id  # noqa: E402

PW = "Reg-Pass-12345"
GREEN_ID = "REGGRN01"
RED_ID = "REGRED01"
CODE = "REGCODE1"
REG = {"full_name": "Regional Customer", "password": PW, "confirm_password": PW, "address": "1 Test Road",
       "state": "Delhi", "city": "New Delhi", "pincode": "110001", "accept_terms": True}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(DB)
            await server._init_db()
            admin = {"id": new_id(), "distributor_id": "REGADM01", "full_name": "Admin", "email": "reg-admin@example.com",
                     "mobile": "9100007001", "password_hash": hash_password(PW), "role": "super_admin", "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
            green = {**admin, "id": new_id(), "distributor_id": GREEN_ID, "full_name": "Green", "email": None,
                     "mobile": "9100007002", "role": "distributor"}
            red = {**green, "id": new_id(), "distributor_id": RED_ID, "mobile": "9100007003", "status": "red"}
            await db.users.insert_many([dict(admin), dict(green), dict(red)])
            await db.referral_codes.insert_one({"id": new_id(), "code": CODE, "label": "Campaign", "active": True,
                                                "uses": 0, "created_by": admin["id"], "created_at": now_iso()})
        client.portal.call(seed)
        core.RATE_LIMITS["customer_register"] = (1000, 3600)
        yield client
        client.portal.call(lambda: server.client.drop_database(DB))


def _run(c, fn):
    return c.portal.call(fn)


def _user(c, mobile):
    return _run(c, lambda: db.users.find_one({"mobile": mobile}, {"_id": 0}))


def _code_uses(c):
    return _run(c, lambda: db.referral_codes.find_one({"code": CODE}))["uses"]


def _otp_for(c, mobile):
    row = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": mobile}, sort=[("created_at", -1)]))
    assert row, "the test SMS adapter recorded no code"
    return row["code"]


def _reg_request(c, mobile, sponsor_id="", email=""):
    return c.post("/api/auth/register-request", json={**REG, "mobile": mobile, "email": email, "sponsor_id": sponsor_id})


def _send_otp(c, mobile, sponsor_id="", email=""):
    return c.post("/api/auth/send-otp", json={"email": email or f"{mobile}@example.com", "mobile": mobile, "sponsor_id": sponsor_id})


def _register(c, mobile, otp, sponsor_id="", email=""):
    return c.post("/api/auth/register", json={**REG, "mobile": mobile, "email": email or f"{mobile}@example.com",
                                              "otp": otp, "sponsor_id": sponsor_id})


# ---------------------------------------------------------------- /register-request (no OTP)
def test_request_without_referral_creates_an_active_account_with_no_sponsor(c):
    r = _reg_request(c, "9100007101")
    assert r.status_code == 200, r.text
    user = _user(c, "9100007101")
    assert user and user["role"] == "distributor" and user["sponsor_id"] is None and user["sponsor_user_id"] is None
    assert _run(c, lambda: db.referral_relationships.find_one({"referred_user_id": user["id"]})) is None
    login = c.post("/api/auth/login", json={"email": "9100007101", "password": PW})
    assert login.status_code == 200 and login.json().get("token")          # immediate login, no admin approval


def test_request_with_valid_member_referral_attributes_the_sponsor(c):
    r = _reg_request(c, "9100007102", sponsor_id=GREEN_ID.lower())
    assert r.status_code == 200, r.text
    user = _user(c, "9100007102")
    assert user["sponsor_id"] == GREEN_ID
    sponsor = _run(c, lambda: db.users.find_one({"distributor_id": GREEN_ID}))
    assert user["sponsor_user_id"] == sponsor["id"]
    assert _run(c, lambda: db.referral_relationships.find_one({"referred_user_id": user["id"], "sponsor_id": sponsor["id"]}))


def test_request_with_valid_admin_code_counts_one_use(c):
    before = _code_uses(c)
    assert _reg_request(c, "9100007103", sponsor_id=CODE).status_code == 200
    assert _code_uses(c) == before + 1
    assert _user(c, "9100007103")["sponsor_id"] == CODE


def test_request_with_unknown_referral_is_refused_and_creates_nothing(c):
    r = _reg_request(c, "9100007104", sponsor_id="NOSUCH99")
    assert r.status_code == 400 and "Invalid referral" in r.json()["detail"]
    assert _user(c, "9100007104") is None
    assert _run(c, lambda: db.registration_requests.find_one({"mobile": "9100007104"})) is None


def test_request_with_inactive_member_referral_is_refused(c):
    r = _reg_request(c, "9100007105", sponsor_id=RED_ID)
    assert r.status_code == 400 and "inactive member" in r.json()["detail"]
    assert _user(c, "9100007105") is None


def test_request_duplicate_mobile_and_email_are_refused(c):
    assert _reg_request(c, "9100007101").status_code == 400                                   # same mobile as above
    assert _reg_request(c, "9100007106", email="reg-dup@example.com").status_code == 200
    assert _reg_request(c, "9100007107", email="reg-dup@example.com").status_code == 400    # same email


# ---------------------------------------------------------------- /send-otp
def test_send_otp_without_referral_sends_by_sms_and_returns_no_code(c):
    r = _send_otp(c, "9100007201")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"message": "OTP sent to your mobile."}
    assert len(_otp_for(c, "9100007201")) == 6


def test_send_otp_checks_referral_but_never_counts_it(c):
    before = _code_uses(c)
    assert _send_otp(c, "9100007202", sponsor_id=CODE).status_code == 200
    assert _code_uses(c) == before                                                            # no double counting at send time


def test_send_otp_with_invalid_referral_sends_nothing(c):
    r = _send_otp(c, "9100007203", sponsor_id="NOSUCH99")
    assert r.status_code == 400
    assert _run(c, lambda: db.test_sms_outbox.find_one({"mobile": "9100007203"})) is None


# ---------------------------------------------------------------- /register (OTP)
def test_register_without_referral_has_no_sponsor_and_logs_in_immediately(c):
    assert _send_otp(c, "9100007301").status_code == 200
    r = _register(c, "9100007301", _otp_for(c, "9100007301"))
    assert r.status_code == 200, r.text
    assert r.json()["token"] and r.json()["user"]["sponsor_id"] is None
    user = _user(c, "9100007301")
    assert user["sponsor_user_id"] is None and user["role"] == "distributor" and user["status"] == "red"
    assert c.post("/api/auth/login", json={"email": "9100007301@example.com", "password": PW}).status_code == 200


def test_register_with_valid_member_referral_attributes_and_persists(c):
    assert _send_otp(c, "9100007302", sponsor_id=GREEN_ID).status_code == 200
    r = _register(c, "9100007302", _otp_for(c, "9100007302"), sponsor_id=GREEN_ID)
    assert r.status_code == 200, r.text
    user = _user(c, "9100007302")
    assert user["sponsor_id"] == GREEN_ID
    assert _run(c, lambda: db.referral_relationships.find_one({"referred_user_id": user["id"]}))


def test_register_with_valid_admin_code_counts_exactly_one_use(c):
    before = _code_uses(c)
    assert _send_otp(c, "9100007303", sponsor_id=CODE).status_code == 200
    assert _register(c, "9100007303", _otp_for(c, "9100007303"), sponsor_id=CODE).status_code == 200
    assert _code_uses(c) == before + 1


def test_register_with_invalid_referral_does_not_consume_the_otp(c):
    assert _send_otp(c, "9100007304").status_code == 200
    otp = _otp_for(c, "9100007304")
    bad = _register(c, "9100007304", otp, sponsor_id="NOSUCH99")
    assert bad.status_code == 400 and "Invalid referral" in bad.json()["detail"]
    assert _user(c, "9100007304") is None
    good = _register(c, "9100007304", otp)                                                    # same code, referral left blank
    assert good.status_code == 200, good.text
    assert _user(c, "9100007304")["sponsor_id"] is None


def test_register_with_wrong_otp_is_refused(c):
    assert _send_otp(c, "9100007305").status_code == 200
    assert _register(c, "9100007305", "000000" if _otp_for(c, "9100007305") != "000000" else "111111").status_code == 400
    assert _user(c, "9100007305") is None


def test_register_duplicate_email_and_mobile_are_refused(c):
    assert _register(c, "9100007301", "123456", email="other@example.com").status_code == 400    # mobile exists
    assert _register(c, "9100007399", "123456", email="9100007301@example.com").status_code == 400  # email exists


# ---------------------------------------------------------------- the test adapter is never active in production
def test_sms_test_adapter_needs_both_the_flag_and_a_test_database(monkeypatch):
    monkeypatch.setenv("SMS_TEST_ADAPTER", "true")
    monkeypatch.setenv("DB_NAME", "homegenies_live_test")
    assert providers._test_sms_adapter() is True
    monkeypatch.setenv("DB_NAME", "homegenies")
    assert providers._test_sms_adapter() is False
    monkeypatch.setenv("DB_NAME", "homegenies_live_test")
    monkeypatch.setenv("SMS_TEST_ADAPTER", "false")
    assert providers._test_sms_adapter() is False


def test_without_sms_configuration_otp_fails_safe_with_503(c, monkeypatch):
    monkeypatch.setenv("SMS_TEST_ADAPTER", "false")
    monkeypatch.setattr(providers, "TWILIO_ENABLED", False)
    r = _send_otp(c, "9100007401")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "OTP_SERVICE_UNAVAILABLE"
    assert _run(c, lambda: db.test_sms_outbox.find_one({"mobile": "9100007401"})) is None
