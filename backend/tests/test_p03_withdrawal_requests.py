"""Programme 03 (B-022): crash-safe, idempotent withdrawal requests.

The request is written first (reserving), the money is held at most once on the wallet (applied_ops withdrawal_hold:<id>), the HELD
ledger row is ensured, then the request opens as pending and the member notice + audit record are written once. These tests crash
the flow at every boundary, race it against itself and against the repair sweep, and check the wallet against its ledger each time.
Eligibility, limits, approval and payout rules are unchanged (covered by test_withdrawal_controls / test_role_eligibility_wallets).
Integration: THROWAWAY MongoDB. Run in its own process: `pytest tests/test_p03_withdrawal_requests.py -n 0`.
"""
import asyncio
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": os.environ.get("DB_NAME", "homegenies_p03_withdrawal_test"),
                   "JWT_SECRET": "p03-withdrawals-" + "k" * 40, "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app",
                   "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import wallet_routes  # noqa: E402
import withdrawal_intents as wi  # noqa: E402
import financial_ops  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id, wallet_apply  # noqa: E402
from wallet_reconcile import expected_aggregates  # noqa: E402

S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _user(key, role="distributor"):
    uid = new_id()
    S[key] = {"id": uid, "distributor_id": ("P" + uid[:7]).upper(), "full_name": key, "mobile": "7" + f"{abs(hash(uid)) % 10**9:09d}",
              "email": f"{key}-{uid[:5]}@example.com", "password_hash": hash_password("x" * 12), "role": role, "status": "green",
              "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
    return S[key]


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            await db.users.insert_many([_user("fin", "accounts_admin"), _user("fin2", "accounts_admin")])
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _member(c, rupees=1000):
    """A fresh verified HomeGenie with `rupees` available, credited through the ledger so the wallet reconciles."""
    u = _user("hg-" + new_id()[:6])

    async def go():
        await db.users.insert_one(dict(u))
        await db.kyc_records.insert_one({"user_id": u["id"], "status": "verified"})
        if rupees:
            await wallet_apply(u["id"], {"available_balance": rupees * 100, "total_earned": rupees * 100})
            await db.wallet_transactions.insert_one({"id": new_id(), "user_id": u["id"], "type": "MANUAL_ADMIN_CREDIT",
                                                     "direction": "credit", "status": "CREDITED", "amount": float(rupees),
                                                     "amount_paise": rupees * 100, "created_at": now_iso()})
    _run(c, go)
    return u


def _post(c, u, amount, key=None):
    body = {"amount": amount}
    if key is not None:
        body["request_key"] = key
    return c.post("/api/withdrawals", headers=_hdr(u["id"]), json=body)


def _w(c, u):
    w = _run(c, lambda: db.wallets.find_one({"user_id": u["id"]}, {"_id": 0})) or {}
    return {f: w.get(f + "_paise", 0) for f in ("pending_balance", "available_balance", "total_earned", "total_withdrawn")}


def _ops(c, u):
    return set((_run(c, lambda: db.wallets.find_one({"user_id": u["id"]}, {"_id": 0, "applied_ops": 1})) or {}).get("applied_ops") or [])


def _consistent(c, u):
    rows = _run(c, lambda: db.wallet_transactions.find({"user_id": u["id"]}, {"_id": 0}).to_list(5000))
    exp, act = expected_aggregates(rows), _w(c, u)
    return {f: (exp[f], act[f]) for f in exp if exp[f] != act[f]}


def _wds(c, u):
    return _run(c, lambda: db.withdrawal_requests.find({"user_id": u["id"]}, {"_id": 0}).to_list(100))


def _count(c, coll, q):
    return _run(c, lambda: db[coll].count_documents(q))


def _effects(c, wid):
    return (_count(c, "notifications", {"meta.withdrawal_id": wid, "meta.event": "requested"}),
            _count(c, "audit_logs", {"action": "withdrawal_requested", "entity_id": wid}))


def _sweep(c, **kw):
    return _run(c, lambda: wi.repair_withdrawal_requests(stale_seconds=kw.pop("stale_seconds", 0), **kw))


class Crash(Exception):
    pass


def _key():
    return "k-" + new_id()


# ================================================================ normal path
def test_request_reserves_once_writes_ledger_and_opens(c):
    u = _member(c, 1000)
    r = _post(c, u, 250.5, _key())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending" and body["amount_paise"] == 25050
    assert "request_key" not in body and "hold_op" not in body               # internal fields are not returned
    assert _w(c, u)["available_balance"] == 100000 - 25050 and _w(c, u)["pending_balance"] == 25050
    assert wi.hold_op(body["id"]) in _ops(c, u)
    assert _count(c, "wallet_transactions", {"op_key": wi.hold_op(body["id"]), "status": "HELD", "amount_paise": 25050}) == 1
    assert _effects(c, body["id"]) == (1, 1)
    wr = _wds(c, u)[0]
    assert "effects_due" not in wr and wr["reserved_at"]
    assert _consistent(c, u) == {}


def test_request_without_key_still_works(c):
    """Older clients send no key: still intent-first and crash-safe, just not deduplicated across retries."""
    u = _member(c, 100)
    r = _post(c, u, 40)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert _consistent(c, u) == {}


@pytest.mark.parametrize("bad", ["short", "has space here", "x" * 81, "semi;colon-key"])
def test_malformed_key_is_rejected_without_side_effects(c, bad):
    u = _member(c, 100)
    assert _post(c, u, 10, bad).status_code == 422
    assert _wds(c, u) == [] and _w(c, u)["available_balance"] == 10000


def test_eligibility_rules_unchanged(c):
    u = _member(c, 100)
    _run(c, lambda: db.kyc_records.update_one({"user_id": u["id"]}, {"$set": {"status": "pending"}}))
    assert _post(c, u, 10, _key()).status_code == 400                       # KYC still required
    v = _member(c, 100)
    _run(c, lambda: db.users.update_one({"id": v["id"]}, {"$set": {"status": "yellow"}}))
    assert _post(c, v, 10, _key()).status_code == 403                       # approved selling role still required
    assert _wds(c, u) == [] and _wds(c, v) == []


# ================================================================ idempotency
def test_same_key_returns_same_request_never_a_second_hold(c):
    u = _member(c, 1000)
    k = _key()
    first = _post(c, u, 300, k).json()
    for _ in range(3):
        again = _post(c, u, 300, k)
        assert again.status_code == 200 and again.json()["id"] == first["id"] and again.json()["already"] is True
    assert len(_wds(c, u)) == 1
    assert _w(c, u)["pending_balance"] == 30000 and _w(c, u)["available_balance"] == 70000
    assert _count(c, "wallet_transactions", {"user_id": u["id"], "type": "WITHDRAWAL"}) == 1
    assert _effects(c, first["id"]) == (1, 1)
    assert _consistent(c, u) == {}


def test_same_key_different_amount_is_refused(c):
    u = _member(c, 1000)
    k = _key()
    first = _post(c, u, 300, k).json()
    r = _post(c, u, 301, k)
    assert r.status_code == 409
    assert len(_wds(c, u)) == 1 and _w(c, u)["pending_balance"] == 30000 and _wds(c, u)[0]["id"] == first["id"]


def test_same_key_is_per_member(c):
    a, b = _member(c, 100), _member(c, 100)
    k = _key()
    ra, rb = _post(c, a, 50, k), _post(c, b, 50, k)
    assert ra.status_code == rb.status_code == 200 and ra.json()["id"] != rb.json()["id"]


def test_different_keys_are_different_requests(c):
    u = _member(c, 1000)
    assert _post(c, u, 100, _key()).json()["id"] != _post(c, u, 100, _key()).json()["id"]
    assert len(_wds(c, u)) == 2 and _w(c, u)["pending_balance"] == 20000 and _consistent(c, u) == {}


# ================================================================ insufficient balance
def test_insufficient_balance_creates_nothing(c):
    u = _member(c, 100)
    r = _post(c, u, 100.01, _key())
    assert r.status_code == 400 and "Insufficient" in r.json()["detail"]
    assert _wds(c, u) == [] and _w(c, u)["available_balance"] == 10000 and _ops(c, u) == set()


def test_balance_lost_between_check_and_hold_closes_as_not_reserved(c, monkeypatch):
    """The fast check passes, then the balance drops before the atomic hold: the request is closed, nothing moves, 400."""
    u = _member(c, 100)
    real = wi.apply_hold

    async def drained(wr):
        await wallet_apply(u["id"], {"available_balance": -9000})            # something else spent the money meanwhile
        return await real(wr)
    monkeypatch.setattr(wi, "apply_hold", drained)
    r = _post(c, u, 50, _key())
    assert r.status_code == 400
    (wr,) = _wds(c, u)
    assert wr["status"] == "not_reserved" and wr["closed_reason"] == "insufficient_balance"
    assert wi.void_op(wr["id"]) in _ops(c, u) and wi.hold_op(wr["id"]) not in _ops(c, u)
    assert _w(c, u)["available_balance"] == 1000 and _w(c, u)["pending_balance"] == 0
    assert c.get("/api/withdrawals", headers=_hdr(u["id"])).json() == []    # never shown to the member as a withdrawal
    assert _effects(c, wr["id"]) == (0, 0)
    closed = _run(c, lambda: db.audit_logs.find({"action": "withdrawal_request_not_reserved", "entity_id": wr["id"]}, {"_id": 0}).to_list(5))
    assert len(closed) == 1 and closed[0]["user_id"] == u["id"] and closed[0]["new_value"]["money_moved"] is False


def test_not_reserved_key_retry_is_refused_not_resurrected(c, monkeypatch):
    u = _member(c, 100)
    real = wi.apply_hold

    async def drained(wr):
        await wallet_apply(u["id"], {"available_balance": -9000})
        return await real(wr)
    monkeypatch.setattr(wi, "apply_hold", drained)
    k = _key()
    assert _post(c, u, 50, k).status_code == 400
    monkeypatch.setattr(wi, "apply_hold", real)
    _run(c, lambda: wallet_apply(u["id"], {"available_balance": 9000}))      # money is back
    assert _post(c, u, 50, k).status_code == 400                             # the closed attempt stays closed
    assert _w(c, u)["pending_balance"] == 0 and len(_wds(c, u)) == 1


# ================================================================ crash at every boundary
def _crash_at(monkeypatch, where):
    """where: before_hold | after_hold | after_ledger | after_open | mid_effects"""
    if where == "before_hold":
        async def boom(wr):
            raise Crash(where)
        monkeypatch.setattr(wi, "apply_hold", boom)
    elif where == "after_hold":
        async def boom(row):
            raise Crash(where)
        monkeypatch.setattr(financial_ops, "ensure_ledger", boom)
    elif where == "after_ledger":
        real = financial_ops.ensure_ledger

        async def boom(row):
            await real(row)                                  # the ledger row is written, then the process dies before the claim
            raise Crash(where)
        monkeypatch.setattr(financial_ops, "ensure_ledger", boom)
    elif where == "after_open":
        async def boom(*a, **k):
            raise Crash(where)
        monkeypatch.setattr(wi, "finish_effects", boom)
    elif where == "mid_effects":
        async def boom(*a, **k):
            raise Crash(where)
        monkeypatch.setattr(wi, "log_audit", boom)          # the notice is written, then the process dies before the audit


def _crashed_request(c, monkeypatch, u, where, amount=100, key=None):
    with monkeypatch.context() as m:
        _crash_at(m, where)
        with pytest.raises(Crash):
            _post(c, u, amount, key or _key())
    (wr,) = _wds(c, u)
    return wr


@pytest.mark.parametrize("where,expect_status,held", [
    ("before_hold", "reserving", False), ("after_hold", "reserving", True), ("after_ledger", "reserving", True),
    ("after_open", "pending", True), ("mid_effects", "pending", True)])
def test_crash_leaves_a_recoverable_state(c, monkeypatch, where, expect_status, held):
    u = _member(c, 500)
    wr = _crashed_request(c, monkeypatch, u, where)
    assert wr["status"] == expect_status
    assert (wi.hold_op(wr["id"]) in _ops(c, u)) is held
    if held:
        assert _w(c, u)["pending_balance"] == 10000
    else:
        assert _w(c, u) == {"pending_balance": 0, "available_balance": 50000, "total_earned": 50000, "total_withdrawn": 0}
    if where in ("after_open", "mid_effects"):
        assert wr.get("effects_due") is True
    # finance cannot act on a request that is still reserving
    if expect_status == "reserving":
        for action in ("approve", "reject"):
            r = c.put(f"/api/admin/withdrawals/{wr['id']}", headers=_hdr(S["fin"]["id"]), json={"action": action})
            assert r.status_code in (400, 409), (action, r.text)
        assert _wds(c, u)[0]["status"] == "reserving"


@pytest.mark.parametrize("where", ["before_hold", "after_hold", "after_ledger", "after_open", "mid_effects"])
def test_repair_sweep_finishes_every_crash(c, monkeypatch, where):
    u = _member(c, 500)
    wr = _crashed_request(c, monkeypatch, u, where)
    res = _sweep(c)
    assert res["failed"] == 0 and res["effects"]["failed"] == 0
    (after,) = _wds(c, u)
    if where == "before_hold":                       # no money ever moved: the request is closed, the wallet untouched
        assert after["status"] == "not_reserved" and after["closed_reason"] == "interrupted_before_reservation"
        assert wi.void_op(wr["id"]) in _ops(c, u) and _w(c, u)["pending_balance"] == 0
        assert _effects(c, wr["id"]) == (0, 0)
        closed = _run(c, lambda: db.audit_logs.find({"action": "withdrawal_request_not_reserved", "entity_id": wr["id"]}).to_list(5))
        assert len(closed) == 1 and closed[0]["user_id"] == "system"
    else:
        assert after["status"] == "pending" and "effects_due" not in after
        assert _count(c, "wallet_transactions", {"op_key": wi.hold_op(wr["id"])}) == 1
        assert _effects(c, wr["id"]) == (1, 1)
        assert _w(c, u)["pending_balance"] == 10000
    assert _consistent(c, u) == {}
    again = _sweep(c)                                               # a second run changes nothing
    assert _wds(c, u) == [after] and _effects(c, wr["id"]) == ((0, 0) if where == "before_hold" else (1, 1))
    assert again["updated"] == 0 and again["effects"]["updated"] == 0


@pytest.mark.parametrize("where", ["before_hold", "after_hold", "after_ledger", "after_open", "mid_effects"])
def test_retry_with_same_key_finishes_every_crash(c, monkeypatch, where):
    u = _member(c, 500)
    k = _key()
    wr = _crashed_request(c, monkeypatch, u, where, key=k)
    r = _post(c, u, 100, k)
    assert r.status_code == 200 and r.json()["id"] == wr["id"]
    (after,) = _wds(c, u)
    assert after["status"] == "pending"
    assert _count(c, "wallet_transactions", {"op_key": wi.hold_op(wr["id"])}) == 1 and _w(c, u)["pending_balance"] == 10000
    assert _consistent(c, u) == {}
    _sweep(c)                                            # the sweep finishes any notice / audit the crash left behind, once
    assert _effects(c, wr["id"]) == (1, 1) and "effects_due" not in _wds(c, u)[0]


def test_sweep_ignores_fresh_reserving_requests(c, monkeypatch):
    """A request still inside its own call (younger than the stale window) is not touched by the sweep."""
    u = _member(c, 500)
    wr = _crashed_request(c, monkeypatch, u, "before_hold")
    res = _sweep(c, stale_seconds=3600)
    assert _wds(c, u)[0]["status"] == "reserving" and wi.void_op(wr["id"]) not in _ops(c, u)
    assert res["updated"] == 0


def test_sweep_dry_run_writes_nothing(c, monkeypatch):
    u = _member(c, 500)
    wr = _crashed_request(c, monkeypatch, u, "after_hold")
    before = (_wds(c, u), _w(c, u), _ops(c, u))
    res = _sweep(c, dry_run=True)
    assert res["eligible"] >= 1 and (_wds(c, u), _w(c, u), _ops(c, u)) == before
    assert _count(c, "wallet_transactions", {"op_key": wi.hold_op(wr["id"])}) == 0


def test_maintenance_runs_the_withdrawal_repair(c, monkeypatch):
    u = _member(c, 500)
    _crashed_request(c, monkeypatch, u, "after_ledger")
    _run(c, lambda: db.withdrawal_requests.update_one({"user_id": u["id"]}, {"$set": {"created_at": "2000-01-01T00:00:00+00:00"}}))
    from cron_routes import run_maintenance
    out = _run(c, lambda: run_maintenance())
    assert "withdrawal_requests" in out and _wds(c, u)[0]["status"] == "pending"


# ================================================================ races
def test_hold_and_void_exclude_each_other_under_race(c, monkeypatch):
    """The original call (hold) racing the repair sweep (void) on the same stalled request: exactly one wins, every time."""
    for _ in range(8):
        u = _member(c, 500)
        wr = _crashed_request(c, monkeypatch, u, "before_hold")

        async def race():
            return await asyncio.gather(wi.settle(dict(wr), actor=u), wi.repair_withdrawal_requests(stale_seconds=0))
        _run(c, race)
        (after,) = _wds(c, u)
        ops = _ops(c, u)
        assert (wi.hold_op(wr["id"]) in ops) != (wi.void_op(wr["id"]) in ops)
        if wi.hold_op(wr["id"]) in ops:
            assert after["status"] == "pending" and _w(c, u)["pending_balance"] == 10000
        else:
            assert after["status"] == "not_reserved" and _w(c, u)["pending_balance"] == 0
        assert _consistent(c, u) == {}


def test_concurrent_same_key_requests_make_one_request(c):
    u = _member(c, 1000)
    k = _key()
    body = wallet_routes.WithdrawBody(amount=200, request_key=k)

    async def one():
        try:
            return await wallet_routes.request_withdrawal(body, None, user=u)
        except HTTPException as e:
            return e

    async def race():
        return await asyncio.gather(*[one() for _ in range(6)])
    res = _run(c, race)
    ok = [r for r in res if isinstance(r, dict)]
    assert ok and len({r["id"] for r in ok}) == 1
    assert all(isinstance(r, dict) or r.status_code == 503 for r in res)    # a loser may only be told to retry
    assert len(_wds(c, u)) == 1 and _w(c, u)["pending_balance"] == 20000
    assert _count(c, "wallet_transactions", {"user_id": u["id"], "type": "WITHDRAWAL"}) == 1
    assert _effects(c, ok[0]["id"]) == (1, 1) and _consistent(c, u) == {}


def test_concurrent_different_keys_never_overdraw(c):
    """Ten concurrent 300 requests against 1000 available: at most three are reserved, the rest refused, never negative."""
    u = _member(c, 1000)

    async def one():
        try:
            return await wallet_routes.request_withdrawal(wallet_routes.WithdrawBody(amount=300, request_key=_key()), None, user=u)
        except HTTPException as e:
            return e

    async def race():
        return await asyncio.gather(*[one() for _ in range(10)])
    res = _run(c, race)
    ok = [r for r in res if isinstance(r, dict)]
    assert len(ok) == 3 and all(r.status_code == 400 for r in res if not isinstance(r, dict))
    w = _w(c, u)
    assert w["available_balance"] == 10000 and w["pending_balance"] == 90000
    assert sum(1 for x in _wds(c, u) if x["status"] == "pending") == 3
    assert _consistent(c, u) == {}


# ================================================================ downstream: review still works, reconciliation is clean
def test_reserved_request_flows_through_review_and_reconciles(c):
    u = _member(c, 1000)
    a = _post(c, u, 300, _key()).json()["id"]
    b = _post(c, u, 200, _key()).json()["id"]
    assert c.put(f"/api/admin/withdrawals/{a}", headers=_hdr(S["fin"]["id"]), json={"action": "approve"}).status_code == 200
    r = c.put(f"/api/admin/withdrawals/{a}", headers=_hdr(S["fin2"]["id"]),
              json={"action": "mark_paid", "payout_reference": "UTR-" + new_id()[:10]})
    assert r.status_code == 200
    assert c.put(f"/api/admin/withdrawals/{b}", headers=_hdr(S["fin"]["id"]), json={"action": "reject"}).status_code == 200
    w = _w(c, u)
    assert w == {"pending_balance": 0, "available_balance": 70000, "total_earned": 100000, "total_withdrawn": 30000}
    assert _consistent(c, u) == {}
    audit = _run(c, lambda: wi.withdrawal_audit())
    mine = [i for i in audit["issues"] if i["withdrawal_id"] in (a, b)]
    assert mine == []


def test_withdrawal_audit_reports_inconsistencies(c):
    u = _member(c, 500)
    wid = _post(c, u, 100, _key()).json()["id"]
    _run(c, lambda: db.wallet_transactions.delete_one({"op_key": wi.hold_op(wid)}))        # simulate a lost ledger row
    issues = {i["withdrawal_id"]: i["issue"] for i in _run(c, lambda: wi.withdrawal_audit())["issues"]}
    assert issues.get(wid) == "hold_ledger_missing"


def test_money_guard_refuses_withdrawals_without_the_key_index(c):
    import money_guard
    u = _member(c, 100)

    async def drop():
        await db.withdrawal_requests.drop_index("withdrawal_requests_user_key_unique")
        money_guard._cache["state"] = None
    _run(c, drop)
    try:
        r = _post(c, u, 10, _key())
        assert r.status_code == 503
        assert _wds(c, u) == [] and _w(c, u)["available_balance"] == 10000
    finally:
        async def restore():
            from db_indexes import apply
            await apply()
            money_guard._cache["state"] = None
        _run(c, restore)
    assert _post(c, u, 10, _key()).status_code == 200


# ================================================================ P03-A04: the pay / reject path
def test_pay_refuses_before_moving_money_without_the_wallet_index(c):
    import money_guard
    u = _member(c, 500)
    wid = _post(c, u, 100, _key()).json()["id"]
    assert c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S["fin"]["id"]), json={"action": "approve"}).status_code == 200
    before = (_w(c, u), _ops(c, u))

    async def drop():
        await db.wallet_transactions.drop_index("wallet_transactions_op_key_unique")
        money_guard._cache["state"] = None
    _run(c, drop)
    try:
        r = c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S["fin2"]["id"]),
                  json={"action": "mark_paid", "payout_reference": "UTR-" + new_id()[:10]})
        assert r.status_code == 503 and (_w(c, u), _ops(c, u)) == before          # nothing moved
        assert _run(c, lambda: db.withdrawal_payout_refs.count_documents({"withdrawal_id": wid})) == 0
    finally:
        async def restore():
            from db_indexes import apply
            await apply()
            money_guard._cache["state"] = None
        _run(c, restore)
    r = c.put(f"/api/admin/withdrawals/{wid}", headers=_hdr(S["fin2"]["id"]),
              json={"action": "mark_paid", "payout_reference": "UTR-" + new_id()[:10]})
    assert r.status_code == 200 and _consistent(c, u) == {}


def test_audit_reports_a_wallet_settled_request_left_open(c):
    u = _member(c, 500)
    wid = _post(c, u, 100, _key()).json()["id"]
    _run(c, lambda: db.wallets.update_one({"user_id": u["id"]}, {"$push": {"applied_ops": f"withdrawal_paid:{wid}"}}))  # crash simulation
    issues = {i["withdrawal_id"]: i["issue"] for i in _run(c, lambda: wi.withdrawal_audit())["issues"]}
    assert issues.get(wid) == "wallet_settled_but_request_open"
