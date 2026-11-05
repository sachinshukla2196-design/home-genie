"""Phase 3B.6: order / payment / cancellation / expiry state machine. Regression tests for the defects found, the seven
named races (A-G) against real MongoDB, and the cross-cutting invariants. Integration: THROWAWAY MongoDB.

Run in its own process: `pytest tests/test_order_lifecycle_races.py -n 0`.
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_lifecycle_test", "JWT_SECRET": "lifecycle-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from commission import release_due_points, release_commission_now  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from wallet_reconcile import expected_aggregates  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
INITIAL = 20
OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


class Crash(Exception):
    pass


@pytest.fixture(autouse=True)
def _no_fault_leaks():
    yield
    stock._FAULT = None


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, did in (("cust", "distributor", "LCCUST"), ("seller", "distributor", "LCSELL"), ("admin", "super_admin", "LCADM"),
                                   ("vu", "vendor", "LCVND")):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": "93" + new_id()[:8].replace("-", "1"), "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "LCVND", "business_name": "Vendor LC", "status": "approved",
                      "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _product(c, vendor=True):
    p = {"id": new_id(), "sku": "LC-" + new_id()[:6], "name": "Saree", "images": [], "mrp": 1200, "selling_price": 1000, "gst_percent": 5,
         "stock": INITIAL, "category": "Sarees", "options": [], "vendor_id": S["v"]["id"] if vendor else None,
         "vendor_name": "Vendor LC" if vendor else None, "is_active": True, "approval_status": "approved", "created_at": now_iso()}
    _run(c, lambda: db.products.insert_one(dict(p)))
    return p["id"]


def _order(c, pid, qty=2, method="online", seller=True):
    body = {"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": method}
    if seller:
        body["seller_ref"] = "LCSELL"
    r = c.post("/api/orders", json=body, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _expire_age(c, oid):
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"created_at": (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()}}))


def _tx(c, o):
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    return sid


def _pay(c, sid):
    return _run(c, lambda: shop_routes._process_paid_order(sid))


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _stock(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}))["stock"]


def _moves(c, oid):
    return sorted(m["delta"] for m in _run(c, lambda: db.stock_movements.find({"order_id": oid}).to_list(50)))


def _comms(c, oid):
    return _run(c, lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))


def _sales(c, oid):
    return _run(c, lambda: db.vendor_ledger.count_documents({"order_id": oid, "type": "SALE_COLLECTED"}))


def _wallet_consistent(c, uid):
    rows = _run(c, lambda: db.wallet_transactions.find({"user_id": uid}, {"_id": 0}).to_list(5000))
    w = _run(c, lambda: db.wallets.find_one({"user_id": uid}, {"_id": 0})) or {}
    exp = expected_aggregates(rows)
    return {f: (exp[f], w.get(f + "_paise", 0)) for f in exp if exp[f] != w.get(f + "_paise", 0)}


def _invariants(c, pid, oid):
    """Order, stock, journal and money invariants that must hold after ANY interleaving."""
    o = _get(c, oid)
    total_moves = sum(m["delta"] for m in _run(c, lambda: db.stock_movements.find({"product_id": pid}).to_list(500)))
    assert _stock(c, pid) == INITIAL + total_moves, "stock counter disagrees with the movement log"
    rows = _run(c, lambda: db.stock_movements.aggregate([{"$match": {"order_id": oid}}, {"$group": {"_id": {"t": "$txn_id", "l": "$line"}, "n": {"$sum": 1}}}]).to_list(50))
    assert all(r["n"] == 1 for r in rows), "a transaction line was logged twice"
    held = -sum(_moves(c, oid))                                              # units this order currently holds
    active = o["status"] != "cancelled" and not o.get("needs_refund")
    assert held == (2 if active else 0), f"order {o['status']}/{o['payment_status']} holds {held} units"
    assert not (o["payment_status"] in ("paid", "partially_refunded") and o["status"] == "payment_pending")
    assert _run(c, lambda: db.stock_txns.count_documents({"order_id": oid, "status": {"$in": ["pending", "rolling_back"]}})) == 0
    types = [x["type"] for x in _comms(c, oid)]
    assert len(types) == len(set(types)), "a commission was created twice"
    if o.get("needs_refund") or o["payment_status"] not in ("paid", "partially_refunded", "refunded"):
        assert types == [], "commission on an order that was never validly paid"
    assert _sales(c, oid) <= 1
    assert _wallet_consistent(c, S["seller"]["id"]) == {}
    return o


# ================================================================ defect A: no payment path re-opens a refunded or COD order
def _refund(c, oid, amount=None, ref=None):
    return _run(c, lambda: shop_routes.reverse_order_financials(oid, {"id": S["admin"]["id"]}, None, refund_amount=amount,
                                                                reference=ref or ("RF-" + new_id()[:6]), reason="test"))


@pytest.mark.parametrize("partial", [False, True])
def test_a_refunded_order_is_never_marked_paid_again_by_any_payment_path(c, partial):
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)
    _pay(c, sid)
    _refund(c, o["id"], amount=100.0 if partial else None)
    before = _get(c, o["id"])
    assert before["payment_status"] == ("partially_refunded" if partial else "refunded")
    _run(c, lambda: db.payment_transactions.update_one({"session_id": sid}, {"$set": {"payment_status": "pending"}}))  # a re-delivered payment
    _pay(c, sid)
    assert c.post("/api/payments/upi-claim", json={"order_id": o["id"], "reference": "UTR-AGAIN"}, headers=_hdr(S["cust"]["id"])).status_code == 409
    assert c.put(f"/api/admin/payments/upi-confirm/{o['id']}", json={"reference": "UTR-AGAIN"}, headers=_hdr(S["admin"]["id"])).status_code == 409
    after = _get(c, o["id"])
    assert after["payment_status"] == before["payment_status"] and after["status"] == before["status"]
    assert after["refunded_paise"] == before["refunded_paise"] and after.get("invoice_number") == before.get("invoice_number")


@pytest.mark.parametrize("state", ["cod_pending", "cod_discrepancy"])
def test_a_cod_order_cannot_be_paid_through_upi_or_manual_payment(c, state):
    pid = _product(c)
    o = _order(c, pid, method="cod")
    if state == "cod_discrepancy":
        _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"payment_status": "cod_discrepancy"}}))
    assert c.post("/api/payments/upi-claim", json={"order_id": o["id"], "reference": "UTR-COD"}, headers=_hdr(S["cust"]["id"])).status_code == 409
    assert c.put(f"/api/admin/payments/upi-confirm/{o['id']}", json={"reference": "UTR-COD"}, headers=_hdr(S["admin"]["id"])).status_code == 409
    r = c.post("/api/admin/payments/manual", json={"distributor_id": "LCCUST", "reference": "MANUAL-1"}, headers=_hdr(S["admin"]["id"]))
    got = _get(c, o["id"])
    assert got["payment_status"] == state and got["payment_method"] == "cod" and _comms(c, o["id"]) == []
    if r.status_code == 200:                                                  # it may pick another (online) order, never this one
        assert r.json()["order"]["id"] != o["id"]


# ================================================================ defect B: the admin status route cannot contradict the order
def _admin_status(c, oid, status):
    return c.put(f"/api/admin/orders/{oid}/status", json={"status": status}, headers=_hdr(S["admin"]["id"]))


def test_an_expired_or_cancelled_order_cannot_be_reopened_without_stock(c):
    pid = _product(c)
    o = _order(c, pid)
    _expire_age(c, o["id"])
    _run(c, stock.expire_pending_online_orders)
    for st in ("processing", "packed", "shipped", "delivered", "confirmed"):
        assert _admin_status(c, o["id"], st).status_code in (400, 409), st
    assert _admin_status(c, o["id"], "cancelled").status_code == 200       # a repeat of the current state stays harmless
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, pid) == INITIAL
    _invariants(c, pid, o["id"])


def test_payment_states_and_unpaid_fulfilment_cannot_be_set_by_hand(c):
    pid = _product(c)
    o = _order(c, pid)                                                       # online, unpaid
    for st in ("paid", "pending", "payment_pending"):
        r = _admin_status(c, o["id"], st)
        assert r.status_code == (200 if st == "payment_pending" else 400), st          # payment_pending is its current state
    for st in ("processing", "shipped", "delivered"):
        assert _admin_status(c, o["id"], st).status_code == 409, st
    assert _get(c, o["id"])["status"] == "payment_pending" and _get(c, o["id"])["payment_status"] == "pending"
    cod = _order(c, pid, method="cod")                                       # COD ships before cash: fulfilment stays allowed
    assert _admin_status(c, cod["id"], "processing").status_code == 200


# ================================================================ defect C: no commission release for a cancelled paid order
def test_the_cron_does_not_release_commission_for_a_cancelled_paid_order(c):
    pid = _product(c)
    o = _order(c, pid)
    _pay(c, _tx(c, o))
    assert len(_comms(c, o["id"])) == 1
    assert _admin_status(c, o["id"], "cancelled").status_code == 200
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
    _run(c, release_due_points)
    cm = _comms(c, o["id"])[0]
    assert cm["released_at"] is None and cm["status"] == "PENDING"
    assert _run(c, lambda: release_commission_now(cm["id"]))["ok"] is False
    _refund(c, o["id"])                                                      # the refund then claws it back from pending
    assert _comms(c, o["id"])[0]["status"] == "REVERSED" and _wallet_consistent(c, S["seller"]["id"]) == {}


# ================================================================ races A-G (real concurrency)
@pytest.mark.parametrize("round_", range(5))
def test_race_a_payment_vs_expiry(c, round_):
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)
    _expire_age(c, o["id"])

    async def race():
        return await asyncio.gather(stock.expire_one(o["id"]), shop_routes._process_paid_order(sid), stock.expire_pending_online_orders(),
                                    return_exceptions=True)
    _run(c, race)
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    got = _invariants(c, pid, o["id"])
    assert got["payment_status"] == "paid"                                   # the payment always counts
    assert got["status"] in ("processing", "cancelled") and (got["status"] == "processing") != bool(got.get("needs_refund"))


@pytest.mark.parametrize("round_", range(5))
def test_race_b_payment_vs_customer_cancellation(c, round_):
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)

    async def cancel():
        return await asyncio.to_thread(lambda: c.post(f"/api/orders/{o['id']}/cancel", json={"reason": "Changed my mind"},
                                                      headers=_hdr(S["cust"]["id"])))

    async def race():
        return await asyncio.gather(shop_routes._process_paid_order(sid), return_exceptions=True)
    import threading
    t = threading.Thread(target=lambda: c.post(f"/api/orders/{o['id']}/cancel", json={"reason": "Changed my mind"}, headers=_hdr(S["cust"]["id"])))
    t.start()
    _run(c, race)
    t.join()
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    got = _invariants(c, pid, o["id"])
    if got["status"] == "cancelled" and got["payment_status"] == "paid" and not got.get("needs_refund"):
        # paid first, then cancelled: the commission waits for the refund case and is never released meanwhile
        _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
        _run(c, release_due_points)
        assert all(x["released_at"] is None for x in _comms(c, o["id"]))


@pytest.mark.parametrize("round_", range(5))
def test_race_c_admin_cancellation_vs_expiry(c, round_):
    pid = _product(c)
    o = _order(c, pid)
    _expire_age(c, o["id"])
    import threading
    t = threading.Thread(target=lambda: _admin_status(c, o["id"], "cancelled"))
    t.start()
    _run(c, stock.expire_pending_online_orders)
    t.join()
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    got = _invariants(c, pid, o["id"])
    assert got["status"] == "cancelled" and _stock(c, pid) == INITIAL and _moves(c, o["id"]) == [-2, 2]


def test_race_d_duplicate_payment_and_webhook_processing(c):
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)

    async def race():
        return await asyncio.gather(*[shop_routes._process_paid_order(sid) for _ in range(6)], return_exceptions=True)
    _run(c, race)
    got = _invariants(c, pid, o["id"])
    assert got["payment_status"] == "paid" and got["status"] == "processing" and got.get("invoice_number")
    assert len(_comms(c, o["id"])) == 1 and _sales(c, o["id"]) == 1
    assert _run(c, lambda: db.commission_plans.count_documents({"_id": o["id"]})) == 1
    for _ in range(3):
        _pay(c, sid)                                                         # later retries: nothing more
    assert len(_comms(c, o["id"])) == 1 and _sales(c, o["id"]) == 1 and _get(c, o["id"])["invoice_number"] == got["invoice_number"]


def test_race_e_late_payment_after_expiry_revives_with_stock(c):
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)
    _expire_age(c, o["id"])
    _run(c, stock.expire_pending_online_orders)
    assert _stock(c, pid) == INITIAL
    _pay(c, sid)
    got = _invariants(c, pid, o["id"])
    assert got["status"] == "processing" and got["payment_status"] == "paid" and _stock(c, pid) == INITIAL - 2
    _run(c, stock.expire_pending_online_orders)
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    assert _stock(c, pid) == INITIAL - 2 and _invariants(c, pid, o["id"])["status"] == "processing"


@pytest.mark.parametrize("round_", range(5))
def test_race_f_stock_recovery_vs_revival_after_an_interrupted_expiry(c, round_):
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)
    _expire_age(c, o["id"])

    def hook(p, **ctx):
        if p == "after_txn_created":
            stock._FAULT = None
            raise Crash(p)
    stock._FAULT = hook
    with pytest.raises(Crash):
        _run(c, lambda: stock.expire_one(o["id"]))

    async def race():
        return await asyncio.gather(stock.run_recovery(min_age_s=0), shop_routes._process_paid_order(sid),
                                    stock.expire_pending_online_orders(), return_exceptions=True)
    _run(c, race)
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    got = _invariants(c, pid, o["id"])
    assert got["payment_status"] == "paid" and got["status"] == "processing" and _stock(c, pid) == INITIAL - 2


@pytest.mark.parametrize("round_", range(5))
def test_race_g_refund_vs_commission_release(c, round_):
    pid = _product(c)
    o = _order(c, pid)
    _pay(c, _tx(c, o))
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
    cid = _comms(c, o["id"])[0]["id"]

    async def race():
        return await asyncio.gather(release_due_points(), release_commission_now(cid),
                                    shop_routes.reverse_order_financials(o["id"], {"id": S["admin"]["id"]}, None, reference="RG-" + new_id()[:6], reason="t"),
                                    return_exceptions=True)
    _run(c, race)
    cm = _comms(c, o["id"])[0]
    assert cm["status"] == "REVERSED" and cm["reversed_paise"] == cm["amount_paise"]   # fully clawed back, exactly once
    assert len(cm.get("reversal_records", [])) == 1
    assert _run(c, lambda: db.wallet_transactions.count_documents({"op_key": f"release:{cid}"})) <= 1
    assert _wallet_consistent(c, S["seller"]["id"]) == {}
    assert _get(c, o["id"])["payment_status"] == "refunded"


@pytest.mark.parametrize("interloper", ["expiry", "admin_cancel"])
def test_a_cancellation_landing_between_the_payment_read_and_claim_is_not_overwritten(c, monkeypatch, interloper):
    """Deterministic form of races A and B: the order is cancelled (expired, or by an admin) after the payment call has read it
    and before it claims it. The claim must miss and the payment be handled as a late payment, never overwrite 'cancelled'
    with 'processing' on an order whose stock was already returned."""
    pid = _product(c)
    o = _order(c, pid)
    sid = _tx(c, o)
    _expire_age(c, o["id"])
    real_next = shop_routes.next_sequence
    fired = {"n": 0}

    async def interleave(*a, **k):
        if fired["n"] == 0:
            fired["n"] = 1
            if interloper == "expiry":
                await stock.expire_one(o["id"])
            else:
                await asyncio.to_thread(lambda: _admin_status(c, o["id"], "cancelled"))
        return await real_next(*a, **k)
    monkeypatch.setattr(shop_routes, "next_sequence", interleave)
    _pay(c, sid)
    monkeypatch.setattr(shop_routes, "next_sequence", real_next)
    _run(c, lambda: stock.run_recovery(min_age_s=0))
    got = _invariants(c, pid, o["id"])
    assert fired["n"] == 1 and got["payment_status"] == "paid"
    if interloper == "expiry":           # expired: the late payment revives the order with its stock
        assert got["status"] == "processing" and _stock(c, pid) == INITIAL - 2
    else:                                # admin-cancelled: the decision stands; the payment is flagged for refund
        assert got["status"] == "cancelled" and got.get("needs_refund") is True and _stock(c, pid) == INITIAL
