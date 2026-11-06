"""Vendor Pillar: public "Apply to sell" and the admin applications inbox (OWNER-LOCKED Option B).

The application creates NO user, NO vendor, NO session; the public answer is neutral (no account enumeration); one open application
per mobile, race-safe; honeypot and rate limit; super_admin/admin manage, support_admin reads, accounts_admin has no access;
conversion never touches an existing account and is idempotent.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`).
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_applications_test", "JWT_SECRET": "vendor-apps-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
for k in ("WEBHOOK_CRON_SECRET", "ADMIN_EMAIL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_UPLOAD_PRESET"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import core  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
PW = "Admin-Pass-123"
_seq = iter(range(10000, 99999))


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


def _app(**over):
    n = next(_seq)
    return {"business_name": f"Weavers {n}", "business_type": "proprietorship", "description": "Handloom cotton sarees made in our own unit.",
            "categories": ["Sarees"], "contact_name": "Meera Devi", "mobile": f"94{n:08d}", "email": f"weavers{n}@example.test",
            "city": "Varanasi", "state": "Uttar Pradesh", "website": "", "consent": True, **over}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        core.RATE_LIMITS["vendor_apply"] = (10000, 3600)        # the limiter has its own test
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, mobile, status in (("super", "super_admin", "9100008001", "green"), ("admin", "admin", "9100008002", "green"),
                                              ("support", "support_admin", "9100008003", "green"), ("fin", "accounts_admin", "9100008004", "green"),
                                              ("genie", "distributor", "9100008005", "green"), ("cust", "distributor", "9100008006", "red")):
                u = {"id": new_id(), "distributor_id": f"AP{mobile[-4:]}", "full_name": key, "mobile": mobile, "email": f"{key}@example.test",
                     "password_hash": hash_password(PW), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _counts(c):
    return _run(c, lambda: _gather())


async def _gather():
    return {"users": await db.users.count_documents({}), "vendors": await db.vendors.count_documents({}),
            "apps": await db.vendor_applications.count_documents({})}


# ================================================================ public application
def test_an_application_is_recorded_and_creates_no_user_vendor_or_session(c):
    before = _counts(c)
    body = _app(website="https://weavers.example.test")
    r = c.post("/api/vendor-applications", json=body)
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"ok", "message"} and "token" not in r.text
    after = _counts(c)
    assert after == {**before, "apps": before["apps"] + 1}
    a = _run(c, lambda: db.vendor_applications.find_one({"mobile": body["mobile"]}, {"_id": 0}))
    assert a["status"] == "new" and a["number"].startswith("VA") and a["categories"] == ["Sarees"] and a["open_mobile"] == body["mobile"]
    assert a["website"] == "https://weavers.example.test" and a["history"][0]["action"] == "submitted"


@pytest.mark.parametrize("who", ("genie", "cust", "super"))
def test_the_answer_is_identical_for_existing_accounts_and_nothing_is_touched(c, who):
    fresh = c.post("/api/vendor-applications", json=_app()).json()
    existing = S[who]
    before_user = _run(c, lambda: db.users.find_one({"id": existing["id"]}, {"_id": 0}))
    for clash in ({"mobile": existing["mobile"]}, {"email": existing["email"]}):
        r = c.post("/api/vendor-applications", json=_app(**clash))
        assert r.status_code == 200 and r.json() == fresh                      # no account enumeration
    assert _run(c, lambda: db.users.find_one({"id": existing["id"]}, {"_id": 0})) == before_user


def test_a_second_open_application_for_the_same_mobile_is_absorbed_neutrally(c):
    body = _app()
    first = c.post("/api/vendor-applications", json=body).json()
    again = c.post("/api/vendor-applications", json={**body, "business_name": "Other name"})
    assert again.status_code == 200 and again.json() == first
    assert _run(c, lambda: db.vendor_applications.count_documents({"mobile": body["mobile"]})) == 1


def test_simultaneous_applications_for_one_mobile_store_exactly_one(c):
    body = _app()
    with ThreadPoolExecutor(max_workers=8) as ex:
        codes = list(ex.map(lambda _: c.post("/api/vendor-applications", json=body).status_code, range(8)))
    assert codes == [200] * 8
    assert _run(c, lambda: db.vendor_applications.count_documents({"mobile": body["mobile"]})) == 1


def test_the_honeypot_stores_nothing_and_answers_the_same(c):
    before = _counts(c)
    r = c.post("/api/vendor-applications", json=_app(company_fax="http://spam.example"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _counts(c) == before


@pytest.mark.parametrize("over,code", [
    ({"mobile": "12345"}, 400), ({"mobile": "5123456789"}, 400), ({"email": "nope"}, 400), ({"business_type": "empire"}, 400),
    ({"categories": ["Toys"]}, 400), ({"categories": []}, 422), ({"state": "Atlantis"}, 400), ({"website": "http://insecure.example"}, 400),
    ({"consent": False}, 400), ({"description": "too short"}, 422), ({"business_name": "<script>x</script>"}, 400), ({"business_name": "x"}, 422)])
def test_invalid_applications_are_refused_and_store_nothing(c, over, code):
    before = _counts(c)
    assert c.post("/api/vendor-applications", json=_app(**over)).status_code == code
    assert _counts(c) == before


def test_applications_are_rate_limited_per_client(c):
    core.RATE_LIMITS["vendor_apply"] = (3, 3600)
    try:
        codes = [c.post("/api/vendor-applications", headers={"X-Forwarded-For": "198.51.100.90"}, json=_app()).status_code for _ in range(5)]
        assert codes == [200, 200, 200, 429, 429]
        assert c.post("/api/vendor-applications", headers={"X-Forwarded-For": "198.51.100.91"}, json=_app()).status_code == 200
    finally:
        core.RATE_LIMITS["vendor_apply"] = (10000, 3600)


def test_the_retired_instant_sign_up_is_gone(c):
    before = _counts(c)
    r = c.post("/api/auth/vendor-register", json={"business_name": "Shop", "full_name": "A B", "mobile": "9400000001", "password": "Abcdefg1",
                                                  "confirm_password": "Abcdefg1", "accept_terms": True})
    assert r.status_code == 404 and _counts(c) == before


# ================================================================ admin inbox: who may do what
def _new_app_id(c, **over):
    body = _app(**over)
    c.post("/api/vendor-applications", json=body)
    return _run(c, lambda: db.vendor_applications.find_one({"mobile": body["mobile"]}, {"_id": 0}))["id"]


@pytest.mark.parametrize("who", ("super", "admin", "support"))
def test_super_admin_admin_and_support_can_read_the_inbox(c, who):
    aid = _new_app_id(c)
    lst = c.get("/api/admin/vendor-applications", headers=_hdr(who))
    assert lst.status_code == 200 and any(i["id"] == aid for i in lst.json()["items"]) and "open_mobile" not in lst.text
    assert c.get(f"/api/admin/vendor-applications/{aid}", headers=_hdr(who)).status_code == 200


@pytest.mark.parametrize("who", ("fin", "genie"))
def test_accounts_admin_and_users_cannot_read_the_inbox(c, who):
    aid = _new_app_id(c)
    assert c.get("/api/admin/vendor-applications", headers=_hdr(who)).status_code == 403
    assert c.get(f"/api/admin/vendor-applications/{aid}", headers=_hdr(who)).status_code == 403


@pytest.mark.parametrize("who", ("support", "fin"))
@pytest.mark.parametrize("action", ("review", "decline", "duplicate", "convert"))
def test_support_and_accounts_cannot_act_on_applications(c, who, action):
    aid = _new_app_id(c)
    before = _run(c, lambda: db.vendor_applications.find_one({"id": aid}, {"_id": 0}))
    r = c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr(who), json={"action": action, "reason": "Not suitable now"})
    assert r.status_code == 403
    assert c.put(f"/api/admin/vendor-applications/{aid}", headers=_hdr(who), json={"city": "Agra"}).status_code == 403
    assert _run(c, lambda: db.vendor_applications.find_one({"id": aid}, {"_id": 0})) == before
    assert _run(c, lambda: db.vendors.count_documents({"application_id": aid})) == 0


def test_search_and_status_filters(c):
    aid = _new_app_id(c, business_name="Unique Loom House")
    found = c.get("/api/admin/vendor-applications", headers=_hdr("admin"), params={"q": "unique loom"}).json()
    assert [i["id"] for i in found["items"]] == [aid] and found["counts"]["new"] >= 1
    assert c.get("/api/admin/vendor-applications", headers=_hdr("admin"), params={"status": "bogus"}).status_code == 400


def test_review_decline_and_duplicate(c):
    aid = _new_app_id(c)
    assert c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "review"}).json()["status"] == "in_review"
    assert c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "decline", "reason": "x"}).status_code == 400
    d = c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "decline", "reason": "Products outside our pillars"})
    assert d.status_code == 200 and d.json()["status"] == "declined" and d.json()["decline_reason"] == "Products outside our pillars"
    assert c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "decline", "reason": "Again declined"}).status_code == 409
    # a declined application frees the mobile: the applicant may apply again later
    mobile = d.json()["mobile"]
    c.post("/api/vendor-applications", json=_app(mobile=mobile))
    assert _run(c, lambda: db.vendor_applications.count_documents({"mobile": mobile})) == 2
    first = _new_app_id(c)
    num = _run(c, lambda: db.vendor_applications.find_one({"id": first}, {"_id": 0, "number": 1}))["number"]
    dup = _new_app_id(c)
    assert c.post(f"/api/admin/vendor-applications/{dup}/action", headers=_hdr("super"), json={"action": "duplicate", "duplicate_of": "VA999999"}).status_code == 400
    r = c.post(f"/api/admin/vendor-applications/{dup}/action", headers=_hdr("super"), json={"action": "duplicate", "duplicate_of": num})
    assert r.status_code == 200 and r.json()["status"] == "duplicate" and r.json()["duplicate_of"] == num


# ================================================================ conversion into onboarding
def test_conversion_creates_an_onboarding_vendor_and_a_pending_owner_that_cannot_sign_in(c):
    aid = _new_app_id(c)
    r = c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["status"] == "converted" and a["vendor_id"] and a["converted_vendor_id"] == a["vendor_id"]
    v = _run(c, lambda: db.vendors.find_one({"id": a["vendor_id"]}, {"_id": 0}))
    assert v["status"] == "onboarding" and v["application_id"] == aid and v["onboarding"]["business"]["legal_name"] == a["business_name"]
    owner = _run(c, lambda: db.users.find_one({"id": v["user_id"]}, {"_id": 0}))
    assert owner["role"] == "vendor" and owner["account_status"] == "pending_approval" and owner["status"] != "green"
    assert _run(c, lambda: db.account_invitations.count_documents({"vendor_id": v["id"]})) == 0       # no invitation before approval
    assert c.post("/api/auth/login", json={"email": a["mobile"], "password": "anything1"}).status_code in (401, 403)
    assert c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"}).status_code == 409


@pytest.mark.parametrize("who", ("genie", "cust", "super"))
def test_conversion_is_refused_when_the_contact_belongs_to_an_existing_account(c, who):
    existing = S[who]
    before = _run(c, lambda: db.users.find_one({"id": existing["id"]}, {"_id": 0}))
    _run(c, lambda: db.vendor_applications.insert_one({"id": new_id(), "number": f"VAX{next(_seq)}", **{k: v for k, v in _app(mobile=existing["mobile"]).items() if k != "consent"},
                                                       "status": "new", "history": [], "created_at": now_iso(), "updated_at": now_iso()}))
    aid = _run(c, lambda: db.vendor_applications.find_one({"mobile": existing["mobile"], "status": "new"}, {"_id": 0}))["id"]
    detail = c.get(f"/api/admin/vendor-applications/{aid}", headers=_hdr("admin")).json()
    assert detail["existing_account"] and "mobile" in detail["existing_account"]["matches"]          # shown to admins only
    r = c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"})
    assert r.status_code == 409
    assert _run(c, lambda: db.users.find_one({"id": existing["id"]}, {"_id": 0})) == before
    assert _run(c, lambda: db.vendor_applications.find_one({"id": aid}, {"_id": 0}))["status"] == "new"
    # the admin replaces the contact with the business's own number; then conversion works
    ok = c.put(f"/api/admin/vendor-applications/{aid}", headers=_hdr("admin"), json={"mobile": f"95{next(_seq):08d}", "email": "", "note": "Business number"})
    assert ok.status_code == 200
    assert c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"}).status_code == 200
    assert _run(c, lambda: db.users.find_one({"id": existing["id"]}, {"_id": 0})) == before


def test_simultaneous_conversions_create_one_vendor(c):
    aid = _new_app_id(c)
    with ThreadPoolExecutor(max_workers=6) as ex:
        codes = list(ex.map(lambda _: c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"}).status_code, range(6)))
    assert codes.count(200) == 1 and codes.count(409) == 5, codes
    assert _run(c, lambda: db.vendors.count_documents({"application_id": aid})) == 1
    assert _run(c, lambda: db.users.count_documents({"vendor_application_id": aid})) == 1


def test_an_interrupted_conversion_is_completed_by_a_retry_without_duplicates(c):
    aid = _new_app_id(c)
    app = _run(c, lambda: db.vendor_applications.find_one({"id": aid}, {"_id": 0}))
    import vendor_onboarding
    # simulate a crash after the owner account and the vendor were created but before the application was closed
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    _run(c, lambda: db.vendor_applications.update_one({"id": aid}, {"$set": {"status": "converting", "converting_at": old}}))
    _run(c, lambda: vendor_onboarding.create_onboarding_vendor(business_name=app["business_name"], contact_name=app["contact_name"],
                                                              mobile=app["mobile"], email=app["email"], admin=S["admin"], application=app))
    r = c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"})
    assert r.status_code == 200 and r.json()["status"] == "converted"
    assert any(h["action"] == "conversion_resumed" for h in r.json()["history"])
    assert _run(c, lambda: db.vendors.count_documents({"application_id": aid})) == 1
    assert _run(c, lambda: db.users.count_documents({"vendor_application_id": aid})) == 1


def test_editing_cannot_take_another_open_applications_mobile(c):
    a1, a2 = _new_app_id(c), _new_app_id(c)
    m1 = _run(c, lambda: db.vendor_applications.find_one({"id": a1}, {"_id": 0, "mobile": 1}))["mobile"]
    assert c.put(f"/api/admin/vendor-applications/{a2}", headers=_hdr("admin"), json={"mobile": m1}).status_code == 409


def test_a_conversion_in_progress_is_not_resumed_by_another_request(c):
    aid = _new_app_id(c)
    _run(c, lambda: db.vendor_applications.update_one({"id": aid}, {"$set": {"status": "converting", "converting_at": now_iso()}}))
    assert c.post(f"/api/admin/vendor-applications/{aid}/action", headers=_hdr("admin"), json={"action": "convert"}).status_code == 409
    assert _run(c, lambda: db.vendors.count_documents({"application_id": aid})) == 0
