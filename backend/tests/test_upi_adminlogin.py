"""
Anjali Herbal Life — Cycle 7 tests:
  Module: shop_routes  -> Manual UPI checkout (claim -> admin confirm -> paid, idempotent)
  Module: shop_routes  -> Stripe checkout regression
  Module: auth_routes  -> Secured admin login (/api/auth/admin-login)
"""
import os
import random
import uuid
import pytest
import requests
from dotenv import dotenv_values as _dv

_fe = _dv("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sachin.shukla2196@gmail.com"
ADMIN_PASSWORD = "Admin@12345"
ADMIN_PASSCODE = "Anjali@Secure#2026"
DEMO_EMAIL = "demo.distributor@anjaliherballife.in"
DEMO_PASSWORD = "Demo@1234"

ADDRESS = {"full_name": "QA Tester", "mobile": "9812345678", "line1": "1 QA Street",
           "city": "Pune", "state": "MH", "pincode": "411001"}


def _auth(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    return r.json()["token"], r.json()["user"]


@pytest.fixture(scope="module")
def dist():
    token, user = _auth(DEMO_EMAIL, DEMO_PASSWORD)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s, user


@pytest.fixture(scope="module")
def admin():
    token, user = _auth(ADMIN_EMAIL, ADMIN_PASSWORD)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return s, user


@pytest.fixture(scope="module")
def starter_product():
    r = requests.get(f"{API}/products", timeout=20)
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("products", r.json().get("items", []))
    kit = [p for p in items if p.get("is_activation_product")] or [p for p in items if p.get("sku") == "ANJ-STARTER"]
    assert kit, f"No activation product found in /api/products: {items[:1]}"
    return kit[0]


def _create_order(session, product_id, qty=1):
    r = session.post(f"{API}/orders", json={"items": [{"product_id": product_id, "quantity": qty}],
                                            "address": ADDRESS}, timeout=25)
    assert r.status_code == 200, f"create order: {r.status_code} {r.text[:400]}"
    o = r.json()
    assert "_id" not in o
    assert o["payment_status"] == "pending", o["payment_status"]
    assert o["total"] > 0
    return o


# ---------------- Manual UPI checkout ----------------
class TestManualUpi:
    def test_full_claim_confirm_flow(self, dist, admin, starter_product):
        ds, _ = dist
        adm, _ = admin
        order = _create_order(ds, starter_product["id"])
        oid, onum = order["id"], order["order_number"]

        # claim
        r = ds.post(f"{API}/payments/upi-claim", json={"order_id": oid, "reference": "QA-UPI-REF-1"}, timeout=25)
        assert r.status_code == 200, r.text
        assert "order_id" in r.json() and r.json()["order_id"] == oid

        g = ds.get(f"{API}/orders/{oid}", timeout=20)
        assert g.status_code == 200, g.text
        od = g.json()
        assert od["payment_status"] == "claimed", od["payment_status"]
        assert od.get("payment_method") == "upi_manual"
        assert od.get("upi_reference") == "QA-UPI-REF-1"

        # admin sees it in the orders list
        al = adm.get(f"{API}/admin/orders", timeout=25)
        assert al.status_code == 200, al.text
        lst = al.json() if isinstance(al.json(), list) else al.json().get("orders", [])
        assert any(o.get("order_number") == onum and o.get("payment_status") == "claimed" for o in lst), \
            "claimed order not visible in /api/admin/orders"

        # admin confirm
        c = adm.put(f"{API}/admin/payments/upi-confirm/{oid}", timeout=30)
        assert c.status_code == 200, c.text

        g2 = ds.get(f"{API}/orders/{oid}", timeout=20)
        od2 = g2.json()
        assert od2["payment_status"] == "paid", od2["payment_status"]
        assert od2["status"] == "processing", od2["status"]
        assert od2.get("invoice_number"), "invoice_number not generated"

        # idempotency: second confirm must not change anything
        c2 = adm.put(f"{API}/admin/payments/upi-confirm/{oid}", timeout=30)
        assert c2.status_code == 200, c2.text
        od3 = ds.get(f"{API}/orders/{oid}", timeout=20).json()
        assert od3["invoice_number"] == od2["invoice_number"], "invoice regenerated on repeat confirm"
        assert od3["payment_status"] == "paid"

    def test_claim_rejects_paid_order(self, dist, admin, starter_product):
        ds, _ = dist
        adm, _ = admin
        order = _create_order(ds, starter_product["id"])
        ds.post(f"{API}/payments/upi-claim", json={"order_id": order["id"]}, timeout=25)
        adm.put(f"{API}/admin/payments/upi-confirm/{order['id']}", timeout=30)
        r = ds.post(f"{API}/payments/upi-claim", json={"order_id": order["id"]}, timeout=25)
        assert r.status_code == 400, f"expected 400 for paid order, got {r.status_code} {r.text[:200]}"

    def test_claim_unknown_order_404(self, dist):
        ds, _ = dist
        r = ds.post(f"{API}/payments/upi-claim", json={"order_id": str(uuid.uuid4())}, timeout=20)
        assert r.status_code == 404, r.status_code

    def test_claim_requires_auth(self, starter_product):
        r = requests.post(f"{API}/payments/upi-claim", json={"order_id": str(uuid.uuid4())}, timeout=20)
        assert r.status_code in (401, 403), r.status_code

    def test_confirm_requires_admin(self, dist, starter_product):
        ds, _ = dist
        order = _create_order(ds, starter_product["id"])
        r = ds.put(f"{API}/admin/payments/upi-confirm/{order['id']}", timeout=20)
        assert r.status_code == 403, f"distributor must not confirm payments, got {r.status_code}"
        # order must stay pending
        assert ds.get(f"{API}/orders/{order['id']}", timeout=20).json()["payment_status"] == "pending"

    def test_confirm_unknown_order_404(self, admin):
        adm, _ = admin
        r = adm.put(f"{API}/admin/payments/upi-confirm/{uuid.uuid4()}", timeout=20)
        assert r.status_code == 404, r.status_code

    def test_cannot_claim_other_users_order(self, admin, dist, starter_product):
        """Order created by distributor cannot be claimed by another user (admin acts as another user)."""
        ds, _ = dist
        adm, _ = admin
        order = _create_order(ds, starter_product["id"])
        r = adm.post(f"{API}/payments/upi-claim", json={"order_id": order["id"]}, timeout=20)
        assert r.status_code == 404, f"cross-user claim should 404, got {r.status_code}"


# ---------------- Stripe checkout regression ----------------
class TestStripeRegression:
    def test_checkout_returns_url(self, dist, starter_product):
        ds, _ = dist
        order = _create_order(ds, starter_product["id"])
        r = ds.post(f"{API}/payments/checkout", json={"order_id": order["id"], "origin_url": BASE_URL}, timeout=40)
        assert r.status_code == 200, f"{r.status_code} {r.text[:400]}"
        d = r.json()
        assert d.get("checkout_url", "").startswith("http"), d
        assert d.get("session_id")
        st = ds.get(f"{API}/payments/status/{d['session_id']}", timeout=40)
        assert st.status_code == 200, st.text
        assert st.json()["payment_status"] != "paid"

    def test_checkout_rejects_paid_order(self, dist, admin, starter_product):
        ds, _ = dist
        adm, _ = admin
        order = _create_order(ds, starter_product["id"])
        ds.post(f"{API}/payments/upi-claim", json={"order_id": order["id"]}, timeout=25)
        adm.put(f"{API}/admin/payments/upi-confirm/{order['id']}", timeout=30)
        r = ds.post(f"{API}/payments/checkout", json={"order_id": order["id"], "origin_url": BASE_URL}, timeout=40)
        assert r.status_code == 400, r.status_code


# ---------------- Secured admin login ----------------
class TestAdminLogin:
    def test_success(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "passcode": ADMIN_PASSCODE}, timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("token") and isinstance(d["token"], str)
        assert d["user"]["email"] == ADMIN_EMAIL
        assert d["user"]["role"] in ("admin", "super_admin")
        assert "password_hash" not in d["user"] and "_id" not in d["user"]
        # token works on an admin endpoint
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {d['token']}"}, timeout=20)
        assert me.status_code == 200 and me.json()["role"] in ("admin", "super_admin")
        adm = requests.get(f"{API}/admin/dashboard", headers={"Authorization": f"Bearer {d['token']}"}, timeout=25)
        assert adm.status_code == 200, adm.status_code

    def test_wrong_passcode_401(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "passcode": "wrong-passcode"}, timeout=25)
        assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"
        assert "token" not in r.text

    def test_missing_passcode_rejected(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=25)
        assert r.status_code in (401, 422), r.status_code

    def test_distributor_role_gated(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "email": DEMO_EMAIL, "password": DEMO_PASSWORD, "passcode": ADMIN_PASSCODE}, timeout=25)
        assert r.status_code == 401, f"distributor must be rejected, got {r.status_code} {r.text[:200]}"

    def test_lockout_after_5_wrong_attempts(self):
        """Uses a throwaway email so the real admin identifier is never locked."""
        email = f"qa_lock_{random.randint(10000, 99999)}@qa-anjali.example.com"
        codes = []
        for _ in range(6):
            r = requests.post(f"{API}/auth/admin-login", json={
                "email": email, "password": "Nope@1234", "passcode": "bad"}, timeout=25)
            codes.append(r.status_code)
        assert codes[:5] == [401] * 5, codes
        assert codes[5] == 429, f"expected 429 lockout on 6th attempt, got {codes}"
        # even correct passcode is blocked while locked
        r = requests.post(f"{API}/auth/admin-login", json={
            "email": email, "password": "Nope@1234", "passcode": ADMIN_PASSCODE}, timeout=25)
        assert r.status_code == 429, r.status_code

    def test_admin_credentials_not_locked_by_this_suite(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "passcode": ADMIN_PASSCODE}, timeout=25)
        assert r.status_code == 200, f"admin got locked out: {r.status_code} {r.text[:200]}"
