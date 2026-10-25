"""Phase 9 backend: benefit approval dates and expiry, the admin proposal and eligibility lists, agreement names, and access.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_admin_screens_backend.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_admin_screens_test", "JWT_SECRET": "admin-screens-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Vendor-Pass-123"
ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


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

            S["fin1"] = await user("9100007001", "accounts_admin", "AS1")
            S["fin2"] = await user("9100007002", "super_admin", "AS2")
            S["cust"] = await user("9100007003", "distributor", "AS3")
            S["ua"] = await user("9100007004", "vendor", "AS4")
            S["va"] = {"id": new_id(), "user_id": S["ua"]["id"], "vendor_code": "VS000001", "business_name": "Screens Store",
                       "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["va"]))
            S["pid"] = new_id()
            await db.products.insert_one({"id": S["pid"], "vendor_id": S["va"]["id"], "name": "Screen saree", "sku": "SS-1", "stock": 5,
                                          "low_stock_threshold": 5, "is_active": True, "approval_status": "approved", "archived": False,
                                          "category": "Sarees", "created_at": now_iso(), "updated_at": now_iso()})
            now = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
            order = {"id": new_id(), "order_number": "SCR1", "user_id": new_id(), "payment_method": "online", "payment_status": "paid",
                     "status": "delivered", "created_at": now.isoformat(), "paid_at": now.isoformat(), "total_paise": 50000, "total": 500.0,
                     "items": [{"product_id": S["pid"], "name": "Screen saree", "sku": "SS-1", "vendor_id": S["va"]["id"], "quantity": 1,
                                "total_paise": 50000, "total": 500.0}],
                     "fulfilments": [{"vendor_id": S["va"]["id"], "status": "delivered", "events": []}], "address": ADDR, "needs_refund": False}
            await db.orders.insert_one(dict(order))
            await db.finance_policy.update_one({"id": "settlement_policy"}, {"$set": {"id": "settlement_policy", "active": True, "version": 1,
                                                "require_dual_approval": True, "min_settlement_paise": 0, "cod_overdue_days": 7, "notes": "t",
                                                "updated_by": None, "updated_at": now_iso()}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _programme(c, key):
    r = c.post("/api/admin/benefits/programmes", headers=_hdr(S["fin2"]["id"]),
               json={"key": key, "title": "Orders programme", "review_days": 30, "benefit_text": "Listing priority review",
                     "criteria": [{"metric": "orders", "value": 1}]})
    assert r.status_code == 200, r.text
    return r.json()


def test_approval_records_effective_and_expiry_dates_and_expired_benefits_read_as_expired(c):
    prog = _programme(c, "dates_prog")
    g = c.post("/api/admin/benefits/proposals", headers=_hdr(S["fin1"]["id"]), json={"vendor_id": S["va"]["id"], "programme_id": prog["id"]}).json()
    bad = c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=_hdr(S["fin2"]["id"]),
                 json={"action": "approve", "effective_from": "2026-13-40"})
    assert bad.status_code == 400
    tomorrow = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
    backwards = c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=_hdr(S["fin2"]["id"]),
                       json={"action": "approve", "effective_from": tomorrow, "expires_at": tomorrow})
    assert backwards.status_code == 400
    ok = c.post(f"/api/admin/benefits/proposals/{g['id']}/decide", headers=_hdr(S["fin2"]["id"]),
                json={"action": "approve", "effective_from": tomorrow, "expires_at": (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()})
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["effective_from"] == tomorrow and ok.json()["applied"] is False
    past = c.portal.call(lambda: db.benefit_grants.update_one({"id": g["id"]}, {"$set": {"expires_at_date": "2000-01-01"}}))
    row = next(b for b in c.get("/api/vendor/advancement/eligibility", headers=_hdr(S["ua"]["id"])).json()["benefits"] if b["id"] == g["id"])
    assert row["status"] == "expired"                                              # an approved benefit past its expiry is not active


def test_admin_lists_show_proposals_and_eligibility_and_block_everyone_else(c):
    prog = _programme(c, "lists_prog")
    c.post("/api/admin/benefits/proposals", headers=_hdr(S["fin1"]["id"]), json={"vendor_id": S["va"]["id"], "programme_id": prog["id"]})
    props = c.get("/api/admin/benefits/proposals", headers=_hdr(S["fin2"]["id"])).json()["proposals"]
    assert any(p["programme_id"] == prog["id"] and p["business_name"] == "Screens Store" for p in props)
    elig = c.get("/api/admin/benefits/eligibility", headers=_hdr(S["fin2"]["id"]), params={"programme_id": prog["id"]}).json()
    row = next(v for v in elig["vendors"] if v["vendor_code"] == "VS000001")
    assert row["eligible"] is True and row["open_proposal"] is not None and row["metrics"]["orders"] == 1
    assert c.get("/api/admin/benefits/eligibility", headers=_hdr(S["fin2"]["id"]), params={"programme_id": "nope"}).status_code == 404
    for who in ("ua", "cust"):
        assert c.get("/api/admin/benefits/proposals", headers=_hdr(S[who]["id"])).status_code in (401, 403)
        assert c.get("/api/admin/benefits/eligibility", headers=_hdr(S[who]["id"]), params={"programme_id": prog["id"]}).status_code in (401, 403)


def test_agreement_lists_name_the_drafter_and_the_approver(c):
    eff = (datetime.now(timezone.utc).date()).isoformat()
    ag = c.post(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["fin1"]["id"]),
                json={"commission_pct": 2.5, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": eff}).json()
    assert c.post(f"/api/admin/finance/agreements/{ag['id']}/approve", headers=_hdr(S["fin2"]["id"])).status_code == 200
    rows = c.get(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["fin2"]["id"])).json()["agreements"]
    row = next(r for r in rows if r["id"] == ag["id"])
    assert row["created_by_name"] == "AS1" and row["approved_by_name"] == "AS2" and row["status"] == "approved"
    assert c.get(f"/api/admin/finance/vendors/{S['va']['id']}/agreements", headers=_hdr(S["ua"]["id"])).status_code == 403
