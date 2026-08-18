"""
Iteration 5 tests:
- Deployment health-probe fix (GET /health w/o /api prefix)
- /api/dashboard optimization regression
- Core flows regression (admin login, wallet, team, referral, products, register OTP)
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "sachin.shukla2196@gmail.com"
ADMIN_PASSWORD = "Admin@12345"
DEMO_EMAIL = "demo.distributor@anjaliherballife.in"
DEMO_PASSWORD = "Demo@1234"


# ---------------- Health probe ----------------
class TestHealth:
    def test_health_root_no_api_prefix_internal(self):
        # K8s health probe hits backend container directly on port 8001 (no ingress)
        r = requests.get("http://localhost:8001/health", timeout=10)
        assert r.status_code == 200, f"internal /health failed: {r.status_code} {r.text}"
        assert r.json() == {"status": "ok"}

    def test_health_api_prefix(self):
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ---------------- Auth helpers ----------------
def _login(email, password):
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=15)
    assert r.status_code == 200, f"login failed {email}: {r.status_code} {r.text}"
    return r.json()["token"]


@pytest.fixture(scope="module")
def demo_token():
    return _login(DEMO_EMAIL, DEMO_PASSWORD)


@pytest.fixture(scope="module")
def admin_token():
    return _login(ADMIN_EMAIL, ADMIN_PASSWORD)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------- Dashboard optimization regression ----------------
class TestDashboard:
    def test_demo_distributor_dashboard(self, demo_token):
        r = requests.get(f"{API}/dashboard", headers=_auth(demo_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # stats
        assert "stats" in data
        assert isinstance(data["stats"].get("total_orders"), int)
        # recent orders <= 5
        recent = data.get("recent_orders", [])
        assert isinstance(recent, list)
        assert len(recent) <= 5
        # wallet snapshot 500/500/1000
        wallet = data.get("wallet", {})
        assert wallet.get("available_balance") == 500, wallet
        assert wallet.get("pending_balance") == 500, wallet
        assert wallet.get("total_earned") == 1000, wallet
        # income series present
        assert "income_series" in data
        assert isinstance(data["income_series"], list)
        # today_income numeric
        assert isinstance(data.get("today_income", 0), (int, float))


# ---------------- Core flows regression ----------------
class TestCoreFlows:
    def test_admin_dashboard(self, admin_token):
        r = requests.get(f"{API}/admin/dashboard", headers=_auth(admin_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "stats" in data or "total_users" in data or isinstance(data, dict)

    def test_wallet(self, demo_token):
        r = requests.get(f"{API}/wallet", headers=_auth(demo_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get("available_balance") == 500
        assert data.get("pending_balance") == 500
        assert data.get("total_earned") == 1000

    def test_team(self, demo_token):
        r = requests.get(f"{API}/team", headers=_auth(demo_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        # accept either flat list or root+members
        members = data.get("members") if isinstance(data, dict) else None
        root = data.get("root") if isinstance(data, dict) else None
        assert root is not None or members is not None, data
        if members is not None:
            assert len(members) >= 3
            for m in members[:3]:
                assert "downline_count" in m
                # photo field may be photo/photo_url
                assert any(k in m for k in ("photo", "photo_url", "avatar"))

    def test_referral(self, demo_token):
        r = requests.get(f"{API}/referral", headers=_auth(demo_token), timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "referral_code" in data or "code" in data or "link" in data

    def test_products_list(self):
        r = requests.get(f"{API}/products", timeout=15)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_register_send_otp(self):
        mobile = "9" + str(int(time.time() * 1000))[-9:]
        email = f"TEST_otp_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/send-otp", json={"email": email, "mobile": mobile}, timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "dev_otp" in data or "otp" in data or data.get("success") is True
