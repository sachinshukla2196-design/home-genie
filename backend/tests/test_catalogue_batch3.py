"""Batch 3 — catalogue and inventory: CAT-01 (variant purchase), CAT-02 (per-line GST/HSN snapshot, totals unchanged),
CAT-03 (no stale stock overwrites: admin edit and vendor variant edit), CAT-04 (archived products never sold), CAT-05 (sticky
admin takedown), CAT-06 (admin product validation), CAT-07 (case-insensitive SKU uniqueness), CAT-08 (real image types).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_catalogue_batch3.py -n 0`).
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_catalogue_batch3_test", "JWT_SECRET": "batch3-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
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

            async def user(key, mobile, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": did, "mobile": mobile, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("cust", "9100003001", "distributor", "B3CUST")
            await user("super", "9100003002", "super_admin", "B3SUPER")
            await user("admin", "9100003003", "admin", "B3ADMIN")
            await user("sup", "9100003004", "support_admin", "B3SUP")
            await user("vu", "9100003005", "vendor", "B3VEND")
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "B3VEND", "business_name": "Vendor B3",
                      "status": "approved", "categories": ["Sarees", "Fashion Products"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


BASE = {"name": "Platform Saree", "mrp": 1000, "selling_price": 800, "gst_percent": 5, "category": "Sarees", "stock": 10}


def _admin_create(c, sku, **kw):
    return c.post("/api/admin/products", json={**BASE, "sku": sku, **kw}, headers=_hdr("admin"))


def _get(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}, {"_id": 0}))


def _vendor_product(c, sku, variants=None, **kw):
    body = {"sku": sku, "name": f"Vendor {sku}", "mrp": 1200, "selling_price": 1000, "category": "Fashion Products", "stock": 10, **kw}
    if variants:
        body["variants"] = variants
    r = c.post("/api/vendor/products", headers=_hdr("vu"), json=body)
    assert r.status_code == 200, r.text
    p = r.json()
    assert c.post(f"/api/admin/vendor-products/{p['id']}/decision", headers=_hdr("admin"), json={"action": "approve"}).status_code == 200
    return _get(c, p["id"]), body


def _order(c, items):
    return c.post("/api/orders", json={"items": items, "address": ADDR, "payment_method": "online"}, headers=_hdr("cust"))


# ================================================================ CAT-06 / CAT-07: admin product validation and SKUs
@pytest.mark.parametrize("bad", [{"selling_price": 1200}, {"mrp": 0}, {"selling_price": -5}, {"gst_percent": 40},
                                 {"category": "Electronics"}, {"hsn_code": "12AB"}, {"images": ["javascript:alert(1)"]},
                                 {"images": ["http://insecure.example/x.jpg"]}, {"stock": -1}, {"name": "x"}])
def test_invalid_admin_products_are_refused(c, bad):
    r = _admin_create(c, "BAD-1", **bad)
    assert r.status_code in (400, 422), (bad, r.text)
    assert not _run(c, lambda: db.products.find_one({"sku": "BAD-1"}))


def test_sku_is_upper_cased_and_unique_without_regard_to_case_or_variants(c):
    r = _admin_create(c, "plat-1", hsn_code="5007")
    assert r.status_code == 200 and r.json()["sku"] == "PLAT-1" and r.json()["hsn_code"] == "5007"
    assert _admin_create(c, "Plat-1").status_code == 400
    _vendor_product(c, "VSKU-1", variants=[{"sku": "VAR-X", "attributes": {"size": "S"}, "stock": 2}])
    assert _admin_create(c, "var-x").status_code == 400                          # clashes with a vendor's variant SKU


def test_opening_stock_is_journaled(c):
    p = _admin_create(c, "PLAT-J", stock=7).json()
    mv = _run(c, lambda: db.stock_movements.find_one({"product_id": p["id"]}))
    assert mv["delta"] == 7 and mv["reason"] == "initial_stock"


# ================================================================ CAT-03: stock is never overwritten by an edit
def test_admin_edit_never_writes_stock_and_adjustments_are_atomic(c):
    p = _admin_create(c, "PLAT-S", stock=10).json()
    _run(c, lambda: db.products.update_one({"id": p["id"]}, {"$inc": {"stock": -3}}))          # an order reserved 3 meanwhile
    r = c.put(f"/api/admin/products/{p['id']}", json={**BASE, "sku": "PLAT-S", "name": "Renamed", "stock": 10}, headers=_hdr("admin"))
    assert r.status_code == 200
    got = _get(c, p["id"])
    assert got["name"] == "Renamed" and got["stock"] == 7                                       # the stale 10 was not written
    assert c.post(f"/api/admin/products/{p['id']}/stock", json={"delta": -8, "reason": "Recount"}, headers=_hdr("admin")).status_code == 409
    ok = c.post(f"/api/admin/products/{p['id']}/stock", json={"delta": -2, "reason": "Damaged units"}, headers=_hdr("admin"))
    assert ok.status_code == 200 and ok.json()["stock"] == 5
    assert _run(c, lambda: db.stock_movements.find_one({"product_id": p["id"], "reason": "Damaged units"}))["delta"] == -2
    assert c.post(f"/api/admin/products/{p['id']}/stock", json={"delta": 0, "reason": "none"}, headers=_hdr("admin")).status_code == 400


def test_vendor_stock_is_not_adjustable_from_the_admin_catalogue(c):
    vp, _ = _vendor_product(c, "VSKU-2")
    assert c.post(f"/api/admin/products/{vp['id']}/stock", json={"delta": 5, "reason": "x-fix"}, headers=_hdr("admin")).status_code == 409


def test_vendor_variant_edit_never_overwrites_a_concurrent_reservation(c):
    import vendor_routes
    vp, body = _vendor_product(c, "VSKU-3", variants=[{"sku": "V3-S", "attributes": {"size": "S"}, "stock": 5},
                                                     {"sku": "V3-M", "attributes": {"size": "M"}, "stock": 5}])
    real = vendor_routes._own_product
    state = {"n": 0}

    async def racing(user, product_id):
        doc = await real(user, product_id)
        state["n"] += 1
        if state["n"] == 1:                                   # a customer reserves 2 units of V3-S right after the edit's read
            await db.products.update_one({"id": product_id, "variants.sku": "V3-S"}, {"$inc": {"variants.$.stock": -2, "stock": -2}})
        return doc
    vendor_routes._own_product = racing
    try:
        r = c.put(f"/api/vendor/products/{vp['id']}", headers=_hdr("vu"),
                  json={**body, "description": "Edited description", "variants": [{"sku": "V3-S", "attributes": {"size": "S"}},
                                                                                  {"sku": "V3-M", "attributes": {"size": "M"}}]})
    finally:
        vendor_routes._own_product = real
    assert r.status_code == 200, r.text
    got = _get(c, vp["id"])
    stock = {v["sku"]: v["stock"] for v in got["variants"]}
    assert stock == {"V3-S": 3, "V3-M": 5} and got["stock"] == 8 and got["description"] == "Edited description"


# ================================================================ CAT-01 / CAT-02: buying a variant
def test_variant_is_bought_by_its_sku_at_its_price_with_tax_data_snapshotted(c):
    vp, _ = _vendor_product(c, "VSKU-4", variants=[{"sku": "V4-S", "attributes": {"size": "S"}, "stock": 4, "price": 700},
                                                   {"sku": "V4-M", "attributes": {"size": "M"}, "stock": 4}], hsn_code="6204", gst_percent=12)
    assert _order(c, [{"product_id": vp["id"], "quantity": 1}]).status_code == 400                     # a variant must be chosen
    r = _order(c, [{"product_id": vp["id"], "quantity": 2, "variant_sku": "V4-S", "variant": "S"}])
    assert r.status_code == 200, r.text
    line = r.json()["items"][0]
    assert line["variant_sku"] == "V4-S" and line["price"] == 700
    assert line["product_gst_percent"] == 12 and line["hsn_code"] == "6204"
    stock = {v["sku"]: v["stock"] for v in _get(c, vp["id"])["variants"]}
    assert stock == {"V4-S": 2, "V4-M": 4}


def test_prices_include_the_products_own_gst_rate(c):
    """Decision 1: shelf prices are GST-inclusive. The product's own rate is taken OUT of the price, never added on top."""
    p = _admin_create(c, "PLAT-T", gst_percent=18).json()
    o = _order(c, [{"product_id": p["id"], "quantity": 1}]).json()
    line = o["items"][0]
    assert o["total"] == 800.0 and o["prices_include_gst"] is True                 # the customer pays the shelf price
    assert line["gst_rate"] == 18 and line["taxable_paise"] == 67797 and line["gst_paise"] == 12203   # 800 x 100/118 = 677.966
    assert o["subtotal_paise"] == 67797 and o["gst_paise"] == 12203 and o["gst_percent"] == 18


def test_mixed_rates_add_up_exactly_and_report_no_single_rate(c):
    a = _admin_create(c, "PLAT-M5", gst_percent=5).json()
    b = _admin_create(c, "PLAT-M12", gst_percent=12, selling_price=499.99, mrp=600).json()
    o = _order(c, [{"product_id": a["id"], "quantity": 3}, {"product_id": b["id"], "quantity": 1}]).json()
    assert o["gst_percent"] is None
    assert o["total_paise"] == 3 * 80000 + 49999
    assert o["subtotal_paise"] + o["gst_paise"] == o["total_paise"]
    assert sum(li["taxable_paise"] for li in o["items"]) == o["subtotal_paise"]
    assert all(li["taxable_paise"] + li["gst_paise"] == li["total_paise"] for li in o["items"])


def test_cod_fee_is_added_outside_the_gst_split(c):
    _run(c, lambda: db.business_settings.update_one({"id": "business_settings"}, {"$set": {"cod_enabled": True, "cod_fee": 25.0}}, upsert=True))
    p = _admin_create(c, "PLAT-COD", gst_percent=5).json()
    r = c.post("/api/orders", json={"items": [{"product_id": p["id"], "quantity": 1}], "address": ADDR, "payment_method": "cod"},
               headers=_hdr("cust"))
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["total_paise"] == 80000 + 2500 and o["subtotal_paise"] + o["gst_paise"] == 80000


# ================================================================ CAT-04 / CAT-05: archived and taken-down products
def test_archived_products_are_never_shown_relisted_or_sold(c):
    vp, _ = _vendor_product(c, "VSKU-5")
    assert c.post(f"/api/vendor/products/{vp['id']}/archive", headers=_hdr("vu"), json={"archived": True}).status_code == 200
    assert c.post(f"/api/vendor/products/{vp['id']}/listing", headers=_hdr("vu"), json={"active": True}).status_code == 409
    _run(c, lambda: db.products.update_one({"id": vp["id"]}, {"$set": {"is_active": True}}))     # even if data says listed...
    assert vp["id"] not in [x["id"] for x in c.get("/api/products").json()]
    assert c.get(f"/api/products/{vp['id']}").status_code == 404
    assert _order(c, [{"product_id": vp["id"], "quantity": 1}]).status_code == 400


def test_inactive_products_are_not_public(c):
    p = _admin_create(c, "PLAT-H", is_active=False).json()
    assert c.get(f"/api/products/{p['id']}").status_code == 404
    assert p["id"] not in [x["id"] for x in c.get("/api/products?active=false").json()]          # the old public switch is gone


def test_admin_takedown_is_sticky_until_lifted(c):
    vp, _ = _vendor_product(c, "VSKU-6")
    assert c.delete(f"/api/admin/products/{vp['id']}", params={"reason": "Counterfeit report"}, headers=_hdr("sup")).status_code == 403
    assert c.delete(f"/api/admin/products/{vp['id']}", params={"reason": "Counterfeit report"}, headers=_hdr("admin")).status_code == 200
    assert _get(c, vp["id"])["admin_takedown"]["reason"] == "Counterfeit report"
    assert c.post(f"/api/vendor/products/{vp['id']}/listing", headers=_hdr("vu"), json={"active": True}).status_code == 409
    assert c.post(f"/api/admin/products/{vp['id']}/takedown/lift", headers=_hdr("sup")).status_code == 403
    assert c.post(f"/api/admin/products/{vp['id']}/takedown/lift", headers=_hdr("admin")).status_code == 200
    assert c.post(f"/api/vendor/products/{vp['id']}/listing", headers=_hdr("vu"), json={"active": True}).status_code == 200


# ================================================================ admin product list
def test_admin_product_list_is_paginated_searchable_and_admin_only(c):
    assert c.get("/api/admin/products", headers=_hdr("cust")).status_code == 403
    r = c.get("/api/admin/products", params={"q": "plat-", "page_size": 2}, headers=_hdr("sup")).json()
    assert r["total"] >= 4 and len(r["items"]) == 2 and r["pages"] >= 2
    assert all("stock_ops" not in x for x in r["items"])
    owner = c.get("/api/admin/products", params={"owner": "vendor"}, headers=_hdr("sup")).json()["items"]
    assert owner and all(x.get("vendor_id") for x in owner)


# ================================================================ CAT-08: image type from the bytes
def test_image_type_is_taken_from_the_file_bytes():
    from storage import sniff_image_type
    assert sniff_image_type(b"\xff\xd8\xff\xe0" + b"0" * 20) == "image/jpeg"
    assert sniff_image_type(b"\x89PNG\r\n\x1a\n" + b"0" * 20) == "image/png"
    assert sniff_image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert sniff_image_type(b"<svg xmlns='http://www.w3.org/2000/svg'><script>") == ""
    assert sniff_image_type(b"GIF89a....") == ""
