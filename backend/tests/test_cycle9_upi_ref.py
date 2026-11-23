"""
HOME GENIES — Cycle 9 tests
  Module: shop_routes  -> PUT /api/admin/payments/upi-confirm/{order_id} MANDATORY reference
  Module: server       -> GET /api/settings/public returns gst_percent
  Module: auth_routes  -> /api/auth/admin-login accepts username OR email + new passcode
"""
import os
import uuid
import pytest
import requests
from dotenv import dotenv_values as _dv

_fe = _dv("/app/frontend/.env")
BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL") or _fe.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
if not BASE_URL:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ["TEST_ADMIN_EMAIL"]
ADMIN_USERNAME = os.environ.get("TEST_ADMIN_USERNAME", ADMIN_EMAIL)
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "Admin@12345")
ADMIN_PASSCODE = os.environ.get("TEST_ADMIN_PASSCODE", "anj000088sk")
DEMO_EMAIL = "demo.distributor@homegenies.example.com"
DEMO_PASSWORD = os.environ.get("TEST_DEMO_PASSWORD", "Demo@1234")


_ADMIN_TOKEN = {}


def _amt(order_id):
    """Batch 13: UPI confirmation must state the exact amount received (payment-integrity rule, Batch 1). The amount is read
    from the order itself through the admin order view; an unknown order gets a placeholder (the server answers 404)."""
    if "t" not in _ADMIN_TOKEN:
        r = requests.post(f"{API}/auth/admin-login", json={"username": os.environ.get("TEST_ADMIN_USERNAME", ADMIN_EMAIL),
                                                           "password": ADMIN_PASSWORD}, timeout=25)
        _ADMIN_TOKEN["t"] = r.json().get("token") if r.status_code == 200 else ""
    r = requests.get(f"{API}/admin/order-ops/orders/{order_id}", headers={"Authorization": f"Bearer {_ADMIN_TOKEN['t']}"}, timeout=25)
    return r.json()["order"]["total"] if r.status_code == 200 else 1.0

ADDRESS = {"full_name": "QA Tester", "mobile": "9812345678", "line1": "1 QA Street",
           "city": "Pune", "state": "MH", "pincode": "411001"}


def _session(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=25)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def dist():
    return _session(DEMO_EMAIL, DEMO_PASSWORD)


@pytest.fixture(scope="module")
def admin():
    # Batch 13: administrators sign in through the admin login only (SEC-11); the member login refuses them
    r = requests.post(f"{API}/auth/admin-login", json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}, timeout=25)
    assert r.status_code == 200, r.text
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {r.json()['token']}", "Content-Type": "application/json"})
    return s


@pytest.fixture(scope="module")
def starter():
    r = requests.get(f"{API}/products", timeout=25)
    assert r.status_code == 200, r.text
    items = r.json() if isinstance(r.json(), list) else r.json().get("products", [])
    # Batch 13: the separate "activation product" (ANJ-STARTER) is retired; any product on sale serves for a purchase
    kit = [p for p in items if p.get("is_activation_product")] or [p for p in items if p.get("sku") == "ANJ-STARTER"] or \
        [p for p in items if (p.get("stock") or 0) > 0]
    assert kit, "activation product missing"
    return kit[0]


def _claimed_order(dist_s, product_id, ref="QA-CLAIM"):
    r = dist_s.post(f"{API}/orders", json={"items": [{"product_id": product_id, "quantity": 1}],
                                           "address": ADDRESS}, timeout=30)
    assert r.status_code == 200, r.text
    o = r.json()
    assert "_id" not in o
    c = dist_s.post(f"{API}/payments/upi-claim", json={"order_id": o["id"], "reference": ref}, timeout=25)
    assert c.status_code == 200, c.text
    return o


# ---------------- Mandatory reference on admin UPI confirm ----------------
class TestUpiConfirmReference:
    def test_missing_reference_field_rejected(self, dist, admin, starter):
        o = _claimed_order(dist, starter["id"])
        r = admin.put(f"{API}/admin/payments/upi-confirm/{o['id']}", json={}, timeout=25)
        assert r.status_code in (400, 422), f"expected 400/422, got {r.status_code} {r.text[:200]}"
        got = dist.get(f"{API}/orders/{o['id']}", timeout=25).json()
        assert got["payment_status"] == "claimed", "order must remain claimed"

    def test_empty_reference_rejected_400(self, dist, admin, starter):
        o = _claimed_order(dist, starter["id"])
        for bad in ("", "   "):
            r = admin.put(f"{API}/admin/payments/upi-confirm/{o['id']}", json={"reference": bad, "amount": _amt(o['id'])}, timeout=25)
            assert r.status_code == 400, f"ref={bad!r} -> {r.status_code} {r.text[:200]}"
            assert "requir" in r.text.lower(), r.text[:300]
        got = dist.get(f"{API}/orders/{o['id']}", timeout=25).json()
        assert got["payment_status"] == "claimed"
        assert not got.get("invoice_number"), "invoice must not be generated on rejected confirm"

    def test_valid_reference_confirms_and_persists(self, dist, admin, starter):
        o = _claimed_order(dist, starter["id"])
        ref = f"UTR{uuid.uuid4().hex[:10].upper()}"
        r = admin.put(f"{API}/admin/payments/upi-confirm/{o['id']}", json={"reference": ref, "amount": _amt(o['id'])}, timeout=40)
        assert r.status_code == 200, r.text
        assert r.json().get("reference") == ref

        got = dist.get(f"{API}/orders/{o['id']}", timeout=25).json()
        assert got["payment_status"] == "paid", got["payment_status"]
        assert got["status"] == "processing", got["status"]
        assert got.get("invoice_number"), "invoice_number missing"
        assert got.get("payment_reference") == ref, got.get("payment_reference")

        # admin list exposes the reference for reconciliation
        lst = admin.get(f"{API}/admin/orders", timeout=30)
        assert lst.status_code == 200
        rows = lst.json() if isinstance(lst.json(), list) else lst.json().get("orders", [])
        row = next((x for x in rows if x.get("order_number") == o["order_number"]), None)
        assert row, "confirmed order missing from /api/admin/orders"
        assert row.get("payment_reference") == ref
        assert "_id" not in row

        # idempotent: repeat confirm keeps the same invoice and does not overwrite reference
        inv = got["invoice_number"]
        r2 = admin.put(f"{API}/admin/payments/upi-confirm/{o['id']}", json={"reference": "SHOULD-NOT-APPLY", "amount": _amt(o['id'])}, timeout=30)
        assert r2.status_code == 200, r2.text
        again = dist.get(f"{API}/orders/{o['id']}", timeout=25).json()
        assert again["invoice_number"] == inv, "invoice regenerated"
        assert again.get("payment_reference") == ref, "reference overwritten on idempotent re-confirm"

    def test_whitespace_trimmed(self, dist, admin, starter):
        o = _claimed_order(dist, starter["id"])
        r = admin.put(f"{API}/admin/payments/upi-confirm/{o['id']}", json={"reference": "  UTR-TRIM-1  ", "amount": _amt(o['id'])}, timeout=40)
        assert r.status_code == 200, r.text
        got = dist.get(f"{API}/orders/{o['id']}", timeout=25).json()
        assert got.get("payment_reference") == "UTR-TRIM-1", got.get("payment_reference")

    def test_requires_admin_role(self, dist, starter):
        o = _claimed_order(dist, starter["id"])
        r = dist.put(f"{API}/admin/payments/upi-confirm/{o['id']}", json={"reference": "HACK", "amount": _amt(o['id'])}, timeout=25)
        assert r.status_code == 403, r.status_code
        assert dist.get(f"{API}/orders/{o['id']}", timeout=25).json()["payment_status"] == "claimed"

    def test_unknown_order_404(self, admin):
        r = admin.put(f"{API}/admin/payments/upi-confirm/{uuid.uuid4()}", json={"reference": "X1", "amount": _amt(uuid.uuid4())}, timeout=25)
        assert r.status_code == 404, r.status_code


# ---------------- Public settings GST ----------------
class TestPublicSettings:
    def test_gst_percent_exposed(self):
        r = requests.get(f"{API}/settings/public", timeout=25)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "gst_percent" in d, d
        assert isinstance(d["gst_percent"], (int, float))
        assert d["gst_percent"] >= 0
        assert d.get("currency_symbol")
        assert "_id" not in d

    def test_order_total_matches_gst_setting(self, dist, starter):
        gst_pct = float(requests.get(f"{API}/settings/public", timeout=25).json()["gst_percent"])
        r = dist.post(f"{API}/orders", json={"items": [{"product_id": starter["id"], "quantity": 1}],
                                            "address": ADDRESS}, timeout=30)
        assert r.status_code == 200, r.text
        o = r.json()
        expected = o["subtotal"] + round(o["subtotal"] * gst_pct / 100)
        assert abs(o["total"] - expected) <= 1, f"total {o['total']} vs expected {expected} (gst {gst_pct}%)"


# ---------------- Admin login with username + new passcode ----------------
class TestAdminLoginUsername:
    def test_username_login_success(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "passcode": ADMIN_PASSCODE}, timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["user"]["role"] in ("admin", "super_admin")
        assert "password_hash" not in d["user"] and "_id" not in d["user"]
        me = requests.get(f"{API}/admin/dashboard", headers={"Authorization": f"Bearer {d['token']}"}, timeout=30)
        assert me.status_code == 200, me.status_code

    def test_email_as_username_still_works(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "username": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "passcode": ADMIN_PASSCODE}, timeout=30)
        assert r.status_code == 200, r.text

    def test_old_passcode_is_ignored(self):
        # approved design: the passcode is no longer required and is ignored, so the password alone signs in
        r = requests.post(f"{API}/auth/admin-login", json={
            "username": ADMIN_USERNAME, "password": ADMIN_PASSWORD, "passcode": "retired-passcode-value"}, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        assert r.json().get("token")

    def test_wrong_password_rejected(self):
        r = requests.post(f"{API}/auth/admin-login", json={
            "username": ADMIN_USERNAME, "password": "Wrong@1234", "passcode": ADMIN_PASSCODE}, timeout=30)
        assert r.status_code == 401, r.status_code
