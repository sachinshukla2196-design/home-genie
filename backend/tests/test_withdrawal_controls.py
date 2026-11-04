"""Phase 3B.4.1: withdrawal review controls. Finance-only authority, REQUESTED -> APPROVED -> PAID (or -> REJECTED), approver and
payer must differ, mandatory unique payout reference, wallet re-check before paying, legacy records, and real-MongoDB races.
Integration: THROWAWAY MongoDB. Run in its own process: `pytest tests/test_withdrawal_controls.py -n 0`.
"""
import asyncio
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_withdrawal_controls_test", "JWT_SECRET": "withdrawal-controls-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import admin_routes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id, wallet_apply  # noqa: E402
from wallet_reconcile import expected_aggregates  # noqa: E402

S = {}
ROLE_OF = {"sup": "super_admin", "fin": "accounts_admin", "fin2": "accounts_admin", "adm": "admin", "support": "support_admin",
           "dist": "distributor", "vendor": "vendor", "vstaff": "vendor_staff"}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _u(key, role="distributor"):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": ("W" + uid[:7]).upper(), "full_name": key, "mobile": "6" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:5]}@example.com", "password_hash": hash_password("x" * 12), "role": role, "status": "green",
            "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            await db.users.insert_many([_u(k, r) for k, r in ROLE_OF.items()] + [_u("hg")])
            await db.kyc_records.insert_one({"user_id": S["hg"], "status": "verified"})
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _fund(c, rupees=1000):
    _run(c, lambda: wallet_apply(S["hg"], {"available_balance": rupees * 100, "total_earned": rupees * 100}))
    _run(c, lambda: db.wallet_transactions.insert_one({"id": new_id(), "user_id": S["hg"], "type": "MANUAL_ADMIN_CREDIT", "direction": "credit",
                                                        "status": "CREDITED", "amount": float(rupees), "amount_paise": rupees * 100, "created_at": now_iso()}))


def _request(c, amount=100.0):
    _fund(c, int(amount))
    r = c.post("/api/withdrawals", headers=_hdr(S["hg"]), json={"amount": amount})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _act(c, who, wid, action, ref=None, note=""):
    body = {"action": action, "note": note}
    if ref is not None:
        body["payout_reference"] = ref
    return c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S[who]), json=body)


def _wd(c, wid):
    return _run(c, lambda: db.withdrawal_requests.find_one({"id": wid}, {"_id": 0}))


def _w(c):
    w = _run(c, lambda: db.wallets.find_one({"user_id": S["hg"]}, {"_id": 0})) or {}
    return {f: w.get(f + "_paise", 0) for f in ("pending_balance", "available_balance", "total_earned", "total_withdrawn")}


def _paid_rows(c, wid):
    return _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"withdrawal_paid:{wid}"}))


def _consistent(c):
    rows = _run(c, lambda: db.wallet_transactions.find({"user_id": S["hg"]}, {"_id": 0}).to_list(5000))
    exp, act = expected_aggregates(rows), _w(c)
    return {f: (exp[f], act[f]) for f in exp if exp[f] != act[f]}


def _ref():
    return "UTR-" + new_id()[:12]


# ================================================================ authorisation
@pytest.mark.parametrize("who", ["adm", "support", "dist", "vendor", "vstaff", "hg"])
def test_only_finance_roles_can_review(c, who):
    wid = _request(c)
    before = (_wd(c, wid), _w(c))
    for action, ref in (("approve", None), ("reject", None), ("mark_paid", _ref())):
        assert _act(c, who, wid, action, ref).status_code == 403, (who, action)
    assert (_wd(c, wid), _w(c)) == before


@pytest.mark.parametrize("approver,payer", [("sup", "fin"), ("fin", "sup"), ("fin", "fin2")])
def test_super_admin_and_accounts_admin_complete_the_workflow(c, approver, payer):
    wid = _request(c)
    start = _w(c)
    assert _act(c, approver, wid, "approve").status_code == 200
    ref = _ref()
    r = _act(c, payer, wid, "mark_paid", ref)
    assert r.status_code == 200 and r.json()["payout_reference"] == ref.upper()
    w = _wd(c, wid)
    assert w["status"] == "paid" and w["approved_by"] == S[approver] and w["paid_by"] == S[payer] and w["approved_at"] and w["paid_at"]
    assert w["payout_reference"] == ref.upper()
    end = _w(c)
    assert end["pending_balance"] == start["pending_balance"] - 10000 and end["total_withdrawn"] == start["total_withdrawn"] + 10000
    assert _paid_rows(c, wid) == 1 and _consistent(c) == {}
    audits = _run(c, lambda: db.audit_logs.find({"entity_id": wid}, {"_id": 0, "action": 1, "user_id": 1, "new_value": 1}).to_list(10))
    assert {a["action"] for a in audits} >= {"withdrawal_approved", "withdrawal_paid"}
    assert next(a for a in audits if a["action"] == "withdrawal_paid")["new_value"]["payout_reference"] == ref.upper()
    listed = next(x for x in c.get("/api/admin/withdrawals", headers=_hdr(S["fin"])).json() if x["id"] == wid)
    assert listed["approved_by_name"] == approver and listed["paid_by_name"] == payer


# ================================================================ state machine
def test_requested_cannot_jump_to_paid(c):
    wid = _request(c)
    before = _w(c)
    r = _act(c, "fin", wid, "mark_paid", _ref())
    assert r.status_code == 409 and "approved before" in r.text
    assert _wd(c, wid)["status"] == "pending" and _w(c) == before and _paid_rows(c, wid) == 0


def test_requested_can_be_rejected_and_the_reservation_returns(c):
    wid = _request(c)
    before = _w(c)
    assert _act(c, "fin", wid, "reject", note="Bank details mismatch").status_code == 200
    after = _w(c)
    assert after["available_balance"] == before["available_balance"] + 10000 and after["pending_balance"] == before["pending_balance"] - 10000
    w = _wd(c, wid)
    assert w["status"] == "rejected" and w["rejected_by"] == S["fin"]
    assert _act(c, "sup", wid, "mark_paid", _ref()).status_code in (400, 409)
    assert _act(c, "sup", wid, "approve").status_code == 400
    assert _act(c, "fin", wid, "reject").json().get("already") is True and _w(c) == after and _consistent(c) == {}


def test_an_approved_withdrawal_can_be_rejected(c):
    wid = _request(c)
    _act(c, "sup", wid, "approve")
    assert _act(c, "fin", wid, "reject").status_code == 200 and _wd(c, wid)["status"] == "rejected"


@pytest.mark.parametrize("ref", [None, "", "  ", "ab", "-UTR123", "UTR@123", "X" * 65])
def test_paying_needs_a_valid_payout_reference(c, ref):
    wid = _request(c)
    _act(c, "sup", wid, "approve")
    before = _w(c)
    assert _act(c, "fin", wid, "mark_paid", ref).status_code == 422
    assert _wd(c, wid)["status"] == "approved" and _w(c) == before and _paid_rows(c, wid) == 0


def test_paid_is_final_and_its_reference_is_immutable(c):
    wid = _request(c)
    _act(c, "sup", wid, "approve")
    ref = _ref()
    assert _act(c, "fin", wid, "mark_paid", ref).status_code == 200
    after = _w(c)
    again = _act(c, "fin", wid, "mark_paid", _ref())                   # a retry, even with another reference, changes nothing
    assert again.status_code == 200 and again.json().get("already") is True
    assert _wd(c, wid)["payout_reference"] == ref.upper() and _w(c) == after and _paid_rows(c, wid) == 1
    assert _act(c, "sup", wid, "reject").status_code == 400 and _act(c, "sup", wid, "approve").status_code == 400
    assert _w(c) == after


def test_invalid_action_is_refused(c):
    wid = _request(c)
    assert c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S["fin"]), json={"action": "cancel"}).status_code == 400


# ================================================================ segregation of duties
def test_the_approver_cannot_pay_but_another_finance_user_can(c):
    wid = _request(c)
    _act(c, "fin", wid, "approve")
    before = _w(c)
    r = _act(c, "fin", wid, "mark_paid", _ref())
    assert r.status_code == 403 and "cannot also pay" in r.text
    assert _w(c) == before and _paid_rows(c, wid) == 0
    assert _act(c, "fin2", wid, "mark_paid", _ref()).status_code == 200


def test_a_second_approval_by_another_user_does_not_replace_the_approver(c):
    wid = _request(c)
    _act(c, "fin", wid, "approve")
    assert _act(c, "fin", wid, "approve").json().get("already") is True
    assert _act(c, "sup", wid, "approve").status_code == 409
    assert _wd(c, wid)["approved_by"] == S["fin"]
    assert _act(c, "fin", wid, "mark_paid", _ref()).status_code == 403           # the recorded approver still cannot pay


# ================================================================ payout reference uniqueness
def test_one_payout_reference_cannot_settle_two_withdrawals(c):
    a, b = _request(c), _request(c)
    _act(c, "sup", a, "approve")
    _act(c, "sup", b, "approve")
    ref = _ref()
    assert _act(c, "fin", a, "mark_paid", ref).status_code == 200
    before = _w(c)
    r = _act(c, "fin", b, "mark_paid", ref.lower())
    assert r.status_code == 409 and "another withdrawal" in r.text
    assert _wd(c, b)["status"] == "approved" and _w(c) == before and _paid_rows(c, b) == 0


# ================================================================ financial safety
def test_a_clawback_after_approval_blocks_payment_until_covered_and_a_refused_reference_can_be_reused(c):
    wid = _request(c)
    _act(c, "sup", wid, "approve")
    _run(c, lambda: wallet_apply(S["hg"], {"available_balance": -50000}))       # a clawback larger than what is available
    before = _w(c)
    ref = _ref()
    for _ in range(2):                                                       # refusal and its retry
        r = _act(c, "fin", wid, "mark_paid", ref)
        assert r.status_code == 409 and "cannot be paid" in r.text
        assert _w(c) == before and _paid_rows(c, wid) == 0 and _wd(c, wid)["status"] == "approved"
    assert _run(c, lambda: db.withdrawal_payout_refs.find_one({"_id": ref.upper()})) is None   # a refused payment holds no reference
    _run(c, lambda: wallet_apply(S["hg"], {"available_balance": 50000}))        # future earnings cover the deficit
    assert _act(c, "fin", wid, "mark_paid", ref).status_code == 200 and _paid_rows(c, wid) == 1


# ================================================================ legacy records
def _legacy_reserve(c):
    """What the real request path does for a 10.00 withdrawal: available -> pending, plus its WITHDRAWAL HELD ledger row."""
    _fund(c, 10)
    _run(c, lambda: wallet_apply(S["hg"], {"available_balance": -1000, "pending_balance": 1000}))
    _run(c, lambda: db.wallet_transactions.insert_one({"id": new_id(), "user_id": S["hg"], "type": "WITHDRAWAL", "direction": "debit",
                                                        "status": "HELD", "amount": 10.0, "amount_paise": 1000, "created_at": now_iso()}))


def _legacy(c, status, **extra):
    wid = new_id()
    _run(c, lambda: db.withdrawal_requests.insert_one({"id": wid, "request_number": "WDLEG", "user_id": S["hg"], "amount": 10.0,
                                                       "amount_paise": 1000, "status": status, "created_at": now_iso(), **extra}))
    return wid


def test_legacy_paid_and_rejected_withdrawals_stay_immutable(c):
    for status in ("paid", "rejected"):
        wid = _legacy(c, status)
        before = (_wd(c, wid), _w(c))
        for action, ref in (("approve", None), ("reject", None), ("mark_paid", _ref())):
            assert _act(c, "fin", wid, action, ref).status_code in (400, 409)
        assert (_wd(c, wid), _w(c)) == before
        assert "approved_by" not in _wd(c, wid)                                  # no approval data is invented


def test_a_legacy_approval_without_an_approver_must_be_approved_again_before_payment(c):
    _legacy_reserve(c)
    wid = _legacy(c, "approved")
    assert _act(c, "fin", wid, "mark_paid", _ref()).status_code == 409
    assert _act(c, "sup", wid, "approve").status_code == 200 and _wd(c, wid)["approved_by"] == S["sup"]
    assert _act(c, "fin", wid, "mark_paid", _ref()).status_code == 200


def test_a_legacy_under_review_request_enters_the_workflow_as_requested(c):
    _legacy_reserve(c)
    wid = _legacy(c, "under_review")
    assert _act(c, "fin", wid, "mark_paid", _ref()).status_code == 409
    assert _act(c, "sup", wid, "approve").status_code == 200


# ================================================================ races against real MongoDB
def _admin(key):
    return {"id": S[key], "role": ROLE_OF[key]}


def test_two_approvers_racing_record_exactly_one_approver(c):
    wid = _request(c)

    async def race():
        return await asyncio.gather(admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="approve"), None, admin=_admin("fin")),
                                    admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="approve"), None, admin=_admin("sup")),
                                    return_exceptions=True)
    res = _run(c, race)
    assert sum(1 for r in res if isinstance(r, dict) and not r.get("already")) == 1
    w = _wd(c, wid)
    assert w["status"] == "approved" and w["approved_by"] in (S["fin"], S["sup"])
    assert _run(c, lambda: db.audit_logs.count_documents({"entity_id": wid, "action": "withdrawal_approved"})) == 1


def test_two_payers_racing_pay_once(c):
    wid = _request(c)
    _act(c, "sup", wid, "approve")
    start = _w(c)
    ref = _ref()

    async def race():
        return await asyncio.gather(*[admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="mark_paid", payout_reference=ref),
                                                                     None, admin=_admin(k)) for k in ("fin", "fin2", "fin", "fin2")],
                                    return_exceptions=True)
    _run(c, race)
    end = _w(c)
    assert end["total_withdrawn"] == start["total_withdrawn"] + 10000 and end["pending_balance"] == start["pending_balance"] - 10000
    assert _paid_rows(c, wid) == 1 and _wd(c, wid)["status"] == "paid" and _consistent(c) == {}
    assert _run(c, lambda: db.audit_logs.count_documents({"entity_id": wid, "action": "withdrawal_paid"})) == 1


def test_approve_racing_reject_ends_in_one_consistent_state(c):
    wid = _request(c)
    start = _w(c)

    async def race():
        return await asyncio.gather(admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="approve"), None, admin=_admin("sup")),
                                    admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="reject"), None, admin=_admin("fin")),
                                    return_exceptions=True)
    _run(c, race)
    w = _wd(c, wid)
    ops = _run(c, lambda: db.wallets.find_one({"user_id": S["hg"]}))["applied_ops"]
    rejected = f"withdrawal_rejected:{wid}" in ops
    assert w["status"] == ("rejected" if rejected else "approved")
    end = _w(c)
    assert end["available_balance"] == start["available_balance"] + (10000 if rejected else 0) and _consistent(c) == {}


def test_two_withdrawals_racing_for_one_payout_reference_only_one_uses_it(c):
    a, b = _request(c), _request(c)
    _act(c, "sup", a, "approve")
    _act(c, "sup", b, "approve")
    start = _w(c)
    ref = _ref()

    async def race():
        return await asyncio.gather(*[admin_routes.review_withdrawal(w, admin_routes.WithdrawalReview(action="mark_paid", payout_reference=ref),
                                                                     None, admin=_admin("fin")) for w in (a, b)], return_exceptions=True)
    _run(c, race)
    paid = [w for w in (a, b) if _wd(c, w)["status"] == "paid"]
    assert len(paid) == 1 and _w(c)["total_withdrawn"] == start["total_withdrawn"] + 10000 and _consistent(c) == {}


def test_a_clawback_racing_payment_never_pays_unsafely(c):
    wid = _request(c)
    _act(c, "sup", wid, "approve")
    start = _w(c)

    async def race():
        return await asyncio.gather(wallet_apply(S["hg"], {"available_balance": -(start["available_balance"] + 10000)}),
                                    admin_routes.review_withdrawal(wid, admin_routes.WithdrawalReview(action="mark_paid", payout_reference=_ref()),
                                                                   None, admin=_admin("fin")), return_exceptions=True)
    _run(c, race)
    status = _wd(c, wid)["status"]
    assert _paid_rows(c, wid) == (1 if status == "paid" else 0)
    if status != "paid":
        assert status == "approved" and _w(c)["pending_balance"] == start["pending_balance"]
