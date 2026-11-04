"""Phase 3B.2: manual commission release and manual wallet credit. Integration: needs a THROWAWAY MongoDB.

Run in its own process: `pytest tests/test_manual_money_controls.py -n 0`.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_manual_money_test", "JWT_SECRET": "manual-money-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import admin_routes  # noqa: E402
from commission import distribute_sale_commissions, release_due_points  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Manual-Money-Pass-1234"
S = {}
OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _person(key, role="distributor", status="green", sponsor=None):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": "M" + uid[:7].upper(), "full_name": key, "mobile": "9" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:6]}@example.com", "password_hash": hash_password(PW), "role": role, "status": status,
            "account_status": "active", "sponsor_user_id": sponsor, "created_at": now_iso(), "updated_at": now_iso()}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            team = _person("team")
            referrer = _person("referrer", sponsor=team["id"])
            seller = _person("seller", sponsor=referrer["id"])
            people = [team, referrer, seller, _person("buyer"), _person("admin", role="admin"), _person("super", role="super_admin"),
                      _person("finance", role="accounts_admin"), _person("support", role="support_admin"), _person("other")]
            await db.users.insert_many([dict(u) for u in people])
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _commissioned_order(c, method="online", proven=True):
    """A paid order whose three commissions were created by the real distribution code, then aged past the return window."""
    oid = new_id()
    o = {"id": oid, "order_number": "MM-" + oid[:6].upper(), "user_id": S["buyer"], "seller_user_id": S["seller"],
         "payment_method": method, "payment_status": "paid", "status": "delivered", "subtotal": 1000.0, "subtotal_paise": 100000,
         "total": 1050.0, "total_paise": 105000, "fulfilments": [], "items": [], "refunded_paise": 0, "refunded_amount": 0.0,
         "paid_at": now_iso(), "created_at": now_iso()}
    if method == "cod":
        o["cod_collection"] = {"type": "courier_confirmation", "reference": "AWB-MM", "expected_paise": 105000, "collected_paise": 105000,
                               "recorded_by": "x", "verified_by_system": False}
    _run(c, lambda: db.orders.insert_one(dict(o)))
    buyer = _run(c, lambda: db.users.find_one({"id": S["buyer"]}, {"_id": 0}))
    assert _run(c, lambda: distribute_sale_commissions(o, buyer))["credited"] == 3
    _run(c, lambda: db.commissions.update_many({"order_id": oid}, {"$set": {"created_at": OLD}}))
    return oid


def _commissions(c, oid):
    return _run(c, lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))


def _direct(c, oid):
    return next(x for x in _commissions(c, oid) if x["type"] == "COMMISSION_DIRECT")


def _wallet(c, uid):
    w = _run(c, lambda: db.wallets.find_one({"user_id": uid}, {"_id": 0}))
    return w["pending_balance"], w["available_balance"]


def _release(c, who, cid, reason="Finance review complete"):
    return c.put(f"/api/admin/commissions/{cid}/status", headers=_hdr(S[who]), json={"action": "release", "reason": reason})


def _released_rows(c, cid):
    return _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"release:{cid}"}))


# ================================================================ manual commission release
@pytest.mark.parametrize("who", ["admin", "support", "other", "buyer"])
def test_only_finance_administrators_can_release_or_hold(c, who):
    oid = _commissioned_order(c)
    cid = _direct(c, oid)["id"]
    assert _release(c, who, cid).status_code == 403
    assert c.put(f"/api/admin/commissions/{cid}/status", headers=_hdr(S[who]), json={"action": "hold", "reason": "checking it"}).status_code == 403
    assert _direct(c, oid)["status"] == "PENDING"


def test_a_reason_is_mandatory(c):
    oid = _commissioned_order(c)
    cid = _direct(c, oid)["id"]
    assert c.put(f"/api/admin/commissions/{cid}/status", headers=_hdr(S["finance"]), json={"action": "release"}).status_code == 422
    assert c.put(f"/api/admin/commissions/{cid}/status", headers=_hdr(S["finance"]), json={"action": "release", "reason": "ok"}).status_code == 422
    assert _direct(c, oid)["status"] == "PENDING"


def test_release_inside_the_return_window_is_refused_and_moves_nothing(c):
    oid = _commissioned_order(c)
    _run(c, lambda: db.commissions.update_many({"order_id": oid}, {"$set": {"created_at": now_iso()}}))
    d = _direct(c, oid)
    before = _wallet(c, d["user_id"])
    r = _release(c, "finance", d["id"])
    assert r.status_code == 409 and "return window" in r.text
    assert _direct(c, oid)["status"] == "PENDING" and _wallet(c, d["user_id"]) == before and _released_rows(c, d["id"]) == 0


def test_release_after_the_window_moves_the_money_through_the_real_path_exactly_once(c):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    pend0, avail0 = _wallet(c, d["user_id"])
    r = _release(c, "finance", d["id"])
    assert r.status_code == 200 and r.json()["status"] == "RELEASED", r.text
    got = _direct(c, oid)
    assert got["status"] == "RELEASED" and got["released_at"] and got["release"]["applied"] is True and got["released_paise"] == 30000
    pend1, avail1 = _wallet(c, d["user_id"])
    assert round(pend0 - pend1, 2) == 300.0 and round(avail1 - avail0, 2) == 300.0         # pending -> available, not a bare status flag
    assert _released_rows(c, d["id"]) == 1
    again = _release(c, "super", d["id"])
    assert again.status_code == 200 and again.json().get("already") is True
    assert _wallet(c, d["user_id"]) == (pend1, avail1) and _released_rows(c, d["id"]) == 1
    cron = _run(c, release_due_points)                                                      # the cron must not pay it a second time
    ops = _run(c, lambda: db.wallets.find_one({"user_id": d["user_id"]}, {"_id": 0, "applied_ops": 1}))["applied_ops"]
    assert ops.count(f"release:{d['id']}") == 1 and _released_rows(c, d["id"]) == 1 and cron["invalid"] == 0     # other aged commissions may release; this one only once
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "commission_released", "entity_id": d["id"]})) == 1


def test_concurrent_release_requests_move_the_money_once(c):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    pend0, avail0 = _wallet(c, d["user_id"])
    fin = {"id": S["finance"], "role": "accounts_admin"}
    body = admin_routes.CommissionActionBody(action="release", reason="Concurrent attempt")

    async def race():
        return await asyncio.gather(*[admin_routes.commission_status(d["id"], body, None, admin=fin) for _ in range(3)], return_exceptions=True)
    _run(c, race)
    pend1, avail1 = _wallet(c, d["user_id"])
    assert round(pend0 - pend1, 2) == 300.0 and round(avail1 - avail0, 2) == 300.0 and _released_rows(c, d["id"]) == 1


def test_unproven_cod_cannot_be_released_even_after_the_window(c):
    oid = _commissioned_order(c, method="cod")
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"cod_collection.type": "manual_exception"}}))     # evidence downgraded
    d = _direct(c, oid)
    before = _wallet(c, d["user_id"])
    r = _release(c, "finance", d["id"])
    assert r.status_code == 409 and "COD" in r.text
    assert _direct(c, oid)["status"] == "PENDING" and _wallet(c, d["user_id"]) == before


def test_proven_cod_can_be_released(c):
    oid = _commissioned_order(c, method="cod")
    assert _release(c, "finance", _direct(c, oid)["id"]).status_code == 200


@pytest.mark.parametrize("state", ["REVERSED", "CANCELLED"])
def test_reversed_commissions_cannot_be_released(c, state):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    _run(c, lambda: db.commissions.update_one({"id": d["id"]}, {"$set": {"status": state}}))
    before = _wallet(c, d["user_id"])
    assert _release(c, "finance", d["id"]).status_code == 409
    assert _wallet(c, d["user_id"]) == before and _released_rows(c, d["id"]) == 0


def test_a_refunded_or_unpaid_order_blocks_release(c):
    for state in ("refunded", "cod_pending", "cod_discrepancy"):
        oid = _commissioned_order(c)
        _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"payment_status": state}}))
        d = _direct(c, oid)
        assert _release(c, "finance", d["id"]).status_code == 409, state
        assert _released_rows(c, d["id"]) == 0


def test_an_open_return_or_refund_case_blocks_release(c):
    oid = _commissioned_order(c)
    _run(c, lambda: db.refund_cases.insert_one({"id": new_id(), "order_id": oid, "status": "awaiting_review", "source_key": "t:" + new_id()}))
    d = _direct(c, oid)
    assert _release(c, "finance", d["id"]).status_code == 409 and _released_rows(c, d["id"]) == 0


def _hold(c, who, cid, reason="Verify seller bank"):
    return c.put(f"/api/admin/commissions/{cid}/status", headers=_hdr(S[who]), json={"action": "hold", "reason": reason})


def test_a_hold_is_a_flag_not_a_status_and_the_cron_leaves_it_alone(c):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    assert _hold(c, "finance", d["id"]).status_code == 200
    held = _direct(c, oid)
    assert held["status"] == "PENDING" and held["manual_hold"] is True and held["hold_reason"] == "Verify seller bank"
    _run(c, release_due_points)
    assert _direct(c, oid)["status"] == "PENDING" and _released_rows(c, d["id"]) == 0
    assert _hold(c, "finance", d["id"], "second hold").status_code == 409


def test_a_held_commission_is_released_only_when_every_normal_condition_holds_and_then_exactly_once(c):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    _hold(c, "finance", d["id"])
    assert _release(c, "finance", d["id"]).status_code == 200 and _released_rows(c, d["id"]) == 1
    done = _direct(c, oid)
    assert done["status"] == "RELEASED" and done["manual_hold"] is False
    assert _release(c, "super", d["id"]).json().get("already") is True and _released_rows(c, d["id"]) == 1
    assert _hold(c, "finance", d["id"], "too late now").status_code == 409


def test_a_hold_never_bypasses_the_return_window_cod_proof_open_cases_or_cancellation(c):
    cases = []
    o = _commissioned_order(c)                                                                   # inside the window
    _run(c, lambda: db.commissions.update_many({"order_id": o}, {"$set": {"created_at": now_iso()}}))
    cases.append(o)
    o = _commissioned_order(c, method="cod")                                                     # unproven COD
    _run(c, lambda: db.orders.update_one({"id": o}, {"$set": {"cod_collection.type": "manual_exception"}}))
    cases.append(o)
    o = _commissioned_order(c)                                                                   # open refund case
    _run(c, lambda: db.refund_cases.insert_one({"id": new_id(), "order_id": o, "status": "initiated", "source_key": "t:" + new_id()}))
    cases.append(o)
    o = _commissioned_order(c)                                                                   # open return case
    _run(c, lambda: db.return_cases.insert_one({"id": new_id(), "order_id": o, "status": "refund_pending"}))
    cases.append(o)
    o = _commissioned_order(c)                                                                   # cancelled order
    _run(c, lambda: db.orders.update_one({"id": o}, {"$set": {"status": "cancelled"}}))
    cases.append(o)
    for oid in cases:
        d = _direct(c, oid)
        _hold(c, "finance", d["id"])
        before = _wallet(c, d["user_id"])
        assert _release(c, "finance", d["id"]).status_code == 409, oid
        assert _direct(c, oid)["released_at"] is None and _wallet(c, d["user_id"]) == before and _released_rows(c, d["id"]) == 0


def _refund(c, oid, amount):
    import shop_routes
    admin = {"id": S["super"], "role": "super_admin"}
    return _run(c, lambda: shop_routes.reverse_order_financials(oid, admin, None, refund_amount=amount, reference=f"RF-{new_id()[:8]}", reason="test"))


def test_a_held_commission_is_still_clawed_back_by_a_refund_and_cannot_release_the_full_amount(c):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    _hold(c, "finance", d["id"])
    pend0, _ = _wallet(c, d["user_id"])
    assert _refund(c, oid, 105.0)["reversed"] == 3                                               # 10% of the order
    after = _direct(c, oid)
    assert after["status"] == "PARTIALLY_REVERSED" and after["reversed_paise"] == 3000
    assert round(pend0 - _wallet(c, d["user_id"])[0], 2) == 30.0
    r = _release(c, "finance", d["id"])
    assert r.status_code == 200 and _direct(c, oid)["released_paise"] == 27000                  # only what is still owed


def test_a_legacy_held_status_record_is_clawed_back_and_cannot_bypass_any_condition(c):
    oid = _commissioned_order(c)
    d = _direct(c, oid)
    _run(c, lambda: db.commissions.update_one({"id": d["id"]}, {"$set": {"status": "HELD"}}))    # as the old route stored it
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"payment_status": "cod_discrepancy"}}))
    assert _release(c, "finance", d["id"]).status_code == 409 and _released_rows(c, d["id"]) == 0
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"payment_status": "paid"}}))
    assert _refund(c, oid, 105.0)["reversed"] == 3
    assert _direct(c, oid)["reversed_paise"] == 3000


# ================================================================ manual wallet credit
def _credit(c, who, did="buyer", amount=250.0, reason="Goodwill adjustment", rid=None, **extra):
    body = {"distributor_id": _did(c, did), "amount": amount, "reason": reason, "request_id": rid or ("rq-" + new_id()[:16]), **extra}
    return c.post("/api/admin/wallet/credit", headers=_hdr(S[who]), json=body), body


def _did(c, key):
    return _run(c, lambda: db.users.find_one({"id": S[key]}, {"distributor_id": 1}))["distributor_id"]


def _state(c, key):
    w = _run(c, lambda: db.wallets.find_one({"user_id": S[key]}, {"_id": 0})) or {}
    n = _run(c, lambda: db.wallet_transactions.count_documents({"user_id": S[key], "type": "MANUAL_ADMIN_CREDIT"}))
    return w.get("available_balance", 0), w.get("available_balance_paise", 0), n


@pytest.mark.parametrize("who", ["support", "other", "buyer"])
def test_unauthorised_callers_cannot_credit_a_wallet(c, who):
    before = _state(c, "buyer")
    r, _ = _credit(c, who)
    assert r.status_code == 403 and _state(c, "buyer") == before


@pytest.mark.parametrize("bad", [
    {"amount": 0}, {"amount": -5}, {"amount": "abc"}, {"amount": None}, {"amount": 12.345}, {"amount": 10_000_001},
    {"amount": "NaN"}, {"amount": "Infinity"}, {"reason": ""}, {"reason": "ok"}, {"reason": "x" * 301},
    {"rid": "short"}, {"rid": "bad id with spaces!!"}, {"rid": "x" * 65}])
def test_invalid_credits_are_refused_and_change_nothing(c, bad):
    before = _state(c, "buyer")
    kwargs = dict(bad)
    rid = kwargs.pop("rid", None)
    r, _ = _credit(c, "finance", rid=rid, **{k: v for k, v in kwargs.items() if k not in ("amount", "reason")},
                   **({"amount": kwargs["amount"]} if "amount" in kwargs else {}), **({"reason": kwargs["reason"]} if "reason" in kwargs else {}))
    assert r.status_code == 422, (bad, r.text)
    assert _state(c, "buyer") == before


def test_a_missing_reason_or_request_id_is_refused(c):
    before = _state(c, "buyer")
    did = _did(c, "buyer")
    assert c.post("/api/admin/wallet/credit", headers=_hdr(S["finance"]), json={"distributor_id": did, "amount": 10, "request_id": "rq-12345678"}).status_code == 422
    assert c.post("/api/admin/wallet/credit", headers=_hdr(S["finance"]), json={"distributor_id": did, "amount": 10, "reason": "Valid reason"}).status_code == 422
    assert _state(c, "buyer") == before


def test_unknown_distributor_is_refused(c):
    r = c.post("/api/admin/wallet/credit", headers=_hdr(S["finance"]), json={"distributor_id": "NOPE9999", "amount": 10, "reason": "Valid reason", "request_id": "rq-12345678"})
    assert r.status_code == 404


def test_a_valid_credit_posts_one_ledger_row_moves_the_wallet_and_is_audited(c):
    a0, p0, n0 = _state(c, "other")
    r, body = _credit(c, "finance", did="other", amount=250.5, reason="Goodwill for delayed order")
    assert r.status_code == 200, r.text
    a1, p1, n1 = _state(c, "other")
    assert p1 - p0 == 25050 and round(a1 - a0, 2) == 250.5 and n1 - n0 == 1
    row = _run(c, lambda: db.wallet_transactions.find_one({"op_key": "admin_credit:" + body["request_id"]}, {"_id": 0}))
    assert row["amount_paise"] == 25050 and row["status"] == "CREDITED" and row["description"] == "Goodwill for delayed order" and row["created_by"] == S["finance"]
    audit = _run(c, lambda: db.audit_logs.find_one({"action": "admin_wallet_credit", "entity_id": S["other"]}, {"_id": 0}))
    assert audit and audit["new_value"]["request_id"] == body["request_id"] and audit["new_value"]["amount_paise"] == 25050


def test_a_repeated_request_id_credits_once_and_a_conflicting_reuse_is_refused(c):
    first, body = _credit(c, "finance", did="buyer", amount=100.0)
    assert first.status_code == 200
    after_first = _state(c, "buyer")
    again = c.post("/api/admin/wallet/credit", headers=_hdr(S["super"]), json=body)
    assert again.status_code == 200 and again.json().get("already") is True and _state(c, "buyer") == after_first
    clash = c.post("/api/admin/wallet/credit", headers=_hdr(S["finance"]), json={**body, "amount": 101.0})
    assert clash.status_code == 409 and _state(c, "buyer") == after_first


def test_concurrent_identical_credits_apply_once(c):
    rid = "rq-" + new_id()[:16]
    model = admin_routes.WalletCreditBody(distributor_id=_did(c, "buyer"), amount=75.0, reason="Concurrent double click", request_id=rid)
    fin = {"id": S["finance"], "role": "accounts_admin", "distributor_id": "X"}
    before = _state(c, "buyer")

    async def race():
        return await asyncio.gather(*[admin_routes.admin_wallet_credit(model, None, admin=fin) for _ in range(4)], return_exceptions=True)
    _run(c, race)
    after = _state(c, "buyer")
    assert after[1] - before[1] == 7500 and after[2] - before[2] == 1


# ================================================================ authorisation matrix (backend, direct)
@pytest.mark.parametrize("who,ok", [("finance", True), ("super", True), ("admin", False), ("support", False), ("other", False), ("buyer", False)])
def test_manual_money_authority_matrix(c, who, ok):
    oid = _commissioned_order(c)
    cid = _direct(c, oid)["id"]
    r = _release(c, who, cid)
    assert (r.status_code == 200) is ok and (r.status_code == 403) is (not ok), r.text
    hold = _hold(c, who, _direct(c, _commissioned_order(c))["id"])
    assert (hold.status_code == 200) is ok and (hold.status_code == 403) is (not ok)
    before = _state(c, "buyer")
    cr, _ = _credit(c, who, did="buyer", amount=10.0)
    assert (cr.status_code == 200) is ok and (cr.status_code == 403) is (not ok)
    assert (_state(c, "buyer")[2] - before[2]) == (1 if ok else 0)
