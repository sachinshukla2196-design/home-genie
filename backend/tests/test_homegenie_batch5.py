"""Batch 5 — HomeGenie selling: HG-02 (the KYC submission and review API contract the new screens use, including the stale
review guard) and HG-01 (the server-side attribution rules that share links rely on).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_homegenie_batch5.py -n 0`).
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_homegenie_batch5_test", "JWT_SECRET": "batch5-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
KYC = {"pan": "ABCDE1234F", "aadhaar": "123456789012", "account_holder_name": "Genie One", "bank_account": "123456789012",
       "ifsc": "SBIN0001234", "bank_name": "SBI"}


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
            await user("genie", "9100005001", "distributor", "HG500001")
            await user("red", "9100005002", "distributor", "HG500002", status="red")
            await user("cust", "9100005003", "distributor", "HG500003", status="red")
            await user("super", "9100005004", "super_admin", "B5SUPER")
            await user("sup", "9100005005", "support_admin", "B5SUP")
            await db.products.insert_one({"id": "p5", "sku": "B5-1", "name": "Saree", "images": [], "mrp": 1000, "selling_price": 800,
                                          "gst_percent": 5, "stock": 50, "category": "Sarees", "options": [], "vendor_id": None,
                                          "is_active": True, "approval_status": "approved", "created_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ================================================================ HG-02: KYC submission and review
def test_member_submits_kyc_and_sees_it_masked(c):
    assert c.get("/api/kyc", headers=_hdr("genie")).json()["status"] == "not_started"
    r = c.post("/api/kyc", json=KYC, headers=_hdr("genie"))
    assert r.status_code == 200, r.text
    mine = c.get("/api/kyc", headers=_hdr("genie")).json()
    assert mine["status"] == "pending" and KYC["pan"] not in str(mine) and KYC["bank_account"] not in str(mine)


def test_admin_review_list_is_masked_and_carries_the_version(c):
    rows = c.get("/api/admin/kyc", params={"status": "pending"}, headers=_hdr("sup")).json()
    row = next(x for x in rows if x["user_id"] == S["genie"]["id"])
    assert row["distributor_id"] == "HG500001" and row.get("version") == 1
    assert KYC["pan"] not in str(row) and KYC["aadhaar"] not in str(row) and KYC["bank_account"] not in str(row)


def test_stale_review_is_refused_and_current_review_verifies(c):
    uid = S["genie"]["id"]
    assert c.post("/api/kyc", json={**KYC, "bank_account": "998877665544"}, headers=_hdr("genie")).status_code == 200   # resubmitted: v2
    stale = c.put(f"/api/admin/kyc/{uid}", json={"action": "verify", "expected_version": 1}, headers=_hdr("sup"))
    assert stale.status_code == 409
    ok = c.put(f"/api/admin/kyc/{uid}", json={"action": "verify", "expected_version": 2}, headers=_hdr("sup"))
    assert ok.status_code == 200 and ok.json()["status"] == "verified"
    assert c.get("/api/kyc", headers=_hdr("genie")).json()["status"] == "verified"


def test_member_resubmission_after_verification_needs_a_new_check(c):
    assert c.post("/api/kyc", json={**KYC, "bank_account": "111122223333"}, headers=_hdr("genie")).status_code == 200
    assert c.get("/api/kyc", headers=_hdr("genie")).json()["status"] == "pending"


# ================================================================ HG-01: attribution rules behind share links
def _order(c, ref):
    r = c.post("/api/orders", json={"items": [{"product_id": "p5", "quantity": 1}], "address": ADDR, "seller_ref": ref,
                                    "payment_method": "online"}, headers=_hdr("cust"))
    assert r.status_code == 200, r.text
    return _run(c, lambda: db.orders.find_one({"id": r.json()["id"]}))


def test_an_activated_homegenie_share_code_attributes_the_order(c):
    o = _order(c, "HG500001")
    assert o["seller_user_id"] == S["genie"]["id"]


@pytest.mark.parametrize("ref", ["HG500002", "HG999999", "", "hg500001 ; drop"])
def test_inactive_unknown_or_malformed_codes_attribute_nothing(c, ref):
    assert not _order(c, ref).get("seller_user_id")


def test_a_homegenie_never_earns_on_their_own_purchase(c):
    r = c.post("/api/orders", json={"items": [{"product_id": "p5", "quantity": 1}], "address": ADDR, "seller_ref": "HG500001",
                                    "payment_method": "online"}, headers=_hdr("genie"))
    assert r.status_code == 200
    assert not _run(c, lambda: db.orders.find_one({"id": r.json()["id"]})).get("seller_user_id")
