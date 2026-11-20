"""Batch 9 / 10 — a suspended vendor keeps access to what it owes customers (paid orders, open returns) but cannot sell; every
API response carries security headers; an unhandled error becomes a JSON 500 with an error id and still carries CORS headers.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_platform_batch9_10.py -n 0`).
"""
import os

import pytest

ORIGIN = "https://home-genie-9zfc.vercel.app"
os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_platform_batch910_test", "JWT_SECRET": "batch910-test-" + "k" * 40,
                   "CORS_ORIGINS": ORIGIN, "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    async def boom():
        raise RuntimeError("simulated bug")
    server.app.add_api_route("/api/__test_boom", boom, methods=["GET"])
    with TestClient(server.app, raise_server_exceptions=False) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, mob, role in (("cust", "9100009001", "distributor"), ("super", "9100009002", "super_admin"), ("vu", "9100009003", "vendor")):
                u = {"id": new_id(), "distributor_id": key.upper() + "9", "full_name": key, "mobile": mob, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "VD9", "business_name": "Vendor 9", "status": "approved",
                      "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
            await db.products.insert_one({"id": "p9", "sku": "B9-1", "name": "Saree", "images": [], "mrp": 1200, "selling_price": 1000,
                                          "gst_percent": 5, "stock": 10, "category": "Sarees", "options": [], "vendor_id": S["v"]["id"],
                                          "vendor_name": "Vendor 9", "is_active": True, "approval_status": "approved", "created_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def test_a_suspended_vendor_still_serves_orders_paid_before_the_suspension_but_cannot_sell(c):
    o = c.post("/api/orders", json={"items": [{"product_id": "p9", "quantity": 1}], "address": ADDR, "payment_method": "online"},
               headers=_hdr("cust")).json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    r = c.post(f"/api/admin/vendors/{S['v']['id']}/decision", json={"action": "suspend", "reason": "Quality review pending"}, headers=_hdr("super"))
    assert r.status_code == 200, r.text
    h = _hdr("vu")
    listing = c.get("/api/vendor/orders", headers=h)
    assert listing.status_code == 200 and o["id"] in str(listing.json())
    assert c.get(f"/api/vendor/orders/{o['id']}", headers=h).status_code == 200
    assert c.post(f"/api/vendor/orders/{o['id']}/fulfilment", json={"status": "accepted", "note": ""}, headers=h).status_code == 200
    assert c.get("/api/vendor/returns", headers=h).status_code == 200
    assert c.get("/api/vendor/products", headers=h).status_code == 403                  # selling stays closed
    assert c.post("/api/vendor/products", json={"sku": "NEW-9", "name": "New", "mrp": 100, "selling_price": 90, "category": "Sarees"},
                  headers=h).status_code == 403


def test_every_api_response_carries_security_headers(c):
    r = c.get("/api/health")
    for k in ("X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy", "Permissions-Policy"):
        assert k in r.headers, k
    assert r.headers["X-Frame-Options"] == "DENY" and r.headers["X-Content-Type-Options"] == "nosniff"
    assert "Strict-Transport-Security" in c.get("/api/health", headers={"x-forwarded-proto": "https"}).headers


def test_an_unhandled_error_is_a_json_500_with_an_error_id_and_cors_headers(c):
    r = c.get("/api/__test_boom", headers={"Origin": ORIGIN})
    assert r.status_code == 500
    body = r.json()
    assert body["error_id"] and "simulated" not in r.text and "Traceback" not in r.text
    assert r.headers.get("access-control-allow-origin") == ORIGIN
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_hot_lookup_indexes_exist_after_the_migration(c):
    names = {(s["coll"], s["name"]) for s in db_indexes.SPECS}
    for coll, name in (("users", "users_id"), ("orders", "orders_id"), ("products", "products_id"),
                       ("webhook_events", "webhook_events_event_unique"), ("revoked_tokens", "revoked_tokens_expires")):
        assert (coll, name) in names
        assert name in _run(c, lambda: db[coll].index_information()), name
