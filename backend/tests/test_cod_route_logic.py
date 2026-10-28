"""COD route logic with an IN-MEMORY FAKE database. This is NOT MongoDB integration verification: it executes the real
handlers' ordering and refusal logic (authority before body, nothing written on a refusal, held orders never reach the
commission path) against a minimal stand-in. The real-database behaviour is covered by test_cod_safeguards.py, which
needs a throwaway MongoDB."""
import asyncio
import os

import pytest
from fastapi import HTTPException

os.environ.setdefault("DB_NAME", "x_fake_route_logic")
import shop_routes  # noqa: E402

TOTAL = 118000


class _Coll:
    def __init__(self, docs, log):
        self.docs, self.log = docs, log

    async def find_one(self, q, proj=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return dict(d)
        return None

    async def update_one(self, q, upd):
        self.log.append(("update", q, upd))
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                d.update(upd["$set"])
                return type("R", (), {"modified_count": 1})()
        return type("R", (), {"modified_count": 0})()

    def find(self, *a, **k):
        class _C:
            async def to_list(self, n):
                return []
        return _C()


class _Db:
    def __init__(self, order):
        self.writes = []
        self.orders = _Coll([order], self.writes)
        self.users = _Coll([], self.writes)


def _order(**kw):
    return {"id": "o1", "order_number": "N1", "user_id": "buyer", "seller_user_id": "seller", "payment_method": "cod",
            "payment_status": "cod_pending", "status": "placed", "total_paise": TOTAL, "total": TOTAL / 100, **kw}


@pytest.fixture
def env(monkeypatch):
    calls = {"distribute": 0, "ledger": 0}

    async def noop(*a, **k):
        return None

    async def distribute(*a, **k):
        calls["distribute"] += 1
        return {"credited": 3}

    async def ledger(*a, **k):
        calls["ledger"] += 1
    monkeypatch.setattr(shop_routes, "log_audit", noop)
    monkeypatch.setattr(shop_routes, "create_notification", noop)

    async def seq(*a, **k):
        return "INV-000001"
    monkeypatch.setattr(shop_routes, "next_sequence", seq)
    monkeypatch.setattr("commission.distribute_sale_commissions", distribute)
    monkeypatch.setattr("ledger.post_order_collected", ledger)

    def make(order=None):
        fake = _Db(order or _order())
        monkeypatch.setattr(shop_routes, "db", fake)
        return fake
    return make, calls


def _call(user, body):
    return asyncio.run(shop_routes.cod_collected("o1", None, user=user, body=body))


GOOD = {"amount_collected": 1180.0, "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1234"}


@pytest.mark.parametrize("user", [{"id": "f", "role": "accounts_admin"}, {"id": "d", "role": "distributor"}, {"id": "s", "role": "support_admin"}])
def test_unauthorised_role_is_refused_before_the_body_or_any_write(env, user):
    make, calls = env
    fake = make()
    for body in (GOOD, None, {"junk": 1}):
        with pytest.raises(HTTPException) as e:
            _call(user, body)
        assert e.value.status_code == 403
    assert fake.writes == [] and calls == {"distribute": 0, "ledger": 0}


def test_dual_role_attributed_homegenie_is_refused_with_no_write(env):
    make, calls = env
    fake = make()
    with pytest.raises(HTTPException) as e:
        _call({"id": "seller", "role": "admin"}, GOOD)
    assert e.value.status_code == 403 and fake.writes == [] and calls["distribute"] == 0


@pytest.mark.parametrize("bad", [None, {}, {**GOOD, "amount_collected": 0}, {**GOOD, "evidence_reference": " "}, {**GOOD, "evidence_type": "x"}])
def test_invalid_evidence_never_marks_the_order_paid_or_writes(env, bad):
    make, calls = env
    fake = make()
    with pytest.raises(HTTPException) as e:
        _call({"id": "admin1", "role": "admin"}, bad)
    assert e.value.status_code == 422
    assert fake.writes == [] and fake.orders.docs[0]["payment_status"] == "cod_pending" and calls["distribute"] == 0


@pytest.mark.parametrize("body,reason", [({**GOOD, "evidence_type": "manual_exception"}, "manual_exception"),
                                         ({**GOOD, "amount_collected": 1000.0}, "amount_mismatch")])
def test_held_collections_never_reach_commission_or_ledger(env, body, reason):
    make, calls = env
    fake = make()
    r = _call({"id": "admin1", "role": "admin"}, body)
    assert r["discrepancy"] is True and r["reason"] == reason
    o = fake.orders.docs[0]
    assert o["payment_status"] == "cod_discrepancy" and o["cod_discrepancy"]["reported_by"] == "admin1"
    assert calls == {"distribute": 0, "ledger": 0}


def test_valid_full_collection_is_paid_once_with_evidence(env):
    make, calls = env
    fake = make()
    fake.users.docs.append({"id": "buyer"})
    r = _call({"id": "admin1", "role": "admin"}, GOOD)
    o = fake.orders.docs[0]
    assert r["ok"] and o["payment_status"] == "paid" and o["cod_collection"]["verified_by_system"] is False
    assert o["cod_collection"]["reference"] == "AWB-1234" and o["cod_collection"]["collected_paise"] == TOTAL
    again = _call({"id": "admin1", "role": "admin"}, GOOD)
    assert again["already"] is True and calls == {"distribute": 1, "ledger": 1}


# ---------------------------------------------------------------- commission path guards (fake DB, NOT MongoDB integration)
import commission  # noqa: E402


class _CommDb:
    def __init__(self, order, plan=True):
        self.orders = _Coll([order], [])
        self.commission_plans = _Coll([{"_id": order["id"], "items": [], "base": 0}] if plan else [], [])


@pytest.mark.parametrize("order", [
    _order(payment_status="cod_discrepancy"),                                                    # held
    _order(payment_status="paid"),                                                               # legacy paid COD, no evidence record
    _order(payment_status="paid", cod_collection={"type": "manual_exception", "expected_paise": TOTAL, "collected_paise": TOTAL}),
    _order(payment_status="paid", cod_collection={"type": "courier_confirmation", "expected_paise": TOTAL, "collected_paise": 100}),  # short
])
def test_resume_distribution_will_not_finish_a_plan_for_unproven_cod(monkeypatch, order):
    monkeypatch.setattr(commission, "db", _CommDb(order))
    r = asyncio.run(commission.resume_distribution("o1"))
    assert r == {"credited": 0, "reason": "cod_collection_not_proven"}


def test_resume_distribution_still_runs_for_online_and_for_proven_cod(monkeypatch):
    for order in (_order(payment_method="online", payment_status="paid"),
                  _order(payment_status="paid", cod_collection={"type": "courier_confirmation", "expected_paise": TOTAL, "collected_paise": TOTAL})):
        monkeypatch.setattr(commission, "db", _CommDb(order))
        r = asyncio.run(commission.resume_distribution("o1"))
        assert r.get("reason") != "cod_collection_not_proven"


def test_distribute_guard_does_not_touch_online_orders(monkeypatch):
    seen = {}

    async def fake_find(*a, **k):
        seen["reached_plan_lookup"] = True
        return {"_id": "o1"}

    class _P:
        find_one = staticmethod(fake_find)

    async def fake_resume(oid):
        return {"credited": 0, "complete": True, "reason": "already_processed"}

    async def noop(*a, **k):
        return None
    monkeypatch.setattr(commission, "db", type("D", (), {"commission_plans": _P})())
    monkeypatch.setattr(commission, "resume_distribution", fake_resume)
    monkeypatch.setattr(commission, "log_audit", noop)
    online = _order(payment_method="online", payment_status="paid")
    r = asyncio.run(commission.distribute_sale_commissions(online, {"id": "buyer2"}))
    assert seen.get("reached_plan_lookup") and r.get("reason") != "cod_collection_not_proven"


# ---------------------------------------------------------------- partial-collection refund reservation (fake DB, NOT MongoDB integration)
class _RefundOrders:
    """Just enough of orders.find_one/update_one for _reserve_refund: equality, $ne and $exists, with $set and $push."""
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, q, proj=None):
        return dict(self.doc) if self.doc.get("id") == q.get("id") else None

    @staticmethod
    def _match(doc, q):
        for k, v in q.items():
            cur = doc.get(k)
            if isinstance(v, dict) and "$ne" in v:
                if (v["$ne"] in cur) if isinstance(cur, list) else (cur == v["$ne"]):
                    return False
            elif isinstance(v, dict) and "$exists" in v:
                if (k in doc) != v["$exists"]:
                    return False
            elif cur != v:
                return False
        return True

    async def update_one(self, q, upd):
        if not self._match(self.doc, q):
            return type("R", (), {"modified_count": 0})()
        self.doc.update(upd.get("$set", {}))
        for k, v in upd.get("$push", {}).items():
            self.doc.setdefault(k, []).append(v)
        return type("R", (), {"modified_count": 1})()


def _short_order():
    return _order(payment_status="paid", cod_collected_paise=100000, refunded_paise=0, refunded_amount=0.0, refund_event_ids=[])


def _reserve(monkeypatch, order, event):
    holder = type("D", (), {"orders": _RefundOrders(order)})()
    monkeypatch.setattr(shop_routes, "db", holder)
    return asyncio.run(shop_routes._reserve_refund("o1", event))


def test_refund_on_a_short_collected_order_cannot_exceed_the_cash_collected(monkeypatch):
    o = _short_order()
    over = {"id": "e1", "amount_paise": 100001, "closes_order": True}
    assert _reserve(monkeypatch, o, over) == "exceeds"
    assert o["refunded_paise"] == 0 and o["refund_event_ids"] == [] and o["payment_status"] == "paid"


def test_refund_of_exactly_the_collected_cash_closes_the_order_once(monkeypatch):
    o = _short_order()
    ev = {"id": "e2", "amount_paise": 100000, "closes_order": True}
    assert _reserve(monkeypatch, o, ev) is None
    assert o["refunded_paise"] == 100000 and o["payment_status"] == "refunded" and o["refund_event_ids"] == ["e2"]
    assert _reserve(monkeypatch, o, ev) is None                                       # a retry of the same event changes nothing
    assert o["refunded_paise"] == 100000 and o["refund_event_ids"] == ["e2"]
    again = {"id": "e3", "amount_paise": 1, "closes_order": False}
    assert _reserve(monkeypatch, o, again) == "exceeds"                               # nothing left to refund


def test_partial_refunds_on_a_short_order_accumulate_to_the_ceiling_only(monkeypatch):
    o = _short_order()
    assert _reserve(monkeypatch, o, {"id": "p1", "amount_paise": 40000, "closes_order": False}) is None
    assert o["payment_status"] == "partially_refunded"
    assert _reserve(monkeypatch, o, {"id": "p2", "amount_paise": 60001, "closes_order": True}) == "exceeds"
    assert _reserve(monkeypatch, o, {"id": "p3", "amount_paise": 60000, "closes_order": True}) is None
    assert o["refunded_paise"] == 100000 and o["payment_status"] == "refunded"


def test_a_fully_collected_or_online_order_still_refunds_up_to_the_order_total(monkeypatch):
    for o in (_order(payment_status="paid", cod_collected_paise=TOTAL, refunded_paise=0, refunded_amount=0.0, refund_event_ids=[]),
              _order(payment_method="online", payment_status="paid", refunded_paise=0, refunded_amount=0.0, refund_event_ids=[])):
        assert _reserve(monkeypatch, o, {"id": "f1", "amount_paise": TOTAL, "closes_order": True}) is None
        assert o["refunded_paise"] == TOTAL and o["payment_status"] == "refunded"
