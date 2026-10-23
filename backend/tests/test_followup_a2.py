"""Phase A2 follow-up: confirmed-cancellation restock, return inspection, refund-hold queue, money buckets, pagination/search.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_followup_test", "JWT_SECRET": "followup-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

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

            async def user(mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": name,
                     "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            S["cust"], S["admin"] = await user("9100000301", "distributor", "HGC"), await user("9100000302", "super_admin", "HGADM")
            S["genie"] = await user("9100000303", "distributor", "HGSEL")
            S["cust2"] = await user("9100000306", "distributor", "HGC2")
            S["ua"], S["ub"] = await user("9100000304", "vendor", "VDA"), await user("9100000305", "vendor", "VDB")
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A"), await vendor(S["ub"], "Vendor B")
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, stock, vendor="va", price=800, name=None, created=None):
    async def mk():
        v = S.get(vendor)
        p = {"id": new_id(), "sku": sku, "name": name or sku, "images": [], "mrp": price + 200, "selling_price": price,
             "gst_percent": 5, "stock": stock, "category": "Sarees", "options": [],
             "vendor_id": v["id"] if v else None, "vendor_name": v["business_name"] if v else None,
             "is_active": True, "approval_status": "approved", "created_at": created or now_iso()}
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _stock(c, pid):
    return c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"]


def _order(c, pid, qty=1, method="cod", seller=None):
    body = {"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": method}
    if seller:
        body["seller_ref"] = seller
    r = c.post("/api/orders", json=body, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _get(c, oid):
    return c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _vsteps(c, vkey, oid, *steps):
    h = _hdr(S[vkey]["id"])
    carrier = {"carrier": "BlueDart", "tracking_number": "BD1", "note": "Signed by recipient"}
    for st in steps:
        r = c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=h, json={"status": st, **carrier})
        assert r.status_code == 200, (st, r.text)


def _admin_status(c, oid, status):
    return c.put(f"/api/admin/orders/{oid}/status", json={"status": status}, headers=_hdr(S["admin"]["id"]))


def _age(c, oid, minutes):
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    c.portal.call(lambda: db.orders.update_one({"id": oid}, {"$set": {"created_at": ts}}))


# ================================================================= confirmed cancellation -> restock
def test_admin_cancel_before_dispatch_restocks_and_stops_fulfilment(c):
    p = _product(c, "C-1", 10)
    o = _order(c, p["id"], 3)
    assert _stock(c, p["id"]) == 7
    r = _admin_status(c, o["id"], "cancelled")
    assert r.status_code == 200 and r.json()["restock"]["restocked_lines"] == 1
    assert _stock(c, p["id"]) == 10
    got = _get(c, o["id"])
    assert got["fulfilments"][0]["status"] == "cancelled"                     # vendor can no longer work on it
    assert _admin_status(c, o["id"], "cancelled").status_code == 200          # repeat: no double restock
    assert _stock(c, p["id"]) == 10
    moves = c.portal.call(lambda: db.stock_movements.find({"order_id": o["id"], "reason": "order_cancelled_confirmed"}).to_list(5))
    assert len(moves) == 1


def test_cancel_after_dispatch_or_delivery_does_not_restock(c):
    p = _product(c, "C-2", 10)
    shipped = _order(c, p["id"], 2)
    _vsteps(c, "ua", shipped["id"], "accepted", "packed", "dispatched")
    assert _admin_status(c, shipped["id"], "cancelled").json()["restock"]["restocked_lines"] == 0
    assert _stock(c, p["id"]) == 8
    assert _get(c, shipped["id"])["fulfilments"][0]["status"] == "dispatched"   # goods in transit are left alone
    done = _order(c, p["id"], 1)
    _vsteps(c, "ua", done["id"], "accepted", "packed", "dispatched", "delivered")
    assert _admin_status(c, done["id"], "cancelled").json()["restock"]["restocked_lines"] == 0
    assert _stock(c, p["id"]) == 7


def test_platform_owned_line_restocks_only_if_not_shipped(c):
    p = _product(c, "C-3", 10, vendor=None)
    o1, o2 = _order(c, p["id"], 2), _order(c, p["id"], 1)
    assert _stock(c, p["id"]) == 7
    assert _admin_status(c, o1["id"], "cancelled").json()["restock"]["restocked_lines"] == 1
    assert _stock(c, p["id"]) == 9
    assert _admin_status(c, o2["id"], "shipped").status_code == 200
    assert _admin_status(c, o2["id"], "cancelled").json()["restock"]["restocked_lines"] == 0
    assert _stock(c, p["id"]) == 9


def test_non_cancel_status_changes_never_touch_stock_and_only_admins_can_cancel(c):
    p = _product(c, "C-4", 10)
    o = _order(c, p["id"], 1)
    assert _admin_status(c, o["id"], "processing").json()["restock"] is None
    assert _stock(c, p["id"]) == 9
    for who in ("cust", "ua", "genie"):
        assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr(S[who]["id"])).status_code == 403
    assert _stock(c, p["id"]) == 9


def test_refund_with_cancel_restocks_pre_dispatch_goods(c):
    p = _product(c, "C-5", 10)
    o = _order(c, p["id"], 2, method="online")
    sid = "cs_" + o["id"][:10]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))
    assert _stock(c, p["id"]) == 8
    r = c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "RF-1", "cancel_order": True}, headers=_hdr(S["admin"]["id"]))
    assert r.status_code == 200, r.text
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, p["id"]) == 10


# ================================================================= returned goods: restock only after inspection
def _returned(c, sku, qty=2):
    p = _product(c, sku, 10)
    o = _order(c, p["id"], qty)
    _vsteps(c, "ua", o["id"], "accepted", "packed", "dispatched")
    h = _hdr(S["ua"]["id"])
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=h, json={"status": "delivery_failed", "note": "Customer unreachable"}).status_code == 200
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=h, json={"status": "returned_to_origin", "note": "Courier returned parcel"}).status_code == 200
    return p, o


def test_return_to_origin_does_not_restock_by_itself(c):
    p, o = _returned(c, "R-1", 2)
    assert _stock(c, p["id"]) == 8                                           # not restocked just because it was declared returned


def test_inspection_rules_and_isolation(c):
    p, o = _returned(c, "R-2", 2)
    url = f"/api/vendor/orders/{o['id']}/return-inspection"
    ha, hb = _hdr(S["ua"]["id"]), _hdr(S["ub"]["id"])
    ok = {"received": True, "outcome": "resellable", "note": "Sealed, unused"}
    assert c.post(url, headers=ha, json={**ok, "received": False}).status_code == 400
    assert c.post(url, headers=ha, json={**ok, "outcome": "maybe"}).status_code == 400
    assert c.post(url, headers=ha, json={**ok, "note": "x"}).status_code == 422
    assert c.post(url, headers=hb, json=ok).status_code == 404                # another vendor cannot decide
    assert c.post(url, headers=_hdr(S["cust"]["id"]), json=ok).status_code == 403
    assert c.post(url, json=ok).status_code == 401
    assert _stock(c, p["id"]) == 8                                           # nothing changed by rejected attempts


def test_resellable_return_is_restocked_exactly_once_even_under_concurrency(c):
    p, o = _returned(c, "R-3", 3)
    url = f"/api/vendor/orders/{o['id']}/return-inspection"
    ok = {"received": True, "outcome": "resellable", "note": "Inspected, resellable"}
    with ThreadPoolExecutor(max_workers=2) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(c.post, url, headers=_hdr(S["ua"]["id"]), json=ok) for _ in range(2)])
    assert codes == [200, 400]
    assert _stock(c, p["id"]) == 10
    insp = _get(c, o["id"])["fulfilments"][0]["return_inspection"]
    assert insp["outcome"] == "resellable" and insp["note"] == "Inspected, resellable"
    assert c.post(url, headers=_hdr(S["ua"]["id"]), json=ok).status_code == 400   # decision is final


def test_damaged_return_is_recorded_but_not_restocked(c):
    p, o = _returned(c, "R-4", 2)
    r = c.post(f"/api/vendor/orders/{o['id']}/return-inspection", headers=_hdr(S["ua"]["id"]),
               json={"received": True, "outcome": "damaged", "note": "Torn packaging, stained"})
    assert r.status_code == 200 and r.json()["restocked_lines"] == 0
    assert _stock(c, p["id"]) == 8


def test_inspection_only_valid_for_returned_orders(c):
    p = _product(c, "R-5", 5)
    o = _order(c, p["id"], 1)
    r = c.post(f"/api/vendor/orders/{o['id']}/return-inspection", headers=_hdr(S["ua"]["id"]),
               json={"received": True, "outcome": "resellable", "note": "not returned at all"})
    assert r.status_code == 400 and _stock(c, p["id"]) == 4


# ================================================================= late payment: hold, queue, no commission / invoice
def _late_paid_without_stock(c, sku, seller=None):
    """Real flow: online order expires, someone else takes the stock, then the payment callback arrives."""
    p = _product(c, sku, 2)
    o = _order(c, p["id"], 2, method="online", seller=seller)
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _age(c, o["id"], 20)
    assert c.get("/api/cron/expire-pending-orders", headers=CRON).status_code == 200
    _order(c, p["id"], 2)                                                    # stock is bought by someone else
    c.portal.call(lambda: shop_routes._process_paid_order(sid))
    return p, o


def test_commissions_are_really_created_for_a_normal_paid_order_control(c):
    p = _product(c, "H-0", 5)
    o = _order(c, p["id"], 1, method="online", seller="HGSEL")
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) >= 1   # so the 0 below is meaningful


def test_refund_hold_blocks_fulfilment_commission_and_invoice(c):
    p, o = _late_paid_without_stock(c, "H-1", seller="HGSEL")
    got = _get(c, o["id"])
    assert got["needs_refund"] is True and got["status"] == "cancelled" and got["payment_status"] == "paid"
    assert not got.get("invoice_number")
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0
    ha = _hdr(S["ua"]["id"])
    assert o["id"] not in [x["id"] for x in c.get("/api/vendor/orders", headers=ha).json()]
    assert c.get(f"/api/vendor/orders/{o['id']}", headers=ha).status_code == 404
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=ha, json={"status": "accepted"}).status_code == 404
    assert o["id"] not in [x["id"] for x in c.get("/api/vendor/orders?page=1", headers=ha).json()["items"]]
    for st in ("processing", "packed", "shipped", "delivered", "paid"):
        assert _admin_status(c, o["id"], st).status_code == 400, st
    assert _get(c, o["id"])["status"] == "cancelled"
    assert _stock(c, p["id"]) == 0                                           # no oversell


def test_admin_refund_queue(c):
    p1, o1 = _late_paid_without_stock(c, "Q-1")
    p2, o2 = _late_paid_without_stock(c, "Q-2")
    ha = _hdr(S["admin"]["id"])
    q = c.get("/api/admin/refund-queue", headers=ha).json()
    ids = [x["id"] for x in q["items"]]
    assert o1["id"] in ids and o2["id"] in ids and q["open_count"] >= 2
    row = next(x for x in q["items"] if x["id"] == o1["id"])
    assert row["needs_refund_reason"] == "paid_after_timeout_out_of_stock" and row["user_name"] and row["waiting_hours"] is not None
    first = c.get("/api/admin/refund-queue?page=1&page_size=1", headers=ha).json()
    second = c.get("/api/admin/refund-queue?page=2&page_size=1", headers=ha).json()
    assert len(first["items"]) == 1 and len(second["items"]) == 1 and first["items"][0]["id"] != second["items"][0]["id"]
    assert first["pages"] == first["total"]
    assert c.get("/api/admin/refund-queue?state=bogus", headers=ha).status_code == 400
    # access control
    assert c.get("/api/admin/refund-queue").status_code == 401
    for who in ("ua", "cust", "genie"):
        assert c.get("/api/admin/refund-queue", headers=_hdr(S[who]["id"])).status_code == 403
    # resolving: a full refund moves the case out of the open queue
    r = c.post(f"/api/admin/orders/{o1['id']}/refund", json={"reference": "UTR-REFUND-1"}, headers=ha)
    assert r.status_code == 200, r.text
    after = c.get("/api/admin/refund-queue", headers=ha).json()
    assert o1["id"] not in [x["id"] for x in after["items"]] and after["open_count"] == q["open_count"] - 1
    assert o1["id"] in [x["id"] for x in c.get("/api/admin/refund-queue?state=resolved", headers=ha).json()["items"]]


# ================================================================= dashboard: unpaid COD vs collected
def test_dashboard_separates_order_value_collected_and_unpaid_cod(c):
    p = _product(c, "D-1", 100, price=33.33, vendor="vb")
    hb = _hdr(S["ub"]["id"])
    cod_unpaid = _order(c, p["id"], 3)                                       # 99.99, cash not collected
    cod_paid = _order(c, p["id"], 1)                                         # 33.33, cash collected
    online = _order(c, p["id"], 2, method="online")                          # 66.66, paid online
    claimed = _order(c, p["id"], 1, method="online")                         # 33.33, UPI claimed, awaiting admin
    rejected = _order(c, p["id"], 5)                                         # vendor rejects: excluded
    unpaid_online = _order(c, p["id"], 4, method="online")                   # never paid: not visible at all
    ha = _hdr(S["admin"]["id"])
    assert c.post(f"/api/orders/{cod_paid['id']}/cod-collected", headers=ha).status_code == 200
    sid = "cs_" + online["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": online["id"], "user_id": online["user_id"], "amount": online["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))
    assert c.post("/api/payments/upi-claim", json={"order_id": claimed["id"], "reference": "UTR998877"}, headers=_hdr(S["cust"]["id"])).status_code == 200
    assert c.post(f"/api/vendor/orders/{rejected['id']}/fulfilment", headers=hb, json={"status": "rejected", "note": "Out of material"}).status_code == 200

    d = c.get("/api/vendor/dashboard", headers=hb).json()["sales"]
    assert d["collected_this_month"] == 99.99                                # 33.33 (COD collected) + 66.66 (online)
    assert d["cod_awaiting_collection"] == 99.99                             # unpaid COD is NOT revenue
    assert d["awaiting_confirmation"] == 33.33
    assert d["under_review"] == 0
    assert d["order_value_this_month"] == 233.31                             # 99.99 + 99.99 + 33.33 (rejected + unpaid online excluded)
    assert d["order_value_this_month"] == round(d["collected_this_month"] + d["cod_awaiting_collection"]
                                                + d["awaiting_confirmation"] + d["under_review"], 2)
    assert d["gross_this_month"] == d["order_value_this_month"]              # deprecated alias, same number
    assert d["collected_this_month"] < d["order_value_this_month"]


# ================================================================= pagination + search
def test_products_list_is_backward_compatible_and_paginates(c):
    for i in range(7):
        _product(c, f"P-{i:02d}", 3 + i, vendor="vb", name=f"Silk Saree {i}", created=f"2026-01-0{i + 1}T00:00:00+00:00")
    hb = _hdr(S["ub"]["id"])
    plain = c.get("/api/vendor/products", headers=hb).json()
    assert isinstance(plain, list) and len(plain) >= 7                       # original contract untouched
    r = c.get("/api/vendor/products?page=1&page_size=3&q=silk", headers=hb).json()
    assert r["total"] == 7 and r["pages"] == 3 and len(r["items"]) == 3 and r["page"] == 1
    seen = []
    for pg in (1, 2, 3):
        seen += [x["sku"] for x in c.get(f"/api/vendor/products?page={pg}&page_size=3&q=silk", headers=hb).json()["items"]]
    assert len(seen) == 7 and len(set(seen)) == 7                            # pages are disjoint and complete
    assert c.get("/api/vendor/products?page=1&page_size=3&q=SILK%20SAREE%203", headers=hb).json()["total"] == 1   # case-insensitive
    assert c.get("/api/vendor/products?q=p-04", headers=hb).json()["total"] == 1                              # by SKU
    big = c.get("/api/vendor/products?page=0&page_size=100000", headers=hb).json()
    assert big["page"] == 1 and big["page_size"] == 100                      # clamped


def test_search_input_is_treated_as_text_not_as_a_query(c):
    hb = _hdr(S["ub"]["id"])
    for evil in (".*", "(", "[", "$ne", "{\"$gt\":\"\"}", "a|b", "\\"):
        r = c.get("/api/vendor/products", headers=hb, params={"page": 1, "q": evil})
        assert r.status_code == 200 and r.json()["total"] == 0, evil
        r = c.get("/api/vendor/orders", headers=hb, params={"page": 1, "q": evil})
        assert r.status_code == 200 and r.json()["total"] == 0, evil
    assert c.get("/api/vendor/products", headers=hb, params={"q": "x" * 5000, "page": 1}).status_code == 200


def test_filters_counts_and_validation(c):
    hb = _hdr(S["ub"]["id"])
    out = _product(c, "F-OUT", 0, vendor="vb")
    low = _product(c, "F-LOW", 2, vendor="vb")
    r = c.get("/api/vendor/products?page=1&stock=out", headers=hb).json()
    assert out["id"] in [x["id"] for x in r["items"]] and low["id"] not in [x["id"] for x in r["items"]]
    assert low["id"] in [x["id"] for x in c.get("/api/vendor/products?page=1&stock=low", headers=hb).json()["items"]]
    assert r["counts"]["all"] >= 9 and r["counts"]["out"] >= 1 and r["counts"]["approved"] == r["counts"]["all"]
    for bad in ("approval=nope", "stock=nope"):
        assert c.get(f"/api/vendor/products?page=1&{bad}", headers=hb).status_code == 400
    for bad in ("status=nope", "date_from=2026-13", "date_to=yesterday"):
        assert c.get(f"/api/vendor/orders?page=1&{bad}", headers=hb).status_code == 400


def test_orders_pagination_search_dates_counts_and_isolation(c):
    pa = _product(c, "O-A1", 50, vendor="va", name="Zebra Print Saree")
    pb = _product(c, "O-B1", 50, vendor="vb", name="Zebra Print Kurti")
    mine = [_order(c, pb["id"], 1) for _ in range(5)]
    theirs = _order(c, pa["id"], 1)
    hb = _hdr(S["ub"]["id"])
    _vsteps(c, "ub", mine[0]["id"], "accepted")
    plain = c.get("/api/vendor/orders", headers=hb).json()
    assert isinstance(plain, list) and theirs["id"] not in [x["id"] for x in plain]
    r = c.get("/api/vendor/orders?page=1&page_size=2&q=zebra", headers=hb).json()
    assert r["total"] == 5 and r["pages"] == 3 and len(r["items"]) == 2
    assert theirs["id"] not in [x["id"] for x in r["items"]]                 # other vendor's order never matches
    assert c.get("/api/vendor/orders?page=1&q=O-A1", headers=hb).json()["total"] == 0          # nor by their SKU
    assert c.get(f"/api/vendor/orders?page=1&q={mine[2]['order_number']}", headers=hb).json()["total"] == 1   # by order number
    assert r["counts"]["new"] == 4 and r["counts"]["accepted"] == 1 and r["counts"]["all"] == 5
    only_new = c.get("/api/vendor/orders?page=1&status=new&q=zebra", headers=hb).json()
    assert only_new["total"] == 4 and all(x["fulfilment"]["status"] == "new" for x in only_new["items"])
    assert only_new["counts"]["all"] == 5                                    # tab counts ignore the status filter
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert c.get(f"/api/vendor/orders?page=1&q=zebra&date_from={today}&date_to={today}", headers=hb).json()["total"] == 5
    assert c.get("/api/vendor/orders?page=1&q=zebra&date_to=2020-01-01", headers=hb).json()["total"] == 0
    assert c.get("/api/vendor/orders?page=1", headers=hb).status_code == 200
    assert c.get("/api/vendor/orders?page=1").status_code == 401
    assert c.get("/api/vendor/orders?page=1", headers=_hdr(S["cust"]["id"])).status_code == 403


# ================================================================= review fixes
def _paid_tx(c, o):
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    return sid


def test_payment_for_an_admin_cancelled_order_is_refunded_not_reopened(c):
    p = _product(c, "X-1", 5)
    o = _order(c, p["id"], 2, method="online", seller="HGSEL")
    sid = _paid_tx(c, o)
    assert _admin_status(c, o["id"], "cancelled").status_code == 200            # admin cancels; stock goes back
    assert _stock(c, p["id"]) == 5
    c.portal.call(lambda: shop_routes._process_paid_order(sid))                   # customer's open payment session completes
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and got["payment_status"] == "paid" and got["needs_refund"] is True
    assert got["needs_refund_reason"] == "paid_after_cancellation"                # admin's decision stands: not revived
    assert not got.get("invoice_number") and _stock(c, p["id"]) == 5              # stock was NOT taken again
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0
    assert o["id"] not in [x["id"] for x in c.get("/api/vendor/orders", headers=_hdr(S["ua"]["id"])).json()]
    assert o["id"] in [x["id"] for x in c.get("/api/admin/refund-queue", headers=_hdr(S["admin"]["id"])).json()["items"]]


def test_cash_cannot_be_confirmed_on_a_cancelled_cod_order(c):
    p = _product(c, "X-2", 5)
    o = _order(c, p["id"], 1, method="cod", seller="HGSEL")
    assert _admin_status(c, o["id"], "cancelled").status_code == 200
    r = c.post(f"/api/orders/{o['id']}/cod-collected", headers=_hdr(S["admin"]["id"]))
    assert r.status_code == 400
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and got["payment_status"] == "cod_pending"
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0


def test_viewing_someone_elses_order_is_refused_and_has_no_side_effects(c):
    p = _product(c, "X-3", 5)
    o = _order(c, p["id"], 1, method="online")
    _age(c, o["id"], 30)                                                         # overdue, but nobody has swept it yet
    assert c.get(f"/api/orders/{o['id']}", headers=_hdr(S["cust2"]["id"])).status_code == 403
    assert _get(c, o["id"])["status"] == "payment_pending" and _stock(c, p["id"]) == 4   # the stranger changed nothing
    mine = c.get(f"/api/orders/{o['id']}", headers=_hdr(S["cust"]["id"])).json()           # the owner's view applies the expiry
    assert mine["status"] == "cancelled" and _stock(c, p["id"]) == 5


def test_sweep_finishes_an_expiry_that_was_interrupted(c):
    p = _product(c, "X-4", 5)
    o = _order(c, p["id"], 2, method="online")
    assert _stock(c, p["id"]) == 3
    # simulate a function timeout after the order was cancelled but before its stock was returned
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled", "cancel_reason": "payment_timeout"}}))
    assert c.get("/api/cron/expire-pending-orders", headers=CRON).json()["expired"] >= 1
    assert _stock(c, p["id"]) == 5
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert _stock(c, p["id"]) == 5                                               # and only once


def test_inspection_does_not_double_restock_orders_returned_under_the_old_rule(c):
    p, o = _returned(c, "X-5", 2)
    # the previous rule restocked automatically at return time and logged this movement reason
    c.portal.call(lambda: db.stock_movements.insert_one({"id": new_id(), "product_id": p["id"], "delta": 2,
                                                         "reason": "order_returned_to_origin", "order_id": o["id"], "created_at": now_iso()}))
    c.portal.call(lambda: db.products.update_one({"id": p["id"]}, {"$inc": {"stock": 2}}))   # ...which put the units back
    assert _stock(c, p["id"]) == 10
    r = c.post(f"/api/vendor/orders/{o['id']}/return-inspection", headers=_hdr(S["ua"]["id"]),
               json={"received": True, "outcome": "resellable", "note": "Inspected, fine"})
    assert r.status_code == 200 and r.json()["restocked_lines"] == 0 and _stock(c, p["id"]) == 10
    assert _get(c, o["id"])["fulfilments"][0]["return_inspection"]["outcome"] == "resellable"


def test_unclassified_payment_status_stays_inside_the_money_identity(c):
    p = _product(c, "X-6", 50, price=40, vendor="vb")
    odd = _order(c, p["id"], 1)
    c.portal.call(lambda: db.orders.update_one({"id": odd["id"]}, {"$set": {"payment_status": "authorized"}}))
    d = c.get("/api/vendor/dashboard", headers=_hdr(S["ub"]["id"])).json()["sales"]
    assert d["under_review"] >= 40
    assert d["order_value_this_month"] == round(d["collected_this_month"] + d["cod_awaiting_collection"]
                                                + d["awaiting_confirmation"] + d["under_review"], 2)
