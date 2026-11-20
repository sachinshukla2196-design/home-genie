"""Owner decisions of 2026-11-20 — one test group per rule.

 4. UPI / manual payment confirmation (and rejection) only by finance-authorised roles.
 8. Material KYC changes need a second person: whoever edited the details cannot verify them.
 9. Unverified UPI claims expire after a configurable period (default 24 h): order cancelled, stock released once, audited;
    races between expiry, confirmation and rejection resolve to exactly one outcome.
10. Support admins never reset member / vendor credentials; admin and super admin may (with the existing safeguards).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_owner_decisions.py -n 0`).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_owner_decisions_test", "JWT_SECRET": "decisions-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


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

            async def user(key, mobile, role, did, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status,
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            for key, mob, role, did in (("cust", "9100006001", "distributor", "D6CUST"), ("super", "9100006002", "super_admin", "D6SUPER"),
                                        ("admin", "9100006003", "admin", "D6ADMIN"), ("fin", "9100006004", "accounts_admin", "D6FIN"),
                                        ("fin2", "9100006005", "accounts_admin", "D6FIN2"), ("sup", "9100006006", "support_admin", "D6SUP"),
                                        ("member", "9100006007", "distributor", "D6MEM"), ("vowner", "9100006008", "vendor", "D6VEND"),
                                        ("kycm", "9100006009", "distributor", "D6KYC")):
                await user(key, mob, role, did)
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


_n = {"i": 0}


def _order(c):
    _n["i"] += 1
    pid = f"p-{_n['i']}"
    _run(c, lambda: db.products.insert_one({"id": pid, "sku": f"D6-{_n['i']}", "name": "Item", "images": [], "mrp": 1000,
                                            "selling_price": 800, "gst_percent": 5, "stock": 10, "category": "Sarees", "options": [],
                                            "vendor_id": None, "is_active": True, "approval_status": "approved", "created_at": now_iso()}))
    r = c.post("/api/orders", json={"items": [{"product_id": pid, "quantity": 2}], "address": ADDR, "payment_method": "online"},
               headers=_hdr("cust"))
    assert r.status_code == 200, r.text
    return r.json(), pid


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _stock(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}))["stock"]


def _claim(c, o):
    assert c.post("/api/payments/upi-claim", json={"order_id": o["id"], "reference": "CUSTREF"}, headers=_hdr("cust")).status_code == 200


def _confirm(c, o, ref, who="fin"):
    return c.put(f"/api/admin/payments/upi-confirm/{o['id']}", json={"reference": ref, "amount": o["total"]}, headers=_hdr(who))


def _age_claim(c, oid, hours):
    when = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"claimed_at": when}}))


# ================================================================ Decision 4: finance-only payment confirmation
@pytest.mark.parametrize("who", ["sup", "admin", "cust"])
def test_non_finance_roles_cannot_confirm_reject_or_record_payments(c, who):
    o, _ = _order(c)
    _claim(c, o)
    assert _confirm(c, o, f"UTR6{_n['i']:011d}", who=who).status_code == 403
    assert c.put(f"/api/admin/payments/upi-reject/{o['id']}", json={"reason": "not found here"}, headers=_hdr(who)).status_code == 403
    assert c.post("/api/admin/payments/manual", json={"distributor_id": "D6CUST", "reference": "UTR999999999", "amount": o["total"]},
                  headers=_hdr(who)).status_code == 403
    assert _get(c, o["id"])["payment_status"] == "claimed"


@pytest.mark.parametrize("who", ["fin", "super"])
def test_finance_roles_confirm_payments(c, who):
    o, _ = _order(c)
    _claim(c, o)
    assert _confirm(c, o, f"UTR7{_n['i']:011d}", who=who).status_code == 200
    assert _get(c, o["id"])["payment_status"] == "paid"


# ================================================================ Decision 10: password reset authority
def _reset(c, actor, target):
    return c.post(f"/api/admin/users/{S[target]['id']}/reset-password", headers=_hdr(actor),
                  json={"temporary_password": "TempPass2026x", "reason": "Member asked for a reset"})


@pytest.mark.parametrize("target", ["member", "vowner"])
def test_support_and_finance_admins_cannot_reset_member_or_vendor_credentials(c, target):
    before = _run(c, lambda: db.users.find_one({"id": S[target]["id"]}))["password_hash"]
    assert _reset(c, "sup", target).status_code == 403
    assert _reset(c, "fin", target).status_code == 403
    assert _run(c, lambda: db.users.find_one({"id": S[target]["id"]}))["password_hash"] == before


@pytest.mark.parametrize("actor,target", [("admin", "member"), ("super", "vowner")])
def test_admin_and_super_admin_may_reset_eligible_accounts(c, actor, target):
    r = _reset(c, actor, target)
    assert r.status_code == 200 and "TempPass2026x" not in r.text


# ================================================================ Decision 8: KYC second person
KYC = {"pan": "ABCDE1234F", "aadhaar": "123456789012", "account_holder_name": "Member", "bank_account": "123456789012",
       "ifsc": "SBIN0001234", "bank_name": "SBI"}


def _kyc(c):
    return _run(c, lambda: db.kyc_records.find_one({"user_id": S["kycm"]["id"]}, {"_id": 0}))


def test_editor_cannot_verify_their_own_kyc_change_but_another_admin_can(c):
    assert c.post("/api/kyc", json=KYC, headers=_hdr("kycm")).status_code == 200
    uid = S["kycm"]["id"]
    assert c.put(f"/api/admin/kyc/{uid}/edit", json={"bank_account": "555566667777"}, headers=_hdr("fin")).status_code == 200
    v = _kyc(c)["version"]
    assert c.put(f"/api/admin/kyc/{uid}", json={"action": "verify", "expected_version": v}, headers=_hdr("fin")).status_code == 403
    assert _kyc(c)["status"] == "pending"
    assert c.put(f"/api/admin/kyc/{uid}", json={"action": "verify", "expected_version": v}, headers=_hdr("fin2")).status_code == 200
    assert _kyc(c)["status"] == "verified"


def test_member_resubmission_clears_the_editor_marker(c):
    uid = S["kycm"]["id"]
    assert c.put(f"/api/admin/kyc/{uid}/edit", json={"bank_account": "888899990000"}, headers=_hdr("fin")).status_code == 200
    assert c.post("/api/kyc", json={**KYC, "bank_account": "121212121212"}, headers=_hdr("kycm")).status_code == 200
    v = _kyc(c)["version"]
    assert _kyc(c).get("last_edited_by") is None                                 # the details are the member's own again
    assert c.put(f"/api/admin/kyc/{uid}", json={"action": "verify", "expected_version": v}, headers=_hdr("fin")).status_code == 200


def test_editor_may_still_reject(c):
    uid = S["kycm"]["id"]
    assert c.put(f"/api/admin/kyc/{uid}/edit", json={"ifsc": "HDFC0001234"}, headers=_hdr("fin")).status_code == 200
    v = _kyc(c)["version"]
    r = c.put(f"/api/admin/kyc/{uid}", json={"action": "reject", "reason": "Cheque does not match", "expected_version": v}, headers=_hdr("fin"))
    assert r.status_code == 200 and _kyc(c)["status"] == "rejected"


# ================================================================ Decision 9: 24-hour UPI claim expiry
def test_claims_older_than_24_hours_expire_and_release_stock_once(c):
    o, pid = _order(c)
    assert _stock(c, pid) == 8
    _claim(c, o)
    assert _get(c, o["id"])["claimed_at"]
    _age_claim(c, o["id"], 25)
    assert _run(c, lambda: stock.expire_upi_claims()) >= 1
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and got["payment_status"] == "claim_expired" and got["cancel_reason"] == "upi_claim_expired"
    assert _stock(c, pid) == 10
    _run(c, lambda: stock.expire_upi_claims())
    assert _stock(c, pid) == 10                                                   # released exactly once
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "upi_claim_expired", "entity_id": o["id"]})) == 1


def test_fresh_claims_do_not_expire_and_the_period_is_configurable(c):
    o, pid = _order(c)
    _claim(c, o)
    _age_claim(c, o["id"], 23)
    _run(c, lambda: stock.expire_upi_claims())
    assert _get(c, o["id"])["payment_status"] == "claimed"
    _age_claim(c, o["id"], 30)
    _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"upi_claim_expiry_hours": 48}}))
    try:
        _run(c, lambda: stock.expire_upi_claims())
        assert _get(c, o["id"])["payment_status"] == "claimed"                    # 30 h < 48 h
    finally:
        _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"upi_claim_expiry_hours": 24}}))


def test_legacy_claims_without_a_claim_time_use_the_last_update(c):
    o, _ = _order(c)
    _claim(c, o)
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$unset": {"claimed_at": ""}, "$set": {"updated_at": old}}))
    _run(c, lambda: stock.expire_upi_claims())
    assert _get(c, o["id"])["payment_status"] == "claim_expired"


def test_confirmation_after_expiry_is_refused(c):
    o, pid = _order(c)
    _claim(c, o)
    _age_claim(c, o["id"], 25)
    _run(c, lambda: stock.expire_upi_claims())
    r = _confirm(c, o, f"UTR8{_n['i']:011d}")
    assert r.status_code == 409
    got = _get(c, o["id"])
    assert got["payment_status"] == "claim_expired" and _stock(c, pid) == 10


def test_confirmation_that_wins_the_race_stops_the_expiry(c):
    o, pid = _order(c)
    _claim(c, o)
    _age_claim(c, o["id"], 25)
    assert _confirm(c, o, f"UTR9{_n['i']:011d}").status_code == 200
    _run(c, lambda: stock.expire_upi_claims())
    got = _get(c, o["id"])
    assert got["payment_status"] == "paid" and got["status"] != "cancelled" and _stock(c, pid) == 8


def test_expiry_landing_during_a_confirmation_wins_cleanly(c, monkeypatch):
    """The finance admin's request has passed its checks; the expiry sweep runs before the paid-claim. Exactly one outcome."""
    o, pid = _order(c)
    _claim(c, o)
    _age_claim(c, o["id"], 25)
    real = shop_routes._process_paid_order

    async def expiry_first(sid, request=None):
        await stock.expire_upi_claims()
        return await real(sid, request)
    monkeypatch.setattr(shop_routes, "_process_paid_order", expiry_first)
    r = _confirm(c, o, f"UTRA{_n['i']:011d}")
    assert r.status_code == 409
    got = _get(c, o["id"])
    assert got["payment_status"] == "claim_expired" and got.get("invoice_number") is None and _stock(c, pid) == 10
    assert _run(c, lambda: db.commissions.count_documents({"reference_order_id": o["id"]})) == 0


def test_rejection_and_expiry_do_not_both_apply(c):
    o, pid = _order(c)
    _claim(c, o)
    _age_claim(c, o["id"], 25)
    assert c.put(f"/api/admin/payments/upi-reject/{o['id']}", json={"reason": "Not in statement"}, headers=_hdr("fin")).status_code == 200
    _run(c, lambda: stock.expire_upi_claims())
    got = _get(c, o["id"])
    assert got["payment_status"] == "pending" and got.get("cancel_reason") != "upi_claim_expired"   # back to the normal unpaid path


# ================================================================ Decision 4: maker-checker for controlled financial actions
def _vendor_id(c):
    v = _run(c, lambda: db.vendors.find_one({"user_id": S["vowner"]["id"]}))
    if not v:
        v = {"id": new_id(), "user_id": S["vowner"]["id"], "business_name": "D6 Vendor", "status": "approved", "created_at": now_iso()}
        _run(c, lambda: db.vendors.insert_one(dict(v)))
    return v["id"]


def test_wallet_credit_needs_a_second_finance_admin(c):
    rid = "rq-" + new_id()[:16]
    body = {"distributor_id": "D6KYC", "amount": 120.0, "reason": "Goodwill for delay", "request_id": rid}
    before = _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"admin_credit:{rid}"}))
    r = c.post("/api/admin/wallet/credit", json=body, headers=_hdr("fin"))
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    aid = r.json()["approval"]["id"]
    assert _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"admin_credit:{rid}"})) == before   # nothing moved yet
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("fin")).status_code == 403   # maker != checker
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("sup")).status_code == 403   # finance only
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("fin2")).status_code == 200
    assert _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"admin_credit:{rid}"})) == 1
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("super")).status_code == 409   # once only
    log = _run(c, lambda: db.audit_logs.find_one({"action": "financial_action_approved", "entity_id": aid}))
    assert log["new_value"]["maker_id"] == S["fin"]["id"] and log["user_id"] == S["fin2"]["id"]


def test_vendor_adjustment_needs_a_second_finance_admin_and_can_be_rejected(c):
    vid = _vendor_id(c)
    url = f"/api/admin/finance/vendors/{vid}/adjustments"
    r = c.post(url, json={"amount": -50, "reason": "Damaged packaging deduction"}, headers=_hdr("fin2"))
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    aid = r.json()["approval"]["id"]
    assert _run(c, lambda: db.vendor_ledger.count_documents({"vendor_id": vid, "type": "ADJUSTMENT"})) == 0
    assert c.post(f"/api/admin/finance/approvals/{aid}/reject", json={"note": "no"}, headers=_hdr("fin")).status_code == 400
    assert c.post(f"/api/admin/finance/approvals/{aid}/reject", json={"note": "Evidence missing"}, headers=_hdr("fin")).status_code == 200
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("super")).status_code == 409
    assert _run(c, lambda: db.vendor_ledger.count_documents({"vendor_id": vid, "type": "ADJUSTMENT"})) == 0
    pending = c.get("/api/admin/finance/approvals", headers=_hdr("super")).json()
    assert all(x["id"] != aid for x in pending)
    assert c.get("/api/admin/finance/approvals", headers=_hdr("sup")).status_code == 403


def test_refund_initiator_cannot_confirm_it(c):
    o, _ = _order(c)
    _claim(c, o)
    assert _confirm(c, o, f"UTRB{_n['i']:011d}").status_code == 200
    assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr("admin")).status_code == 200
    cid = _run(c, lambda: db.refund_cases.find_one({"order_id": o["id"]}))["id"]          # opened by the real cancellation path
    assert c.post(f"/api/admin/refund-cases/{cid}/action", json={"action": "initiate", "method": "upi"}, headers=_hdr("fin")).status_code == 200
    body = {"action": "confirm", "reference": "RFND-D6-0001", "confirmation_type": "manual_reconciliation", "note": "Verified in bank statement"}
    assert c.post(f"/api/admin/refund-cases/{cid}/action", json=body, headers=_hdr("fin")).status_code == 403
    assert c.post(f"/api/admin/refund-cases/{cid}/action", json=body, headers=_hdr("fin2")).status_code == 200


def test_settlement_two_person_rule_cannot_be_switched_off(c):
    vid = _vendor_id(c)
    assert c.put("/api/admin/finance/policy", headers=_hdr("fin"), json={"active": True, "require_dual_approval": False}).status_code == 200
    _run(c, lambda: db.vendor_ledger.insert_one({"id": new_id(), "vendor_id": vid, "type": "ADJUSTMENT", "amount_paise": 50000,
                                                 "source_key": "d6seed:" + vid, "status": "posted", "created_at": now_iso()}))
    sid = c.post("/api/admin/finance/settlements", headers=_hdr("fin"), json={"vendor_id": vid, "amount": 100}).json()["id"]
    act = lambda who, a, **kw: c.post(f"/api/admin/finance/settlements/{sid}/action", headers=_hdr(who), json={"action": a, **kw})  # noqa: E731
    assert act("fin", "approve").status_code == 403                                   # creator cannot approve
    assert act("fin2", "approve").status_code == 200
    assert act("fin2", "mark_paid", reference="UTR-D6-SETTLE").status_code == 403     # approver cannot pay
    assert act("fin", "mark_paid", reference="UTR-D6-SETTLE").status_code == 200


# ================================================================ Decision 5: a distinct CUSTOMER identity
REG = {"full_name": "New Shopper", "password": "Shopper-Pass-12", "confirm_password": "Shopper-Pass-12", "state": "MH",
       "city": "Pune", "pincode": "411001", "address": "1 Road"}


def test_customer_signup_creates_a_customer_not_a_distributor(c):
    _run(c, lambda: db.users.update_one({"id": S["member"]["id"]}, {"$set": {"status": "green"}}))
    r = c.post("/api/auth/register-request", json={**REG, "mobile": "9300006001", "email": "shopper1@example.com",
                                                    "account_type": "customer", "sponsor_id": "D6MEM"})
    assert r.status_code == 200, r.text
    u = _run(c, lambda: db.users.find_one({"mobile": "9300006001"}))
    assert u["role"] == "customer" and u["status"] == "customer" and u["distributor_id"].startswith("CU")
    assert u.get("sponsor_id") is None and u.get("sponsor_user_id") is None                   # no network link at all
    assert not _run(c, lambda: db.referral_relationships.find_one({"referred_user_id": u["id"]}))
    S["shopper"] = u


def test_existing_signup_still_creates_a_red_homegenie(c):
    r = c.post("/api/auth/register-request", json={**REG, "mobile": "9300006002", "email": "genie2@example.com"})
    assert r.status_code == 200
    u = _run(c, lambda: db.users.find_one({"mobile": "9300006002"}))
    assert u["role"] == "distributor" and u["status"] == "red" and u["distributor_id"].startswith("HG")


def test_customer_can_log_in_and_shop_but_never_earn_withdraw_or_activate(c):
    login = c.post("/api/auth/login", json={"email": "9300006001", "password": REG["password"]})
    assert login.status_code == 200 and login.json()["user"]["role"] == "customer"
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    pid = "p-cust"
    _run(c, lambda: db.products.insert_one({"id": pid, "sku": "D6-CUST", "name": "Item", "images": [], "mrp": 1000, "selling_price": 800,
                                            "gst_percent": 5, "stock": 10, "category": "Sarees", "options": [], "vendor_id": None,
                                            "is_active": True, "approval_status": "approved", "created_at": now_iso()}))
    o = c.post("/api/orders", json={"items": [{"product_id": pid, "quantity": 1}], "address": ADDR, "payment_method": "online",
                                    "seller_ref": "D6MEM"}, headers=h)
    assert o.status_code == 200, o.text
    assert _get(c, o.json()["id"])["seller_user_id"] == S["member"]["id"]                     # a HomeGenie earns on a customer's buy
    assert c.post("/api/withdrawals", json={"amount": 10}, headers=h).status_code == 403
    sid = "cs_" + o.json()["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o.json()["id"],
                                                        "user_id": S["shopper"]["id"], "amount": o.json()["total"],
                                                        "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    r = c.post(f"/api/admin/activations/{S['shopper']['id']}/approve", json={"order_id": o.json()["id"]}, headers=_hdr("admin"))
    assert r.status_code in (400, 403, 404, 409)
    assert _run(c, lambda: db.users.find_one({"id": S["shopper"]["id"]}))["role"] == "customer"
    shopper_comms = _run(c, lambda: db.commissions.count_documents({"user_id": S["shopper"]["id"]}))
    assert shopper_comms == 0
