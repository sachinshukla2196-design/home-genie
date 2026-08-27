"""BETA registration-request -> admin approval -> login-by-ID workflow + product permanent delete + security.

NOTE: users.email has a NON-sparse unique index (server.py:110) so only ONE email-less user can
ever exist. Approving a 2nd request without an email -> 500 DuplicateKeyError. Documented below.
"""
import os
import secrets
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


def submit_request(client, mobile, email="", name="TEST_Applicant"):
    body = {"full_name": name, "mobile": mobile, "password": PW, "confirm_password": PW, "email": email}
    return client.post(f"{API}/auth/register-request", json=body)


def find_req(admin, mobile):
    rows = admin.get(f"{API}/admin/registration-requests").json()
    matches = [x for x in rows if x["mobile"] == mobile]
    assert len(matches) == 1, f"expected 1 request for {mobile}, got {len(matches)}"
    return matches[0]


@pytest.fixture(scope="module")
def approved_distributor(client, admin):
    """Submit + approve a request WITH email (works around the null-email unique index bug)."""
    mob = rand_mobile()
    em = f"test_{mob}@example.test"
    assert submit_request(client, mob, em, "TEST_Approved Distributor").status_code == 200
    req = find_req(admin, mob)
    ap = admin.post(f"{API}/admin/registration-requests/{req['id']}/approve")
    if ap.status_code != 200:
        pytest.fail(f"approve failed {ap.status_code}: {ap.text[:300]}")
    return {"mobile": mob, "email": em, "req_id": req["id"], "did": ap.json()["distributor_id"]}


# ---------- POST /api/auth/register-request ----------
class TestRegistrationRequest:
    def test_submit_request_creates_pending_no_user(self, client, admin):
        mob = rand_mobile()
        r = submit_request(client, mob, name="TEST_Pending Only")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "approval" in data["message"].lower()
        assert "token" not in data and "user" not in data

        req = find_req(admin, mob)
        assert req["status"] == "pending"
        assert req["email"] is None
        assert "password_hash" not in req and "_id" not in req

        # no user yet -> login must fail
        assert client.post(f"{API}/auth/login", json={"email": mob, "password": PW}).status_code == 401

    def test_duplicate_pending_rejected(self, client):
        mob = rand_mobile()
        assert submit_request(client, mob, name="TEST_Dup1").status_code == 200
        r = submit_request(client, mob, name="TEST_Dup2")
        assert r.status_code == 400, r.text
        assert "pending" in r.json()["detail"].lower()

    def test_invalid_mobile(self, client):
        r = submit_request(client, "12345")
        assert r.status_code == 400
        assert "mobile" in r.json()["detail"].lower()

    def test_password_mismatch(self, client):
        r = client.post(f"{API}/auth/register-request",
                        json={"full_name": "TEST_X", "mobile": rand_mobile(),
                              "password": PW, "confirm_password": "Other@123"})
        assert r.status_code == 400
        assert "match" in r.json()["detail"].lower()

    def test_short_password_422(self, client):
        r = client.post(f"{API}/auth/register-request",
                        json={"full_name": "TEST_S", "mobile": rand_mobile(),
                              "password": "123", "confirm_password": "123"})
        assert r.status_code == 422


# ---------- admin approve / reject + login by DID / mobile ----------
class TestApprovalAndLogin:
    def test_approved_user_is_red_active(self, client, admin, approved_distributor):
        did = approved_distributor["did"]
        assert did.startswith("ANJ") and len(did) == 9, did
        assert find_req(admin, approved_distributor["mobile"])["status"] == "approved"

        users = admin.get(f"{API}/admin/users").json()
        u = next(x for x in (users if isinstance(users, list) else users.get("items", []))
                 if x["distributor_id"] == did)
        assert u["status"] == "red"
        assert u.get("account_status") == "active"

    def test_login_by_distributor_id(self, client, approved_distributor):
        did = approved_distributor["did"]
        r = client.post(f"{API}/auth/login", json={"email": did, "password": PW})
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u["distributor_id"] == did
        assert u["status"] == "red"
        assert "password_hash" not in u and "_id" not in u
        assert r.json()["token"]
        # lowercase DID also works
        assert client.post(f"{API}/auth/login", json={"email": did.lower(), "password": PW}).status_code == 200

    def test_login_by_mobile(self, client, approved_distributor):
        r = client.post(f"{API}/auth/login", json={"email": approved_distributor["mobile"], "password": PW})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["distributor_id"] == approved_distributor["did"]

    def test_login_wrong_password(self, client, approved_distributor):
        r = client.post(f"{API}/auth/login", json={"email": approved_distributor["did"], "password": "Wrong@999"})
        assert r.status_code == 401

    def test_double_approve_rejected(self, admin, approved_distributor):
        r = admin.post(f"{API}/admin/registration-requests/{approved_distributor['req_id']}/approve")
        assert r.status_code == 400, r.text

    def test_registered_mobile_blocks_new_request(self, client, approved_distributor):
        r = submit_request(client, approved_distributor["mobile"], name="TEST_Again")
        assert r.status_code == 400
        assert "already exists" in r.json()["detail"].lower()

    def test_reject_flow(self, client, admin):
        mob = rand_mobile()
        assert submit_request(client, mob, name="TEST_Reject Me").status_code == 200
        req = find_req(admin, mob)
        assert admin.post(f"{API}/admin/registration-requests/{req['id']}/reject").status_code == 200
        assert find_req(admin, mob)["status"] == "rejected"
        assert client.post(f"{API}/auth/login", json={"email": mob, "password": PW}).status_code == 401

    def test_approve_nonexistent_404(self, admin):
        assert admin.post(f"{API}/admin/registration-requests/does-not-exist/approve").status_code == 404

    def test_emailless_approval_bug(self, client, admin):
        """BUG: users.email unique index is not sparse/partial -> only one null-email user allowed."""
        mob = rand_mobile()
        assert submit_request(client, mob, name="TEST_No Email").status_code == 200
        req = find_req(admin, mob)
        r = admin.post(f"{API}/admin/registration-requests/{req['id']}/approve")
        assert r.status_code == 200, (
            f"Email-less approval returned {r.status_code} ({r.text[:200]}) - "
            "DuplicateKeyError on users.email_1 unique index (null). "
            "Fix: partialFilterExpression {email: {$type: 'string'}} or omit null email field."
        )
        assert client.post(f"{API}/auth/login", json={"email": mob, "password": PW}).status_code == 200


# ---------- security ----------
class TestSecurity:
    def test_list_requires_admin(self, client):
        assert client.get(f"{API}/admin/registration-requests").status_code in (401, 403)

    def test_approve_reject_require_admin(self, client):
        for path in ("approve", "reject"):
            r = client.post(f"{API}/admin/registration-requests/xyz/{path}")
            assert r.status_code in (401, 403), f"{path} -> {r.status_code}"

    def test_bad_token_rejected(self, client):
        r = client.get(f"{API}/admin/registration-requests", headers={"Authorization": "Bearer bogus"})
        assert r.status_code in (401, 403)

    def test_distributor_token_cannot_access_admin(self, client, approved_distributor):
        tok = client.post(f"{API}/auth/login",
                          json={"email": approved_distributor["did"], "password": PW}).json()["token"]
        r = client.get(f"{API}/admin/registration-requests", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 403, r.status_code


# ---------- DELETE /api/admin/products/{id}/permanent (regression) ----------
class TestProductPermanentDelete:
    def test_permanent_delete(self, admin):
        payload = {"sku": f"TESTPD{secrets.randbelow(90000) + 10000}", "name": "TEST_Perm Delete Product",
                   "mrp": 299, "selling_price": 199, "stock": 5, "category": "Herbal",
                   "description": "test", "images": ["https://example.com/x.jpg"]}
        cr = admin.post(f"{API}/admin/products", json=payload)
        assert cr.status_code in (200, 201), cr.text
        pid = cr.json()["id"]
        dr = admin.delete(f"{API}/admin/products/{pid}/permanent")
        assert dr.status_code in (200, 204), dr.text
        lst = admin.get(f"{API}/admin/products").json()
        items = lst if isinstance(lst, list) else lst.get("items", [])
        assert all(p.get("id") != pid for p in items), "product still present after permanent delete"

    def test_permanent_delete_requires_admin(self, client):
        assert client.delete(f"{API}/admin/products/anything/permanent").status_code in (401, 403)

    def test_permanent_delete_missing_404(self, admin):
        assert admin.delete(f"{API}/admin/products/nope-not-real/permanent").status_code == 404
