"""Batch 1 — payment and order integrity: FIN-01 (manual/UPI confirmation needs the exact amount and a unique reference),
FIN-02 (vendors never see or ship unverified orders), FIN-06 (a second captured payment is never applied twice and is flagged
for refund), FIN-07 (orders are never hard-deleted; removal cancels through the stock path), FIN-08 (UPI claims can be
rejected), FIN-14 (Razorpay events are marked handled only after processing), FIN-15 (support/finance roles cannot cancel
paid orders).

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_payment_integrity_batch1.py -n 0`).
"""
import hashlib
import hmac
import json
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_payment_batch1_test", "JWT_SECRET": "batch1-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "RAZORPAY_WEBHOOK_SECRET": "whsec-test-only"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
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
            await user("cust", "9100001001", "distributor", "B1CUST")
            await user("cust2", "9100001002", "distributor", "B1CUST2")
            await user("super", "9100001003", "super_admin", "B1SUPER")
            await user("admin", "9100001004", "admin", "B1ADMIN")
            await user("sup", "9100001005", "support_admin", "B1SUP")
            await user("fin", "9100001006", "accounts_admin", "B1FIN")
            await user("vu", "9100001007", "vendor", "B1VEND")
            S["v"] = {"id": new_id(), "user_id": S["vu"]["id"], "vendor_code": "B1VEND", "business_name": "Vendor B1",
                      "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["v"]))
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


_n = {"i": 0}


def _product(c, stock=10):
    _n["i"] += 1
    sku = f"B1-{_n['i']}"

    async def mk():
        p = {"id": new_id(), "sku": sku, "name": sku, "images": [], "mrp": 1000, "selling_price": 800, "gst_percent": 5,
             "stock": stock, "category": "Sarees", "options": [], "vendor_id": S["v"]["id"], "vendor_name": "Vendor B1",
             "is_active": True, "approval_status": "approved", "created_at": now_iso()}
        await db.products.insert_one(dict(p))
        return p
    return _run(c, mk)


def _order(c, cust="cust", method="online", qty=1):
    p = _product(c)
    r = c.post("/api/orders", json={"items": [{"product_id": p["id"], "quantity": qty}], "address": ADDR, "payment_method": method},
               headers=_hdr(cust))
    assert r.status_code == 200, r.text
    return r.json(), p


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _stock(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}))["stock"]


def _claim(c, o, cust="cust", ref=""):
    return c.post("/api/payments/upi-claim", json={"order_id": o["id"], "reference": ref}, headers=_hdr(cust))


def _confirm(c, o, ref, amount=None, actor="fin"):
    return c.put(f"/api/admin/payments/upi-confirm/{o['id']}", json={"reference": ref, "amount": o["total"] if amount is None else amount},
                 headers=_hdr(actor))


def _gateway_tx(c, o, sid, provider="stripe"):
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "currency": "INR", "provider": provider,
                                                        "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))


def _gateway_paid(c, sid):
    _run(c, lambda: shop_routes._process_paid_order(sid))


# ================================================================ FIN-01: amount and unique reference
def test_confirmation_needs_the_exact_amount(c):
    o, _ = _order(c)
    assert _claim(c, o).status_code == 200
    assert _confirm(c, o, "UTR100000000001", amount=o["total"] - 1).status_code == 400
    assert _confirm(c, o, "UTR100000000001", amount=o["total"] + 50).status_code == 400
    r = c.put(f"/api/admin/payments/upi-confirm/{o['id']}", json={"reference": "UTR100000000001"}, headers=_hdr("fin"))
    assert r.status_code == 422                                                  # amount is mandatory
    assert _get(c, o["id"])["payment_status"] == "claimed"
    ok = _confirm(c, o, "UTR100000000001")
    assert ok.status_code == 200 and _get(c, o["id"])["payment_status"] == "paid"
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": f"manual_{o['id']}"}))
    assert tx["amount_received"] == o["total"] and tx["recorded_by"] == S["fin"]["id"]


def test_one_reference_can_confirm_only_one_order(c):
    o1, _ = _order(c)
    o2, _ = _order(c)
    assert _claim(c, o1).status_code == 200 and _claim(c, o2).status_code == 200
    assert _confirm(c, o1, "UTR 2000 0000 0001").status_code == 200
    r = _confirm(c, o2, "utr200000000001")                                        # same UTR, different spacing/case
    assert r.status_code == 409 and "another order" in r.json()["detail"]
    assert _get(c, o2["id"])["payment_status"] == "claimed"
    assert _confirm(c, o1, "UTR200000000001").json()["message"] == "Order already paid."   # same order: idempotent


def test_manual_payment_needs_amount_and_unique_reference(c):
    o, _ = _order(c, cust="cust2")
    body = {"distributor_id": "B1CUST2", "reference": "UTR200000000001", "amount": o["total"]}
    assert c.post("/api/admin/payments/manual", json=body, headers=_hdr("fin")).status_code == 409   # used above
    body["reference"] = "UTR300000000001"
    assert c.post("/api/admin/payments/manual", json={**body, "amount": 1}, headers=_hdr("fin")).status_code == 400
    r = c.post("/api/admin/payments/manual", json=body, headers=_hdr("fin"))
    assert r.status_code == 200 and _get(c, o["id"])["payment_status"] == "paid"


def test_invalid_reference_format_refused(c):
    o, _ = _order(c)
    _claim(c, o)
    assert _confirm(c, o, "abc").status_code == 400
    assert _confirm(c, o, "<script>alert(1)</script>").status_code == 400


# ================================================================ FIN-02: vendors never see or ship unverified orders
def test_claimed_orders_are_invisible_to_the_vendor_until_confirmed(c):
    o, _ = _order(c)
    assert _claim(c, o).status_code == 200
    ids = [x["id"] for x in c.get("/api/vendor/orders", headers=_hdr("vu")).json()["items"]] \
        if isinstance(c.get("/api/vendor/orders", headers=_hdr("vu")).json(), dict) else \
        [x["id"] for x in c.get("/api/vendor/orders", headers=_hdr("vu")).json()]
    assert o["id"] not in ids
    assert c.get(f"/api/vendor/orders/{o['id']}", headers=_hdr("vu")).status_code == 404
    acc = c.post(f"/api/vendor/orders/{o['id']}/fulfilment", json={"status": "accepted", "note": ""}, headers=_hdr("vu"))
    assert acc.status_code == 404
    assert _confirm(c, o, "UTR400000000001").status_code == 200
    acc = c.post(f"/api/vendor/orders/{o['id']}/fulfilment", json={"status": "accepted", "note": ""}, headers=_hdr("vu"))
    assert acc.status_code == 200, acc.text


def test_refund_landing_mid_request_blocks_forward_fulfilment(c):
    """The vendor read the order while paid; a full refund lands before the write. The forward step must be refused."""
    import vendor_routes
    o, _ = _order(c)
    _claim(c, o)
    assert _confirm(c, o, "UTR500000000001").status_code == 200
    real = db.orders

    class Orders:
        def __getattr__(self, n):
            return getattr(real, n)

        async def find_one(self, *a, **k):
            doc = await real.find_one(*a, **k)
            if doc and doc.get("id") == o["id"]:
                await real.update_one({"id": o["id"]}, {"$set": {"payment_status": "refunded"}})
            return doc

    class DB:
        orders = Orders()

        def __getattr__(self, n):
            return getattr(db, n)
    saved = vendor_routes.db
    vendor_routes.db = DB()
    try:
        r = c.post(f"/api/vendor/orders/{o['id']}/fulfilment", json={"status": "accepted", "note": ""}, headers=_hdr("vu"))
    finally:
        vendor_routes.db = saved
    assert r.status_code == 409
    assert _get(c, o["id"])["fulfilments"][0]["status"] == "new"


# ================================================================ FIN-06: duplicate captures
def test_second_gateway_capture_is_not_applied_and_is_flagged_once(c):
    o, p = _order(c)
    _gateway_tx(c, o, "cs_first")
    _gateway_tx(c, o, "rzp_second", provider="razorpay")
    _gateway_paid(c, "cs_first")
    paid = _get(c, o["id"])
    assert paid["payment_status"] == "paid" and paid["paid_session_id"] == "cs_first"
    ledger_before = _run(c, lambda: db.vendor_ledger.count_documents({"order_id": o["id"]}))
    _gateway_paid(c, "rzp_second")
    _gateway_paid(c, "rzp_second")                                          # re-delivered: still recorded once
    _gateway_paid(c, "cs_first")                                            # the original reported again: no flag
    after = _get(c, o["id"])
    assert after["has_duplicate_payment"] is True and len(after["duplicate_payments"]) == 1
    d = after["duplicate_payments"][0]
    assert d["session_id"] == "rzp_second" and d["status"] == "refund_due" and d["reason"] == "order_already_paid"
    assert after["invoice_number"] == paid["invoice_number"]
    assert _run(c, lambda: db.vendor_ledger.count_documents({"order_id": o["id"]})) == ledger_before
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": "rzp_second"}))
    assert tx["duplicate_capture"] is True and tx["applied_to_order"] is False


def test_capture_on_a_refunded_order_is_flagged_not_applied(c):
    o, _ = _order(c)
    _gateway_tx(c, o, "cs_paid")
    _gateway_paid(c, "cs_paid")
    r = c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "RFND-0001", "reason": "test"}, headers=_hdr("super"))
    assert r.status_code == 200, r.text
    _gateway_tx(c, o, "cs_late")
    _gateway_paid(c, "cs_late")
    after = _get(c, o["id"])
    assert after["payment_status"] == "refunded"
    assert [x["session_id"] for x in after["duplicate_payments"]] == ["cs_late"]


# ================================================================ FIN-07: never hard-delete
def test_remove_cancels_through_stock_path_and_keeps_the_record(c):
    o, p = _order(c, qty=2)
    assert _stock(c, p["id"]) == 8
    assert c.delete(f"/api/admin/orders/{o['id']}", headers=_hdr("sup")).status_code == 403
    r = c.delete(f"/api/admin/orders/{o['id']}", headers=_hdr("admin"))
    assert r.status_code == 200 and r.json()["archived"] is True
    got = _get(c, o["id"])
    assert got and got["status"] == "cancelled" and got["archived"] is True and got["cancel_reason"] == "removed_by_admin"
    assert _stock(c, p["id"]) == 10                                         # reserved stock came back
    assert c.delete(f"/api/admin/orders/{o['id']}", headers=_hdr("admin")).json()["already_removed"] is True
    assert _stock(c, p["id"]) == 10                                         # and only once


@pytest.mark.parametrize("kind", ["claimed", "paid", "cod", "attempted"])
def test_orders_with_payment_or_cod_history_cannot_be_removed(c, kind):
    o, _ = _order(c, method="cod" if kind == "cod" else "online")
    if kind == "claimed":
        _claim(c, o)
    if kind == "paid":
        _gateway_tx(c, o, f"cs_{o['id']}")
        _gateway_paid(c, f"cs_{o['id']}")
    if kind == "attempted":
        _run(c, lambda: db.payment_transactions.insert_one({"session_id": f"x_{o['id']}", "order_id": o["id"], "payment_status": "paid"}))
    before = _get(c, o["id"])
    assert c.delete(f"/api/admin/orders/{o['id']}", headers=_hdr("super")).status_code == 409
    assert _get(c, o["id"]) == before


# ================================================================ FIN-08: UPI claim rejection
def test_rejecting_a_claim_returns_the_order_to_unpaid_and_records_it(c):
    o, _ = _order(c)
    assert _claim(c, o, ref="CUSTREF1").status_code == 200
    assert c.put(f"/api/admin/payments/upi-reject/{o['id']}", json={"reason": "no"}, headers=_hdr("fin")).status_code == 422
    r = c.put(f"/api/admin/payments/upi-reject/{o['id']}", json={"reason": "Not in bank statement"}, headers=_hdr("fin"))
    assert r.status_code == 200
    got = _get(c, o["id"])
    assert got["payment_status"] == "pending" and got["payment_method"] == "online" and got["upi_reference"] is None
    assert got["rejected_upi_claims"][0]["reference"] == "CUSTREF1"
    assert c.put(f"/api/admin/payments/upi-reject/{o['id']}", json={"reason": "again please"}, headers=_hdr("fin")).status_code == 409
    assert c.put(f"/api/admin/payments/upi-reject/{o['id']}", json={"reason": "member"}, headers=_hdr("cust")).status_code == 403


# ================================================================ FIN-14: Razorpay webhook idempotency
def _webhook(c, event_id, rzp_order):
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": {"order_id": rzp_order}}}}).encode()
    sig = hmac.new(b"whsec-test-only", body, hashlib.sha256).hexdigest()
    return c.post("/api/webhook/razorpay", content=body, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id,
                                                                    "Content-Type": "application/json"})


def test_failed_webhook_processing_is_retried_and_success_is_final(c, monkeypatch):
    o, _ = _order(c)
    _gateway_tx(c, o, "order_rzp_1", provider="razorpay")
    real = shop_routes._process_paid_order
    calls = {"n": 0}

    async def flaky(sid, request=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database hiccup")
        return await real(sid, request)
    monkeypatch.setattr(shop_routes, "_process_paid_order", flaky)
    with pytest.raises(RuntimeError):
        _webhook(c, "evt_1", "order_rzp_1")
    assert _run(c, lambda: db.webhook_events.find_one({"event_id": "evt_1"}))["status"] == "failed"
    assert _webhook(c, "evt_1", "order_rzp_1").json()["status"] == "ok"            # Razorpay's retry processes it
    assert _get(c, o["id"])["payment_status"] == "paid"
    assert _webhook(c, "evt_1", "order_rzp_1").json()["status"] == "duplicate"
    assert calls["n"] == 2


def test_an_event_being_processed_is_not_processed_twice(c):
    _run(c, lambda: db.webhook_events.insert_one({"event_id": "evt_busy", "status": "processing", "claimed_at": now_iso()}))
    assert _webhook(c, "evt_busy", "order_none").json()["status"] == "duplicate"
    _run(c, lambda: db.webhook_events.insert_one({"event_id": "evt_legacy", "provider": "razorpay"}))     # recorded by the old code
    assert _webhook(c, "evt_legacy", "order_none").json()["status"] == "duplicate"


def test_bad_signature_refused(c):
    r = c.post("/api/webhook/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "bad", "Content-Type": "application/json"})
    assert r.status_code == 400


# ================================================================ FIN-15: who may cancel a paid order
@pytest.mark.parametrize("actor,expected", [("sup", 403), ("fin", 403), ("admin", 200)])
def test_only_super_admin_or_admin_cancel_paid_orders(c, actor, expected):
    o, _ = _order(c)
    _gateway_tx(c, o, f"cs_c_{o['id']}")
    _gateway_paid(c, f"cs_c_{o['id']}")
    r = c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr(actor))
    assert r.status_code == expected, r.text
    assert _get(c, o["id"])["status"] == ("cancelled" if expected == 200 else "processing")


def test_support_can_still_cancel_an_unpaid_order(c):
    o, _ = _order(c)
    assert c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled"}, headers=_hdr("sup")).status_code == 200
