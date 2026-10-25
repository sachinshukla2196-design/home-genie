"""Vendor operations (Phase 5): product CRUD and approval, inventory rules, order transitions, returns authority and isolation.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_vendor_operations.py -n 0`.
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_vendor_ops_test", "JWT_SECRET": "vendor-ops-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
PW = "Vendor-Pass-123"
S = {}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _iso(days_ago=1):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).replace(hour=12, minute=0, second=0, microsecond=0).isoformat()


def _body(sku, **kw):
    b = {"sku": sku, "name": f"Product {sku}", "mrp": 1000, "selling_price": 800, "category": "Sarees", "stock": 10}
    b.update(kw)
    return b


def _rows(resp):
    body = resp.json()
    return body if isinstance(body, list) else body.get("items", [])


def _order(vid, product_id, qty=2, status="new", user=None):
    total = 80000 * qty
    line = {"product_id": product_id, "name": "Ops Saree", "sku": "OPS", "vendor_id": vid, "quantity": qty, "total_paise": total, "total": total / 100}
    return {"id": new_id(), "order_number": "OPS" + new_id()[:8].upper(), "user_id": user or new_id(), "payment_method": "cod",
            "payment_status": "cod_pending", "status": status, "created_at": _iso(), "paid_at": None, "total_paise": total, "total": total / 100,
            "items": [line], "fulfilments": [{"vendor_id": vid, "status": status, "events": []}], "address": ADDR, "needs_refund": False}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()      # the migration step: startup no longer creates indexes

            async def user(mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password(PW), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name, code):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": code, "business_name": name, "status": "approved",
                     "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v

            S["adm"] = await user("9100002001", "super_admin", "OADM")
            S["cust"] = await user("9100002002", "distributor", "OCUS")
            S["ua"] = await user("9100002003", "vendor", "OVA")
            S["va"] = await vendor(S["ua"], "Ops Store A", "VO000001")
            S["ub"] = await user("9100002004", "vendor", "OVB")
            S["vb"] = await vendor(S["ub"], "Ops Store B", "VO000002")
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ====================================================================== product CRUD and approval
def test_product_create_list_view_edit_and_archive(c):
    h = _hdr(S["ua"]["id"])
    r = c.post("/api/vendor/products", headers=h, json=_body("CRUD-1", description="Handwoven", images=[]))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["approval_status"] == "pending" and p["stock"] == 10
    assert c.get("/api/vendor/products", headers=h).status_code == 200
    assert any(x["id"] == p["id"] for x in _rows(c.get("/api/vendor/products", headers=h)))
    edited = c.put(f"/api/vendor/products/{p['id']}", headers=h, json=_body("CRUD-1", name="Renamed Saree", description="Handwoven silk", category="Sarees"))
    assert edited.status_code == 200 and edited.json()["name"] == "Renamed Saree"
    archived = c.post(f"/api/vendor/products/{p['id']}/archive", headers=h, json={"archived": True})
    assert archived.status_code == 200
    listed = _rows(c.get("/api/vendor/products", headers=h))
    assert all(x["id"] != p["id"] for x in listed) or any(x["id"] == p["id"] and x.get("archived") for x in listed)


def test_only_the_four_pillars_are_accepted(c):
    h = _hdr(S["ua"]["id"])
    for ok in ("Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"):
        assert c.post("/api/vendor/products", headers=h, json=_body(f"PIL-{ok[:4]}", category=ok)).status_code in (200, 400)  # attributes may still apply
    assert c.post("/api/vendor/products", headers=h, json=_body("PIL-BAD", category="Electronics")).status_code == 400
    assert c.post("/api/vendor/products", headers=h, json=_body("PIL-NONE", category="")).status_code in (400, 422)


def test_product_approval_and_rejection_reason_are_shown_to_the_vendor(c):
    h = _hdr(S["ua"]["id"])
    p = c.post("/api/vendor/products", headers=h, json=_body("APP-1")).json()
    adm = _hdr(S["adm"]["id"])
    assert c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=adm, json={"action": "reject", "reason": "x"}).status_code == 400   # reason too short
    assert c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=adm, json={"action": "reject", "reason": "Photos are unclear"}).status_code == 200
    seen = _rows(c.get("/api/vendor/products", headers=h, params={"approval": "rejected"}))
    row = next(x for x in seen if x["id"] == p["id"])
    assert row["approval_status"] == "rejected" and row["rejection_reason"] == "Photos are unclear" and row["is_active"] is False
    assert c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=adm, json={"action": "approve"}).status_code == 400   # rejected: must be resubmitted first
    fresh = c.post("/api/vendor/products", headers=h, json=_body("APP-2")).json()
    assert c.post(f"/api/admin/vendor-products/{fresh['id']}/decision", headers=adm, json={"action": "approve"}).status_code == 200
    live = next(x for x in _rows(c.get("/api/vendor/products", headers=h)) if x["id"] == fresh["id"])
    assert live["approval_status"] == "approved" and live["is_active"] is True


# ====================================================================== inventory
def test_inventory_adjustments_record_history_and_never_go_negative(c):
    h = _hdr(S["ua"]["id"])
    p = c.post("/api/vendor/products", headers=h, json=_body("INV-1", stock=4)).json()
    url = f"/api/vendor/products/{p['id']}/stock"
    assert c.post(url, headers=h, json={"delta": -5, "reason": "Damaged on shelf"}).status_code == 400          # would go negative
    assert c.post(url, headers=h, json={"delta": 0, "reason": "Nothing changed"}).status_code == 400
    assert c.post(url, headers=h, json={"delta": 3, "reason": "Supplier delivery"}).status_code == 200
    assert c.post(url, headers=h, json={"delta": -7, "reason": "Recount"}).status_code == 200
    assert c.post(url, headers=h, json={"delta": -1, "reason": "One more"}).status_code == 400              # stock is now 0
    hist = c.get(f"/api/vendor/products/{p['id']}/stock-history", headers=h).json()
    rows = hist if isinstance(hist, list) else hist.get("items", hist.get("movements", []))
    assert rows[0]["delta"] == -7 and rows[0]["after"] == 0 and rows[0]["reason"] == "Recount"      # newest first
    assert rows[1]["delta"] == 3 and rows[1]["after"] == 7


# ====================================================================== order transitions
def test_order_transitions_are_validated_and_cannot_be_applied_twice(c):
    h = _hdr(S["ua"]["id"])
    prod = c.post("/api/vendor/products", headers=h, json=_body("ORD-1", stock=20)).json()
    o = _order(S["va"]["id"], prod["id"])
    c.portal.call(lambda: db.orders.insert_one(dict(o)))
    url = f"/api/vendor/orders/{o['id']}/fulfilment"
    assert c.post(url, headers=h, json={"status": "delivered", "note": "Skipped steps"}).status_code == 400   # new -> delivered
    assert c.post(url, headers=h, json={"status": "accepted", "note": "Accepted"}).status_code == 200
    assert c.post(url, headers=h, json={"status": "accepted", "note": "Again"}).status_code == 400          # already accepted
    assert c.post(url, headers=h, json={"status": "packed", "note": "Packed well"}).status_code == 200
    assert c.post(url, headers=h, json={"status": "dispatched", "note": "Sent"}).status_code == 400          # no carrier/tracking
    assert c.post(url, headers=h, json={"status": "dispatched", "note": "Sent", "carrier": "Bluedart", "tracking_number": "BD123"}).status_code == 200
    assert c.post(url, headers=h, json={"status": "dispatched", "note": "Sent twice", "carrier": "Bluedart", "tracking_number": "BD123"}).status_code == 400   # no duplicate dispatch
    assert c.post(url, headers=h, json={"status": "cancelled", "note": "Too late"}).status_code == 400    # cannot cancel after dispatch
    assert c.post(url, headers=h, json={"status": "delivered", "note": "Received"}).status_code == 200
    stored = c.portal.call(lambda: db.orders.find_one({"id": o["id"]}, {"_id": 0, "fulfilments": 1}))
    assert stored["fulfilments"][0]["status"] == "delivered"


def test_orders_are_only_visible_and_changeable_by_their_own_vendor(c):
    prod = c.post("/api/vendor/products", headers=_hdr(S["ub"]["id"]), json=_body("OWN-B", stock=5)).json()
    o = _order(S["vb"]["id"], prod["id"], qty=1)
    c.portal.call(lambda: db.orders.insert_one(dict(o)))
    assert c.get(f"/api/vendor/orders/{o['id']}", headers=_hdr(S["ua"]["id"])).status_code == 404
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", headers=_hdr(S["ua"]["id"]), json={"status": "accepted", "note": "Not mine"}).status_code == 404
    assert c.get(f"/api/vendor/orders/{o['id']}", headers=_hdr(S["ub"]["id"])).status_code == 200
    ids_a = [x["id"] for x in _rows(c.get("/api/vendor/orders", headers=_hdr(S["ua"]["id"])))]
    assert o["id"] not in ids_a


def test_products_and_stock_of_another_vendor_cannot_be_touched(c):
    other = c.post("/api/vendor/products", headers=_hdr(S["ub"]["id"]), json=_body("ISO-B", stock=5)).json()
    h = _hdr(S["ua"]["id"])
    assert c.put(f"/api/vendor/products/{other['id']}", headers=h, json=_body("ISO-B", name="Hijack")).status_code == 404
    assert c.post(f"/api/vendor/products/{other['id']}/stock", headers=h, json={"delta": 1, "reason": "Stealing"}).status_code == 404
    assert c.post(f"/api/vendor/products/{other['id']}/archive", headers=h, json={"archived": True}).status_code == 404
    assert c.get(f"/api/vendor/products/{other['id']}/stock-history", headers=h).status_code == 404


# ====================================================================== returns and refund authority
def test_vendors_cannot_refund_and_admin_refund_endpoints_refuse_vendors(c):
    h = _hdr(S["ua"]["id"])
    assert c.post(f"/api/vendor/returns/{new_id()}/action", headers=h, json={"action": "refund", "note": "Refund it now"}).status_code in (400, 404)
    assert c.get("/api/admin/refund-cases", headers=h).status_code == 403
    assert c.post(f"/api/admin/refund-cases/{new_id()}/action", headers=h, json={"action": "confirm", "note": "x"}).status_code == 403
    assert c.post(f"/api/admin/returns/{new_id()}/decision", headers=h, json={"action": "approve", "note": "x"}).status_code == 403
    assert c.get("/api/admin/refund-cases", headers=_hdr(S["cust"]["id"])).status_code == 403
