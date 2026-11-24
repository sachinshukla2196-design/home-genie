"""Batch 12 — fixes for the confirmed Batch 11 audit defects (docs/HOME_GENIES_BATCH11_PRE_RELEASE_AUDIT.md).

Security : C-1 OTP attempts are race-safe and budgeted per identifier · C-2 client IP cannot be forged · C-3 the legacy sign-up
           no longer marks an unproven e-mail verified · C-9 Google recovery needs a proven e-mail · C-16 vendor applicants prove
           the mobile when SMS works · C-17 vendor accounts follow the vendor lifecycle; staff stop with their owner · L6 · L9.
Money    : C-4 the admin "Refund" action needs a second finance admin · L1 fail/retry cannot launder the initiator · C-5 / C-7
           delivery comes from the vendor fulfilments (per vendor), never from an admin status, a COD confirmation or a
           cancelled order · C-6 a sale reversal nets earlier refunds · C-8 COD cash and commission exclude goods a vendor never
           supplied · C-10 · C-11 refunds are split on goods value, not the COD fee · C-13 · C-18 · C-21.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_batch12_remediation.py -n 0`).
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_batch12_remediation_test", "JWT_SECRET": "batch12-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret", "SMS_TEST_ADAPTER": "true"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
from starlette.requests import Request  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import core  # noqa: E402
import eligibility  # noqa: E402
import providers  # noqa: E402
import shop_routes  # noqa: E402
import auth_routes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
PW = "Pass-1234x"
S = {}
LONG_AGO = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()


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
            for key, mob, role, did in (("cust", "9100012001", "distributor", "B12CUST"), ("super", "9100012002", "super_admin", "B12SUPER"),
                                        ("admin", "9100012003", "admin", "B12ADMIN"), ("fin", "9100012004", "accounts_admin", "B12FIN"),
                                        ("fin2", "9100012005", "accounts_admin", "B12FIN2"), ("sup", "9100012006", "support_admin", "B12SUP"),
                                        ("va", "9100012007", "vendor", "B12VA"), ("vb", "9100012008", "vendor", "B12VB"),
                                        ("staff", "9100012009", "vendor_staff", "B12STAFF"), ("member", "9100012010", "distributor", "B12MEM")):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mob, "email": f"{did.lower()}@example.com",
                     "username": did.lower(), "password_hash": hash_password(PW), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            for key, owner in (("A", "va"), ("B", "vb")):
                v = {"id": new_id(), "user_id": S[owner]["id"], "vendor_code": f"B12V{key}", "business_name": f"Vendor {key}",
                     "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                S["v" + key] = v
                await db.products.insert_one({"id": f"b12p{key}", "sku": f"B12-{key}", "name": f"Saree {key}", "images": [], "mrp": 1200,
                                              "selling_price": 1050, "gst_percent": 5, "stock": 500, "category": "Sarees", "options": [],
                                              "vendor_id": v["id"], "vendor_name": v["business_name"], "is_active": True,
                                              "approval_status": "approved", "created_at": now_iso()})
            await db.vendor_members.insert_one({"id": new_id(), "vendor_id": S["vA"]["id"], "user_id": S["staff"]["id"], "mobile": S["staff"]["mobile"],
                                                "full_name": "Staff", "role": "order_manager", "permissions": ["orders.read"], "status": "active",
                                                "created_at": now_iso(), "updated_at": now_iso()})
            core.RATE_LIMITS["vendor_apply"] = (10000, 3600)
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ------------------------------------------------------------------ helpers
_n = {"i": 0}


def _order(c, items, method="online", who="cust", **extra):
    r = c.post("/api/orders", json={"items": [{"product_id": p, "quantity": q} for p, q in items], "address": ADDR,
                                    "payment_method": method, **extra}, headers=_hdr(who))
    assert r.status_code == 200, r.text
    return r.json()


def _pay(c, o):
    _n["i"] += 1
    sid = f"cs_b12_{_n['i']}"
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    return _get(c, o["id"])


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _fulfil(c, oid, vendor_key, *steps):
    for st in steps:
        body = {"status": st, "note": "Handed to customer" if st == "delivered" else ("Out of stock now" if st in ("rejected", "cancelled") else ""),
                "carrier": "BlueDart", "tracking_number": "BD1"}
        r = c.post(f"/api/vendor/orders/{oid}/fulfilment", json=body, headers=_hdr(vendor_key))
        assert r.status_code == 200, (st, r.text)


def _age_delivery(c, oid):
    """Move every recorded delivery 60 days back (past any return window)."""
    async def go():
        o = await db.orders.find_one({"id": oid}, {"_id": 0})
        for f in o.get("fulfilments", []):
            for e in f.get("events", []):
                if e.get("status") == "delivered":
                    e["at"] = LONG_AGO
            if f.get("delivered_at"):
                f["delivered_at"] = LONG_AGO
        await db.orders.update_one({"id": oid}, {"$set": {"fulfilments": o.get("fulfilments", []),
                                                          **({"delivered_at": LONG_AGO} if o.get("delivered_at") else {})}})
    _run(c, go)


def _ledger_net(c, vendor_key, oid):
    rows = _run(c, lambda: db.vendor_ledger.find({"vendor_id": S["v" + vendor_key]["id"], "order_id": oid}, {"_id": 0}).to_list(100))
    return sum(r["amount_paise"] for r in rows), sorted((r["type"], r["amount_paise"]) for r in rows)


def _confirm_case(c, case_id, who, ref):
    return c.post(f"/api/admin/refund-cases/{case_id}/action", headers=_hdr(who),
                  json={"action": "confirm", "reference": ref, "confirmation_type": "manual_reconciliation",
                        "note": "Bank statement checked for this refund"})


def _code(c, mobile):
    rec = _run(c, lambda: db.test_sms_outbox.find_one({"mobile": mobile}, {"_id": 0}, sort=[("created_at", -1)]))
    return rec and rec["code"]


# ================================================================ C-1: OTP attempts
def test_parallel_otp_guesses_cannot_exceed_the_attempt_limit(c):
    mobile = "9300012001"
    _run(c, lambda: providers.otp_create(mobile, "login"))
    right = _code(c, mobile)

    async def burst():
        async def guess(code):
            try:
                return await providers.otp_verify(mobile, "login", code)
            except Exception as e:      # HTTPException
                return getattr(e, "status_code", 500)
        wrong = [f"{(int(right) + i) % 1000000:06d}" for i in range(1, 31)]
        return await asyncio.gather(*[guess(g) for g in wrong + [right]])
    results = _run(c, burst)
    assert results.count(True) == 0                                       # the right code, sent last, is refused too
    rec = _run(c, lambda: db.otp_sessions.find_one({"identifier": mobile, "purpose": "login"}, sort=[("created_at", -1)]))
    assert rec["attempts"] <= providers.OTP_MAX_ATTEMPTS and not rec["used"]


def test_a_correct_code_is_used_once_even_under_concurrency(c):
    mobile = "9300012002"
    _run(c, lambda: providers.otp_create(mobile, "login"))
    right = _code(c, mobile)

    async def burst():
        async def go():
            try:
                return await providers.otp_verify(mobile, "login", right)
            except Exception as e:
                return getattr(e, "status_code", 500)
        return await asyncio.gather(*[go() for _ in range(5)])
    assert _run(c, burst).count(True) == 1


def test_fresh_codes_do_not_reset_the_daily_guessing_budget(c):
    mobile = "9300012003"
    statuses = []
    for _ in range(6):                                                    # 6 codes x 4 wrong guesses = 24 > 20 budget
        _run(c, lambda: db.otp_sessions.update_many({"identifier": mobile}, {"$set": {"created_at": LONG_AGO}}))   # skip cooldown
        _run(c, lambda: providers.otp_create(mobile, "forgot"))
        right = _code(c, mobile)
        for i in range(1, 5):
            async def g(code=f"{(int(right) + i) % 1000000:06d}"):
                try:
                    return await providers.otp_verify(mobile, "forgot", code)
                except Exception as e:
                    return e.status_code
            statuses.append(_run(c, g))
    assert 429 in statuses
    _run(c, lambda: db.otp_sessions.update_many({"identifier": mobile}, {"$set": {"created_at": LONG_AGO}}))
    _run(c, lambda: providers.otp_create(mobile, "forgot"))
    right = _code(c, mobile)

    async def ok():
        try:
            return await providers.otp_verify(mobile, "forgot", right)
        except Exception as e:
            return e.status_code
    assert _run(c, ok) == 429                                             # budget spent: even the right code waits a day


# ================================================================ C-2: client IP
def _req(peer, xff=None):
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234), "method": "GET", "path": "/"})


def test_client_ip_ignores_forwarded_headers_from_the_internet(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    assert core.client_ip(_req("8.8.4.4", "1.2.3.4")) == "8.8.4.4"                    # direct client cannot pick its IP
    assert core.client_ip(_req("10.0.0.2", "1.2.3.4, 198.51.100.9")) == "198.51.100.9"  # behind a private proxy: rightmost
    assert core.client_ip(_req("127.0.0.1")) == "127.0.0.1"
    monkeypatch.setenv("VERCEL", "1")
    assert core.client_ip(_req("10.1.1.1", "198.51.100.7")) == "198.51.100.7"         # Vercel overwrites the header


# ================================================================ C-3 / C-9 / L6 / L9: identity
def test_legacy_signup_does_not_verify_the_email_so_google_cannot_enter_it(c, monkeypatch):
    mobile, email = "9300012010", "victim.b12@example.com"
    assert c.post("/api/auth/send-otp", json={"email": email, "mobile": mobile, "sponsor_id": ""}).status_code == 200
    r = c.post("/api/auth/register", json={"full_name": "Attacker", "email": email, "mobile": mobile, "password": "Attack-123x",
                                           "confirm_password": "Attack-123x", "accept_terms": True, "otp": _code(c, mobile),
                                           "sponsor_id": "", "address": "x", "state": "MH", "city": "Pune", "pincode": "411001"})
    assert r.status_code == 200, r.text
    assert _run(c, lambda: db.users.find_one({"email": email}))["email_verified"] is False

    async def identity(_sid):
        return {"email": email, "name": "Victim"}
    monkeypatch.setattr(auth_routes, "_google_identity", identity)
    g = c.post("/api/auth/google/session", json={"session_id": "s"})
    assert "token" not in g.text                                         # the victim is not logged into the attacker's account
    rec = c.post("/api/auth/forgot/google", json={"session_id": "s"})
    assert rec.status_code == 200 and "reset_token" not in rec.json()   # C-9: and cannot reset it either


def test_google_recovery_still_works_for_a_proven_email(c, monkeypatch):
    _run(c, lambda: db.users.update_one({"id": S["member"]["id"]}, {"$set": {"email_verified": True}}))

    async def identity(_sid):
        return {"email": S["member"]["email"], "name": "Member"}
    monkeypatch.setattr(auth_routes, "_google_identity", identity)
    assert c.post("/api/auth/forgot/google", json={"session_id": "s"}).json().get("reset_token")


def test_a_blocked_admin_gets_the_invalid_credentials_answer(c):
    async def mk():
        u = {"id": new_id(), "distributor_id": "B12BLK", "username": "b12blocked", "email": "b12blk@example.com", "mobile": "9100012099",
             "password_hash": hash_password(PW), "role": "admin", "status": "green", "account_status": "blocked", "blocked": True,
             "created_at": now_iso(), "updated_at": now_iso()}
        await db.users.insert_one(u)
    _run(c, mk)
    right = c.post("/api/auth/admin-login", json={"username": "b12blocked", "password": PW})
    wrong = c.post("/api/auth/admin-login", json={"username": "b12blocked", "password": "nope-nope-1"})
    assert right.status_code == wrong.status_code == 401 and right.json() == wrong.json()


def test_only_access_tokens_are_sessions(c):
    import jwt
    now = datetime.now(timezone.utc)
    signup = jwt.encode({"type": "google_signup", "sub": S["cust"]["id"], "email": "x@example.com", "exp": now + timedelta(minutes=5)},
                        core.JWT_SECRET, algorithm=core.JWT_ALGO)
    no_exp = jwt.encode({"type": "access", "sub": S["cust"]["id"]}, core.JWT_SECRET, algorithm=core.JWT_ALGO)
    for t in (signup, no_exp):
        assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {t}"}).status_code == 401
    assert c.get("/api/auth/me", headers=_hdr("cust")).status_code == 200


# ================================================================ C-16: vendor applicants prove the mobile
APP = {"business_name": "Weaves B12", "business_type": "Manufacturer", "description": "We weave handloom sarees in Pune.",
       "categories": ["Sarees"], "contact_name": "Owner", "email": "", "city": "Pune", "state": "Maharashtra",
       "website": "", "consent": True, "password": "Vendor-pass-12", "confirm_password": "Vendor-pass-12"}


def test_vendor_application_needs_the_mobile_code_when_sms_works(c):
    from vendor_onboarding import BUSINESS_TYPES
    body = {**APP, "business_type": list(BUSINESS_TYPES)[0], "mobile": "9300012020"}
    assert c.post("/api/vendor-applications", json=body).status_code == 400
    assert not _run(c, lambda: db.users.find_one({"mobile": "9300012020"}))
    assert c.post("/api/vendor-applications/send-otp", json={"mobile": "9300012020"}).status_code == 200
    r = c.post("/api/vendor-applications", json={**body, "otp": _code(c, "9300012020")})
    assert r.status_code == 200, r.text
    u = _run(c, lambda: db.users.find_one({"mobile": "9300012020"}))
    assert u and u["mobile_verified"] is True and u["role"] == "vendor"


# ================================================================ C-17: vendor accounts and their staff
def test_support_and_accounts_admins_cannot_block_or_deactivate_a_vendor_owner(c):
    for who in ("sup", "fin"):
        assert c.put(f"/api/admin/users/{S['vb']['id']}/block", json={"blocked": True},
                     headers=_hdr(who)).status_code == 403
        assert c.delete(f"/api/admin/users/{S['vb']['id']}", headers=_hdr(who)).status_code == 403
    assert _run(c, lambda: db.users.find_one({"id": S["vb"]["id"]}))["account_status"] == "active"


def test_staff_stop_when_the_owner_account_is_blocked(c):
    assert c.get("/api/vendor/orders", headers=_hdr("staff")).status_code == 200
    _run(c, lambda: db.users.update_one({"id": S["va"]["id"]}, {"$set": {"blocked": True, "account_status": "blocked"}}))
    try:
        assert c.get("/api/vendor/orders", headers=_hdr("staff")).status_code == 403
    finally:
        _run(c, lambda: db.users.update_one({"id": S["va"]["id"]}, {"$set": {"blocked": False, "account_status": "active"}}))
    assert c.get("/api/vendor/orders", headers=_hdr("staff")).status_code == 200


# ================================================================ C-5 / C-7: delivery comes from the vendor fulfilments
def test_an_admin_marking_a_vendor_order_delivered_starts_no_payout_clock(c):
    o = _pay(c, _order(c, [("b12pA", 1)]))
    r = c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "delivered"}, headers=_hdr("sup"))
    assert r.status_code == 200
    o = _get(c, o["id"])
    assert o["status"] == "delivered" and o["status_set_by_admin"]["by"] == S["sup"]["id"]
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"delivered_at": LONG_AGO}}))
    o = _get(c, o["id"])
    assert _run(c, lambda: eligibility.payout_block(o)) == "not_delivered"
    assert _run(c, lambda: eligibility.payout_block(o, vendor_id=S["vA"]["id"])) == "not_delivered"


def test_moving_a_platform_order_back_from_delivered_withdraws_the_delivery(c):
    async def mk():
        await db.products.insert_one({"id": "b12own", "sku": "B12-OWN", "name": "Own", "images": [], "mrp": 500, "selling_price": 420,
                                      "gst_percent": 5, "stock": 50, "category": "Sarees", "options": [], "vendor_id": None,
                                      "is_active": True, "approval_status": "approved", "created_at": now_iso()})
    _run(c, mk)
    o = _pay(c, _order(c, [("b12own", 1)]))
    assert not o.get("fulfilments")
    assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "delivered"}, headers=_hdr("admin")).status_code == 200
    assert _get(c, o["id"]).get("delivered_at")
    assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "shipped"}, headers=_hdr("admin")).status_code == 200
    o = _get(c, o["id"])
    assert "delivered_at" not in o and _run(c, lambda: eligibility.payout_block(o)) == "not_delivered"


def test_a_vendor_cannot_move_a_cancelled_order_forward(c):
    o = _pay(c, _order(c, [("b12pA", 1)]))
    _fulfil(c, o["id"], "va", "accepted", "packed", "dispatched")
    assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr("super")).status_code == 200
    r = c.post(f"/api/vendor/orders/{o['id']}/fulfilment", json={"status": "delivered", "note": "Handed over"}, headers=_hdr("va"))
    assert r.status_code == 409
    assert _get(c, o["id"])["status"] == "cancelled"


def test_one_vendor_rejecting_does_not_hold_the_other_vendors_money_for_ever(c):
    o = _pay(c, _order(c, [("b12pA", 1), ("b12pB", 1)]))
    _fulfil(c, o["id"], "va", "accepted", "packed", "dispatched", "delivered")
    _fulfil(c, o["id"], "vb", "rejected")
    o = _get(c, o["id"])
    assert o["status"] == "delivered"
    _age_delivery(c, o["id"])
    o = _get(c, o["id"])
    # B's refund case is still open. Batch 12 held everything on the order for it; Programme 01 (B-001, directive section 5.3)
    # changed that rule: B's case is refunded from B's share alone (ledger.post_refund_shares, vendor-specific refund), so it no
    # longer holds vendor A's settlement. The whole-order HomeGenie commission still waits for it ...
    assert _run(c, lambda: eligibility.payout_block(o, vendor_id=S["vA"]["id"])) is None
    assert _run(c, lambda: eligibility.payout_block(o)) == "open_return_or_refund"
    assert _run(c, lambda: eligibility.payout_block(o, vendor_id=S["vB"]["id"])) == "not_delivered"   # B supplied nothing
    case = _run(c, lambda: db.refund_cases.find_one({"source_key": f"vreject:{o['id']}:{S['vB']['id']}"}, {"_id": 0}))
    assert c.post(f"/api/admin/refund-cases/{case['id']}/action", json={"action": "initiate"}, headers=_hdr("fin")).status_code == 200
    assert _confirm_case(c, case["id"], "fin2", "UTR-B12-VREJ").status_code == 200
    o = _get(c, o["id"])
    # ... and once it is settled, vendor A (delivered, past the window) is payable and so is the order's commission
    assert _run(c, lambda: eligibility.payout_block(o, vendor_id=S["vA"]["id"])) is None
    assert _run(c, lambda: eligibility.payout_block(o)) is None


def test_a_vendor_whose_part_is_delivered_is_eligible_while_another_vendor_is_still_shipping(c):
    o = _pay(c, _order(c, [("b12pA", 1), ("b12pB", 1)]))
    _fulfil(c, o["id"], "va", "accepted", "packed", "dispatched", "delivered")
    _fulfil(c, o["id"], "vb", "accepted")
    _age_delivery(c, o["id"])
    o = _get(c, o["id"])
    assert _run(c, lambda: eligibility.payout_block(o, vendor_id=S["vA"]["id"])) is None       # vendor A: delivered + window
    assert _run(c, lambda: eligibility.payout_block(o)) == "not_delivered"                     # the order (commission) waits


# ================================================================ C-6: sale reversal after a partial refund
def test_partial_refund_then_vendor_rejection_leaves_the_vendor_at_zero(c):
    o = _pay(c, _order(c, [("b12pA", 2)]))
    _run(c, lambda: shop_routes.reverse_order_financials(o["id"], S["fin"], None, refund_amount=200.0, reference="B12-PARTIAL",
                                                         reason="partial"))
    _fulfil(c, o["id"], "va", "rejected")
    net, rows = _ledger_net(c, "A", o["id"])
    assert net == 0, rows
    _run(c, lambda: __import__("ledger").reconcile_ledger())
    assert _ledger_net(c, "A", o["id"])[0] == 0


# ================================================================ C-11: refunds split on goods value
def test_refunding_all_goods_of_a_cod_order_takes_back_the_whole_vendor_sale(c):
    o = _order(c, [("b12pA", 1)], method="cod")
    _fulfil(c, o["id"], "va", "accepted", "packed", "dispatched", "delivered")
    o = _get(c, o["id"])
    r = c.post(f"/api/orders/{o['id']}/cod-collected", json={"amount_collected": o["total"], "evidence_type": "courier_confirmation",
                                                            "evidence_reference": "COD-B12-1"}, headers=_hdr("admin"))
    assert r.status_code == 200, r.text
    goods = (o["total_paise"] - o["cod_fee_paise"]) / 100
    _run(c, lambda: shop_routes.reverse_order_financials(o["id"], S["fin"], None, refund_amount=goods, reference="B12-GOODS", reason="return"))
    assert _ledger_net(c, "A", o["id"])[0] == 0


# ================================================================ C-8 / C-5d: COD with a vendor that did not supply
def test_cod_cash_and_commission_exclude_goods_a_vendor_rejected(c):
    o = _order(c, [("b12pA", 1), ("b12pB", 1)], method="cod", who="member", seller_ref="B12CUST")
    _fulfil(c, o["id"], "va", "accepted", "packed", "dispatched", "delivered")
    _fulfil(c, o["id"], "vb", "rejected")
    o = _get(c, o["id"])
    line_a = next(li for li in o["items"] if li["product_id"] == "b12pA")
    expected = (line_a["total_paise"] + o["cod_fee_paise"]) / 100
    short_of_full = c.post(f"/api/orders/{o['id']}/cod-collected", json={"amount_collected": o["total"], "evidence_type": "courier_confirmation",
                                                                         "evidence_reference": "COD-B12-2"}, headers=_hdr("admin"))
    assert short_of_full.json().get("discrepancy") is True              # the full total is NOT what was owed any more
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"payment_status": "cod_pending"}, "$unset": {"cod_discrepancy": ""}}))
    r = c.post(f"/api/orders/{o['id']}/cod-collected", json={"amount_collected": expected, "evidence_type": "courier_confirmation",
                                                            "evidence_reference": "COD-B12-3"}, headers=_hdr("admin"))
    assert r.status_code == 200 and not r.json().get("discrepancy"), r.text
    o = _get(c, o["id"])
    assert o["payment_status"] == "paid" and o["commission_base_paise"] == line_a["taxable_paise"]
    comm = _run(c, lambda: db.commissions.find({"order_id": o["id"]}, {"_id": 0}).to_list(10))
    direct = next(x for x in comm if x["type"] == "COMMISSION_DIRECT")
    assert direct["amount_paise"] == round(line_a["taxable_paise"] * 30 / 100)
    assert _ledger_net(c, "B", o["id"])[0] == 0                          # nothing for the vendor that supplied nothing


def test_confirming_cod_cash_does_not_mark_undelivered_vendor_goods_delivered(c):
    o = _order(c, [("b12pA", 1)], method="cod")
    r = c.post(f"/api/orders/{o['id']}/cod-collected", json={"amount_collected": o["total"], "evidence_type": "courier_confirmation",
                                                            "evidence_reference": "COD-B12-4"}, headers=_hdr("admin"))
    assert r.status_code == 200
    o = _get(c, o["id"])
    assert o["payment_status"] == "paid" and o["status"] != "delivered" and not o.get("delivered_at")
    assert _run(c, lambda: eligibility.payout_block(o)) == "not_delivered"


# ================================================================ C-10
def test_a_partly_refunded_cod_order_still_counts_as_collected(c):
    from cod_rules import collection_is_proven
    o = {"payment_status": "partially_refunded", "cod_collection": {"type": "courier_confirmation", "collected_paise": 100, "expected_paise": 100}}
    assert collection_is_proven(o)
    assert not collection_is_proven({**o, "payment_status": "refunded"})


# ================================================================ C-4 / L1: refunds always need a second finance admin
def test_the_admin_refund_action_only_records_and_a_different_finance_admin_confirms(c):
    o = _pay(c, _order(c, [("b12pA", 1)]))
    r = c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "UTR-B12-ONE", "amount": 100.0}, headers=_hdr("fin"))
    assert r.status_code == 200 and r.json()["status"] == "pending_confirmation", r.text
    case = r.json()["case"]
    assert _get(c, o["id"])["payment_status"] == "paid"                 # no money moved yet
    assert _confirm_case(c, case["id"], "fin", "UTR-B12-ONE").status_code == 403
    assert _confirm_case(c, case["id"], "fin2", "UTR-B12-ONE").status_code == 200
    o = _get(c, o["id"])
    assert o["payment_status"] == "partially_refunded" and o["refunded_paise"] == 10000


def test_a_refund_initiator_cannot_be_laundered_through_fail_and_retry(c):
    o = _pay(c, _order(c, [("b12pA", 1)]))
    case = c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "UTR-B12-TWO"}, headers=_hdr("fin")).json()["case"]
    assert c.post(f"/api/admin/refund-cases/{case['id']}/action", json={"action": "fail", "note": "bank bounced it"}, headers=_hdr("sup")).status_code == 200
    assert c.post(f"/api/admin/refund-cases/{case['id']}/action", json={"action": "retry"}, headers=_hdr("sup")).status_code == 200
    assert _confirm_case(c, case["id"], "fin", "UTR-B12-TWO").status_code == 403
    assert _confirm_case(c, case["id"], "fin2", "UTR-B12-TWO").status_code == 200


# ================================================================ C-13: withdrawal KYC re-check
def test_a_withdrawal_is_not_approved_or_paid_while_kyc_is_unverified(c):
    async def setup():
        await db.kyc_records.insert_one({"id": new_id(), "user_id": S["member"]["id"], "status": "verified", "created_at": now_iso()})
        await db.wallets.update_one({"user_id": S["member"]["id"]}, {"$set": {"available_balance": 500.0, "available_balance_paise": 50000}},
                                    upsert=True)
    _run(c, setup)
    r = c.post("/api/withdrawals", json={"amount": 100}, headers=_hdr("member"))
    assert r.status_code == 200, r.text
    wid = _run(c, lambda: db.withdrawal_requests.find_one({"user_id": S["member"]["id"]}))["id"]
    _run(c, lambda: db.kyc_records.update_one({"user_id": S["member"]["id"]}, {"$set": {"status": "pending"}}))
    assert c.put(f"/api/admin/withdrawals/{wid}", json={"action": "approve"}, headers=_hdr("fin")).status_code == 409
    _run(c, lambda: db.kyc_records.update_one({"user_id": S["member"]["id"]}, {"$set": {"status": "verified"}}))
    assert c.put(f"/api/admin/withdrawals/{wid}", json={"action": "approve"}, headers=_hdr("fin")).status_code == 200
    _run(c, lambda: db.kyc_records.update_one({"user_id": S["member"]["id"]}, {"$set": {"status": "pending"}}))
    assert c.put(f"/api/admin/withdrawals/{wid}", json={"action": "mark_paid", "payout_reference": "UTRB12PAY0001"},
                  headers=_hdr("fin2")).status_code == 409
    assert _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}))["status"] == "approved"


# ================================================================ C-18: interrupted approvals can be finished
def test_an_interrupted_approval_is_listed_and_finished_exactly_once(c):
    r = c.post("/api/admin/wallet/credit", json={"distributor_id": "B12MEM", "amount": 25, "reason": "Goodwill for a delay",
                                                 "request_id": "b12-stuck-0001"}, headers=_hdr("fin"))
    aid = r.json()["approval"]["id"]
    stale = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    _run(c, lambda: db.financial_approvals.update_one({"_id": aid}, {"$set": {"status": "approving", "checker_id": S["super"]["id"],
                                                                              "decided_at": stale}}))
    listed = c.get("/api/admin/finance/approvals", headers=_hdr("fin2")).json()
    assert any(a["id"] == aid for a in listed)
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("fin")).status_code == 403   # still not the maker
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("fin2")).status_code == 200
    assert c.post(f"/api/admin/finance/approvals/{aid}/approve", json={}, headers=_hdr("fin2")).status_code == 409
    txns = _run(c, lambda: db.wallet_transactions.count_documents({"user_id": S["member"]["id"], "description": {"$regex": "Goodwill"}}))
    assert txns <= 1


# ================================================================ C-21
def test_statement_reads_legacy_commission_amounts(c):
    async def mk():
        await db.commissions.insert_one({"id": "b12-legacy", "order_id": "no-order", "order_number": "ORDLEG", "user_id": S["member"]["id"],
                                         "type": "COMMISSION_DIRECT", "status": "PENDING", "amount": 123.45, "created_at": now_iso()})
    _run(c, mk)
    st = c.get("/api/commissions/statement", headers=_hdr("member")).json()
    row = next(i for i in st["items"] if i["id"] == "b12-legacy")
    assert row["amount_paise"] == 12345
