"""Batch 13, Phase 7 — customer address book and wishlist (customer_routes.py) and checkout address snapshots.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_customer_batch13.py -n 0`).
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_customer_b13_test", "JWT_SECRET": "customer13-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
A = {"label": "home", "full_name": "Asha Rao", "mobile": "9100016099", "line1": "12 MG Road", "line2": "Flat 4B", "locality": "Camp",
     "landmark": "Near the post office", "city": "Pune", "district": "Pune", "state": "Maharashtra", "pincode": "411001"}


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
            for key, role, status in (("a", "customer", "customer"), ("b", "customer", "customer"), ("m", "distributor", "green")):
                u = {"id": new_id(), "distributor_id": "C13" + key.upper(), "full_name": key, "mobile": f"91000160{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            for pid, extra in (("w1", {}), ("w2", {"variants": [{"sku": "W2-S", "attributes": {"size": "S"}, "stock": 3, "price": 900},
                                                                    {"sku": "W2-M", "attributes": {"size": "M"}, "stock": 0}], "stock": 3}),
                               ("w3", {"stock": 0}), ("w4", {"approval_status": "pending", "is_active": False})):
                await db.products.insert_one({"id": pid, "sku": pid.upper(), "name": f"Item {pid}", "images": [], "mrp": 1200, "selling_price": 1000,
                                              "gst_percent": 5, "stock": 10, "category": "Sarees", "options": [], "vendor_id": None,
                                              "is_active": True, "approval_status": "approved", "created_at": now_iso(), **extra})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _add(c, who="a", **over):
    r = c.post("/api/addresses", json={**A, **over}, headers=_hdr(who))
    assert r.status_code == 200, r.text
    return r.json()


def _list(c, who="a"):
    return c.get("/api/addresses", headers=_hdr(who)).json()["items"]


# ================================================================ address book
def test_validation_is_enforced_by_the_server(c):
    for bad in ({"mobile": "12345"}, {"mobile": "5100016099"}, {"pincode": "012345"}, {"pincode": "41100"}, {"state": "Atlantis"},
                {"full_name": " "}, {"line1": ""}, {"label": "office"}, {"country": "Nepal"}, {"line1": "<script>x</script>"}):
        r = c.post("/api/addresses", json={**A, **bad}, headers=_hdr("a"))
        assert r.status_code == 422, bad
    assert _add(c, mobile="+91 91000-16099")["mobile"] == "9100016099"          # normalised


def test_first_address_is_default_and_default_moves_correctly(c):
    first = _list(c, "b")
    assert first == []
    x = _add(c, "b", label="home")
    assert x["is_default"] is True
    y = _add(c, "b", label="work", line1="Office park 7")
    assert y["is_default"] is False
    rows = c.post(f"/api/addresses/{y['id']}/default", headers=_hdr("b")).json()["items"]
    assert [r["id"] for r in rows if r["is_default"]] == [y["id"]] and rows[0]["id"] == y["id"]
    rows = c.delete(f"/api/addresses/{y['id']}", headers=_hdr("b")).json()["items"]       # delete the default
    assert len(rows) == 1 and rows[0]["id"] == x["id"] and rows[0]["is_default"] is True
    rows = c.delete(f"/api/addresses/{x['id']}", headers=_hdr("b")).json()["items"]
    assert rows == [] and _run(c, lambda: db.users.find_one({"id": S["b"]["id"]}))["default_address_id"] is None
    assert c.delete(f"/api/addresses/{x['id']}", headers=_hdr("b")).status_code == 200      # idempotent


def test_concurrent_default_changes_leave_exactly_one_default(c):
    ids = [_add(c, "b", line1=f"House {i}")["id"] for i in range(4)]
    list(ThreadPoolExecutor(max_workers=4).map(lambda i: c.post(f"/api/addresses/{i}/default", headers=_hdr("b")), ids))
    assert sum(1 for r in _list(c, "b") if r["is_default"]) == 1


def test_customers_cannot_see_or_change_each_others_addresses(c):
    mine = _add(c, "a", line1="Private lane 1")
    for method, path, body in (("PUT", f"/api/addresses/{mine['id']}", A), ("DELETE", f"/api/addresses/{mine['id']}", None),
                               ("POST", f"/api/addresses/{mine['id']}/default", None)):
        assert c.request(method, path, json=body, headers=_hdr("b")).status_code == 404
    assert all(r["id"] != mine["id"] for r in _list(c, "b"))
    o = c.post("/api/orders", json={"items": [{"product_id": "w1", "quantity": 1}], "address_id": mine["id"], "payment_method": "cod"},
               headers=_hdr("b"))
    assert o.status_code == 404                                                     # cannot ship to someone else's address


def test_checkout_snapshots_the_address_and_later_edits_do_not_touch_the_order(c):
    a = _add(c, "a", line1="Snapshot road 5", landmark="Blue gate")
    r = c.post("/api/orders", json={"items": [{"product_id": "w1", "quantity": 1}], "address_id": a["id"], "payment_method": "cod"},
               headers=_hdr("a"))
    assert r.status_code == 200, r.text
    oid = r.json()["id"]
    snap = _run(c, lambda: db.orders.find_one({"id": oid}))["address"]
    assert snap["line1"] == "Snapshot road 5" and snap["landmark"] == "Blue gate" and snap["address_id"] == a["id"]
    assert c.put(f"/api/addresses/{a['id']}", json={**A, "line1": "Moved away 9"}, headers=_hdr("a")).status_code == 200
    c.delete(f"/api/addresses/{a['id']}", headers=_hdr("a"))
    assert _run(c, lambda: db.orders.find_one({"id": oid}))["address"]["line1"] == "Snapshot road 5"
    assert c.post("/api/orders", json={"items": [{"product_id": "w1", "quantity": 1}], "address_id": a["id"], "payment_method": "cod"},
                  headers=_hdr("a")).status_code == 404                              # deleted address cannot be used again


def test_a_typed_checkout_address_is_validated(c):
    base = {"items": [{"product_id": "w1", "quantity": 1}], "payment_method": "cod"}
    bad = {"full_name": "X Y", "mobile": "123", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
    assert c.post("/api/orders", json={**base, "address": bad}, headers=_hdr("a")).status_code == 422
    assert c.post("/api/orders", json={**base, "address": {**bad, "mobile": "9100016001", "pincode": "4110"}}, headers=_hdr("a")).status_code == 422
    assert c.post("/api/orders", json=base, headers=_hdr("a")).status_code in (400, 422)                 # no address at all
    assert c.post("/api/orders", json={**base, "address": {**bad, "mobile": "9100016001"}}, headers=_hdr("a")).status_code == 200


# ================================================================ wishlist
def _wish(c, who="a"):
    return c.get("/api/wishlist", headers=_hdr(who)).json()["items"]


def test_wishlist_add_is_idempotent_even_when_concurrent_and_remove_is_idempotent(c):
    codes = list(ThreadPoolExecutor(max_workers=5).map(lambda _: c.post("/api/wishlist", json={"product_id": "w1"}, headers=_hdr("a")).status_code, range(5)))
    assert codes == [200] * 5 and len([i for i in _wish(c) if i["product_id"] == "w1"]) == 1
    assert c.delete("/api/wishlist/w1", headers=_hdr("a")).json()["removed"] is True
    assert c.delete("/api/wishlist/w1", headers=_hdr("a")).json()["removed"] is False
    assert all(i["product_id"] != "w1" for i in _wish(c))


def test_only_products_on_sale_can_be_saved_and_variants_must_exist(c):
    assert c.post("/api/wishlist", json={"product_id": "w4"}, headers=_hdr("a")).status_code == 404       # not approved
    assert c.post("/api/wishlist", json={"product_id": "nope"}, headers=_hdr("a")).status_code == 404
    assert c.post("/api/wishlist", json={"product_id": "w2", "variant_sku": "W2-XL"}, headers=_hdr("a")).status_code == 400


def test_wishlist_shows_the_live_state_price_changes_and_never_makes_unavailable_items_buyable(c):
    for body in ({"product_id": "w2"}, {"product_id": "w2", "variant_sku": "w2-s"}, {"product_id": "w2", "variant_sku": "W2-M"},
                 {"product_id": "w3"}, {"product_id": "w1"}):
        assert c.post("/api/wishlist", json=body, headers=_hdr("m")).status_code == 200, body
    _run(c, lambda: db.products.update_one({"id": "w1"}, {"$set": {"selling_price": 950}}))
    items = {(i["product_id"], i["variant_sku"]): i for i in _wish(c, "m")}
    assert items[("w2", "")]["status"] == "choose_variant"
    assert items[("w2", "W2-S")]["status"] == "available" and items[("w2", "W2-S")]["price"] == 900
    assert items[("w2", "W2-M")]["status"] == "out_of_stock"
    assert items[("w3", "")]["status"] == "out_of_stock"
    assert items[("w1", "")]["price_change"] == "down" and items[("w1", "")]["price_at_add"] == 1000
    _run(c, lambda: db.products.update_one({"id": "w1"}, {"$set": {"archived": True}}))
    gone = next(i for i in _wish(c, "m") if i["product_id"] == "w1")
    assert gone["status"] == "unavailable" and gone["product"] is None and gone["name"] == "Item w1"
    r = c.post("/api/orders", json={"items": [{"product_id": "w1", "quantity": 1}], "address": {**A, "state": "MH"}, "payment_method": "cod"},
               headers=_hdr("m"))
    assert r.status_code in (400, 404)                                                # still not purchasable
    _run(c, lambda: db.products.update_one({"id": "w1"}, {"$set": {"archived": False, "selling_price": 1000}}))


def test_wishlists_are_private(c):
    c.post("/api/wishlist", json={"product_id": "w1"}, headers=_hdr("a"))
    assert all(i["product_id"] != "w1" or False for i in _wish(c, "b"))
    assert c.delete("/api/wishlist/w1", headers=_hdr("b")).json()["removed"] is False
    assert any(i["product_id"] == "w1" for i in _wish(c, "a"))
    assert c.get("/api/wishlist").status_code == 401
