"""Vendor panel baseline (Phase A): access control, tenant isolation, product/stock/order rules.

In-process (no live server); uses a THROWAWAY database that is dropped at the end. Needs MONGO_URL in the
environment (any reachable MongoDB); DB_NAME is forced to a test database so real data is never touched.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_core_test",
                   "JWT_SECRET": "vendor-core-test-" + "k" * 40, "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
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
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status,
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name, status):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": name,
                     "status": status, "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            async def product(v, sku, stock, approved=True):
                p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": 1000, "selling_price": 800, "gst_percent": 5,
                     "stock": stock, "category": "Sarees", "options": [], "vendor_id": v["id"], "vendor_name": v["business_name"],
                     "is_active": approved, "approval_status": "approved" if approved else "pending", "created_at": now_iso()}
                await db.products.insert_one(dict(p))
                return p

            ua, ub = await user("9100000101", "vendor", "VDA"), await user("9100000102", "vendor", "VDB")
            ud, us = await user("9100000103", "vendor", "VDD"), await user("9100000104", "vendor", "VDS")
            S.update(ua=ua, ub=ub, ud=ud, us=us,
                     cust=await user("9100000105", "distributor", "HGC", "red"),
                     genie=await user("9100000106", "distributor", "HGG"))
            S["va"], S["vb"] = await vendor(ua, "Vendor A", "approved"), await vendor(ub, "Vendor B", "approved")
            await vendor(ud, "Draft Vendor", "draft")
            await vendor(us, "Suspended Vendor", "suspended")
            S["pa"], S["pb"] = await product(S["va"], "A-1", 10), await product(S["vb"], "B-1", 10)
            S["last"] = await product(S["va"], "A-LAST", 1)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _order(c, pid, qty=1):
    return c.post("/api/orders", json={"items": [{"product_id": pid, "quantity": qty}], "address": ADDR,
                                       "payment_method": "cod"}, headers=_hdr(S["cust"]["id"]))


# ---------------------------------------------------------------- access control
def test_no_token_and_wrong_roles_are_refused(c):
    assert c.get("/api/vendor/products").status_code == 401
    assert c.get("/api/vendor/me", headers=_hdr(S["cust"]["id"])).status_code == 403
    assert c.get("/api/vendor/products", headers=_hdr(S["genie"]["id"])).status_code == 403


def test_draft_and_suspended_vendors_cannot_sell(c):
    for key in ("ud", "us"):
        h = _hdr(S[key]["id"])
        assert c.get("/api/vendor/products", headers=h).status_code == 403
        assert c.post("/api/vendor/products", headers=h, json={"sku": "ZZ-1", "name": "Zz", "mrp": 10, "selling_price": 9,
                                                              "category": "Sarees"}).status_code == 403
        assert c.get("/api/vendor/orders", headers=h).status_code == 403


# ---------------------------------------------------------------- tenant isolation
def test_vendor_cannot_touch_another_vendors_records(c):
    ha = _hdr(S["ua"]["id"])
    pid = S["pb"]["id"]
    assert c.put(f"/api/vendor/products/{pid}", headers=ha, json={"sku": "B-1", "name": "xx", "mrp": 10, "selling_price": 9,
                                                                 "category": "Sarees"}).status_code == 404
    assert c.post(f"/api/vendor/products/{pid}/stock", headers=ha, json={"delta": 5, "reason": "not mine"}).status_code == 404
    assert c.get(f"/api/vendor/products/{pid}/stock-history", headers=ha).status_code == 404
    assert c.post(f"/api/vendor/products/{pid}/listing", headers=ha, json={"active": False}).status_code == 404
    oid = _order(c, pid).json()["id"]
    assert c.get(f"/api/vendor/orders/{oid}", headers=ha).status_code == 404
    assert c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=ha, json={"status": "accepted"}).status_code == 404
    assert oid not in [o["id"] for o in c.get("/api/vendor/orders", headers=ha).json()]
    assert all(p["vendor_id"] == S["va"]["id"] for p in c.get("/api/vendor/products", headers=ha).json())


# ---------------------------------------------------------------- products
def test_new_product_needs_admin_approval_and_validates_input(c):
    h = _hdr(S["ua"]["id"])
    base = {"sku": "a-new-1", "name": "New", "mrp": 1000, "selling_price": 900, "category": "Sarees", "stock": 3}
    r = c.post("/api/vendor/products", headers=h, json=base)
    assert r.status_code == 200 and r.json()["approval_status"] == "pending" and r.json()["is_active"] is False
    assert r.json()["sku"] == "A-NEW-1"
    pid = r.json()["id"]
    assert c.post(f"/api/vendor/products/{pid}/listing", headers=h, json={"active": True}).status_code == 400  # not approved
    assert c.post("/api/vendor/products", headers=h, json=base).status_code == 400                           # duplicate SKU
    assert c.post("/api/vendor/products", headers=h, json={**base, "sku": "a-2", "selling_price": 1500}).status_code == 400
    assert c.post("/api/vendor/products", headers=h, json={**base, "sku": "a-3", "category": "Electronics"}).status_code == 400
    assert c.post("/api/vendor/products", headers=h, json={**base, "sku": "a-4", "mrp": -5}).status_code == 422


def test_product_images_must_be_safe_references(c):
    h = _hdr(S["ua"]["id"])
    base = {"name": "Img", "mrp": 1000, "selling_price": 900, "category": "Sarees"}
    unsafe = ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "vbscript:msgbox(1)", "data:text/html;base64,AAAA", "file:///etc/passwd",
              "http://insecure.example/x.png", "//evil.example/x.png", "ftp://host/x.png", "blob:https://x/1",
              "/../../etc/passwd", "/ok.png<script>", "https://x.example/a b.png", 'https://x.example/a".png',
              "https://x.example/" + "a" * 600, "", "   "]
    for i, bad in enumerate(unsafe):
        r = c.post("/api/vendor/products", headers=h, json={**base, "sku": f"IMG-BAD-{i}", "images": [bad]})
        assert r.status_code == 422, repr(bad)
    assert c.post("/api/vendor/products", headers=h, json={**base, "sku": "IMG-MANY", "images": ["/brand/a.jpg"] * 9}).status_code == 422
    legit = ["/api/files/homegenies/vendor/abc/123.png", "/brand/pillar-sarees.jpg", "https://cdn.example.com/a.jpg",
             "https://res.cloudinary.com/demo/image/upload/v1/sample.jpg?w=800&q=80"]
    for i, good in enumerate(legit):
        r = c.post("/api/vendor/products", headers=h, json={**base, "sku": f"IMG-OK-{i}", "images": [good]})
        assert r.status_code == 200, good
        assert r.json()["images"] == [good]
    two = c.post("/api/vendor/products", headers=h, json={**base, "sku": "IMG-OK-MULTI", "images": legit[:3]})
    assert two.status_code == 200 and two.json()["images"] == legit[:3]
    # the update path is validated too (not just create)
    pid = two.json()["id"]
    upd = {**base, "sku": "IMG-OK-MULTI"}
    assert c.put(f"/api/vendor/products/{pid}", headers=h, json={**upd, "images": ["javascript:alert(1)"]}).status_code == 422
    assert c.put(f"/api/vendor/products/{pid}", headers=h, json={**upd, "images": [legit[0]]}).status_code == 200


# ---------------------------------------------------------------- stock
def test_stock_never_negative_and_changes_are_recorded(c):
    h = _hdr(S["ua"]["id"])
    pid = S["pa"]["id"]
    assert c.post(f"/api/vendor/products/{pid}/stock", headers=h, json={"delta": -999, "reason": "too many"}).status_code == 400
    assert c.post(f"/api/vendor/products/{pid}/stock", headers=h, json={"delta": 0, "reason": "nothing"}).status_code == 400
    assert c.post(f"/api/vendor/products/{pid}/stock", headers=h, json={"delta": 5}).status_code == 422          # reason required
    r = c.post(f"/api/vendor/products/{pid}/stock", headers=h, json={"delta": -2, "reason": "damaged in storage"})
    assert r.status_code == 200 and r.json()["stock"] == 8
    last = c.get(f"/api/vendor/products/{pid}/stock-history", headers=h).json()[0]
    assert (last["delta"], last["before"], last["after"], last["reason"]) == (-2, 10, 8, "damaged in storage")


def test_last_unit_cannot_be_oversold_under_concurrency(c):
    pid = S["last"]["id"]
    with ThreadPoolExecutor(max_workers=2) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(_order, c, pid), ex.submit(_order, c, pid)])
    assert codes == [200, 409]
    assert c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"] == 0


# ---------------------------------------------------------------- order fulfilment
def test_fulfilment_state_machine_and_cod_separation(c):
    h = _hdr(S["ua"]["id"])
    pid = S["pa"]["id"]
    before = c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"]
    oid = _order(c, pid, 2).json()["id"]
    url = f"/api/vendor/orders/{oid}/fulfilment"
    step = lambda **b: c.post(url, headers=h, json=b)
    assert step(status="packed").status_code == 400                       # cannot skip 'accepted'
    assert step(status="delivered", note="proof").status_code == 400
    assert step(status="accepted").status_code == 200
    assert step(status="accepted").status_code == 400                     # replay rejected
    assert step(status="dispatched").status_code == 400                   # needs carrier + tracking
    assert step(status="packed").status_code == 200
    assert step(status="dispatched", carrier="BlueDart", tracking_number="BD123").status_code == 200
    assert step(status="delivered").status_code == 400                    # needs delivery evidence
    assert step(status="delivered", note="Signed by recipient").status_code == 200
    o = c.portal.call(lambda: db.orders.find_one({"id": oid}))
    assert o["payment_status"] == "cod_pending"                           # delivered != paid/collected
    assert c.post(f"/api/orders/{oid}/cod-collected", headers=h).status_code == 403   # vendor cannot confirm cash
    assert c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"] == before - 2


def test_vendor_rejection_restocks_exactly_once(c):
    h = _hdr(S["ua"]["id"])
    pid = S["pa"]["id"]
    before = c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"]
    oid = _order(c, pid, 3).json()["id"]
    url = f"/api/vendor/orders/{oid}/fulfilment"
    assert c.post(url, headers=h, json={"status": "rejected", "note": "x"}).status_code == 400          # reason too short
    assert c.post(url, headers=h, json={"status": "rejected", "note": "Out of material"}).status_code == 200
    assert c.post(url, headers=h, json={"status": "rejected", "note": "Out of material"}).status_code == 400
    assert c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"] == before
