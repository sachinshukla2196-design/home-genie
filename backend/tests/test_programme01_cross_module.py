"""Programme 01, section 12: cross-module financial integrity. Realistic synthetic data in an isolated database; every scenario
ends with ONE reconciliation of the whole order, in integer paise:

  customer paid - COD fee - refunds booked - refund owed for goods NOT SUPPLIED (open rto / vendor-rejection cases, whose
  vendor sale is reversed at once)  ==  net vendor goods in the vendor ledger (SALE_COLLECTED + SALE_REVERSAL + REFUND)
  (other open cases - returns, goodwill - move the ledger only when booked; any amount an open case promises beyond what is
  still refundable is REPORTED as `over_promised`, the known gap B-021, never hidden)
  HomeGenie commission reversed  ==  credited x refunded / goods value   (each commission, within rounding of 1 paisa)
  platform commission revenue    ==  - sum(vendor COMMISSION entries)    (no agreement in these scenarios: 0)
  wallet aggregates              ==  wallet ledger
  product stock                  ==  start - units still reserved by live orders

No balancing entry is ever created by the test; the numbers must agree on their own.
Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_cross_module.py -n 0`.
"""
import os
import threading

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_cross_test", "JWT_SECRET": "p01-cross-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import commission  # noqa: E402
import db_indexes  # noqa: E402
import ledger  # noqa: E402
import money_guard  # noqa: E402
import order_completion  # noqa: E402
import returns_routes  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from commission import release_due_points  # noqa: E402
from core import db  # noqa: E402
from eligibility import payout_block  # noqa: E402
from p01_harness import World, seed_world, hdr  # noqa: E402

S = {}
START = 50


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "XM")
        client.portal.call(seed)
        yield World(client, S, "XMSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def reconcile(w, oid, pids=()):
    """The whole-order reconciliation. Returns the figures for scenario-specific checks."""
    o = w.get(oid)
    paid = o["total_paise"] if o["payment_status"] in ("paid", "partially_refunded", "refunded") else 0
    refunded = int(o.get("refunded_paise") or 0)
    booked = sum(e["amount_paise"] for e in w.events(oid, "completed"))
    assert refunded == booked, "order refund total must equal the completed refund events"
    open_cases = [c for c in w.cases(oid) if c["status"] in ("awaiting_review", "initiated", "failed")]
    owed = sum(c["amount_paise"] for c in open_cases)
    owed_not_supplied = sum(c["amount_paise"] for c in open_cases if c["kind"] in ("returned_to_origin", "vendor_rejection"))
    fee = int(o.get("cod_fee_paise") or 0) if paid else 0
    rows = w.ledger(oid)
    goods = sum(r["amount_paise"] for r in rows if r["type"] in ("SALE_COLLECTED", "SALE_REVERSAL", "REFUND"))
    platform_commission = -sum(r["amount_paise"] for r in rows if r["type"] == "COMMISSION")
    if paid:
        assert paid - fee - refunded - owed_not_supplied == goods, {"paid": paid, "cod_fee": fee, "refunded": refunded,
                                                                     "owed_not_supplied": owed_not_supplied, "ledger_goods": goods}
    for c in w.comms(oid):
        expected = c["amount_paise"] * refunded / (o["total_paise"] or 1)
        assert abs(c.get("reversed_paise", 0) - expected) <= max(1, len(c.get("reversal_records", []))), (c, expected)
        assert c.get("released_paise", 0) <= c["amount_paise"] - c.get("reversed_paise", 0) + (c.get("released_paise", 0) if
                                                                                                c.get("released_at") and
                                                                                                c.get("reversed_paise") else 0)
    assert w.wallet_ok(), "wallet aggregates must equal the wallet ledger"
    for pid in pids:
        live = 0
        for x in w.run(lambda: db.orders.find({"items.product_id": pid}, {"_id": 0}).to_list(500)):
            for li in x["items"]:
                if li["product_id"] == pid and x.get("stock_reserved") and not li.get("stock_released"):
                    live += li["quantity"]
        assert w.stock(pid) == START - live, (pid, w.stock(pid), live)
    assert w.audits("order_created", oid), "every order has its creation audit"
    over_promised = max(owed - max(paid - fee - refunded, 0), 0)
    return {"paid": paid, "refunded": refunded, "owed": owed, "goods": goods, "platform_commission": platform_commission,
            "platform_fee": fee, "over_promised": over_promised, "order": o}


# 1 ---------------------------------------------------------------------------------------------------------------------------
def test_01_normal_prepaid_single_vendor(w):
    pid = w.product("va", 1000, stock=START)
    o = w.paid_order([(pid, 2)])
    w.deliver("va", o["id"])
    w.age(o["id"])
    w.run(release_due_points)
    r = reconcile(w, o["id"], [pid])
    assert r["goods"] == r["paid"] == 200000 and r["platform_commission"] == 0
    assert all(c["released_at"] for c in w.comms(o["id"]))


# 2 ---------------------------------------------------------------------------------------------------------------------------
def test_02_normal_cod_single_vendor(w):
    pid = w.product("va", 800, stock=START)
    o = w.order([(pid, 1)], method="cod")
    w.deliver("va", o["id"])
    body = {"amount_collected": o["total"], "evidence_type": "courier_confirmation", "evidence_reference": "AWB-X2"}
    assert w.c.post(f"/api/orders/{o['id']}/cod-collected", json=body, headers=hdr(S["adm"]["id"])).status_code == 200
    w.age(o["id"])
    w.run(release_due_points)
    r = reconcile(w, o["id"], [pid])
    assert r["goods"] == 80000 and r["platform_fee"] == r["paid"] - 80000                 # the COD fee is platform revenue
    assert all(c["released_at"] for c in w.comms(o["id"]))


# 3 ---------------------------------------------------------------------------------------------------------------------------
def test_03_multi_vendor_prepaid(w):
    pa, pb = w.product("va", 1000, stock=START), w.product("vb", 500, stock=START)
    o = w.paid_order([(pa, 1), (pb, 2)])
    w.deliver("va", o["id"])
    w.deliver("vb", o["id"])
    r = reconcile(w, o["id"], [pa, pb])
    assert w.net(o["id"], "va") == 100000 and w.net(o["id"], "vb") == 100000 and r["goods"] == 200000


# 4 ---------------------------------------------------------------------------------------------------------------------------
def test_04_vendor_a_delivered_vendor_b_returned_to_origin(w):
    pa, pb = w.product("va", 1000, stock=START), w.product("vb", 700, stock=START)
    o = w.paid_order([(pa, 1), (pb, 1)])
    w.deliver("va", o["id"])
    assert w.rto("vb", o["id"]).status_code == 200
    r = reconcile(w, o["id"], [pa, pb])
    assert r["owed"] == 70000 and w.net(o["id"], "vb") == 0 and w.net(o["id"], "va") == 100000
    w.age(o["id"])
    fresh = w.get(o["id"])
    assert w.run(lambda: payout_block(fresh, vendor_id=S["va"]["id"])) is None          # A is payable
    w.run(release_due_points)
    assert all(c["released_at"] is None for c in w.comms(o["id"]))                     # commission waits for B's refund
    case = next(c for c in w.cases(o["id"]) if c["kind"] == "returned_to_origin")
    assert w.act("adm", case["id"], "initiate").status_code == 200
    assert w.confirm("fin2", case["id"], "UTR-X4-" + o["id"][:6]).status_code == 200
    w.run(release_due_points)
    r = reconcile(w, o["id"], [pa, pb])
    assert r["refunded"] == 70000 and r["owed"] == 0 and all(c["released_at"] for c in w.comms(o["id"]))
    # the vendor returns B's goods to stock after inspecting them
    assert w.c.post(f"/api/vendor/orders/{o['id']}/return-inspection", headers=hdr(S["uvb"]["id"]),
                    json={"received": True, "outcome": "resellable", "note": "Sealed, resellable"}).status_code == 200
    reconcile(w, o["id"], [pa, pb])


# 5 ---------------------------------------------------------------------------------------------------------------------------
def test_05_refund_requested_while_the_order_is_eligible_for_settlement(w):
    pa = w.product("va", 1000, stock=START)
    o = w.paid_order([(pa, 2)])
    w.deliver("va", o["id"])
    w.age(o["id"])
    aged = w_order(w, o["id"])
    assert w.run(lambda: payout_block(aged, vendor_id=S["va"]["id"])) is None
    case, _ = w.run(lambda: returns_routes.open_refund_case(aged, "return", 100000, "one returned", "x5:" + o["id"],
                                                            vendor_id=S["va"]["id"]))
    held = w.get(o["id"])
    assert w.run(lambda: payout_block(held, vendor_id=S["va"]["id"])) == "open_return_or_refund"
    reconcile(w, o["id"], [pa])
    assert w.act("adm", case["id"], "initiate").status_code == 200
    assert w.confirm("fin2", case["id"], "UTR-X5-" + o["id"][:6]).status_code == 200
    r = reconcile(w, o["id"], [pa])
    assert r["refunded"] == 100000 and w.net(o["id"], "va") == 100000


# 6 ---------------------------------------------------------------------------------------------------------------------------
def test_06_refund_rejected_at_booking(w):
    pa = w.product("va", 1000, stock=START)
    o = w.paid_order([(pa, 1)])
    x, _ = w.run(lambda: returns_routes.open_refund_case(_ORD_SET(o), "goodwill", 80000, "x", "x6a:" + o["id"]))
    y, _ = w.run(lambda: returns_routes.open_refund_case(_ORD[o["id"]], "goodwill", 50000, "y", "x6b:" + o["id"]))
    for c in (x, y):
        assert w.act("adm", c["id"], "initiate").status_code == 200
    assert w.confirm("fin2", y["id"], "UTR-X6Y-" + o["id"][:6]).status_code == 200
    assert w.confirm("fin2", x["id"], "UTR-X6X-" + o["id"][:6]).status_code == 409        # only 500 left
    r = reconcile(w, o["id"], [pa])
    assert r["refunded"] == 50000 and w.case(x["id"])["status"] == "initiated"
    assert r["over_promised"] == 30000          # case X still promises 800 with 500 refundable: reported (B-021), not booked


# 7 ---------------------------------------------------------------------------------------------------------------------------
def test_07_crash_after_payment_success(w, monkeypatch):
    pa = w.product("va", 1000, stock=START)
    o = w.order([(pa, 1)])
    sid = w.tx(o)

    async def boom(*a, **k):
        raise RuntimeError("process died")
    monkeypatch.setattr(commission, "distribute_sale_commissions", boom)
    with pytest.raises(RuntimeError):
        w.run(lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    w.run(order_completion.repair_incomplete_completions)
    r = reconcile(w, o["id"], [pa])
    assert r["goods"] == r["paid"] and len(w.comms(o["id"])) == 1 and "completion_due" not in r["order"]


# 8 ---------------------------------------------------------------------------------------------------------------------------
def test_08_duplicate_payment_event(w):
    pa = w.product("va", 1000, stock=START)
    o = w.order([(pa, 1)])
    sid = w.tx(o)
    ts = [threading.Thread(target=lambda: w.run(lambda: shop_routes._process_paid_order(sid))) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    r = reconcile(w, o["id"], [pa])
    assert len(w.ledger(o["id"], "SALE_COLLECTED")) == 1 and len(w.comms(o["id"])) == 1 and r["goods"] == r["paid"]


# 9 ---------------------------------------------------------------------------------------------------------------------------
def test_09_duplicate_rto_event(w):
    pa, pb = w.product("va", 1000, stock=START), w.product("vb", 1000, stock=START)
    o = w.paid_order([(pa, 1), (pb, 1)])
    assert w.rto("vb", o["id"]).status_code == 200
    out = [w.step("vb", o["id"], "returned_to_origin", note="Again returned").status_code for _ in range(3)]
    w.run(returns_routes.ensure_cases_for_flagged_orders)
    assert out == [400, 400, 400] and len(w.cases(o["id"])) == 1
    reconcile(w, o["id"], [pa, pb])


# 10 --------------------------------------------------------------------------------------------------------------------------
def test_10_ledger_repair_interrupted_halfway(w):
    pa = w.product("va", 300, stock=START)
    ids = [w.paid_order([(pa, 1)])["id"] for _ in range(6)]
    w.run(lambda: db.vendor_ledger.delete_many({"order_id": {"$in": ids}}))              # entries lost (simulated)
    first = w.run(lambda: ledger.reconcile_ledger(limit=2, max_seconds=0))
    assert not first["sweep"]["complete"]
    w.run(ledger.reconcile_ledger)
    w.run(ledger.reconcile_ledger)
    for oid in ids:
        assert len(w.ledger(oid, "SALE_COLLECTED")) == 1
        reconcile(w, oid, [pa])


# 11 --------------------------------------------------------------------------------------------------------------------------
def test_11_expired_prepaid_reservation_with_a_delayed_payment(w):
    pa = w.product("vb", 400, stock=START)
    o = w.order([(pa, 3)], seller=False)
    sid = w.tx(o)
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    w.run(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"created_at": old}}))
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    assert w.get(o["id"])["status"] == "cancelled" and w.stock(pa) == START
    w.run(lambda: shop_routes._process_paid_order(sid))                                    # the payment arrives late
    r = reconcile(w, o["id"], [pa])
    assert r["order"]["status"] == "processing" and w.stock(pa) == START - 3 and r["goods"] == r["paid"]


# 12 --------------------------------------------------------------------------------------------------------------------------
def test_12_accepted_cod_order_during_expiry_processing(w):
    pa = w.product("va", 600, stock=START)
    o = w.order([(pa, 2)], method="cod")
    assert w.step("va", o["id"], "accepted").status_code == 200
    from datetime import datetime, timedelta, timezone
    w.run(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}}))
    w.run(lambda: stock.expire_pending_online_orders(limit=10))
    r = reconcile(w, o["id"], [pa])
    assert r["order"]["status"] != "cancelled" and w.stock(pa) == START - 2 and r["paid"] == 0 and r["goods"] == 0


# 13 --------------------------------------------------------------------------------------------------------------------------
def test_13_missing_required_financial_index(w):
    pa = w.product("va", 1000, stock=START)
    o = w.order([(pa, 1)])
    sid = w.tx(o)
    w.run(lambda: db.wallet_transactions.drop_index("wallet_transactions_op_key_unique"))
    money_guard.reset_cache()
    try:
        with pytest.raises(HTTPException):
            w.run(lambda: shop_routes._process_paid_order(sid))
        mid = w.get(o["id"])
        assert mid["payment_status"] == "paid" and mid.get("completion_due") and w.comms(o["id"]) == []
        r = w.c.post("/api/orders", json={"items": [{"product_id": pa, "quantity": 1}], "address": __import__("p01_harness").ADDR,
                                          "payment_method": "online"}, headers=hdr(S["cust"]["id"]))
        assert r.status_code == 200                                                         # ordering does not need the wallet index
    finally:
        w.run(db_indexes.apply)
    w.run(order_completion.repair_incomplete_completions)
    reconcile(w, o["id"], [pa])


# 14 --------------------------------------------------------------------------------------------------------------------------
def test_14_admin_upload_and_vendor_isolation(w, monkeypatch):
    import storage
    saved = {}
    monkeypatch.setattr(storage, "_put", lambda path, data, ct: saved.setdefault(path, {"path": path, "size": len(data)}))
    r = w.c.post("/api/admin/uploads/image?kind=merchandising", headers=hdr(S["adm"]["id"]),
                 files={"file": ("b.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png")})
    assert r.status_code == 200
    assert w.c.post("/api/admin/uploads/image?kind=merchandising", headers=hdr(S["uva"]["id"]),
                    files={"file": ("b.png", b"\x89PNG\r\n\x1a\n", "image/png")}).status_code == 403
    assert w.c.post("/api/admin/uploads/sign", headers=hdr(S["uvb"]["id"]), json={"kind": "product"}).status_code == 403
    # vendor A still sees only its own orders and ledger
    mine = w.c.get("/api/vendor/finance/ledger", headers=hdr(S["uva"]["id"]))
    assert mine.status_code == 200 and all(x.get("vendor_id") in (S["va"]["id"], None) for x in mine.json().get("items", []))


# helpers that avoid nested portal calls -----------------------------------------------------------------------------------------
_ORD = {}


def w_order(w, oid):
    _ORD[oid] = w.get(oid)
    return _ORD[oid]


def _ORD_SET(o):
    _ORD[o["id"]] = o
    return o
