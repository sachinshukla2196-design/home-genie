"""Batch 13, Phase 9 — admin order operations (admin_order_ops.py): paged / filtered list, authorised export, and an order detail
that shows each vendor's part separately and never treats an admin status change as a delivery.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_admin_order_ops_b13.py -n 0`).
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_order_ops_b13_test", "JWT_SECRET": "orderops13-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Kavya Nair", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role in (("super", "super_admin"), ("admin", "admin"), ("fin", "accounts_admin"), ("sup", "support_admin"),
                              ("cust", "customer"), ("va", "vendor"), ("vb", "vendor")):
                u = {"id": new_id(), "distributor_id": "OO" + key.upper(), "full_name": "Kavya Nair" if key == "cust" else key,
                     "mobile": f"91000180{len(S):02d}", "email": f"{key}@example.com", "password_hash": hash_password("Pass-1234x"),
                     "role": role, "status": "green", "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            for k, owner in (("A", "va"), ("B", "vb")):
                S["v" + k] = {"id": new_id(), "user_id": S[owner]["id"], "vendor_code": "OOV" + k, "business_name": f"Vendor {k}",
                              "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(S["v" + k]))
                await db.products.insert_one({"id": "pp" + k, "sku": "OO-" + k, "name": f"Saree {k}", "images": [], "mrp": 1200,
                                              "selling_price": 1050, "gst_percent": 5, "stock": 100, "category": "Sarees", "options": [],
                                              "vendor_id": S["v" + k]["id"], "vendor_name": f"Vendor {k}", "is_active": True,
                                              "approval_status": "approved", "created_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _order(c, items, method="online", pay=True):
    o = c.post("/api/orders", json={"items": [{"product_id": p, "quantity": q} for p, q in items], "address": ADDR, "payment_method": method},
               headers=_hdr("cust")).json()
    if pay and method == "online":
        sid = "cs_" + o["id"][:12]
        _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                            "amount": o["total"], "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
        _run(c, lambda: shop_routes._process_paid_order(sid))
    return o


def _step(c, who, oid, *steps):
    for st in steps:
        r = c.post(f"/api/vendor/orders/{oid}/fulfilment", json={"status": st, "note": "Handed to customer" if st == "delivered" else "",
                                                                "carrier": "BlueDart", "tracking_number": "BD7"}, headers=_hdr(who))
        assert r.status_code == 200, r.text


def test_multi_vendor_detail_shows_each_vendor_separately_and_admin_status_is_not_a_delivery(c):
    o = _order(c, [("ppA", 1), ("ppB", 2)])
    _step(c, "va", o["id"], "accepted", "packed", "dispatched", "delivered")
    assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "delivered", "reason": "Customer called to confirm"},
                 headers=_hdr("admin")).status_code == 200
    d = c.get(f"/api/admin/order-ops/orders/{o['id']}", headers=_hdr("sup")).json()
    v = {x["vendor_name"]: x for x in d["vendors"]}
    assert v["Vendor A"]["status"] == "delivered" and v["Vendor A"]["delivered_at"] and v["Vendor A"]["delivery_evidence"] == "Handed to customer"
    assert v["Vendor B"]["delivered_at"] is None and v["Vendor B"]["payout_block"] == "not_delivered"
    assert v["Vendor A"]["goods_paise"] == 105000 and v["Vendor B"]["goods_paise"] == 210000
    assert v["Vendor A"]["ledger_net_paise"] == 105000 and v["Vendor B"]["lines"] == [1]
    assert d["delivery"]["order_delivered_at"] is None and d["order"]["status_set_by_admin"]["by"] == S["admin"]["id"]
    assert any(a["action"] == "order_status_changed" and a["new_value"]["reason"] == "Customer called to confirm" for a in d["audit"])
    assert d["customer"]["mobile"] == S["cust"]["mobile"] and d["payments"] and d["address"]["line1"] == "1 Road"


def test_finance_sees_customer_contact_masked(c):
    o = _order(c, [("ppA", 1)])
    d = c.get(f"/api/admin/order-ops/orders/{o['id']}", headers=_hdr("fin")).json()["customer"]
    assert d["masked"] is True and d["mobile"].endswith(S["cust"]["mobile"][-4:]) and d["mobile"] != S["cust"]["mobile"] and "•" in d["email"]


def test_list_is_paged_filtered_and_sorted_on_the_server(c):
    cod = _order(c, [("ppB", 1)], method="cod")
    unpaid = _order(c, [("ppA", 1)], pay=False)
    h = _hdr("admin")
    r = c.get("/api/admin/order-ops/orders", params={"page_size": 2}, headers=h).json()
    assert r["total"] >= 4 and len(r["items"]) == 2 and r["pages"] >= 2
    assert all(x["payment_method"] == "cod" for x in c.get("/api/admin/order-ops/orders", params={"method": "cod"}, headers=h).json()["items"])
    ids = [x["id"] for x in c.get("/api/admin/order-ops/orders", params={"vendor_id": S["vB"]["id"]}, headers=h).json()["items"]]
    assert cod["id"] in ids and unpaid["id"] not in ids
    assert [x["id"] for x in c.get("/api/admin/order-ops/orders", params={"q": unpaid["order_number"]}, headers=h).json()["items"]] == [unpaid["id"]]
    assert c.get("/api/admin/order-ops/orders", params={"q": "Kavya"}, headers=h).json()["total"] >= 4
    totals = [x["total_paise"] for x in c.get("/api/admin/order-ops/orders", params={"sort": "total", "order": "asc"}, headers=h).json()["items"]]
    assert totals == sorted(totals)
    row = c.get("/api/admin/order-ops/orders", params={"q": cod["order_number"]}, headers=h).json()["items"][0]
    assert "•" in row["customer"]["mobile"] and "address" not in row
    assert c.get("/api/admin/order-ops/orders", params={"refund": "bogus"}, headers=h).status_code == 400
    assert c.get("/api/admin/order-ops/orders", params={"payment_status": "pending"}, headers=h).json()["total"] >= 1


def test_export_is_for_authorised_roles_masked_and_audited(c):
    assert c.get("/api/admin/order-ops/orders.csv", headers=_hdr("sup")).status_code == 403
    r = c.get("/api/admin/order-ops/orders.csv", headers=_hdr("fin"))
    assert r.status_code == 200 and r.text.startswith("order_number,") and "1 Road" not in r.text and S["cust"]["mobile"] not in r.text
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "orders_exported"})) == 1


def test_only_admins_reach_order_operations(c):
    assert c.get("/api/admin/order-ops/orders", headers=_hdr("cust")).status_code == 403
    assert c.get("/api/admin/order-ops/orders", headers=_hdr("va")).status_code == 403
    assert c.get("/api/admin/order-ops/orders/nope", headers=_hdr("admin")).status_code == 404
