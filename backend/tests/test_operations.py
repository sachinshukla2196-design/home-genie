"""Operations: order detail, dispatch deadlines, vendor notifications for new orders / low stock.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_operations_test", "JWT_SECRET": "operations-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
for k in ("WEBHOOK_CRON_SECRET", "ADMIN_EMAIL"):
    os.environ.pop(k, None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
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

            async def user(mobile, role, did, status="green"):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": name, "status": "approved",
                     "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v
            S["cust"], S["adm"] = await user("9100001001", "distributor", "HGC", "red"), await user("9100001002", "super_admin", "HGADM")
            S["ua"], S["ub"] = await user("9100001003", "vendor", "VDA"), await user("9100001004", "vendor", "VDB")
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A"), await vendor(S["ub"], "Vendor B")
            await db.business_settings.update_one({"id": "business_settings"}, {"$set": {"gst_percent": 5.0, "cod_fee": 0.0}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, vendor="va", price=100, stock=50, **extra):
    async def mk():
        v = S[vendor]
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": price + 50, "selling_price": price, "gst_percent": 5, "stock": stock,
             "category": "Sarees", "options": [], "vendor_id": v["id"], "vendor_name": v["business_name"], "is_active": True,
             "approval_status": "approved", "created_at": now_iso(), **extra}
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _order(c, lines, method="cod"):
    r = c.post("/api/orders", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": p["id"], "quantity": q} for p, q in lines],
                                                                     "address": ADDR, "payment_method": method})
    assert r.status_code == 200, r.text
    return r.json()


def _notes(c, vkey, title=None):
    q = {"user_id": S[vkey]["id"], **({"title": title} if title else {})}
    return c.portal.call(lambda: db.notifications.find(q, {"_id": 0}).to_list(100))


def _pay(c, o):
    sid = "cs_" + o["id"][:12]
    if not c.portal.call(lambda: db.payment_transactions.find_one({"session_id": sid})):
        c.portal.call(lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                                 "amount": o["total"], "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))


def _fulfil(c, vkey, oid, *statuses):
    for st in statuses:
        extra = {"carrier": "BlueDart", "tracking_number": "BD123", "tracking_url": "https://track.example/BD123"} if st == "dispatched" else {}
        r = c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=_hdr(S[vkey]["id"]), json={"status": st, "note": "Signed by recipient", **extra})
        assert r.status_code == 200, (st, r.text)


# ====================================================================== notifications
def test_vendors_are_told_about_new_orders_once_cod_at_placement_online_at_payment(c):
    pa, pb = _product(c, "N-A"), _product(c, "N-B", "vb")
    cod = _order(c, [(pa, 1), (pb, 1)])
    for vk in ("ua", "ub"):
        n = [x for x in _notes(c, vk, "New order") if x["meta"].get("order_id") == cod["id"]]
        assert len(n) == 1 and cod["order_number"] in n[0]["message"]
    online = _order(c, [(pa, 1)], method="online")
    assert [x for x in _notes(c, "ua", "New order") if x["meta"].get("order_id") == online["id"]] == []        # not until it is paid
    _pay(c, online)
    _pay(c, online)
    assert len([x for x in _notes(c, "ua", "New order") if x["meta"].get("order_id") == online["id"]]) == 1   # duplicate callback: still one
    assert [x for x in _notes(c, "ub", "New order") if x["meta"].get("order_id") == online["id"]] == []        # vendor B is not on that order


def test_low_stock_alert_fires_once_when_a_sale_crosses_the_threshold(c):
    p = _product(c, "LS-1", stock=7, low_stock_threshold=5)
    _order(c, [(p, 1)])
    assert [n for n in _notes(c, "ua", "Low stock") if n["meta"].get("product_id") == p["id"]] == []          # 6 left: still healthy
    _order(c, [(p, 2)])
    alerts = [n for n in _notes(c, "ua", "Low stock") if n["meta"].get("product_id") == p["id"]]
    assert len(alerts) == 1 and "down to 4" in alerts[0]["message"]
    _order(c, [(p, 1)])
    assert len([n for n in _notes(c, "ua", "Low stock") if n["meta"].get("product_id") == p["id"]]) == 1     # already low: no spam
    other = [n for n in _notes(c, "ub", "Low stock") if n["meta"].get("product_id") == p["id"]]
    assert other == []                                                                                          # only the owner is told


# ====================================================================== deadlines
def _age(c, oid, days):
    ts = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": {"created_at": ts}}))


def test_dispatch_deadline_uses_each_products_handling_time_and_flags_overdue_orders(c):
    fast, slow = _product(c, "DL-F", package={"handling_days": 1}), _product(c, "DL-S", package={"handling_days": 6})
    o1, o2 = _order(c, [(fast, 1)]), _order(c, [(slow, 1)])
    default = _order(c, [(_product(c, "DL-D"), 1)])                                                           # no handling time: 3-day default
    for o in (o1, o2, default):
        _age(c, o["id"], 2)
    h = _hdr(S["ua"]["id"])
    row = lambda oid: next(x for x in c.get("/api/vendor/orders?page=1&page_size=100", headers=h).json()["items"] if x["id"] == oid)
    assert row(o1["id"])["dispatch_overdue"] is True and row(o2["id"])["dispatch_overdue"] is False and row(default["id"])["dispatch_overdue"] is False
    assert row(o1["id"])["dispatch_due_at"] < row(o2["id"])["dispatch_due_at"]
    r = c.get("/api/cron/expire-pending-orders", headers=CRON).json()
    assert r["deadline_alerts"] >= 1
    assert len([n for n in _notes(c, "ua", "Dispatch deadline passed") if n["meta"].get("order_id") == o1["id"]]) == 1
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert len([n for n in _notes(c, "ua", "Dispatch deadline passed") if n["meta"].get("order_id") == o1["id"]]) == 1   # alerted once
    assert [n for n in _notes(c, "ua", "Dispatch deadline passed") if n["meta"].get("order_id") == o2["id"]] == []
    _fulfil(c, "ua", o1["id"], "accepted", "packed", "dispatched")
    assert row(o1["id"])["dispatch_overdue"] is False                                                           # dispatched: no longer overdue


def test_prepaid_deadlines_run_from_the_payment_time_not_the_order_time(c):
    p = _product(c, "DL-P", package={"handling_days": 1})
    o = _order(c, [(p, 1)], method="online")
    _age(c, o["id"], 5)                                                                                          # placed long ago, but unpaid
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"created_at": datetime.now(timezone.utc).isoformat()}}))
    _pay(c, o)
    v = next(x for x in c.get("/api/vendor/orders?page=1&page_size=100", headers=_hdr(S["ua"]["id"])).json()["items"] if x["id"] == o["id"])
    assert v["dispatch_overdue"] is False and v["dispatch_due_at"] > datetime.now(timezone.utc).isoformat()


# ====================================================================== order detail
def test_order_detail_shows_timeline_shipment_returns_and_only_this_vendors_money(c):
    pa, pb = _product(c, "OD-A", price=100), _product(c, "OD-B", "vb", price=250)
    o = _order(c, [(pa, 2), (pb, 1)], method="online")
    _pay(c, o)
    _fulfil(c, "ua", o["id"], "accepted", "packed", "dispatched", "delivered")
    ha = _hdr(S["ua"]["id"])
    base = c.get(f"/api/vendor/orders/{o['id']}", headers=ha).json()
    assert "timeline" not in base and base["fulfilment"]["status"] == "delivered"                               # the plain view is unchanged
    d = c.get(f"/api/vendor/orders/{o['id']}?detail=true", headers=ha).json()
    types = [t["type"] for t in d["timeline"]]
    assert types[0] == "placed" and "payment" in types and types.count("fulfilment") == 5                       # new, accepted, packed, dispatched, delivered
    assert [t["at"] for t in d["timeline"]] == sorted(t["at"] for t in d["timeline"])
    assert d["shipment"]["carrier"] == "BlueDart" and d["shipment"]["tracking_number"] == "BD123" and d["shipment"]["dispatched_at"]
    assert d["financial"]["items_total_paise"] == 20000 and d["items_total_paise"] == 20000                       # vendor A's lines only (not B's 250)
    assert [e["amount_paise"] for e in d["ledger"]] == [20000] and all(e["vendor_id"] == S["va"]["id"] for e in d["ledger"])
    assert "ship_to" in d and all(li["vendor_id"] == S["va"]["id"] for li in d["items"])
    assert set(t["by"] for t in d["timeline"] if t["type"] == "fulfilment") <= {"you", "system", "platform"}      # no raw user ids
    rid = c.post(f"/api/orders/{o['id']}/returns", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": pa["id"], "quantity": 1}], "reason": "Colour is different"}).json()["cases"][0]["id"]
    d = c.get(f"/api/vendor/orders/{o['id']}?detail=true", headers=ha).json()
    assert [r["id"] for r in d["returns"]] == [rid] and any(t["type"] == "return" for t in d["timeline"])
    assert c.get(f"/api/vendor/orders/{o['id']}?detail=true", headers=_hdr(S["ub"]["id"])).json()["items_total_paise"] == 25000   # B sees its own part only
    assert c.get(f"/api/vendor/orders/{o['id']}?detail=true", headers=_hdr(S["cust"]["id"])).status_code == 403


def test_exceptions_are_listed_and_orders_awaiting_refund_stay_hidden(c):
    p = _product(c, "OD-X")
    o = _order(c, [(p, 1)])
    _fulfil(c, "ua", o["id"], "accepted", "packed", "dispatched")
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=_hdr(S["ua"]["id"]), json={"status": "delivery_failed", "note": "Customer not reachable"}).status_code == 200
    d = c.get(f"/api/vendor/orders/{o['id']}?detail=true", headers=_hdr(S["ua"]["id"])).json()
    assert [e["status"] for e in d["exceptions"]] == ["delivery_failed"] and d["exceptions"][0]["note"] == "Customer not reachable"
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"needs_refund": True}}))
    assert c.get(f"/api/vendor/orders/{o['id']}?detail=true", headers=_hdr(S["ua"]["id"])).status_code == 404
