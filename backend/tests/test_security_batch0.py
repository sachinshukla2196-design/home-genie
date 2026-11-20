"""Batch 0 security hotfix: SEC-01 (admin password reset), SEC-02 (report data exposure), SEC-03 (editing/blocking protected
accounts), SEC-04 (unblock restores the real status) and SEC-06 (KYC edits by finance only, verification reset).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_security_batch0.py -n 0`): it sets environment variables and
imports `server` at module level.
"""
import json
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_security_batch0_test", "JWT_SECRET": "batch0-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "SMS_TEST_ADAPTER": "true"})   # test-only SMS adapter: codes go to test_sms_outbox in this *_test database
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
PW = "Member-Pass-123"
RAW_AADHAAR = "123456789012"
RAW_PAN = "ABCDE1234F"
RAW_ACCT = "998877665544"
TEMP = "TempPass2026x"


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, coro_fn):
    return c.portal.call(coro_fn)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(key, mobile, role, did, account_status="active", status="green", **extra):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": f"{did.lower()}@example.com",
                     "password_hash": hash_password(PW), "role": role, "status": status, "account_status": account_status,
                     "aadhaar_number": RAW_AADHAAR, "created_at": now_iso(), "updated_at": now_iso(), **extra}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("super", "9200000001", "super_admin", "HGSUPER")
            await user("super2", "9200000002", "super_admin", "HGSUPER2")
            await user("admin", "9200000003", "admin", "HGADMIN")
            await user("fin", "9200000004", "accounts_admin", "HGFIN")
            await user("sup", "9200000005", "support_admin", "HGSUP")
            await user("admin2", "9200000006", "admin", "HGADMIN2")
            for i, key in enumerate(("m1", "m2", "m3", "m4", "m5", "m6", "m7")):
                await user(key, f"92000001{i:02d}", "distributor", f"HG10000{i}", status="red")
            await user("pending_owner", "9200000201", "vendor", "VD900001", account_status="pending_approval")
            await user("invited_owner", "9200000202", "vendor", "VD900002", account_status="invited")
            await user("deleted", "9200000203", "distributor", "HG900003", account_status="deleted", blocked=True)
            await user("legacy_owner", "9200000204", "vendor", "VD900004", account_status="blocked", blocked=True)
            await user("legacy_member", "9200000205", "distributor", "HG900005", account_status="blocked", blocked=True)
            # ---- Round 2 (H1/M4): accounts blocked under the OLD implementation (status overwritten to "blocked", no pre_block_status)
            await user("legacy_del_member", "9200000206", "distributor", "HG900006", account_status="blocked", blocked=True,
                       deleted_at=now_iso(), deleted_by="old-admin")
            await user("legacy_del_owner", "9200000207", "vendor", "VD900007", account_status="blocked", blocked=True,
                       deleted_at=now_iso(), deleted_by="old-admin", invite_accepted_at=now_iso())
            await user("legacy_accepted_owner", "9200000208", "vendor", "VD900008", account_status="blocked", blocked=True,
                       invite_accepted_at=now_iso())
            await user("legacy_invited_owner", "9200000209", "vendor", "VD900009", account_status="blocked", blocked=True)
            await user("legacy_no_evidence_owner", "9200000210", "vendor", "VD900010", account_status="blocked", blocked=True)
            await db.vendors.insert_one({"id": new_id(), "user_id": S["legacy_del_owner"]["id"], "status": "approved", "owner_activation": "active"})
            await db.vendors.insert_one({"id": new_id(), "user_id": S["legacy_accepted_owner"]["id"], "status": "approved"})
            await db.vendors.insert_one({"id": new_id(), "user_id": S["legacy_invited_owner"]["id"], "status": "approved", "owner_activation": "invited"})
            await db.vendors.insert_one({"id": new_id(), "user_id": S["legacy_no_evidence_owner"]["id"], "status": "approved"})
            # ---- Round 2 (H2): ordinary accounts, none with verified contacts (as register-request creates them)
            for key, mob, role, did in (("victim", "9200000401", "distributor", "HG400001"), ("vowner", "9200000402", "vendor", "VD400002"),
                                        ("plain", "9200000403", "distributor", "HG400003"), ("rec", "9200000404", "distributor", "HG400004"),
                                        ("other", "9200000405", "distributor", "HG400005")):
                await user(key, mob, role, did, mobile_verified=False, email_verified=False)
            await db.vendors.insert_one({"id": new_id(), "user_id": S["vowner"]["id"], "status": "approved", "owner_activation": "active"})
            # ---- Batch 0 completion: self-service mobile change and OTP password reset
            for key, mob, role, did in (("cm1", "9200000601", "distributor", "HG600001"), ("fo1", "9200000602", "distributor", "HG600002"),
                                        ("fo_blocked", "9200000603", "distributor", "HG600003")):
                await user(key, mob, role, did, **({"blocked": True, "account_status": "blocked"} if key == "fo_blocked" else {}))
            # ---- Round 2 (M2): pending KYC records, one without a version field (as existing records are)
            for key in ("kv1", "kv2"):
                await user(key, "92000005" + ("01" if key == "kv1" else "02"), "distributor", key.upper())
                await db.kyc_records.insert_one({"id": new_id(), "user_id": S[key]["id"], "status": "pending", "pan": RAW_PAN,
                                                 "bank_account": RAW_ACCT, "ifsc": "SBIN0000001", "account_holder_name": "K",
                                                 "bank_name": "SBI", "submitted_at": now_iso()})
            for key, act in (("pending_owner", "not_started"), ("invited_owner", "invited"), ("legacy_owner", "not_started")):
                await db.vendors.insert_one({"id": new_id(), "user_id": S[key]["id"], "business_name": key, "status": "onboarding",
                                             "owner_activation": act, "created_at": now_iso()})
            await db.registration_requests.insert_one({"id": new_id(), "full_name": "Applicant", "mobile": "9200000301",
                                                      "aadhaar_number": RAW_AADHAAR, "password_hash": hash_password(PW),
                                                      "status": "pending", "created_at": now_iso()})
            for key, st in (("m4", "verified"), ("m5", "rejected"), ("m6", "verified")):
                await db.kyc_records.insert_one({"id": new_id(), "user_id": S[key]["id"], "status": st, "pan": RAW_PAN,
                                                 "aadhaar": RAW_AADHAAR, "bank_account": RAW_ACCT, "ifsc": "SBIN0000001",
                                                 "account_holder_name": "M", "bank_name": "SBI", "submitted_at": now_iso()})
                await db.users.update_one({"id": S[key]["id"]}, {"$set": {"kyc_status": st}})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _user(c, key):
    return _run(c, lambda: db.users.find_one({"id": S[key]["id"]}, {"_id": 0}))


def _reset(c, actor, target, temp=TEMP, reason="Member forgot the password"):
    return c.post(f"/api/admin/users/{S[target]['id']}/reset-password", headers=_hdr(actor),
                  json={"temporary_password": temp, "reason": reason})


# ============================================================ SEC-01: password reset
@pytest.mark.parametrize("actor", ["sup", "fin", "admin", "super2"])
def test_nobody_resets_the_super_admin(c, actor):
    before = _user(c, "super")["password_hash"]
    r = _reset(c, actor, "super")
    assert r.status_code == 403
    assert _user(c, "super")["password_hash"] == before


@pytest.mark.parametrize("actor", ["sup", "fin", "admin"])
def test_only_super_admin_resets_other_admin_accounts(c, actor):
    before = _user(c, "admin2")["password_hash"]
    assert _reset(c, actor, "admin2").status_code == 403
    assert _user(c, "admin2")["password_hash"] == before


def test_admin_cannot_reset_own_account_here(c):
    assert _reset(c, "admin", "admin").status_code == 403
    assert _reset(c, "super", "super").status_code == 403


def test_reset_response_never_contains_a_password_and_needs_reason_and_strong_temp(c):
    assert _reset(c, "admin", "m1", temp="short1").status_code == 400
    assert _reset(c, "admin", "m1", temp="onlyletterslong").status_code == 400
    assert _reset(c, "admin", "m1", reason="").status_code == 400
    r = _reset(c, "admin", "m1")
    assert r.status_code == 200, r.text
    body = r.json()
    text = json.dumps(body)
    assert TEMP not in text and "password" not in body and "token" not in text.lower()
    assert body["must_change_password"] is True and body["sessions_revoked"] is True


def test_super_admin_can_reset_an_admin_account(c):
    r = _reset(c, "super", "admin2")
    assert r.status_code == 200 and TEMP not in r.text
    assert _user(c, "admin2")["must_change_password"] is True


def test_reset_revokes_sessions_and_forces_a_password_change(c):
    old = _hdr("m2")
    assert c.get("/api/auth/me", headers=old).status_code == 200
    assert _reset(c, "admin", "m2").status_code == 200
    assert c.get("/api/auth/me", headers=old).status_code == 401              # every earlier session is refused
    login = c.post("/api/auth/login", json={"email": S["m2"]["mobile"], "password": TEMP})
    assert login.status_code == 200, login.text
    assert login.json()["user"]["must_change_password"] is True
    tok = {"Authorization": f"Bearer {login.json()['token']}"}
    assert c.get("/api/dashboard", headers=tok).status_code == 403          # nothing else works until the change
    me = c.get("/api/auth/me", headers=tok)
    assert me.status_code == 200 and me.json()["password_change_otp_required"] is True
    # The admin knows TEMP, but TEMP alone can never finish the change: a code to the trusted mobile is also needed.
    assert c.put("/api/auth/change-password", headers=tok, json={"current_password": TEMP, "new_password": "MyOwnPass99"}).status_code == 400
    assert c.put("/api/auth/change-password", headers=tok, json={"current_password": TEMP, "new_password": "MyOwnPass99", "otp": "000000"}).status_code == 400
    assert c.post("/api/auth/forced-change/send-otp", headers=tok).status_code == 200
    code = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": S["m2"]["mobile"]}, {"_id": 0}, sort=[("created_at", -1)]))["code"]
    ch = c.put("/api/auth/change-password", headers=tok, json={"current_password": TEMP, "new_password": "MyOwnPass99", "otp": code})
    assert ch.status_code == 200, ch.text
    tok2 = {"Authorization": f"Bearer {ch.json()['token']}"}
    assert c.get("/api/dashboard", headers=tok2).status_code == 200
    assert _user(c, "m2")["must_change_password"] is False


def test_reset_refused_for_not_activated_and_deleted_accounts(c):
    for key in ("pending_owner", "invited_owner", "deleted"):
        assert _reset(c, "super", key).status_code == 409, key


# ============================================================ SEC-02: reports and admin listings
FORBIDDEN_KEYS = {"password_hash", "aadhaar_number", "aadhaar"}


def _walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + "." + str(k), k, v
            yield from _walk(v, path + "." + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")


def _assert_clean(payload, where):
    for p, k, v in _walk(payload):
        assert k not in ("password_hash", "aadhaar_number"), f"{where}: {p}"
        if isinstance(v, str):
            assert v != RAW_AADHAAR and not v.startswith("$2b$"), f"{where}: {p} leaks a secret"


def test_registration_report_has_only_the_listed_fields(c):
    from admin_routes import REPORTS
    r = c.get("/api/admin/reports/registrations", headers=_hdr("sup"))
    assert r.status_code == 200
    allowed = set(REPORTS["registrations"][2])
    assert r.json()["rows"] and all(set(row) <= allowed for row in r.json()["rows"])


def test_no_report_or_export_leaks_credentials_or_aadhaar(c):
    from admin_routes import REPORTS
    for name, (_, _, fields) in REPORTS.items():
        r = c.get(f"/api/admin/reports/{name}", headers=_hdr("sup"))
        assert r.status_code == 200
        _assert_clean(r.json(), name)
        assert all(set(row) <= set(fields) for row in r.json()["rows"])
        csv_text = c.get(f"/api/admin/reports/{name}/export", headers=_hdr("sup")).text
        assert "password_hash" not in csv_text and RAW_AADHAAR not in csv_text and "$2b$" not in csv_text
        assert csv_text.splitlines()[0].split(",") == fields


def test_csv_export_neutralises_formulas(c):
    _run(c, lambda: db.users.update_one({"id": S["m7"]["id"]}, {"$set": {"full_name": "=HYPERLINK(\"http://x\")"}}))
    csv_text = c.get("/api/admin/reports/registrations/export", headers=_hdr("sup")).text
    assert "'=HYPERLINK" in csv_text and "\n=HYPERLINK" not in csv_text and ",=HYPERLINK" not in csv_text


def test_no_admin_get_endpoint_returns_password_hash_or_raw_aadhaar(c):
    """Calls every parameter-free GET under /api/admin as the super admin and scans the whole JSON response."""
    checked = 0
    for route in server.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/admin") or "{" in path or "GET" not in getattr(route, "methods", set()):
            continue
        r = c.get(path, headers=_hdr("super"))
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json"):
            _assert_clean(r.json(), path)
            checked += 1
    assert checked >= 20


def test_registration_requests_list_masks_aadhaar(c):
    rows = c.get("/api/admin/registration-requests", headers=_hdr("sup")).json()
    assert rows and rows[0].get("aadhaar_masked") == "XXXX-XXXX-9012" and "aadhaar_number" not in rows[0]


# ============================================================ SEC-03: editing and blocking protected accounts
@pytest.mark.parametrize("actor", ["sup", "fin", "admin"])
def test_non_super_admins_cannot_edit_or_block_admin_accounts(c, actor):
    for target in ("super", "admin2"):
        before = _user(c, target)
        assert c.put(f"/api/admin/users/{S[target]['id']}", headers=_hdr(actor), json={"email": "evil@example.com"}).status_code == 403
        assert c.put(f"/api/admin/users/{S[target]['id']}/block", headers=_hdr(actor), json={"blocked": True}).status_code == 403
        after = _user(c, target)
        assert (after["email"], after.get("blocked"), after["account_status"]) == (before["email"], before.get("blocked"), before["account_status"])


def test_super_admin_account_cannot_be_blocked_or_edited_even_by_super_admin(c):
    assert c.put(f"/api/admin/users/{S['super']['id']}/block", headers=_hdr("super2"), json={"blocked": True}).status_code == 403
    assert c.put(f"/api/admin/users/{S['super']['id']}", headers=_hdr("super2"), json={"mobile": "9999999990"}).status_code == 403


def test_contact_edit_is_validated_and_duplicates_are_controlled(c):
    url = f"/api/admin/users/{S['m3']['id']}"
    assert c.put(url, headers=_hdr("sup"), json={"email": "not-an-email"}).status_code == 400
    assert c.put(url, headers=_hdr("sup"), json={"mobile": "12345"}).status_code == 400
    assert c.put(url, headers=_hdr("sup"), json={"aadhaar_number": "12"}).status_code == 400
    assert c.put(url, headers=_hdr("sup"), json={"mobile": S["m1"]["mobile"]}).status_code == 409
    assert c.put(url, headers=_hdr("sup"), json={"email": S["m1"]["email"]}).status_code == 409


def test_contact_change_is_only_proposed_notifies_member_and_audits_masked_values(c):
    """Round 2 (H2): an admin contact edit no longer applies directly; the live contact stays the trusted one."""
    before = _user(c, "m3")
    r = c.put(f"/api/admin/users/{S['m3']['id']}", headers=_hdr("sup"), json={"mobile": "9300000003", "email": "new.m3@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["contact_change"]["status"] == "pending" and r.json()["contact_change"]["new"]["mobile"] == "XXXXXX0003"
    u = _user(c, "m3")
    assert (u["mobile"], u["email"]) == (before["mobile"], before["email"])
    assert u["pending_contact_change"]["new"] == {"mobile": "XXXXXX0003", "email": "n***@example.com"}
    note = _run(c, lambda: db.notifications.find_one({"user_id": S["m3"]["id"], "type": "security"}, {"_id": 0}))
    assert note and "requested" in note["title"]
    notice = _run(c, lambda: db.test_sms_notices.find_one({"mobile": before["mobile"]}, {"_id": 0}))
    assert notice and "9300000003" not in notice["text"]                          # sent to the TRUSTED number, no raw new value
    log = _run(c, lambda: db.audit_logs.find_one({"action": "contact_change_requested", "entity_id": S["m3"]["id"]}, {"_id": 0}))
    text = json.dumps(log)
    assert "9300000003" not in text and "new.m3@example.com" not in text and "XXXXXX0003" in text and log["new_value"]["status"] == "pending"


# ============================================================ SEC-04: block / unblock restores the real status
def _block(c, key, blocked, actor="admin"):
    return c.put(f"/api/admin/users/{S[key]['id']}/block", headers=_hdr(actor), json={"blocked": blocked})


@pytest.mark.parametrize("key,expected", [("pending_owner", "pending_approval"), ("invited_owner", "invited")])
def test_unblocking_a_not_activated_owner_does_not_activate_it(c, key, expected):
    assert _block(c, key, True).json()["account_status"] == "blocked"
    r = _block(c, key, False)
    assert r.status_code == 200 and r.json()["account_status"] == expected
    u = _user(c, key)
    assert u["account_status"] == expected and u["blocked"] is False
    assert c.post("/api/auth/login", json={"email": S[key]["mobile"], "password": PW}).status_code == 403   # still not usable


def test_deleted_account_cannot_be_blocked_or_unblocked(c):
    assert _block(c, "deleted", False).status_code == 409
    assert _block(c, "deleted", True).status_code == 409
    assert _user(c, "deleted")["account_status"] == "deleted"


def test_member_block_unblock_round_trip_and_idempotent(c):
    assert _block(c, "m1", True).json()["account_status"] == "blocked"
    assert _block(c, "m1", True).json().get("unchanged") is True        # a second block keeps the recorded status
    assert c.get("/api/auth/me", headers=_hdr("m1")).status_code == 401
    assert _block(c, "m1", False).json()["account_status"] == "active"
    assert "pre_block_status" not in _user(c, "m1")


def test_legacy_blocked_accounts_without_a_recorded_status(c):
    assert _block(c, "legacy_owner", False).json()["account_status"] == "pending_approval"    # never auto-activated
    assert _block(c, "legacy_member", False).json()["account_status"] == "active"


def test_super_admin_can_block_and_unblock_an_admin_account(c):
    assert _block(c, "admin2", True, actor="super").status_code == 200
    assert _block(c, "admin2", False, actor="super").json()["account_status"] == "active"


# ============================================================ SEC-06: KYC edits
@pytest.mark.parametrize("actor", ["sup", "admin"])
def test_non_finance_roles_cannot_edit_kyc(c, actor):
    r = c.put(f"/api/admin/kyc/{S['m4']['id']}/edit", headers=_hdr(actor), json={"bank_account": "111122223333"})
    assert r.status_code == 403
    k = _run(c, lambda: db.kyc_records.find_one({"user_id": S["m4"]["id"]}, {"_id": 0}))
    assert k["bank_account"] == RAW_ACCT and k["status"] == "verified"


def test_kyc_change_resets_verification_and_audit_is_masked(c):
    r = c.put(f"/api/admin/kyc/{S['m4']['id']}/edit", headers=_hdr("fin"), json={"bank_account": "111122223333", "ifsc": "HDFC0001234"})
    assert r.status_code == 200, r.text
    assert r.json()["verification_reset"] is True and r.json()["status"] == "pending"
    k = _run(c, lambda: db.kyc_records.find_one({"user_id": S["m4"]["id"]}, {"_id": 0}))
    assert k["status"] == "pending" and k["bank_account"] == "111122223333" and k["last_edited_by"] == S["fin"]["id"]
    assert _user(c, "m4")["kyc_status"] == "pending"
    log = _run(c, lambda: db.audit_logs.find_one({"action": "kyc_edited_by_admin", "entity_id": S["m4"]["id"]}, {"_id": 0}))
    text = json.dumps(log)
    assert RAW_ACCT not in text and "111122223333" not in text and "XXXX5544" in text and "XXXX3333" in text
    assert log["old_value"]["status"] == "verified" and log["new_value"]["status"] == "pending"


def test_kyc_edit_with_identical_values_keeps_status(c):
    r = c.put(f"/api/admin/kyc/{S['m6']['id']}/edit", headers=_hdr("super"), json={"pan": RAW_PAN.lower(), "bank_account": RAW_ACCT})
    assert r.status_code == 200 and r.json()["changed"] == []
    assert _run(c, lambda: db.kyc_records.find_one({"user_id": S["m6"]["id"]}))["status"] == "verified"


def test_kyc_edit_on_rejected_record_returns_it_to_pending_and_validates(c):
    url = f"/api/admin/kyc/{S['m5']['id']}/edit"
    assert c.put(url, headers=_hdr("fin"), json={"pan": "BAD"}).status_code == 400
    assert c.put(url, headers=_hdr("fin"), json={"ifsc": "XX"}).status_code == 400
    assert c.put(url, headers=_hdr("fin"), json={"bank_account": "12ab"}).status_code == 400
    r = c.put(url, headers=_hdr("fin"), json={"pan": "PQRST6789Z"})
    assert r.status_code == 200 and r.json()["status"] == "pending"


# ============================================================ audit trail has no secrets
def test_audit_trail_contains_no_plaintext_secrets(c):
    logs = _run(c, lambda: db.audit_logs.find({}, {"_id": 0}).to_list(5000))
    assert any(x["action"] == "admin_reset_password" for x in logs)
    text = json.dumps(logs)
    for secret in (TEMP, PW, "MyOwnPass99", RAW_AADHAAR, RAW_PAN, RAW_ACCT, "111122223333", "PQRST6789Z"):
        assert secret not in text, secret
    reset = next(x for x in logs if x["action"] == "admin_reset_password")
    assert reset["new_value"]["reason"] and reset["user_id"] and reset["created_at"]


# ============================================================ Round 2 — H1 / M4: legacy blocked accounts
@pytest.mark.parametrize("key", ["legacy_del_member", "legacy_del_owner"])
def test_deleted_accounts_blocked_under_old_code_are_refused_both_ways(c, key):
    before = _user(c, key)
    assert _block(c, key, False, actor="super").status_code == 409
    assert _block(c, key, True, actor="super").status_code == 409
    after = _user(c, key)
    assert (after["account_status"], after["blocked"]) == (before["account_status"], True)
    assert c.post("/api/auth/login", json={"email": S[key]["mobile"], "password": PW}).status_code in (401, 403)


def test_deletion_marker_beats_invite_acceptance(c):
    u = _user(c, "legacy_del_owner")
    assert u.get("invite_accepted_at") and u.get("deleted_at")
    assert _block(c, "legacy_del_owner", False, actor="super").status_code == 409


@pytest.mark.parametrize("key,expected", [("legacy_accepted_owner", "active"), ("legacy_invited_owner", "invited"),
                                          ("legacy_no_evidence_owner", "pending_approval")])
def test_legacy_vendor_owner_restoration_uses_only_activation_evidence(c, key, expected):
    r = _block(c, key, False)
    assert r.status_code == 200 and r.json()["account_status"] == expected
    login = c.post("/api/auth/login", json={"email": S[key]["mobile"], "password": PW})
    assert (login.status_code == 200) == (expected == "active")


def test_deleted_marker_written_during_block_is_refused_at_write_time(c):
    """A deactivation that lands between the read and the write must win: the update filter requires no deletion marker."""
    import admin_routes
    real_find = db.users.find_one

    class Users:
        def __getattr__(self, n):
            return getattr(db.users, n)

        async def find_one(self, *a, **k):
            doc = await real_find(*a, **k)
            if doc and doc.get("id") == S["m7"]["id"]:
                await db.users.update_one({"id": S["m7"]["id"]}, {"$set": {"deleted_at": now_iso(), "deleted_by": "racer"}})
            return doc

    class DB:
        users = Users()

        def __getattr__(self, n):
            return getattr(db, n)
    saved = admin_routes.db
    admin_routes.db = DB()
    try:
        r = _block(c, "m7", True)
    finally:
        admin_routes.db = saved
    assert r.status_code == 409
    assert _user(c, "m7").get("blocked") is not True


# ============================================================ Round 2 — H2: admin contact change cannot take over an account
ATTACKER_MOBILE, ATTACKER_EMAIL = "9399999991", "attacker@evil.example"


def _code(c, mobile):
    rec = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": mobile}, {"_id": 0}, sort=[("created_at", -1)]))
    return rec and rec["code"]


def _propose(c, key, actor="sup", **values):
    r = c.put(f"/api/admin/users/{S[key]['id']}", headers=_hdr(actor), json=values)
    assert r.status_code == 200, r.text
    return r.json()["contact_change"]


@pytest.mark.parametrize("key", ["victim", "vowner"])
def test_admin_set_attacker_mobile_cannot_log_in_by_otp(c, key):
    _propose(c, key, mobile=ATTACKER_MOBILE)
    assert _user(c, key)["mobile"] == S[key]["mobile"]                         # live contact unchanged
    assert c.post("/api/auth/login-otp/send", json={"mobile": ATTACKER_MOBILE}).status_code == 200   # generic answer
    assert _code(c, ATTACKER_MOBILE) is None                                   # no code was ever issued for that number
    v = c.post("/api/auth/login-otp/verify", json={"mobile": ATTACKER_MOBILE, "otp": "123456"})
    assert v.status_code == 400 and "token" not in v.text
    assert c.post("/api/auth/login", json={"email": ATTACKER_MOBILE, "password": PW}).status_code == 401


def test_admin_set_attacker_email_cannot_take_over_through_google(c, monkeypatch):
    import auth_routes
    _propose(c, "victim", email=ATTACKER_EMAIL)

    async def attacker_identity(_sid):
        return {"email": ATTACKER_EMAIL, "name": "Attacker"}
    monkeypatch.setattr(auth_routes, "_google_identity", attacker_identity)
    g = c.post("/api/auth/google/session", json={"session_id": "s"})
    assert g.status_code == 200 and g.json().get("mode") == "register" and "token" not in g.json()
    u = _user(c, "victim")
    assert u["email"] == S["victim"]["email"] and not u.get("google_linked")


def test_pending_contact_cannot_be_used_for_recovery(c, monkeypatch):
    import auth_routes
    _propose(c, "rec", mobile="9399999993", email="rec.attacker@evil.example")
    assert c.post("/api/auth/forgot/send", json={"identifier": "9399999993"}).status_code == 200
    assert _run(c, lambda: db.password_reset_requests.count_documents({"user_id": S["rec"]["id"]})) == 0

    async def attacker_identity(_sid):
        return {"email": "rec.attacker@evil.example", "name": "Attacker"}
    monkeypatch.setattr(auth_routes, "_google_identity", attacker_identity)
    rec = c.post("/api/auth/forgot/google", json={"session_id": "s"})
    assert rec.status_code == 200 and "reset_token" not in rec.json()


def test_unauthorised_confirmations_are_refused(c):
    cc = _propose(c, "rec", actor="sup", mobile="9399999994")
    rid = cc["id"]
    assert c.post("/api/auth/contact-change/confirm", headers=_hdr("rec"), json={"request_id": rid, "otp": "000000"}).status_code == 400
    # a code sent to the NEW number (e.g. by the attacker requesting a login OTP for it) proves nothing
    assert c.post("/api/auth/contact-change/send-otp", headers=_hdr("rec"), json={"request_id": rid}).status_code == 200
    assert _code(c, "9399999994") is None                                      # the code went to the trusted number only
    # another account cannot see or confirm it
    assert c.post("/api/auth/contact-change/confirm", headers=_hdr("other"), json={"request_id": rid, "otp": _code(c, S["rec"]["mobile"])}).status_code == 404
    # recovery approval: never by non-super admins, never by the requester, never without evidence
    assert c.post(f"/api/admin/contact-changes/{rid}/recovery-approve", headers=_hdr("admin"), json={"evidence": "x" * 30}).status_code == 403
    assert c.post(f"/api/admin/contact-changes/{rid}/recovery-approve", headers=_hdr("super"), json={"evidence": "short"}).status_code == 422
    assert _user(c, "rec")["mobile"] == S["rec"]["mobile"]
    own = _propose(c, "rec", actor="super", mobile="9399999995")
    assert c.post(f"/api/admin/contact-changes/{own['id']}/recovery-approve", headers=_hdr("super"), json={"evidence": "x" * 30}).status_code == 403
    assert _user(c, "rec")["mobile"] == S["rec"]["mobile"]


def test_trusted_contact_confirms_and_the_new_mobile_becomes_usable(c):
    cc = _propose(c, "victim", mobile="9300000401")
    assert c.post("/api/auth/contact-change/send-otp", headers=_hdr("victim"), json={"request_id": cc["id"]}).status_code == 200
    code = _code(c, S["victim"]["mobile"])                                     # delivered to the OLD, trusted number
    r = c.post("/api/auth/contact-change/confirm", headers=_hdr("victim"), json={"request_id": cc["id"], "otp": code})
    assert r.status_code == 200 and r.json()["method"] == "holder_otp_trusted_mobile"
    u = _user(c, "victim")
    assert u["mobile"] == "9300000401" and "pending_contact_change" not in u
    req = _run(c, lambda: db.contact_change_requests.find_one({"id": cc["id"]}, {"_id": 0}))
    assert req["status"] == "confirmed" and req["confirmation_method"] == "holder_otp_trusted_mobile"
    assert c.post("/api/auth/login-otp/send", json={"mobile": "9300000401"}).status_code == 200
    v = c.post("/api/auth/login-otp/verify", json={"mobile": "9300000401", "otp": _code(c, "9300000401")})
    assert v.status_code == 200 and v.json()["user"]["id"] == S["victim"]["id"]


def test_reviewed_recovery_by_a_different_super_admin_applies_the_change(c):
    cc = _propose(c, "vowner", actor="admin", mobile="9300000402")
    r = c.post(f"/api/admin/contact-changes/{cc['id']}/recovery-approve", headers=_hdr("super2"),
               json={"evidence": "Aadhaar card checked in person, ref DOC-2026-11-18-01"})
    assert r.status_code == 200 and r.json()["method"] == "recovery_review"
    assert _user(c, "vowner")["mobile"] == "9300000402"
    req = _run(c, lambda: db.contact_change_requests.find_one({"id": cc["id"]}, {"_id": 0}))
    assert req["decided_by"] == S["super2"]["id"] and req["evidence"].startswith("Aadhaar")


def test_holder_can_reject_and_admin_can_cancel(c):
    cc = _propose(c, "other", mobile="9399999996")
    assert c.post("/api/auth/contact-change/reject", headers=_hdr("other"), json={"request_id": cc["id"]}).json()["status"] == "rejected"
    assert "pending_contact_change" not in _user(c, "other")
    cc2 = _propose(c, "other", mobile="9399999997")
    assert c.post(f"/api/admin/contact-changes/{cc2['id']}/cancel", headers=_hdr("fin")).status_code == 200
    assert _user(c, "other")["mobile"] == S["other"]["mobile"]


def test_unverified_accounts_without_a_pending_change_keep_their_login(c, monkeypatch):
    import auth_routes
    u = _user(c, "plain")
    assert u["mobile_verified"] is False and u["email_verified"] is False and "pending_contact_change" not in u
    assert c.post("/api/auth/login", json={"email": S["plain"]["mobile"], "password": PW}).status_code == 200
    assert c.post("/api/auth/login-otp/send", json={"mobile": S["plain"]["mobile"]}).status_code == 200
    assert c.post("/api/auth/login-otp/verify", json={"mobile": S["plain"]["mobile"], "otp": _code(c, S["plain"]["mobile"])}).status_code == 200

    async def own_identity(_sid):
        return {"email": S["plain"]["email"], "name": "Plain"}
    monkeypatch.setattr(auth_routes, "_google_identity", own_identity)
    # Batch 4 (SEC-05): Google no longer links itself to an account whose email was never confirmed (pre-hijack defence);
    # password and OTP above keep working for such accounts, and an account that is already Google-linked keeps Google.
    assert c.post("/api/auth/google/session", json={"session_id": "s"}).status_code == 409
    _run(c, lambda: db.users.update_one({"id": S["plain"]["id"]}, {"$set": {"google_linked": True}}))
    g = c.post("/api/auth/google/session", json={"session_id": "s"})
    assert g.status_code == 200 and g.json().get("token")


# ============================================================ Round 2 — M2: stale KYC verification
def test_stale_expected_version_is_refused(c):
    k = c.get("/api/admin/kyc", headers=_hdr("super")).json()
    rec = next(x for x in k if x["user_id"] == S["kv1"]["id"])
    seen = rec.get("version") or 0
    assert c.put(f"/api/admin/kyc/{S['kv1']['id']}/edit", headers=_hdr("fin"), json={"bank_account": "556677889900"}).status_code == 200
    r = c.put(f"/api/admin/kyc/{S['kv1']['id']}", headers=_hdr("super"), json={"action": "verify", "expected_version": seen})
    assert r.status_code == 409
    assert _run(c, lambda: db.kyc_records.find_one({"user_id": S["kv1"]["id"]}))["status"] == "pending"
    fresh = _run(c, lambda: db.kyc_records.find_one({"user_id": S["kv1"]["id"]}))["version"]
    ok = c.put(f"/api/admin/kyc/{S['kv1']['id']}", headers=_hdr("super"), json={"action": "verify", "expected_version": fresh})
    assert ok.status_code == 200 and ok.json()["status"] == "verified"


def test_edit_landing_between_read_and_verify_is_never_overwritten(c):
    """Interleaving: the reviewer's request reads the record, then a finance edit lands, then the reviewer's write runs."""
    import admin_routes
    real = db.kyc_records

    class Kyc:
        def __getattr__(self, n):
            return getattr(real, n)

        async def find_one(self, *a, **k):
            doc = await real.find_one(*a, **k)
            if doc and doc.get("user_id") == S["kv2"]["id"]:
                await real.update_one({"user_id": S["kv2"]["id"]},
                                      {"$set": {"bank_account": "112233445566", "status": "pending"}, "$inc": {"version": 1}})
            return doc

    class DB:
        kyc_records = Kyc()

        def __getattr__(self, n):
            return getattr(db, n)
    saved = admin_routes.db
    admin_routes.db = DB()
    try:
        r = c.put(f"/api/admin/kyc/{S['kv2']['id']}", headers=_hdr("super"), json={"action": "verify"})
    finally:
        admin_routes.db = saved
    assert r.status_code == 409
    rec = _run(c, lambda: db.kyc_records.find_one({"user_id": S["kv2"]["id"]}))
    assert rec["status"] == "pending" and rec["bank_account"] == "112233445566"
    assert _user(c, "kv2").get("kyc_status") != "verified"


# ============================================================ Round 2 — audit trail has no raw contacts or codes
def test_round2_audit_and_requests_hold_no_raw_codes(c):
    logs = json.dumps(_run(c, lambda: db.audit_logs.find({"action": {"$regex": "^contact_change"}}, {"_id": 0}).to_list(500)))
    for raw in (ATTACKER_MOBILE, ATTACKER_EMAIL, "9300000401", "9300000402", "rec.attacker@evil.example"):
        assert raw not in logs, raw
    codes = {x["code"] for x in _run(c, lambda: db.test_sms_outbox.find({}, {"_id": 0, "code": 1}).to_list(500))}
    every_log = json.dumps(_run(c, lambda: db.audit_logs.find({}, {"_id": 0}).to_list(5000)))
    assert codes and not any(f'"{code}"' in every_log for code in codes)
    assert '"otp"' not in every_log


# ============================================================ Batch 0 completion: reset -> self-service takeover chain closed
def _latest_code(c, mobile):
    rec = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": mobile}, {"_id": 0}, sort=[("created_at", -1)]))
    return rec and rec["code"]


def test_self_service_mobile_change_needs_the_current_trusted_mobile(c):
    h, new = _hdr("cm1"), "9300000601"
    assert c.put("/api/auth/change-mobile/send", headers=h, json={"mobile": new}).status_code == 200
    cur_code, new_code = _latest_code(c, S["cm1"]["mobile"]), _latest_code(c, new)
    assert cur_code and new_code
    # possession of the NEW number alone is not enough (a session opened with an admin's temporary password has only that)
    assert c.put("/api/auth/change-mobile/verify", headers=h, json={"mobile": new, "otp": new_code}).status_code == 400
    assert c.put("/api/auth/change-mobile/verify", headers=h, json={"mobile": new, "otp": new_code, "current_otp": "000000"}).status_code == 400
    assert _user(c, "cm1")["mobile"] == S["cm1"]["mobile"]


def test_self_service_mobile_change_with_both_codes_succeeds_and_is_audited_masked(c, monkeypatch):
    import providers
    monkeypatch.setattr(providers, "OTP_RESEND_COOLDOWN", 0)
    h, new = _hdr("cm1"), "9300000611"
    assert c.put("/api/auth/change-mobile/send", headers=h, json={"mobile": new}).status_code == 200
    r = c.put("/api/auth/change-mobile/verify", headers=h,
              json={"mobile": new, "otp": _latest_code(c, new), "current_otp": _latest_code(c, S["cm1"]["mobile"])})
    assert r.status_code == 200, r.text
    u = _user(c, "cm1")
    assert u["mobile"] == new and u["mobile_verified"] is True
    log = _run(c, lambda: db.audit_logs.find_one({"action": "mobile_changed", "entity_id": S["cm1"]["id"]}, {"_id": 0}))
    assert new not in json.dumps(log) and log["new_value"]["mobile"] == "XXXXXX0611"


def test_self_service_password_reset_by_trusted_mobile(c):
    old = _hdr("fo1")
    assert c.post("/api/auth/forgot/otp/send", json={"mobile": S["fo1"]["mobile"]}).status_code == 200
    code = _latest_code(c, S["fo1"]["mobile"])
    assert c.post("/api/auth/forgot/otp/reset", json={"mobile": S["fo1"]["mobile"], "otp": "000000", "password": "Fresh-Pass-77"}).status_code == 400
    r = c.post("/api/auth/forgot/otp/reset", json={"mobile": S["fo1"]["mobile"], "otp": code, "password": "Fresh-Pass-77"})
    assert r.status_code == 200, r.text
    assert c.post("/api/auth/login", json={"email": S["fo1"]["mobile"], "password": "Fresh-Pass-77"}).status_code == 200
    assert c.get("/api/auth/me", headers=old).status_code == 401                 # older sessions revoked
    assert c.post("/api/auth/forgot/otp/reset", json={"mobile": S["fo1"]["mobile"], "otp": code, "password": "Again-Pass-88"}).status_code == 400


@pytest.mark.parametrize("key", ["super", "fo_blocked", "pending_owner", "legacy_del_member"])
def test_otp_reset_never_issued_for_admins_blocked_unactivated_or_deleted(c, key):
    before = _run(c, lambda: db.test_sms_outbox.count_documents({"mobile": S[key]["mobile"]}))
    r = c.post("/api/auth/forgot/otp/send", json={"mobile": S[key]["mobile"]})
    assert r.status_code == 200 and "registered" in r.json()["message"]               # same answer as for anyone
    assert _run(c, lambda: db.test_sms_outbox.count_documents({"mobile": S[key]["mobile"]})) == before


def test_unknown_number_gets_the_same_answer_and_no_code(c):
    r = c.post("/api/auth/forgot/otp/send", json={"mobile": "9311111111"})
    assert r.status_code == 200 and _latest_code(c, "9311111111") is None


def test_registration_otp_is_rate_limited_per_ip(c, monkeypatch):
    import core
    monkeypatch.setitem(core.RATE_LIMITS, "otp_send_ip", (2, 3600))
    _run(c, lambda: db.rate_limits.delete_many({"key": {"$regex": "^otp_send_ip:"}}))
    codes = [c.post("/api/auth/send-otp", json={"email": f"r{i}@example.com", "mobile": f"93222222{i:02d}", "sponsor_id": ""}).status_code
             for i in range(3)]
    assert codes[-1] == 429, codes
