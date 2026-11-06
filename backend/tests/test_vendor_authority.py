"""Vendor V1.1: who may run the vendor lifecycle (OWNER-APPROVED authority model).

super_admin and admin: create vendors, invite owners, approve/reject/suspend/reinstate, decide products, review documents,
change the document policy. support_admin and accounts_admin are refused all of these (read access stays). accounts_admin keeps
its finance functions (agreements, bank-change approval, settlement policy). A vendor's product cannot be edited, re-listed or
permanently deleted from the general admin catalogue routes; only super_admin/admin may take it down there.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`).
"""
import os
from datetime import date, timedelta

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_authority_test", "JWT_SECRET": "vendor-authority-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
for k in ("WEBHOOK_CRON_SECRET", "ADMIN_EMAIL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_UPLOAD_PRESET"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
ADMINS = {"super": "super_admin", "admin": "admin", "fin": "accounts_admin", "support": "support_admin"}
REFUSED = ("fin", "support")
ALLOWED = ("super", "admin")
_seq = iter(range(100, 10_000))


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
            for i, (key, role) in enumerate(ADMINS.items()):
                u = {"id": new_id(), "distributor_id": f"VA{i:04d}", "full_name": key, "mobile": f"91000062{i:02d}", "email": None,
                     "password_hash": hash_password("Admin-Pass-123"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _vendor(c, status="submitted", owner_status="active"):
    """A vendor (and its owner account) seeded directly in the given status."""
    n = next(_seq)
    async def go():
        u = {"id": new_id(), "distributor_id": f"VD9{n:05d}", "full_name": f"Owner {n}", "mobile": f"98{n:08d}", "email": None,
             "password_hash": hash_password("Owner-Pass-123"), "role": "vendor", "status": "green", "account_status": owner_status,
             "created_at": now_iso(), "updated_at": now_iso()}
        v = {"id": new_id(), "user_id": u["id"], "vendor_code": f"VD9{n:05d}", "business_name": f"Store {n}", "status": status,
             "categories": ["Sarees"], "bank_account": "111122223333", "bank_account_name": f"Store {n}", "ifsc": "SBIN0000001",
             "created_at": now_iso(), "updated_at": now_iso()}
        await db.users.insert_one(dict(u))
        await db.vendors.insert_one(dict(v))
        return v
    return _run(c, go)


def _product(c, vendor_id, approval="pending", active=False):
    n = next(_seq)
    async def go():
        p = {"id": new_id(), "sku": f"VA-SKU-{n}", "name": f"Saree {n}", "vendor_id": vendor_id, "vendor_name": "Store",
             "category": "Sarees", "mrp": 1000, "selling_price": 900, "gst_percent": 5, "stock": 5, "low_stock_threshold": 5,
             "is_active": active, "approval_status": approval, "archived": False, "created_at": now_iso(), "updated_at": now_iso()}
        await db.products.insert_one(dict(p))
        return p
    return _run(c, go)


def _status(c, vid):
    return _run(c, lambda: db.vendors.find_one({"id": vid}, {"_id": 0, "status": 1}))["status"]


def _distributor(c, status="red"):
    n = next(_seq)
    async def go():
        u = {"id": new_id(), "distributor_id": f"HGA{n:05d}", "full_name": f"User {n}", "mobile": f"97{n:08d}", "email": None,
             "password_hash": hash_password("User-Pass-123"), "role": "distributor", "status": status, "account_status": "active",
             "created_at": now_iso(), "updated_at": now_iso()}
        await db.users.insert_one(dict(u))
        return u
    return _run(c, go)


# ================================================================ create / invite
@pytest.mark.parametrize("who", REFUSED)
def test_support_and_accounts_cannot_create_vendors(c, who):
    n = next(_seq)
    r = c.post("/api/admin/vendors/create", headers=_hdr(who), json={"business_name": f"New {n}", "full_name": "Owner Name", "mobile": f"96{n:08d}"})
    assert r.status_code == 403, r.text
    assert _run(c, lambda: db.users.find_one({"mobile": f"96{n:08d}"})) is None
    assert _run(c, lambda: db.vendors.find_one({"business_name": f"New {n}"})) is None


@pytest.mark.parametrize("who", ALLOWED)
def test_admin_and_super_admin_create_vendors(c, who):
    n = next(_seq)
    r = c.post("/api/admin/vendors/create", headers=_hdr(who), json={"business_name": f"New {n}", "full_name": "Owner Name", "mobile": f"96{n:08d}"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "onboarding" and "invitation" not in r.json()      # no login until a super admin approves


@pytest.mark.parametrize("who", ALLOWED)
def test_no_one_can_convert_an_existing_account_into_a_vendor(c, who):
    for status in ("red", "green"):
        u = _distributor(c, status=status)
        before = _run(c, lambda: db.users.find_one({"id": u["id"]}, {"_id": 0}))
        r = c.post("/api/admin/vendors/invite", headers=_hdr(who), json={"identifier": u["distributor_id"]})
        assert r.status_code == 410, r.text
        assert _run(c, lambda: db.users.find_one({"id": u["id"]}, {"_id": 0})) == before
        assert _run(c, lambda: db.vendors.find_one({"user_id": u["id"]})) is None


@pytest.mark.parametrize("who", REFUSED)
def test_support_and_accounts_cannot_grant_the_vendor_role(c, who):
    u = _distributor(c)
    r = c.post("/api/admin/vendors/invite", headers=_hdr(who), json={"identifier": u["distributor_id"]})
    assert r.status_code == 403, r.text
    assert _run(c, lambda: db.users.find_one({"id": u["id"]}, {"_id": 0, "role": 1}))["role"] == "distributor"


@pytest.mark.parametrize("who", REFUSED)
def test_support_and_accounts_cannot_issue_or_revoke_owner_invitations(c, who):
    v = _vendor(c, status="draft", owner_status="invited")
    assert c.post(f"/api/admin/vendors/{v['id']}/owner-invitation", headers=_hdr(who)).status_code == 403
    assert c.post(f"/api/admin/vendors/{v['id']}/owner-invitation/revoke", headers=_hdr(who)).status_code == 403
    assert _run(c, lambda: db.account_invitations.count_documents({"vendor_id": v["id"]})) == 0
    assert c.get(f"/api/admin/vendors/{v['id']}/owner-invitation", headers=_hdr(who)).status_code == 200    # status is still readable


def test_only_super_admin_issues_the_owner_invitation_and_only_after_approval(c):
    pending = _vendor(c, status="onboarding", owner_status="pending_approval")
    assert c.post(f"/api/admin/vendors/{pending['id']}/owner-invitation", headers=_hdr("super")).status_code == 400   # not approved yet
    v = _vendor(c, status="approved", owner_status="pending_approval")
    assert c.post(f"/api/admin/vendors/{v['id']}/owner-invitation", headers=_hdr("admin")).status_code == 403       # admin cannot activate
    assert c.post(f"/api/admin/vendors/{v['id']}/owner-invitation", headers=_hdr("super")).status_code == 200


@pytest.mark.parametrize("who", ALLOWED)
def test_admin_and_super_admin_revoke_owner_invitations(c, who):
    v = _vendor(c, status="approved", owner_status="pending_approval")
    assert c.post(f"/api/admin/vendors/{v['id']}/owner-invitation", headers=_hdr("super")).status_code == 200
    r = c.post(f"/api/admin/vendors/{v['id']}/owner-invitation/revoke", headers=_hdr(who))
    assert r.status_code == 200 and r.json()["revoked"] == 1


# ================================================================ lifecycle decisions
ADMIN_DECISIONS = [("submitted", "start_review", "under_review"), ("submitted", "request_changes", "changes_requested"),
                   ("approved", "suspend", "suspended"), ("draft", "request_documents", "pending_documents")]
FINAL_DECISIONS = [("submitted", "approve", "approved"), ("submitted", "reject", "rejected"), ("suspended", "reinstate", "approved"),
                   ("approved", "activate", "active")]                     # owner-locked: super_admin only
DECISIONS = ADMIN_DECISIONS + FINAL_DECISIONS


@pytest.mark.parametrize("who", REFUSED)
@pytest.mark.parametrize("frm,action,to", DECISIONS)
def test_support_and_accounts_cannot_decide_vendor_status(c, who, frm, action, to):
    v = _vendor(c, status=frm)
    r = c.post(f"/api/admin/vendors/{v['id']}/decision", headers=_hdr(who), json={"action": action, "reason": "A valid reason here"})
    assert r.status_code == 403, r.text
    assert _status(c, v["id"]) == frm
    assert _run(c, lambda: db.vendor_status_history.count_documents({"vendor_id": v["id"]})) == 0


@pytest.mark.parametrize("frm,action,to", FINAL_DECISIONS)
def test_admin_cannot_make_final_decisions(c, frm, action, to):
    v = _vendor(c, status=frm)
    r = c.post(f"/api/admin/vendors/{v['id']}/decision", headers=_hdr("admin"), json={"action": action, "reason": "A valid reason here"})
    assert r.status_code == 403, r.text
    assert _status(c, v["id"]) == frm
    assert _run(c, lambda: db.vendor_status_history.count_documents({"vendor_id": v["id"]})) == 0


@pytest.mark.parametrize("frm,action,to", FINAL_DECISIONS)
def test_super_admin_makes_final_decisions(c, frm, action, to):
    v = _vendor(c, status=frm)
    r = c.post(f"/api/admin/vendors/{v['id']}/decision", headers=_hdr("super"), json={"action": action, "reason": "A valid reason here"})
    assert r.status_code == 200, r.text
    assert _status(c, v["id"]) == to


@pytest.mark.parametrize("who", ALLOWED)
@pytest.mark.parametrize("frm,action,to", ADMIN_DECISIONS)
def test_admin_and_super_admin_decide_vendor_status(c, who, frm, action, to):
    v = _vendor(c, status=frm)
    r = c.post(f"/api/admin/vendors/{v['id']}/decision", headers=_hdr(who), json={"action": action, "reason": "A valid reason here"})
    assert r.status_code == 200, r.text
    assert _status(c, v["id"]) == to


# ================================================================ product decisions
@pytest.mark.parametrize("who", REFUSED)
@pytest.mark.parametrize("action", ("approve", "reject"))
def test_support_and_accounts_cannot_decide_vendor_products(c, who, action):
    v = _vendor(c, status="approved")
    p = _product(c, v["id"])
    r = c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=_hdr(who), json={"action": action, "reason": "Image is blurred"})
    assert r.status_code == 403, r.text
    after = _run(c, lambda: db.products.find_one({"id": p["id"]}, {"_id": 0, "approval_status": 1, "is_active": 1}))
    assert after == {"approval_status": "pending", "is_active": False}


@pytest.mark.parametrize("who", ALLOWED)
def test_admin_and_super_admin_decide_vendor_products(c, who):
    v = _vendor(c, status="approved")
    p1, p2 = _product(c, v["id"]), _product(c, v["id"])
    assert c.post(f"/api/admin/vendor-products/{p1['id']}/decision", headers=_hdr(who), json={"action": "approve"}).status_code == 200
    assert c.post(f"/api/admin/vendor-products/{p2['id']}/decision", headers=_hdr(who), json={"action": "reject", "reason": "Image is blurred"}).status_code == 200
    got = {x["id"]: x["approval_status"] for x in _run(c, lambda: db.products.find({"id": {"$in": [p1["id"], p2["id"]]}}, {"_id": 0}).to_list(5))}
    assert got == {p1["id"]: "approved", p2["id"]: "rejected"}


# ================================================================ documents and policy
def _document(c, vid):
    async def go():
        d = {"id": new_id(), "vendor_id": vid, "type": "pan", "status": "pending", "url": "https://res.cloudinary.com/x/doc.png",
             "created_at": now_iso()}
        await db.vendor_documents.insert_one(dict(d))
        return d
    return _run(c, go)


def test_accounts_admin_cannot_review_documents(c):
    who = "fin"
    v = _vendor(c)
    d = _document(c, v["id"])
    r = c.post(f"/api/admin/vendor-documents/{d['id']}/review", headers=_hdr(who), json={"status": "verified"})
    assert r.status_code == 403, r.text
    assert _run(c, lambda: db.vendor_documents.find_one({"id": d["id"]}, {"_id": 0, "status": 1}))["status"] == "pending"
    assert c.get(f"/api/admin/vendors/{v['id']}/documents", headers=_hdr(who)).status_code == 200      # still readable


@pytest.mark.parametrize("who", ("super", "admin", "support"))   # support keeps review pending an owner decision
def test_admin_super_admin_and_support_review_documents(c, who):
    v = _vendor(c)
    d = _document(c, v["id"])
    assert c.post(f"/api/admin/vendor-documents/{d['id']}/review", headers=_hdr(who), json={"status": "verified"}).status_code == 200


@pytest.mark.parametrize("who", REFUSED)
def test_support_and_accounts_cannot_change_the_document_policy(c, who):
    before = _run(c, lambda: db.vendor_policy.find_one({"id": "vendor_policy"}, {"_id": 0}))
    assert c.put("/api/admin/vendor-policy", headers=_hdr(who), json={"required_documents": ["pan"]}).status_code == 403
    assert _run(c, lambda: db.vendor_policy.find_one({"id": "vendor_policy"}, {"_id": 0})) == before


@pytest.mark.parametrize("who", ALLOWED)
def test_admin_and_super_admin_change_the_document_policy(c, who):
    r = c.put("/api/admin/vendor-policy", headers=_hdr(who), json={"required_documents": []})
    assert r.status_code == 200, r.text


# ================================================================ read access is unchanged
@pytest.mark.parametrize("who", list(ADMINS))
def test_every_admin_role_can_still_read_vendors(c, who):
    v = _vendor(c)
    assert c.get("/api/admin/vendors", headers=_hdr(who)).status_code == 200
    assert c.get(f"/api/admin/vendors/{v['id']}/history", headers=_hdr(who)).status_code == 200
    assert c.get("/api/admin/vendor-products?status=all", headers=_hdr(who)).status_code == 200


# ================================================================ general catalogue routes cannot bypass vendor control
@pytest.mark.parametrize("who", list(ADMINS))
def test_no_admin_can_edit_or_relist_a_vendor_product_from_the_catalogue_screen(c, who):
    v = _vendor(c, status="suspended")
    p = _product(c, v["id"], approval="approved", active=False)
    body = {"sku": p["sku"], "name": "Changed", "mrp": 1000, "selling_price": 1, "stock": 5, "category": "Sarees", "is_active": True}
    r = c.put(f"/api/admin/products/{p['id']}", headers=_hdr(who), json=body)
    assert r.status_code == 409, r.text
    after = _run(c, lambda: db.products.find_one({"id": p["id"]}, {"_id": 0, "name": 1, "selling_price": 1, "is_active": 1}))
    assert after == {"name": p["name"], "selling_price": 900, "is_active": False}


@pytest.mark.parametrize("who", list(ADMINS))
def test_no_admin_can_permanently_delete_a_vendor_product(c, who):
    v = _vendor(c, status="approved")
    p = _product(c, v["id"], approval="approved", active=True)
    assert c.delete(f"/api/admin/products/{p['id']}/permanent", headers=_hdr(who)).status_code == 409
    assert _run(c, lambda: db.products.find_one({"id": p["id"]}, {"_id": 1})) is not None


@pytest.mark.parametrize("who", REFUSED)
def test_support_and_accounts_cannot_take_down_a_vendor_product(c, who):
    v = _vendor(c, status="approved")
    p = _product(c, v["id"], approval="approved", active=True)
    assert c.delete(f"/api/admin/products/{p['id']}", headers=_hdr(who)).status_code == 403
    assert _run(c, lambda: db.products.find_one({"id": p["id"]}, {"_id": 0, "is_active": 1}))["is_active"] is True


@pytest.mark.parametrize("who", ALLOWED)
def test_admin_and_super_admin_can_take_down_a_vendor_product(c, who):
    v = _vendor(c, status="approved")
    p = _product(c, v["id"], approval="approved", active=True)
    assert c.delete(f"/api/admin/products/{p['id']}", headers=_hdr(who)).status_code == 200
    assert _run(c, lambda: db.products.find_one({"id": p["id"]}, {"_id": 0, "is_active": 1}))["is_active"] is False


def test_company_products_are_unchanged_by_the_vendor_rules(c):
    body = {"sku": f"HG-OWN-{next(_seq)}", "name": "Own Detergent", "mrp": 200, "selling_price": 180, "stock": 10,
            "category": "Household Essentials", "is_active": True}
    r = c.post("/api/admin/products", headers=_hdr("admin"), json=body)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    assert c.put(f"/api/admin/products/{pid}", headers=_hdr("admin"), json={**body, "selling_price": 170}).status_code == 200
    assert c.delete(f"/api/admin/products/{pid}", headers=_hdr("admin")).status_code == 200
    assert c.delete(f"/api/admin/products/{pid}/permanent", headers=_hdr("admin")).status_code == 200


# ================================================================ accounts_admin finance functions still work
def test_accounts_admin_keeps_agreements_bank_approval_and_settlement_policy(c):
    v = _vendor(c, status="approved")
    eff = (date.today() + timedelta(days=3)).isoformat()
    r = c.post(f"/api/admin/finance/vendors/{v['id']}/agreements", headers=_hdr("fin"),
               json={"commission_pct": 10, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": eff})
    assert r.status_code == 200, r.text
    assert c.post(f"/api/admin/finance/agreements/{r.json()['id']}/approve", headers=_hdr("super")).status_code == 200

    async def bank_request():
        rq = {"id": new_id(), "vendor_id": v["id"], "kind": "bank", "payload": {"bank_account_name": "Store", "bank_account": "999988887777",
              "ifsc": "HDFC0000001"}, "reason": "Moved bank", "status": "pending", "admin_note": "", "created_at": now_iso()}
        await db.vendor_change_requests.insert_one(dict(rq))
        return rq
    rq = _run(c, bank_request)
    assert c.post(f"/api/admin/vendor-change-requests/{rq['id']}/decision", headers=_hdr("fin"), json={"decision": "approve"}).status_code == 200
    assert _run(c, lambda: db.vendors.find_one({"id": v["id"]}, {"_id": 0, "ifsc": 1}))["ifsc"] == "HDFC0000001"

    r = c.put("/api/admin/finance/policy", headers=_hdr("fin"), json={"active": False, "require_dual_approval": True})
    assert r.status_code == 200, r.text
    assert c.get(f"/api/admin/finance/vendors/{v['id']}/ledger", headers=_hdr("fin")).status_code == 200


def test_support_admin_still_cannot_use_finance_functions(c):
    v = _vendor(c, status="approved")
    eff = (date.today() + timedelta(days=3)).isoformat()
    r = c.post(f"/api/admin/finance/vendors/{v['id']}/agreements", headers=_hdr("support"),
               json={"commission_pct": 10, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": eff})
    assert r.status_code == 403
