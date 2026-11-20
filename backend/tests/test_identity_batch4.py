"""Batch 4 — identity and authentication: SEC-05 (server-verified Google sign-up, mobile code at sign-up when SMS works, no
Google pre-hijack), SEC-10 (admin lockout cannot be triggered from elsewhere), SEC-11 (admins only through the admin login),
SEC-12 (logout revokes the token), SEC-16 (suspended / revoked vendor staff lose their login).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_identity_batch4.py -n 0`).
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_identity_batch4_test", "JWT_SECRET": "batch4-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "SMS_TEST_ADAPTER": "true"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import auth_routes  # noqa: E402
import providers  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
PW = "Strong-Pass-123!"


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(key, mobile, role, did, **extra):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": f"{did.lower()}@example.com",
                     "username": did.lower(), "password_hash": hash_password(PW), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso(), **extra}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("super", "9100004001", "super_admin", "B4SUPER")
            await user("member", "9100004002", "distributor", "B4MEMBER")
            await user("owner", "9100004003", "vendor", "B4OWNER")
            await user("staff", "9100004004", "vendor_staff", "B4STAFF")
            S["v"] = {"id": new_id(), "user_id": S["owner"]["id"], "vendor_code": "B4OWNER", "business_name": "Vendor B4",
                      "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
            S["m"] = {"id": new_id(), "vendor_id": S["v"]["id"], "user_id": S["staff"]["id"], "mobile": S["staff"]["mobile"],
                      "full_name": "Staff", "role": "order_manager", "permissions": ["orders.read"], "status": "active",
                      "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendor_members.insert_one(dict(S["m"]))
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _code(c, mobile):
    rec = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": mobile}, {"_id": 0}, sort=[("created_at", -1)]))
    return rec and rec["code"]


REG = {"full_name": "New Member", "password": "Member-Pass-12", "confirm_password": "Member-Pass-12", "state": "MH", "city": "Pune",
       "pincode": "411001", "address": "1 Road"}


def _google(monkeypatch, email):
    async def identity(_sid):
        return {"email": email, "name": "G User"}
    monkeypatch.setattr(auth_routes, "_google_identity", identity)


# ================================================================ SEC-05: sign-up
def test_signup_needs_the_mobile_code_when_sms_works(c):
    body = {**REG, "mobile": "9300004001", "email": "new1@example.com"}
    assert c.post("/api/auth/register-request", json=body).status_code == 400
    assert c.post("/api/auth/register-request", json={**body, "otp": "000000"}).status_code == 400
    assert c.post("/api/auth/register-request/send-otp", json={"mobile": "9300004001"}).status_code == 200
    r = c.post("/api/auth/register-request", json={**body, "otp": _code(c, "9300004001")})
    assert r.status_code == 200, r.text
    u = _run(c, lambda: db.users.find_one({"mobile": "9300004001"}))
    assert u["mobile_verified"] is True and u["email_verified"] is False
    assert c.post("/api/auth/register-request/send-otp", json={"mobile": "9300004001"}).status_code == 400   # already registered


def test_without_sms_the_existing_signup_still_works(c, monkeypatch):
    monkeypatch.setattr(providers, "sms_available", lambda: False)
    r = c.post("/api/auth/register-request", json={**REG, "mobile": "9300004002", "email": "new2@example.com"})
    assert r.status_code == 200, r.text
    assert _run(c, lambda: db.users.find_one({"mobile": "9300004002"}))["mobile_verified"] is False
    assert c.get("/api/settings/public").json()["sms_otp_available"] is False


def test_google_signup_flag_alone_is_not_trusted(c, monkeypatch):
    monkeypatch.setattr(providers, "sms_available", lambda: False)
    base = {**REG, "mobile": "9300004003", "email": "g.user@example.com", "google_verified": True}
    assert c.post("/api/auth/register-request", json=base).status_code == 400                         # flag without proof
    import jwt
    forged = jwt.encode({"type": "google_signup", "email": "g.user@example.com"}, "not-the-server-secret", algorithm="HS256")
    assert c.post("/api/auth/register-request", json={**base, "google_signup_token": forged}).status_code == 400
    _google(monkeypatch, "other@example.com")
    other_tok = c.post("/api/auth/google/session", json={"session_id": "s"}).json()["google_signup_token"]
    assert c.post("/api/auth/register-request", json={**base, "google_signup_token": other_tok}).status_code == 400   # wrong email
    _google(monkeypatch, "g.user@example.com")
    g = c.post("/api/auth/google/session", json={"session_id": "s"}).json()
    assert g["mode"] == "register" and g["google_signup_token"]
    r = c.post("/api/auth/register-request", json={**base, "google_signup_token": g["google_signup_token"]})
    assert r.status_code == 200, r.text
    u = _run(c, lambda: db.users.find_one({"email": "g.user@example.com"}))
    assert u["email_verified"] is True and u["google_linked"] is True


def test_google_cannot_take_over_an_account_registered_with_someone_elses_email(c, monkeypatch):
    monkeypatch.setattr(providers, "sms_available", lambda: False)
    # an attacker registers first with the victim's email and their own password
    assert c.post("/api/auth/register-request", json={**REG, "mobile": "9300004004", "email": "victim@example.com"}).status_code == 200
    _google(monkeypatch, "victim@example.com")
    r = c.post("/api/auth/google/session", json={"session_id": "s"})
    assert r.status_code == 409 and "token" not in r.text                                           # the victim is not logged into it


# ================================================================ SEC-11: admins use the admin login only
def test_admins_cannot_use_the_member_login_or_google(c, monkeypatch):
    assert c.post("/api/auth/login", json={"email": S["super"]["mobile"], "password": PW}).status_code == 403
    _run(c, lambda: db.users.update_one({"id": S["super"]["id"]}, {"$set": {"email_verified": True}}))
    _google(monkeypatch, S["super"]["email"])
    assert c.post("/api/auth/google/session", json={"session_id": "s"}).status_code == 403
    assert c.post("/api/auth/admin-login", json={"username": "b4super", "password": PW}).status_code == 200
    assert c.post("/api/auth/login", json={"email": S["member"]["mobile"], "password": PW}).status_code == 200


# ================================================================ SEC-10: lockout cannot be triggered from elsewhere
def test_failed_admin_logins_from_one_place_do_not_lock_the_admin_out_elsewhere(c):
    bad = {"X-Forwarded-For": "203.0.113.9"}
    for _ in range(6):
        c.post("/api/auth/admin-login", json={"username": "b4super", "password": "wrong-guess"}, headers=bad)
    assert c.post("/api/auth/admin-login", json={"username": "b4super", "password": PW}, headers=bad).status_code in (401, 423, 429)
    good = c.post("/api/auth/admin-login", json={"username": "b4super", "password": PW}, headers={"X-Forwarded-For": "198.51.100.7"})
    assert good.status_code == 200, good.text


# ================================================================ SEC-12: logout revokes the token
def test_logout_revokes_only_that_session(c):
    t1 = c.post("/api/auth/login", json={"email": S["member"]["mobile"], "password": PW}).json()["token"]
    t2 = c.post("/api/auth/login", json={"email": S["member"]["mobile"], "password": PW}).json()["token"]
    h1, h2 = {"Authorization": f"Bearer {t1}"}, {"Authorization": f"Bearer {t2}"}
    assert c.post("/api/auth/logout", headers=h1).status_code == 200
    assert c.get("/api/auth/me", headers=h1).status_code == 401
    assert c.get("/api/auth/me", headers=h2).status_code == 200
    rec = _run(c, lambda: db.revoked_tokens.find_one({"user_id": S["member"]["id"]}))
    assert rec and rec["expires_at"]


# ================================================================ SEC-16: staff lose their login with their membership
def test_suspended_and_revoked_staff_lose_every_session(c):
    tok = c.post("/api/auth/login", json={"email": S["staff"]["mobile"], "password": PW}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert c.get("/api/auth/me", headers=h).status_code == 200
    assert c.post(f"/api/vendor/staff/{S['m']['id']}/suspend", headers=_hdr("owner")).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401
    assert c.get("/api/dashboard", headers=h).status_code == 401                                   # the /app side too
    assert c.post("/api/auth/login", json={"email": S["staff"]["mobile"], "password": PW}).status_code in (401, 403)
    assert c.post(f"/api/vendor/staff/{S['m']['id']}/reactivate", headers=_hdr("owner")).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 200
    assert c.delete(f"/api/vendor/staff/{S['m']['id']}", headers=_hdr("owner")).status_code == 200      # revoke
    assert c.get("/api/auth/me", headers=h).status_code == 401
    assert _run(c, lambda: db.users.find_one({"id": S["staff"]["id"]}))["account_status"] == "suspended"
    assert _run(c, lambda: db.users.find_one({"id": S["owner"]["id"]}))["account_status"] == "active"   # never other roles


# ================================================================ VEN-01 (Batch 9): invitation emails carry an absolute link
def test_owner_invitation_link_is_absolute(monkeypatch):
    import vendor_invitations
    monkeypatch.setenv("FRONTEND_PUBLIC_URL", "https://shop.example.com/")
    assert vendor_invitations.frontend_origin() == "https://shop.example.com"
    monkeypatch.delenv("FRONTEND_PUBLIC_URL")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000,https://home-genie-9zfc.vercel.app")
    assert vendor_invitations.frontend_origin() == "https://home-genie-9zfc.vercel.app"
