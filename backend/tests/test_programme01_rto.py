"""Programme 01 / B-001: a paid vendor group RETURNED TO ORIGIN (never delivered) has the same money effect as a vendor
rejection: refund obligation recorded atomically, the vendor's sale and platform commission for that group reversed, ONE refund
case for that group's lines, HomeGenie commission held and then clawed back by the refund. Other vendors' allocations stand.

Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_rto.py -n 0`.
"""
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_rto_test", "JWT_SECRET": "p01-rto-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger  # noqa: E402
import returns_routes  # noqa: E402
import shop_routes  # noqa: E402
from commission import release_due_points  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from eligibility import payout_block  # noqa: E402
from wallet_reconcile import expected_aggregates  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
OLD = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
ROLES = {"adm": "admin", "fin": "accounts_admin", "fin2": "accounts_admin", "sup": "super_admin"}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(key, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": "93" + new_id()[:8].replace("-", "3"), "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("cust", "distributor", "RTCUST")
            await user("seller", "distributor", "RTSELL")
            for k, r in ROLES.items():
                await user(k, r, "RT" + k.upper())
            for k in ("va", "vb"):
                await user("u" + k, "vendor", "RT" + k.upper())
                S[k] = {"id": new_id(), "user_id": S["u" + k]["id"], "vendor_code": "RT" + k.upper(), "business_name": "Vendor " + k,
                        "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(S[k]))
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _product(c, vendor="va", price=1000, stock=50):
    p = {"id": new_id(), "sku": "RT-" + new_id()[:6], "name": "Saree " + vendor, "images": [], "mrp": price + 200, "selling_price": price,
         "gst_percent": 5, "stock": stock, "category": "Sarees", "options": [], "vendor_id": S[vendor]["id"],
         "vendor_name": S[vendor]["business_name"], "is_active": True, "approval_status": "approved", "created_at": now_iso()}
    _run(c, lambda: db.products.insert_one(dict(p)))
    return p["id"]


def _paid_order(c, lines):
    r = c.post("/api/orders", json={"items": [{"product_id": p, "quantity": q} for p, q in lines], "address": ADDR, "payment_method": "online",
                                    "seller_ref": "RTSELL"}, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    o = r.json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    return _get(c, o["id"])


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _cases(c, oid):
    return _run(c, lambda: db.refund_cases.find({"order_id": oid}, {"_id": 0}).to_list(20))


def _comms(c, oid):
    return _run(c, lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))


def _ledger(c, oid, typ=None, vendor=None):
    q = {"order_id": oid}
    if typ:
        q["type"] = typ
    if vendor:
        q["vendor_id"] = S[vendor]["id"]
    return _run(c, lambda: db.vendor_ledger.find(q, {"_id": 0}).to_list(50))


def _net(c, oid, vendor):
    return sum(r["amount_paise"] for r in _ledger(c, oid, vendor=vendor))


def _stock(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}, {"_id": 0, "stock": 1}))["stock"]


def _wallet_ok(c):
    rows = _run(c, lambda: db.wallet_transactions.find({"user_id": S["seller"]["id"]}, {"_id": 0}).to_list(5000))
    w = _run(c, lambda: db.wallets.find_one({"user_id": S["seller"]["id"]}, {"_id": 0})) or {}
    exp = expected_aggregates(rows)
    return all(exp[f] == w.get(f + "_paise", 0) for f in exp)


def _step(c, vendor, oid, status, note="Courier could not reach the customer", **kw):
    body = {"status": status, "note": note, **kw}
    if status == "dispatched":
        body.update({"carrier": "Delhivery", "tracking_number": "TRK" + oid[:6]})
    return c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=_hdr(S["u" + vendor]["id"]), json=body)


def _to_failed(c, vendor, oid):
    for st in ("accepted", "packed", "dispatched", "delivery_failed"):
        assert _step(c, vendor, oid, st).status_code == 200, st


def _rto(c, vendor, oid):
    _to_failed(c, vendor, oid)
    return _step(c, vendor, oid, "returned_to_origin", note="Shipment returned to the warehouse")


def _deliver(c, vendor, oid):
    for st in ("accepted", "packed", "dispatched"):
        assert _step(c, vendor, oid, st).status_code == 200, st
    assert _step(c, vendor, oid, "delivered", note="Recipient: Cust, OTP 4411").status_code == 200


async def _age_delivery(oid, vendor_id):
    """Move one vendor's recorded delivery (and the commission creation) into the past, past every window."""
    o = await db.orders.find_one({"id": oid}, {"_id": 0})
    fl = []
    for f in o["fulfilments"]:
        if f["vendor_id"] == vendor_id and f["status"] == "delivered":
            f = {**f, "delivered_at": OLD, "events": [{**e, "at": OLD} if e.get("status") == "delivered" else e for e in f["events"]]}
        fl.append(f)
    await db.orders.update_one({"id": oid}, {"$set": {"fulfilments": fl}})
    await db.commissions.update_many({"order_id": oid}, {"$set": {"created_at": OLD}})


def _act(c, who, cid, action, **kw):
    return c.post(f"/api/admin/refund-cases/{cid}/action", headers=_hdr(S[who]["id"]), json={"action": action, **kw})


def _confirm(c, cid, ref, maker="adm", checker="fin2"):
    assert _act(c, maker, cid, "initiate").status_code == 200
    r = _act(c, checker, cid, "confirm", reference=ref, confirmation_type="manual_reconciliation", note="Verified against the bank statement")
    assert r.status_code == 200, r.text
    return r


# ================================================================ single vendor
def test_full_prepaid_rto_records_liability_reverses_sale_and_holds_commission(c):
    pid = _product(c, "va", 1000)
    o = _paid_order(c, [(pid, 2)])                                           # 2,000 incl. GST
    stock_after_order = _stock(c, pid)
    sale = _ledger(c, o["id"], "SALE_COLLECTED", "va")
    assert len(sale) == 1 and sale[0]["amount_paise"] == 200000
    assert _rto(c, "va", o["id"]).status_code == 200
    cases = _cases(c, o["id"])
    assert len(cases) == 1 and cases[0]["kind"] == "returned_to_origin" and cases[0]["vendor_id"] == S["va"]["id"]
    assert cases[0]["amount_paise"] == 200000 and cases[0]["status"] == "awaiting_review"
    assert cases[0]["source_key"] == f"rto:{o['id']}:{S['va']['id']}"
    got = _get(c, o["id"])
    assert not any(f.get("refund_due") for f in got["fulfilments"])           # the case exists, so the marker is cleared
    assert got["payment_status"] == "paid"                                    # no money moved: the case awaits the refund flow
    assert _net(c, o["id"], "va") <= 0                                        # sale and platform commission reversed
    assert len(_ledger(c, o["id"], "SALE_REVERSAL", "va")) == 1
    assert _stock(c, pid) == stock_after_order                                # restocked only after the receipt inspection
    # commission: never released while the goods are undelivered
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
    _run(c, release_due_points)
    assert all(x["released_at"] is None for x in _comms(c, o["id"]))
    fresh = _get(c, o["id"])
    assert _run(c, lambda: payout_block(fresh)) is not None
    assert _run(c, lambda: payout_block(fresh, vendor_id=S["va"]["id"])) is not None


def test_confirmed_rto_refund_reverses_the_commission_completely(c):
    o = _paid_order(c, [(_product(c, "va", 800), 1)])
    _rto(c, "va", o["id"])
    case = _cases(c, o["id"])[0]
    _confirm(c, case["id"], "UTR-RTO1-" + o["id"][:6])
    got = _get(c, o["id"])
    assert got["payment_status"] == "refunded" and got["refunded_paise"] == o["total_paise"]
    assert all(x["status"] == "REVERSED" and x["reversed_paise"] == x["amount_paise"] for x in _comms(c, o["id"]))
    assert _net(c, o["id"], "va") == 0 and _ledger(c, o["id"], "REFUND") == []   # sale already reversed: no double take-back
    assert _wallet_ok(c)


def test_resellable_return_inspection_restocks_once(c):
    pid = _product(c, "va", 500, stock=10)
    o = _paid_order(c, [(pid, 3)])
    assert _stock(c, pid) == 7
    _rto(c, "va", o["id"])
    assert _stock(c, pid) == 7
    body = {"received": True, "outcome": "resellable", "note": "Seal intact, resellable"}
    url = f"/api/vendor/orders/{o['id']}/return-inspection"
    assert c.post(url, headers=_hdr(S["uva"]["id"]), json=body).status_code == 200
    assert c.post(url, headers=_hdr(S["uva"]["id"]), json=body).status_code == 400
    assert _stock(c, pid) == 10


# ================================================================ multi-vendor
def test_vendor_a_delivered_vendor_b_rto_only_b_is_reversed_and_a_can_settle(c):
    pa, pb = _product(c, "va", 1000), _product(c, "vb", 500)
    o = _paid_order(c, [(pa, 1), (pb, 2)])                                    # A 1,000 + B 1,000 = 2,000
    _deliver(c, "va", o["id"])
    assert _rto(c, "vb", o["id"]).status_code == 200
    cases = _cases(c, o["id"])
    assert len(cases) == 1 and cases[0]["vendor_id"] == S["vb"]["id"] and cases[0]["amount_paise"] == 100000
    got = _get(c, o["id"])
    st = {f["vendor_id"]: f["status"] for f in got["fulfilments"]}
    assert st == {S["va"]["id"]: "delivered", S["vb"]["id"]: "returned_to_origin"}
    assert _ledger(c, o["id"], "SALE_REVERSAL", "va") == [] and len(_ledger(c, o["id"], "SALE_REVERSAL", "vb")) == 1
    assert _net(c, o["id"], "va") > 0                                         # A's sale stands
    _run(c, lambda: _age_delivery(o["id"], S["va"]["id"]))
    fresh = _get(c, o["id"])
    # A's settlement is not held by B's case; the whole-order HomeGenie commission is.
    assert _run(c, lambda: payout_block(fresh, vendor_id=S["va"]["id"])) is None
    assert _run(c, lambda: payout_block(fresh)) == "open_return_or_refund"
    elig, _ = _run(c, lambda: ledger._eligible_paise(S["va"]["id"]))
    assert elig >= _net(c, o["id"], "va") > 0
    _run(c, release_due_points)
    assert all(x["released_at"] is None for x in _comms(c, o["id"]))
    # B's refund is confirmed: half the commission (B's share) is clawed back, then the rest releases.
    _confirm(c, cases[0]["id"], "UTR-RTO2-" + o["id"][:6])
    got = _get(c, o["id"])
    assert got["payment_status"] == "partially_refunded" and got["refunded_paise"] == 100000
    cm = _comms(c, o["id"])[0]
    assert abs(cm["reversed_paise"] - cm["amount_paise"] / 2) <= 0.5 and cm["status"] == "PARTIALLY_REVERSED"
    _run(c, release_due_points)
    cm = _comms(c, o["id"])[0]
    assert cm["released_at"] is not None
    assert _ledger(c, o["id"], "REFUND", "va") == []                         # A never shares B's refund
    assert _wallet_ok(c)


def test_both_vendors_rto_refunds_sum_to_the_total(c):
    o = _paid_order(c, [(_product(c, "va", 700), 1), (_product(c, "vb", 300), 1)])
    _rto(c, "va", o["id"])
    _rto(c, "vb", o["id"])
    cases = _cases(c, o["id"])
    assert sorted(x["kind"] for x in cases) == ["returned_to_origin", "returned_to_origin"]
    assert sum(x["amount_paise"] for x in cases) == o["total_paise"]


# ================================================================ idempotency, concurrency, recovery
def test_duplicate_rto_is_refused_and_books_nothing_twice(c):
    o = _paid_order(c, [(_product(c, "va", 600), 1)])
    assert _rto(c, "va", o["id"]).status_code == 200
    assert _step(c, "va", o["id"], "returned_to_origin", note="Again, returned").status_code == 400
    _run(c, returns_routes.ensure_cases_for_flagged_orders)
    _run(c, ledger.reconcile_ledger)
    assert len(_cases(c, o["id"])) == 1 and len(_ledger(c, o["id"], "SALE_REVERSAL")) == 1


def test_concurrent_rto_calls_open_one_case_and_one_reversal(c):
    o = _paid_order(c, [(_product(c, "va", 600), 1)])
    _to_failed(c, "va", o["id"])
    codes = []
    ts = [threading.Thread(target=lambda: codes.append(_step(c, "va", o["id"], "returned_to_origin", note="Returned by courier").status_code))
          for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert codes.count(200) == 1
    _run(c, returns_routes.ensure_cases_for_flagged_orders)
    assert len(_cases(c, o["id"])) == 1 and len(_ledger(c, o["id"], "SALE_REVERSAL")) == 1


def test_crash_after_the_transition_is_repaired_by_the_sweep(c):
    """Only the atomic transition happened (status + refund_due), then the process died: nothing is payable until the repair
    sweep has reversed the sale and opened the case, exactly once."""
    pa, pb = _product(c, "va", 1000), _product(c, "vb", 1000)
    o = _paid_order(c, [(pa, 1), (pb, 1)])
    _deliver(c, "va", o["id"])
    _to_failed(c, "vb", o["id"])
    _run(c, lambda: db.orders.update_one({"id": o["id"], "fulfilments.vendor_id": S["vb"]["id"]},
                                         {"$set": {"fulfilments.$.status": "returned_to_origin", "fulfilments.$.refund_due": True}}))
    _run(c, lambda: _age_delivery(o["id"], S["va"]["id"]))
    fresh = _get(c, o["id"])
    assert _run(c, lambda: payout_block(fresh)) == "refund_due"                       # commission waits for the repair
    assert _run(c, lambda: payout_block(fresh, vendor_id=S["vb"]["id"])) == "refund_due"
    assert _run(c, lambda: payout_block(fresh, vendor_id=S["va"]["id"])) is None       # A is not B's problem
    _run(c, release_due_points)
    assert all(x["released_at"] is None for x in _comms(c, o["id"]))
    for _ in range(2):
        _run(c, returns_routes.ensure_cases_for_flagged_orders)
    cases = _cases(c, o["id"])
    assert len(cases) == 1 and cases[0]["kind"] == "returned_to_origin" and cases[0]["amount_paise"] == 100000
    assert len(_ledger(c, o["id"], "SALE_REVERSAL", "vb")) == 1
    assert not any(f.get("refund_due") for f in _get(c, o["id"])["fulfilments"])


def test_rto_after_redispatch_and_a_second_failure(c):
    o = _paid_order(c, [(_product(c, "va", 900), 1)])
    _to_failed(c, "va", o["id"])
    assert _step(c, "va", o["id"], "dispatched").status_code == 200
    assert _step(c, "va", o["id"], "delivery_failed").status_code == 200
    assert _step(c, "va", o["id"], "returned_to_origin", note="Returned after two attempts").status_code == 200
    assert len(_cases(c, o["id"])) == 1


def test_rto_needs_a_reason(c):
    o = _paid_order(c, [(_product(c, "va", 900), 1)])
    _to_failed(c, "va", o["id"])
    assert _step(c, "va", o["id"], "returned_to_origin", note="rto").status_code == 400
    assert _cases(c, o["id"]) == []


def test_rto_after_a_partial_refund_is_capped_by_what_is_still_refundable(c):
    pa, pb = _product(c, "va", 1000), _product(c, "vb", 1000)
    o = _paid_order(c, [(pa, 1), (pb, 1)])
    # an earlier goodwill refund of 1,500 was confirmed on this order (an order-wide case)
    case, _ = _run(c, lambda: returns_routes.open_refund_case(o, "goodwill", 150000, "Goodwill", "gw:" + o["id"]))
    _confirm(c, case["id"], "UTR-GW-" + o["id"][:6])
    _rto(c, "vb", o["id"])
    rto = [x for x in _cases(c, o["id"]) if x["kind"] == "returned_to_origin"]
    assert len(rto) == 1 and rto[0]["amount_paise"] == 50000                 # only 500 is still refundable
    _confirm(c, rto[0]["id"], "UTR-RTO3-" + o["id"][:6])
    got = _get(c, o["id"])
    assert got["refunded_paise"] == o["total_paise"] and got["payment_status"] == "refunded"
    assert _wallet_ok(c)


def test_unpaid_cod_rto_opens_no_refund_case(c):
    r = c.post("/api/orders", json={"items": [{"product_id": _product(c, "va"), "quantity": 1}], "address": ADDR, "payment_method": "cod"},
               headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    _to_failed(c, "va", oid)
    assert _step(c, "va", oid, "returned_to_origin", note="Customer refused the parcel").status_code == 200
    assert _cases(c, oid) == [] and _ledger(c, oid) == []


def test_historical_rto_orders_are_not_rewritten_by_the_sweeps(c):
    """An order returned to origin BEFORE Programme 01 (no refund_due marker, sale never reversed) is left exactly as it is by the
    automatic sweeps; it is reported for a finance decision instead (scripts/programme01_reconcile.py)."""
    o = _paid_order(c, [(_product(c, "va", 400), 1)])
    _run(c, lambda: db.orders.update_one({"id": o["id"], "fulfilments.vendor_id": S["va"]["id"]},
                                         {"$set": {"fulfilments.$.status": "returned_to_origin"}}))
    before = (_cases(c, o["id"]), _ledger(c, o["id"]))
    _run(c, returns_routes.ensure_cases_for_flagged_orders)
    _run(c, ledger.reconcile_ledger)
    assert (_cases(c, o["id"]), _ledger(c, o["id"])) == before
    rep = _run(c, returns_routes.historical_rto_report)                         # reported for a finance decision instead
    assert any(x["vendor_id"] == S["va"]["id"] and x["group_value_paise"] == 40000 and not x["sale_reversed"] for x in rep["orders"])
