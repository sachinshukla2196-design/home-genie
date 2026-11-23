"""Batch 13, Phases 10–11 — search / discovery (discovery.py) and merchandising (merchandising.py).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_discovery_merch_b13.py -n 0`).
"""
import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_discovery_b13_test", "JWT_SECRET": "discovery13-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

S = {}
IMG = "/brand/pillar-sarees.jpg"


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


def _p(pid, name, price, cat="Sarees", sub="Silk", brand="Sutra", stock=5, attrs=None, created=None, **extra):
    return {"id": pid, "sku": pid.upper(), "name": name, "images": [], "mrp": price + 100, "selling_price": price, "gst_percent": 5,
            "stock": stock, "category": cat, "subcategory": sub, "brand": brand, "keywords": [], "options": [], "vendor_id": None,
            "attributes": attrs or {}, "is_active": True, "approval_status": "approved", "created_at": created or now_iso(), **extra}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role in (("super", "super_admin"), ("admin", "admin"), ("sup", "support_admin"), ("vu", "vendor"), ("cust", "customer")):
                u = {"id": new_id(), "distributor_id": "DM" + key.upper(), "full_name": key, "mobile": f"91000190{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            await db.products.insert_many([
                _p("s1", "Banarasi silk saree red", 4200, attrs={"colour": "Red", "fabric": "Silk"}, created=old),
                _p("s2", "Kanjeevaram silk saree", 6800, sub="Kanjeevaram", attrs={"colour": "Gold"}),
                _p("s3", "Cotton handloom saree", 1500, sub="Cotton", brand="Weavers", attrs={"colour": "Red", "fabric": "Cotton"}),
                _p("s4", "Silk saree out of stock", 3000, stock=0),
                _p("s5", "Hidden silk saree", 3500, approval_status="pending", is_active=False),
                _p("s6", "Archived silk saree", 3600, archived=True),
                _p("k1", "Herbal face serum", 650, cat="Makeup, Beauty & Skincare", sub="Skincare", brand="Glow"),
            ])
            await db.orders.insert_many([
                {"id": f"o{i}", "order_number": f"O{i}", "payment_status": ps, "status": st, "created_at": now_iso(),
                 "items": [{"product_id": pid, "quantity": q}]}
                for i, (pid, q, ps, st) in enumerate([("s3", 5, "paid", "delivered"), ("s1", 2, "paid", "processing"),
                                                      ("s2", 9, "pending", "pending"), ("s1", 1, "paid", "cancelled")])])
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


# ================================================================ search
def _search(c, **params):
    r = c.get("/api/catalog/search", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_search_finds_only_products_on_sale_and_ranks_by_relevance(c):
    ids = [p["id"] for p in _search(c, q="silk")["items"]]
    assert set(ids) == {"s1", "s2", "s4"} and "s5" not in ids and "s6" not in ids
    first = _search(c, q="banarasi")["items"][0]
    assert first["id"] == "s1" and "pending_revision" not in first and "price_history" not in first


def test_filters_sorting_and_paging_run_on_the_server(c):
    assert [p["id"] for p in _search(c, category="Sarees", sort="price_asc")["items"]] == ["s3", "s4", "s1", "s2"]
    assert {p["id"] for p in _search(c, min_price=2000, max_price=5000)["items"]} == {"s1", "s4"}
    assert {p["id"] for p in _search(c, q="silk", in_stock=True)["items"]} == {"s1", "s2"}
    assert {p["id"] for p in _search(c, brand="Weavers")["items"]} == {"s3"}
    r = c.get("/api/catalog/search", params=[("attr.colour", "Red"), ("category", "Sarees")]).json()
    assert {p["id"] for p in r["items"]} == {"s1", "s3"}
    page = _search(c, category="Sarees", sort="name", page_size=2, page=2)
    assert page["total"] == 4 and page["pages"] == 2 and len(page["items"]) == 2
    assert c.get("/api/catalog/search", params={"attr.nonsense": "x"}).status_code == 400
    assert c.get("/api/catalog/search", params={"sort": "popular"}).status_code == 400


def test_search_input_cannot_act_as_a_query_operator(c):
    assert _search(c, q='{"$gt": ""}')["total"] == 0
    assert c.get("/api/catalog/suggest", params={"q": ".*"}).json()["products"] == []


def test_suggestions_facets_related_and_recently_viewed(c):
    s = c.get("/api/catalog/suggest", params={"q": "sil"}).json()
    assert {p["id"] for p in s["products"]} == {"s1", "s2", "s4"}
    f = c.get("/api/catalog/facets", params={"category": "Sarees"}).json()
    assert f["count"] == 4 and f["price"] == {"min": 1500, "max": 6800} and set(f["brands"]) == {"Sutra", "Weavers"}
    assert "Red" in f["attributes"]["colour"] and "Silk" in f["subcategories"]
    rel = [p["id"] for p in c.get("/api/catalog/products/s1/related").json()["items"]]
    assert "s1" not in rel and rel[0] == "s4" or rel[0] in ("s2", "s3", "s4")
    assert not ({"s5", "s6"} & set(rel))
    rv = c.get("/api/catalog/products", params={"ids": "s3,s5,s1,missing"}).json()["items"]
    assert [p["id"] for p in rv] == ["s3", "s1"]


def test_search_uses_the_indexes(c):
    plan = _run(c, lambda: db.command({"explain": {"find": "products", "filter": {"$text": {"$search": "silk"}, "is_active": True}}, "verbosity": "queryPlanner"}))
    assert "TEXT" in str(plan["queryPlanner"]["winningPlan"])
    plan = _run(c, lambda: db.command({"explain": {"find": "products", "filter": {"is_active": True, "approval_status": "approved", "category": "Sarees"},
                                                   "sort": {"selling_price": 1}}, "verbosity": "queryPlanner"}))
    assert "IXSCAN" in str(plan["queryPlanner"]["winningPlan"])


# ================================================================ merchandising
def _sec(c, who="admin", **body):
    r = c.post("/api/admin/merch/sections", json=body, headers=_hdr(who))
    return r


def _publish(c, sid, who="admin"):
    return c.post(f"/api/admin/merch/sections/{sid}/status", json={"action": "publish"}, headers=_hdr(who))


def test_only_catalogue_admins_manage_sections(c):
    body = {"kind": "collection", "title": "Wedding edit", "product_ids": ["s1"]}
    assert _sec(c, "sup", **body).status_code == 403 and _sec(c, "vu", **body).status_code == 403
    assert _sec(c, "admin", **body).status_code == 200


def test_only_products_on_sale_can_be_featured_and_out_of_stock_ones_are_skipped(c):
    assert _sec(c, kind="featured_products", title="Picks", product_ids=["s1", "s5"]).status_code == 400
    r = _sec(c, kind="featured_products", title="Picks", product_ids=["s2", "s4", "s1"]).json()
    assert r["status"] == "draft"
    assert not any(s["id"] == r["id"] for s in c.get("/api/merch/home").json()["sections"])          # drafts are not shown
    assert _publish(c, r["id"]).status_code == 200
    live = next(s for s in c.get("/api/merch/home").json()["sections"] if s["id"] == r["id"])
    assert [p["id"] for p in live["products"]] == ["s2", "s1"]                                         # order kept, s4 out of stock skipped
    _run(c, lambda: db.products.update_one({"id": "s2"}, {"$set": {"archived": True}}))
    live = next(s for s in c.get("/api/merch/home").json()["sections"] if s["id"] == r["id"])
    assert [p["id"] for p in live["products"]] == ["s1"]
    _run(c, lambda: db.products.update_one({"id": "s2"}, {"$set": {"archived": False}}))


def test_campaign_dates_activate_and_expire_without_a_job(c):
    now = datetime.now(timezone.utc)
    future = _sec(c, kind="new_arrivals", title="Coming soon", starts_at=(now + timedelta(days=1)).isoformat()).json()
    past = _sec(c, kind="new_arrivals", title="Old sale", starts_at=(now - timedelta(days=5)).isoformat(),
                ends_at=(now - timedelta(days=1)).isoformat()).json()
    for s in (future, past):
        _publish(c, s["id"])
    ids = [s["id"] for s in c.get("/api/merch/home").json()["sections"]]
    assert future["id"] not in ids and past["id"] not in ids
    states = {s["id"]: s["state"] for s in c.get("/api/admin/merch/sections", headers=_hdr("sup")).json()["sections"]}
    assert states[future["id"]] == "scheduled" and states[past["id"]] == "expired"
    assert _sec(c, kind="new_arrivals", title="Bad dates", starts_at=now.isoformat(), ends_at=(now - timedelta(days=1)).isoformat()).status_code == 400


def test_bestsellers_come_from_paid_non_cancelled_orders_and_show_no_numbers(c):
    r = _sec(c, kind="bestsellers", title="Bestsellers", window_days=30).json()
    _publish(c, r["id"])
    live = next(s for s in c.get("/api/merch/home").json()["sections"] if s["id"] == r["id"])
    assert [p["id"] for p in live["products"]] == ["s3", "s1"]                 # s2's order is unpaid; cancelled units not counted
    assert "units" not in str(live) and "rating" not in str(live)


def test_banners_need_storage_images_alt_text_and_internal_links(c):
    assert _sec(c, kind="banner", title="Diwali", image_desktop=IMG, alt="Diwali sarees", link="https://evil.example.com").status_code == 422
    assert _sec(c, kind="banner", title="Diwali", image_desktop="javascript:alert(1)", alt="x").status_code in (400, 422)
    assert _sec(c, kind="banner", title="Diwali", image_desktop=IMG).status_code == 400                          # no alt text
    r = _sec(c, kind="banner", title="Diwali", image_desktop=IMG, alt="Diwali sarees", link="/app/products?category=Sarees")
    assert r.status_code == 200


def test_reorder_unpublish_and_audit(c):
    secs = c.get("/api/admin/merch/sections", headers=_hdr("admin")).json()["sections"]
    ids = [s["id"] for s in secs][::-1]
    assert [s["id"] for s in c.post("/api/admin/merch/sections/order", json={"ids": ids}, headers=_hdr("admin")).json()["sections"]] == ids
    live = c.get("/api/merch/home").json()["sections"]
    assert c.post(f"/api/admin/merch/sections/{live[0]['id']}/status", json={"action": "unpublish"}, headers=_hdr("admin")).status_code == 200
    assert live[0]["id"] not in [s["id"] for s in c.get("/api/merch/home").json()["sections"]]
    assert _run(c, lambda: db.audit_logs.count_documents({"action": {"$regex": "^merch_section"}})) >= 5
