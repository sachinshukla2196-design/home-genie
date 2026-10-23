"""Phase A2: stock reservation lifecycle (15-minute payment window, idempotent release, late payments).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_stock_test", "JWT_SECRET": "stock-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
CRON = {"Authorization": "Bearer cron-test-secret"}
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()

            async def user(mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            S["cust"], S["admin"] = await user("9100000201", "distributor", "HGC"), await user("9100000202", "super_admin", "HGADM")
            S["genie"] = await user("9100000204", "distributor", "HGSEL")
            S["vu"] = await user("9100000203", "vendor", "VDX")
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "VDX", "business_name": "Vendor X",
                      "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, stock):
    async def mk():
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": 1000, "selling_price": 800, "gst_percent": 5,
             "stock": stock, "category": "Sarees", "options": [], "vendor_id": S["v"]["id"], "vendor_name": "Vendor X",
             "is_active": True, "approval_status": "approved", "created_at": now_iso()}
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _stock(c, pid):
    return c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"]


def _order(c, pid, qty=1, method="online", seller=None):
    body = {"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": method}
    if seller:
        body["seller_ref"] = seller          # attributes the sale to a HomeGenie, so commissions WOULD be created if paid normally
    r = c.post("/api/orders", json=body, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _age(c, oid, minutes):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": {"created_at": ts}}))


def _get(c, oid):
    return c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _sweep(c):
    r = c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert r.status_code == 200, r.text
    return r.json()["expired"]


def _tx(c, o):
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    return sid


# ---------------------------------------------------------------- reservation + expiry
def test_cron_endpoint_requires_secret(c):
    assert c.get("/api/cron/expire-pending-orders").status_code == 401
    assert c.get("/api/cron/expire-pending-orders", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_online_order_inside_window_keeps_its_stock(c):
    p = _product(c, "W-1", 5)
    o = _order(c, p["id"], 2)
    assert _stock(c, p["id"]) == 3
    _age(c, o["id"], 14)
    _sweep(c)
    assert _get(c, o["id"])["status"] == "payment_pending" and _stock(c, p["id"]) == 3


def test_overdue_online_order_is_cancelled_and_stock_restored_exactly_once(c):
    p = _product(c, "W-2", 5)
    o = _order(c, p["id"], 2)
    sid = _tx(c, o)
    _age(c, o["id"], 16)
    # two sweeps racing each other
    with ThreadPoolExecutor(max_workers=2) as ex:
        n = sum(f.result() for f in [ex.submit(_sweep, c), ex.submit(_sweep, c)])
    got = _get(c, o["id"])
    assert n == 1 and got["status"] == "cancelled" and got["cancel_reason"] == "payment_timeout"
    assert _stock(c, p["id"]) == 5                                   # restored once, not twice
    assert _sweep(c) == 0 and _stock(c, p["id"]) == 5                # repeat sweep: nothing changes
    assert all(f["status"] == "cancelled" for f in got["fulfilments"])
    moves = c.portal.call(lambda: db.stock_movements.find({"order_id": o["id"]}).to_list(10))
    assert sorted(m["delta"] for m in moves) == [-2, 2]
    assert c.portal.call(lambda: db.payment_transactions.find_one({"session_id": sid}))["status"] == "expired"


def test_cod_orders_keep_stock_however_old(c):
    p = _product(c, "W-3", 5)
    o = _order(c, p["id"], 1, method="cod")
    _age(c, o["id"], 60 * 24)
    _sweep(c)
    assert _get(c, o["id"])["status"] == "confirmed" and _stock(c, p["id"]) == 4


def test_upi_claim_awaiting_admin_is_not_expired(c):
    p = _product(c, "W-4", 5)
    o = _order(c, p["id"], 1)
    r = c.post("/api/payments/upi-claim", json={"order_id": o["id"], "reference": "UTR123456"}, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200
    _age(c, o["id"], 120)
    _sweep(c)
    assert _get(c, o["id"])["status"] == "payment_pending" and _stock(c, p["id"]) == 4


def test_payment_that_lands_first_wins_over_the_sweep(c):
    p = _product(c, "W-5", 5)
    o = _order(c, p["id"], 1)
    sid = _tx(c, o)
    c.portal.call(lambda: shop_routes._process_paid_order(sid))
    _age(c, o["id"], 30)
    _sweep(c)
    got = _get(c, o["id"])
    assert got["payment_status"] == "paid" and got["status"] == "processing" and _stock(c, p["id"]) == 4


def test_checkout_sweeps_overdue_orders_so_stock_is_free_to_buy(c):
    p = _product(c, "W-6", 1)
    first = _order(c, p["id"], 1)
    assert c.post("/api/orders", json={"items": [{"product_id": p["id"], "quantity": 1}], "address": ADDR,
                                       "payment_method": "cod"}, headers=_hdr(S["cust"]["id"])).status_code == 409
    _age(c, first["id"], 20)
    second = _order(c, p["id"], 1, method="cod")          # sweep inside create_order frees the unit
    assert _get(c, first["id"])["status"] == "cancelled" and second["id"] and _stock(c, p["id"]) == 0


def test_cannot_start_payment_on_an_expired_order(c):
    p = _product(c, "W-7", 3)
    o = _order(c, p["id"], 1)
    _age(c, o["id"], 20)
    r = c.post("/api/payments/checkout", json={"order_id": o["id"], "origin_url": "https://home-genie-9zfc.vercel.app"},
               headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 400 and "not completed in time" in r.json()["detail"]
    assert _stock(c, p["id"]) == 3


# ---------------------------------------------------------------- idempotent release
def test_release_stock_is_idempotent_per_line_and_scoped_to_the_order(c):
    p = _product(c, "R-1", 5)
    o = _order(c, p["id"], 2, method="cod")
    assert _stock(c, p["id"]) == 3
    a = c.portal.call(lambda: stock.release_stock(o["id"], "test", "tester"))
    b = c.portal.call(lambda: stock.release_stock(o["id"], "test", "tester"))
    assert (a, b) == (1, 0) and _stock(c, p["id"]) == 5
    assert c.portal.call(lambda: stock.release_stock(o["id"], "test", "tester", vendor_id="someone-else")) == 0


# ---------------------------------------------------------------- late payment (callbacks arriving after expiry)
def test_late_payment_revives_order_when_stock_still_available_and_is_idempotent(c):
    p = _product(c, "L-1", 5)
    o = _order(c, p["id"], 2)
    sid = _tx(c, o)
    _age(c, o["id"], 20)
    assert _sweep(c) == 1 and _stock(c, p["id"]) == 5

    async def duplicate_callbacks():            # webhook + browser verify arriving together
        await asyncio.gather(shop_routes._process_paid_order(sid), shop_routes._process_paid_order(sid))
    c.portal.call(duplicate_callbacks)
    got = _get(c, o["id"])
    assert got["payment_status"] == "paid" and got["status"] == "processing" and got.get("invoice_number")
    assert "cancel_reason" not in got and got["revived_after_timeout"] is True
    assert all(f["status"] == "new" for f in got["fulfilments"])
    assert _stock(c, p["id"]) == 3                                  # taken back exactly once
    c.portal.call(lambda: shop_routes._process_paid_order(sid))     # replay
    assert _stock(c, p["id"]) == 3


def test_late_payment_without_stock_is_flagged_for_refund_not_oversold(c):
    p = _product(c, "L-2", 2)
    o = _order(c, p["id"], 2, seller="HGSEL")
    sid = _tx(c, o)
    _age(c, o["id"], 20)
    _sweep(c)
    _order(c, p["id"], 2, method="cod")                             # someone else buys the freed stock
    assert _stock(c, p["id"]) == 0
    c.portal.call(lambda: shop_routes._process_paid_order(sid))
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and got["payment_status"] == "paid" and got["needs_refund"] is True
    assert not got.get("invoice_number") and _stock(c, p["id"]) == 0
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0
    assert c.portal.call(lambda: db.notifications.count_documents({"user_id": S["admin"]["id"], "title": "Refund needed"})) >= 1


def test_admin_confirming_a_late_upi_payment_goes_through_the_same_path(c):
    p = _product(c, "L-3", 4)
    o = _order(c, p["id"], 1)
    _age(c, o["id"], 20)
    _sweep(c)
    url = f"/api/admin/payments/upi-confirm/{o['id']}"
    assert c.put(url, json={"reference": "UTR-LATE-1"}, headers=_hdr(S["admin"]["id"])).status_code == 200
    got = _get(c, o["id"])
    assert got["status"] == "processing" and got["payment_status"] == "paid" and _stock(c, p["id"]) == 3
    assert c.put(url, json={"reference": "UTR-LATE-1"}, headers=_hdr(S["admin"]["id"])).json()["message"] == "Order already paid."
    assert _stock(c, p["id"]) == 3


# ---------------------------------------------------------------- vendor isolation still holds with the new flow
def test_expired_orders_never_appear_to_vendors_and_other_roles_cannot_trigger_sweeps(c):
    p = _product(c, "V-1", 3)
    o = _order(c, p["id"], 1)
    _age(c, o["id"], 20)
    _sweep(c)
    assert o["id"] not in [x["id"] for x in c.get("/api/vendor/orders", headers=_hdr(S["vu"]["id"])).json()]
    assert c.get("/api/cron/expire-pending-orders", headers=_hdr(S["admin"]["id"])).status_code == 401
