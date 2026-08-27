"""Iteration 11 retest: FIX 1 - multiple EMAIL-LESS registration approvals must all succeed (no 500).

Also emits credentials of an email-less approved distributor to /app/test_reports/it11_creds.json
for the Playwright login test (FIX 2).
"""
import json
import os
import secrets
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


def rand_mobile():
    return "9" + "".join(secrets.choice("0123456789") for _ in range(9))


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin(client):
    r = client.post(f"{API}/auth/admin-login",
                    json={"username": "admin", "password": "admin123", "passcode": "admin123"})
    if r.status_code != 200:
        pytest.fail(f"admin-login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("token")
    assert tok
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    return s


class TestMultipleEmaillessApprovals:
    """FIX 1"""

    def test_three_emailless_approvals(self, client, admin):
        created = []
        for i in range(3):
            mob = rand_mobile()
            r = client.post(f"{API}/auth/register-request",
                            json={"full_name": f"TEST_NoEmail{i}", "mobile": mob,
                                  "password": PW, "confirm_password": PW, "email": ""})
            assert r.status_code == 200, r.text
            rows = admin.get(f"{API}/admin/registration-requests").json()
            req = [x for x in rows if x["mobile"] == mob]
            assert len(req) == 1
            assert req[0]["email"] is None
            ap = admin.post(f"{API}/admin/registration-requests/{req[0]['id']}/approve")
            assert ap.status_code == 200, f"#{i} approve -> {ap.status_code}: {ap.text[:300]}"
            body = ap.json()
            did = body.get("distributor_id")
            assert did and did.startswith("ANJ") and len(did) == 9, body
            created.append({"mobile": mob, "did": did})

        dids = [c["did"] for c in created]
        assert len(set(dids)) == 3, f"duplicate distributor ids: {dids}"

        # verify each user: RED rank, active, login by DID and by mobile
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

            for ident in (c["did"], c["mobile"]):
                lr = client.post(f"{API}/auth/login", json={"email": ident, "password": PW})
                assert lr.status_code == 200, f"login {ident} -> {lr.status_code}: {lr.text[:200]}"
                assert lr.json().get("token")

        out = Path("/app/test_reports/it11_creds.json")
        out.write_text(json.dumps({"password": PW, "emailless": created}, indent=2))
        print("EMAILLESS_CREDS", json.dumps(created))

    def test_emailless_then_email_user_both_work(self, client, admin):
        """Regression: email-based registration + approval + email login still works."""
        mob = rand_mobile()
        em = f"test_{mob}@example.test"
        r = client.post(f"{API}/auth/register-request",
                        json={"full_name": "TEST_WithEmail", "mobile": mob,
                              "password": PW, "confirm_password": PW, "email": em})
        assert r.status_code == 200, r.text
        rows = admin.get(f"{API}/admin/registration-requests").json()
        req = [x for x in rows if x["mobile"] == mob][0]
        ap = admin.post(f"{API}/admin/registration-requests/{req['id']}/approve")
        assert ap.status_code == 200, ap.text
        lr = client.post(f"{API}/auth/login", json={"email": em, "password": PW})
        assert lr.status_code == 200, lr.text
        assert lr.json()["user"]["email"] == em
        creds_path = Path("/app/test_reports/it11_creds.json")
        data = json.loads(creds_path.read_text()) if creds_path.exists() else {"password": PW}
        data["email_user"] = {"email": em, "mobile": mob, "did": ap.json()["distributor_id"]}
        creds_path.write_text(json.dumps(data, indent=2))
        print("EMAIL_CREDS", em)

    def test_duplicate_email_still_blocked(self, client, admin):
        """Partial unique index must still enforce uniqueness for real string emails."""
        creds_path = Path("/app/test_reports/it11_creds.json")
        data = json.loads(creds_path.read_text())
        existing = data["email_user"]["email"]
        mob = rand_mobile()
        r = client.post(f"{API}/auth/register-request",
                        json={"full_name": "TEST_DupEmail", "mobile": mob,
                              "password": PW, "confirm_password": PW, "email": existing})
        if r.status_code == 200:
            rows = admin.get(f"{API}/admin/registration-requests").json()
            req = [x for x in rows if x["mobile"] == mob][0]
            ap = admin.post(f"{API}/admin/registration-requests/{req['id']}/approve")
            assert ap.status_code in (400, 409), (
                f"duplicate email approve returned {ap.status_code} (expected 400/409): {ap.text[:200]}")
        else:
            assert r.status_code in (400, 409), r.status_code
