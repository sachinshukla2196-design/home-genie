"""Owner decisions 2 and 3 — earnings become payable only after DELIVERY plus the return window, with nothing unresolved.

The same rule (eligibility.payout_block) governs the two separate systems: HomeGenie commission release and vendor settlement.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_payout_eligibility.py -n 0`).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_payout_eligibility_test", "JWT_SECRET": "payout-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import ledger as L  # noqa: E402
from commission import release_due_points  # noqa: E402
from eligibility import payout_block  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


def _ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(key, mobile, role, did, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status,
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("cust", "9100007001", "distributor", "HG700001", status="red")
            await user("genie", "9100007002", "distributor", "HG700002")
            await user("super", "9100007003", "super_admin", "E7SUPER")
            await user("fin", "9100007004", "accounts_admin", "E7FIN")
            await user("vu", "9100007005", "vendor", "E7VEND")
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "E7VEND", "business_name": "Vendor E7",
                      "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
            await db.finance_policy.update_one({"id": "settlement_policy"}, {"$set": {"active": True, "require_dual_approval": False,
                                                                                  "min_settlement": 1}}, upsert=True)
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _paid_order(c, seller=True):
    pid = new_id()
    _run(c, lambda: db.products.insert_one({"id": pid, "sku": f"E7-{pid[:6]}", "name": "Saree", "images": [], "mrp": 1200,
                                            "selling_price": 1000, "gst_percent": 5, "stock": 10, "category": "Sarees", "options": [],
                                            "vendor_id": S["v"]["id"], "vendor_name": "Vendor E7", "is_active": True,
                                            "approval_status": "approved", "created_at": now_iso()}))
    body = {"items": [{"product_id": pid, "quantity": 1}], "address": ADDR, "payment_method": "online",
            **({"seller_ref": "HG700002"} if seller else {})}
    o = c.post("/api/orders", json=body, headers=_hdr("cust")).json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    return o


def _comm(c, oid):
    return _run(c, lambda: db.commissions.find_one({"order_id": oid, "type": "COMMISSION_DIRECT"}, {"_id": 0}))


def _set(c, oid, **fields):
    """Batch 12 (audit C-5): delivery is the VENDOR FULFILMENT, so a delivery time given here is recorded on every fulfilment
    (status delivered + a delivered event), exactly as the vendor's dispatch flow records it - not only on the order."""
    async def go():
        o = await db.orders.find_one({"id": oid}, {"_id": 0})
        extra = {}
        if "delivered_at" in fields and o.get("fulfilments"):
            fl = []
            for f in o["fulfilments"]:
                ev = [e for e in f.get("events", []) if e.get("status") != "delivered"] + [{"status": "delivered", "at": fields["delivered_at"]}]
                fl.append({**f, "status": "delivered", "delivered_at": fields["delivered_at"], "events": ev})
            extra["fulfilments"] = fl
        await db.orders.update_one({"id": oid}, {"$set": {**fields, **extra}})
    _run(c, go)


def _release(c):
    return _run(c, release_due_points)


# ================================================================ Decision 2: commission release
def test_paid_but_undelivered_commission_never_releases_however_old(c):
    o = _paid_order(c)
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": _ago(90)}}))
    _release(c)
    assert _comm(c, o["id"])["status"] == "PENDING"


def test_release_waits_for_the_full_return_window_after_delivery(c):
    o = _paid_order(c)
    _set(c, o["id"], status="delivered", delivered_at=_ago(3))              # window is 7 days
    _release(c)
    assert _comm(c, o["id"])["status"] == "PENDING"
    _set(c, o["id"], delivered_at=_ago(8))
    _release(c)
    assert _comm(c, o["id"])["status"] == "RELEASED"


def test_a_longer_return_window_holds_commission_longer(c):
    o = _paid_order(c)
    _set(c, o["id"], status="delivered", delivered_at=_ago(10))
    _run(c, lambda: db.returns_policy.update_one({"id": "returns_policy"}, {"$set": {"window_days": 14}}, upsert=True))
    try:
        _release(c)
        assert _comm(c, o["id"])["status"] == "PENDING"
    finally:
        _run(c, lambda: db.returns_policy.update_one({"id": "returns_policy"}, {"$set": {"window_days": 7}}, upsert=True))


@pytest.mark.parametrize("problem", ["open_return", "cancelled", "refund_due", "cod_discrepancy"])
def test_unresolved_orders_hold_commission(c, problem):
    o = _paid_order(c)
    _set(c, o["id"], status="delivered", delivered_at=_ago(30))
    if problem == "open_return":
        _run(c, lambda: db.return_cases.insert_one({"id": new_id(), "order_id": o["id"], "status": "requested", "created_at": now_iso()}))
    elif problem == "cancelled":
        _set(c, o["id"], status="cancelled")
    elif problem == "refund_due":
        _set(c, o["id"], refund_due_cancel=True)
    else:
        _set(c, o["id"], payment_status="cod_discrepancy")
    _release(c)
    assert _comm(c, o["id"])["status"] != "RELEASED"


def test_manual_release_follows_the_same_rule(c):
    o = _paid_order(c)
    cid = _comm(c, o["id"])["id"]
    r = c.put(f"/api/admin/commissions/{cid}/status", json={"action": "release", "reason": "early please"}, headers=_hdr("fin"))
    assert r.status_code == 409 and "delivered" in r.json()["detail"]
    _set(c, o["id"], status="delivered", delivered_at=_ago(8))
    r = c.put(f"/api/admin/commissions/{cid}/status", json={"action": "release", "reason": "window passed"}, headers=_hdr("fin"))
    assert r.status_code == 200, r.text


def test_admin_marking_a_vendor_order_delivered_is_recorded_but_is_not_the_delivery(c):
    # Batch 12 (audit C-5a; replaces "admin marking delivered records the delivery time"): for vendor goods the delivery is the
    # vendor fulfilment. The admin's status change is recorded but starts no payout clock (owner decision D-04 is open).
    o = _paid_order(c, seller=False)
    for st in ("processing", "shipped", "delivered"):
        c.put(f"/api/admin/orders/{o['id']}/status", json={"status": st}, headers=_hdr("super"))
    got = _run(c, lambda: db.orders.find_one({"id": o["id"]}, {"_id": 0}))
    assert got["status"] == "delivered" and got["status_set_by_admin"]["status"] == "delivered" and not got.get("delivered_at")
    assert _run(c, lambda: payout_block(got)) == "not_delivered"


# ================================================================ Decision 3: vendor settlement eligibility
def _bal(c):
    return _run(c, lambda: L.balances(S["v"]["id"]))


def test_vendor_money_becomes_settleable_only_after_delivery_and_the_window(c):
    before = _bal(c)["available_for_settlement_paise"]
    o = _paid_order(c, seller=False)
    sale = _run(c, lambda: db.vendor_ledger.find_one({"order_id": o["id"], "type": L.SALE}))["amount_paise"]
    b = _bal(c)
    assert b["available_for_settlement_paise"] == before and b["awaiting_eligibility_paise"] >= sale
    _set(c, o["id"], status="delivered", delivered_at=_ago(2))
    assert _bal(c)["available_for_settlement_paise"] == before
    _set(c, o["id"], delivered_at=_ago(8))
    assert _bal(c)["available_for_settlement_paise"] == before + sale


@pytest.mark.parametrize("problem", ["open_return", "refund_case", "needs_refund", "duplicate_payment"])
def test_unresolved_orders_keep_vendor_money_on_hold(c, problem):
    o = _paid_order(c, seller=False)
    _set(c, o["id"], status="delivered", delivered_at=_ago(30))
    before = _bal(c)["available_for_settlement_paise"]
    if problem == "open_return":
        _run(c, lambda: db.return_cases.insert_one({"id": new_id(), "order_id": o["id"], "status": "requested", "created_at": now_iso()}))
    elif problem == "refund_case":
        _run(c, lambda: db.refund_cases.insert_one({"id": new_id(), "order_id": o["id"], "status": "awaiting_review", "amount_paise": 100}))
    elif problem == "needs_refund":
        _set(c, o["id"], needs_refund=True)
    else:
        _set(c, o["id"], duplicate_payments=[{"session_id": "x", "status": "refund_due"}])
    assert _bal(c)["available_for_settlement_paise"] < before
    assert _bal(c)["held_orders"] >= 1


def test_settlement_cannot_be_requested_beyond_eligible_money(c):
    avail = _bal(c)["available_for_settlement_paise"]
    _paid_order(c, seller=False)                                              # paid, not delivered: not eligible
    r = c.post("/api/admin/finance/settlements", headers=_hdr("fin"), json={"vendor_id": S["v"]["id"], "amount": avail / 100 + 1})
    assert r.status_code == 400


# ================================================================ Batch 5: the member's commission statement
def test_commission_statement_shows_net_amounts_and_why_each_is_held(c):
    o = _paid_order(c)
    st = c.get("/api/commissions/statement", headers=_hdr("genie")).json()
    row = next(x for x in st["items"] if x["order_number"] == o["order_number"])
    assert row["held_because"] == "not_delivered" and row["net_paise"] == row["amount_paise"] > 0
    _set(c, o["id"], status="delivered", delivered_at=_ago(8))
    _release(c)
    st2 = c.get("/api/commissions/statement", headers=_hdr("genie")).json()
    row2 = next(x for x in st2["items"] if x["order_number"] == o["order_number"])
    assert row2["released_at"] and row2["held_because"] is None
    assert st2["released_paise"] >= row2["net_paise"] and st2["earned_paise"] == st2["released_paise"] + st2["pending_paise"] + st2["reversed_paise"]
    assert c.get("/api/commissions/statement", headers=_hdr("cust")).json()["items"] == []       # only one's own rows
