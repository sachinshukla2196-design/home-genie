"""Customer cancellation, returns & replacements, staged refund cases.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.

Run this file in its own pytest process (e.g. `pytest tests/<file> -n 0`): it sets environment variables and imports
`server` at module level, so combining it with another in-process test file in one run shares that state.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_returns_test", "JWT_SECRET": "returns-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import shop_routes  # noqa: E402
import stock  # noqa: E402
import returns_routes  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
CRON = {"Authorization": "Bearer cron-test-secret"}
S = {}


class Crash(Exception):
    pass


def crash_at(point, nth=1):
    state = {"n": 0}

    def hook(p, **ctx):
        if p == point:
            state["n"] += 1
            if state["n"] == nth:
                stock._FAULT = None
                raise Crash(point)
    stock._FAULT = hook


@pytest.fixture(autouse=True)
def _reset():
    yield
    stock._FAULT = None


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
            S["cust"], S["cust2"] = await user("9100000701", "distributor", "HGC", "red"), await user("9100000702", "distributor", "HGC2", "red")
            S["admin"], S["fin"] = await user("9100000703", "super_admin", "HGADM"), await user("9100000704", "accounts_admin", "HGFIN")
            S["supp"], S["plain"] = await user("9100000705", "support_admin", "HGSUPP"), await user("9100000706", "admin", "HGPLAIN")
            S["ua"], S["ub"] = await user("9100000707", "vendor", "VDA"), await user("9100000708", "vendor", "VDB")
            S["va"], S["vb"] = await vendor(S["ua"], "Vendor A"), await vendor(S["ub"], "Vendor B")
            await db.business_settings.update_one({"id": "business_settings"}, {"$set": {"gst_percent": 5.0, "cod_fee": 0.0}}, upsert=True)
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _product(c, sku, price, vendor="va", stock_qty=100, **extra):
    async def mk():
        v = S[vendor]
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": price + 100, "selling_price": price, "gst_percent": 5,
             "stock": stock_qty, "category": "Sarees", "options": [], "vendor_id": v["id"], "vendor_name": v["business_name"],
             "is_active": True, "approval_status": "approved", "created_at": now_iso(), **extra}
        await db.products.insert_one(dict(p))
        return p
    return c.portal.call(mk)


def _stock(c, pid):
    return c.portal.call(lambda: db.products.find_one({"id": pid}))["stock"]


def _order(c, lines, method="cod", who="cust"):
    body = {"items": [{"product_id": p["id"], "quantity": q} for p, q in lines], "address": ADDR, "payment_method": method}
    r = c.post("/api/orders", json=body, headers=_hdr(S[who]["id"]))
    assert r.status_code == 200, r.text
    return r.json()


def _pay(c, o):
    sid = "cs_" + o["id"][:12]
    c.portal.call(lambda: db.payment_transactions.insert_one(
        {"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"], "amount": o["total"],
         "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    c.portal.call(lambda: shop_routes._process_paid_order(sid))


def _get(c, oid):
    return c.portal.call(lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _fulfil(c, vkey, oid, *statuses):
    for st in statuses:
        extra = {"carrier": "BD", "tracking_number": "T1"} if st == "dispatched" else {}
        r = c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=_hdr(S[vkey]["id"]), json={"status": st, "note": "Signed by recipient", **extra})
        assert r.status_code == 200, (st, r.text)


def _delivered(c, lines, vkey="ua", method="cod", who="cust"):
    o = _order(c, lines, method=method, who=who)
    if method == "online":
        _pay(c, o)
    _fulfil(c, vkey, o["id"], "accepted", "packed", "dispatched", "delivered")
    return o


def _cancel(c, oid, who="cust", reason="Changed my mind"):
    return c.post(f"/api/orders/{oid}/cancel", headers=_hdr(S[who]["id"]), json={"reason": reason})


def _cases(c, **q):
    return c.portal.call(lambda: db.refund_cases.find(q, {"_id": 0}).to_list(100))


# ================================================================ customer cancellation
def test_untouched_cod_order_is_cancelled_immediately_and_stock_returns_once(c):
    p = _product(c, "CX-1", 100)
    o = _order(c, [(p, 3)])
    assert _stock(c, p["id"]) == 97
    r = _cancel(c, o["id"])
    assert r.status_code == 200 and r.json()["outcome"] == "cancelled" and r.json()["refund_case"] is None
    got = _get(c, o["id"])
    assert got["status"] == "cancelled" and got["cancel_reason"] == "customer_cancelled" and got["fulfilments"][0]["status"] == "cancelled"
    assert _stock(c, p["id"]) == 100 and got["restock_intents"] == []
    assert _cancel(c, o["id"]).status_code == 400                                   # already cancelled
    assert _stock(c, p["id"]) == 100
    assert _cancel(c, o["id"], who="cust2").status_code == 404                      # someone else's order
    assert c.post(f"/api/orders/{o['id']}/cancel", headers=_hdr(S["cust"]["id"]), json={"reason": "x"}).status_code == 422


def test_paid_online_order_cancel_opens_a_refund_case_and_reverses_the_vendor_sale(c):
    p = _product(c, "CX-2", 200)
    o = _order(c, [(p, 1)], method="online")
    _pay(c, o)
    assert any(e["type"] == "SALE_COLLECTED" for e in c.portal.call(lambda: db.vendor_ledger.find({"order_id": o["id"]}).to_list(10)))
    r = _cancel(c, o["id"])
    assert r.status_code == 200 and r.json()["refund_case"]
    cases = _cases(c, order_id=o["id"])
    assert len(cases) == 1 and cases[0]["kind"] == "cancellation" and cases[0]["status"] == "awaiting_review"
    assert cases[0]["amount_paise"] == o["total_paise"] and _stock(c, p["id"]) == 100
    types = [e["type"] for e in c.portal.call(lambda: db.vendor_ledger.find({"order_id": o["id"]}).sort("posted_at", 1).to_list(10))]
    assert types == ["SALE_COLLECTED", "SALE_REVERSAL"]
    _cancel(c, o["id"])
    assert len(_cases(c, order_id=o["id"])) == 1                                     # still one case


def test_unpaid_online_order_can_be_cancelled_and_frees_its_stock(c):
    p = _product(c, "CX-3", 100)
    o = _order(c, [(p, 2)], method="online")
    assert _stock(c, p["id"]) == 98
    assert _cancel(c, o["id"]).json()["outcome"] == "cancelled" and _stock(c, p["id"]) == 100
    assert _cases(c, order_id=o["id"]) == []


def test_after_vendor_acceptance_cancellation_becomes_a_request_and_dispatch_blocks_it(c):
    p = _product(c, "CX-4", 100)
    o = _order(c, [(p, 1)])
    _fulfil(c, "ua", o["id"], "accepted")
    r = _cancel(c, o["id"])
    assert r.status_code == 200 and r.json()["outcome"] == "requested"
    got = _get(c, o["id"])
    assert got["status"] != "cancelled" and got["cancel_requested"]["reason"] == "Changed my mind" and _stock(c, p["id"]) == 99
    _cancel(c, o["id"], reason="Please cancel")
    assert _get(c, o["id"])["cancel_requested"]["reason"] == "Changed my mind"       # raised once
    _fulfil(c, "ua", o["id"], "packed", "dispatched")
    assert _cancel(c, o["id"]).status_code == 409 and "dispatched" in _cancel(c, o["id"]).json()["detail"]


def test_cancel_crash_is_replayed_by_recovery_without_double_restock(c):
    p = _product(c, "CX-5", 100)
    o = _order(c, [(p, 2)])
    crash_at("before_line")
    with pytest.raises(Crash):
        _cancel(c, o["id"])
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, p["id"]) == 98          # decision recorded, stock not yet returned
    c.portal.call(lambda: stock.run_recovery(min_age_s=0))
    c.portal.call(lambda: stock.run_recovery(min_age_s=0))
    assert _stock(c, p["id"]) == 100


# ================================================================ staged refund cases
def _open_case(c, price=100.0, method="online"):
    p = _product(c, f"RC-{new_id()[:6]}", price)
    o = _order(c, [(p, 1)], method=method)
    _pay(c, o)
    _cancel(c, o["id"])
    return o, _cases(c, order_id=o["id"])[0]


def _act(c, who, cid, action, **kw):
    return c.post(f"/api/admin/refund-cases/{cid}/action", headers=_hdr(S[who]["id"]), json={"action": action, **kw})


def test_refund_is_recorded_only_after_an_authorised_confirmation(c):
    o, case = _open_case(c)
    cid = case["id"]
    assert _act(c, "fin", cid, "confirm", reference="UTR1", confirmation_type="manual_reconciliation", note="x" * 12).status_code == 400   # must initiate first
    assert _act(c, "fin", cid, "initiate", amount=case["amount_paise"] / 100 + 1).status_code == 400                                         # cannot raise
    assert _act(c, "plain", cid, "initiate", method="upi", amount=case["amount_paise"] / 100 - 5).status_code == 200                           # may lower
    assert _get(c, o["id"]).get("refunded_paise") in (None, 0)                                                                               # nothing recorded yet
    lowered = case["amount_paise"] - 500
    # confirmation rules
    assert _act(c, "supp", cid, "confirm", reference="UTR1", confirmation_type="manual_reconciliation", note="x" * 12).status_code == 403   # finance only
    assert _act(c, "fin", cid, "confirm", reference="U", confirmation_type="manual_reconciliation", note="x" * 12).status_code == 400
    assert _act(c, "fin", cid, "confirm", reference="UTR1", confirmation_type="manual_reconciliation", note="short").status_code == 400
    assert _act(c, "fin", cid, "confirm", reference="UTR1", confirmation_type="bogus", note="x" * 12).status_code == 400
    r = _act(c, "fin", cid, "confirm", reference="UTR1", confirmation_type="provider")
    assert r.status_code == 409 and "not configured" in r.json()["detail"]                                                                    # never pretends to verify
    assert _get(c, o["id"]).get("refunded_paise") in (None, 0)
    ok = _act(c, "fin", cid, "confirm", reference="UTR-OK-1", confirmation_type="manual_reconciliation", note="Verified in bank statement 24 Oct")
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
    got = _get(c, o["id"])
    assert got["refunded_paise"] == lowered and got["payment_status"] == "partially_refunded"
    assert _act(c, "fin", cid, "confirm", reference="UTR-OK-1", confirmation_type="manual_reconciliation", note="x" * 12).status_code == 400   # already confirmed
    assert _act(c, "fin", cid, "resolve", note="Customer acknowledged refund").json()["status"] == "resolved"
    assert [e["status"] for e in _cases(c, id=cid)[0]["events"]] == ["awaiting_review", "initiated", "confirmed", "resolved"]


def test_confirming_twice_concurrently_refunds_once(c):
    o, case = _open_case(c)
    _act(c, "fin", case["id"], "initiate", method="upi")
    body = {"reference": "UTR-RACE", "confirmation_type": "manual_reconciliation", "note": "Verified against bank statement"}
    codes = sorted(ThreadPoolExecutor(max_workers=2).map(lambda _: _act(c, "fin", case["id"], "confirm", **body).status_code, range(2)))
    assert codes[0] == 200 and codes[1] in (400, 409)
    assert _get(c, o["id"])["refunded_paise"] == o["total_paise"] and c.portal.call(lambda: db.order_refunds.count_documents({"order_id": o["id"]})) == 1


def test_confirm_resumes_cleanly_after_a_crash_between_the_books_and_the_case(c):
    o, case = _open_case(c)
    _act(c, "fin", case["id"], "initiate", method="upi")
    # the process died after the financial reversal was recorded but before the case was marked confirmed
    c.portal.call(lambda: shop_routes.reverse_order_financials(o["id"], {"id": S["fin"]["id"]}, None, case["amount_paise"] / 100, "UTR-CRASH", "t",
                                                               case_id=case["id"]))
    r = _act(c, "fin", case["id"], "confirm", reference="UTR-CRASH", confirmation_type="manual_reconciliation", note="Verified in the bank statement")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert _get(c, o["id"])["refunded_paise"] == o["total_paise"]                             # not refunded twice
    assert c.portal.call(lambda: db.order_refunds.count_documents({"order_id": o["id"]})) == 1


def test_a_reference_cannot_be_reused_for_a_different_case_on_the_same_order(c):
    o, case = _open_case(c)
    c.portal.call(lambda: shop_routes.reverse_order_financials(o["id"], {"id": "a"}, None, 10.0, "UTR-REUSED", "t"))     # a different, earlier refund
    _act(c, "fin", case["id"], "initiate", method="upi", amount=20.0)
    r = _act(c, "fin", case["id"], "confirm", reference="UTR-REUSED", confirmation_type="manual_reconciliation", note="Verified in the bank statement")
    assert r.status_code == 409


def test_failed_refunds_can_be_retried_and_every_transition_is_validated(c):
    o, case = _open_case(c)
    cid = case["id"]
    assert _act(c, "fin", cid, "fail", note="bank down").status_code == 400                   # cannot fail before it started
    _act(c, "fin", cid, "initiate", method="bank_transfer")
    assert _act(c, "fin", cid, "fail", note="no").status_code == 400                          # reason required
    assert _act(c, "fin", cid, "fail", note="Bank transfer bounced").json()["status"] == "failed"
    assert _act(c, "fin", cid, "retry", method="upi").json()["status"] == "initiated"
    assert _act(c, "fin", cid, "resolve", note="x").status_code == 400
    assert _act(c, "fin", cid, "resolve", note="Customer withdrew the complaint").json()["outcome"] == "no_refund"
    assert _act(c, "fin", cid, "initiate").status_code == 400                                  # terminal
    assert _act(c, "fin", "nope", "initiate").status_code == 404


def test_the_one_step_refund_action_also_settles_the_open_case(c):
    o, case = _open_case(c)
    r = c.post(f"/api/admin/orders/{o['id']}/refund", headers=_hdr(S["fin"]["id"]), json={"reference": "UTR-LEGACY"})
    assert r.status_code == 200
    assert _cases(c, id=case["id"])[0]["status"] == "confirmed" and _cases(c, id=case["id"])[0]["reference"] == "UTR-LEGACY"


def test_queue_lists_every_state_and_late_payments_get_a_case_automatically(c):
    p = _product(c, "RQ-1", 90, stock_qty=1)
    o = _order(c, [(p, 1)], method="online")
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"payment_status": "paid", "needs_refund": True, "status": "cancelled",
                                                                         "needs_refund_reason": "paid_after_timeout_out_of_stock", "needs_refund_at": now_iso()}}))
    h = _hdr(S["fin"]["id"])
    q = c.get("/api/admin/refund-cases?state=open", headers=h).json()
    late = next(x for x in q["items"] if x["order_id"] == o["id"])
    assert late["kind"] == "late_payment" and late["status"] == "awaiting_review" and late["amount_paise"] == o["total_paise"]
    assert set(q["counts"]) == {"awaiting_review", "initiated", "confirmed", "failed", "resolved"}
    c.get("/api/admin/refund-cases", headers=h)
    assert len(_cases(c, order_id=o["id"])) == 1                                              # created once
    assert c.get("/api/admin/refund-cases?state=bogus", headers=h).status_code == 400
    for who in ("ua", "cust"):
        assert c.get("/api/admin/refund-cases", headers=_hdr(S[who]["id"])).status_code == 403
    assert c.get("/api/admin/refund-cases").status_code == 401


# ================================================================ returns
def _return(c, o, lines, who="cust", kind="return", reason="Item arrived damaged", photos=None):
    return c.post(f"/api/orders/{o['id']}/returns", headers=_hdr(S[who]["id"]),
                  json={"kind": kind, "items": [{"product_id": p["id"], "quantity": q} for p, q in lines], "reason": reason, "photos": photos or []})


def _vact(c, vkey, rid, action, **kw):
    return c.post(f"/api/vendor/returns/{rid}/action", headers=_hdr(S[vkey]["id"]), json={"action": action, **kw})


def _inspect(c, vkey, rid, outcomes, note="Inspected on receipt"):
    return c.post(f"/api/vendor/returns/{rid}/inspection", headers=_hdr(S[vkey]["id"]),
                  json={"lines": [{"index": i, "outcome": o} for i, o in enumerate(outcomes)], "note": note})


def _case_row(c, rid):
    return c.portal.call(lambda: db.return_cases.find_one({"id": rid}, {"_id": 0}))


def test_return_requests_are_validated_against_delivery_window_quantity_and_policy(c):
    p, q = _product(c, "RT-1", 100), _product(c, "RT-2", 50, returnable=False)
    o = _order(c, [(p, 3), (q, 1)])
    assert _return(c, o, [(p, 1)]).status_code == 400                                         # not delivered yet
    _fulfil(c, "ua", o["id"], "accepted", "packed", "dispatched", "delivered")
    assert _return(c, o, [(p, 4)]).status_code == 400 and "at most 3" in _return(c, o, [(p, 4)]).json()["detail"]
    assert _return(c, o, [(q, 1)]).status_code == 400 and "not eligible" in _return(c, o, [(q, 1)]).json()["detail"]
    assert _return(c, o, [(p, 1)], who="cust2").status_code == 404
    assert _return(c, o, [(p, 1)], reason="bad").status_code == 422
    assert _return(c, o, [(p, 1)], photos=["javascript:alert(1)"]).status_code == 422
    assert _return(c, o, [(p, 1)], kind="swap").status_code == 400
    ok = _return(c, o, [(p, 2)], photos=["/api/files/x.png", "https://cdn.example.com/a.jpg"])
    assert ok.status_code == 200 and ok.json()["cases"][0]["status"] == "requested" and ok.json()["cases"][0]["suggested_refund_paise"] == 21000   # 2 x 100 + 5% GST
    assert _return(c, o, [(p, 2)]).status_code == 400                                         # only 1 left to return
    assert _return(c, o, [(p, 1)]).status_code == 200


def test_the_return_window_is_configurable_and_enforced_server_side(c):
    p = _product(c, "RT-3", 100)
    o = _delivered(c, [(p, 1)])
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    c.portal.call(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"fulfilments.0.events.$[e].at": old}}, array_filters=[{"e.status": "delivered"}]))
    pol = lambda who, **kw: c.put("/api/admin/returns/policy", headers=_hdr(S[who]["id"]), json=kw)
    try:
        r = _return(c, o, [(p, 1)])
        assert r.status_code == 400 and "7 days" in r.json()["detail"]
        assert pol("supp", window_days=30).status_code == 403                                 # support admins cannot change policy
        assert pol("ua", window_days=30).status_code == 403
        assert pol("admin", window_days=30, excluded_categories=[]).status_code == 200
        assert _return(c, o, [(p, 1)]).status_code == 200                                     # now inside the 30-day window
        assert pol("admin", window_days=30, enabled=False).status_code == 200
        assert _return(c, o, [(p, 1)]).status_code == 400
        pub = c.get("/api/returns/policy", headers=_hdr(S["cust"]["id"])).json()
        assert pub["enabled"] is False and pub["provisional"] is False
        assert pol("admin", window_days=30, enabled=True, excluded_categories=["Sarees"]).status_code == 200
        assert "not eligible" in _return(c, o, [(p, 1)]).json()["detail"]                    # excluded category
    finally:
        pol("admin", window_days=7, enabled=True, excluded_categories=[])                     # never leak policy into other tests


def test_a_mixed_vendor_return_request_is_split_per_vendor(c):
    pa, pb = _product(c, "RT-4A", 100, "va"), _product(c, "RT-4B", 100, "vb")
    o = _order(c, [(pa, 1), (pb, 1)])
    _fulfil(c, "ua", o["id"], "accepted", "packed", "dispatched", "delivered")
    _fulfil(c, "ub", o["id"], "accepted", "packed", "dispatched", "delivered")
    cases = _return(c, o, [(pa, 1), (pb, 1)]).json()["cases"]
    assert sorted(x["vendor_id"] for x in cases) == sorted([S["va"]["id"], S["vb"]["id"]]) and all(len(x["lines"]) == 1 for x in cases)
    a_case = next(x for x in cases if x["vendor_id"] == S["va"]["id"])
    assert c.get(f"/api/vendor/returns/{a_case['id']}", headers=_hdr(S["ub"]["id"])).status_code == 404            # vendor isolation
    assert _vact(c, "ub", a_case["id"], "approve").status_code == 404
    assert all(x["vendor_id"] == S["vb"]["id"] for x in c.get("/api/vendor/returns", headers=_hdr(S["ub"]["id"])).json()["items"])
    assert c.get("/api/vendor/returns", headers=_hdr(S["cust"]["id"])).status_code == 403


def _approved_received(c, price=100.0, qty=3, ret_qty=3, kind="return"):
    p = _product(c, f"RF-{new_id()[:6]}", price, stock_qty=50)
    o = _delivered(c, [(p, qty)])
    rid = _return(c, o, [(p, ret_qty)], kind=kind).json()["cases"][0]["id"]
    assert _vact(c, "ua", rid, "approve").status_code == 200
    assert c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={"carrier": "DTDC", "tracking_number": "RET1"}).status_code == 200
    assert _vact(c, "ua", rid, "receive").status_code == 200
    return p, o, rid


def test_returned_goods_restock_only_after_inspection_only_resellable_and_only_once(c):
    p = _product(c, "RF-MAIN", 100, stock_qty=50)
    o = _delivered(c, [(p, 4)])
    assert _stock(c, p["id"]) == 46
    # two separate return lines: one resellable, one damaged
    cases = _return(c, o, [(p, 3)]).json()["cases"]
    rid = cases[0]["id"]
    assert _inspect(c, "ua", rid, ["resellable"]).status_code == 409                          # not received yet
    _vact(c, "ua", rid, "approve")
    assert c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={}).status_code == 200
    assert _stock(c, p["id"]) == 46                                                          # in transit: nothing restocked
    assert _vact(c, "ua", rid, "receive").status_code == 200
    assert _stock(c, p["id"]) == 46                                                          # received but NOT inspected: still nothing
    assert _inspect(c, "ua", rid, []).status_code == 422 and _inspect(c, "ua", rid, ["maybe"]).status_code == 400
    assert _inspect(c, "ub", rid, ["resellable"]).status_code == 404                          # another vendor cannot decide
    codes = sorted(ThreadPoolExecutor(max_workers=2).map(lambda _: _inspect(c, "ua", rid, ["resellable"]).status_code, range(2)))
    assert codes == [200, 409]                                                               # concurrent inspections: exactly one wins
    assert _stock(c, p["id"]) == 49                                                          # +3 resellable, once
    assert _case_row(c, rid)["status"] == "refund_pending"
    rc = _cases(c, return_case_id=rid)
    assert len(rc) == 1 and rc[0]["kind"] == "return" and rc[0]["amount_paise"] == 31500 and rc[0]["vendor_id"] == S["va"]["id"]
    c.portal.call(returns_routes.reconcile_returns)
    c.portal.call(lambda: stock.run_recovery(min_age_s=0))
    assert _stock(c, p["id"]) == 49 and len(_cases(c, return_case_id=rid)) == 1              # repair sweeps change nothing


def test_damaged_returns_are_never_restocked_and_mixed_outcomes_restock_only_good_lines(c):
    p1, p2 = _product(c, "RF-D1", 100, stock_qty=20), _product(c, "RF-D2", 100, stock_qty=20)
    o = _delivered(c, [(p1, 2), (p2, 2)])
    rid = _return(c, o, [(p1, 2), (p2, 1)]).json()["cases"][0]["id"]
    _vact(c, "ua", rid, "approve")
    c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={})
    _vact(c, "ua", rid, "receive")
    assert _inspect(c, "ua", rid, ["damaged", "resellable"]).status_code == 200
    assert _stock(c, p1["id"]) == 18 and _stock(c, p2["id"]) == 19                            # only p2's returned unit went back
    moves = c.portal.call(lambda: db.stock_movements.find({"order_id": o["id"], "reason": "return_inspected_resellable"}).to_list(10))
    assert [(m["product_id"], m["delta"]) for m in moves] == [(p2["id"], 1)]


def test_return_refund_flows_through_a_case_and_credits_back_only_the_returning_vendor(c):
    pa, pb = _product(c, "RF-V1", 100, "va", stock_qty=20), _product(c, "RF-V2", 100, "vb", stock_qty=20)
    o = _order(c, [(pa, 1), (pb, 1)], method="online")
    _pay(c, o)
    _fulfil(c, "ua", o["id"], "accepted", "packed", "dispatched", "delivered")
    _fulfil(c, "ub", o["id"], "accepted", "packed", "dispatched", "delivered")
    rid = next(x for x in _return(c, o, [(pa, 1)]).json()["cases"])["id"]
    _vact(c, "ua", rid, "approve")
    c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={})
    _vact(c, "ua", rid, "receive")
    _inspect(c, "ua", rid, ["resellable"])
    case = _cases(c, return_case_id=rid)[0]
    _act(c, "fin", case["id"], "initiate", method="upi")
    assert _case_row(c, rid)["status"] == "refund_pending"
    assert _act(c, "fin", case["id"], "confirm", reference="UTR-RET-1", confirmation_type="manual_reconciliation", note="Verified in the bank statement").status_code == 200
    assert _case_row(c, rid)["status"] == "refunded"
    ent = lambda vk: c.portal.call(lambda: db.vendor_ledger.find({"vendor_id": S[vk]["id"], "order_id": o["id"]}).to_list(10))
    assert [e["amount_paise"] for e in ent("va") if e["type"] == "REFUND"] == [-10000]        # vendor A: the returned item's value
    assert [e for e in ent("vb") if e["type"] == "REFUND"] == []                              # vendor B untouched
    assert _get(c, o["id"])["refunded_paise"] == case["amount_paise"] == 10500


def test_a_vendor_may_contest_but_never_outright_reject_and_the_admin_decides(c):
    p = _product(c, "RF-C1", 100)
    o = _delivered(c, [(p, 1)])
    rid = _return(c, o, [(p, 1)]).json()["cases"][0]["id"]
    assert _vact(c, "ua", rid, "reject", note="no thanks").status_code == 400               # there is no vendor 'reject'
    assert _vact(c, "ua", rid, "contest", note="x").status_code == 400
    assert _vact(c, "ua", rid, "contest", note="Customer used the product").json()["status"] == "contested"
    assert _vact(c, "ua", rid, "approve").status_code == 409                                 # once contested only an admin decides
    ok = c.post(f"/api/admin/returns/{rid}/decision", headers=_hdr(S["fin"]["id"]), json={"decision": "approve", "note": "Reviewed the photos"})
    assert ok.status_code == 200 and _case_row(c, rid)["status"] == "approved"
    assert c.post(f"/api/admin/returns/{rid}/decision", headers=_hdr(S["ua"]["id"]), json={"decision": "approve", "note": "vendor tries"}).status_code == 403


def test_admin_can_reject_a_return_and_the_customer_is_told(c):
    p = _product(c, "RF-C3", 100)
    o = _delivered(c, [(p, 1)])
    rid = _return(c, o, [(p, 1)]).json()["cases"][0]["id"]
    _vact(c, "ua", rid, "contest", note="Looks used, see photos")
    url = f"/api/admin/returns/{rid}/decision"
    assert c.post(url, headers=_hdr(S["ua"]["id"]), json={"decision": "reject", "note": "vendor tries"}).status_code == 403
    assert c.post(url, headers=_hdr(S["admin"]["id"]), json={"decision": "maybe", "note": "invalid one"}).status_code == 400
    assert c.post(url, headers=_hdr(S["admin"]["id"]), json={"decision": "reject", "note": "Used item, outside policy"}).json()["status"] == "rejected"
    assert c.post(url, headers=_hdr(S["admin"]["id"]), json={"decision": "approve", "note": "second try"}).status_code == 409     # final
    assert c.portal.call(lambda: db.notifications.count_documents({"user_id": S["cust"]["id"], "title": "Return declined"})) >= 1


def test_replacement_flow_decrements_stock_once_and_needs_inspection_first(c):
    p = _product(c, "RF-R1", 100, stock_qty=10)
    o = _delivered(c, [(p, 2)])
    assert _stock(c, p["id"]) == 8
    rid = _return(c, o, [(p, 1)], kind="replacement").json()["cases"][0]["id"]
    _vact(c, "ua", rid, "approve")
    c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={})
    _vact(c, "ua", rid, "receive")
    assert _vact(c, "ua", rid, "replacement_dispatched", carrier="BD", tracking_number="R1").status_code == 409          # inspect first
    assert _inspect(c, "ua", rid, ["damaged"]).status_code == 200
    assert _case_row(c, rid)["status"] == "replacement_due" and _cases(c, return_case_id=rid) == []                       # no refund case
    assert _stock(c, p["id"]) == 8
    assert _vact(c, "ua", rid, "replacement_dispatched", carrier="", tracking_number="").status_code == 400
    assert _vact(c, "ua", rid, "replacement_dispatched", carrier="BD", tracking_number="R1").status_code == 200
    assert _stock(c, p["id"]) == 7 and _case_row(c, rid)["status"] == "closed"
    assert _vact(c, "ua", rid, "replacement_dispatched", carrier="BD", tracking_number="R1").status_code == 409
    assert _stock(c, p["id"]) == 7


def test_replacement_without_stock_is_refused_and_changes_nothing(c):
    p = _product(c, "RF-R2", 100, stock_qty=1)
    o = _delivered(c, [(p, 1)])
    assert _stock(c, p["id"]) == 0
    rid = _return(c, o, [(p, 1)], kind="replacement").json()["cases"][0]["id"]
    _vact(c, "ua", rid, "approve")
    c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={})
    _vact(c, "ua", rid, "receive")
    _inspect(c, "ua", rid, ["damaged"])
    assert _vact(c, "ua", rid, "replacement_dispatched", carrier="BD", tracking_number="R2").status_code == 409
    assert _stock(c, p["id"]) == 0 and _case_row(c, rid)["status"] == "replacement_due"


@pytest.mark.parametrize("point,stock_at_crash", [("before_line", 18), ("before_decision", 20)])
def test_interrupted_inspection_is_finished_exactly_once_by_the_repair_sweep(c, point, stock_at_crash):
    p = _product(c, f"RF-X-{point}", 100, stock_qty=20)
    o = _delivered(c, [(p, 2)])
    rid = _return(c, o, [(p, 2)]).json()["cases"][0]["id"]
    _vact(c, "ua", rid, "approve")
    c.post(f"/api/returns/{rid}/ship", headers=_hdr(S["cust"]["id"]), json={})
    _vact(c, "ua", rid, "receive")
    crash_at(point)                                                                          # dies inside the restock transaction
    with pytest.raises(Crash):
        _inspect(c, "ua", rid, ["resellable"])
    assert _case_row(c, rid)["status"] == "inspected" and _stock(c, p["id"]) == stock_at_crash and _cases(c, return_case_id=rid) == []
    r = c.get("/api/cron/expire-pending-orders", headers=CRON).json()
    assert r["returns_repaired"] >= 1
    assert _stock(c, p["id"]) == 20 and len(_cases(c, return_case_id=rid)) == 1 and _case_row(c, rid)["status"] == "refund_pending"
    c.get("/api/cron/expire-pending-orders", headers=CRON)
    assert _stock(c, p["id"]) == 20 and len(_cases(c, return_case_id=rid)) == 1


def test_customers_can_withdraw_a_return_until_it_is_received(c):
    p = _product(c, "RF-W1", 100)
    o = _delivered(c, [(p, 1)])
    rid = _return(c, o, [(p, 1)]).json()["cases"][0]["id"]
    assert c.post(f"/api/returns/{rid}/cancel", headers=_hdr(S["cust2"]["id"])).status_code == 404
    assert c.post(f"/api/returns/{rid}/cancel", headers=_hdr(S["cust"]["id"])).json()["status"] == "cancelled"
    assert c.post(f"/api/returns/{rid}/cancel", headers=_hdr(S["cust"]["id"])).status_code == 409
    assert _vact(c, "ua", rid, "approve").status_code == 409                                  # a withdrawn request cannot be approved
    assert _return(c, o, [(p, 1)]).status_code == 200                                         # and the quantity is free again
