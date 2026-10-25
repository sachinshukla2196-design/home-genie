"""Registration without admin approval: several EMAIL-LESS registrations all succeed and log in immediately, an
e-mail registration works, and a duplicate e-mail is refused. Writes the created test credentials to
TEST_REPORTS_DIR (or the temp dir) for the browser login test.

Live suite: needs REACT_APP_BACKEND_URL (or frontend env) and TEST_ADMIN_USER / TEST_ADMIN_PASSWORD.
Run it on its own: `pytest tests/test_it11_emailless.py -n 0`.
"""
import json
import os
import secrets
import tempfile
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
base_url = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not base_url:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = base_url.rstrip("/")
API = f"{BASE_URL}/api"
PW = "Test@1234"
CREDS_PATH = Path(os.environ.get("TEST_REPORTS_DIR") or tempfile.gettempdir()) / "it11_creds.json"


def rand_mobile():
    return "9" + "".join(secrets.choice("0123456789") for _ in range(9))


def register(client, mobile, full_name, email=""):
    return client.post(f"{API}/auth/register-request",
                       json={"full_name": full_name, "mobile": mobile, "password": PW, "confirm_password": PW,
                             "state": "Rajasthan", "city": "Jaipur", "pincode": "302001", "address": "1 Test Road",
                             "email": email})


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin(client):
    r = client.post(f"{API}/auth/admin-login",
                    json={"username": os.environ["TEST_ADMIN_USER"], "password": os.environ["TEST_ADMIN_PASSWORD"],
                          "passcode": os.environ.get("TEST_ADMIN_PASSCODE", "")})
    if r.status_code != 200:
        pytest.fail(f"admin-login failed {r.status_code}: {r.text[:300]}")
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {r.json()['token']}"})
    return s


class TestEmaillessRegistrations:
    def test_three_emailless_registrations_activate_and_log_in(self, client, admin):
        created = []
        for i in range(3):
            mob = rand_mobile()
            r = register(client, mob, f"TEST_NoEmail{i}")
            assert r.status_code == 200, r.text
            rows = admin.get(f"{API}/admin/registration-requests").json()
            req = [x for x in rows if x["mobile"] == mob]
            assert len(req) == 1 and req[0]["email"] is None
            lr = client.post(f"{API}/auth/login", json={"email": mob, "password": PW})
            assert lr.status_code == 200, f"#{i} login -> {lr.status_code}: {lr.text[:200]}"
            created.append({"mobile": mob, "did": lr.json()["user"]["distributor_id"]})

        dids = [c["did"] for c in created]
        assert len(set(dids)) == 3, f"duplicate distributor ids: {dids}"
        assert all(d.startswith("HG") and len(d) == 8 for d in dids), dids

        users = admin.get(f"{API}/admin/users").json()
        if isinstance(users, dict):
            users = users.get("users", users.get("items", []))
        by_did = {u.get("distributor_id"): u for u in users}
        for c in created:
            u = by_did.get(c["did"])
            assert u, f"user {c['did']} not found in /api/admin/users"
            assert str(u.get("status", "")).lower() == "red", u.get("status")
            assert u.get("account_status") == "active", u.get("account_status")
            assert u.get("email") in (None, ""), u.get("email")
            assert "_id" not in u
            assert client.post(f"{API}/auth/login", json={"email": c["did"], "password": PW}).status_code == 200

        CREDS_PATH.write_text(json.dumps({"password": PW, "emailless": created}, indent=2))

    def test_email_registration_logs_in_by_email(self, client, admin):
        mob = rand_mobile()
        em = f"test_{mob}@example.com"
        assert register(client, mob, "TEST_WithEmail", em).status_code == 200
        lr = client.post(f"{API}/auth/login", json={"email": em, "password": PW})
        assert lr.status_code == 200, lr.text
        assert lr.json()["user"]["email"] == em
        data = json.loads(CREDS_PATH.read_text()) if CREDS_PATH.exists() else {"password": PW}
        data["email_user"] = {"email": em, "mobile": mob, "did": lr.json()["user"]["distributor_id"]}
        CREDS_PATH.write_text(json.dumps(data, indent=2))

    def test_duplicate_email_is_refused_at_registration(self, client, admin):
        """The e-mail is still unique: a second registration with the same address creates nothing."""
        existing = json.loads(CREDS_PATH.read_text())["email_user"]["email"]
        mob = rand_mobile()
        r = register(client, mob, "TEST_DupEmail", existing)
        assert r.status_code == 400, r.text
        assert client.post(f"{API}/auth/login", json={"email": mob, "password": PW}).status_code == 401
