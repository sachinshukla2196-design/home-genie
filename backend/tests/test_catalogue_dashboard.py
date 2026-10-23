"""Catalogue (attributes, variants, archive, sorting, CSV) and the aggregation-based dashboard.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_catalogue_test", "JWT_SECRET": "catalogue-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
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
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": status, "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                return u

            async def vendor(u, name):
                v = {"id": new_id(), "user_id": u["id"], "vendor_code": u["distributor_id"], "business_name": name, "status": "approved",
                     "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(v))
                return v
            S["cust"], S["admin"] = await user("9100000801", "distributor", "HGC", "red"), await user("9100000802", "super_admin", "HGADM")
            S["ua"], S["ub"] = await user("9100000803", "vendor", "VDA"), await user("9100000804", "vendor", "VDB")
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A"), await vendor(S["ub"], "Vendor B")
            await db.business_settings.update_one({"id": "business_settings"}, {"$set": {"gst_percent": 5.0, "cod_fee": 0.0}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _body(sku, **kw):
    b = {"sku": sku, "name": f"Product {sku}", "mrp": 1000, "selling_price": 800, "category": "Sarees", "stock": 10}
    b.update(kw)
    return b


def _post(c, vkey, body):
    return c.post("/api/vendor/products", headers=_hdr(S[vkey]["id"]), json=body)


def _approve(c, pid):
    c.portal.call(lambda: db.products.update_one({"id": pid}, {"$set": {"approval_status": "approved", "is_active": True}}))


def _prod(c, pid):
    return c.portal.call(lambda: db.products.find_one({"id": pid}))


# ====================================================================== attributes + package
def test_attributes_are_validated_per_pillar_and_irrelevant_fields_are_rejected(c):
    ok = _post(c, "ua", _body("AT-1", attributes={"fabric": "Silk", "weave_style": "Banarasi", "colour": "Maroon", "length_m": 6.3}))
    assert ok.status_code == 200 and ok.json()["attributes"]["fabric"] == "Silk"
    bad = _post(c, "ua", _body("AT-2", attributes={"ingredients": "Water"}))                       # a skincare field on a saree
    assert bad.status_code == 400 and "not a field for Sarees" in bad.json()["detail"]
    skin = _post(c, "ua", _body("AT-3", category="Makeup, Beauty & Skincare", attributes={"ingredients": "Aqua", "expiry_date": "2027-03-31", "net_quantity": "50 ml"}))
    assert skin.status_code == 200
    assert _post(c, "ua", _body("AT-4", category="Makeup, Beauty & Skincare", attributes={"expiry_date": "31/03/2027"})).status_code == 400
    assert _post(c, "ua", _body("AT-5", category="Household Essentials", attributes={"weight_g": "heavy"})).status_code == 400
    assert _post(c, "ua", _body("AT-6", category="Household Essentials", attributes={"weight_g": -5})).status_code == 400
    assert _post(c, "ua", _body("AT-7", attributes={"fabric": "x" * 61})).status_code == 400
    assert _post(c, "ua", _body("AT-8", category="Electronics")).status_code == 400                 # pillars are locked
    pkg = _post(c, "ua", _body("AT-9", package={"weight_g": 700, "length_cm": 30, "fragile": True, "handling_days": 2}))
    assert pkg.status_code == 200 and pkg.json()["package"]["handling_days"] == 2
    assert _post(c, "ua", _body("AT-10", package={"weight_g": -1})).status_code == 400
    assert _post(c, "ua", _body("AT-11", package={"handling_days": 90})).status_code == 400


def test_compliance_documents_start_as_submitted_never_verified_and_urls_are_checked(c):
    doc = {"type": "test_report", "url": "https://cdn.example.com/lab.pdf", "status": "verified", "note": "lab"}
    r = _post(c, "ua", _body("DC-1", compliance_documents=[doc]))
    assert r.status_code == 200 and r.json()["compliance_documents"][0]["status"] == "submitted"     # a vendor cannot self-verify
    assert _post(c, "ua", _body("DC-2", compliance_documents=[{"type": "test_report", "url": "javascript:alert(1)"}])).status_code == 400
    assert _post(c, "ua", _body("DC-3", compliance_documents=[{"type": "nonsense", "url": "https://x.example/a.pdf"}])).status_code == 400


# ====================================================================== variants + inventory
def _variants():
    return [{"sku": "VR-S", "attributes": {"size": "S"}, "stock": 3, "price": 700},
            {"sku": "VR-M", "attributes": {"size": "M"}, "stock": 5}]


def test_variants_have_their_own_sku_price_and_stock_and_product_stock_is_their_sum(c):
    r = _post(c, "ua", _body("VP-1", category="Fashion Products", variants=_variants(), stock=999))
    assert r.status_code == 200
    p = r.json()
    assert p["stock"] == 8 and {v["sku"]: v["stock"] for v in p["variants"]} == {"VR-S": 3, "VR-M": 5}       # the 999 was ignored
    assert _post(c, "ua", _body("VP-2", variants=_variants())).status_code == 400                           # variant SKUs already exist
    assert _post(c, "ub", _body("VP-3", variants=_variants())).status_code == 400                           # ...also across vendors
    assert _post(c, "ua", _body("VP-4", variants=[{"sku": "X1", "attributes": {"size": "S"}}, {"sku": "X1", "attributes": {"size": "M"}}])).status_code == 400
    assert _post(c, "ua", _body("VP-5", variants=[{"sku": "VP-5", "attributes": {"size": "S"}}])).status_code == 400   # same as the product SKU
    assert _post(c, "ua", _body("VP-6", variants=[{"sku": "Y1", "attributes": {}}])).status_code == 400
    assert _post(c, "ua", _body("VP-7", variants=[{"sku": "Y2", "attributes": {"shape": "round"}}])).status_code == 400
    assert _post(c, "ua", _body("VP-8", variants=[{"sku": "Y3", "attributes": {"size": "S"}, "price": 5000, "mrp": 100}])).status_code == 400
    mv = c.portal.call(lambda: db.stock_movements.find({"product_id": p["id"]}).to_list(10))
    assert sorted((m["variant_sku"], m["delta"]) for m in mv) == [("VR-M", 5), ("VR-S", 3)]


def test_editing_variants_keeps_stock_blocks_removal_with_stock_and_resubmits_on_price_changes(c):
    p = _post(c, "ua", _body("VE-1", category="Fashion Products", variants=[{"sku": "VE-1-S", "attributes": {"size": "S"}, "stock": 4}])).json()
    _approve(c, p["id"])
    h = _hdr(S["ua"]["id"])
    put = lambda body: c.put(f"/api/vendor/products/{p['id']}", headers=h, json=body)
    same = _body("VE-1", category="Fashion Products", variants=[{"sku": "VE-1-S", "attributes": {"size": "S"}, "stock": 99}])
    r = put(same)
    assert r.status_code == 200 and r.json()["variants"][0]["stock"] == 4                         # payload stock ignored for an existing variant
    assert r.json()["approval_status"] == "approved"                                             # not a material change
    r = put(_body("VE-1", category="Fashion Products", variants=[{"sku": "VE-1-S", "attributes": {"size": "S"}, "price": 650}]))
    assert r.json()["approval_status"] == "pending" and r.json()["is_active"] is False            # price change -> admin review again
    assert put(_body("VE-1", category="Fashion Products", variants=[])).status_code == 400        # cannot drop variants that hold stock
    assert put(_body("VE-1", category="Fashion Products", variants=[{"sku": "VE-1-M", "attributes": {"size": "M"}, "stock": 2}])).status_code == 400
    r = put(_body("VE-1", category="Fashion Products", variants=[{"sku": "VE-1-S", "attributes": {"size": "S"}}, {"sku": "VE-1-L", "attributes": {"size": "L"}, "stock": 2}]))
    assert r.status_code == 200 and r.json()["stock"] == 6                                       # new variant brings its opening stock


def test_variant_stock_adjustments_are_atomic_reasoned_and_isolated(c):
    p = _post(c, "ua", _body("VS-1", category="Fashion Products", variants=[{"sku": "VS-1-S", "attributes": {"size": "S"}, "stock": 4}])).json()
    ha, hb = _hdr(S["ua"]["id"]), _hdr(S["ub"]["id"])
    url = f"/api/vendor/products/{p['id']}/stock"
    assert c.post(url, headers=ha, json={"delta": 1, "reason": "recount"}).status_code == 400                 # which variant?
    assert c.post(url, headers=ha, json={"delta": 1, "reason": "recount", "variant_sku": "NOPE"}).status_code == 404
    assert c.post(url, headers=ha, json={"delta": -9, "reason": "damaged", "variant_sku": "VS-1-S"}).status_code == 400
    assert c.post(url, headers=hb, json={"delta": 5, "reason": "not mine", "variant_sku": "VS-1-S"}).status_code == 404
    assert c.post(url, headers=ha, json={"delta": 2, "reason": "new batch", "variant_sku": "vs-1-s"}).status_code == 200
    d = _prod(c, p["id"])
    assert d["variants"][0]["stock"] == 6 and d["stock"] == 6
    last = c.get(f"/api/vendor/products/{p['id']}/stock-history", headers=ha).json()[0]
    assert (last["variant_sku"], last["delta"], last["before"], last["after"]) == ("VS-1-S", 2, 4, 6)
    with ThreadPoolExecutor(max_workers=6) as ex:
        codes = list(ex.map(lambda _: c.post(url, headers=ha, json={"delta": -2, "reason": "sold offline", "variant_sku": "VS-1-S"}).status_code, range(6)))
    assert codes.count(200) == 3 and codes.count(400) == 3 and _prod(c, p["id"])["variants"][0]["stock"] == 0     # never negative


def test_orders_require_a_variant_use_its_price_and_cannot_oversell_it(c):
    p = _post(c, "ua", _body("VO-1", category="Fashion Products", selling_price=900,
                             variants=[{"sku": "VO-1-S", "attributes": {"size": "S"}, "stock": 2, "price": 700}, {"sku": "VO-1-M", "attributes": {"size": "M"}, "stock": 5}])).json()
    _approve(c, p["id"])
    order = lambda **it: c.post("/api/orders", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": p["id"], "quantity": 1, **it}], "address": ADDR, "payment_method": "cod"})
    assert order().status_code == 400 and "choose an option" in order().json()["detail"]
    assert order(variant_sku="NOPE").status_code == 400
    s = order(variant_sku="VO-1-S")
    assert s.status_code == 200 and s.json()["items"][0]["price_paise"] == 70000 and s.json()["items"][0]["variant"] == "size: S"      # variant price
    m = order(variant_sku="VO-1-M")
    assert m.json()["items"][0]["price_paise"] == 90000                                                                               # falls back to the product price
    assert order(variant_sku="VO-1-S").status_code == 200 and order(variant_sku="VO-1-S").status_code == 409                            # S sold out
    d = _prod(c, p["id"])
    assert {v["sku"]: v["stock"] for v in d["variants"]} == {"VO-1-S": 0, "VO-1-M": 4} and d["stock"] == 4
    plain = _post(c, "ua", _body("VO-2")).json()
    _approve(c, plain["id"])
    r = c.post("/api/orders", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": plain["id"], "quantity": 1, "variant_sku": "X"}], "address": ADDR, "payment_method": "cod"})
    assert r.status_code == 400 and "no variants" in r.json()["detail"]


def test_each_product_has_its_own_low_stock_threshold(c):
    a = _post(c, "ua", _body("LT-1", stock=8, low_stock_threshold=10)).json()
    b = _post(c, "ua", _body("LT-2", stock=8, low_stock_threshold=2)).json()
    h = _hdr(S["ua"]["id"])
    low = [x["sku"] for x in c.get("/api/vendor/products?page=1&stock=low&page_size=100", headers=h).json()["items"]]
    assert "LT-1" in low and "LT-2" not in low


# ====================================================================== archive, sort, filter
def test_archived_products_leave_the_shop_and_lists_and_can_be_restored_paused(c):
    p = _post(c, "ua", _body("AR-1")).json()
    _approve(c, p["id"])
    h = _hdr(S["ua"]["id"])
    assert any(x["id"] == p["id"] for x in c.get("/api/products").json())
    assert c.post(f"/api/vendor/products/{p['id']}/archive", headers=h, json={"archived": True}).json()["archived"] is True
    assert not any(x["id"] == p["id"] for x in c.get("/api/products").json())
    assert p["id"] not in [x["id"] for x in c.get("/api/vendor/products", headers=h).json()]
    page = c.get("/api/vendor/products?page=1&archived=true&page_size=100", headers=h).json()
    assert p["id"] in [x["id"] for x in page["items"]] and page["counts"]["archived"] >= 1
    assert c.put(f"/api/vendor/products/{p['id']}", headers=h, json=_body("AR-1")).status_code == 409
    assert c.post(f"/api/vendor/products/{p['id']}/archive", headers=_hdr(S["ub"]["id"]), json={"archived": True}).status_code == 404
    r = c.post(f"/api/vendor/products/{p['id']}/archive", headers=h, json={"archived": False}).json()
    assert r["archived"] is False and r["is_active"] is False                                      # restored paused, never auto-live


def test_sorting_and_filter_inputs_are_whitelisted(c):
    for i, (price, stock) in enumerate([(300, 1), (100, 9), (200, 5)]):
        _post(c, "ub", _body(f"SO-{i}", selling_price=price, mrp=price + 50, stock=stock))
    h = _hdr(S["ub"]["id"])
    get = lambda qs: c.get(f"/api/vendor/products?page=1&page_size=100&q=SO-&{qs}", headers=h)
    assert [x["selling_price"] for x in get("sort=price&order=asc").json()["items"]] == [100, 200, 300]
    assert [x["selling_price"] for x in get("sort=price&order=desc").json()["items"]] == [300, 200, 100]
    assert [x["stock"] for x in get("sort=stock&order=asc").json()["items"]] == [1, 5, 9]
    for bad in ("sort=password", "sort=$where", "order=sideways", "category=Electronics"):
        assert get(bad).status_code == 400, bad
    assert all(x["category"] == "Sarees" for x in get("category=Sarees").json()["items"])


# ====================================================================== CSV
def _imp(c, vkey, csv, mode="products", commit=False):
    return c.post("/api/vendor/products/import", headers=_hdr(S[vkey]["id"]), json={"mode": mode, "csv": csv, "commit": commit})


HEAD = "sku,name,category,mrp,selling_price,stock,images\n"


def test_export_is_own_catalogue_only_and_formula_safe(c):
    _post(c, "ua", _body("EX-1", name="=HYPERLINK(\"http://evil\")"))
    r = c.get("/api/vendor/products/export.csv", headers=_hdr(S["ua"]["id"]))
    assert r.status_code == 200 and "'=HYPERLINK" in r.text and "EX-1" in r.text
    assert "SO-0" not in r.text                                                                      # vendor B's products
    t = c.get("/api/vendor/products/import-template.csv?mode=stock", headers=_hdr(S["ua"]["id"]))
    assert t.status_code == 200 and t.text.startswith("sku,variant_sku,delta,reason")
    assert c.get("/api/vendor/products/import-template.csv?mode=x", headers=_hdr(S["ua"]["id"])).status_code == 400


def test_import_is_all_or_nothing_with_a_row_by_row_report(c):
    csv = HEAD + "IM-1,Good one,Sarees,500,400,5,/brand/a.jpg\n" + "IM-2,,Sarees,500,400,5,\n" + "IM-3,Bad price,Sarees,100,900,5,\n" \
        + "IM-4,Bad image,Sarees,500,400,5,javascript:alert(1)\n" + "IM-5,Bad cat,Electronics,500,400,5,\n" + "IM-1,Dup row,Sarees,500,400,5,\n"
    prev = _imp(c, "ua", csv).json()
    assert prev["committed"] is False and prev["rows"] == 6 and prev["valid"] == 1 and prev["invalid"] == 5
    bad = {r["sku"]: r for r in prev["report"] if r["status"] == "error"}
    assert "duplicate" in " ".join(bad["IM-1"]["errors"]) and set(bad) >= {"IM-2", "IM-3", "IM-4", "IM-5", "IM-1"}
    assert prev["report"][0]["row"] == 2
    r = _imp(c, "ua", csv, commit=True)
    assert r.status_code == 400 and r.json()["detail"]["invalid"] == 5
    assert c.portal.call(lambda: db.products.count_documents({"sku": {"$regex": "^IM-"}})) == 0         # NOTHING was written


def test_a_valid_import_creates_products_for_review_and_updates_existing_ones_safely(c):
    ok = HEAD + "IM-10,Imported saree,Sarees,900,700,12,/brand/pillar-sarees.jpg\n" + "IM-11,Second,Household Essentials,300,250,4,\n"
    assert _imp(c, "ua", ok).json()["valid"] == 2 and c.portal.call(lambda: db.products.count_documents({"sku": "IM-10"})) == 0   # preview wrote nothing
    r = _imp(c, "ua", ok, commit=True)
    assert r.status_code == 200 and r.json()["committed"] is True
    p = c.portal.call(lambda: db.products.find_one({"sku": "IM-10"}))
    assert p["approval_status"] == "pending" and p["is_active"] is False and p["stock"] == 12 and p["vendor_id"] == S["va"]["id"]
    _approve(c, p["id"])
    upd = HEAD + "IM-10,Imported saree,Sarees,900,700,999,/brand/pillar-sarees.jpg\n"          # same data, different 'stock' column
    assert _imp(c, "ua", upd, commit=True).status_code == 200
    d = _prod(c, p["id"])
    assert d["stock"] == 12 and d["approval_status"] == "approved"                                  # stock never changes via the products CSV
    assert _imp(c, "ua", HEAD + "IM-10,Imported saree,Sarees,900,650,0,/brand/pillar-sarees.jpg\n", commit=True).status_code == 200
    assert _prod(c, p["id"])["approval_status"] == "pending"                                        # price change -> re-review
    clash = _imp(c, "ub", HEAD + "IM-10,Hijack,Sarees,100,90,1,\n")
    assert clash.json()["invalid"] == 1 and "another seller" in clash.json()["report"][0]["errors"][0]
    assert _prod(c, p["id"])["name"] == "Imported saree"


def test_stock_import_needs_reasons_never_goes_negative_and_only_touches_own_products(c):
    p = _post(c, "ua", _body("SI-1", stock=5)).json()
    v = _post(c, "ua", _body("SI-2", category="Fashion Products", variants=[{"sku": "SI-2-S", "attributes": {"size": "S"}, "stock": 3}])).json()
    head = "sku,variant_sku,delta,reason\n"
    assert _imp(c, "ua", head + "SI-1,,5,New batch\nSI-2,SI-2-S,-1,Damaged\n", "stock", commit=True).status_code == 200
    assert _prod(c, p["id"])["stock"] == 10 and _prod(c, v["id"])["variants"][0]["stock"] == 2 and _prod(c, v["id"])["stock"] == 2
    mv = c.portal.call(lambda: db.stock_movements.find({"product_id": p["id"], "source": "csv"}).to_list(5))
    assert mv[0]["reason"] == "New batch" and mv[0]["delta"] == 5
    bad = _imp(c, "ua", head + "SI-1,,-50,Too many\nSI-1,,0,Zero\nSI-1,,3,\nNOPE,,1,Unknown\nSI-2,,1,Missing variant\nSI-2,X,1,Bad variant\n", "stock").json()
    assert bad["valid"] == 0 and bad["invalid"] == 6
    assert _imp(c, "ub", head + "SI-1,,5,Hijack\n", "stock").json()["invalid"] == 1                 # another vendor's product
    assert _imp(c, "ua", head + "SI-1,,-50,Too many\nSI-1,,1,Fine\n", "stock", commit=True).status_code == 400
    assert _prod(c, p["id"])["stock"] == 10                                                          # the good row was NOT applied either


def test_import_inputs_are_bounded(c):
    assert _imp(c, "ua", "name\nx\n").status_code == 400                                             # missing sku column
    assert _imp(c, "ua", HEAD).status_code == 400                                                   # no rows
    assert _imp(c, "ua", HEAD + "".join(f"BIG-{i},N,Sarees,10,9,1,\n" for i in range(501))).status_code == 400
    assert c.post("/api/vendor/products/import", headers=_hdr(S["ua"]["id"]), json={"mode": "products", "csv": "x" * 1_000_001}).status_code == 422
    assert _imp(c, "ua", HEAD, mode="bogus").status_code == 400


# ====================================================================== dashboard
def _cod_order(c, p, qty=1):
    r = c.post("/api/orders", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": p["id"], "quantity": qty}], "address": ADDR, "payment_method": "cod"})
    assert r.status_code == 200, r.text
    return r.json()


def _dash(c, vkey, qs=""):
    r = c.get(f"/api/vendor/dashboard{qs}", headers=_hdr(S[vkey]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def test_dashboard_values_come_from_the_database_and_obey_the_money_identity(c):
    p = _post(c, "ub", _body("DB-1", selling_price=100, mrp=150, stock=500)).json()
    _approve(c, p["id"])
    o1, o2 = _cod_order(c, p, 2), _cod_order(c, p, 1)
    c.post(f"/api/orders/{o2['id']}/cod-collected", headers=_hdr(S["admin"]["id"]))
    d = _dash(c, "ub")
    s = d["sales"]
    assert s["order_value_paise"] == s["collected_paise"] + s["cod_awaiting_paise"] + s["awaiting_confirmation_paise"] + s["under_review_paise"]
    assert s["cod_awaiting_paise"] >= 20000 and s["collected_paise"] >= 10000 and d["today"]["orders"] >= 2
    assert d["range"]["key"] == "month" and "gross_this_month" in s and s["order_value"] == s["gross_this_month"]
    assert sum(x["value_paise"] for x in d["trend"]) >= s["order_value_paise"]
    assert d["best_sellers"][0]["sku"] and d["best_sellers"][0]["category"] == "Sarees"
    assert d["queue"]["new"] >= 2 and any(a["key"] == "new_orders" and a["priority"] == "high" and a["link"] == "/vendor/orders?status=new" for a in d["action_centre"])
    assert set(d["returns"]) >= {"requested", "to_inspect", "replacements_due"} and "provisional" in d["finance"]


def test_dashboard_ranges_filters_and_validation(c):
    today = datetime.now(timezone.utc).date()
    assert [x["date"] for x in _dash(c, "ub", "?range=today")["trend"]] == [today.isoformat()]
    assert len(_dash(c, "ub", "?range=7d")["trend"]) == 7 and len(_dash(c, "ub", "?range=30d")["trend"]) == 30
    old = (today - timedelta(days=100)).isoformat()
    c.portal.call(lambda: db.orders.update_many({"fulfilments.vendor_id": S["vb"]["id"], "order_number": {"$exists": True}}, {"$set": {}}))
    assert _dash(c, "ub", f"?range=custom&date_from={old}&date_to={old}")["sales"]["orders"] == 0     # nothing that day
    for bad in ("?range=forever", "?range=custom", "?range=custom&date_from=2026-13-01&date_to=2026-12-01",
                "?range=custom&date_from=2024-01-01&date_to=2026-01-01", "?range=custom&date_from=2026-12-01&date_to=2026-01-01"):
        assert c.get(f"/api/vendor/dashboard{bad}", headers=_hdr(S["ub"]["id"])).status_code == 400, bad


def test_dashboard_excludes_unpaid_online_rejected_and_other_vendors_orders(c):
    pa = _post(c, "ua", _body("DB-A", selling_price=100, mrp=150, stock=50)).json()
    _approve(c, pa["id"])
    before_b = _dash(c, "ub")["sales"]["order_value_paise"]
    a_order = _cod_order(c, pa, 3)
    assert _dash(c, "ub")["sales"]["order_value_paise"] == before_b                                  # vendor A's order is invisible to B
    before_a = _dash(c, "ua")["sales"]["order_value_paise"]
    c.post("/api/orders", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": pa["id"], "quantity": 1}], "address": ADDR, "payment_method": "online"})
    assert _dash(c, "ua")["sales"]["order_value_paise"] == before_a                                  # unpaid online is not order value
    c.post(f"/api/vendor/orders/{a_order['id']}/fulfilment", headers=_hdr(S["ua"]["id"]), json={"status": "rejected", "note": "Out of material"})
    assert _dash(c, "ua")["sales"]["order_value_paise"] == before_a - 30000


def test_dashboard_is_aggregated_in_the_database_not_capped_at_500_orders(c):
    vid, base = S["vb"]["id"], datetime.now(timezone.utc).isoformat()
    docs = [{"id": new_id(), "order_number": f"BULK{i}", "user_id": S["cust"]["id"], "payment_method": "cod", "payment_status": "cod_pending",
             "status": "confirmed", "created_at": base, "items": [{"product_id": "bulk", "sku": "BULK", "name": "Bulk item", "vendor_id": vid, "quantity": 1,
                                                                   "price_paise": 1000, "total_paise": 1000, "total": 10.0}],
             "fulfilments": [{"vendor_id": vid, "status": "new", "events": []}]} for i in range(700)]
    c.portal.call(lambda: db.orders.insert_many(docs))
    t = time.time()
    d = _dash(c, "ub")
    assert time.time() - t < 5
    assert d["queue"]["new"] >= 700 and d["sales"]["orders"] >= 700 and d["sales"]["cod_awaiting_paise"] >= 700 * 1000
    assert c.get("/api/vendor/orders", headers=_hdr(S["ub"]["id"])).status_code == 200                # the plain list is still bounded (back-compat)
    c.portal.call(lambda: db.orders.delete_many({"order_number": {"$regex": "^BULK"}}))


def test_dashboard_inventory_alerts_and_isolation(c):
    _post(c, "ub", _body("INV-OUT", stock=0))
    _post(c, "ub", _body("INV-LOW", stock=2, low_stock_threshold=5))
    d = _dash(c, "ub")
    skus = {a["sku"] for a in d["inventory_alerts"]}
    assert {"INV-OUT", "INV-LOW"} <= skus and d["products"]["out_of_stock"] >= 1 and d["products"]["low_stock"] >= 1
    assert all(not a["sku"].startswith(("AT-", "VP-", "IM-")) for a in d["inventory_alerts"])        # only B's own products
    assert c.get("/api/vendor/dashboard", headers=_hdr(S["cust"]["id"])).status_code == 403
    assert c.get("/api/vendor/dashboard").status_code == 401


def test_a_mixed_vendor_order_counts_only_each_vendors_own_lines(c):
    pa = _post(c, "ua", _body("MX-A", selling_price=100, mrp=150, stock=50)).json()
    pb = _post(c, "ub", _body("MX-B", selling_price=250, mrp=300, stock=50)).json()
    _approve(c, pa["id"]); _approve(c, pb["id"])
    a0, b0 = _dash(c, "ua")["sales"]["order_value_paise"], _dash(c, "ub")["sales"]["order_value_paise"]
    r = c.post("/api/orders", headers=_hdr(S["cust"]["id"]), json={"items": [{"product_id": pa["id"], "quantity": 2}, {"product_id": pb["id"], "quantity": 1}],
                                                                     "address": ADDR, "payment_method": "cod"})
    assert r.status_code == 200
    assert _dash(c, "ua")["sales"]["order_value_paise"] - a0 == 20000       # only vendor A's 2 x 100
    assert _dash(c, "ub")["sales"]["order_value_paise"] - b0 == 25000       # only vendor B's 1 x 250
    best_b = [x["sku"] for x in _dash(c, "ub")["best_sellers"]]
    assert "MX-A" not in best_b
