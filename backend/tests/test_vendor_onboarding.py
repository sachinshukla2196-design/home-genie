"""Vendor Pillar: admin onboarding, the backend checklist, super-admin final review, owner activation, sign-in gates and identity.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`).
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_onboarding_test", "JWT_SECRET": "vendor-onboarding-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
for k in ("WEBHOOK_CRON_SECRET", "ADMIN_EMAIL", "CLOUDINARY_CLOUD_NAME", "CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_UPLOAD_PRESET"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import core  # noqa: E402
import auth_routes  # noqa: E402
import vendor_onboarding as VO  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
PW = "Admin-Pass-123"
OWNER_PW = "Owner-Pass-123"
_seq = iter(range(10000, 99999))


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        core.RATE_LIMITS["staff_accept"] = (10000, 3600)
        core.RATE_LIMITS["forgot_password"] = (10000, 3600)
        core.RATE_LIMITS["login_ip"] = (10000, 600)
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, mobile in (("super", "super_admin", "9100009001"), ("super2", "super_admin", "9100009007"), ("admin", "admin", "9100009002"),
                                      ("support", "support_admin", "9100009003"), ("fin", "accounts_admin", "9100009004")):
                u = {"id": new_id(), "distributor_id": f"OB{mobile[-4:]}", "full_name": key, "mobile": mobile, "email": f"{key}@example.test",
                     "password_hash": hash_password(PW), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _create(c):
    n = next(_seq)
    mobile = f"96{n:08d}"
    r = c.post("/api/admin/vendors/create", headers=_hdr("admin"),
               json={"business_name": f"Onboard {n}", "full_name": "Kavya Rao", "mobile": mobile, "email": f"owner{n}@example.test"})
    assert r.status_code == 200, r.text
    return {**r.json(), "mobile": mobile, "email": f"owner{n}@example.test", "n": n}


def _sections(v, business_type="proprietorship", gst=True, signatory=True):
    pan = "ABCDE1234F"
    sec = {
        "business": {"legal_name": f"Onboard {v['n']} Traders", "display_name": f"Onboard {v['n']}", "business_type": business_type,
                     "supplier_roles": ["manufacturer", "wholesaler"], "description": "Cotton and silk sarees from our looms in Surat.",
                     "categories": ["Sarees", "Fashion Products"], "year_established": 2012},
        "person": {"full_name": "Kavya Rao", "designation": "Proprietor", "mobile": v["mobile"], "email": v["email"], "relationship": "proprietor",
                   "is_authorised_signatory": signatory, **({} if signatory else {"signatory_name": "Ravi Rao"})},
        "legal": {"pan": pan, "gst_registered": gst, **({"gstin": "24ABCDE1234F1Z5"} if gst else {"gst_exemption_declared": True})},
        "addresses": {"registered": {"line1": "4 Ring Road", "city": "Surat", "state": "Gujarat", "pincode": "395002"},
                      "pickup_same_as": "registered", "return_same_as": "pickup", "pickup_contact_name": "Kavya Rao", "pickup_contact_phone": v["mobile"]},
        "operations": {"handling_days": 2, "support_phone": v["mobile"], "support_hours": "Mon-Sat 10am-7pm", "packaging_by": "vendor", "shipping_by": "vendor"},
        "bank": {"account_holder": f"Onboard {v['n']} Traders", "bank_name": "HDFC Bank", "account_number": "50100123456789",
                 "account_number_confirm": "50100123456789", "ifsc": "HDFC0001234", "account_type": "current"},
    }
    if business_type == "private_limited":
        sec["legal"]["cin"] = "U17110GJ2012PTC012345"
    if business_type == "llp":
        sec["legal"]["llpin"] = "AAB-1234"
    return sec


def _save_all(c, v, **kw):
    for key, data in _sections(v, **kw).items():
        r = c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/{key}", headers=_hdr("admin"), json=data)
        assert r.status_code == 200, (key, r.text)
    return r.json()


def _docs(c, v, types, verify=True):
    for t in types:
        d = c.post(f"/api/admin/vendors/{v['vendor_id']}/onboarding/documents", headers=_hdr("admin"), json={"type": t, "url": f"https://cdn.example.test/{t}.png"})
        assert d.status_code == 200, d.text
        if verify:
            assert c.post(f"/api/admin/vendor-documents/{d.json()['id']}/review", headers=_hdr("support"), json={"status": "verified"}).status_code == 200


def _agreement(c, v):
    eff = (date.today() + timedelta(days=1)).isoformat()
    a = c.post(f"/api/admin/finance/vendors/{v['vendor_id']}/agreements", headers=_hdr("fin"),
               json={"commission_pct": 12.5, "fixed_fee_paise": 0, "settlement_schedule": "monthly", "effective_from": eff})
    assert a.status_code == 200, a.text
    assert c.post(f"/api/admin/finance/agreements/{a.json()['id']}/approve", headers=_hdr("super")).status_code == 200


BASE_DOCS = ("pan", "bank_proof", "address_proof", "identity", "gst")


def _ready(c):
    """A complete registration submitted for final approval."""
    v = _create(c)
    _save_all(c, v)
    _docs(c, v, BASE_DOCS)
    _agreement(c, v)
    r = c.post(f"/api/admin/vendors/{v['vendor_id']}/submit-for-approval", headers=_hdr("admin"))
    assert r.status_code == 200, r.text
    assert r.json()["vendor"]["status"] == "ready_for_review"
    return v


def _snapshot(c, vid):
    async def go():
        v = await db.vendors.find_one({"id": vid}, {"_id": 0})
        return {"vendor": v, "owner": await db.users.find_one({"id": v["user_id"]}, {"_id": 0}),
                "invites": await db.account_invitations.count_documents({"vendor_id": vid}),
                "history": await db.vendor_status_history.count_documents({"vendor_id": vid})}
    return _run(c, go)


# ================================================================ sections and the checklist
def test_sections_save_progress_and_the_checklist_reports_what_is_missing(c):
    v = _create(c)
    g = c.get(f"/api/admin/vendors/{v['vendor_id']}/onboarding", headers=_hdr("admin")).json()
    assert g["vendor"]["status"] == "onboarding" and g["checklist"]["complete"] is False
    biz = next(s for s in g["checklist"]["sections"] if s["key"] == "business")
    assert "Business type" in biz["missing"]
    part = c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/business", headers=_hdr("admin"), json={"business_type": "llp"})
    assert part.status_code == 200 and part.json()["onboarding"]["business"]["business_type"] == "llp"          # partial save works
    after = _save_all(c, v)
    secs = {s["key"]: s for s in after["checklist"]["sections"]}
    assert all(secs[k]["complete"] for k in ("business", "person", "legal", "addresses", "operations", "bank")), secs
    assert not secs["documents"]["complete"] and not secs["commercial"]["complete"]
    assert after["onboarding"]["bank"]["account_number"].endswith("6789") and "50100123456789" not in str(after)   # masked
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/submit-for-approval", headers=_hdr("admin")).status_code == 400
    # the platform fields the rest of the system reads are kept in step
    vv = _run(c, lambda: db.vendors.find_one({"id": v["vendor_id"]}, {"_id": 0}))
    assert vv["business_name"] == f"Onboard {v['n']}" and vv["categories"] == ["Sarees", "Fashion Products"] and vv["ifsc"] == "HDFC0001234"
    assert vv["return_address"].startswith("4 Ring Road") and vv["gstin"] == "24ABCDE1234F1Z5"


@pytest.mark.parametrize("section,data", [
    ("business", {"categories": ["Toys"]}), ("business", {"business_type": "empire"}), ("business", {"year_established": 1800}),
    ("business", {"website": "http://insecure.example"}), ("business", {"description": "short"}),
    ("person", {"mobile": "12345"}), ("person", {"email": "nope"}),
    ("legal", {"pan": "ABC"}), ("legal", {"pan": "ABCDE1234F", "gstin": "24ZZZZZ9999Z1Z5"}),          # GSTIN must contain the PAN
    ("legal", {"cin": "123"}), ("legal", {"llpin": "12-34"}),
    ("addresses", {"registered": {"pincode": "012345"}}), ("addresses", {"registered": {"state": "Atlantis"}}),
    ("addresses", {"pickup_same_as": "return"}),
    ("operations", {"handling_days": 40}), ("operations", {"packaging_by": "someone"}),
    ("bank", {"account_number": "12345678", "account_number_confirm": "12345679"}), ("bank", {"ifsc": "BAD"})])
def test_section_formats_are_validated_on_the_server(c, section, data):
    v = _create(c)
    assert c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/{section}", headers=_hdr("admin"), json=data).status_code == 400


def test_documents_follow_required_conditional_optional_rules(c):
    v = _create(c)
    _save_all(c, v, business_type="private_limited", gst=False, signatory=False)
    rules = c.get(f"/api/admin/vendors/{v['vendor_id']}/onboarding", headers=_hdr("admin")).json()["checklist"]["documents"]
    assert rules["required"] == ["pan", "bank_proof", "address_proof", "identity"]
    assert {c_["type"] for c_ in rules["conditional"]} == {"business_registration", "authorisation_letter"}       # not GST: not registered
    assert "gst" in rules["optional"] and "other" in rules["optional"]
    # an uploaded but unverified document does not count; a rejected one does not count
    _docs(c, v, ("pan", "bank_proof", "address_proof", "identity", "business_registration"), verify=True)
    _docs(c, v, ("authorisation_letter",), verify=False)
    docs = next(s for s in c.get(f"/api/admin/vendors/{v['vendor_id']}/onboarding", headers=_hdr("admin")).json()["checklist"]["sections"] if s["key"] == "documents")
    assert docs["missing"] == ["Authorisation letter for the signatory (uploaded, awaiting verification)"]


def test_a_complete_registration_can_be_submitted_and_is_then_locked(c):
    v = _ready(c)
    assert c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/business", headers=_hdr("admin"), json={"display_name": "Changed"}).status_code == 409
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/onboarding/documents", headers=_hdr("admin"), json={"type": "other", "url": "https://x.example/o.png"}).status_code == 409
    hist = c.get(f"/api/admin/vendors/{v['vendor_id']}/onboarding", headers=_hdr("admin")).json()["history"]
    assert [(h["from"], h["to"]) for h in hist] == [(None, "onboarding"), ("onboarding", "ready_for_review")]


@pytest.mark.parametrize("who", ("support", "fin"))
def test_support_and_accounts_cannot_edit_or_submit_onboarding(c, who):
    v = _create(c)
    before = _snapshot(c, v["vendor_id"])
    assert c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/business", headers=_hdr(who), json={"display_name": "Nope"}).status_code == 403
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/onboarding/documents", headers=_hdr(who), json={"type": "pan", "url": "https://x.example/p.png"}).status_code == 403
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/submit-for-approval", headers=_hdr(who)).status_code == 403
    assert _snapshot(c, v["vendor_id"]) == before
    view = c.get(f"/api/admin/vendors/{v['vendor_id']}/onboarding", headers=_hdr(who))
    assert view.status_code == (200 if who == "support" else 403)                            # support may look; accounts may not


def test_the_owner_login_contact_follows_the_registration_but_never_takes_an_existing_account(c):
    v = _create(c)
    other = _create(c)
    clash = c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/person", headers=_hdr("admin"), json={"mobile": other["mobile"]})
    assert clash.status_code == 409
    admin_clash = c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/person", headers=_hdr("admin"), json={"email": S["admin"]["email"]})
    assert admin_clash.status_code == 409
    new_mobile = f"97{next(_seq):08d}"
    assert c.put(f"/api/admin/vendors/{v['vendor_id']}/onboarding/person", headers=_hdr("admin"), json={"mobile": new_mobile}).status_code == 200
    owner = _run(c, lambda: db.users.find_one({"id": v["user_id"]}, {"_id": 0}))
    assert owner["mobile"] == new_mobile and owner["account_status"] == "pending_approval"


# ================================================================ final review: super admin only
@pytest.mark.parametrize("who", ("admin", "support", "fin"))
@pytest.mark.parametrize("action", ("approve", "request_changes", "reject"))
def test_only_super_admin_makes_the_final_decision(c, who, action):
    v = _ready(c)
    before = _snapshot(c, v["vendor_id"])
    r = c.post(f"/api/admin/vendors/{v['vendor_id']}/final-review", headers=_hdr(who), json={"action": action, "reason": "Needs more detail"})
    assert r.status_code == 403
    assert _snapshot(c, v["vendor_id"]) == before
    # the generic decision route cannot be used to skip the onboarding review either
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/decision", headers=_hdr("super"), json={"action": "approve"}).status_code == 409


def test_approval_activates_the_owner_through_one_invitation(c):
    v = _ready(c)
    r = c.post(f"/api/admin/vendors/{v['vendor_id']}/final-review", headers=_hdr("super"), json={"action": "approve"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["vendor"]["status"] == "approved" and body["invitation"]["status"] == "invited" and body["invitation"]["token"]
    snap = _snapshot(c, v["vendor_id"])
    assert snap["owner"]["account_status"] == "invited" and snap["invites"] == 1 and snap["vendor"]["owner_activation"] == "invited"
    # still no sign-in until the owner accepts
    assert c.post("/api/auth/login", json={"email": v["email"], "password": OWNER_PW}).status_code in (401, 403)
    assert c.post("/api/vendor/invitation/owner/accept", json={"token": body["invitation"]["token"], "password": OWNER_PW}).status_code == 200
    login = c.post("/api/auth/login", json={"email": v["email"], "password": OWNER_PW})
    assert login.status_code == 200 and login.json()["user"]["role"] == "vendor" and login.json()["user"]["status"] != "green"
    tok = {"Authorization": f"Bearer {login.json()['token']}"}
    me = c.get("/api/vendor/me", headers=tok).json()["vendor"]
    assert me["status"] == "approved" and "onboarding" not in me and "50100123456789" not in str(me)
    assert c.get("/api/vendor/products", headers=tok).status_code == 200                              # operational panel
    assert _run(c, lambda: db.vendors.find_one({"id": v["vendor_id"]}, {"_id": 0}))["owner_activation"] == "active"
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/final-review", headers=_hdr("super"), json={"action": "approve"}).status_code == 409


def test_simultaneous_approvals_issue_exactly_one_invitation(c):
    v = _ready(c)
    with ThreadPoolExecutor(max_workers=6) as ex:
        res = list(ex.map(lambda k: c.post(f"/api/admin/vendors/{v['vendor_id']}/final-review", headers=_hdr(k), json={"action": "approve"}),
                          ["super", "super2"] * 3))
    codes = [r.status_code for r in res]
    assert codes.count(200) == 1 and codes.count(409) == 5, codes
    snap = _snapshot(c, v["vendor_id"])
    assert snap["invites"] == 1 and snap["history"] == 3              # created, submitted, approved: one approval only


def test_an_approval_interrupted_before_the_invitation_is_repaired_once(c):
    v = _ready(c)
    vend = _run(c, lambda: db.vendors.find_one({"id": v["vendor_id"]}, {"_id": 0}))
    import vendor_lifecycle
    _run(c, lambda: vendor_lifecycle.move(vend, "approved", "super_admin", S["super"]["id"], "Final approval", extra={"owner_activation": "pending"}))
    assert _snapshot(c, v["vendor_id"])["invites"] == 0                                  # crash: approved, no invitation yet
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/owner-access", headers=_hdr("admin"), json={}).status_code == 403
    with ThreadPoolExecutor(max_workers=5) as ex:
        res = list(ex.map(lambda _: c.post(f"/api/admin/vendors/{v['vendor_id']}/owner-access", headers=_hdr("super"), json={}), range(5)))
    assert all(r.status_code == 200 for r in res)
    assert sum(1 for r in res if r.json().get("token")) == 1                             # exactly one invitation issued
    assert _snapshot(c, v["vendor_id"])["invites"] == 1
    # a claim left behind by a crash mid-issue is taken over only once it is stale
    _run(c, lambda: db.vendors.update_one({"id": v["vendor_id"]}, {"$set": {"owner_activation": "issuing", "owner_activation_claimed_at": now_iso()}}))
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/owner-access", headers=_hdr("super"), json={}).json()["token"] is None
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    _run(c, lambda: db.vendors.update_one({"id": v["vendor_id"]}, {"$set": {"owner_activation_claimed_at": old}}))
    assert c.post(f"/api/admin/vendors/{v['vendor_id']}/owner-access", headers=_hdr("super"), json={}).json()["token"]
    assert _run(c, lambda: db.account_invitations.count_documents({"vendor_id": v["vendor_id"], "status": "pending"})) == 1


def test_request_changes_returns_to_onboarding_and_reject_is_final_until_reopened(c):
    v = _ready(c)
    vid = v["vendor_id"]
    assert c.post(f"/api/admin/vendors/{vid}/final-review", headers=_hdr("super"), json={"action": "request_changes", "reason": "x"}).status_code == 400
    back = c.post(f"/api/admin/vendors/{vid}/final-review", headers=_hdr("super"), json={"action": "request_changes", "reason": "Upload a clearer PAN"})
    assert back.status_code == 200 and back.json()["vendor"]["status"] == "onboarding" and back.json()["vendor"]["review_feedback"] == "Upload a clearer PAN"
    assert c.put(f"/api/admin/vendors/{vid}/onboarding/business", headers=_hdr("admin"), json={"display_name": "Clearer Store"}).status_code == 200
    assert c.post(f"/api/admin/vendors/{vid}/submit-for-approval", headers=_hdr("admin")).status_code == 200
    rej = c.post(f"/api/admin/vendors/{vid}/final-review", headers=_hdr("super"), json={"action": "reject", "reason": "Products are not original"})
    assert rej.status_code == 200 and rej.json()["vendor"]["status"] == "rejected"
    assert _snapshot(c, vid)["owner"]["account_status"] == "pending_approval" and _snapshot(c, vid)["invites"] == 0
    assert c.post(f"/api/admin/vendors/{vid}/final-review", headers=_hdr("admin"), json={"action": "reopen"}).status_code == 403
    assert c.post(f"/api/admin/vendors/{vid}/final-review", headers=_hdr("super"), json={"action": "reopen"}).json()["vendor"]["status"] == "onboarding"


def test_approval_is_refused_if_the_registration_stopped_being_complete(c):
    v = _ready(c)
    doc = _run(c, lambda: db.vendor_documents.find_one({"vendor_id": v["vendor_id"], "type": "pan"}, {"_id": 0}))
    _run(c, lambda: db.vendor_documents.update_one({"id": doc["id"]}, {"$set": {"status": "rejected"}}))
    r = c.post(f"/api/admin/vendors/{v['vendor_id']}/final-review", headers=_hdr("super"), json={"action": "approve"})
    assert r.status_code == 400 and any("PAN" in m for m in r.json()["detail"]["missing"])
    assert _snapshot(c, v["vendor_id"])["vendor"]["status"] == "ready_for_review"


# ================================================================ sign-in gates: nothing before activation
def _pending_owner(c):
    v = _create(c)
    _run(c, lambda: db.users.update_one({"id": v["user_id"]}, {"$set": {"password_hash": hash_password(OWNER_PW)}}))   # even with a known password
    return v


@pytest.mark.parametrize("state", ("pending_approval", "invited"))
def test_every_sign_in_path_refuses_an_account_that_is_not_activated(c, state, monkeypatch):
    v = _pending_owner(c)
    _run(c, lambda: db.users.update_one({"id": v["user_id"]}, {"$set": {"account_status": state}}))
    user = _run(c, lambda: db.users.find_one({"id": v["user_id"]}, {"_id": 0}))
    # password login (by mobile, email and ID)
    for ident in (v["mobile"], v["email"], user["distributor_id"]):
        assert c.post("/api/auth/login", json={"email": ident, "password": OWNER_PW}).status_code == 403
    # an existing token is useless
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {create_token(v['user_id'])}"}).status_code == 401
    assert c.get("/api/vendor/me", headers={"Authorization": f"Bearer {create_token(v['user_id'])}"}).status_code == 401
    # mobile OTP login is never offered or accepted
    assert auth_routes._eligible_for_login_otp(user) is False
    assert c.post("/api/auth/login-otp/verify", json={"mobile": v["mobile"], "otp": "123456"}).status_code == 400
    # Google sign-in and Google password recovery
    async def fake_identity(_sid):
        return {"email": v["email"], "name": "Kavya"}
    monkeypatch.setattr(auth_routes, "_google_identity", fake_identity)
    assert c.post("/api/auth/google/session", json={"session_id": "s"}).status_code == 403
    rec = c.post("/api/auth/forgot/google", json={"session_id": "s"})
    assert rec.status_code == 200 and "reset_token" not in rec.json()
    # the admin-handled forgot request is not created, and an admin cannot reset the password instead of the invitation
    assert c.post("/api/auth/forgot/send", json={"identifier": v["mobile"]}).status_code == 200
    assert _run(c, lambda: db.password_reset_requests.count_documents({"user_id": v["user_id"]})) == 0
    assert c.post(f"/api/admin/users/{v['user_id']}/reset-password", headers=_hdr("super"), json={"password": "Reset-Pass-123"}).status_code == 409


def test_an_activated_owner_signs_in_normally(c):
    v = _pending_owner(c)
    _run(c, lambda: db.users.update_one({"id": v["user_id"]}, {"$set": {"account_status": "active"}}))
    assert c.post("/api/auth/login", json={"email": v["mobile"], "password": OWNER_PW}).status_code == 200


# ================================================================ identity separation
def test_vendor_accounts_never_carry_homegenie_status_or_withdraw(c):
    v = _create(c)
    owner = _run(c, lambda: db.users.find_one({"id": v["user_id"]}, {"_id": 0}))
    assert owner["status"] == "not_applicable" and owner["role"] == "vendor"
    # even a legacy vendor account that still carries "green" cannot request a HomeGenie withdrawal or appear eligible
    legacy = {"id": new_id(), "distributor_id": f"VDL{next(_seq)}", "full_name": "Legacy", "mobile": f"93{next(_seq):08d}", "email": None,
              "password_hash": hash_password(OWNER_PW), "role": "vendor", "status": "green", "account_status": "active",
              "created_at": now_iso(), "updated_at": now_iso()}
    _run(c, lambda: db.users.insert_one(dict(legacy)))
    h = {"Authorization": f"Bearer {create_token(legacy['id'])}"}
    assert c.post("/api/withdrawals", headers=h, json={"amount": 100, "method": "upi", "upi_id": "legacy@upi"}).status_code == 403
    assert c.get("/api/referral", headers=h).json()["eligible"] is False


def test_vendor_staff_accounts_do_not_get_homegenie_status(c):
    import vendor_staff_routes
    import inspect
    assert '"status": VENDOR_ACCOUNT_STATUS' in inspect.getsource(vendor_staff_routes.accept_invitation)


def test_the_onboarding_options_are_readable_by_viewers_only(c):
    assert c.get("/api/admin/vendor-onboarding/options", headers=_hdr("support")).status_code == 200
    assert c.get("/api/admin/vendor-onboarding/options", headers=_hdr("fin")).status_code == 403
    opts = c.get("/api/admin/vendor-onboarding/options", headers=_hdr("admin")).json()
    assert len(opts["states"]) == 36 and opts["categories"] == VO.PILLARS


def test_saving_part_of_a_section_keeps_the_rest_and_empty_clears(c):
    v = _create(c)
    _save_all(c, v)
    vid = v["vendor_id"]
    after = c.put(f"/api/admin/vendors/{vid}/onboarding/business", headers=_hdr("admin"), json={"display_name": "Renamed Store"}).json()
    biz = after["onboarding"]["business"]
    assert biz["display_name"] == "Renamed Store" and biz["legal_name"].endswith("Traders") and biz["categories"] == ["Sarees", "Fashion Products"]
    cleared = c.put(f"/api/admin/vendors/{vid}/onboarding/business", headers=_hdr("admin"), json={"website": "", "year_established": None}).json()
    assert "year_established" not in cleared["onboarding"]["business"]
    # the bank account is kept when the masked field is left blank
    kept = c.put(f"/api/admin/vendors/{vid}/onboarding/bank", headers=_hdr("admin"), json={"bank_name": "HDFC Bank Ltd", "account_number": ""}).json()
    assert kept["onboarding"]["bank"]["account_number"].endswith("6789")
    # choosing an explicit pickup address replaces "same as registered", and back
    addr = {"line1": "9 Depot Lane", "city": "Surat", "state": "Gujarat", "pincode": "395003"}
    a1 = c.put(f"/api/admin/vendors/{vid}/onboarding/addresses", headers=_hdr("admin"), json={"pickup": addr}).json()["onboarding"]["addresses"]
    assert a1["pickup"]["line1"] == "9 Depot Lane" and "pickup_same_as" not in a1 and a1["return_same_as"] == "pickup"
    a2 = c.put(f"/api/admin/vendors/{vid}/onboarding/addresses", headers=_hdr("admin"), json={"pickup_same_as": "registered"}).json()["onboarding"]["addresses"]
    assert a2["pickup_same_as"] == "registered" and "pickup" not in a2
