"""Batch 12, Phase 5 — granular vendor staff permissions.

- Fine-grained permissions (create / edit / submit / archive, accept / pack / dispatch, respond / inspect, export ...).
- Existing members keep exactly their access: the original coarse permissions imply the fine ones (no migration, no lock-out).
- Fulfilment steps are checked per step (a packer cannot dispatch; a dispatcher cannot accept).
- Presets are least-privilege; custom roles accept only known permissions; only the owner manages staff.
- A permission matrix: every preset against every sensitive vendor endpoint.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_staff_permissions_batch12.py -n 0`).
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_staff_perms_b12_test", "JWT_SECRET": "staffperm12-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import vendor_staff as VS  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


async def _member(key, role, perms):
    u = {"id": new_id(), "distributor_id": "SP" + key.upper(), "full_name": key, "mobile": f"91000140{len(S):02d}", "email": None,
         "password_hash": hash_password("Pass-1234x"), "role": "vendor_staff", "status": "green", "account_status": "active",
         "created_at": now_iso(), "updated_at": now_iso()}
    await db.users.insert_one(dict(u))
    S[key] = u
    await db.vendor_members.insert_one({"id": new_id(), "vendor_id": S["v"]["id"], "user_id": u["id"], "mobile": u["mobile"],
                                        "full_name": key, "role": role, "permissions": perms, "status": "active",
                                        "created_at": now_iso(), "updated_at": now_iso()})


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role in (("owner", "vendor"), ("cust", "distributor")):
                u = {"id": new_id(), "distributor_id": "SP" + key.upper(), "full_name": key, "mobile": f"91000139{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            S["v"] = {"id": new_id(), "user_id": S["owner"]["id"], "vendor_code": "SPV", "business_name": "Perm Vendor", "status": "approved",
                      "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
            await db.products.insert_one({"id": "spp", "sku": "SP-1", "name": "Saree", "images": [], "mrp": 1200, "selling_price": 1050,
                                          "gst_percent": 5, "stock": 100, "category": "Sarees", "options": [], "vendor_id": S["v"]["id"],
                                          "vendor_name": "Perm Vendor", "is_active": True, "approval_status": "approved", "created_at": now_iso()})
            for preset, perms in VS.PRESETS.items():
                await _member(preset, preset, list(perms))
            await _member("legacy_fulfil", "custom", ["orders.read", "orders.fulfil"])           # stored before Batch 12
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _paid_order(c):
    o = c.post("/api/orders", json={"items": [{"product_id": "spp", "quantity": 1}], "address": ADDR, "payment_method": "online"},
               headers=_hdr("cust")).json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    return o


def _step(c, who, oid, status):
    body = {"status": status, "note": "Handed to customer" if status == "delivered" else ("Out of stock now" if status == "rejected" else ""),
            "carrier": "BlueDart", "tracking_number": "BD1"}
    return c.post(f"/api/vendor/orders/{oid}/fulfilment", json=body, headers=_hdr(who))


# ================================================================ vocabulary and presets
def test_every_preset_uses_known_permissions_and_none_grants_owner_only_areas():
    known = set(VS.PERMISSIONS) | set(VS.LEGACY_IMPLIES)
    for name, perms in VS.PRESETS.items():
        assert set(perms) <= known, name
        assert name in VS.PRESET_INFO and VS.PRESET_INFO[name]["label"] and VS.PRESET_INFO[name]["description"]
    for p in VS.PERMISSIONS:
        info = VS.PERMISSION_INFO[p]
        assert info["module"] and info["label"] and info["description"] and info["risk"] in ("low", "medium", "high")
    for required in ("catalogue_manager", "product_editor", "inventory_manager", "warehouse_staff", "order_manager", "packing_staff",
                     "dispatch_staff", "returns_manager", "support_staff", "finance_viewer", "reports_viewer", "store_manager"):
        assert required in VS.PRESETS
    assert "products.submit" not in VS.PRESETS["product_editor"]
    assert not any(p.startswith("finance") for p in VS.PRESETS["warehouse_staff"] + VS.PRESETS["packing_staff"])


def test_original_permissions_still_open_exactly_what_they_did():
    eff = VS.effective_permissions(["orders.read", "orders.fulfil", "products.write", "returns.act", "inventory.write"])
    assert {"orders.accept", "orders.pack", "orders.dispatch", "products.create", "products.edit", "products.submit",
            "products.archive", "returns.respond", "returns.inspect", "inventory.adjust"} <= eff


def test_custom_roles_accept_only_known_permissions(c):
    with pytest.raises(Exception):
        VS.validate_role("custom", ["orders.read", "settlements.pay"])
    assert VS.validate_role("custom", ["orders.pack", "orders.read"]) == ["orders.pack", "orders.read"]


def test_the_staff_screen_gets_descriptions_and_risk_levels(c):
    r = c.get("/api/vendor/staff", headers=_hdr("owner"))
    assert r.status_code == 200
    body = r.json()
    assert body["permission_info"]["orders.dispatch"]["module"] == "Orders" and body["preset_info"]["packing_staff"]["label"]
    assert c.get("/api/vendor/staff", headers=_hdr("store_manager")).status_code == 403          # only the owner manages staff


# ================================================================ fulfilment, step by step
def test_each_fulfilment_step_needs_its_own_permission(c):
    o = _paid_order(c)
    assert _step(c, "packing_staff", o["id"], "accepted").status_code == 403
    assert _step(c, "dispatch_staff", o["id"], "accepted").status_code == 403
    assert _step(c, "order_manager", o["id"], "accepted").status_code == 200
    assert _step(c, "dispatch_staff", o["id"], "packed").status_code == 403
    assert _step(c, "packing_staff", o["id"], "packed").status_code == 200
    assert _step(c, "packing_staff", o["id"], "dispatched").status_code == 403
    assert _step(c, "dispatch_staff", o["id"], "dispatched").status_code == 200
    assert _step(c, "warehouse_staff", o["id"], "delivered").status_code == 403
    assert _step(c, "dispatch_staff", o["id"], "delivered").status_code == 200


def test_a_member_with_the_original_fulfil_permission_keeps_every_step(c):
    o = _paid_order(c)
    for st in ("accepted", "packed", "dispatched", "delivered"):
        assert _step(c, "legacy_fulfil", o["id"], st).status_code == 200, st


# ================================================================ the matrix
MATRIX = [
    # (method, path, body, permission that opens it)
    ("GET", "/api/vendor/products", None, "products.read"),
    ("POST", "/api/vendor/pim/drafts", {}, "products.create"),
    ("POST", "/api/vendor/products/spp/stock", {"delta": 1, "reason": "recount test"}, "inventory.adjust"),
    ("GET", "/api/vendor/products/spp/stock-history", None, "inventory.read"),
    ("POST", "/api/vendor/products/spp/listing", {"active": True}, "products.archive"),
    ("GET", "/api/vendor/orders", None, "orders.read"),
    ("GET", "/api/vendor/returns", None, "returns.read"),
    ("GET", "/api/vendor/dashboard", None, "reports.read"),
    ("GET", "/api/vendor/reports/current.csv", None, "reports.export"),
    ("GET", "/api/vendor/finance/summary", None, "finance.read"),
    ("GET", "/api/vendor/finance/statement.csv", None, "finance.export"),
    ("GET", "/api/vendor/staff", None, None),            # owner only
    ("PUT", "/api/vendor/me", {}, None),                 # owner only
]


@pytest.mark.parametrize("preset", sorted(VS.PRESETS))
def test_permission_matrix(c, preset):
    eff = VS.effective_permissions(VS.PRESETS[preset])
    for method, path, body, perm in MATRIX:
        r = c.request(method, path, json=body, headers=_hdr(preset))
        allowed = perm is not None and perm in eff
        if allowed:
            assert r.status_code != 403, (preset, method, path, r.text)
        else:
            assert r.status_code == 403, (preset, method, path, r.status_code)
