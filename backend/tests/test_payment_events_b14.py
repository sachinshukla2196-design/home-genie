"""Batch 14, P0 — payment webhook reconciliation (payment_events.py).

Covers: valid event, invalid signature, malformed event, duplicate event, the same event delivered concurrently, amount and currency
mismatch, unknown order, unknown payment attempt, failed payment, a delayed success after the order expired, out-of-order events,
a partial failure retried (by the provider and by a finance admin), a multi-vendor order allocated per vendor, no duplicate
commission or vendor-ledger effects, and no payout eligibility from an unverified event.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment (isolated test MongoDB only).
Run this file in its own pytest process (`pytest tests/test_payment_events_b14.py -n 0`).
"""
import hashlib
import hmac
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

SECRET = "whsec-b14-test-only"
os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_payment_events_b14_test", "JWT_SECRET": "payev14-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "RAZORPAY_WEBHOOK_SECRET": SECRET})
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger  # noqa: E402
import eligibility  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Meera Iyer", "mobile": "9000011111", "line1": "1 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
_n = {"i": 0}


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app, raise_server_exceptions=False) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, did in (("cust", "customer", "CU140001"), ("hg", "distributor", "HG140001"), ("fin", "accounts_admin", "PE14FIN"),
                                   ("sup", "support_admin", "PE14SUP"), ("va", "vendor", "PE14VA"), ("vb", "vendor", "PE14VB")):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": f"91000210{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green" if role != "customer" else "customer",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            for k in ("A", "B"):
                S["v" + k] = {"id": new_id(), "user_id": S["v" + k.lower()]["id"], "vendor_code": "PE" + k, "business_name": f"Vendor {k}",
                              "status": "approved", "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
                await db.vendors.insert_one(dict(S["v" + k]))
                await db.products.insert_one({"id": "pe" + k, "sku": "PE-" + k, "name": f"Saree {k}", "images": [], "mrp": 1200, "selling_price": 1050,
                                              "gst_percent": 5, "stock": 100, "category": "Sarees", "options": [], "vendor_id": S["v" + k]["id"],
                                              "vendor_name": f"Vendor {k}", "is_active": True, "approval_status": "approved", "created_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _order(c, items=(("peA", 1),), ref="HG140001"):
    """An online order with OUR Razorpay attempt recorded exactly as razorpay_create_order records it (no gateway call)."""
    o = c.post("/api/orders", json={"items": [{"product_id": p, "quantity": q} for p, q in items], "address": ADDR, "payment_method": "online",
                                    **({"seller_ref": ref} if ref else {})}, headers=_hdr("cust")).json()
    _n["i"] += 1
    gid = f"order_rzp_b14_{_n['i']}"
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": gid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "currency": "INR", "provider": "razorpay", "status": "initiated",
                                                        "payment_status": "pending", "created_at": now_iso()}))
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"razorpay_order_id": gid}}))
    return o, gid


def _event(event_id, gid, amount, *, etype="payment.captured", status="captured", currency="INR", secret=SECRET):
    entity = {"id": "pay_" + event_id, "order_id": gid, "status": status, "currency": currency, "amount": amount,
              "email": "buyer@example.com", "contact": "+919000011111", "card": {"last4": "4242"}}
    body = json.dumps({"event": etype, "payload": {"payment": {"entity": entity}}}).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, {"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": event_id, "Content-Type": "application/json"}


def _post(c, *args, **kw):
    body, headers = _event(*args, **kw)
    return c.post("/api/webhook/razorpay", content=body, headers=headers)


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _ev(c, eid):
    return _run(c, lambda: db.webhook_events.find_one({"event_id": eid}, {"_id": 0}))


def _effects(c, oid):
    sales = _run(c, lambda: db.vendor_ledger.find({"order_id": oid, "type": "SALE_COLLECTED"}, {"_id": 0}).to_list(20))
    comms = _run(c, lambda: db.commissions.count_documents({"order_id": oid}))
    return sales, comms


# ================================================================ authenticity and shape
def test_invalid_signatures_and_malformed_events_are_refused_and_not_recorded(c):
    o, gid = _order(c)
    body, h = _event("evt_badsig", gid, o["total_paise"], secret="not-the-secret")
    assert c.post("/api/webhook/razorpay", content=body, headers=h).status_code == 400
    assert c.post("/api/webhook/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "x"}).status_code == 400
    for raw in (b"not json", json.dumps({"payload": {}}).encode(), json.dumps(["x"]).encode()):
        sig = hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
        assert c.post("/api/webhook/razorpay", content=raw, headers={"X-Razorpay-Signature": sig}).status_code == 400
    assert _ev(c, "evt_badsig") is None and _get(c, o["id"])["payment_status"] == "pending"


# ================================================================ the happy path, recorded without personal data
def test_a_valid_capture_pays_exactly_the_matched_order_and_is_recorded(c):
    o, gid = _order(c)
    other, _ = _order(c)
    r = _post(c, "evt_ok", gid, o["total_paise"])
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert _get(c, o["id"])["payment_status"] == "paid" and _get(c, other["id"])["payment_status"] == "pending"
    ev = _ev(c, "evt_ok")
    assert ev["order_id"] == o["id"] and ev["session_id"] == gid and ev["applied"] is True and ev["attempts"][-1]["outcome"] == "processed"
    assert "buyer@example.com" not in json.dumps(ev) and "4242" not in json.dumps(ev)          # no PII / card data kept
    sales, comms = _effects(c, o["id"])
    assert len(sales) == 1 and comms == 1


def test_duplicate_and_concurrent_deliveries_have_exactly_one_effect(c):
    o, gid = _order(c, items=(("peA", 1), ("peB", 2)))
    codes = list(ThreadPoolExecutor(max_workers=6).map(lambda _: _post(c, "evt_conc", gid, o["total_paise"]).json()["status"], range(6)))
    assert codes.count("processed") == 1 and codes.count("duplicate") == 5
    for _ in range(3):
        assert _post(c, "evt_conc", gid, o["total_paise"]).json()["status"] == "duplicate"
    assert _post(c, "evt_conc_2", gid, o["total_paise"]).json()["status"] == "processed"       # a second event for the same capture
    sales, comms = _effects(c, o["id"])
    by_vendor = {s["vendor_id"]: s["amount_paise"] for s in sales}
    assert by_vendor == {S["vA"]["id"]: 105000, S["vB"]["id"]: 210000}                         # each vendor's own lines, once
    assert comms == 1 and len(_get(c, o["id"]).get("duplicate_payments") or []) == 0


# ================================================================ validation before money moves
@pytest.mark.parametrize("bad", ["amount", "currency"])
def test_amount_or_currency_mismatch_is_rejected_and_changes_nothing(c, bad):
    o, gid = _order(c)
    amount = o["total_paise"] - 100 if bad == "amount" else o["total_paise"]
    r = _post(c, f"evt_mis_{bad}", gid, amount, currency="USD" if bad == "currency" else "INR")
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert bad in _ev(c, f"evt_mis_{bad}")["reason"] and _get(c, o["id"])["payment_status"] == "pending"
    assert _effects(c, o["id"]) == ([], 0)
    assert _post(c, f"evt_mis_{bad}", gid, o["total_paise"]).json()["status"] == "duplicate"   # a rejected event stays rejected


def test_unknown_payment_attempt_and_unknown_order_are_recorded_as_unmatched(c):
    assert _post(c, "evt_unknown_attempt", "order_rzp_never_created", 105000).json()["status"] == "unmatched"
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": "order_rzp_orphan", "order_id": "no-such-order",
                                                        "amount": 1050.0, "provider": "razorpay", "status": "initiated", "created_at": now_iso()}))
    assert _post(c, "evt_unknown_order", "order_rzp_orphan", 105000).json()["status"] == "unmatched"
    assert "does not exist" in _ev(c, "evt_unknown_order")["reason"]


def test_a_non_final_status_never_pays(c):
    o, gid = _order(c)
    assert _post(c, "evt_authorized", gid, o["total_paise"], status="authorized").json()["status"] == "ignored"
    assert _get(c, o["id"])["payment_status"] == "pending"


# ================================================================ failures and ordering
def test_failed_payment_is_recorded_and_out_of_order_events_settle_correctly(c):
    o, gid = _order(c)
    assert _post(c, "evt_fail_1", gid, o["total_paise"], etype="payment.failed", status="failed").json()["status"] == "processed"
    assert _get(c, o["id"])["payment_status"] == "pending"
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": gid}))
    assert tx["gateway_events"][0]["type"] == "payment.failed"
    assert _post(c, "evt_ok_after_fail", gid, o["total_paise"]).json()["status"] == "processed"   # a later retry by the payer succeeds
    assert _post(c, "evt_fail_late", gid, o["total_paise"], etype="payment.failed", status="failed").json()["status"] == "processed"
    assert _get(c, o["id"])["payment_status"] == "paid"                                           # a stale failure never un-pays
    assert _post(c, "evt_other_type", gid, o["total_paise"], etype="refund.created").json()["status"] == "ignored"


def test_a_delayed_success_on_an_expired_order_follows_the_late_payment_rules(c):
    from stock import EXPIRY_REASON
    o, gid = _order(c)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled", "cancel_reason": EXPIRY_REASON}}))
    assert _post(c, "evt_late", gid, o["total_paise"]).json()["status"] == "processed"
    got = _get(c, o["id"])
    assert got["payment_status"] == "paid"
    assert got["status"] == "processing" or got.get("needs_refund") is True          # revived if stock allows, else marked for refund


# ================================================================ partial failure and retry
def test_a_partial_failure_is_recorded_and_a_finance_retry_completes_it_once(c, monkeypatch):
    o, gid = _order(c, items=(("peA", 1), ("peB", 1)))
    real = ledger.post_order_collected
    calls = {"n": 0}

    async def crash(order, scale=None):
        calls["n"] += 1
        raise RuntimeError("ledger write interrupted")
    monkeypatch.setattr(ledger, "post_order_collected", crash)
    r = _post(c, "evt_partial", gid, o["total_paise"])
    assert r.status_code == 500 and _ev(c, "evt_partial")["status"] == "failed"
    assert _get(c, o["id"])["payment_status"] == "paid" and _effects(c, o["id"])[0] == []       # paid, vendor sales not written yet
    monkeypatch.setattr(ledger, "post_order_collected", real)
    assert c.post("/api/admin/payment-events/evt_partial/retry", headers=_hdr("sup")).status_code == 403
    r = c.post("/api/admin/payment-events/evt_partial/retry", headers=_hdr("fin"))
    assert r.status_code == 200 and r.json()["status"] == "processed", r.text
    sales, comms = _effects(c, o["id"])
    assert len(sales) == 2 and comms == 1
    assert c.post("/api/admin/payment-events/evt_partial/retry", headers=_hdr("fin")).status_code == 409     # final now
    assert len(_ev(c, "evt_partial")["attempts"]) == 2
    assert _run(c, lambda: db.audit_logs.count_documents({"action": "payment_event_retried"})) == 1


def test_finance_can_list_events_that_need_attention(c):
    r = c.get("/api/admin/payment-events", params={"status": "rejected"}, headers=_hdr("fin")).json()
    assert r["total"] >= 2 and all(x["status"] == "rejected" for x in r["items"]) and r["attention"]["rejected"] >= 2
    assert c.get("/api/admin/payment-events", headers=_hdr("sup")).status_code == 403
    assert c.get("/api/admin/payment-events", headers=_hdr("cust")).status_code == 403


# ================================================================ no payout eligibility from payment alone
def test_a_verified_payment_does_not_make_money_payable_before_delivery(c):
    o, gid = _order(c)
    _post(c, "evt_elig", gid, o["total_paise"])
    order = _get(c, o["id"])
    assert _run(c, lambda: eligibility.payout_block(order)) == "not_delivered"
    assert _run(c, lambda: eligibility.payout_block(order, vendor_id=S["vA"]["id"])) == "not_delivered"
    comm = _run(c, lambda: db.commissions.find_one({"order_id": o["id"]}))
    assert comm["status"] == "PENDING" and not comm.get("released_at")
