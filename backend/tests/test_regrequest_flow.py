"""Registration request -> immediate account activation (approved design: normal customers need no admin approval),
login by HomeGenie ID or mobile, admin safeguards, security, and product permanent delete.

Live suite: needs REACT_APP_BACKEND_URL (or frontend env) and TEST_ADMIN_USER / TEST_ADMIN_PASSWORD (+ optional
TEST_ADMIN_PASSCODE, ignored by the server). Run it on its own: `pytest tests/test_regrequest_flow.py -n 0`.
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
                    json={"username": os.environ["TEST_ADMIN_USER"], "password": os.environ["TEST_ADMIN_PASSWORD"],
                          "passcode": os.environ.get("TEST_ADMIN_PASSCODE", "")})
    if r.status_code != 200:
        pytest.fail(f"admin-login failed {r.status_code}: {r.text[:300]}")
    tok = r.json().get("token")
    assert tok
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {tok}"})
    return s


def submit_request(client, mobile, email="", name="TEST_Applicant"):
    body = {"full_name": name, "mobile": mobile, "password": PW, "confirm_password": PW, "email": email,
            "state": "Rajasthan", "city": "Jaipur", "pincode": "302001", "address": "1 Test Road"}
    return client.post(f"{API}/auth/register-request", json=body)


def find_req(admin, mobile):
    rows = admin.get(f"{API}/admin/registration-requests").json()
    matches = [x for x in rows if x["mobile"] == mobile]
    assert len(matches) == 1, f"expected 1 request for {mobile}, got {len(matches)}"
    return matches[0]


def find_user(admin, did):
    users = admin.get(f"{API}/admin/users").json()
    rows = users if isinstance(users, list) else users.get("items", [])
    return next(x for x in rows if x["distributor_id"] == did)


@pytest.fixture(scope="module")
def activated(client, admin):
    """Registration with an e-mail; the account exists as soon as the request succeeds."""
    mob = rand_mobile()
    em = f"test_{mob}@example.com"
    assert submit_request(client, mob, em, "TEST_Activated Distributor").status_code == 200
    req = find_req(admin, mob)
    login = client.post(f"{API}/auth/login", json={"email": mob, "password": PW})
    assert login.status_code == 200, login.text
    did = login.json()["user"]["distributor_id"]
    return {"mobile": mob, "email": em, "req_id": req["id"], "did": did}


# ---------- POST /api/auth/register-request ----------
class TestRegistrationRequest:
    def test_registration_activates_the_account_immediately(self, client, admin):
        mob = rand_mobile()
        r = submit_request(client, mob, name="TEST_Immediate")
        assert r.status_code == 200, r.text
        data = r.json()
        assert "log in" in data["message"].lower() and "approval" not in data["message"].lower()
        assert "token" not in data and "user" not in data

        req = find_req(admin, mob)
        assert req["status"] == "approved"
        assert req["email"] is None                           # blank e-mail is stored as null
        assert "password_hash" not in req and "_id" not in req

        login = client.post(f"{API}/auth/login", json={"email": mob, "password": PW})
        assert login.status_code == 200, login.text
        assert login.json()["token"]

    def test_registered_mobile_blocks_a_second_request(self, client, activated):
        r = submit_request(client, activated["mobile"], name="TEST_Again")
        assert r.status_code == 400
        assert "already exists" in r.json()["detail"].lower()

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

    def test_short_password_refused(self, client):
        r = client.post(f"{API}/auth/register-request",
                        json={"full_name": "TEST_S", "mobile": rand_mobile(),
                              "password": "123", "confirm_password": "123"})
        assert r.status_code == 400
        assert "6 characters" in r.json()["detail"]

    def test_two_registrations_without_email_both_succeed(self, client, admin):
        """Regression: blank e-mail used to be stored as '' and collided on the unique e-mail index."""
        for _ in range(2):
            mob = rand_mobile()
            assert submit_request(client, mob, name="TEST_No Email").status_code == 200
            assert client.post(f"{API}/auth/login", json={"email": mob, "password": PW}).status_code == 200

    def test_invalid_referral_is_refused_and_creates_nothing(self, client, admin):
        mob = rand_mobile()
        body = {"full_name": "TEST_Bad Ref", "mobile": mob, "password": PW, "confirm_password": PW,
                "state": "Rajasthan", "city": "Jaipur", "pincode": "302001", "address": "1 Test Road",
                "sponsor_id": "NOSUCH99"}
        r = client.post(f"{API}/auth/register-request", json=body)
        assert r.status_code == 400 and "Invalid referral" in r.json()["detail"]
        assert client.post(f"{API}/auth/login", json={"email": mob, "password": PW}).status_code == 401


# ---------- login by HomeGenie ID / mobile, admin safeguards ----------
class TestActivatedAccount:
    def test_account_is_red_and_active(self, admin, activated):
        assert activated["did"].startswith("HG") and len(activated["did"]) == 8, activated["did"]
        u = find_user(admin, activated["did"])
        assert u["status"] == "red"
        assert u.get("account_status") == "active"

    def test_login_by_distributor_id(self, client, activated):
        did = activated["did"]
        r = client.post(f"{API}/auth/login", json={"email": did, "password": PW})
        assert r.status_code == 200, r.text
        u = r.json()["user"]
        assert u["distributor_id"] == did
        assert "password_hash" not in u and "_id" not in u
        assert client.post(f"{API}/auth/login", json={"email": did.lower(), "password": PW}).status_code == 200

    def test_login_by_mobile(self, client, activated):
        r = client.post(f"{API}/auth/login", json={"email": activated["mobile"], "password": PW})
        assert r.status_code == 200, r.text
        assert r.json()["user"]["distributor_id"] == activated["did"]

    def test_login_wrong_password(self, client, activated):
        r = client.post(f"{API}/auth/login", json={"email": activated["did"], "password": "Wrong@999"})
        assert r.status_code == 401

    def test_approve_of_an_activated_request_is_refused(self, admin, activated):
        r = admin.post(f"{API}/admin/registration-requests/{activated['req_id']}/approve")
        assert r.status_code == 400, r.text

    def test_reject_of_an_activated_request_is_refused_and_account_stays_active(self, client, admin, activated):
        r = admin.post(f"{API}/admin/registration-requests/{activated['req_id']}/reject")
        assert r.status_code == 400, r.text
        assert find_req(admin, activated["mobile"])["status"] == "approved"
        assert client.post(f"{API}/auth/login", json={"email": activated["mobile"], "password": PW}).status_code == 200

    def test_approve_nonexistent_404(self, admin):
        assert admin.post(f"{API}/admin/registration-requests/does-not-exist/approve").status_code == 404

    def test_reject_nonexistent_404(self, admin):
        assert admin.post(f"{API}/admin/registration-requests/does-not-exist/reject").status_code == 404


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

    def test_distributor_token_cannot_access_admin(self, client, activated):
        tok = client.post(f"{API}/auth/login",
                          json={"email": activated["did"], "password": PW}).json()["token"]
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
