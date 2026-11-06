"""Vendor owner invitations: expiry, single use, revocation and rotation, token secrecy, and who may issue invitations.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_owner_invitation.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_owner_invite_test", "JWT_SECRET": "owner-invite-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import core  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Owner-Pass-123"
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
            for key, mobile, role in (("adm", "9100006001", "super_admin"), ("cust", "9100006002", "distributor")):
                S[key] = {"id": new_id(), "distributor_id": key.upper() + "1", "full_name": key, "mobile": mobile, "email": None,
                          "password_hash": hash_password(PW), "role": role, "status": "green", "account_status": "active",
                          "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(S[key]))
        client.portal.call(seed)
        core.RATE_LIMITS["staff_accept"] = (1000, 3600)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _create(c, mobile, name="Invite Store"):
    """Vendor Pillar: creation starts onboarding (no invitation); the owner invitation is issued once a super admin has approved.
    The onboarding checklist and the final review are covered in tests/test_vendor_onboarding.py; here the vendor is moved to
    `approved` directly so these tests can focus on the invitation mechanics."""
    r = c.post("/api/admin/vendors/create", headers=_hdr(S["adm"]["id"]),
               json={"business_name": name, "full_name": "Owner Person", "mobile": mobile, "email": f"{mobile}@example.test"})
    assert r.status_code == 200, r.text
    made = r.json()
    assert "invitation" not in made and made["status"] == "onboarding"
    c.portal.call(lambda: db.vendors.update_one({"id": made["vendor_id"]}, {"$set": {"status": "approved", "owner_activation": "pending"}}))
    inv = c.post(f"/api/admin/vendors/{made['vendor_id']}/owner-invitation", headers=_hdr(S["adm"]["id"]))
    assert inv.status_code == 200, inv.text
    return {**made, "invitation": inv.json()}


def test_a_new_vendor_account_cannot_sign_in_until_the_owner_accepts(c):
    made = _create(c, "9199006101")
    assert made["invitation"]["token"] and made["invitation"]["delivered"] is False
    assert c.post("/api/auth/login", json={"email": "9199006101", "password": PW}).status_code in (400, 401, 403)


def test_valid_token_sets_the_owner_password_and_is_single_use(c):
    made = _create(c, "9199006102")
    tok = made["invitation"]["token"]
    info = c.get("/api/vendor/invitation/owner", params={"token": tok})
    assert info.status_code == 200 and info.json()["business_name"] == "Invite Store" and info.json()["mobile_hint"].endswith("6102")
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": tok, "password": "weakpass"}).status_code == 400
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": tok, "password": "Owner-Pass-123"}).status_code == 200
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": tok, "password": "Another-Pass-9"}).status_code == 400   # reuse
    assert c.get("/api/vendor/invitation/owner", params={"token": tok}).status_code == 400
    assert c.post("/api/auth/login", json={"email": "9199006102", "password": "Owner-Pass-123"}).status_code == 200


def test_expired_invitations_are_rejected(c):
    made = _create(c, "9199006103")
    tok = made["invitation"]["token"]
    c.portal.call(lambda: db.account_invitations.update_many({"vendor_id": made["vendor_id"]},
                                                             {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}}))
    assert c.get("/api/vendor/invitation/owner", params={"token": tok}).status_code == 400
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": tok, "password": PW}).status_code == 400
    status = c.get(f"/api/admin/vendors/{made['vendor_id']}/owner-invitation", headers=_hdr(S["adm"]["id"])).json()
    assert status["status"] == "expired"


def test_resend_rotates_the_token_and_revoke_stops_the_link(c):
    made = _create(c, "9199006104")
    old = made["invitation"]["token"]
    vid = made["vendor_id"]
    new = c.post(f"/api/admin/vendors/{vid}/owner-invitation", headers=_hdr(S["adm"]["id"])).json()["token"]
    assert new and new != old
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": old, "password": PW}).status_code == 400          # old link is dead
    assert c.post(f"/api/admin/vendors/{vid}/owner-invitation/revoke", headers=_hdr(S["adm"]["id"])).json()["revoked"] == 1
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": new, "password": PW}).status_code == 400          # revoked
    fresh = c.post(f"/api/admin/vendors/{vid}/owner-invitation", headers=_hdr(S["adm"]["id"])).json()["token"]
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": fresh, "password": PW}).status_code == 200
    assert c.post(f"/api/admin/vendors/{vid}/owner-invitation", headers=_hdr(S["adm"]["id"])).status_code == 409            # already set up


def test_invalid_tokens_fail_the_same_way_and_no_token_is_stored_or_listed(c):
    made = _create(c, "9199006105")
    tok = made["invitation"]["token"]
    bad = c.get("/api/vendor/invitation/owner", params={"token": "x" * 40})
    assert bad.status_code == 400 and bad.json()["detail"].startswith("This invitation is not valid")
    stored = c.portal.call(lambda: db.account_invitations.find({"vendor_id": made["vendor_id"]}, {"_id": 0}).to_list(10))
    assert stored and all(tok not in str(row) for row in stored)                                                           # only a hash is stored
    listing = c.get("/api/admin/vendors", headers=_hdr(S["adm"]["id"])).text
    assert tok not in listing and "password" not in listing.lower()
    audit = c.portal.call(lambda: db.audit_logs.find({}, {"_id": 0}).to_list(500))
    assert all(tok not in str(a) for a in audit)                                                                           # never logged


def test_only_admins_issue_invitations_and_finished_or_rejected_vendors_cannot_be_reinvited(c):
    made = _create(c, "9199006106")
    vid = made["vendor_id"]
    assert c.post(f"/api/admin/vendors/{vid}/owner-invitation", headers=_hdr(S["cust"]["id"])).status_code in (401, 403)
    assert c.post(f"/api/admin/vendors/{vid}/owner-invitation").status_code in (401, 403)
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": made["invitation"]["token"], "password": PW}).status_code == 200
    c.portal.call(lambda: db.vendors.update_one({"id": vid}, {"$set": {"status": "rejected"}}))
    assert c.post(f"/api/admin/vendors/{vid}/owner-invitation", headers=_hdr(S["adm"]["id"])).status_code == 400
