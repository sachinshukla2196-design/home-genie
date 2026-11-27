"""Programme 03 (DEF-05): Stripe payment-completion integrity.

A Stripe webhook or the browser's status poll may complete an order only when Stripe's OWN record of the checkout session (read
server-to-server) says paid, in INR, for exactly the order total in paise, for the order our payment attempt belongs to. Every
delivery is recorded once in webhook_events (provider stripe) with the same claim / outcome / finance-retry rules as Razorpay, and
the order is paid only through the one idempotent state machine (no duplicate sale, commission, invoice or stock movement).

No real Stripe: shop_routes._stripe is replaced by an in-memory fake (no network, no credentials).
In-process, THROWAWAY database. Run in its own process: `pytest tests/test_p03_stripe_integrity.py -n 0`.
"""
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": os.environ.get("DB_NAME", "homegenies_p03_stripe_test"), "JWT_SECRET": "p03stripe-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("STRIPE_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
from stripe_checkout import CheckoutStatusResponse, CheckoutSessionResponse, WebhookResponse  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Asha Rao", "mobile": "9000022222", "line1": "2 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
GOOD_SIG = "t=1,v1=fake-good"


class FakeStripe:
    """In-memory stand-in for stripe_checkout.StripeCheckout. `sessions[sid]` is what Stripe itself would report."""
    sessions: dict = {}
    created: list = []
    status_calls: list = []

    def __init__(self, *a, **k):
        pass

    async def create_checkout_session(self, req):
        sid = "cs_test_" + new_id().replace("-", "")[:20]
        FakeStripe.created.append({"sid": sid, "amount": req.amount, "currency": req.currency, "metadata": dict(req.metadata)})
        FakeStripe.sessions[sid] = CheckoutStatusResponse(status="open", payment_status="unpaid",
                                                          amount_total=int(round(req.amount * 100)), currency=req.currency,
                                                          metadata=dict(req.metadata))
        return CheckoutSessionResponse(url=f"https://checkout.example.test/{sid}", session_id=sid)

    async def get_checkout_status(self, sid):
        FakeStripe.status_calls.append(sid)
        if sid not in FakeStripe.sessions:
            raise RuntimeError("No such checkout session")
        return FakeStripe.sessions[sid]

    async def handle_webhook(self, body, sig):
        if sig != GOOD_SIG:
            raise ValueError("signature verification failed")
        d = json.loads(body)
        return WebhookResponse(event_type=d.get("type"), event_id=d.get("id"), session_id=d.get("session_id"),
                               payment_status=d.get("payment_status"), metadata={})


def _hdr(key):
    return {"Authorization": f"Bearer {create_token(S[key]['id'])}"}


def _run(c, fn):
    return c.portal.call(fn)


@pytest.fixture(scope="module")
def c():
    mp = pytest.MonkeyPatch()
    mp.setattr(shop_routes, "_stripe", lambda request: FakeStripe())
    with TestClient(server.app, raise_server_exceptions=False) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            for key, role, did in (("cust", "customer", "CU030001"), ("hg", "distributor", "HG030001"), ("fin", "accounts_admin", "P03FIN"),
                                   ("sup", "support_admin", "P03SUP"), ("va", "vendor", "P03VA")):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": f"91000330{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role, "status": "green" if role != "customer" else "customer",
                     "account_status": "active", "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            S["vA"] = {"id": new_id(), "user_id": S["va"]["id"], "vendor_code": "P3A", "business_name": "Vendor A", "status": "approved",
                       "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["vA"]))
            await db.products.insert_one({"id": "p3A", "sku": "P3-A", "name": "Saree A", "images": [], "mrp": 1200, "selling_price": 1050.55,
                                          "gst_percent": 5, "stock": 500, "category": "Sarees", "options": [], "vendor_id": S["vA"]["id"],
                                          "vendor_name": "Vendor A", "is_active": True, "approval_status": "approved", "created_at": now_iso()})
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))
    mp.undo()


def _order(c, qty=1, ref="HG030001"):
    o = c.post("/api/orders", json={"items": [{"product_id": "p3A", "quantity": qty}], "address": ADDR, "payment_method": "online",
                                    **({"seller_ref": ref} if ref else {})}, headers=_hdr("cust"))
    assert o.status_code == 200, o.text
    return o.json()


def _checkout(c, o):
    r = c.post("/api/payments/checkout", json={"order_id": o["id"], "origin_url": "https://shop.example.test"}, headers=_hdr("cust"))
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _pay(sid, **over):
    """Stripe now reports the session paid (optionally with other figures)."""
    cur = FakeStripe.sessions[sid]
    FakeStripe.sessions[sid] = CheckoutStatusResponse(status=over.get("status", "complete"), payment_status=over.get("payment_status", "paid"),
                                                      amount_total=over.get("amount_total", cur.amount_total),
                                                      currency=over.get("currency", cur.currency), metadata=over.get("metadata", cur.metadata))


def _hook(c, event_id, sid, etype="checkout.session.completed", sig=GOOD_SIG):
    body = json.dumps({"id": event_id, "type": etype, "session_id": sid, "payment_status": "paid"})
    return c.post("/api/webhook/stripe", content=body, headers={"Stripe-Signature": sig, "Content-Type": "application/json"})


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _ev(c, eid):
    return _run(c, lambda: db.webhook_events.find_one({"event_id": eid}, {"_id": 0}))


def _effects(c, oid):
    sales = _run(c, lambda: db.vendor_ledger.count_documents({"order_id": oid, "type": "SALE_COLLECTED"}))
    comms = _run(c, lambda: db.commissions.count_documents({"order_id": oid}))
    stock = _run(c, lambda: db.products.find_one({"id": "p3A"}, {"_id": 0, "stock": 1}))["stock"]
    return sales, comms, stock


# ================================================================ checkout records the exact amount
def test_checkout_sends_and_records_the_exact_paise_total(c):
    o = _order(c)
    sid = _checkout(c, o)
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": sid}, {"_id": 0}))
    assert tx["provider"] == "stripe" and tx["amount_paise"] == o["total_paise"] and tx["payment_status"] == "pending"
    sent = [x for x in FakeStripe.created if x["sid"] == sid][0]
    assert int(round(sent["amount"] * 100)) == o["total_paise"] and sent["metadata"]["order_id"] == o["id"]


# ================================================================ webhook: the happy path
def test_valid_webhook_pays_the_order_once_and_is_recorded(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    r = _hook(c, "evt_ok_1", sid)
    assert r.status_code == 200 and r.json()["status"] == "processed"
    order = _get(c, o["id"])
    assert order["payment_status"] == "paid" and order["paid_session_id"] == sid and not order.get("completion_due")
    ev = _ev(c, "stripe:evt_ok_1")
    assert ev["provider"] == "stripe" and ev["status"] == "processed" and ev["applied"] is True and ev["order_id"] == o["id"]
    assert ev["amount_paise"] == o["total_paise"] and ev["currency"] == "INR" and ev["gateway_status"] == "paid"
    assert "metadata" not in ev and S["cust"]["id"] not in json.dumps(ev)                # no gateway payload / personal data kept
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": sid}, {"_id": 0}))
    assert tx["payment_status"] == "paid" and tx["gateway_amount_paise"] == o["total_paise"] and tx["verified_at"]
    sales, comms, _ = _effects(c, o["id"])
    assert sales == 1 and comms == 1


def test_async_payment_succeeded_is_acted_on(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    assert _hook(c, "evt_async_1", sid, etype="checkout.session.async_payment_succeeded").json()["status"] == "processed"
    assert _get(c, o["id"])["payment_status"] == "paid"


# ================================================================ authenticity and shape
def test_bad_signature_and_malformed_events_are_refused_and_not_recorded(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    assert _hook(c, "evt_badsig", sid, sig="t=1,v1=forged").status_code == 400
    r = c.post("/api/webhook/stripe", content=json.dumps({"type": "checkout.session.completed", "session_id": sid}),
               headers={"Stripe-Signature": GOOD_SIG})
    assert r.status_code == 400                                                         # no event id
    assert _ev(c, "stripe:evt_badsig") is None and _get(c, o["id"])["payment_status"] == "pending"


def test_other_event_types_are_recorded_as_ignored(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    r = _hook(c, "evt_expired", sid, etype="checkout.session.expired")
    assert r.json()["status"] == "ignored" and _get(c, o["id"])["payment_status"] == "pending"


# ================================================================ validation against Stripe's own record
@pytest.mark.parametrize("over,reason", [
    ({"amount_total": -1}, "amount"),                 # filled in below as total - 1
    ({"amount_total": +1}, "amount"),
    ({"currency": "usd"}, "currency"),
    ({"metadata": {"order_id": "someone-elses-order"}}, "another order"),
])
def test_mismatched_payment_is_rejected_and_changes_nothing(c, over, reason):
    o = _order(c)
    sid = _checkout(c, o)
    if "amount_total" in over:
        over = {"amount_total": o["total_paise"] + over["amount_total"]}
    _pay(sid, **over)
    _, _, stock_before = _effects(c, o["id"])
    eid = "evt_mis_" + new_id()[:8]
    r = _hook(c, eid, sid)
    assert r.status_code == 200 and r.json()["status"] == "rejected" and reason in _ev(c, "stripe:" + eid)["reason"]
    order = _get(c, o["id"])
    assert order["payment_status"] == "pending" and not order.get("paid_session_id")
    assert _effects(c, o["id"]) == (0, 0, stock_before)


def test_webhook_body_figures_are_never_trusted(c):
    """The webhook says paid but Stripe's own record says unpaid: nothing happens (ignored), and a later real event still works."""
    o = _order(c)
    sid = _checkout(c, o)
    r = _hook(c, "evt_early", sid)
    assert r.json()["status"] == "ignored" and _get(c, o["id"])["payment_status"] == "pending"
    _pay(sid)
    assert _hook(c, "evt_real", sid).json()["status"] == "processed" and _get(c, o["id"])["payment_status"] == "paid"


def test_unknown_session_and_foreign_provider_are_unmatched(c):
    assert _hook(c, "evt_unknown", "cs_test_not_ours").json()["status"] == "unmatched"
    o = _order(c)
    rzp = "order_rzp_p03_" + new_id()[:6]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": rzp, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "currency": "INR", "provider": "razorpay",
                                                        "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    FakeStripe.sessions[rzp] = CheckoutStatusResponse("complete", "paid", o["total_paise"], "inr", {"order_id": o["id"]})
    assert _hook(c, "evt_foreign", rzp).json()["status"] == "unmatched"        # a Razorpay attempt can never be paid by a Stripe event
    assert _get(c, o["id"])["payment_status"] == "pending"


def test_legacy_attempt_without_provider_is_still_ours(c):
    o = _order(c)
    sid = _checkout(c, o)
    _run(c, lambda: db.payment_transactions.update_one({"session_id": sid}, {"$unset": {"provider": "", "amount_paise": ""}}))
    _pay(sid)
    assert _hook(c, "evt_legacy", sid).json()["status"] == "processed"
    assert _run(c, lambda: db.payment_transactions.find_one({"session_id": sid}))["provider"] == "stripe"


# ================================================================ idempotency and races
def test_duplicate_and_concurrent_deliveries_have_one_effect(c):
    o = _order(c, qty=2)
    sid = _checkout(c, o)
    _pay(sid)
    _, _, stock_before = _effects(c, o["id"])
    outs = list(ThreadPoolExecutor(max_workers=6).map(lambda _: _hook(c, "evt_conc", sid).json()["status"], range(6)))
    assert outs.count("processed") == 1 and outs.count("duplicate") == 5
    assert _hook(c, "evt_conc", sid).json()["status"] == "duplicate"
    assert _effects(c, o["id"]) == (1, 1, stock_before)                     # stock was reserved at order time; payment moves none


def test_two_different_events_for_one_session_apply_once(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    assert _hook(c, "evt_a", sid).json()["status"] == "processed"
    r = _hook(c, "evt_b", sid, etype="checkout.session.async_payment_succeeded")
    assert r.json()["status"] == "processed"          # `applied` on an event means "this session is the order's payment"
    assert _get(c, o["id"])["paid_session_id"] == sid and _effects(c, o["id"])[:2] == (1, 1)     # the effects happened once


def test_status_poll_and_webhook_race_apply_once(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)

    def poll(_):
        return c.get(f"/api/payments/status/{sid}").json()["payment_status"]

    def hook(i):
        return _hook(c, f"evt_race_{i % 2}", sid).json()["status"]
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: poll(i) if i % 2 else hook(i), range(8)))
    assert _get(c, o["id"])["payment_status"] == "paid" and _effects(c, o["id"])[:2] == (1, 1)
    bad = _run(c, lambda: db.webhook_events.count_documents({"session_id": sid, "status": {"$nin": ["processed"]}}))
    assert bad == 0                                                    # every recorded event finished cleanly; no failures


# ================================================================ the browser status poll
def test_poll_records_nothing_until_stripe_says_paid(c):
    o = _order(c)
    sid = _checkout(c, o)
    for _ in range(3):
        r = c.get(f"/api/payments/status/{sid}")
        assert r.status_code == 200 and r.json()["payment_status"] == "pending"
    assert _ev(c, f"stripe:checkout:{sid}") is None
    _pay(sid)
    r = c.get(f"/api/payments/status/{sid}")
    assert r.json()["payment_status"] == "paid" and r.json()["order_id"] == o["id"]
    ev = _ev(c, f"stripe:checkout:{sid}")
    assert ev["type"] == "status_check" and ev["status"] == "processed" and ev["applied"] is True
    calls = len(FakeStripe.status_calls)
    for _ in range(3):
        assert c.get(f"/api/payments/status/{sid}").json()["payment_status"] == "paid"
    assert len(FakeStripe.status_calls) == calls                                  # a paid attempt is not re-checked
    assert _effects(c, o["id"])[:2] == (1, 1)


def test_poll_with_wrong_amount_does_not_pay(c):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid, amount_total=o["total_paise"] - 100)
    r = c.get(f"/api/payments/status/{sid}")
    assert r.status_code == 200 and r.json()["payment_status"] == "pending"
    assert _ev(c, f"stripe:checkout:{sid}")["status"] == "rejected" and _get(c, o["id"])["payment_status"] == "pending"


def test_poll_never_calls_stripe_for_other_providers(c):
    o = _order(c)
    rzp = "order_rzp_p03poll_" + new_id()[:6]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": rzp, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "currency": "INR", "provider": "razorpay",
                                                        "status": "initiated", "payment_status": "pending", "created_at": now_iso()}))
    before = len(FakeStripe.status_calls)
    assert c.get(f"/api/payments/status/{rzp}").json()["payment_status"] == "pending"
    assert len(FakeStripe.status_calls) == before


def test_poll_when_card_checkout_is_not_configured_stays_pending(c, monkeypatch):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    from fastapi import HTTPException

    def unconfigured(request):
        raise HTTPException(status_code=503, detail="Card checkout is not configured yet.")
    monkeypatch.setattr(shop_routes, "_stripe", unconfigured)
    r = c.get(f"/api/payments/status/{sid}")
    assert r.status_code == 200 and r.json()["payment_status"] == "pending"


def test_poll_gateway_error_stays_pending_and_is_retried(c):
    o = _order(c)
    sid = _checkout(c, o)
    FakeStripe.sessions.pop(sid)                                       # Stripe errors on the lookup
    r = c.get(f"/api/payments/status/{sid}")
    assert r.status_code == 200 and r.json()["payment_status"] == "pending"
    FakeStripe.sessions[sid] = CheckoutStatusResponse("complete", "paid", o["total_paise"], "inr", {"order_id": o["id"]})
    assert c.get(f"/api/payments/status/{sid}").json()["payment_status"] == "paid"


# ================================================================ failure, recovery and finance retry
def test_failed_processing_is_recorded_and_finance_retry_completes_it(c, monkeypatch):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    real = shop_routes._process_paid_order

    async def boom(*a, **k):
        raise RuntimeError("database went away")
    monkeypatch.setattr(shop_routes, "_process_paid_order", boom)
    r = _hook(c, "evt_fail", sid)
    assert r.status_code == 500
    ev = _ev(c, "stripe:evt_fail")
    assert ev["status"] == "failed" and _get(c, o["id"])["payment_status"] == "pending"
    monkeypatch.setattr(shop_routes, "_process_paid_order", real)
    assert c.post("/api/admin/payment-events/stripe:evt_fail/retry", headers=_hdr("sup")).status_code == 403   # finance only
    r = c.post("/api/admin/payment-events/stripe:evt_fail/retry", headers=_hdr("fin"))
    assert r.status_code == 200 and r.json()["status"] == "processed"
    assert _get(c, o["id"])["payment_status"] == "paid" and _effects(c, o["id"])[:2] == (1, 1)
    assert c.post("/api/admin/payment-events/stripe:evt_fail/retry", headers=_hdr("fin")).status_code == 409    # final now


def test_stripe_redelivery_after_failure_completes_it(c, monkeypatch):
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)

    async def boom(*a, **k):
        raise RuntimeError("transient")
    with monkeypatch.context() as m:
        m.setattr(shop_routes, "_process_paid_order", boom)
        assert _hook(c, "evt_redeliver", sid).status_code == 500
    assert _hook(c, "evt_redeliver", sid).json()["status"] == "processed"
    assert _effects(c, o["id"])[:2] == (1, 1)


def test_finance_retry_rereads_stripe_not_the_stored_figures(c, monkeypatch):
    """A failed event is retried against Stripe's CURRENT record: if Stripe now reports a different amount it is rejected."""
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)

    async def boom(*a, **k):
        raise RuntimeError("transient")
    with monkeypatch.context() as m:
        m.setattr(shop_routes, "_process_paid_order", boom)
        assert _hook(c, "evt_reread", sid).status_code == 500
    _pay(sid, amount_total=o["total_paise"] - 1)
    r = c.post("/api/admin/payment-events/stripe:evt_reread/retry", headers=_hdr("fin"))
    assert r.status_code == 200 and r.json()["status"] == "rejected" and _get(c, o["id"])["payment_status"] == "pending"


def test_crash_after_payment_claim_is_finished_by_completion(c, monkeypatch):
    """The order is claimed paid, then completion crashes: the event is failed, the order carries completion_due, and a retry
    finishes the completion without a second sale or commission."""
    import order_completion
    o = _order(c)
    sid = _checkout(c, o)
    _pay(sid)
    real = order_completion.complete_paid_order

    async def boom(*a, **k):
        raise RuntimeError("crash during completion")
    with monkeypatch.context() as m:
        m.setattr(order_completion, "complete_paid_order", boom)
        assert _hook(c, "evt_cc", sid).status_code == 500
    assert _get(c, o["id"])["payment_status"] == "paid" and _get(c, o["id"]).get("completion_due") is True
    assert order_completion.complete_paid_order is real
    r = c.post("/api/admin/payment-events/stripe:evt_cc/retry", headers=_hdr("fin"))
    assert r.status_code == 200
    assert not _get(c, o["id"]).get("completion_due") and _effects(c, o["id"])[:2] == (1, 1)


def test_late_payment_for_an_expired_order_follows_the_existing_rules(c):
    o = _order(c)
    sid = _checkout(c, o)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled", "payment_status": "pending",
                                                                   "cancel_reason": "admin_cancelled"}}))
    _pay(sid)
    r = _hook(c, "evt_late", sid)
    assert r.status_code == 200 and r.json()["status"] == "processed"
    order = _get(c, o["id"])
    assert order["status"] == "cancelled" and _effects(c, o["id"])[:2] == (0, 0)          # never re-opened, nothing earned


def test_events_appear_in_the_finance_payment_events_list(c):
    r = c.get("/api/admin/payment-events", params={"q": "stripe:evt_ok_1"}, headers=_hdr("fin"))
    assert r.status_code == 200
    (row,) = r.json()["items"]
    assert row["provider"] == "stripe" and row["status"] == "processed"
    assert c.get("/api/admin/payment-events", headers=_hdr("sup")).status_code == 403
