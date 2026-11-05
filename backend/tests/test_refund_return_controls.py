"""Phase 3B.7: post-payment refunds, returns and cancellations. D1 (one refund case, one confirmation), D2 (return quantity
claims), G1 (paid admin cancellation opens a refund case), G2 (vendor rejection of a paid order opens one), D3 (refund
authority). Integration: THROWAWAY MongoDB. Run in its own process: `pytest tests/test_refund_return_controls.py -n 0`.
"""
import asyncio
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_refund_controls_test", "JWT_SECRET": "refund-controls-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import returns_routes  # noqa: E402
import shop_routes  # noqa: E402
from commission import release_due_points  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402
from wallet_reconcile import expected_aggregates  # noqa: E402

ADDR = {"full_name": "Cust", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
ROLES = {"sup": "super_admin", "fin": "accounts_admin", "fin2": "accounts_admin", "adm": "admin", "support": "support_admin",
         "dist": "distributor", "vstaff": "vendor_staff"}


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()

            async def user(key, role, did):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": "94" + new_id()[:8].replace("-", "4"), "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            await user("cust", "distributor", "RRCUST")
            await user("seller", "distributor", "RRSELL")
            for k, r in ROLES.items():
                await user(k, r, "RR" + k.upper())
            for k in ("va", "vb"):
                await user("u" + k, "vendor", "RR" + k.upper())
                S[k] = {"id": new_id(), "user_id": S["u" + k]["id"], "vendor_code": "RR" + k.upper(), "business_name": "Vendor " + k,
                        "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(S[k]))
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _product(c, vendor="va", price=1000):
    p = {"id": new_id(), "sku": "RR-" + new_id()[:6], "name": "Saree " + vendor, "images": [], "mrp": price + 200, "selling_price": price,
         "gst_percent": 5, "stock": 50, "category": "Sarees", "options": [], "vendor_id": S[vendor]["id"], "vendor_name": S[vendor]["business_name"],
         "is_active": True, "approval_status": "approved", "created_at": now_iso()}
    _run(c, lambda: db.products.insert_one(dict(p)))
    return p["id"]


def _paid_order(c, lines):
    """lines = [(product_id, qty)]. A real order through POST /api/orders, attributed to a HomeGenie, paid online."""
    r = c.post("/api/orders", json={"items": [{"product_id": p, "quantity": q} for p, q in lines], "address": ADDR, "payment_method": "online",
                                    "seller_ref": "RRSELL"}, headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 200, r.text
    o = r.json()
    sid = "cs_" + o["id"][:12]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    return _get(c, o["id"])


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _cases(c, oid):
    return _run(c, lambda: db.refund_cases.find({"order_id": oid}, {"_id": 0}).to_list(20))


def _events(c, oid):
    return _run(c, lambda: db.order_refunds.count_documents({"order_id": oid, "status": "completed"}))


def _comms(c, oid):
    return _run(c, lambda: db.commissions.find({"order_id": oid}, {"_id": 0}).to_list(10))


def _ledger(c, oid, typ):
    return _run(c, lambda: db.vendor_ledger.find({"order_id": oid, "type": typ}, {"_id": 0}).to_list(20))


def _wallet_ok(c):
    rows = _run(c, lambda: db.wallet_transactions.find({"user_id": S["seller"]["id"]}, {"_id": 0}).to_list(5000))
    w = _run(c, lambda: db.wallets.find_one({"user_id": S["seller"]["id"]}, {"_id": 0})) or {}
    exp = expected_aggregates(rows)
    return all(exp[f] == w.get(f + "_paise", 0) for f in exp)


def _act(c, who, cid, action, **kw):
    return c.post(f"/api/admin/refund-cases/{cid}/action", headers=_hdr(S[who]["id"]), json={"action": action, **kw})


def _confirm_body(ref):
    return {"reference": ref, "confirmation_type": "manual_reconciliation", "note": "Verified against the bank statement"}


def _open_case(c, amount_paise=None):
    o = _paid_order(c, [(_product(c), 2)])
    case, _ = _run(c, lambda: returns_routes.open_refund_case(o, "test", amount_paise or o["total_paise"], "test case", "t:" + o["id"]))
    return o, case


def _clawbacks(c, oid):
    return sum(len(x.get("reversal_records", [])) for x in _comms(c, oid))


# ================================================================ D1: one refund case, one confirmation
@pytest.mark.parametrize("round_", range(5))
def test_d1_two_finance_users_confirming_with_different_references_refund_once(c, round_):
    o, case = _open_case(c, 30000)
    assert _act(c, "fin", case["id"], "initiate").status_code == 200
    out = []
    ts = [threading.Thread(target=lambda who=who, ref=ref: out.append(_act(c, who, case["id"], "confirm", **_confirm_body(ref)).status_code))
          for who, ref in (("fin", "UTR-A-" + o["id"][:6]), ("fin2", "UTR-B-" + o["id"][:6]))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(out) == [200, 409], out
    assert _events(c, o["id"]) == 1 and _get(c, o["id"])["refunded_paise"] == 30000
    assert _clawbacks(c, o["id"]) == 1 and _wallet_ok(c)
    assert _run(c, lambda: db.refund_cases.find_one({"id": case["id"]}))["status"] == "confirmed"


def test_d1_the_same_user_double_submitting_refunds_once(c):
    o, case = _open_case(c, 20000)
    _act(c, "fin", case["id"], "initiate")
    out = []
    ref = "UTR-DBL-" + o["id"][:6]
    ts = [threading.Thread(target=lambda: out.append(_act(c, "fin", case["id"], "confirm", **_confirm_body(ref)).status_code)) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count(200) == 1 and _events(c, o["id"]) == 1 and _get(c, o["id"])["refunded_paise"] == 20000 and _wallet_ok(c)


def test_d1_a_crash_after_the_claim_resumes_only_with_the_same_reference(c):
    o, case = _open_case(c, 10000)
    _act(c, "fin", case["id"], "initiate")
    ref = "UTR-CLAIM-" + o["id"][:6]
    _run(c, lambda: db.refund_cases.update_one({"id": case["id"]}, {"$set": {"confirming_reference": ref, "confirming_by": S["fin"]["id"]}}))
    assert _act(c, "fin2", case["id"], "confirm", **_confirm_body("UTR-OTHER-" + o["id"][:6])).status_code == 409
    assert _events(c, o["id"]) == 0
    assert _act(c, "fin2", case["id"], "confirm", **_confirm_body(ref)).status_code == 200
    assert _events(c, o["id"]) == 1 and _get(c, o["id"])["refunded_paise"] == 10000


def test_d1_a_crash_after_the_money_moved_finishes_with_the_same_reference_and_cannot_be_abandoned(c):
    o, case = _open_case(c, 10000)
    _act(c, "fin", case["id"], "initiate")
    ref = "UTR-MOVED-" + o["id"][:6]
    _run(c, lambda: db.refund_cases.update_one({"id": case["id"]}, {"$set": {"confirming_reference": ref}}))
    _run(c, lambda: shop_routes.reverse_order_financials(o["id"], {"id": S["fin"]["id"]}, None, 100.0, ref, "t", case_id=case["id"]))
    assert _act(c, "fin", case["id"], "fail", note="Bank transfer bounced").status_code == 409          # the money is recorded
    assert _act(c, "fin", case["id"], "confirm", **_confirm_body("UTR-NEW-" + o["id"][:6])).status_code == 409
    assert _act(c, "fin", case["id"], "confirm", **_confirm_body(ref)).status_code == 200
    assert _events(c, o["id"]) == 1 and _get(c, o["id"])["refunded_paise"] == 10000 and _clawbacks(c, o["id"]) == 1 and _wallet_ok(c)


def test_d1_a_claim_whose_money_never_moved_can_be_failed_and_retried(c):
    o, case = _open_case(c, 10000)
    _act(c, "fin", case["id"], "initiate")
    _run(c, lambda: db.refund_cases.update_one({"id": case["id"]}, {"$set": {"confirming_reference": "UTR-NEVER"}}))
    assert _act(c, "fin", case["id"], "fail", note="Transfer never left the bank").status_code == 200
    assert "confirming_reference" not in _run(c, lambda: db.refund_cases.find_one({"id": case["id"]}))
    assert _act(c, "fin", case["id"], "retry").status_code == 200
    assert _act(c, "fin2", case["id"], "confirm", **_confirm_body("UTR-RETRY-" + o["id"][:6])).status_code == 200
    assert _events(c, o["id"]) == 1


# ================================================================ D2: return quantity claims
def _deliver(c, o):
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "delivered", **{f"fulfilments.{i}.status": "delivered" for i in range(len(o["fulfilments"]))},
                                                                    **{f"fulfilments.{i}.events": [{"status": "delivered", "at": now_iso()}] for i in range(len(o["fulfilments"]))}}}))


def _return(c, oid, pid, qty):
    return c.post(f"/api/orders/{oid}/returns", json={"kind": "return", "reason": "Wrong size", "items": [{"product_id": pid, "quantity": qty}]},
                  headers=_hdr(S["cust"]["id"]))


def _active_returned(c, oid, line=0):
    rows = _run(c, lambda: db.return_cases.find({"order_id": oid, "status": {"$nin": ["cancelled", "rejected"]}}, {"_id": 0, "lines": 1}).to_list(50))
    return sum(x["quantity"] for r in rows for x in r["lines"] if x["order_line"] == line)


@pytest.mark.parametrize("round_", range(5))
def test_d2_concurrent_requests_never_claim_more_than_was_bought(c, round_):
    pid = _product(c)
    o = _paid_order(c, [(pid, 1)])
    _deliver(c, o)
    out = []
    ts = [threading.Thread(target=lambda: out.append(_return(c, o["id"], pid, 1).status_code)) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out.count(200) == 1 and _active_returned(c, o["id"]) == 1
    assert _get(c, o["id"])["return_claimed"]["0"] == 1


def test_d2_partial_returns_add_up_to_the_quantity_bought_and_no_further(c):
    pid = _product(c)
    o = _paid_order(c, [(pid, 3)])
    _deliver(c, o)
    assert _return(c, o["id"], pid, 1).status_code == 200
    assert _return(c, o["id"], pid, 2).status_code == 200
    r = _return(c, o["id"], pid, 1)
    assert r.status_code == 400 and "at most 0" in r.text and _active_returned(c, o["id"]) == 3


def test_d2_an_over_claim_on_one_line_leaves_the_other_lines_untouched(c):
    p1, p2 = _product(c), _product(c)
    o = _paid_order(c, [(p1, 2), (p2, 1)])
    _deliver(c, o)
    assert _return(c, o["id"], p2, 1).status_code == 200
    r = c.post(f"/api/orders/{o['id']}/returns", json={"kind": "return", "reason": "Both wrong", "items": [{"product_id": p1, "quantity": 2},
                                                                                                          {"product_id": p2, "quantity": 1}]},
               headers=_hdr(S["cust"]["id"]))
    assert r.status_code == 400
    assert _get(c, o["id"])["return_claimed"] == {"1": 1, "0": 0} or _get(c, o["id"])["return_claimed"].get("0", 0) == 0
    assert _return(c, o["id"], p1, 2).status_code == 200                                     # line 0 was not left reserved


def test_d2_withdrawal_and_rejection_give_the_units_back_once(c):
    pid = _product(c)
    o = _paid_order(c, [(pid, 1)])
    _deliver(c, o)
    rid = _return(c, o["id"], pid, 1).json()["cases"][0]["id"]
    assert c.post(f"/api/returns/{rid}/cancel", headers=_hdr(S["cust"]["id"])).status_code == 200
    assert c.post(f"/api/returns/{rid}/cancel", headers=_hdr(S["cust"]["id"])).status_code == 409    # no second release
    assert _get(c, o["id"])["return_claimed"]["0"] == 0
    rid2 = _return(c, o["id"], pid, 1).json()["cases"][0]["id"]
    assert c.post(f"/api/admin/returns/{rid2}/decision", headers=_hdr(S["sup"]["id"]), json={"decision": "reject", "note": "Outside policy"}).status_code == 200
    assert _get(c, o["id"])["return_claimed"]["0"] == 0
    assert _return(c, o["id"], pid, 1).status_code == 200 and _get(c, o["id"])["return_claimed"]["0"] == 1


@pytest.mark.parametrize("round_", range(3))
def test_d2_a_withdrawal_racing_a_new_request_never_over_claims(c, round_):
    pid = _product(c)
    o = _paid_order(c, [(pid, 1)])
    _deliver(c, o)
    rid = _return(c, o["id"], pid, 1).json()["cases"][0]["id"]
    ts = [threading.Thread(target=lambda: c.post(f"/api/returns/{rid}/cancel", headers=_hdr(S["cust"]["id"]))),
          threading.Thread(target=lambda: _return(c, o["id"], pid, 1)), threading.Thread(target=lambda: _return(c, o["id"], pid, 1))]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert _active_returned(c, o["id"]) <= 1 and _get(c, o["id"])["return_claimed"]["0"] == _active_returned(c, o["id"])


def test_d2_historical_return_cases_are_counted_when_the_counter_starts(c):
    pid = _product(c)
    o = _paid_order(c, [(pid, 2)])
    _deliver(c, o)
    _run(c, lambda: db.return_cases.insert_one({"id": new_id(), "number": "RTN-OLD", "order_id": o["id"], "user_id": S["cust"]["id"],
                                                "vendor_id": S["va"]["id"], "kind": "return", "status": "requested", "created_at": OLD,
                                                "lines": [{"order_line": 0, "product_id": pid, "quantity": 2, "price_paise": 100000}]}))
    assert _return(c, o["id"], pid, 1).status_code == 400 and _get(c, o["id"])["return_claimed"]["0"] == 2


def test_d2_an_inspected_return_restocks_once_however_often_it_is_repaired(c):
    pid = _product(c)
    o = _paid_order(c, [(pid, 2)])
    _deliver(c, o)
    rid = _return(c, o["id"], pid, 2).json()["cases"][0]["id"]
    hv = _hdr(S["uva"]["id"])
    assert c.post(f"/api/vendor/returns/{rid}/action", headers=hv, json={"action": "approve"}).status_code == 200
    assert c.post(f"/api/vendor/returns/{rid}/action", headers=hv, json={"action": "receive"}).status_code == 200
    before = _run(c, lambda: db.products.find_one({"id": pid}))["stock"]
    assert c.post(f"/api/vendor/returns/{rid}/inspection", headers=hv, json={"lines": [{"index": 0, "outcome": "resellable"}],
                                                                           "note": "Tags intact"}).status_code == 200
    for _ in range(3):
        _run(c, returns_routes.reconcile_returns)
    assert _run(c, lambda: db.products.find_one({"id": pid}))["stock"] == before + 2
    assert len([x for x in _cases(c, o["id"]) if x["kind"] == "return"]) == 1


# ================================================================ G1: paid order cancelled by an admin
def test_g1_admin_cancellation_of_a_paid_order_opens_one_refund_case_and_holds_commission(c):
    o = _paid_order(c, [(_product(c), 2)])
    r = c.put(f"/api/admin/orders/{o['id']}/status", headers=_hdr(S["sup"]["id"]), json={"status": "cancelled"})
    assert r.status_code == 200 and r.json()["refund_case"]
    assert c.put(f"/api/admin/orders/{o['id']}/status", headers=_hdr(S["sup"]["id"]), json={"status": "cancelled"}).status_code == 200
    _run(c, returns_routes.ensure_cases_for_flagged_orders)
    cases = _cases(c, o["id"])
    assert len(cases) == 1 and cases[0]["kind"] == "cancellation" and cases[0]["amount_paise"] == o["total_paise"]
    assert len(_ledger(c, o["id"], "SALE_REVERSAL")) == 1 and "refund_due_cancel" not in _get(c, o["id"])
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
    _run(c, release_due_points)
    assert all(x["released_at"] is None for x in _comms(c, o["id"]))
    assert _act(c, "fin", cases[0]["id"], "initiate").status_code == 200
    assert _act(c, "fin2", cases[0]["id"], "confirm", **_confirm_body("UTR-G1-" + o["id"][:6])).status_code == 200
    got = _get(c, o["id"])
    assert got["payment_status"] == "refunded" and _events(c, o["id"]) == 1
    assert all(x["status"] == "REVERSED" for x in _comms(c, o["id"])) and _wallet_ok(c)
    assert len(_ledger(c, o["id"], "REFUND")) == 0                          # the reversed sale is not refunded a second time


def test_g1_a_crash_after_the_cancellation_is_repaired_once(c):
    o = _paid_order(c, [(_product(c), 1)])
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled", "refund_due_cancel": True,
                                                                    "fulfilments.0.status": "cancelled"}}))
    for _ in range(3):
        _run(c, returns_routes.ensure_cases_for_flagged_orders)
    assert len(_cases(c, o["id"])) == 1 and len(_ledger(c, o["id"], "SALE_REVERSAL")) == 1


def test_g1_an_unpaid_cancellation_opens_no_refund_case(c):
    r = c.post("/api/orders", json={"items": [{"product_id": _product(c), "quantity": 1}], "address": ADDR, "payment_method": "online"},
               headers=_hdr(S["cust"]["id"]))
    oid = r.json()["id"]
    assert c.put(f"/api/admin/orders/{oid}/status", headers=_hdr(S["sup"]["id"]), json={"status": "cancelled"}).json()["refund_case"] is None
    assert _cases(c, oid) == []


# ================================================================ G2: a vendor rejects a paid order
def _reject(c, vendor, oid):
    return c.post(f"/api/vendor/orders/{oid}/fulfilment", headers=_hdr(S["u" + vendor]["id"]), json={"status": "rejected", "note": "Out of material"})


def test_g2_a_partial_rejection_refunds_only_that_vendors_lines_and_holds_commission(c):
    pa, pb = _product(c, "va", 1000), _product(c, "vb", 500)
    o = _paid_order(c, [(pa, 1), (pb, 2)])                                    # subtotal 2,000, GST 100, total 2,100
    assert _reject(c, "va", o["id"]).status_code == 200
    cases = _cases(c, o["id"])
    assert len(cases) == 1 and cases[0]["kind"] == "vendor_rejection" and cases[0]["vendor_id"] == S["va"]["id"]
    assert cases[0]["amount_paise"] == 105000                                 # 1,000 + its 50.00 share of GST
    got = _get(c, o["id"])
    assert got["status"] == "processing" and not any(f.get("refund_due") for f in got["fulfilments"])
    assert {e["vendor_id"] for e in _ledger(c, o["id"], "SALE_REVERSAL")} == {S["va"]["id"]}
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
    _run(c, release_due_points)
    assert all(x["released_at"] is None for x in _comms(c, o["id"]))          # held while the refund case is open
    _act(c, "fin", cases[0]["id"], "initiate")
    assert _act(c, "fin2", cases[0]["id"], "confirm", **_confirm_body("UTR-G2-" + o["id"][:6])).status_code == 200
    got = _get(c, o["id"])
    assert got["payment_status"] == "partially_refunded" and got["refunded_paise"] == 105000
    cm = _comms(c, o["id"])[0]
    assert cm["reversed_paise"] == cm["amount_paise"] * 105000 // 210000 and cm["status"] == "PARTIALLY_REVERSED"
    assert _ledger(c, o["id"], "REFUND") == [] and _wallet_ok(c)              # vendor A's sale was already reversed; B untouched


def test_g2_when_every_vendor_rejects_the_order_is_cancelled_and_refunds_sum_to_the_total(c):
    pa, pb = _product(c, "va", 1000), _product(c, "vb", 500)
    o = _paid_order(c, [(pa, 1), (pb, 2)])
    _reject(c, "va", o["id"])
    _reject(c, "vb", o["id"])
    _run(c, returns_routes.ensure_cases_for_flagged_orders)
    cases = _cases(c, o["id"])
    assert sorted(x["kind"] for x in cases) == ["vendor_rejection", "vendor_rejection"]
    assert sum(x["amount_paise"] for x in cases) == o["total_paise"]
    assert _get(c, o["id"])["status"] == "cancelled"


def test_g2_concurrent_rejections_open_one_case(c):
    o = _paid_order(c, [(_product(c, "va"), 1)])
    ts = [threading.Thread(target=lambda: _reject(c, "va", o["id"])) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    _run(c, returns_routes.ensure_cases_for_flagged_orders)
    assert len(_cases(c, o["id"])) == 1 and len(_ledger(c, o["id"], "SALE_REVERSAL")) == 1


def test_g2_an_already_released_commission_is_clawed_back_proportionally(c):
    pa, pb = _product(c, "va", 1000), _product(c, "vb", 1000)
    o = _paid_order(c, [(pa, 1), (pb, 1)])
    _run(c, lambda: db.commissions.update_many({"order_id": o["id"]}, {"$set": {"created_at": OLD}}))
    _run(c, release_due_points)
    assert all(x["released_at"] for x in _comms(c, o["id"]))
    _reject(c, "vb", o["id"])                                                  # (the fulfilment is still 'new')
    case = _cases(c, o["id"])[0]
    _act(c, "fin", case["id"], "initiate")
    assert _act(c, "sup", case["id"], "confirm", **_confirm_body("UTR-G2R-" + o["id"][:6])).status_code == 200
    cm = _comms(c, o["id"])[0]
    assert cm["reversed_paise"] == cm["amount_paise"] // 2 and len(cm["reversal_records"]) == 1 and _wallet_ok(c)


def test_g2_an_unpaid_cod_rejection_opens_no_refund_case(c):
    r = c.post("/api/orders", json={"items": [{"product_id": _product(c, "va"), "quantity": 1}], "address": ADDR, "payment_method": "cod"},
               headers=_hdr(S["cust"]["id"]))
    oid = r.json()["id"]
    assert _reject(c, "va", oid).status_code == 200 and _cases(c, oid) == []


# ================================================================ D3: refund authority
def _snapshot(c, oid):
    return (_get(c, oid), _cases(c, oid), _comms(c, oid), _ledger(c, oid, "REFUND"),
            _run(c, lambda: db.wallets.find_one({"user_id": S["seller"]["id"]}, {"_id": 0, "applied_ops": 0, "updated_at": 0})))


@pytest.mark.parametrize("who,ok", [("sup", True), ("fin", True), ("adm", False), ("support", False), ("dist", False), ("uva", False), ("vstaff", False)])
def test_d3_only_finance_can_refund_confirm_or_close_a_refund(c, who, ok):
    o, case = _open_case(c, 10000)
    o2, case2 = _open_case(c, 10000)
    assert _act(c, "fin", case["id"], "initiate").status_code == 200
    before = _snapshot(c, o["id"])
    r1 = c.post(f"/api/admin/orders/{o['id']}/refund", headers=_hdr(S[who]["id"]), json={"reference": "UTR-ONE-" + who, "amount": 1.0})
    r2 = _act(c, who, case["id"], "confirm", **_confirm_body("UTR-D3-" + who + o["id"][:4]))
    r3 = _act(c, who, case2["id"], "resolve", note="Customer withdrew the complaint")
    if ok:
        assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 200)
        assert r3.json()["outcome"] == "no_refund"
    else:
        assert (r1.status_code, r2.status_code, r3.status_code) == (403, 403, 403)
        assert _snapshot(c, o["id"]) == before
        assert _run(c, lambda: db.refund_cases.find_one({"id": case2["id"]}))["status"] == "awaiting_review"
