"""Vendor staff management (Phase 4): invitations, acceptance, roles, suspension, revocation, and vendor isolation.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_vendor_staff.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_staff_test", "JWT_SECRET": "vendor-staff-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
import core  # noqa: E402

PW = "Vendor-Pass-123"
STAFF_PW = "Staff-Pass-456"
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _tok(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        core.RATE_LIMITS["staff_accept"] = (1000, 3600)     # many acceptances in one run; the limiter is tested separately
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()      # the migration step: startup no longer creates indexes

            async def user(mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password(PW), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name, code):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": code, "business_name": name, "status": "approved",
                     "categories": ["Sarees"], "bank_account": "111122223333", "bank_account_name": name, "ifsc": "SBIN0000001",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            S["adm"] = await user("9100001001", "super_admin", "SADM")
            S["cust"] = await user("9100001002", "distributor", "SCUS")
            S["ua"] = await user("9100001003", "vendor", "SVA")
            S["va"] = await vendor(S["ua"], "Staff Store A", "VS000001")
            S["ub"] = await user("9100001004", "vendor", "SVB")
            S["vb"] = await vendor(S["ub"], "Staff Store B", "VS000002")
            base = {"status": "draft", "stock": 5, "low_stock_threshold": 5, "is_active": True, "approval_status": "approved", "archived": False,
                    "category": "Sarees", "created_at": now_iso(), "updated_at": now_iso()}
            S["pa"] = new_id()
            S["pb"] = new_id()
            await db.products.insert_many([{**base, "id": S["pa"], "vendor_id": S["va"]["id"], "name": "Store A Saree", "sku": "SA-1"},
                                           {**base, "id": S["pb"], "vendor_id": S["vb"]["id"], "name": "Store B Saree", "sku": "SB-1"}])
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _invite(c, who, mobile, role="store_manager", perms=None, name="Team Member"):
    body = {"mobile": mobile, "full_name": name, "role": role}
    if perms is not None:
        body["permissions"] = perms
    r = c.post("/api/vendor/staff/invitations", headers=_hdr(S[who]["id"]), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _accept(c, token, mobile, name="Team Member", password=STAFF_PW):
    return c.post("/api/vendor/staff/accept", json={"token": token, "mobile": mobile, "full_name": name, "password": password})


def _member_id(c, mobile):
    return c.portal.call(lambda: db.vendor_members.find_one({"mobile": mobile}, {"_id": 0, "id": 1}))["id"]


def _staff_login(c, mobile):
    r = c.post("/api/auth/login", json={"email": mobile, "password": STAFF_PW})
    assert r.status_code == 200, r.text
    return _tok(r.json()["token"])


def _joined(c, mobile, role="store_manager", perms=None):
    inv = _invite(c, "ua", mobile, role, perms)
    assert _accept(c, inv["token"], mobile).status_code == 200
    return _staff_login(c, mobile), _member_id(c, mobile)


# ====================================================================== invitations
def test_invitation_is_secret_single_use_and_expires(c):
    mobile = "9100001101"
    inv = _invite(c, "ua", mobile)
    info = c.get("/api/vendor/staff/invitation", params={"token": inv["token"]})
    assert info.status_code == 200 and info.json()["business_name"] == "Staff Store A" and info.json()["mobile_hint"].endswith("1101")
    assert c.get("/api/vendor/staff/invitation", params={"token": "not-a-real-token"}).status_code == 400
    assert _accept(c, inv["token"], "9100001199").status_code == 400                     # wrong mobile: same generic answer
    assert _accept(c, inv["token"], mobile, password="nopassword").status_code == 400     # password rule
    assert _accept(c, inv["token"], mobile).status_code == 200
    assert _accept(c, inv["token"], mobile).status_code == 400                           # single use
    stored = c.portal.call(lambda: db.vendor_members.find_one({"mobile": mobile}, {"_id": 0}))
    assert stored["token_hash"] is None and stored["status"] == "active" and inv["token"] not in str(stored)  # only a hash is stored
    user = c.portal.call(lambda: db.users.find_one({"mobile": mobile}, {"_id": 0}))
    assert user["role"] == "vendor_staff" and user["password_hash"] != STAFF_PW


def test_an_expired_invitation_cannot_be_accepted_and_resend_voids_the_old_link(c):
    mobile = "9100001102"
    old = _invite(c, "ua", mobile)
    c.portal.call(lambda: db.vendor_members.update_one({"mobile": mobile}, {"$set": {"invite_expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}}))
    assert _accept(c, old["token"], mobile).status_code == 400
    c.portal.call(lambda: db.vendor_members.update_one({"mobile": mobile}, {"$set": {"invite_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}}))
    resent = c.post(f"/api/vendor/staff/{_member_id(c, mobile)}/resend", headers=_hdr(S["ua"]["id"])).json()
    assert _accept(c, old["token"], mobile).status_code == 400                           # the old link is dead
    assert _accept(c, resent["token"], mobile).status_code == 200


def test_invitations_refuse_existing_accounts_duplicates_and_bad_roles(c):
    assert c.post("/api/vendor/staff/invitations", headers=_hdr(S["ua"]["id"]),
                  json={"mobile": "9100001002", "full_name": "Customer", "role": "store_manager"}).status_code == 400   # a customer's number
    _invite(c, "ua", "9100001103")
    assert c.post("/api/vendor/staff/invitations", headers=_hdr(S["ua"]["id"]),
                  json={"mobile": "9100001103", "full_name": "Again", "role": "store_manager"}).status_code == 409
    assert c.post("/api/vendor/staff/invitations", headers=_hdr(S["ua"]["id"]),
                  json={"mobile": "9100001104", "full_name": "Owner", "role": "owner"}).status_code == 400              # no owner transfer
    assert c.post("/api/vendor/staff/invitations", headers=_hdr(S["ua"]["id"]),
                  json={"mobile": "9100001105", "full_name": "Bad", "role": "custom", "permissions": ["staff.manage"]}).status_code == 400


# ====================================================================== roles and permissions on real endpoints
def test_preset_roles_allow_only_their_permissions(c):
    fin_h, _ = _joined(c, "9100001201", role="finance_viewer")
    assert c.get("/api/vendor/finance/summary", headers=fin_h).status_code == 200            # read-only earnings
    assert c.get("/api/vendor/orders", headers=fin_h).status_code == 403
    assert c.get("/api/vendor/products", headers=fin_h).status_code == 403
    assert c.post("/api/vendor/products", headers=fin_h, json={}).status_code == 403          # no product writes
    prod_h, _ = _joined(c, "9100001202", role="product_manager")
    assert c.get("/api/vendor/products", headers=prod_h).status_code == 200
    assert c.get("/api/vendor/orders", headers=prod_h).status_code == 403
    assert c.get("/api/vendor/finance/summary", headers=prod_h).status_code == 403


def test_custom_roles_are_bounded_to_the_listed_permissions(c):
    assert c.post("/api/vendor/staff/invitations", headers=_hdr(S["ua"]["id"]),
                  json={"mobile": "9100001301", "full_name": "Custom", "role": "custom", "permissions": []}).status_code == 400
    h, _ = _joined(c, "9100001302", role="custom", perms=["orders.read"])
    assert c.get("/api/vendor/orders", headers=h).status_code == 200
    assert c.get("/api/vendor/products", headers=h).status_code == 403


def test_role_changes_take_effect_on_the_next_request_and_are_audited(c):
    h, mid = _joined(c, "9100001401", role="finance_viewer")
    assert c.get("/api/vendor/finance/summary", headers=h).status_code == 200
    assert c.get("/api/vendor/products", headers=h).status_code == 403
    r = c.put(f"/api/vendor/staff/{mid}", headers=_hdr(S["ua"]["id"]), json={"role": "product_manager"})
    assert r.status_code == 200
    assert c.get("/api/vendor/products", headers=h).status_code == 200                       # new role, same login
    assert c.get("/api/vendor/finance/summary", headers=h).status_code == 403
    audit = c.portal.call(lambda: db.audit_logs.find({"action": "vendor_staff_role_changed", "entity_id": mid}, {"_id": 0}).to_list(5))
    assert audit and audit[0]["old_value"]["role"] == "finance_viewer" and audit[0]["new_value"]["role"] == "product_manager"


# ====================================================================== staff cannot manage the team, the profile or money
def test_staff_cannot_manage_the_team_profile_bank_or_documents(c):
    h, mid = _joined(c, "9100001501", role="store_manager")
    assert c.get("/api/vendor/staff", headers=h).status_code == 403
    assert c.post("/api/vendor/staff/invitations", headers=h, json={"mobile": "9100001502", "full_name": "X Y", "role": "store_manager"}).status_code == 403
    assert c.put(f"/api/vendor/staff/{mid}", headers=h, json={"role": "custom", "permissions": ["finance.read"]}).status_code == 403   # no self-promotion
    assert c.post(f"/api/vendor/staff/{mid}/revoke", headers=h).status_code in (403, 404, 405)
    assert c.put("/api/vendor/me", headers=h, json={"business_name": "Hijacked", "contact_person": "X Y", "phone": "9876500000",
                                                    "address": "1 Road Lane", "submit": False}).status_code == 403
    assert c.post("/api/vendor/me/bank-change", headers=h, json={}).status_code == 403
    assert c.post("/api/vendor/documents", headers=h, json={}).status_code == 403
    assert c.get("/api/vendor/finance/summary", headers=h).status_code == 403                # store manager has no finance
    assert c.post("/api/admin/vendors/" + S["va"]["id"] + "/decision", headers=h, json={"action": "approve"}).status_code == 403


def test_admins_and_customers_are_not_vendor_staff_and_keep_their_own_access(c):
    assert c.get("/api/vendor/staff", headers=_hdr(S["cust"]["id"])).status_code == 403
    assert c.get("/api/vendor/staff", headers=_hdr(S["adm"]["id"])).status_code == 403
    assert c.post("/api/auth/login", json={"email": "9100001001", "password": PW}).status_code == 200      # admin login unchanged
    assert c.post("/api/auth/login", json={"email": "9100001002", "password": PW}).status_code == 200      # customer login unchanged


# ====================================================================== suspension and revocation
def test_suspension_and_revocation_stop_access_on_the_next_request(c):
    h, mid = _joined(c, "9100001601", role="order_manager")
    assert c.get("/api/vendor/orders", headers=h).status_code == 200
    assert c.post(f"/api/vendor/staff/{mid}/suspend", headers=_hdr(S["ua"]["id"])).status_code == 200
    assert c.get("/api/vendor/orders", headers=h).status_code == 403                         # same token, now refused
    assert c.post(f"/api/vendor/staff/{mid}/reactivate", headers=_hdr(S["ua"]["id"])).status_code == 200
    assert c.get("/api/vendor/orders", headers=h).status_code == 200
    assert c.delete(f"/api/vendor/staff/{mid}", headers=_hdr(S["ua"]["id"])).status_code == 200
    assert c.get("/api/vendor/orders", headers=h).status_code == 403
    assert c.post(f"/api/vendor/staff/{mid}/reactivate", headers=_hdr(S["ua"]["id"])).status_code == 400   # revoke is final
    actions = {a["action"] for a in c.portal.call(lambda: db.audit_logs.find({"entity_id": mid}, {"_id": 0, "action": 1}).to_list(20))}
    assert {"vendor_staff_suspended", "vendor_staff_reactivated", "vendor_staff_revoked"} <= actions


# ====================================================================== vendor isolation
def test_one_vendors_owner_and_staff_never_reach_another_vendors_data(c):
    h, mid = _joined(c, "9100001701", role="store_manager")
    products = c.get("/api/vendor/products", headers=h).json()
    ids = [p["id"] for p in (products["items"] if isinstance(products, dict) else products)]
    assert S["pa"] in ids and S["pb"] not in ids
    b_team = c.get("/api/vendor/staff", headers=_hdr(S["ub"]["id"])).json()["staff"]
    assert all(m["id"] != mid for m in b_team)                                               # B's owner does not see A's team
    assert c.post(f"/api/vendor/staff/{mid}/suspend", headers=_hdr(S["ub"]["id"])).status_code == 404
    assert c.delete(f"/api/vendor/staff/{mid}", headers=_hdr(S["ub"]["id"])).status_code == 404
    assert c.put(f"/api/vendor/staff/{mid}", headers=_hdr(S["ub"]["id"]), json={"role": "product_manager"}).status_code == 404
    a_team = c.get("/api/vendor/staff", headers=_hdr(S["ua"]["id"])).json()["staff"]
    assert all("Store B" not in str(m) for m in a_team)
    assert c.get("/api/vendor/products", headers=_hdr(S["ub"]["id"])).status_code == 200
    assert S["pa"] not in str(c.get("/api/vendor/products", headers=_hdr(S["ub"]["id"])).json())
    assert c.get("/api/vendor/staff", headers=h).status_code == 403                          # A's staff cannot even list A's team


def test_the_team_list_masks_mobiles_and_shows_roles_and_status(c):
    _invite(c, "ua", "9100001801", role="inventory_staff")
    text = c.get("/api/vendor/staff", headers=_hdr(S["ua"]["id"])).text
    assert "9100001801" not in text and "email" not in text
    rows = c.get("/api/vendor/staff", headers=_hdr(S["ua"]["id"])).json()["staff"]
    row = next(r for r in rows if r["role"] == "inventory_staff" and r["status"] == "invited")
    assert row["mobile"].endswith("1801") and row["invite_expires_at"]
