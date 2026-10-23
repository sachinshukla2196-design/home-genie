"""Vendor ledger, settlements, statements, COD reconciliation and permissions.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_finance_test", "JWT_SECRET": "finance-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
import ledger as L  # noqa: E402
from money import to_paise  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
CRON = {"Authorization": "Bearer cron-test-secret"}
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
            S["cust"] = await user("9100000601", "distributor", "HGC", "red")
            S["fin"], S["fin2"] = await user("9100000602", "accounts_admin", "HGFIN"), await user("9100000603", "super_admin", "HGSUP")
            S["supp"] = await user("9100000604", "support_admin", "HGSUPP")
            S["genie"] = await user("9100000605", "distributor", "HGSEL")
            S["ua"], S["ub"] = await user("9100000606", "vendor", "VDA"), await user("9100000607", "vendor", "VDB")
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A"), await vendor(S["ub"], "Vendor B")
            await db.business_settings.update_one({"id": "business_settings"}, {"$set": {"gst_percent": 5.0, "cod_fee": 0.0}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, price, vendor, stock=1000):
    async def mk():
        v = S.get(vendor)
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": price + 100, "selling_price": price, "gst_percent": 5,
             "stock": stock, "category": "Sarees", "options": [], "vendor_id": v["id"] if v else None,
             "vendor_name": v["business_name"] if v else None, "is_active": True, "approval_status": "approved", "created_at": now_iso()}
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _order(c, lines, method="online", seller=None):
    body = {"items": [{"product_id": p["id"], "quantity": q} for p, q in lines], "address": ADDR, "payment_method": method}
    if seller:
        body["seller_ref"] = seller
    r = c.post("/api/orders", json=body, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _pay(c, o):
    sid = "cs_" + o["id"][:12]
    if not c.portal.call(lambda: db.payment_transactions.find_one({"session_id": sid})):
        c.portal.call(lambda: db.payment_transactions.insert_one(
            {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
             "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))


def _entries(c, vkey=None, **q):
    f = dict(q)
    if vkey:
        f["vendor_id"] = S[vkey]["id"]
    return c.portal.call(lambda: db.vendor_ledger.find(f, {"_id": 0}).sort("posted_at", 1).to_list(500))


def _bal(c, vkey):
    return c.portal.call(lambda: L.balances(S[vkey]["id"]))


def _refund(c, o, amount=None, ref="R"):
    return c.portal.call(lambda: shop_routes.reverse_order_financials(o["id"], {"id": S["fin"]["id"]}, None, amount, ref, "t"))


def _fulfil(c, vkey, oid, status, **kw):
    return c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=_hdr(S[vkey]["id"]), json={"status": status, "note": "Reason given", **kw})


# ====================================================================== posting + idempotency
def test_sales_are_recorded_only_when_payment_is_confirmed_and_exactly_once(c):
    pa, pb = _product(c, "L-A1", 33.33, "va"), _product(c, "L-B1", 100.0, "vb")
    o = _order(c, [(pa, 3), (pb, 1)])                                 # A: 99.99   B: 100.00 (+GST that is not the vendors')
    assert _entries(c, order_id=o["id"]) == []                         # nothing before payment
    _pay(c, o)
    ea, eb = _entries(c, "va", order_id=o["id"]), _entries(c, "vb", order_id=o["id"])
    assert [(e["type"], e["amount_paise"]) for e in ea] == [("SALE_COLLECTED", 9999)]
    assert [(e["type"], e["amount_paise"]) for e in eb] == [("SALE_COLLECTED", 10000)]
    for _ in range(3):                                                 # duplicate webhook / retry / recovery
        _pay(c, o)
        c.portal.call(lambda: L.reconcile_ledger())
    assert len(_entries(c, order_id=o["id"])) == 2


def test_platform_owned_lines_never_create_vendor_entries(c):
    plat = _product(c, "L-P1", 50.0, None)
    o = _order(c, [(plat, 2)])
    _pay(c, o)
    assert _entries(c, order_id=o["id"]) == []


def test_cod_sale_is_recorded_only_when_cash_is_confirmed(c):
    pa = _product(c, "L-A2", 200.0, "va")
    o = _order(c, [(pa, 1)], method="cod")
    assert _entries(c, order_id=o["id"]) == []
    assert c.post(f"/api/orders/{o['id']}/cod-collected", headers=_hdr(S["fin2"]["id"])).status_code == 200
    assert [e["amount_paise"] for e in _entries(c, "va", order_id=o["id"])] == [20000]
    c.post(f"/api/orders/{o['id']}/cod-collected", headers=_hdr(S["fin2"]["id"]))
    assert len(_entries(c, order_id=o["id"])) == 1


def test_vendor_rejecting_a_paid_order_reverses_the_sale_with_a_linked_entry(c):
    pa = _product(c, "L-A3", 120.0, "va")
    o = _order(c, [(pa, 1)])
    _pay(c, o)
    assert _fulfil(c, "ua", o["id"], "rejected").status_code == 200
    ents = _entries(c, "va", order_id=o["id"])
    assert [e["type"] for e in ents] == ["SALE_COLLECTED", "SALE_REVERSAL"]
    assert ents[1]["amount_paise"] == -12000 and ents[1]["reverses"] == ents[0]["id"]
    c.portal.call(lambda: L.reconcile_ledger())
    assert len(_entries(c, "va", order_id=o["id"])) == 2


# ====================================================================== refunds reconcile to the paisa
def test_refund_shares_add_up_to_each_vendors_sale_exactly(c):
    pa, pb = _product(c, "L-A4", 33.33, "va"), _product(c, "L-B4", 66.67, "vb")
    o = _order(c, [(pa, 3), (pb, 1)])                                  # A 99.99 / B 66.67
    _pay(c, o)
    for ref, amt in (("P1", 10.0), ("P2", 33.33), ("P3", 0.01), ("FINAL", None)):
        _refund(c, o, amt, ref)
    for vk, sale in (("va", 9999), ("vb", 6667)):
        es = _entries(c, vk, order_id=o["id"])
        assert sum(e["amount_paise"] for e in es if e["type"] == "SALE_COLLECTED") == sale
        assert sum(e["amount_paise"] for e in es if e["type"] == "REFUND") == -sale          # to the paisa, never 1 off
        assert sum(e["amount_paise"] for e in es) == 0
    c.portal.call(lambda: L.reconcile_ledger())
    assert sum(e["amount_paise"] for e in _entries(c, "va", order_id=o["id"])) == 0


def test_random_refund_sequences_always_reconcile_to_the_paisa(c):
    import random
    rnd = random.Random(2026)
    for k in range(25):
        pa = _product(c, f"RR-A{k}", round(rnd.uniform(1, 400), 2), "va")
        pb = _product(c, f"RR-B{k}", round(rnd.uniform(1, 400), 2), "vb")
        o = _order(c, [(pa, rnd.randint(1, 5)), (pb, rnd.randint(1, 4))])
        _pay(c, o)
        remaining = o["total_paise"]
        for i in range(rnd.randint(1, 4)):                                     # partial refunds of awkward sizes
            part = max(1, int(remaining * rnd.uniform(0.05, 0.5)))
            if part >= remaining:
                break
            _refund(c, o, part / 100, f"p{i}")
            remaining -= part
        _refund(c, o, None, "final")                                           # closes the order
        for vk in ("va", "vb"):
            es = _entries(c, vk, order_id=o["id"])
            sale = sum(e["amount_paise"] for e in es if e["type"] == "SALE_COLLECTED")
            assert sale > 0 and sum(e["amount_paise"] for e in es if e["type"] == "REFUND") == -sale, (k, vk)


def test_a_lost_ledger_entry_is_rebuilt_exactly_once_by_the_repair_sweep(c):
    pa = _product(c, "L-A5", 80.0, "va")
    o = _order(c, [(pa, 1)])
    _pay(c, o)
    c.portal.call(lambda: db.vendor_ledger.delete_many({"order_id": o["id"]}))      # simulate a crash that lost the write
    assert _entries(c, order_id=o["id"]) == []
    r = c.get("/api/cron/expire-pending-orders", headers=CRON).json()
    assert r["ledger"]["sales"] >= 1 and [e["amount_paise"] for e in _entries(c, "va", order_id=o["id"])] == [8000]
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert len(_entries(c, "va", order_id=o["id"])) == 1


def test_orders_awaiting_refund_never_reach_the_ledger(c):
    pa = _product(c, "L-A6", 90.0, "va", stock=2)
    o = _order(c, [(pa, 2)])
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"payment_status": "paid", "needs_refund": True}}))
    c.portal.call(lambda: L.reconcile_ledger())
    assert _entries(c, order_id=o["id"]) == []


# ====================================================================== permissions
def test_vendors_see_only_their_own_ledger_and_cannot_write_anything(c):
    pa, pb = _product(c, "L-A7", 10.0, "va"), _product(c, "L-B7", 20.0, "vb")
    o = _order(c, [(pa, 1), (pb, 1)])
    _pay(c, o)
    ha, hb = _hdr(S["ua"]["id"]), _hdr(S["ub"]["id"])
    mine = c.get("/api/vendor/finance/ledger?page_size=100", headers=ha).json()["items"]
    assert mine and all(e["vendor_id"] == S["va"]["id"] for e in mine)
    assert all(e["vendor_id"] == S["vb"]["id"] for e in c.get("/api/vendor/finance/ledger?page_size=100", headers=hb).json()["items"])
    assert c.get("/api/vendor/finance/summary", headers=ha).json()["balances"]["eligible_sales_paise"] != \
        c.get("/api/vendor/finance/summary", headers=hb).json()["balances"]["eligible_sales_paise"]
    for method, url, body in (("post", "/api/admin/finance/settlements", {"vendor_id": S["va"]["id"]}),
                              ("post", f"/api/admin/finance/vendors/{S['va']['id']}/adjustments", {"amount": 5, "reason": "self credit"}),
                              ("put", "/api/admin/finance/policy", {"active": True}),
                              ("get", f"/api/admin/finance/vendors/{S['vb']['id']}/ledger", None),
                              ("post", "/api/admin/finance/reconcile", None)):
        r = getattr(c, method)(url, headers=ha, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (url, r.status_code)
    assert c.post("/api/vendor/finance/settlements", headers=ha, json={}).status_code in (404, 405)    # no vendor write route exists
    for who in ("cust", "genie"):
        assert c.get("/api/vendor/finance/summary", headers=_hdr(S[who]["id"])).status_code == 403
    assert c.get("/api/vendor/finance/summary").status_code == 401


def test_support_admins_can_view_but_not_change_finances(c):
    h = _hdr(S["supp"]["id"])
    assert c.get("/api/admin/finance/vendors", headers=h).status_code == 200
    assert c.post(f"/api/admin/finance/vendors/{S['va']['id']}/adjustments", headers=h, json={"amount": 5, "reason": "not allowed"}).status_code == 403
    assert c.put("/api/admin/finance/policy", headers=h, json={"active": True}).status_code == 403


# ====================================================================== adjustments
def test_adjustments_are_audited_idempotent_and_reversible_never_edited(c):
    h = _hdr(S["fin"]["id"])
    url = f"/api/admin/finance/vendors/{S['vb']['id']}/adjustments"
    r = c.post(url, headers=h, json={"amount": -12.5, "reason": "Damaged goods deduction", "idempotency_key": "k1"})
    assert r.status_code == 200 and r.json()["entry"]["amount_paise"] == -1250 and r.json()["created"] is True
    again = c.post(url, headers=h, json={"amount": -12.5, "reason": "Damaged goods deduction", "idempotency_key": "k1"}).json()
    assert again["created"] is False and again["entry"]["id"] == r.json()["entry"]["id"]          # double-click: still one entry
    fix = c.post(url, headers=h, json={"amount": 12.5, "reason": "Reversal of mistaken deduction", "reverses": r.json()["entry"]["id"]})
    assert fix.status_code == 200 and fix.json()["entry"]["reverses"] == r.json()["entry"]["id"]
    adj = _entries(c, "vb", type="ADJUSTMENT")
    assert [e["amount_paise"] for e in adj] == [-1250, 1250]                                     # history kept, net zero
    assert c.post(url, headers=h, json={"amount": 0, "reason": "zero not allowed"}).status_code == 400
    assert c.post(url, headers=h, json={"amount": 5, "reason": "x"}).status_code == 422
    assert c.post(url, headers=h, json={"amount": 5, "reason": "bad link", "reverses": "nope"}).status_code == 404
    assert c.post(f"/api/admin/finance/vendors/nope/adjustments", headers=h, json={"amount": 5, "reason": "no vendor"}).status_code == 404
    assert c.portal.call(lambda: db.audit_logs.count_documents({"action": "vendor_ledger_adjustment"})) >= 2
    assert not c.portal.call(lambda: db.vendor_ledger.find_one({"id": r.json()["entry"]["id"], "status": {"$ne": "posted"}}))


# ====================================================================== settlements
def _make_money(c, vkey, vendor, price):
    p = _product(c, f"S-{vkey}-{new_id()[:6]}", price, vkey)
    o = _order(c, [(p, 1)])
    _pay(c, o)
    return o


def test_settlements_are_off_until_the_policy_is_explicitly_activated(c):
    assert c.get("/api/admin/finance/policy", headers=_hdr(S["fin"]["id"])).json()["active"] is False
    _make_money(c, "va", S["va"], 500.0)
    r = c.post("/api/admin/finance/settlements", headers=_hdr(S["fin"]["id"]), json={"vendor_id": S["va"]["id"]})
    assert r.status_code == 409 and "not approved" in r.json()["detail"]
    s = c.get("/api/vendor/finance/summary", headers=_hdr(S["ua"]["id"])).json()
    assert s["policy"]["active"] is False and s["policy"]["message"] and s["balances"]["provisional"] is True


def test_full_settlement_lifecycle_with_dual_approval_and_exact_balances(c):
    fin, fin2 = _hdr(S["fin"]["id"]), _hdr(S["fin2"]["id"])
    assert c.put("/api/admin/finance/policy", headers=fin, json={"active": True, "require_dual_approval": True, "min_settlement": 1}).status_code == 200
    before = _bal(c, "vb")
    _make_money(c, "vb", S["vb"], 250.0)
    avail = _bal(c, "vb")["available_for_settlement_paise"]
    assert avail == before["available_for_settlement_paise"] + 25000
    assert c.post("/api/admin/finance/settlements", headers=fin, json={"vendor_id": S["vb"]["id"], "amount": avail / 100 + 0.01}).status_code == 400   # over
    r = c.post("/api/admin/finance/settlements", headers=fin, json={"vendor_id": S["vb"]["id"]})
    assert r.status_code == 200 and r.json()["amount_paise"] == avail and r.json()["status"] == "requested"
    sid = r.json()["id"]
    assert c.post("/api/admin/finance/settlements", headers=fin2, json={"vendor_id": S["vb"]["id"]}).status_code in (400, 409)   # nothing left / one open only
    act = lambda who, a, **kw: c.post(f"/api/admin/finance/settlements/{sid}/action", headers=who, json={"action": a, **kw})
    assert act(fin, "approve").status_code == 403                                       # creator cannot approve (dual approval)
    assert act(fin2, "mark_paid", reference="UTR1").status_code == 400                  # must be approved first
    assert act(fin2, "approve").status_code == 200
    assert act(fin2, "mark_paid", reference="UTR1").status_code == 403                  # approver cannot also pay
    assert act(fin, "mark_paid", reference="").status_code == 400                       # reference required
    assert _bal(c, "vb")["settlement_in_progress_paise"] == avail
    assert act(fin, "mark_paid", reference="UTR-123456").status_code == 200
    assert act(fin, "mark_paid", reference="UTR-123456").status_code == 400             # no double payment
    paid = _entries(c, "vb", type="SETTLEMENT_PAID")
    assert len(paid) == 1 and paid[0]["amount_paise"] == -avail
    b = _bal(c, "vb")
    assert b["settled_paise"] == avail and b["available_for_settlement_paise"] == 0 and b["settlement_in_progress_paise"] == 0
    assert b["pending_settlement_paise"] == b["vendor_payable_paise"] - avail
    mine = c.get("/api/vendor/finance/settlements", headers=_hdr(S["ub"]["id"])).json()["items"]
    assert mine[0]["status"] == "paid" and mine[0]["reference"] == "UTR-123456"


def test_only_one_open_settlement_per_vendor_even_under_concurrency(c):
    fin = _hdr(S["fin"]["id"])
    c.put("/api/admin/finance/policy", headers=fin, json={"active": True})
    _make_money(c, "va", S["va"], 300.0)
    codes = sorted(ThreadPoolExecutor(max_workers=2).map(
        lambda _: c.post("/api/admin/finance/settlements", headers=fin, json={"vendor_id": S["va"]["id"], "amount": 50}).status_code, range(2)))
    assert codes == [200, 409]
    open_one = c.portal.call(lambda: db.settlements.find_one({"vendor_id": S["va"]["id"], "status": "requested"}))
    assert c.post(f"/api/admin/finance/settlements/{open_one['id']}/action", headers=fin, json={"action": "reject", "note": "x"}).status_code == 400   # reason too short
    assert c.post(f"/api/admin/finance/settlements/{open_one['id']}/action", headers=fin, json={"action": "reject", "note": "Wrong amount requested"}).status_code == 200
    assert c.post("/api/admin/finance/settlements", headers=fin, json={"vendor_id": S["va"]["id"], "amount": 50}).status_code == 200   # free again


def test_a_balance_that_shrinks_after_the_request_blocks_payment(c):
    fin = _hdr(S["fin"]["id"])
    c.put("/api/admin/finance/policy", headers=fin, json={"active": True, "require_dual_approval": False})
    c.portal.call(lambda: db.settlements.update_many({"vendor_id": S["vb"]["id"], "status": {"$in": ["requested", "approved"]}}, {"$set": {"status": "rejected"}}))
    o = _make_money(c, "vb", S["vb"], 400.0)
    avail = _bal(c, "vb")["available_for_settlement_paise"]
    sid = c.post("/api/admin/finance/settlements", headers=fin, json={"vendor_id": S["vb"]["id"], "amount": avail / 100}).json()["id"]
    assert c.post(f"/api/admin/finance/settlements/{sid}/action", headers=fin, json={"action": "approve"}).status_code == 200
    _refund(c, o, 100.0, "SHRINK")                                                       # a refund lands in between
    r = c.post(f"/api/admin/finance/settlements/{sid}/action", headers=fin, json={"action": "mark_paid", "reference": "UTR-777"})
    assert r.status_code == 409 and _entries(c, "vb", source_key=f"settle:{sid}") == []          # nothing was paid out
    assert c.portal.call(lambda: db.settlements.find_one({"id": sid}))["status"] == "approved"


def test_paid_settlement_always_has_its_ledger_entry_even_after_a_crash(c):
    s = c.portal.call(lambda: db.settlements.find_one({"vendor_id": S["vb"]["id"], "status": "paid"}))
    c.portal.call(lambda: db.vendor_ledger.delete_many({"source_key": f"settle:{s['id']}"}))
    r = c.post("/api/admin/finance/reconcile", headers=_hdr(S["fin"]["id"])).json()
    assert r["settlements"] == 1
    assert len(_entries(c, "vb", source_key=f"settle:{s['id']}")) == 1


# ====================================================================== statement + COD
def test_statement_csv_is_vendor_scoped_exact_and_formula_safe(c):
    h = _hdr(S["fin"]["id"])
    c.post(f"/api/admin/finance/vendors/{S['va']['id']}/adjustments", headers=h, json={"amount": 1, "reason": "=HYPERLINK(\"http://evil\")"})
    r = c.get("/api/vendor/finance/statement.csv", headers=_hdr(S["ua"]["id"]))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    body = r.text
    assert "'=HYPERLINK" in body and ",=HYPERLINK" not in body
    assert S["vb"]["id"] not in body and "SALE_COLLECTED" in body
    assert c.get("/api/vendor/finance/statement.csv?date_from=bad", headers=_hdr(S["ua"]["id"])).status_code == 400


def test_cod_short_collection_is_held_until_an_admin_resolves_it(c):
    pa = _product(c, "L-A8", 200.0, "va")
    o = _order(c, [(pa, 1)], method="cod", seller="HGSEL")                                # total 210.00
    r = c.post(f"/api/orders/{o['id']}/cod-collected", headers=_hdr(S["fin2"]["id"]), json={"amount_collected": 180.0})
    assert r.status_code == 200 and r.json()["discrepancy"] is True
    got = c.portal.call(lambda: db.orders.find_one({"id": o["id"]}))
    assert got["payment_status"] == "cod_discrepancy" and got["cod_discrepancy"]["expected_paise"] == 21000 and got["cod_discrepancy"]["collected_paise"] == 18000
    assert _entries(c, order_id=o["id"]) == [] and c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0
    assert c.post(f"/api/orders/{o['id']}/cod-collected", headers=_hdr(S["fin2"]["id"])).json().get("already") is True      # cannot be bypassed
    states = c.get("/api/vendor/finance/cod", headers=_hdr(S["ua"]["id"])).json()
    assert next(x for x in states["items"] if x["order_id"] == o["id"])["state"] == "discrepancy" and states["summary"]["discrepancy_paise"] >= 20000
    url = f"/api/admin/finance/cod-discrepancies/{o['id']}/resolve"
    assert c.post(url, headers=_hdr(S["genie"]["id"]), json={"resolution": "confirm_full", "note": "I say so"}).status_code == 403
    assert c.post(url, headers=_hdr(S["supp"]["id"]), json={"resolution": "confirm_full", "note": "support cannot"}).status_code == 403
    assert c.post(url, headers=_hdr(S["fin"]["id"]), json={"resolution": "maybe", "note": "invalid choice"}).status_code == 400
    assert c.post(url, headers=_hdr(S["fin"]["id"]), json={"resolution": "accept_short", "note": "Customer paid 180, balance waived"}).status_code == 200
    assert [e["amount_paise"] for e in _entries(c, "va", order_id=o["id"])] == [17143]       # 200.00 x 180.00/210.00, half-up
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) == 0  # held: no commission on a short collection
    assert c.post(url, headers=_hdr(S["fin"]["id"]), json={"resolution": "confirm_full", "note": "second attempt"}).status_code == 404   # already resolved


def test_cod_full_confirmation_of_a_discrepancy_credits_commission_and_the_full_sale(c):
    pa = _product(c, "L-A9", 200.0, "va")
    o = _order(c, [(pa, 1)], method="cod", seller="HGSEL")
    c.post(f"/api/orders/{o['id']}/cod-collected", headers=_hdr(S["fin2"]["id"]), json={"amount_collected": 100.0})
    r = c.post(f"/api/admin/finance/cod-discrepancies/{o['id']}/resolve", headers=_hdr(S["fin"]["id"]),
               json={"resolution": "confirm_full", "note": "Verified full cash received later"})
    assert r.status_code == 200
    assert [e["amount_paise"] for e in _entries(c, "va", order_id=o["id"])] == [20000]
    assert c.portal.call(lambda: db.commissions.count_documents({"order_id": o["id"]})) >= 1


def test_cod_reconciliation_flags_cash_that_is_overdue(c):
    pa = _product(c, "L-A10", 150.0, "va")
    o = _order(c, [(pa, 1)], method="cod")
    for st in ("accepted", "packed"):
        assert _fulfil(c, "ua", o["id"], st).status_code == 200
    assert _fulfil(c, "ua", o["id"], "dispatched", carrier="BD", tracking_number="T9").status_code == 200
    assert _fulfil(c, "ua", o["id"], "delivered", note="Signed by recipient").status_code == 200
    h = _hdr(S["ua"]["id"])
    row = lambda: next(x for x in c.get("/api/vendor/finance/cod", headers=h).json()["items"] if x["order_id"] == o["id"])
    assert row()["state"] == "delivered_awaiting_cash" and row()["overdue"] is False
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"fulfilments.0.events.$[e].at": old}}, array_filters=[{"e.status": "delivered"}]))
    assert row()["overdue"] is True and row()["days_waiting"] >= 9
    summary = c.get("/api/vendor/finance/cod", headers=h).json()["summary"]
    assert summary["overdue_paise"] >= 15000 and summary["delivered_awaiting_cash_paise"] >= 15000
    only = c.get("/api/vendor/finance/cod?state=delivered_awaiting_cash", headers=h).json()
    assert all(x["state"] == "delivered_awaiting_cash" for x in only["items"])


def test_money_identity_holds_for_every_vendor(c):
    for vk in ("va", "vb"):
        b = _bal(c, vk)
        rows = c.portal.call(lambda vk=vk: db.vendor_ledger.find({"vendor_id": S[vk]["id"]}).to_list(1000))
        total = sum(r["amount_paise"] for r in rows)
        assert b["vendor_payable_paise"] - b["settled_paise"] == total == b["pending_settlement_paise"]
        assert all(isinstance(r["amount_paise"], int) and r["amount_paise"] != 0 for r in rows)
