"""Vendor governance (history, documents, bank changes, support), notifications, account security, rate limits, signed uploads.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_governance_test", "JWT_SECRET": "governance-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
for k in ("WEBHOOK_CRON_SECRET", "ADMIN_EMAIL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_UPLOAD_PRESET"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import core  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
PW = "Vendor-Pass-123"


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()

            async def user(mobile, role, did, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password(PW), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name, status="approved"):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": name, "status": status,
                     "categories": ["Sarees"], "bank_account": "123456789012", "bank_account_name": name, "ifsc": "SBIN0000001",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v
            S["cust"], S["sup"] = await user("9100000901", "distributor", "HGC", "red"), await user("9100000902", "support_admin", "HGSUP")
            S["adm"], S["fin"] = await user("9100000903", "super_admin", "HGADM"), await user("9100000904", "accounts_admin", "HGFIN")
            S["ua"], S["ub"] = await user("9100000905", "vendor", "VDA"), await user("9100000906", "vendor", "VDB")
            S["ud"] = await user("9100000907", "vendor", "VDD")
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A"), await vendor(S["ub"], "Vendor B")
            S["vd"] = await vendor(S["ud"], "Draft Vendor", "draft")
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


@pytest.fixture(autouse=True)
def _restore_limits():
    saved = dict(core.RATE_LIMITS)
    yield
    core.RATE_LIMITS.clear()
    core.RATE_LIMITS.update(saved)


# ====================================================================== status history & onboarding
def _register(c, mobile, ip="10.0.0.1"):
    return c.post("/api/auth/vendor-register", headers={"X-Forwarded-For": ip},
                  json={"business_name": "Hist Store", "full_name": "Hist Owner", "mobile": mobile, "email": "", "password": PW, "confirm_password": PW, "accept_terms": True})


PROFILE = {"business_name": "Hist Store", "contact_person": "Hist Owner", "phone": "9876500001", "address": "12 Market Road, Jaipur", "city": "Jaipur",
           "state": "RJ", "pincode": "302001", "categories": ["Sarees"], "bank_account_name": "Hist Store", "bank_account": "111122223333",
           "ifsc": "SBIN0000001", "agree_terms": True}


def test_onboarding_history_is_recorded_hides_internal_notes_and_locks_edits_during_review(c):
    r = _register(c, "9876500001")
    assert r.status_code == 200
    tok = {"Authorization": f"Bearer {r.json()['token']}"}
    vid = c.portal.call(lambda: db.vendors.find_one({"vendor_code": r.json()["user"]["distributor_id"]}))["id"]
    assert c.put("/api/vendor/me", headers=tok, json={**PROFILE, "submit": True}).json()["vendor"]["status"] == "submitted"
    assert c.put("/api/vendor/me", headers=tok, json={**PROFILE, "address": "Changed address", "submit": False}).status_code == 409    # locked while with the team
    dec = lambda action, **kw: c.post(f"/api/admin/vendors/{vid}/decision", headers=_hdr(S["adm"]["id"]), json={"action": action, **kw})
    assert dec("start_review", internal_note="Looks fine, check GST").status_code == 200
    assert c.put("/api/vendor/me", headers=tok, json={**PROFILE, "address": "Changed again", "submit": False}).status_code == 409           # still locked
    assert dec("reject", reason="Bank proof unclear", internal_note="Suspect duplicate of VD0099").status_code == 200
    me = c.get("/api/vendor/me", headers=tok).json()["vendor"]
    assert me["status"] == "rejected" and me["rejection_reason"] == "Bank proof unclear" and "reviewed_by" not in me
    assert c.put("/api/vendor/me", headers=tok, json={**PROFILE, "submit": True}).json()["vendor"]["status"] == "submitted"                 # resubmission
    mine = c.get("/api/vendor/me/history", headers=tok).json()
    assert [(h["from"], h["to"]) for h in reversed(mine["items"])] == [(None, "draft"), ("draft", "submitted"), ("submitted", "under_review"),
                                                                       ("under_review", "rejected"), ("rejected", "submitted")]
    assert all("internal_note" not in h and "actor" not in h for h in mine["items"]) and mine["terms_version_accepted"] == mine["terms_version_current"]
    admin = c.get(f"/api/admin/vendors/{vid}/history", headers=_hdr(S["adm"]["id"])).json()["items"]
    assert any(h.get("internal_note") == "Suspect duplicate of VD0099" for h in admin)                                                        # admins see it
    assert c.get(f"/api/admin/vendors/{vid}/history", headers=_hdr(S["ua"]["id"])).status_code == 403
    assert dec("approve").status_code == 200 and dec("approve").status_code == 400                                                             # transitions validated


# ====================================================================== documents
def test_documents_cannot_be_self_verified_and_only_the_owner_and_admins_see_them(c):
    h, hb = _hdr(S["ua"]["id"]), _hdr(S["ub"]["id"])
    ok = c.post("/api/vendor/documents", headers=h, json={"type": "pan", "url": "https://cdn.example.com/pan.pdf", "note": "PAN card"})
    assert ok.status_code == 200 and ok.json()["status"] == "submitted"
    did = ok.json()["id"]
    assert c.post("/api/vendor/documents", headers=h, json={"type": "pan", "url": "https://x.example/a.pdf", "status": "verified"}).json()["status"] == "submitted"
    assert c.post("/api/vendor/documents", headers=h, json={"type": "visa", "url": "https://x.example/a.pdf"}).status_code == 400
    assert c.post("/api/vendor/documents", headers=h, json={"type": "pan", "url": "javascript:alert(1)"}).status_code == 422
    assert c.post("/api/vendor/documents", headers=h, json={"type": "pan", "url": "http://insecure.example/a.pdf"}).status_code == 422
    assert c.post("/api/vendor/documents", headers=h, json={"type": "pan", "url": "https://x.example/a.pdf", "expires_at": "2026-13-45"}).status_code == 400
    assert [d["id"] for d in c.get("/api/vendor/documents", headers=hb).json()["items"]] == []                        # vendor B sees nothing of A's
    assert c.delete(f"/api/vendor/documents/{did}", headers=hb).status_code == 404
    rv = lambda who, body: c.post(f"/api/admin/vendor-documents/{did}/review", headers=_hdr(S[who]["id"]), json=body)
    assert rv("ua", {"status": "verified"}).status_code == 403
    assert rv("sup", {"status": "rejected", "note": "x"}).status_code == 400
    assert rv("sup", {"status": "bogus"}).status_code == 400
    assert rv("sup", {"status": "verified"}).json()["status"] == "verified"
    assert c.delete(f"/api/vendor/documents/{did}", headers=h).status_code == 409                                      # verified: cannot be removed
    other = c.post("/api/vendor/documents", headers=h, json={"type": "gst", "url": "/api/files/x/gst.pdf"}).json()["id"]
    assert c.delete(f"/api/vendor/documents/{other}", headers=h).json()["ok"] is True
    assert other not in [d["id"] for d in c.get("/api/vendor/documents", headers=h).json()["items"]]
    assert c.portal.call(lambda: db.vendor_documents.find_one({"id": other}))["deleted"] is True                       # kept for audit
    assert c.portal.call(lambda: db.notifications.count_documents({"user_id": S["ua"]["id"], "title": "Document verified"})) == 1


def test_required_documents_are_unset_by_default_and_enforced_once_an_admin_sets_them(c):
    h = _hdr(S["ub"]["id"])
    req = c.get("/api/vendor/me/requirements", headers=h).json()
    assert req["configured"] is False and "not decided" in req["note"] and req["missing"] == []
    r = _register(c, "9876500002", ip="10.0.0.2")
    tok = {"Authorization": f"Bearer {r.json()['token']}"}
    assert c.put("/api/admin/vendor-policy", headers=_hdr(S["fin"]["id"]), json={"required_documents": ["pan"]}).status_code == 403
    assert c.put("/api/admin/vendor-policy", headers=_hdr(S["adm"]["id"]), json={"required_documents": ["pan", "nonsense"]}).status_code == 400
    assert c.put("/api/admin/vendor-policy", headers=_hdr(S["adm"]["id"]), json={"required_documents": ["pan"]}).status_code == 200
    try:
        sub = c.put("/api/vendor/me", headers=tok, json={**PROFILE, "phone": "9876500002", "submit": True})
        assert sub.status_code == 400 and "pan" in sub.json()["detail"]
        d = c.post("/api/vendor/documents", headers=tok, json={"type": "pan", "url": "https://x.example/pan.pdf"}).json()
        c.portal.call(lambda: db.vendor_documents.update_one({"id": d["id"]}, {"$set": {"status": "rejected"}}))
        assert c.put("/api/vendor/me", headers=tok, json={**PROFILE, "phone": "9876500002", "submit": True}).status_code == 400      # a rejected doc does not count
        c.post("/api/vendor/documents", headers=tok, json={"type": "pan", "url": "https://x.example/pan2.pdf"})
        assert c.put("/api/vendor/me", headers=tok, json={**PROFILE, "phone": "9876500002", "submit": True}).status_code == 200
    finally:
        c.put("/api/admin/vendor-policy", headers=_hdr(S["adm"]["id"]), json={"required_documents": []})


# ====================================================================== bank-detail change
def test_bank_changes_are_reviewed_masked_and_applied_only_on_finance_approval(c):
    h = _hdr(S["ua"]["id"])
    good = {"bank_account_name": "Vendor A", "bank_account": "998877665544", "ifsc": "hdfc0001234", "reason": "Moved to a new bank account"}
    assert c.post("/api/vendor/me/bank-change", headers=h, json={**good, "ifsc": "BAD"}).status_code == 422
    assert c.post("/api/vendor/me/bank-change", headers=h, json={**good, "bank_account": "12 34"}).status_code == 422
    assert c.post("/api/vendor/me/bank-change", headers=_hdr(S["ud"]["id"]), json=good).status_code == 403                    # not an approved vendor
    r = c.post("/api/vendor/me/bank-change", headers=h, json=good)
    assert r.status_code == 200 and r.json()["payload"]["bank_account"].endswith("5544") and "998877" not in r.text and r.json()["payload"]["ifsc"] == "HDFC0001234"
    assert c.post("/api/vendor/me/bank-change", headers=h, json=good).status_code == 409                                         # one at a time
    assert c.get("/api/vendor/me/bank-change", headers=_hdr(S["ub"]["id"])).json()["items"] == []
    rid = r.json()["id"]
    dec = lambda who, body: c.post(f"/api/admin/vendor-change-requests/{rid}/decision", headers=_hdr(S[who]["id"]), json=body)
    assert dec("sup", {"decision": "approve"}).status_code == 403
    assert dec("fin", {"decision": "reject"}).status_code == 400
    assert c.portal.call(lambda: db.vendors.find_one({"id": S["va"]["id"]}))["bank_account"] == "123456789012"           # nothing changed yet
    assert dec("fin", {"decision": "approve", "note": "Verified by call"}).status_code == 200
    v = c.portal.call(lambda: db.vendors.find_one({"id": S["va"]["id"]}))
    assert v["bank_account"] == "998877665544" and v["ifsc"] == "HDFC0001234"
    assert dec("fin", {"decision": "approve"}).status_code == 409
    listing = c.get("/api/admin/vendor-change-requests?status=approved", headers=_hdr(S["fin"]["id"])).json()["items"]
    assert listing and "998877" not in str(listing)                                                                              # admin list is masked too


def test_a_rejected_bank_change_leaves_the_bank_details_untouched(c):
    h = _hdr(S["ub"]["id"])
    r = c.post("/api/vendor/me/bank-change", headers=h, json={"bank_account_name": "Vendor B", "bank_account": "555544443333", "ifsc": "ICIC0000001", "reason": "Switching to another bank"})
    rid = r.json()["id"]
    dec = c.post(f"/api/admin/vendor-change-requests/{rid}/decision", headers=_hdr(S["fin"]["id"]), json={"decision": "reject", "note": "Account name does not match the PAN"})
    assert dec.status_code == 200 and dec.json()["status"] == "rejected"
    assert c.portal.call(lambda: db.vendors.find_one({"id": S["vb"]["id"]}))["bank_account"] == "123456789012"
    mine = c.get("/api/vendor/me/bank-change", headers=h).json()["items"][0]
    assert mine["status"] == "rejected" and mine["admin_note"].startswith("Account name")
    assert c.post("/api/vendor/me/bank-change", headers=h, json={"bank_account_name": "Vendor B", "bank_account": "555544443333", "ifsc": "ICIC0000001",
                                                                 "reason": "Trying again with correct name"}).status_code == 200     # may resubmit after a rejection


# ====================================================================== support tickets
def _ticket(c, vkey="ua", **kw):
    body = {"category": "order", "subject": "Courier problem", "body": "The courier lost the parcel for this order.", **kw}
    return c.post("/api/vendor/support/tickets", headers=_hdr(S[vkey]["id"]), json=body)


def test_support_tickets_flow_with_isolation_urgency_and_a_resolution_note(c):
    r = _ticket(c)
    assert r.status_code == 200 and r.json()["status"] == "open" and r.json()["number"].startswith("TKT")
    tid = r.json()["id"]
    pay = _ticket(c, category="payment", priority="low", subject="Payment missing").json()
    assert pay["urgent"] is True and pay["priority"] == "high"                                                                   # money issues are never 'low'
    assert _ticket(c, category="bogus").status_code == 400 and _ticket(c, priority="urgent").status_code == 400
    assert _ticket(c, attachments=["javascript:alert(1)"]).status_code == 422
    assert _ticket(c, subject="x").status_code == 422
    # related records must belong to the vendor
    own = c.portal.call(lambda: db.products.insert_one({"id": "p-own", "vendor_id": S["va"]["id"], "sku": "T-1", "name": "T"}))
    c.portal.call(lambda: db.products.insert_one({"id": "p-other", "vendor_id": S["vb"]["id"], "sku": "T-2", "name": "T2"}))
    assert _ticket(c, related_type="product", related_id="p-own").json()["related"] == {"type": "product", "id": "p-own"}
    assert _ticket(c, related_type="product", related_id="p-other").status_code == 404
    assert _ticket(c, related_type="product").status_code == 400 and _ticket(c, related_type="thing", related_id="x").status_code == 400
    # isolation
    hb = _hdr(S["ub"]["id"])
    assert c.get(f"/api/vendor/support/tickets/{tid}", headers=hb).status_code == 404
    assert c.post(f"/api/vendor/support/tickets/{tid}/reply", headers=hb, json={"body": "hi"}).status_code == 404
    assert all(t["vendor_id"] == S["vb"]["id"] for t in c.get("/api/vendor/support/tickets", headers=hb).json()["items"])
    assert c.get("/api/vendor/support/tickets", headers=_hdr(S["cust"]["id"])).status_code == 403
    # admin side
    adm = lambda who, body: c.post(f"/api/admin/support/tickets/{tid}/reply", headers=_hdr(S[who]["id"]), json=body)
    assert c.get("/api/admin/support/tickets", headers=_hdr(S["ua"]["id"])).status_code == 403
    first = c.get("/api/admin/support/tickets", headers=_hdr(S["sup"]["id"])).json()["items"][0]
    assert first["urgent"] is True                                                                                                # urgent tickets sort first
    assert adm("sup", {"body": "We are checking with the courier."}).json()["status"] == "in_progress"
    assert adm("sup", {"body": "Done", "status": "resolved"}).status_code == 400                                                 # needs a resolution note
    assert adm("sup", {"body": "Closed it", "status": "closed", "resolution_note": "Refund issued to customer"}).status_code == 400   # in_progress -> closed not allowed
    res = adm("sup", {"body": "Parcel was recovered.", "status": "resolved", "resolution_note": "Parcel recovered and redelivered"}).json()
    assert res["status"] == "resolved" and res["resolution"]["note"].startswith("Parcel")
    back = c.post(f"/api/vendor/support/tickets/{tid}/reply", headers=_hdr(S["ua"]["id"]), json={"body": "Still not received, please check."}).json()
    assert back["status"] == "open" and len(back["messages"]) == 4                                                              # a reply re-opens it
    adm("sup", {"body": "Resolved again", "status": "resolved", "resolution_note": "Second resolution note"})
    assert adm("sup", {"body": "Final", "status": "closed"}).json()["status"] == "closed"
    assert c.post(f"/api/vendor/support/tickets/{tid}/reply", headers=_hdr(S["ua"]["id"]), json={"body": "hello"}).status_code == 409   # closed
    assert c.portal.call(lambda: db.notifications.count_documents({"user_id": S["ua"]["id"], "title": "Support replied"})) >= 3


def test_ticket_creation_is_rate_limited_per_vendor(c):
    c.portal.call(lambda: db.rate_limits.delete_many({}))                       # fresh counters: earlier tests also created tickets
    core.RATE_LIMITS["support_ticket"] = (3, 86400)
    codes = [_ticket(c, vkey="ub", subject=f"Spam {i}").status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    assert _ticket(c, vkey="ua", subject="A is not affected").status_code == 200                                                  # other vendor unaffected


# ====================================================================== notifications
def test_vendor_notifications_are_paginated_filtered_and_private(c):
    for i in range(7):
        c.portal.call(lambda i=i: core.create_notification(S["ua"]["id"], "order" if i % 2 else "stock", f"N{i}", "msg"))
    h = _hdr(S["ua"]["id"])
    first = c.get("/api/vendor/notifications?page=1&page_size=3", headers=h).json()
    assert len(first["items"]) == 3 and first["pages"] >= 3 and first["unread"] >= 7
    assert all(n["type"] == "stock" for n in c.get("/api/vendor/notifications?type=stock&page_size=100", headers=h).json()["items"])
    assert c.get("/api/vendor/notifications?page_size=100000", headers=h).json()["page_size"] == 100                                 # bounded
    assert all(n["user_id"] == S["ua"]["id"] for n in c.get("/api/vendor/notifications?page_size=100", headers=h).json()["items"])
    assert c.get("/api/vendor/notifications", headers=_hdr(S["cust"]["id"])).status_code == 403


# ====================================================================== account security
def test_change_password_revokes_old_sessions_and_enforces_strength(c):
    login = lambda pw: c.post("/api/auth/login", json={"email": "9100000906", "password": pw})
    old = login(PW).json()["token"]
    h = {"Authorization": f"Bearer {old}"}
    put = lambda cur, new: c.put("/api/auth/change-password", headers=h, json={"current_password": cur, "new_password": new})
    assert put("wrong-password", "New-Pass-456x").status_code == 400
    assert put(PW, PW).status_code == 400
    assert put(PW, "short1").status_code == 422 and put(PW, "onlyletters").status_code == 400
    r = put(PW, "New-Pass-456x")
    assert r.status_code == 200
    import time as _t
    _t.sleep(1.1)
    assert c.get("/api/auth/me", headers=h).status_code == 401                                                                   # the old session is signed out
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"}).status_code == 200                    # the fresh one works
    assert login(PW).status_code == 401 and login("New-Pass-456x").status_code == 200
    adm = c.post("/api/auth/login", json={"email": "9100000903", "password": PW}).json()["token"]
    weak = c.put("/api/auth/change-password", headers={"Authorization": f"Bearer {adm}"}, json={"current_password": PW, "new_password": "Simple-Pass-1"})
    assert weak.status_code == 400 and "14" in weak.json()["detail"]                                                              # admins need strong passwords


def test_rate_limits_cap_abuse_per_client_and_never_leak_to_other_clients(c):
    core.RATE_LIMITS["vendor_register"] = (3, 3600)
    codes = [_register(c, f"98765010{i:02d}", ip="203.0.113.9").status_code for i in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    blocked = _register(c, "9876501099", ip="203.0.113.9")
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    assert _register(c, "9876501098", ip="203.0.113.77").status_code == 200                                                         # another client: fine
    core.RATE_LIMITS["login_ip"] = (4, 600)
    res = [c.post("/api/auth/login", headers={"X-Forwarded-For": "198.51.100.5"}, json={"email": f"nobody{i}", "password": "x"}).status_code for i in range(6)]
    assert res[:4] == [401] * 4 and res[4:] == [429, 429]
    core.RATE_LIMITS["admin_login_ip"] = (2, 600)
    ad = [c.post("/api/auth/admin-login", headers={"X-Forwarded-For": "198.51.100.6"}, json={"username": "x", "password": "y"}).status_code for i in range(4)]
    assert ad[2:] == [429, 429]


def test_the_limiter_is_exact_under_concurrency(c):
    core.RATE_LIMITS["forgot_password"] = (5, 3600)
    def hit(_):
        return c.post("/api/auth/forgot/send", headers={"X-Forwarded-For": "192.0.2.50"}, json={"identifier": "nobody", "mobile": "9999999999", "email": "x@y.z"}).status_code
    with ThreadPoolExecutor(max_workers=10) as ex:
        codes = list(ex.map(hit, range(20)))
    assert codes.count(429) == 15 and codes.count(429) + len([x for x in codes if x != 429]) == 20


# ====================================================================== injection / bounds
def test_query_parameters_and_bodies_cannot_inject_operators_or_exhaust_the_server(c):
    h = _hdr(S["ua"]["id"])
    for qs in ('q[$ne]=x', 'status[$ne]=new', 'page[$gt]=0', 'q={"$gt":""}', "q=%24where"):
        assert c.get(f"/api/vendor/orders?page=1&{qs}", headers=h).status_code in (200, 400, 422), qs
        assert c.get(f"/api/vendor/products?page=1&{qs}", headers=h).status_code in (200, 400, 422), qs
    assert c.post("/api/auth/login", json={"email": {"$ne": ""}, "password": {"$ne": ""}}).status_code == 422
    assert c.post("/api/auth/login", json={"email": "9100000905", "password": {"$gt": ""}}).status_code == 422
    for path in ("/api/vendor/orders", "/api/vendor/products", "/api/vendor/finance/ledger", "/api/vendor/returns", "/api/vendor/support/tickets"):
        r = c.get(f"{path}?page=1&page_size=99999", headers=h)
        assert r.status_code == 200 and r.json()["page_size"] == 100, path


# ====================================================================== signed uploads
def _configure_cloudinary():
    os.environ.update({"CLOUDINARY_CLOUD_NAME": "hgtest", "CLOUDINARY_API_KEY": "123456789012345", "CLOUDINARY_API_SECRET": "unit-test-secret-value",
                       "CLOUDINARY_UPLOAD_PRESET": "hg_vendor_signed"})


def _unconfigure():
    for k in ("CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_UPLOAD_PRESET"):
        os.environ.pop(k, None)


def test_signing_is_disabled_until_cloudinary_is_configured_and_never_exposes_the_secret(c):
    h = _hdr(S["ua"]["id"])
    assert c.post("/api/vendor/uploads/sign", headers=h, json={"kind": "product"}).status_code == 503
    _configure_cloudinary()
    try:
        r = c.post("/api/vendor/uploads/sign", headers=h, json={"kind": "product"})
        assert r.status_code == 200
        j = r.json()
        assert "unit-test-secret-value" not in r.text and "api_secret" not in r.text
        p = j["params"]
        assert p["folder"] == f"homegenies/vendors/{S['va']['id']}/products" and p["allowed_formats"] == "jpg,png,webp" and p["overwrite"] == "false"
        assert p["upload_preset"] == "hg_vendor_signed" and len(p["public_id"]) == 32 and "type" not in p
        expect = hashlib.sha1(("&".join(f"{k}={p[k]}" for k in sorted(p)) + "unit-test-secret-value").encode()).hexdigest()
        assert j["signature"] == expect and j["upload_url"] == "https://api.cloudinary.com/v1_1/hgtest/image/upload" and j["max_bytes"] == 5 * 1024 * 1024
        # the client cannot choose the folder / id
        forged = c.post("/api/vendor/uploads/sign", headers=h, json={"kind": "product", "folder": "homegenies/vendors/someone-else", "public_id": "x"}).json()
        assert forged["params"]["folder"].startswith(f"homegenies/vendors/{S['va']['id']}/")
        doc = c.post("/api/vendor/uploads/sign", headers=h, json={"kind": "document"}).json()
        assert doc["params"]["type"] == "authenticated" and "pdf" in doc["params"]["allowed_formats"] and doc["params"]["folder"].endswith("/documents")
        assert c.post("/api/vendor/uploads/sign", headers=h, json={"kind": "video"}).status_code == 400
        for who in ("cust", "ud"):
            assert c.post("/api/vendor/uploads/sign", headers=_hdr(S[who]["id"]), json={}).status_code == 403
        assert c.post("/api/vendor/uploads/sign", json={}).status_code == 401
        core.RATE_LIMITS["upload_sign"] = (2, 3600)
        codes = [c.post("/api/vendor/uploads/sign", headers=_hdr(S["ub"]["id"]), json={"kind": "product"}).status_code for _ in range(4)]
        assert codes == [200, 200, 429, 429]
    finally:
        _unconfigure()


def test_cloudinary_images_must_be_in_the_vendors_own_folder_and_legacy_values_keep_working(c):
    h = _hdr(S["ua"]["id"])
    base = {"name": "Img check", "mrp": 500, "selling_price": 400, "category": "Sarees", "stock": 1}
    mine = f"https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/vendors/{S['va']['id']}/products/abc.jpg"
    theirs = f"https://res.cloudinary.com/hgtest/image/upload/v1/homegenies/vendors/{S['vb']['id']}/products/abc.jpg"
    other_cloud = f"https://res.cloudinary.com/evil/image/upload/v1/homegenies/vendors/{S['va']['id']}/products/abc.jpg"
    post = lambda sku, img: c.post("/api/vendor/products", headers=h, json={**base, "sku": sku, "images": [img]})
    assert post("CL-0", theirs).status_code == 200                                                         # not configured yet: legacy behaviour (any https)
    _configure_cloudinary()
    try:
        assert post("CL-1", mine).status_code == 200
        assert post("CL-2", theirs).status_code == 400 and "does not belong" in post("CL-2", theirs).json()["detail"]
        assert post("CL-3", other_cloud).status_code == 400
        assert post("CL-4", "http://res.cloudinary.com/hgtest/image/upload/x.jpg").status_code == 422
        for legacy in ("/api/files/homegenies/vendor/x.png", "/brand/pillar-sarees.jpg", "https://cdn.example.com/a.jpg"):
            assert post(f"CL-L{abs(hash(legacy)) % 9999}", legacy).status_code == 200, legacy             # existing paths and hosts are untouched
        p = c.portal.call(lambda: db.products.find_one({"sku": "CL-1"}))
        assert c.put(f"/api/vendor/products/{p['id']}", headers=h, json={**base, "sku": "CL-1", "images": [theirs]}).status_code == 400
        assert c.put(f"/api/vendor/products/{p['id']}", headers=h, json={**base, "sku": "CL-1", "images": [mine]}).status_code == 200
    finally:
        _unconfigure()


def test_contact_verification_status_is_honest_about_missing_providers(c):
    v = c.get("/api/vendor/me/verification", headers=_hdr(S["ua"]["id"])).json()
    assert v["mobile"]["provider_available"] is False and v["note"] and v["mobile"]["verified"] is False
