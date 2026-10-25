"""End-to-end vendor lifecycle (Phase 8): admin creates a vendor, the owner completes onboarding, is approved and activated, invites
and revokes staff, runs products, stock, orders and reports, and goes through commercial terms, a settlement and a benefit.
Each step asserts the state the next step depends on. Security checks run at the points they matter.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_e2e_vendor_integration.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_e2e_test", "JWT_SECRET": "e2e-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger as L  # noqa: E402
import returns_routes  # noqa: E402
import core  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADMIN_PW = "Admin-Pass-123"
OWNER_PW = "Owner-Pass-123"
STAFF_PW = "Staff-Pass-456"
ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
PROFILE = {"business_name": "E2E Store", "contact_person": "Owner Name", "phone": "9876500050", "address": "12 Market Road, Jaipur",
           "city": "Jaipur", "state": "RJ", "pincode": "302001", "categories": ["Sarees"], "bank_account_name": "E2E Store",
           "bank_account": "111122223333", "ifsc": "SBIN0000001", "agree_terms": True}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _login(c, ident, pw):
    r = c.post("/api/auth/login", json={"email": ident, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()      # the migration step: startup no longer creates indexes
            for key, mobile, role, name in (("fin1", "9100005001", "accounts_admin", "Finance One"), ("fin2", "9100005002", "super_admin", "Finance Two"),
                                       ("cust", "9100005003", "distributor", "Customer One")):
                S[key] = {"id": new_id(), "distributor_id": f"E{key.upper()}", "full_name": name, "mobile": mobile, "email": None,
                          "password_hash": hash_password(ADMIN_PW), "role": role, "status": "green", "account_status": "active",
                          "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(S[key]))
            await db.finance_policy.update_one({"id": "settlement_policy"}, {"$set": {"id": "settlement_policy", "active": True, "version": 1,
                                                "require_dual_approval": True, "min_settlement_paise": 0, "cod_overdue_days": 7, "notes": "e2e",
                                                "updated_by": None, "updated_at": now_iso()}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _paid_order(vid, pid, paise):
    now = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    line = {"product_id": pid, "name": "E2E saree", "sku": "E2E-1", "vendor_id": vid, "quantity": 1, "price_paise": paise, "price": paise / 100,
            "total_paise": paise, "total": paise / 100}
    return {"id": new_id(), "order_number": "E2E" + new_id()[:8].upper(), "user_id": new_id(), "payment_method": "online", "payment_status": "paid",
            "status": "new", "created_at": now, "paid_at": now, "total_paise": paise, "total": paise / 100, "items": [line],
            "fulfilments": [{"vendor_id": vid, "status": "new", "events": []}], "address": ADDR, "needs_refund": False}


def test_full_vendor_lifecycle(c):
    fin2, fin1 = _hdr(S["fin2"]["id"]), _hdr(S["fin1"]["id"])

    # 1. admin creates the vendor account; a non-admin cannot
    core.RATE_LIMITS["staff_accept"] = (1000, 3600)
    body = {"business_name": "E2E Store", "full_name": "Owner Name", "mobile": "9199001101", "email": "owner.e2e@example.test"}
    assert c.post("/api/admin/vendors/create", json=body).status_code in (401, 403)
    made = c.post("/api/admin/vendors/create", headers=fin2, json=body)
    assert made.status_code == 200 and made.json()["status"] == "draft"
    vid = made.json()["vendor_id"]
    S["vid"] = vid
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": made.json()["invitation"]["token"], "password": OWNER_PW}).status_code == 200
    owner = _login(c, "owner.e2e@example.test", OWNER_PW)
    S["owner"] = owner

    # 2. a draft vendor cannot sell; onboarding works; submitting moves to submitted
    assert c.get("/api/vendor/products", headers=owner).status_code == 403
    assert c.put("/api/vendor/me", headers=owner, json={**PROFILE, "submit": False}).json()["vendor"]["status"] == "draft"
    assert c.put("/api/vendor/me", headers=owner, json={**PROFILE, "submit": True}).json()["vendor"]["status"] == "submitted"
    # the owner's own status cannot be set by request body
    assert c.put("/api/vendor/me", headers=owner, json={**PROFILE, "status": "active", "submit": False}).status_code == 409   # locked while under review

    # 3. documents are submitted; corrections are requested; the owner resubmits; the documents are reviewed
    doc = c.post("/api/vendor/documents", headers=owner, json={"type": "pan", "url": "https://cdn.example.com/pan.pdf"})
    assert doc.status_code == 200, doc.text
    doc_id = doc.json().get("id") or doc.json().get("document", {}).get("id")
    assert c.post(f"/api/admin/vendor-documents/{doc_id}/review", headers=fin2, json={"status": "verified"}).status_code == 200
    assert c.post(f"/api/admin/vendors/{vid}/decision", headers=fin2, json={"action": "request_changes", "reason": "Bank proof is unclear"}).status_code == 200
    assert c.put("/api/vendor/me", headers=owner, json={**PROFILE, "address": "14 Market Road, Jaipur", "submit": True}).json()["vendor"]["status"] == "submitted"

    # 4. activation only after approval; the vendor cannot approve or activate itself
    assert c.post("/api/vendor/finance/terms/x/accept", headers=owner).status_code in (403, 404)
    assert c.post(f"/api/admin/vendors/{vid}/decision", headers=owner, json={"action": "approve"}).status_code == 403
    assert c.post(f"/api/admin/vendors/{vid}/decision", headers=fin2, json={"action": "activate"}).status_code == 400          # not approved yet
    assert c.post(f"/api/admin/vendors/{vid}/decision", headers=fin2, json={"action": "start_review"}).status_code == 200
    assert c.post(f"/api/admin/vendors/{vid}/decision", headers=fin2, json={"action": "approve"}).status_code == 200
    assert c.post(f"/api/admin/vendors/{vid}/decision", headers=fin2, json={"action": "activate"}).status_code == 200
    assert c.get("/api/vendor/products", headers=owner).status_code == 200                       # active vendors can sell

    # 5. staff: invite, accept, scoped access, revoke
    inv = c.post("/api/vendor/staff/invitations", headers=owner, json={"mobile": "9199001102", "full_name": "Staff Member", "role": "store_manager"}).json()
    assert c.post("/api/vendor/staff/accept", json={"token": inv["token"], "mobile": "9199001102", "full_name": "Staff Member", "password": STAFF_PW}).status_code == 200
    staff = _login(c, "9199001102", STAFF_PW)
    assert c.get("/api/vendor/products", headers=staff).status_code == 200
    assert c.get("/api/vendor/finance/summary", headers=staff).status_code == 403                 # store manager: no finance
    assert c.post("/api/vendor/staff/invitations", headers=staff, json={"mobile": "9199001103", "full_name": "Escalate", "role": "owner"}).status_code == 403
    member = c.get("/api/vendor/staff", headers=owner).json()["staff"][0]["id"]

    # 6. products and stock (owner), with product approval by admin
    prod = c.post("/api/vendor/products", headers=owner, json={"sku": "E2E-1", "name": "E2E Saree", "mrp": 1200, "selling_price": 1000,
                                                              "category": "Sarees", "stock": 10}).json()
    assert c.post(f"/api/admin/vendor-products/{prod['id']}/decision", headers=fin2, json={"action": "approve"}).status_code == 200
    assert c.post(f"/api/vendor/products/{prod['id']}/stock", headers=owner, json={"delta": -50, "reason": "Recount"}).status_code == 400
    assert c.post(f"/api/vendor/products/{prod['id']}/stock", headers=owner, json={"delta": 2, "reason": "Delivery"}).status_code == 200
    S["pid"] = prod["id"]

    # 7. staff revoked: the very next request is refused
    assert c.delete(f"/api/vendor/staff/{member}", headers=owner).status_code == 200
    assert c.get("/api/vendor/products", headers=staff).status_code == 403

    # 8. orders: the owner fulfils a permitted order through each step
    order = _paid_order(vid, prod["id"], 100000)
    c.portal.call(lambda: db.orders.insert_one(dict(order)))
    c.portal.call(lambda: L.post_order_collected(order))                     # the sale, as checkout would post it
    url = f"/api/vendor/orders/{order['id']}/fulfilment"
    assert c.post(url, headers=owner, json={"status": "accepted", "note": "Accepted"}).status_code == 200
    assert c.post(url, headers=owner, json={"status": "packed", "note": "Packed"}).status_code == 200
    assert c.post(url, headers=owner, json={"status": "dispatched", "note": "Sent", "carrier": "Bluedart", "tracking_number": "BD778"}).status_code == 200
    assert c.post(url, headers=owner, json={"status": "delivered", "note": "Delivered"}).status_code == 200
    S["order"] = order

    # 9. reports reconcile with the ledger and the dashboard
    rep = c.get("/api/vendor/reports/current", headers=owner, params={"range": "30d"}).json()
    dash = c.get("/api/vendor/dashboard", headers=owner, params={"range": "30d"}).json()
    assert rep["sales"]["order_value_paise"] == dash["sales"]["order_value_paise"] == 100000
    sale_entries = c.portal.call(lambda: db.vendor_ledger.find({"vendor_id": vid, "type": "SALE_COLLECTED"}, {"_id": 0, "amount_paise": 1}).to_list(100))
    assert rep["earnings"]["sales_paise"] == sum(e["amount_paise"] for e in sale_entries) == 100000
    assert rep["dispatch"]["dispatched_orders"] == 1 and rep["dispatch"]["average_hours_to_dispatch"] is not None
    assert rep["stock_movements"]["added"] == 12                                   # 10 opening stock + 2 delivered; both are movements
    assert rep["commission"]["available"] is False                                 # no agreement yet

    # 10. commercial terms: a version is approved by a different admin, applies to later sales, and is accepted by the vendor
    ag = c.post(f"/api/admin/finance/vendors/{vid}/agreements", headers=fin1,
                json={"commission_pct": 2.0, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": datetime.now(timezone.utc).date().isoformat()}).json()
    assert c.post(f"/api/admin/finance/agreements/{ag['id']}/approve", headers=fin1).status_code == 403
    assert c.post(f"/api/admin/finance/agreements/{ag['id']}/approve", headers=fin2).status_code == 200
    terms = c.get("/api/vendor/finance/terms", headers=owner).json()
    assert terms["current"]["version"] == 1 and "approved_by" not in str(terms)
    assert c.post(f"/api/vendor/finance/terms/{ag['id']}/accept", headers=owner).status_code == 200
    later = _paid_order(vid, prod["id"], 50000)
    c.portal.call(lambda: db.orders.insert_one(dict(later)))
    c.portal.call(lambda: L.post_order_collected(later))
    commissions = c.portal.call(lambda: db.vendor_ledger.find({"vendor_id": vid, "type": "COMMISSION"}, {"_id": 0, "amount_paise": 1}).to_list(10))
    assert sum(e["amount_paise"] for e in commissions) == -1000                      # 2% of 50,000 paise

    # 11. settlement: request, approve by another admin, pay by a third step with a reference; no double payout
    st = c.post("/api/admin/finance/settlements", headers=fin1, json={"vendor_id": vid, "amount": 100.0, "note": "Monthly"})
    assert st.status_code == 200, st.text
    sid = st.json()["id"]
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=fin1, json={"action": "approve", "note": "ok"}).status_code == 403
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=fin2, json={"action": "approve", "note": "ok"}).status_code == 200
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=fin1, json={"action": "mark_paid", "reference": "UTRE2E001", "note": "paid"}).status_code == 200
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=fin1, json={"action": "mark_paid", "reference": "UTRE2E002", "note": "again"}).status_code == 400
    assert c.post(f"/api/vendor/finance/settlements/{sid}/action", headers=owner, json={"action": "mark_paid"}).status_code in (403, 404, 405)
    summ = c.get("/api/vendor/finance/summary", headers=owner).json()["balances"]
    assert summ["settled_paise"] == 10000
    assert summ["pending_settlement_paise"] == summ["vendor_payable_paise"] - summ["settled_paise"]
    assert summ["eligible_sales_paise"] == 150000 and summ["commissions_paise"] == -1000
    assert summ["vendor_payable_paise"] == 150000 - 1000                              # sales less commission, before payouts
    rows = c.get("/api/vendor/finance/settlements", headers=owner).json()["items"]
    assert rows[0]["status"] == "paid" and rows[0]["reference"] == "UTRE2E001"

    # 12. advancement: a programme, a proposal by one admin, approval by another, and no money moved by the approval
    prog = c.post("/api/admin/benefits/programmes", headers=fin2, json={"key": "e2e_orders", "title": "Steady orders", "review_days": 30,
                                                                       "benefit_text": "Listing priority review", "criteria": [{"metric": "orders", "value": 1}]}).json()
    before = c.portal.call(lambda: db.vendor_ledger.count_documents({"vendor_id": vid}))
    g = c.post("/api/admin/benefits/proposals", headers=fin1, json={"vendor_id": vid, "programme_id": prog["id"]}).json()
    assert g["evaluation"]["eligible"] is True
    assert c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=fin1, json={"action": "approve"}).status_code == 403
    assert c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=fin2, json={"action": "approve"}).status_code == 200
    assert c.portal.call(lambda: db.vendor_ledger.count_documents({"vendor_id": vid})) == before
    assert c.get("/api/vendor/advancement/eligibility", headers=owner).json()["benefits"][0]["status"] == "approved"


def test_security_boundaries_hold_across_the_lifecycle(c):
    owner = S["owner"]
    vid = S["vid"]
    other = c.post("/api/admin/vendors/create", headers=_hdr(S["fin2"]["id"]),
                   json={"business_name": "Other E2E", "full_name": "Other Owner", "mobile": "9199001150", "email": "other.e2e@example.test"}).json()
    c.post("/api/vendor/invitation/owner/accept", json={"token": other["invitation"]["token"], "password": OWNER_PW})
    other_owner = _login(c, "other.e2e@example.test", OWNER_PW)
    c.put("/api/vendor/me", headers=other_owner, json={**PROFILE, "business_name": "Other E2E", "submit": True})
    c.post(f"/api/admin/vendors/{other['vendor_id']}/decision", headers=_hdr(S["fin2"]["id"]), json={"action": "start_review"})
    assert c.post(f"/api/admin/vendors/{other['vendor_id']}/decision", headers=_hdr(S["fin2"]["id"]), json={"action": "approve"}).status_code == 200
    assert c.get("/api/vendor/products", headers=other_owner).status_code == 200  # approved: now ownership, not the approval gate, decides
    assert c.get(f"/api/vendor/products/{S['pid']}/stock-history", headers=other_owner).status_code == 404
    assert all(o["id"] != S["order"]["id"] for o in c.get("/api/vendor/orders", headers=other_owner).json())
    assert c.get("/api/vendor/reports/current.csv", headers=other_owner, params={"range": "30d"}).text.count("E2E Saree") == 0
    assert c.post(f"/api/admin/finance/vendors/{vid}/adjustments", headers=owner, json={"amount": 500, "reason": "Credit me"}).status_code == 403
    assert c.post("/api/admin/finance/settlements", headers=owner, json={"vendor_id": vid, "amount": 1.0}).status_code == 403
    assert c.get("/api/admin/refund-cases", headers=owner).status_code == 403
    assert c.get("/api/admin/vendors", headers=owner).status_code == 403
    customer = c.portal.call(lambda: db.users.find_one({"role": "distributor"}, {"_id": 0}))
    assert c.get("/api/vendor/me", headers=_hdr(customer["id"])).status_code == 403
    assert c.post("/api/admin/vendors/create", headers=_hdr(customer["id"]), json={"business_name": "Nope", "full_name": "No One", "mobile": "9199001199"}).status_code in (401, 403)
    assert c.post("/api/auth/login", json={"email": "owner.e2e@example.test", "password": "wrong-password"}).status_code == 401
    me = c.get("/api/vendor/me", headers=owner).text
    assert "password" not in me.lower() and "111122223333" not in me                    # bank account is masked
    admin_list = c.get("/api/admin/vendors", headers=_hdr(S["fin2"]["id"])).text
    assert "password_hash" not in admin_list and OWNER_PW not in admin_list
    assert other["vendor_id"] != vid


def test_returns_workflow_end_to_end(c):
    """A customer returns a delivered item: vendor approves, customer ships back, vendor receives and inspects, stock is restored
    once, a refund case is raised for the vendor's share, and the vendor cannot refund."""
    customer = c.portal.call(lambda: db.users.find_one({"role": "distributor"}, {"_id": 0}))
    vid, pid = S["vid"], S["pid"]
    order = _paid_order(vid, pid, 80000)
    delivered_at = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    order.update({"user_id": customer["id"], "status": "delivered",
                  "fulfilments": [{"vendor_id": vid, "status": "delivered", "events": [{"status": "delivered", "at": delivered_at, "by": "vendor", "note": "Delivered"}]}]})
    c.portal.call(lambda: db.orders.insert_one(dict(order)))
    c.portal.call(lambda: L.post_order_collected(order))
    stock_before = c.portal.call(lambda: db.products.find_one({"id": pid}, {"_id": 0, "stock": 1}))["stock"]
    cust = {"Authorization": f"Bearer {create_token(customer['id'])}"}

    req = c.post(f"/api/orders/{order['id']}/returns", headers=cust,
                 json={"kind": "return", "items": [{"product_id": pid, "quantity": 1}], "reason": "Damaged on arrival", "photos": []})
    assert req.status_code == 200, req.text
    rid = req.json()["cases"][0]["id"]
    owner = S["owner"]
    assert c.post(f"/api/vendor/returns/{rid}/action", headers=owner, json={"action": "refund", "note": "Refund it now"}).status_code == 400   # no vendor refunds
    assert c.post(f"/api/vendor/returns/{rid}/action", headers=owner, json={"action": "approve", "note": "Please send it back"}).status_code == 200
    assert c.post(f"/api/returns/{rid}/ship", headers=cust, json={"carrier": "DTDC", "tracking_number": "RET778"}).status_code == 200
    assert c.post(f"/api/vendor/returns/{rid}/action", headers=owner, json={"action": "receive", "note": "Received"}).status_code == 200
    assert c.post(f"/api/vendor/returns/{rid}/inspection", headers=owner,
                  json={"lines": [{"index": 0, "outcome": "resellable"}], "note": "Unopened"}).status_code == 200
    c.portal.call(returns_routes.reconcile_returns)                                            # the sweep that raises the refund case
    stock_after = c.portal.call(lambda: db.products.find_one({"id": pid}, {"_id": 0, "stock": 1}))["stock"]
    assert stock_after == stock_before + 1                                                     # restocked once, resellable only
    assert c.post(f"/api/vendor/returns/{rid}/inspection", headers=owner,
                  json={"lines": [{"index": 0, "outcome": "resellable"}], "note": "Again"}).status_code == 409   # not twice
    case = c.portal.call(lambda: db.return_cases.find_one({"id": rid}, {"_id": 0}))
    assert case["status"] == "refund_pending" and case["vendor_id"] == vid
    refund = c.portal.call(lambda: db.refund_cases.find_one({"return_case_id": rid}, {"_id": 0}))
    assert refund is not None and refund["amount_paise"] > 0 and refund["vendor_id"] == vid
    assert c.post(f"/api/admin/refund-cases/{refund['id']}/action", headers=owner, json={"action": "confirm", "note": "x", "reference": "UTRRET1"}).status_code == 403
