"""Password recovery with Google: a Google-verified e-mail proves the account, then a single-use token (15 minutes)
sets the new password. The managed Google check is replaced by a stub, so no network is needed.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_forgot_google.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_forgot_google_test", "JWT_SECRET": "forgot-google-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import auth_routes  # noqa: E402
import core  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Old-Pass-1234"
NEW_PW = "Brand-New-5678"
GOOGLE = {}          # session_id -> identity the stubbed Google check returns
S = {}


async def _stub_identity(session_id):
    if not (session_id or "").strip():   # mirrors the real helper's validation
        raise HTTPException(status_code=400, detail="Missing session. Please try signing in again.")
    if session_id == "outage":
        raise HTTPException(status_code=503, detail="Could not verify Google sign-in right now. Please try again.")
    if session_id not in GOOGLE:
        raise HTTPException(status_code=401, detail="Google sign-in could not be verified. Please try again.")
    return {"email": GOOGLE[session_id], "name": "Test"}


@pytest.fixture(scope="module")
def c(monkeypatch_module):
    monkeypatch_module.setattr(auth_routes, "_google_identity", _stub_identity)
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            members = (("member", "9100008001", "member@example.com", "distributor"),
                       ("blocked", "9100008002", "blocked@example.com", "distributor"),
                       ("admin", "9100008003", "admin@example.com", "super_admin"))
            for key, mobile, email, role in members:
                S[key] = {"id": new_id(), "distributor_id": key.upper() + "1", "full_name": key, "mobile": mobile,
                          "email": email, "password_hash": hash_password(PW), "role": role, "status": "green",
                          "account_status": "active", "blocked": key == "blocked",
                          "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(S[key]))
        client.portal.call(seed)
        core.RATE_LIMITS["forgot_password"] = (1000, 3600)
        core.RATE_LIMITS["forgot_reset"] = (1000, 3600)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


@pytest.fixture(scope="module")
def monkeypatch_module():
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


def _run(c, fn):
    return c.portal.call(fn)


def _request(c, email, session=None):
    sid = session or f"sid-{os.urandom(4).hex()}"
    GOOGLE[sid] = email
    return c.post("/api/auth/forgot/google", json={"session_id": sid})


def _reset(c, token, password=NEW_PW):
    return c.post("/api/auth/forgot/google/reset", json={"token": token, "password": password})


def _login(c, email, password):
    return c.post("/api/auth/login", json={"email": email, "password": password})


def test_google_verified_member_gets_a_token_and_can_set_a_new_password(c):
    r = _request(c, "member@example.com")
    assert r.status_code == 200, r.text
    token = r.json()["reset_token"]
    assert len(token) > 30
    assert _reset(c, token).status_code == 200
    assert _login(c, "member@example.com", NEW_PW).status_code == 200      # new password works
    assert _login(c, "member@example.com", PW).status_code == 401          # old password refused


def test_the_token_works_once(c):
    token = _request(c, "member@example.com").json()["reset_token"]
    assert _reset(c, token).status_code == 200
    again = _reset(c, token)
    assert again.status_code == 400 and "invalid or has expired" in again.json()["detail"]


def test_a_newer_request_invalidates_the_older_token(c):
    first = _request(c, "member@example.com").json()["reset_token"]
    second = _request(c, "member@example.com").json()["reset_token"]
    assert _reset(c, first).status_code == 400
    assert _reset(c, second).status_code == 200


def test_an_expired_token_is_refused(c):
    token = _request(c, "member@example.com").json()["reset_token"]
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    _run(c, lambda: db.password_reset_tokens.update_many({"used": False}, {"$set": {"expires_at": past}}))
    assert _reset(c, token).status_code == 400
    assert _login(c, "member@example.com", NEW_PW).status_code == 200          # the refused token changed nothing


def test_unknown_blocked_and_admin_accounts_get_the_same_answer_and_no_token(c):
    known_message = _request(c, "member@example.com").json()["message"]
    for email in ("nobody@example.com", "blocked@example.com", "admin@example.com"):
        other = _request(c, email)
        assert other.status_code == 200
        assert other.json() == {"message": known_message}                     # identical body, no token


def test_admin_password_cannot_be_reset_this_way(c):
    admin_hash_before = _run(c, lambda: db.users.find_one({"id": S["admin"]["id"]}))["password_hash"]
    assert _request(c, "admin@example.com").status_code == 200
    assert _run(c, lambda: db.password_reset_tokens.find_one({"user_id": S["admin"]["id"]})) is None
    assert _run(c, lambda: db.users.find_one({"id": S["admin"]["id"]}))["password_hash"] == admin_hash_before


def test_an_invalid_or_missing_google_session_is_refused(c):
    assert c.post("/api/auth/forgot/google", json={"session_id": "not-issued"}).status_code == 401
    assert c.post("/api/auth/forgot/google", json={"session_id": "  "}).status_code == 400


def test_google_outage_fails_safely_with_503(c):
    r = c.post("/api/auth/forgot/google", json={"session_id": "outage"})
    assert r.status_code == 503
    assert "reset_token" not in r.text


def test_weak_new_password_is_refused_and_the_token_survives(c):
    token = _request(c, "member@example.com").json()["reset_token"]
    assert _reset(c, token, password="short").status_code == 400
    assert _reset(c, token).status_code == 200


def test_a_reset_signs_out_sessions_issued_before_it(c):
    old = _login(c, "member@example.com", NEW_PW).json()["token"]
    h = {"Authorization": f"Bearer {old}"}
    assert c.get("/api/auth/me", headers=h).status_code == 200
    token = _request(c, "member@example.com").json()["reset_token"]
    assert _reset(c, token, password="Third-Pass-9999").status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_the_token_is_stored_only_as_a_hash(c):
    token = _request(c, "member@example.com").json()["reset_token"]
    stored = _run(c, lambda: db.password_reset_tokens.find({}, {"_id": 0}).to_list(500))
    assert stored and all(token not in str(row) for row in stored)
    assert all(len(row["token_hash"]) == 64 for row in stored)


def test_no_token_is_ever_written_to_the_audit_log(c):
    token = _request(c, "member@example.com").json()["reset_token"]
    _reset(c, token)
    audit = _run(c, lambda: db.audit_logs.find({}, {"_id": 0}).to_list(1000))
    assert audit and all(token not in str(row) for row in audit)
