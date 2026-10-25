"""Vendor foundation (Phase 1): lifecycle transitions, role boundaries, unique vendor IDs, and the repeatable migration.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_vendor_foundation.py -n 0`.
"""
import os
import re

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_foundation_test", "JWT_SECRET": "vendor-foundation-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pymongo.errors import DuplicateKeyError  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import vendor_lifecycle as VL  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Vendor-Pass-123"
PROFILE = {"business_name": "Foundation Store", "contact_person": "Owner", "phone": "9876500010", "address": "12 Market Road, Jaipur",
           "city": "Jaipur", "state": "RJ", "pincode": "302001", "categories": ["Sarees"], "bank_account_name": "Foundation Store",
           "bank_account": "111122223333", "ifsc": "SBIN0000001", "agree_terms": True}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _status(c, vid):
    return c.portal.call(lambda: db.vendors.find_one({"id": vid}, {"_id": 0, "status": 1}))["status"]


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
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

            async def vendor(u, name, status, code, bank=True):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": code, "business_name": name, "status": status,
                     "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                if bank:
                    v.update({"bank_account": "111122223333", "bank_account_name": name, "ifsc": "SBIN0000001"})
                await db.vendors.insert_one(dict(v))
                return v

            S["adm"] = await user("9100000951", "super_admin", "FADM")
            S["cust"] = await user("9100000952", "distributor", "FCUS")
            S["owner_u"] = await user("9100000953", "vendor", "FVA")
            S["owner"] = await vendor(S["owner_u"], "Owner Store", "approved", "VF000001")
            S["draft_u"] = await user("9100000954", "vendor", "FVD")
            S["draft"] = await vendor(S["draft_u"], "Draft Store", "draft", "VF000002", bank=False)
            S["invited_u"] = await user("9100000955", "vendor", "FVI")
            S["invited"] = await vendor(S["invited_u"], "Invited Store", "invited", "VF000003")
            S["staff_u"] = await user("9100000956", "vendor_staff", "FVS")
            await db.vendor_members.insert_one({"id": new_id(), "vendor_id": S["owner"]["id"], "user_id": S["staff_u"]["id"],
                                                "role": "staff", "permissions": [], "status": "active", "created_at": now_iso()})
            S["newbie_u"] = await user("9100000957", "vendor", "FVN")      # vendor login with no vendor record yet
            S["other_u"] = await user("9100000958", "vendor", "FVB")
            S["other"] = await vendor(S["other_u"], "Other Store", "approved", "VF000004")
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ====================================================================== transition table
def test_transition_table_is_closed_and_only_an_admin_can_activate_or_approve():
    assert all(f in VL.STATUSES and t in VL.STATUSES and a in ("vendor", "admin") for (f, t), a in VL.TRANSITIONS.items())
    assert set(VL.SELLING) <= set(VL.STATUSES) and set(VL.CONTACT_ONLY) <= set(VL.STATUSES)
    assert {(f, a) for (f, t), a in VL.TRANSITIONS.items() if t == "active"} == {("approved", "admin")}
    assert not any(a == "vendor" and t in ("approved", "active", "suspended", "rejected") for (f, t), a in VL.TRANSITIONS.items())
    assert not VL.transition_allowed("draft", "approved", "admin") and not VL.transition_allowed("draft", "active", "admin")
    assert not VL.transition_allowed("submitted", "active", "admin")                       # review cannot be skipped


def test_invalid_moves_are_refused_before_anything_is_written(c):
    d = c.portal.call(lambda: db.vendors.find_one({"id": S["draft"]["id"]}, {"_id": 0}))
    for to, actor in [("approved", "admin"), ("active", "admin"), ("active", "vendor"), ("approved", "vendor")]:
        with pytest.raises(HTTPException) as e:
            c.portal.call(lambda: VL.move(d, to, actor, "tester"))
        assert e.value.status_code == 400
    assert _status(c, S["draft"]["id"]) == "draft"


def test_a_stale_snapshot_cannot_overwrite_a_newer_status(c):
    stale = {"id": S["draft"]["id"], "status": "submitted"}                             # the database says draft
    with pytest.raises(HTTPException) as e:
        c.portal.call(lambda: VL.move(stale, "approved", "admin", "tester"))
    assert e.value.status_code == 409
    assert _status(c, S["draft"]["id"]) == "draft"


# ====================================================================== admin decisions through the API
def test_admin_decisions_follow_the_lifecycle_and_are_recorded(c):
    v = {"id": new_id(), "user_id": new_id(), "vendor_code": "VF000010", "business_name": "Review Store", "status": "submitted",
         "created_at": now_iso(), "updated_at": now_iso()}
    c.portal.call(lambda: db.vendors.insert_one(dict(v)))
    vid = v["id"]
    dec = lambda action, **kw: c.post(f"/api/admin/vendors/{vid}/decision", headers=_hdr(S["adm"]["id"]), json={"action": action, **kw})
    assert dec("reject", reason="").status_code == 400                                       # a reason is required
    assert dec("approve").status_code == 200 and _status(c, vid) == "approved"
    assert dec("approve").status_code == 400                                                  # already approved
    assert dec("activate").status_code == 200 and _status(c, vid) == "active"
    assert dec("activate").status_code == 400
    assert dec("suspend", reason="Test suspension reason").status_code == 200 and _status(c, vid) == "suspended"
    assert dec("activate").status_code == 400                                                 # must be reinstated first
    assert dec("reinstate").status_code == 200 and _status(c, vid) == "approved"
    assert dec("start_review").status_code == 400                                             # no longer submitted
    hist = c.portal.call(lambda: db.vendor_status_history.find({"vendor_id": vid}, {"_id": 0, "from": 1, "to": 1}).sort("at", 1).to_list(50))
    assert [h["to"] for h in hist][-3:] == ["active", "suspended", "approved"]


def test_a_rejected_application_can_still_be_approved_by_admin(c):
    v = {"id": new_id(), "user_id": new_id(), "vendor_code": "VF000011", "business_name": "Second Chance", "status": "submitted",
         "created_at": now_iso(), "updated_at": now_iso()}
    c.portal.call(lambda: db.vendors.insert_one(dict(v)))
    assert c.post(f"/api/admin/vendors/{v['id']}/decision", headers=_hdr(S["adm"]["id"]), json={"action": "reject", "reason": "Bank proof unclear"}).status_code == 200
    assert c.post(f"/api/admin/vendors/{v['id']}/decision", headers=_hdr(S["adm"]["id"]), json={"action": "approve"}).status_code == 200


def test_only_an_admin_can_decide(c):
    for who in ("owner_u", "draft_u", "cust"):
        r = c.post(f"/api/admin/vendors/{S['draft']['id']}/decision", headers=_hdr(S[who]["id"]), json={"action": "approve"})
        assert r.status_code == 403
    assert _status(c, S["draft"]["id"]) == "draft"


# ====================================================================== the vendor cannot change its own status
def test_profile_api_ignores_any_status_sent_by_the_vendor(c):
    r = c.put("/api/vendor/me", headers=_hdr(S["draft_u"]["id"]), json={**PROFILE, "status": "approved", "submit": False})
    assert r.status_code == 200
    assert _status(c, S["draft"]["id"]) == "draft"
    r = c.put("/api/vendor/me", headers=_hdr(S["owner_u"]["id"]), json={**PROFILE, "status": "active", "submit": False})
    assert r.status_code == 200 and _status(c, S["owner"]["id"]) == "approved"


def test_invited_vendor_becomes_a_draft_on_first_save(c):
    assert c.put("/api/vendor/me", headers=_hdr(S["invited_u"]["id"]), json={**PROFILE, "submit": False}).status_code == 200
    assert _status(c, S["invited"]["id"]) == "draft"


def test_submit_needs_a_complete_profile_and_then_moves_to_submitted(c):
    h = _hdr(S["draft_u"]["id"])
    assert c.put("/api/vendor/me", headers=h, json={**PROFILE, "bank_account": "", "ifsc": "", "submit": True}).status_code == 400
    assert _status(c, S["draft"]["id"]) == "draft"
    assert c.put("/api/vendor/me", headers=h, json={**PROFILE, "submit": True}).status_code == 200
    assert _status(c, S["draft"]["id"]) == "submitted"


def test_active_vendor_keeps_selling_access_and_contact_only_edits(c):
    c.portal.call(lambda: db.vendors.update_one({"id": S["owner"]["id"]}, {"$set": {"status": "active"}}))
    try:
        assert c.get("/api/vendor/products", headers=_hdr(S["owner_u"]["id"])).status_code == 200
        assert c.get("/api/vendor/dashboard", headers=_hdr(S["owner_u"]["id"]), params={"range": "30d"}).status_code == 200
        assert c.put("/api/vendor/me", headers=_hdr(S["owner_u"]["id"]), json={**PROFILE, "submit": True}).status_code == 200
        assert _status(c, S["owner"]["id"]) == "active"                                  # a contact-only save never changes status
    finally:
        c.portal.call(lambda: db.vendors.update_one({"id": S["owner"]["id"]}, {"$set": {"status": "approved"}}))


# ====================================================================== roles and data boundaries
def test_customers_and_admins_cannot_use_vendor_routes_and_staff_only_what_they_are_granted(c):
    for who in ("cust", "adm"):
        assert c.get("/api/vendor/me", headers=_hdr(S[who]["id"])).status_code == 403
        assert c.get("/api/vendor/products", headers=_hdr(S[who]["id"])).status_code == 403
    # an active staff member with no permissions can read their own vendor profile, nothing else
    assert c.get("/api/vendor/me", headers=_hdr(S["staff_u"]["id"])).status_code == 200
    assert c.get("/api/vendor/products", headers=_hdr(S["staff_u"]["id"])).status_code == 403


def test_a_vendor_only_ever_sees_its_own_record(c):
    me = c.get("/api/vendor/me", headers=_hdr(S["other_u"]["id"])).json()["vendor"]
    assert me["id"] == S["other"]["id"] and me["id"] != S["owner"]["id"]


def test_vendor_ids_and_owner_links_are_unique_in_the_database(c):
    base = {"status": "draft", "created_at": now_iso(), "updated_at": now_iso()}
    with pytest.raises(DuplicateKeyError):
        c.portal.call(lambda: db.vendors.insert_one({"id": new_id(), "user_id": new_id(), "vendor_code": S["owner"]["vendor_code"], **base}))
    with pytest.raises(DuplicateKeyError):
        c.portal.call(lambda: db.vendors.insert_one({"id": new_id(), "user_id": S["owner_u"]["id"], "vendor_code": "VF999901", **base}))
    with pytest.raises(DuplicateKeyError):
        c.portal.call(lambda: db.vendors.insert_one({"id": S["owner"]["id"], "user_id": new_id(), "vendor_code": "VF999902", **base}))
    with pytest.raises(DuplicateKeyError):
        c.portal.call(lambda: db.vendor_members.insert_one({"id": new_id(), "vendor_id": S["owner"]["id"], "user_id": S["staff_u"]["id"]}))
    names = c.portal.call(lambda: db.vendors.index_information())
    assert {"vendors_id_unique", "vendors_user_unique", "vendors_code_unique"} <= set(names)


def test_a_vendor_without_a_record_gets_a_system_code_not_its_login_id(c):
    assert c.put("/api/vendor/me", headers=_hdr(S["newbie_u"]["id"]), json={**PROFILE, "submit": False}).status_code == 200
    v = c.portal.call(lambda: db.vendors.find_one({"user_id": S["newbie_u"]["id"]}, {"_id": 0}))
    assert re.fullmatch(r"VD\d{6}", v["vendor_code"]) and v["vendor_code"] != S["newbie_u"]["distributor_id"]
    assert v["status"] == "draft"


# ====================================================================== migration
def test_migration_dry_run_reports_then_apply_backfills_once(c):
    legacy = {"id": new_id(), "user_id": new_id(), "business_name": "Legacy Store", "status": "approved", "created_at": now_iso()}
    c.portal.call(lambda: db.vendors.insert_one(dict(legacy)))
    dry = c.portal.call(lambda: VL.migrate(apply=False))
    assert dry["backfilled"] == ["(would assign)"] and dry["duplicates"] == {}
    assert c.portal.call(lambda: db.vendors.find_one({"id": legacy["id"]}, {"_id": 0, "vendor_code": 1})).get("vendor_code") is None
    first = c.portal.call(lambda: VL.migrate(apply=True))
    assert len(first["backfilled"]) == 1 and re.fullmatch(r"VD\d{6}", first["backfilled"][0])
    code = c.portal.call(lambda: db.vendors.find_one({"id": legacy["id"]}, {"_id": 0, "vendor_code": 1})).get("vendor_code")
    assert code == first["backfilled"][0]
    second = c.portal.call(lambda: VL.migrate(apply=True))
    assert second["backfilled"] == [] and second["duplicates"] == {} and second["indexes_failed"] == []


def test_staff_list_is_owner_only_and_never_returns_full_contacts(c):
    owner = c.get("/api/vendor/staff", headers=_hdr(S["owner_u"]["id"]))
    assert owner.status_code == 200
    rows = owner.json()["staff"]
    assert len(rows) == 1 and rows[0]["role"] == "staff" and rows[0]["status"] == "active"
    assert rows[0]["mobile"].endswith("0956") and "9100000956" not in owner.text
    assert "email" not in owner.text
    assert c.get("/api/vendor/staff", headers=_hdr(S["staff_u"]["id"])).status_code == 403     # staff cannot list the team
    assert c.get("/api/vendor/staff", headers=_hdr(S["cust"]["id"])).status_code == 403
    assert c.get("/api/vendor/staff", headers=_hdr(S["adm"]["id"])).status_code == 403
    assert c.get("/api/vendor/staff", headers=_hdr(S["other_u"]["id"])).json()["staff"] == []   # another vendor sees none of ours
    assert c.get("/api/vendor/staff", headers=_hdr(S["draft_u"]["id"])).status_code == 200      # onboarding owners can see the page
