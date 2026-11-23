"""Batch 12, Phase 4 — product information management (pim.py): drafts, completeness, submission, revisions that keep the
approved product live, admin products on a vendor's behalf, staff permissions, and stock that no form can overwrite.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_pim_batch12.py -n 0`).
"""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_pim_batch12_test", "JWT_SECRET": "pim12-test-" + "k" * 40,
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


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, mob, role in (("super", "9100013001", "super_admin"), ("admin", "9100013002", "admin"), ("sup", "9100013003", "support_admin"),
                                   ("vu", "9100013004", "vendor"), ("cust", "9100013005", "customer"), ("ro", "9100013006", "vendor_staff"),
                                   ("rw", "9100013007", "vendor_staff"), ("vu2", "9100013008", "vendor")):
                u = {"id": new_id(), "distributor_id": "P12" + key.upper(), "full_name": key, "mobile": mob, "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            for vk, owner in (("v", "vu"), ("v2", "vu2")):
                S[vk] = {"id": new_id(), "user_id": S[owner]["id"], "vendor_code": "P12" + vk.upper(), "business_name": f"Weaves {vk}",
                         "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(S[vk]))
            for key, perms in (("ro", ["products.read"]), ("rw", ["products.read", "products.write"])):
                await db.vendor_members.insert_one({"id": new_id(), "vendor_id": S["v"]["id"], "user_id": S[key]["id"], "mobile": S[key]["mobile"],
                                                    "full_name": key, "role": "catalogue", "permissions": perms, "status": "active",
                                                    "created_at": now_iso(), "updated_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


_n = {"i": 0}


def _complete(**over):
    _n["i"] += 1
    d = {"sku": f"P12-SAR-{_n['i']}", "name": "Banarasi silk saree with zari border", "category": "Sarees", "subcategory": "Banarasi",
         "short_description": "Handwoven Banarasi silk saree", "description": "A handwoven Banarasi silk saree with a rich zari border and pallu.",
         "brand": "Weaves", "images": [IMG], "image_alt": {IMG: "Red Banarasi saree, front view"}, "mrp": 5000, "selling_price": 4200,
         "gst_percent": 5, "hsn_code": "5007", "stock": 7, "low_stock_threshold": 2,
         "attributes": {"fabric": "Pure silk", "colour": "Red", "length_m": 6.3, "care_instructions": "Dry clean only",
                        "country_of_origin": "India", "occasion": ["Wedding", "Festive"], "blouse_piece": True},
         "package": {"weight_g": 800, "handling_days": 2, "length_cm": 35, "width_cm": 25, "height_cm": 5},
         "highlights": ["Pure silk", "Zari border"], "returnable": True}
    d.update(over)
    return d


def _draft(c, who="vu", **body):
    r = c.post("/api/vendor/pim/drafts", json=body, headers=_hdr(who))
    assert r.status_code == 200, r.text
    return r.json()


def _save(c, dr, data, who="vu"):
    return c.put(f"/api/vendor/pim/drafts/{dr['id']}", json={"data": data, "version": dr["version"]}, headers=_hdr(who))


def _new_product(c, **over):
    dr = _draft(c)
    dr = _save(c, dr, _complete(**over)).json()
    r = c.post(f"/api/vendor/pim/drafts/{dr['id']}/submit", headers=_hdr("vu"))
    assert r.status_code == 200, r.text
    return r.json()["product_id"]


def _approve(c, pid, who="super"):
    return c.post(f"/api/admin/vendor-products/{pid}/decision", json={"action": "approve"}, headers=_hdr(who))


def _product(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}, {"_id": 0}))


# ================================================================ template and access
def test_the_template_is_for_vendors_and_admins_only(c):
    r = c.get("/api/pim/template", headers=_hdr("vu"))
    assert r.status_code == 200 and set(r.json()["templates"]) == {"Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"}
    assert c.get("/api/pim/template", headers=_hdr("admin")).status_code == 200
    assert c.get("/api/pim/template", headers=_hdr("cust")).status_code == 403


# ================================================================ drafts
def test_drafts_save_partially_with_versions_and_report_what_is_missing(c):
    dr = _draft(c)
    assert dr["check"]["ok"] is False and dr["check"]["sections"]["basics"]["problems"]
    s1 = _save(c, dr, {"name": "Half done", "category": "Sarees"})
    assert s1.status_code == 200 and s1.json()["version"] == dr["version"] + 1
    assert _save(c, dr, {"name": "Stale tab"}).status_code == 409                   # saved from an out-of-date copy
    details = s1.json()["check"]["sections"]["details"]["problems"][0]
    assert "Fabric" in details and "Care instructions" in details                    # the category template's required fields
    assert c.get("/api/vendor/pim/drafts", headers=_hdr("vu")).json()[0]["id"] == dr["id"] or \
        any(x["id"] == dr["id"] for x in c.get("/api/vendor/pim/drafts", headers=_hdr("vu")).json())
    assert c.get(f"/api/vendor/pim/drafts/{dr['id']}", headers=_hdr("vu2")).status_code == 404       # another vendor


def test_an_incomplete_draft_cannot_be_submitted(c):
    dr = _save(c, _draft(c), _complete(images=[], attributes={})).json()
    r = c.post(f"/api/vendor/pim/drafts/{dr['id']}/submit", headers=_hdr("vu"))
    assert r.status_code == 422 and r.json()["detail"]["check"]["sections"]["media"]["problems"]
    assert _run(c, lambda: db.product_drafts.find_one({"id": dr["id"]}))["status"] == "draft"


def test_invalid_values_are_refused_by_the_shared_validation(c):
    dr = _save(c, _draft(c), _complete(attributes={**_complete()["attributes"], "pattern": "Not a pattern"})).json()
    r = c.post(f"/api/vendor/pim/drafts/{dr['id']}/submit", headers=_hdr("vu"))
    assert r.status_code == 400 and "pattern" in r.text
    dr2 = _save(c, _draft(c), _complete(selling_price=6000)).json()
    assert c.post(f"/api/vendor/pim/drafts/{dr2['id']}/submit", headers=_hdr("vu")).status_code == 422


def test_a_complete_draft_creates_a_product_awaiting_review_with_its_opening_stock(c):
    pid = _new_product(c)
    p = _product(c, pid)
    assert p["approval_status"] == "pending" and p["is_active"] is False and p["stock"] == 7
    assert p["highlights"] == ["Pure silk", "Zari border"] and p["image_alt"] == {IMG: "Red Banarasi saree, front view"}
    assert _run(c, lambda: db.stock_movements.count_documents({"product_id": pid, "reason": "initial_stock"})) == 1
    assert _approve(c, pid).status_code == 200
    p = _product(c, pid)
    assert p["approval_status"] == "approved" and p["is_active"] is True and p["price_history"][0]["to"]["selling_price"] == 4200


# ================================================================ revisions keep the approved product live
def test_a_change_to_an_approved_product_waits_for_review_while_the_product_stays_on_sale(c):
    pid = _new_product(c)
    assert _approve(c, pid).status_code == 200
    _run(c, lambda: db.products.update_one({"id": pid}, {"$set": {"stock": 3}}))      # sold some since (stock moved elsewhere)
    dr = _draft(c, product_id=pid)
    assert dr["data"]["selling_price"] == 4200
    dr = _save(c, dr, {**dr["data"], "selling_price": 3900, "stock": 999}).json()
    r = c.post(f"/api/vendor/pim/drafts/{dr['id']}/submit", headers=_hdr("vu"))
    assert r.status_code == 200 and r.json()["result"] == "revision_pending"
    p = _product(c, pid)
    assert p["selling_price"] == 4200 and p["is_active"] is True and p["approval_status"] == "approved"   # live version untouched
    assert c.put(f"/api/vendor/products/{pid}", json=_complete(sku=p["sku"]), headers=_hdr("vu")).status_code == 409
    shop = c.get(f"/api/products/{pid}").json()                                      # shoppers never see unapproved changes
    assert shop["selling_price"] == 4200 and "pending_revision" not in shop and "price_history" not in shop
    assert "compliance_documents" not in shop and all("pending_revision" not in x for x in c.get("/api/products").json())
    assert c.get("/api/admin/pim/revisions", headers=_hdr("sup")).status_code == 200
    diff = c.get(f"/api/admin/pim/products/{pid}/revision", headers=_hdr("admin")).json()["diff"]
    assert diff["selling_price"] == {"live": 4200, "proposed": 3900}
    assert c.post(f"/api/admin/pim/products/{pid}/revision/decision", json={"action": "approve"}, headers=_hdr("sup")).status_code == 403
    r = c.post(f"/api/admin/pim/products/{pid}/revision/decision", json={"action": "approve"}, headers=_hdr("admin"))
    assert r.status_code == 200, r.text
    p = _product(c, pid)
    assert p["selling_price"] == 3900 and p["is_active"] is True and p["approval_status"] == "approved"
    assert p["stock"] == 3                                                            # no form ever sets live stock
    assert p["price_history"][-1]["from"]["selling_price"] == 4200 and p["price_history"][-1]["to"]["selling_price"] == 3900
    assert p["pending_revision"]["status"] == "approved"


def test_a_rejected_or_returned_change_leaves_the_live_product_untouched(c):
    pid = _new_product(c)
    _approve(c, pid)
    for action in ("reject", "request_changes"):
        dr = _draft(c, product_id=pid)
        dr = _save(c, dr, {**dr["data"], "name": "Completely different title " + action}).json()
        assert c.post(f"/api/vendor/pim/drafts/{dr['id']}/submit", headers=_hdr("vu")).json()["result"] == "revision_pending"
        assert c.post(f"/api/admin/pim/products/{pid}/revision/decision", json={"action": action}, headers=_hdr("admin")).status_code == 400
        r = c.post(f"/api/admin/pim/products/{pid}/revision/decision", json={"action": action, "reason": "Title does not match the photos"},
                   headers=_hdr("admin"))
        assert r.status_code == 200
        p = _product(c, pid)
        assert p["name"] == "Banarasi silk saree with zari border" and p["is_active"] is True
        rev = c.get(f"/api/vendor/pim/products/{pid}/revision", headers=_hdr("vu")).json()
        assert rev["status"] in ("rejected", "changes_requested") and rev["reason"] == "Title does not match the photos"


def test_one_open_draft_per_product_even_when_two_tabs_open_it_together(c):
    pid = _new_product(c)
    ids = list(ThreadPoolExecutor(max_workers=4).map(lambda _: _draft(c, product_id=pid)["id"], range(4)))
    assert len(set(ids)) == 1


# ================================================================ admin on a vendor's behalf
def test_an_admin_prepares_a_product_for_a_vendor_but_another_admin_approves_it(c):
    r = c.post("/api/admin/pim/drafts", json={"vendor_id": S["v"]["id"]}, headers=_hdr("admin"))
    assert r.status_code == 200, r.text
    dr = r.json()
    assert c.post("/api/admin/pim/drafts", json={"vendor_id": S["v"]["id"]}, headers=_hdr("sup")).status_code == 403
    dr = c.put(f"/api/admin/pim/drafts/{dr['id']}", json={"data": _complete(), "version": dr["version"]}, headers=_hdr("admin")).json()
    out = c.post(f"/api/admin/pim/drafts/{dr['id']}/submit", headers=_hdr("admin"))
    assert out.status_code == 200, out.text
    pid = out.json()["product_id"]
    assert _product(c, pid)["created_on_behalf_by"] == S["admin"]["id"] and _product(c, pid)["vendor_id"] == S["v"]["id"]
    assert _approve(c, pid, "admin").status_code == 403
    assert _approve(c, pid, "super").status_code == 200


def test_admins_do_not_edit_a_vendors_own_draft(c):
    dr = _draft(c)
    assert c.put(f"/api/admin/pim/drafts/{dr['id']}", json={"data": {"name": "x"}, "version": dr["version"]}, headers=_hdr("admin")).status_code == 403
    assert c.post(f"/api/admin/pim/drafts/{dr['id']}/submit", headers=_hdr("admin")).status_code == 403


# ================================================================ vendor staff
def test_staff_follow_their_product_permissions(c):
    assert c.post("/api/vendor/pim/drafts", json={}, headers=_hdr("ro")).status_code == 403
    assert c.get("/api/vendor/pim/drafts", headers=_hdr("ro")).status_code == 200
    r = c.post("/api/vendor/pim/drafts", json={}, headers=_hdr("rw"))
    assert r.status_code == 200 and r.json()["vendor_id"] == S["v"]["id"]
