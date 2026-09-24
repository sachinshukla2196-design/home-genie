"""Production-hardening E2E tests (iteration_12).

Covers:
- Admin login (new creds) / old creds rejected
- OTP fail-safe (503) with no dev_otp leakage
- Admin blocked from OTP login (403)
- reset-data backdoor removed (404)
- Registration flow -> admin approve -> NO ₹100 at approval
- Activation via admin manual-payment -> ₹100 sponsor commission, idempotent
- 3-deep chain product commission (20% / 12%) on non-activation product
- Withdrawal (no minimum), atomic wallet, reject returns funds, mark_paid clears pending
- Refund clawback (idempotent)
"""
import os
import time
import random
import string
import pytest
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "frontend" / ".env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_USER = "admin"
ADMIN_PASS = "fFiiKDF2TBZtiVrwcu"
ADMIN_PASSCODE = "79258486"
MASTER_ID = "MST000001"


def _rand_mobile():
    return "9" + "".join(random.choice("0123456789") for _ in range(9))


def _rand_aadhaar():
    return "".join(random.choice("0123456789") for _ in range(12))


def _rand_str(n=6):
    return "".join(random.choices(string.ascii_lowercase, k=n))


# ---------------- Fixtures ----------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/admin-login",
                      json={"username": ADMIN_USER, "password": ADMIN_PASS, "passcode": ADMIN_PASSCODE},
                      timeout=15)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data["user"]["role"] == "super_admin"
    assert isinstance(data.get("token"), str) and len(data["token"]) > 10
    return data["token"]


@pytest.fixture(scope="session")
def admin_h(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------- Helpers ----------------
def _register_request(sponsor_id):
    body = {
        "full_name": f"TEST {_rand_str()}",
        "mobile": _rand_mobile(),
        "password": "Test@1234", "confirm_password": "Test@1234",
        "email": "", "address": "line1",
        "state": "Delhi", "city": "Delhi", "pincode": "110001",
        "sponsor_id": sponsor_id, "aadhaar_number": _rand_aadhaar(),
    }
    r = requests.post(f"{API}/auth/register-request", json=body, timeout=15)
    return r, body


def _find_pending_req(admin_h, mobile):
    r = requests.get(f"{API}/admin/registration-requests", headers=admin_h, timeout=15)
    assert r.status_code == 200
    for x in r.json():
        if x.get("mobile") == mobile and x.get("status") == "pending":
            return x
    return None


def _approve(admin_h, req_id):
    r = requests.post(f"{API}/admin/registration-requests/{req_id}/approve",
                      headers=admin_h, json={}, timeout=15)
    return r


def _login(identifier, password="Test@1234"):
    r = requests.post(f"{API}/auth/login", json={"email": identifier, "password": password}, timeout=15)
    return r


def _admin_manual_payment(admin_h, did, reference="TEST-ACT"):
    r = requests.post(f"{API}/admin/payments/manual", headers=admin_h,
                      json={"distributor_id": did, "reference": reference, "note": ""},
                      timeout=20)
    return r


def _create_and_activate(admin_h, sponsor_did):
    """Register -> approve -> activate a new distributor. Returns (did, user_id, mobile, token)."""
    r, body = _register_request(sponsor_did)
    assert r.status_code == 200, f"register-request failed: {r.text}"
    req = _find_pending_req(admin_h, body["mobile"])
    assert req is not None, "pending request not found"
    ar = _approve(admin_h, req["id"])
    assert ar.status_code == 200, f"approve failed: {ar.text}"
    did = ar.json()["distributor_id"]
    # Activate via admin manual payment
    mp = _admin_manual_payment(admin_h, did, reference=f"TEST-ACT-{did}")
    assert mp.status_code == 200, f"manual payment failed: {mp.text}"
    # login as this distributor
    lg = _login(did)
    assert lg.status_code == 200, f"login failed: {lg.text}"
    tok = lg.json()["token"]
    uid = lg.json()["user"]["id"]
    return did, uid, body["mobile"], tok


# ==============================================================
# 1. Admin login: new creds work, old rejected
# ==============================================================
class TestAdminLogin:
    def test_new_creds_ok(self, admin_token):
        assert isinstance(admin_token, str)

    def test_old_creds_rejected(self):
        r = requests.post(f"{API}/auth/admin-login",
                          json={"username": "admin", "password": "admin123", "passcode": "admin123"},
                          timeout=15)
        assert r.status_code == 401, f"expected 401 got {r.status_code} {r.text}"


# ==============================================================
# 2. OTP fail-safe and admin block, no dev_otp in payloads
# ==============================================================
class TestOtp:
    def test_login_otp_send_unconfigured_returns_503_no_otp_leak(self, admin_h):
        # Register a fresh non-admin distributor so we know the mobile is non-admin.
        r, body = _register_request(MASTER_ID)
        assert r.status_code == 200, r.text
        req = _find_pending_req(admin_h, body["mobile"])
        ar = _approve(admin_h, req["id"])
        assert ar.status_code == 200
        # Now hit login-otp/send for this registered non-admin mobile → expect 503
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": body["mobile"]}, timeout=15)
        assert r.status_code == 503, f"expected 503 got {r.status_code} {r.text}"
        body_text = r.text.lower()
        for banned in ("dev_otp", "test_number", "test_otp", "\"otp\":"):
            assert banned not in body_text, f"leaked '{banned}' in response"

    def test_admin_otp_blocked_403(self, admin_h):
        # Mobile 9999999999 belongs to an admin per current DB (proven by prior probe).
        r = requests.post(f"{API}/auth/login-otp/send", json={"mobile": "9999999999"}, timeout=15)
        # If no admin holds that mobile in this env we skip; else assert 403.
        if r.status_code == 404:
            pytest.skip("no admin mobile present in DB to probe")
        assert r.status_code == 403, f"expected 403 for admin OTP send, got {r.status_code} {r.text}"
        assert "otp" not in r.text.lower() or "sign in with the secure" in r.text.lower()


# ==============================================================
# 3. reset-data backdoor removed
# ==============================================================
class TestResetBackdoor:
    def test_reset_data_removed(self, admin_h):
        r = requests.post(f"{API}/admin/maintenance/reset-data", headers=admin_h,
                          json={"confirm": "RESET"}, timeout=15)
        assert r.status_code == 404, f"expected 404 got {r.status_code} {r.text}"


# ==============================================================
# 4. Registration flow: approval does NOT credit ₹100
# ==============================================================
class TestRegistrationApprovalNoRupee100:
    def test_approve_does_not_pay_100(self, admin_h):
        r, body = _register_request(MASTER_ID)
        assert r.status_code == 200, r.text
        req = _find_pending_req(admin_h, body["mobile"])
        assert req is not None
        ar = _approve(admin_h, req["id"])
        assert ar.status_code == 200, ar.text
        did = ar.json()["distributor_id"]
        # verify no REFERRAL_COMMISSION for this new user
        comms = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        for c in comms:
            assert not (c.get("referred_distributor_id") == did
                        and c.get("type") == "REFERRAL_COMMISSION"), \
                f"₹100 wrongly credited at approval for {did}"
        # cleanup: leave the RED user (will be reused/deleted at session end)


# ==============================================================
# 5. ₹100 at GREEN activation, idempotent
# ==============================================================
class TestActivationRupee100:
    def test_activation_pays_100_once(self, admin_h):
        # Register + approve under MST000001 (sponsor is admin — but admin isn't GREEN → no ₹100 possible).
        # Per code: referral commission only paid if sponsor.status == 'green'.
        # So we need to first create a GREEN sponsor under MST000001, then a new distributor under that sponsor.
        sponsor_did, sponsor_uid, _, _ = _create_and_activate(admin_h, MASTER_ID)
        # Now create a NEW distributor with sponsor_did and activate them
        r, body = _register_request(sponsor_did)
        assert r.status_code == 200, r.text
        req = _find_pending_req(admin_h, body["mobile"])
        ar = _approve(admin_h, req["id"])
        assert ar.status_code == 200, ar.text
        new_did = ar.json()["distributor_id"]

        # count referral commissions BEFORE activation
        comms_before = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        n_before = sum(1 for c in comms_before
                       if c.get("referred_distributor_id") == new_did
                       and c.get("type") == "REFERRAL_COMMISSION")
        assert n_before == 0

        # activate
        mp = _admin_manual_payment(admin_h, new_did, reference=f"TEST-ACT-{new_did}")
        assert mp.status_code == 200, mp.text

        comms_after = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        ref_comms = [c for c in comms_after
                     if c.get("referred_distributor_id") == new_did
                     and c.get("type") == "REFERRAL_COMMISSION"]
        assert len(ref_comms) == 1, f"expected 1 REFERRAL_COMMISSION got {len(ref_comms)}"
        c = ref_comms[0]
        assert float(c["amount"]) == 100.0
        assert c.get("sponsor_distributor_id") == sponsor_did

        # New distributor should have zero commissions to themselves
        self_comms = [c for c in comms_after
                      if c.get("sponsor_distributor_id") == new_did]
        assert len(self_comms) == 0

        # idempotent: rerun manual payment
        mp2 = _admin_manual_payment(admin_h, new_did, reference=f"TEST-ACT-{new_did}")
        assert mp2.status_code == 200, mp2.text
        comms_final = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        ref_comms2 = [c for c in comms_final
                      if c.get("referred_distributor_id") == new_did
                      and c.get("type") == "REFERRAL_COMMISSION"]
        assert len(ref_comms2) == 1, "double payment on retry (not idempotent)"


# ==============================================================
# 6. 70% product commission E2E (2 deep)
# ==============================================================
@pytest.fixture(scope="module")
def product_id(admin_h):
    """Create a NON-activation product for the 70% commission test."""
    sku = f"TEST-PROD-{_rand_str(8).upper()}"
    body = {"sku": sku, "name": f"Test Product {sku}", "mrp": 1000, "selling_price": 1000,
            "gst_percent": 5.0, "stock": 500, "category": "Test",
            "is_active": True, "is_activation_product": False}
    r = requests.post(f"{API}/admin/products", headers=admin_h, json=body, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


class TestProductLevelCommission:
    def test_l1_l2_commission_20_12(self, admin_h, product_id):
        # Build a 3-deep GREEN chain: A -> B -> C (C is buyer)
        did_a, uid_a, _, tok_a = _create_and_activate(admin_h, MASTER_ID)
        did_b, uid_b, _, tok_b = _create_and_activate(admin_h, did_a)
        did_c, uid_c, _, tok_c = _create_and_activate(admin_h, did_b)

        # C places a product order (non-activation)
        addr = {"full_name": "Buyer", "mobile": "9876543210",
                "line1": "L1", "city": "Delhi", "state": "Delhi", "pincode": "110001"}
        order_body = {"items": [{"product_id": product_id, "quantity": 1}], "address": addr}
        ro = requests.post(f"{API}/orders", headers={"Authorization": f"Bearer {tok_c}"},
                           json=order_body, timeout=15)
        assert ro.status_code == 200, ro.text
        order = ro.json()
        assert order.get("is_activation_order") is False
        subtotal = float(order["subtotal"])
        assert subtotal == 1000.0

        # Admin marks paid via manual payment (uses latest unpaid order for that distributor)
        mp = _admin_manual_payment(admin_h, did_c, reference=f"PROD-{order['order_number']}")
        assert mp.status_code == 200, mp.text

        # Fetch commissions and confirm L1=20% to B, L2=12% to A
        comms = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        order_comms = [c for c in comms
                       if c.get("reference_order_id") == order["id"]
                       and c.get("type") == "PURCHASE_LEVEL_COMMISSION"]
        by_sponsor = {c["sponsor_distributor_id"]: c for c in order_comms}
        assert did_b in by_sponsor, f"L1 (sponsor {did_b}) commission missing; got {order_comms}"
        assert did_a in by_sponsor, f"L2 (sponsor {did_a}) commission missing"
        l1 = by_sponsor[did_b]
        l2 = by_sponsor[did_a]
        assert float(l1["amount"]) == round(subtotal * 0.20, 2), f"L1 amt {l1['amount']}"
        assert float(l1["percent"]) == 20.0
        assert float(l1["base_amount"]) == subtotal
        assert float(l2["amount"]) == round(subtotal * 0.12, 2), f"L2 amt {l2['amount']}"
        assert float(l2["percent"]) == 12.0

        # store for refund test
        pytest.SHARED_ORDER_ID = order["id"]
        pytest.SHARED_ORDER_TOTAL = order["total"]
        pytest.SHARED_ORDER_BUYER = did_c
        pytest.SHARED_L1_SPONSOR_UID = uid_b

    def test_activation_order_did_not_create_purchase_commission(self, admin_h):
        """Activation orders must not create PURCHASE_LEVEL_COMMISSION rows."""
        comms = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        # find activation orders (all have is_activation_order True). Fetch orders.
        orders = requests.get(f"{API}/admin/orders", headers=admin_h, timeout=15).json()
        act_order_ids = {o["id"] for o in orders if o.get("is_activation_order")}
        bad = [c for c in comms
               if c.get("type") == "PURCHASE_LEVEL_COMMISSION"
               and c.get("reference_order_id") in act_order_ids]
        assert not bad, f"activation orders wrongly created purchase commissions: {len(bad)}"


# ==============================================================
# 7. Withdrawal atomic + no minimum
# ==============================================================
class TestWithdrawal:
    def test_withdrawal_flow(self, admin_h):
        # Create GREEN distributor A -> GREEN B under A. B buys product to give A commission.
        sponsor_did, sponsor_uid, _, sponsor_tok = _create_and_activate(admin_h, MASTER_ID)
        buyer_did, buyer_uid, _, buyer_tok = _create_and_activate(admin_h, sponsor_did)

        # Create a non-activation product
        sku = f"TEST-WD-{_rand_str(6).upper()}"
        pr = requests.post(f"{API}/admin/products", headers=admin_h,
                           json={"sku": sku, "name": sku, "mrp": 500, "selling_price": 500,
                                 "gst_percent": 5.0, "stock": 100, "category": "Test",
                                 "is_active": True, "is_activation_product": False}, timeout=15)
        assert pr.status_code in (200, 201), pr.text
        pid = pr.json()["id"]

        addr = {"full_name": "B", "mobile": "9876543210",
                "line1": "L1", "city": "Delhi", "state": "Delhi", "pincode": "110001"}
        ro = requests.post(f"{API}/orders", headers={"Authorization": f"Bearer {buyer_tok}"},
                           json={"items": [{"product_id": pid, "quantity": 1}], "address": addr}, timeout=15)
        assert ro.status_code == 200, ro.text

        mp = _admin_manual_payment(admin_h, buyer_did, reference="TEST-WD-BUY")
        assert mp.status_code == 200, mp.text

        # KYC submit + admin verify for sponsor
        kbody = {"pan": "ABCDE1234F", "aadhaar": "111122223333",
                 "account_holder_name": "T", "bank_account": "1234567890",
                 "ifsc": "SBIN0001234", "bank_name": "SBI"}
        kr = requests.post(f"{API}/kyc", headers={"Authorization": f"Bearer {sponsor_tok}"},
                           json=kbody, timeout=15)
        assert kr.status_code == 200, kr.text
        vr = requests.put(f"{API}/admin/kyc/{sponsor_uid}", headers=admin_h,
                          json={"action": "verify", "reason": ""}, timeout=15)
        assert vr.status_code == 200, vr.text

        # Wallet before
        w0 = requests.get(f"{API}/wallet", headers={"Authorization": f"Bearer {sponsor_tok}"}, timeout=15).json()
        avail0 = float(w0["available_balance"])
        pend0 = float(w0["pending_balance"])
        assert avail0 >= 100.0, f"expected >=100 balance from L1 commission, got {avail0}"

        # Request withdrawal for 50 (any amount>0 allowed)
        amt = 50.0
        wr = requests.post(f"{API}/withdrawals", headers={"Authorization": f"Bearer {sponsor_tok}"},
                           json={"amount": amt}, timeout=15)
        assert wr.status_code == 200, wr.text
        wd_id = wr.json()["id"]

        w1 = requests.get(f"{API}/wallet", headers={"Authorization": f"Bearer {sponsor_tok}"}, timeout=15).json()
        assert abs(float(w1["available_balance"]) - (avail0 - amt)) < 0.01
        assert abs(float(w1["pending_balance"]) - (pend0 + amt)) < 0.01

        # Insufficient balance
        big = requests.post(f"{API}/withdrawals", headers={"Authorization": f"Bearer {sponsor_tok}"},
                            json={"amount": 999999.0}, timeout=15)
        assert big.status_code == 400, big.text

        # Reject -> returns to available
        rj = requests.put(f"{API}/admin/withdrawals/{wd_id}", headers=admin_h,
                         json={"action": "reject", "note": "test"}, timeout=15)
        assert rj.status_code == 200, rj.text
        w2 = requests.get(f"{API}/wallet", headers={"Authorization": f"Bearer {sponsor_tok}"}, timeout=15).json()
        assert abs(float(w2["available_balance"]) - avail0) < 0.01
        assert abs(float(w2["pending_balance"]) - pend0) < 0.01

        # New request + mark_paid clears pending, increases total_withdrawn
        wr2 = requests.post(f"{API}/withdrawals", headers={"Authorization": f"Bearer {sponsor_tok}"},
                            json={"amount": amt}, timeout=15)
        assert wr2.status_code == 200
        wd2_id = wr2.json()["id"]
        tw0 = float(w2.get("total_withdrawn", 0) or 0)
        mpay = requests.put(f"{API}/admin/withdrawals/{wd2_id}", headers=admin_h,
                            json={"action": "mark_paid", "note": ""}, timeout=15)
        assert mpay.status_code == 200, mpay.text
        w3 = requests.get(f"{API}/wallet", headers={"Authorization": f"Bearer {sponsor_tok}"}, timeout=15).json()
        assert abs(float(w3["pending_balance"]) - pend0) < 0.01
        assert abs(float(w3["total_withdrawn"]) - (tw0 + amt)) < 0.01


# ==============================================================
# 8. Refund clawback (idempotent)
# ==============================================================
class TestRefundClawback:
    def test_refund_reverses_commissions(self, admin_h):
        order_id = getattr(pytest, "SHARED_ORDER_ID", None)
        if not order_id:
            pytest.skip("no shared order from product-commission test")
        # Snapshot commissions
        comms_pre = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        pre_map = {c["id"]: c for c in comms_pre if c.get("reference_order_id") == order_id}
        assert pre_map, "no commissions for shared order"
        assert all(c["status"] == "CREDITED" for c in pre_map.values())

        # Refund
        rf = requests.put(f"{API}/admin/orders/{order_id}/status", headers=admin_h,
                         json={"status": "refunded"}, timeout=15)
        assert rf.status_code == 200, rf.text

        comms_post = requests.get(f"{API}/admin/commissions", headers=admin_h, timeout=15).json()
        post_map = {c["id"]: c for c in comms_post if c.get("reference_order_id") == order_id}
        for cid in pre_map:
            assert post_map[cid]["status"] == "REVERSED", f"comm {cid} not reversed"

        # Idempotent: repeat refund -> no additional CLAWBACK ledger entries
        txs1 = requests.get(f"{API}/admin/reports/wallet", headers=admin_h, timeout=15).json()
        n1 = sum(1 for r in txs1["rows"] if r.get("type") == "COMMISSION_CLAWBACK")
        rf2 = requests.put(f"{API}/admin/orders/{order_id}/status", headers=admin_h,
                          json={"status": "refunded"}, timeout=15)
        assert rf2.status_code == 200
        txs2 = requests.get(f"{API}/admin/reports/wallet", headers=admin_h, timeout=15).json()
        n2 = sum(1 for r in txs2["rows"] if r.get("type") == "COMMISSION_CLAWBACK")
        assert n1 == n2, f"refund not idempotent: {n1} -> {n2}"
