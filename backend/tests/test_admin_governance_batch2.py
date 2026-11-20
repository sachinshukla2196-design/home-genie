"""Batch 2 — admin governance: ADM-01 (settings persist exactly), AUD-01 (append-only audit), SEC-17 (the environment
credential overrides the super admin password only when the environment value changes), OPS-01 (admin team management,
super admin only, never touching super_admin accounts).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_admin_governance_batch2.py -n 0`).
"""
import json
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_governance_batch2_test", "JWT_SECRET": "batch2-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "SMS_TEST_ADAPTER": "true"})
for k in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH", "ADMIN_USERNAME"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
PW = "Admin-Pass-1234!"


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

            async def user(key, mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": f"{did.lower()}@example.com",
                     "username": f"{did.lower()}@example.com", "password_hash": hash_password(PW), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("super", "9100002001", "super_admin", "B2SUPER")
            await user("admin", "9100002002", "admin", "B2ADMIN")
            await user("fin", "9100002003", "accounts_admin", "B2FIN")
            await user("sup", "9100002004", "support_admin", "B2SUP")
            await user("member", "9100002005", "distributor", "B2MEMBER")
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ================================================================ ADM-01: settings persist exactly
FULL = {"commission_direct_pct": 30, "commission_referral_pct": 10, "commission_team_pct": 5, "return_window_days": 9,
        "point_value": 1.0, "points_withdrawal_enabled": False, "cod_enabled": False, "cod_fee": 25.0, "badge_t1_sales": 11000.0,
        "badge_t2_sales": 22000.0, "badge_t3_sales": 33000.0, "badge_t4_sales": 44000.0, "require_kyc_for_withdrawal": True,
        "gst_percent": 5.0, "company_name": "HOME GENIES Test", "company_email": "ops@example.com", "company_phone": "9100002999",
        "company_address": "1 Test Road"}


def test_every_settings_field_round_trips(c):
    r = c.put("/api/admin/settings", json=FULL, headers=_hdr("fin"))
    assert r.status_code == 200, r.text
    got = c.get("/api/admin/settings", headers=_hdr("sup")).json()
    for k, v in FULL.items():
        assert got[k] == v, (k, got[k], v)


def test_non_finance_roles_change_only_non_money_settings(c):
    assert c.put("/api/admin/settings", json={**FULL, "cod_fee": 99.0}, headers=_hdr("sup")).status_code == 403
    r = c.put("/api/admin/settings", json={**FULL, "company_name": "Renamed by support"}, headers=_hdr("sup"))
    assert r.status_code == 200 and r.json()["company_name"] == "Renamed by support" and r.json()["cod_fee"] == 25.0


def test_invalid_settings_are_refused_not_silently_saved(c):
    r = c.put("/api/admin/settings", json={"commission_direct_pct": 80, "commission_referral_pct": 30}, headers=_hdr("fin"))
    assert r.status_code == 422
    assert c.get("/api/admin/settings", headers=_hdr("fin")).json()["commission_direct_pct"] == 30


# ================================================================ AUD-01: append-only audit
def test_audit_logs_cannot_be_deleted_by_anyone(c):
    before = _run(c, lambda: db.audit_logs.count_documents({}))
    assert before > 0
    for who in ("super", "admin", "fin", "sup"):
        assert c.delete("/api/admin/audit-logs", headers=_hdr(who)).status_code == 405
    assert _run(c, lambda: db.audit_logs.count_documents({})) == before + 4                     # each attempt is recorded
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "audit_logs_delete_refused"})) == 4


# ================================================================ SEC-17: environment credential behaviour
ENV_EMAIL = "owner@example.com"


def _boot(c, password):
    os.environ.update({"ADMIN_EMAIL": ENV_EMAIL, "ADMIN_PASSWORD": password, "ADMIN_USERNAME": "owner"})
    try:
        _run(c, server._init_db)
    finally:
        for k in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "ADMIN_USERNAME"):
            os.environ.pop(k, None)


def _admin_login(c, pw):
    return c.post("/api/auth/admin-login", json={"username": "owner", "password": pw})


def test_password_changed_in_the_app_survives_restarts_and_env_rotation_still_works(c):
    first = "Env-Owner-Pass-2026!"
    _boot(c, first)
    login = _admin_login(c, first)
    assert login.status_code == 200, login.text
    tok = {"Authorization": f"Bearer {login.json()['token']}"}
    me = c.get("/api/auth/me", headers=tok).json()
    assert "env_credential_marker" not in me and "password_hash" not in me
    ch = c.put("/api/auth/change-password", headers=tok, json={"current_password": first, "new_password": "App-Chosen-Pass-77!x"})
    assert ch.status_code == 200, ch.text
    _boot(c, first)                                                       # cold start with the SAME environment value
    assert _admin_login(c, "App-Chosen-Pass-77!x").status_code == 200       # the app-chosen password is kept
    assert _admin_login(c, first).status_code == 401
    _boot(c, "Rotated-Env-Pass-2027!")                                    # deliberate rotation through the environment
    assert _admin_login(c, "Rotated-Env-Pass-2027!").status_code == 200
    assert _admin_login(c, "App-Chosen-Pass-77!x").status_code == 401
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "admin_credential_rotated"})) == 1


def test_env_marker_never_leaves_the_server(c):
    owner = _run(c, lambda: db.users.find_one({"email": ENV_EMAIL}))
    assert owner.get("env_credential_marker", "").startswith("$2")
    detail = c.get(f"/api/admin/users/{owner['id']}", headers=_hdr("super"))
    assert "env_credential_marker" not in detail.text and "$2b$" not in detail.text


# ================================================================ OPS-01: admin team
NEW = {"full_name": "New Finance", "email": "new.fin@example.com", "mobile": "9100002101", "role": "accounts_admin",
       "temporary_password": "TempAdmin2026x", "reason": "New finance team member"}


@pytest.mark.parametrize("who", ["admin", "fin", "sup", "member"])
def test_only_the_super_admin_manages_the_team(c, who):
    assert c.get("/api/admin/team", headers=_hdr(who)).status_code == 403
    assert c.post("/api/admin/team", json=NEW, headers=_hdr(who)).status_code == 403
    assert c.put(f"/api/admin/team/{S['sup']['id']}/role", json={"role": "admin", "reason": "promote me"}, headers=_hdr(who)).status_code == 403


def test_super_admin_creates_an_admin_who_must_set_their_own_password(c):
    r = c.post("/api/admin/team", json=NEW, headers=_hdr("super"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "accounts_admin" and body["must_change_password"] is True and "TempAdmin2026x" not in r.text
    S["new"] = {"id": body["id"]}
    login = c.post("/api/auth/admin-login", json={"username": NEW["email"], "password": NEW["temporary_password"]})
    assert login.status_code == 200
    tok = {"Authorization": f"Bearer {login.json()['token']}"}
    assert c.get("/api/admin/finance/policy", headers=tok).status_code == 403          # nothing until the forced change
    me = c.get("/api/auth/me", headers=tok).json()
    assert me["password_change_otp_required"] is True                                   # the super admin cannot finish it
    strong = "New-Fin-Own-Pass-55!"
    assert c.put("/api/auth/change-password", headers=tok, json={"current_password": NEW["temporary_password"], "new_password": strong}).status_code == 400
    assert c.post("/api/auth/forced-change/send-otp", headers=tok).status_code == 200
    code = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": NEW["mobile"]}, sort=[("created_at", -1)]))["code"]
    ch = c.put("/api/auth/change-password", headers=tok, json={"current_password": NEW["temporary_password"], "new_password": strong, "otp": code})
    assert ch.status_code == 200, ch.text
    assert c.get("/api/admin/finance/policy", headers={"Authorization": f"Bearer {ch.json()['token']}"}).status_code == 200
    log = json.dumps(_run(c, lambda: db.audit_logs.find_one({"action": "admin_account_created"}, {"_id": 0})))
    assert NEW["mobile"] not in log and NEW["temporary_password"] not in log and "New finance team member" in log


@pytest.mark.parametrize("bad", [{"role": "super_admin"}, {"role": "distributor"}, {"email": "nope"}, {"mobile": "123"},
                                 {"temporary_password": "short1"}, {"temporary_password": "onlylettersverylong"}, {"reason": ""}])
def test_invalid_admin_creation_refused(c, bad):
    r = c.post("/api/admin/team", json={**NEW, "email": "x.other@example.com", "mobile": "9100002102", **bad}, headers=_hdr("super"))
    assert r.status_code in (400, 422), r.text


def test_existing_accounts_are_never_converted_into_admins(c):
    for clash in ({"email": S["member"]["email"]}, {"mobile": S["member"]["mobile"]}):
        assert c.post("/api/admin/team", json={**NEW, "email": "y.other@example.com", "mobile": "9100002103", **clash},
                      headers=_hdr("super")).status_code == 409
    assert _run(c, lambda: db.users.find_one({"id": S["member"]["id"]}))["role"] == "distributor"


def test_role_changes_only_among_team_roles(c):
    url = lambda uid: f"/api/admin/team/{uid}/role"                                     # noqa: E731
    assert c.put(url(S["sup"]["id"]), json={"role": "admin", "reason": "promotion"}, headers=_hdr("super")).json()["role"] == "admin"
    assert c.put(url(S["sup"]["id"]), json={"role": "super_admin", "reason": "promotion"}, headers=_hdr("super")).status_code == 422
    assert c.put(url(S["super"]["id"]), json={"role": "admin", "reason": "demotion"}, headers=_hdr("super")).status_code == 403
    assert c.put(url(S["member"]["id"]), json={"role": "admin", "reason": "conversion"}, headers=_hdr("super")).status_code == 403
    assert c.put(url(S["sup"]["id"]), json={"role": "support_admin", "reason": "x"}, headers=_hdr("super")).status_code == 422
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "admin_role_changed"})) == 1


def test_disabling_an_admin_revokes_access_and_can_be_undone(c):
    tok = _hdr("admin")
    assert c.get("/api/admin/users", headers=tok).status_code == 200
    assert c.put(f"/api/admin/users/{S['admin']['id']}/block", json={"blocked": True}, headers=_hdr("super")).status_code == 200
    assert c.get("/api/admin/users", headers=tok).status_code == 401
    assert c.put(f"/api/admin/users/{S['admin']['id']}/block", json={"blocked": False}, headers=_hdr("super")).json()["account_status"] == "active"
    assert c.get("/api/admin/users", headers=_hdr("admin")).status_code == 200


def test_team_list_masks_contacts_and_hides_credentials(c):
    rows = c.get("/api/admin/team", headers=_hdr("super")).json()
    text = json.dumps(rows)
    assert "password_hash" not in text and "$2b$" not in text and S["fin"]["mobile"] not in text
    assert {r["role"] for r in rows} >= {"super_admin", "accounts_admin"}
