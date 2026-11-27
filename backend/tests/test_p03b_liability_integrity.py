"""Programme 03-B: crash-safe refund obligations (P03-A01 customer cancellation of a paid order; P03-A02 late payment on a
cancelled order), their repair, and the `liabilities` reconciliation domain.

Crashes are injected after real database transitions (the claim, the restock, the sale reversal, the case, the marker clear, the
late-payment decision) and the PERSISTED state is checked, then recovered by the production repair paths. No real gateway:
Stripe is an in-memory fake. In-process, THROWAWAY database. Run in its own process:
`pytest tests/test_p03b_liability_integrity.py -n 0`.
"""
import asyncio
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": os.environ.get("DB_NAME", "homegenies_p03b_test"), "JWT_SECRET": "p03b-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("STRIPE_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import shop_routes  # noqa: E402
import returns_routes  # noqa: E402
import stock  # noqa: E402
import ledger as L  # noqa: E402
import late_payments  # noqa: E402
import reconciliation  # noqa: E402
from stripe_checkout import CheckoutStatusResponse, CheckoutSessionResponse, WebhookResponse  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

ADDR = {"full_name": "Ravi Menon", "mobile": "9000044444", "line1": "4 Road", "city": "Pune", "state": "MH", "pincode": "411001"}
S = {}
GOOD_SIG = "t=1,v1=fake-good"
PAST = "2000-01-01T00:00:00+00:00"


class Crash(Exception):
    pass


class FakeStripe:
    sessions: dict = {}
    down = False

    def __init__(self, *a, **k):
        pass

    async def create_checkout_session(self, req):
        sid = "cs_test_" + new_id().replace("-", "")[:20]
        FakeStripe.sessions[sid] = CheckoutStatusResponse("open", "unpaid", int(round(req.amount * 100)), req.currency, dict(req.metadata))
        return CheckoutSessionResponse(url=f"https://checkout.example.test/{sid}", session_id=sid)

    async def get_checkout_status(self, sid):
        if FakeStripe.down:
            raise RuntimeError("provider unavailable")
        if sid not in FakeStripe.sessions:
            raise RuntimeError("No such checkout session")
        return FakeStripe.sessions[sid]

    async def handle_webhook(self, body, sig):
        if sig != GOOD_SIG:
            raise ValueError("bad signature")
        d = json.loads(body)
        return WebhookResponse(event_type=d["type"], event_id=d["id"], session_id=d.get("session_id"), payment_status="paid", metadata={})


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
            for key, role, did in (("cust", "customer", "CU3B0001"), ("cust2", "customer", "CU3B0002"), ("hg", "distributor", "HG3B0001"),
                                   ("adm", "admin", "P3BADM"), ("fin", "accounts_admin", "P3BFIN"), ("va", "vendor", "P3BVA")):
                u = {"id": new_id(), "distributor_id": did, "full_name": key, "mobile": f"91000440{len(S):02d}", "email": None,
                     "password_hash": hash_password("Pass-1234x"), "role": role,
                     "status": "customer" if role == "customer" else "green", "account_status": "active",
                     "created_at": now_iso(), "updated_at": now_iso()}
                await db.users.insert_one(dict(u))
                S[key] = u
            S["vA"] = {"id": new_id(), "user_id": S["va"]["id"], "vendor_code": "P3BA", "business_name": "Vendor 3B", "status": "approved",
                       "categories": ["Sarees"], "created_at": now_iso(), "updated_at": now_iso()}
            await db.vendors.insert_one(dict(S["vA"]))
        _run(client, seed)
        yield client
        _run(client, lambda: server.client.drop_database(os.environ["DB_NAME"]))
    mp.undo()


@pytest.fixture(autouse=True)
def _clean_hooks():
    yield
    stock._FAULT = None
    FakeStripe.down = False


def _product(c, qty=50):
    pid = "p3b-" + new_id()[:8]
    _run(c, lambda: db.products.insert_one({"id": pid, "sku": pid.upper(), "name": "Saree", "images": [], "mrp": 1500, "selling_price": 1200.0,
                                            "gst_percent": 5, "stock": qty, "category": "Sarees", "options": [], "vendor_id": S["vA"]["id"],
                                            "vendor_name": "Vendor 3B", "is_active": True, "approval_status": "approved",
                                            "created_at": now_iso()}))
    return pid


def _order(c, pid, who="cust", qty=1):
    r = c.post("/api/orders", json={"items": [{"product_id": pid, "quantity": qty}], "address": ADDR, "payment_method": "online",
                                    "seller_ref": "HG3B0001"}, headers=_hdr(who))
    assert r.status_code == 200, r.text
    return r.json()


def _attempt(c, o, provider="stripe"):
    sid = "cs_test_" + new_id().replace("-", "")[:20]
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": sid, "order_id": o["id"], "user_id": o["user_id"],
                                                        "amount": o["total"], "amount_paise": o["total_paise"], "provider": provider,
                                                        "currency": "INR", "status": "initiated", "payment_status": "pending",
                                                        "created_at": now_iso()}))
    FakeStripe.sessions[sid] = CheckoutStatusResponse("open", "unpaid", o["total_paise"], "inr", {"order_id": o["id"]})
    return sid


def _stripe_paid(sid, **over):
    cur = FakeStripe.sessions[sid]
    FakeStripe.sessions[sid] = CheckoutStatusResponse("complete", over.get("payment_status", "paid"), over.get("amount", cur.amount_total),
                                                      over.get("currency", cur.currency), over.get("metadata", cur.metadata))


def _paid_order(c, qty=1):
    pid = _product(c)
    o = _order(c, pid, qty=qty)
    sid = _attempt(c, o)
    _run(c, lambda: shop_routes._process_paid_order(sid))
    assert _get(c, o["id"])["payment_status"] == "paid"
    return o, pid, sid


def _hook(c, event_id, sid):
    body = json.dumps({"id": event_id, "type": "checkout.session.completed", "session_id": sid})
    return c.post("/api/webhook/stripe", content=body, headers={"Stripe-Signature": GOOD_SIG, "Content-Type": "application/json"})


def _get(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _stock(c, pid):
    return _run(c, lambda: db.products.find_one({"id": pid}, {"_id": 0, "stock": 1}))["stock"]


def _cases(c, oid):
    return _run(c, lambda: db.refund_cases.find({"order_id": oid}, {"_id": 0}).to_list(20))


def _ledger(c, oid, etype):
    return _run(c, lambda: db.vendor_ledger.count_documents({"order_id": oid, "type": etype}))


def _cancel(c, o, who="cust"):
    return c.post(f"/api/orders/{o['id']}/cancel", json={"reason": "Changed my mind"}, headers=_hdr(who))


def _sweep(c):
    return _run(c, lambda: returns_routes.ensure_cases_for_flagged_orders())


def _expire_lease(c, oid):
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"late_payment_due.lease_until": PAST}}))


def _late_repair(c):
    return _run(c, lambda: late_payments.repair_late_payments())


def _stock_fault(point):
    def hook(p, **ctx):
        if p == point:
            stock._FAULT = None
            raise Crash(p)
    stock._FAULT = hook


def _a01_settled(c, o, pid, stock_before):
    """The single correct end state of a cancelled paid order (P03-A01)."""
    g = _get(c, o["id"])
    cases = _cases(c, o["id"])
    assert g["status"] == "cancelled" and g["payment_status"] == "paid" and "refund_due_cancel" not in g
    assert len(cases) == 1 and cases[0]["source_key"] == f"cancel:{o['id']}" and cases[0]["amount_paise"] == o["total_paise"]
    assert cases[0]["status"] == "awaiting_review"                           # recorded, not executed: no money moved
    assert _ledger(c, o["id"], "SALE_REVERSAL") == 1                          # the vendor sale taken back once
    assert _stock(c, pid) == stock_before + o["items"][0]["quantity"]          # stock returned once
    assert not g.get("restock_intents")
    return cases[0]


# ======================================================================== P03-A01: customer cancels a paid order
def test_a01_paid_cancellation_records_one_obligation(c):
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    r = _cancel(c, o)
    assert r.status_code == 200 and r.json()["refund_case"]
    case = _a01_settled(c, o, pid, before)
    assert r.json()["refund_case"] == case["number"]


def test_a01_retry_and_lost_response_create_no_second_obligation(c):
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    assert _cancel(c, o).status_code == 200
    for _ in range(3):                                                        # the client never saw the answer and retries
        assert _cancel(c, o).status_code == 400
    _sweep(c)
    _a01_settled(c, o, pid, before)


def test_a01_concurrent_cancellations_make_one_obligation(c):
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    codes = list(ThreadPoolExecutor(max_workers=6).map(lambda _: _cancel(c, o).status_code, range(6)))
    assert codes.count(200) == 1 and all(x in (400, 409) for x in codes if x != 200)
    _sweep(c)
    _a01_settled(c, o, pid, before)


@pytest.mark.parametrize("where", ["after_claim", "after_cancel_release", "before_intent_clear", "before_reversal",
                                   "before_case", "before_marker_clear", "before_audit"])
def test_a01_crash_at_every_step_is_recovered(c, monkeypatch, where):
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    if where == "after_claim":
        monkeypatch.setattr(returns_routes, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "customer_cancel_after_claim" else None)
    elif where in ("after_cancel_release", "before_intent_clear"):
        _stock_fault(where)
    elif where == "before_reversal":
        async def boom(*a, **k):
            raise Crash(where)
        monkeypatch.setattr(L, "post_sale_reversal", boom)
    elif where == "before_case":
        monkeypatch.setattr(returns_routes, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "settle_cancel_before_case" else None)
    elif where == "before_marker_clear":
        monkeypatch.setattr(returns_routes, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "settle_cancel_before_marker_clear" else None)
    elif where == "before_audit":
        async def boom(*a, **k):
            raise Crash(where)
        monkeypatch.setattr(returns_routes, "log_audit", boom)
    with pytest.raises(Crash):
        _run(c, lambda: returns_routes.customer_cancel(o["id"], returns_routes.CancelIn(reason="Crash test"), None, user=S["cust"]))
    monkeypatch.undo()
    stock._FAULT = None
    g = _get(c, o["id"])
    assert g["status"] == "cancelled"                                         # the cancellation is durable ...
    if where != "before_audit":                                               # ... and so is the obligation (marker or case)
        assert g.get("refund_due_cancel") is True or _cases(c, o["id"])
    # the reconciliation never reports this as unrecorded money: the marker IS the record until the case exists
    rep = _run(c, lambda: reconciliation.liabilities())
    assert o["id"] not in {i["order_id"] for i in rep["issues"]}
    _run(c, lambda: stock.run_recovery(limit=50, min_age_s=0))               # the production repairs, in maintenance order
    _sweep(c)
    _sweep(c)                                                                 # twice: no change
    _a01_settled(c, o, pid, before)


def test_a01_two_repair_workers_concurrently(c, monkeypatch):
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    monkeypatch.setattr(returns_routes, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "customer_cancel_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: returns_routes.customer_cancel(o["id"], returns_routes.CancelIn(reason="Crash test"), None, user=S["cust"]))
    monkeypatch.undo()

    async def race():
        return await asyncio.gather(*[returns_routes.settle_paid_cancellation(o["id"]) for _ in range(4)],
                                    returns_routes.ensure_cases_for_flagged_orders(), return_exceptions=True)
    res = _run(c, race)
    assert not [r for r in res if isinstance(r, BaseException)], res
    _sweep(c)
    _a01_settled(c, o, pid, before)


def test_a01_payment_landing_between_read_and_claim_never_cancels_without_obligation(c, monkeypatch):
    """A concurrent capture: the claim is conditional on the payment state the cancel request read."""
    pid = _product(c)
    o = _order(c, pid)
    sid = _attempt(c, o)
    orders_cls = type(db.orders)
    original = orders_cls.find_one
    state = {"done": False}

    async def find_then_pay(self, *a, **k):
        doc = await original(self, *a, **k)
        if self.name == "orders" and not state["done"] and a and isinstance(a[0], dict) and a[0].get("user_id") == S["cust"]["id"] \
                and a[0].get("id") == o["id"]:
            state["done"] = True
            await shop_routes._process_paid_order(sid)                        # the payment lands right after the cancel read
        return doc
    monkeypatch.setattr(orders_cls, "find_one", find_then_pay)
    r = _cancel(c, o)
    monkeypatch.setattr(orders_cls, "find_one", original)
    assert state["done"]                                                      # the payment really landed in the window
    g = _get(c, o["id"])
    assert r.status_code == 409 and g["payment_status"] == "paid" and g["status"] != "cancelled"     # never paid + cancelled + unrecorded
    assert _run(c, lambda: reconciliation.liabilities())["checks"]["cancelled_money_without_obligation"] == 0


def test_a01_admin_cancel_race_is_also_closed(c, monkeypatch):
    pid = _product(c)
    o = _order(c, pid)
    sid = _attempt(c, o)
    orders_cls = type(db.orders)
    original = orders_cls.find_one
    state = {"done": False}

    async def find_then_pay(self, *a, **k):
        doc = await original(self, *a, **k)
        if self.name == "orders" and not state["done"] and a and a[0] == {"id": o["id"]} and k.get("projection") is None \
                and len(a) > 1 and a[1] == {"_id": 0}:
            state["done"] = True
            await shop_routes._process_paid_order(sid)
        return doc
    monkeypatch.setattr(orders_cls, "find_one", find_then_pay)
    r = c.put(f"/api/admin/orders/{o['id']}/status", json={"status": "cancelled", "reason": "test"}, headers=_hdr("adm"))
    monkeypatch.setattr(orders_cls, "find_one", original)
    g = _get(c, o["id"])
    assert state["done"]                                                      # the payment really landed in the window
    assert r.status_code == 409 and g["payment_status"] == "paid" and g["status"] != "cancelled"
    assert not (g["status"] == "cancelled" and g["payment_status"] == "paid" and not g.get("refund_due_cancel") and not _cases(c, o["id"]))


def test_a01_existing_obligation_is_reused(c):
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    _run(c, lambda: returns_routes.open_refund_case(o, "cancellation", o["total_paise"], "pre-existing", f"cancel:{o['id']}"))
    assert _cancel(c, o).status_code == 200
    _a01_settled(c, o, pid, before)


def test_a01_refunded_order_cannot_create_an_obligation(c):
    o, _, _ = _paid_order(c)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"payment_status": "refunded"}}))
    assert _cancel(c, o).status_code == 409 and _cases(c, o["id"]) == []


def test_a01_unpaid_cancellation_with_unrelated_paid_payment_creates_no_obligation(c):
    """Invalid association: a paid attempt of ANOTHER order never makes this order's cancellation a refund obligation."""
    o1, _, _ = _paid_order(c)
    pid = _product(c)
    o2 = _order(c, pid)
    _run(c, lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": "cs_other_" + new_id()[:8], "order_id": o1["id"],
                                                        "payment_status": "paid", "status": "completed", "created_at": now_iso()}))
    assert _cancel(c, o2).status_code == 200
    g = _get(c, o2["id"])
    assert g["status"] == "cancelled" and "refund_due_cancel" not in g and _cases(c, o2["id"]) == []


def test_a01_works_without_any_payment_provider(c):
    """The obligation comes from the order's own payment state; the gateway is never needed to record it."""
    o, pid, _ = _paid_order(c)
    before = _stock(c, pid)
    FakeStripe.down = True
    assert _cancel(c, o).status_code == 200
    _a01_settled(c, o, pid, before)


# ======================================================================== P03-A02: payment lands on a cancelled order
def _cancelled_unpaid(c, who="cust"):
    pid = _product(c)
    o = _order(c, pid, who=who)
    sid = _attempt(c, o)
    assert _cancel(c, o, who=who).status_code == 200                          # customer cancels before paying
    return o, pid, sid


def _a02_owed(c, o, sid):
    """The single correct end state of a late payment on an order that stays cancelled (P03-A02)."""
    g = _get(c, o["id"])
    assert g["status"] == "cancelled" and g["payment_status"] == "paid" and g["paid_session_id"] == sid
    assert g.get("needs_refund") is True and "late_payment_due" not in g and not g.get("completion_due")
    _sweep(c)
    cases = _cases(c, o["id"])
    assert len(cases) == 1 and cases[0]["source_key"] == f"late:{o['id']}" and cases[0]["amount_paise"] == o["total_paise"]
    assert cases[0]["status"] == "awaiting_review"                           # an obligation, not an executed refund
    assert _ledger(c, o["id"], "SALE_COLLECTED") == 0                         # not treated as sale revenue
    assert _run(c, lambda: db.commission_plans.count_documents({"_id": o["id"]})) == 0
    assert not g.get("invoice_number")
    tx = _run(c, lambda: db.payment_transactions.find_one({"session_id": sid}, {"_id": 0}))
    assert tx["payment_status"] == "paid"                                     # the captured payment record is kept
    return cases[0]


def test_a02_late_stripe_payment_records_one_obligation(c):
    o, _, sid = _cancelled_unpaid(c)
    _stripe_paid(sid)
    assert _hook(c, "evt_3b_late", sid).json()["status"] == "processed"
    _a02_owed(c, o, sid)


def test_a02_duplicate_webhooks_and_status_checks_make_one_obligation(c):
    o, _, sid = _cancelled_unpaid(c)
    _stripe_paid(sid)
    assert _hook(c, "evt_3b_dup", sid).json()["status"] == "processed"
    assert _hook(c, "evt_3b_dup", sid).json()["status"] == "duplicate"
    assert _hook(c, "evt_3b_dup2", sid).json()["status"] == "processed"      # another event, same session: nothing new
    for _ in range(3):
        c.get(f"/api/payments/status/{sid}")
    _a02_owed(c, o, sid)


def test_a02_concurrent_webhook_and_status_check(c):
    o, _, sid = _cancelled_unpaid(c)
    _stripe_paid(sid)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda i: _hook(c, f"evt_3b_race_{i % 2}", sid) if i % 2 else c.get(f"/api/payments/status/{sid}"), range(8)))
    _a02_owed(c, o, sid)


@pytest.mark.parametrize("where", ["late_after_claim", "late_before_decision", "flag_refund", "late_before_marker_clear"])
def test_a02_crash_at_every_step_is_recovered(c, monkeypatch, where):
    o, _, sid = _cancelled_unpaid(c)
    if where == "flag_refund":
        async def boom(*a, **k):
            raise Crash(where)
        monkeypatch.setattr(stock, "_flag_refund", boom)
    else:
        monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == where else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    g = _get(c, o["id"])
    assert g["payment_status"] == "paid" and g["status"] == "cancelled"
    assert g.get("late_payment_due", {}).get("session_id") == sid             # the obligation is durable: the marker
    # completion must wait, not clear the marker or earn anything
    from order_completion import repair_incomplete_completions
    _run(c, lambda: repair_incomplete_completions())
    assert _get(c, o["id"]).get("completion_due") is True
    # while the lease is held the reconciliation shows it as pending, never as unrecorded money
    rep = _run(c, lambda: reconciliation.liabilities())
    assert rep["checks"]["cancelled_money_without_obligation"] == 0 and o["id"] not in {i["order_id"] for i in rep["issues"]}
    assert _late_repair(c)["updated"] == 0                                    # lease still held by the (dead) request
    _expire_lease(c, o["id"])
    rep = _run(c, lambda: reconciliation.liabilities())
    assert any(i["order_id"] == o["id"] and i["reason"] == "late_payment_decision_interrupted" for i in rep["issues"])
    res = _late_repair(c)
    assert res["updated"] == 1 and res["failed"] == 0
    assert _late_repair(c)["updated"] == 0                                    # run twice: nothing more
    _a02_owed(c, o, sid)


def test_a02_repair_and_redelivery_concurrently(c, monkeypatch):
    o, _, sid = _cancelled_unpaid(c)
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    _expire_lease(c, o["id"])

    async def race():
        return await asyncio.gather(late_payments.repair_late_payments(), late_payments.repair_late_payments(),
                                    shop_routes._process_paid_order(sid), return_exceptions=True)
    res = _run(c, race)
    assert not [r for r in res if isinstance(r, BaseException)]
    _a02_owed(c, o, sid)


@pytest.mark.parametrize("over,outcome", [({"amount": -1}, "rejected"), ({"currency": "usd"}, "rejected"),
                                          ({"metadata": {"order_id": "another-order"}}, "rejected"), ({"payment_status": "unpaid"}, "ignored")])
def test_a02_unverified_late_payment_changes_nothing(c, over, outcome):
    o, _, sid = _cancelled_unpaid(c)
    if "amount" in over:
        over = {"amount": o["total_paise"] - 1}
    _stripe_paid(sid, **over)
    assert _hook(c, "evt_3b_bad_" + new_id()[:6], sid).json()["status"] == outcome
    g = _get(c, o["id"])
    assert g["payment_status"] != "paid" and "late_payment_due" not in g and not g.get("needs_refund") and _cases(c, o["id"]) == []


def test_a02_fake_session_and_provider_outage(c):
    o, _, sid = _cancelled_unpaid(c)
    assert _hook(c, "evt_3b_fake", "cs_test_not_ours").json()["status"] == "unmatched"
    _stripe_paid(sid)
    FakeStripe.down = True
    assert _hook(c, "evt_3b_down", sid).status_code == 500                    # recorded as failed; nothing applied
    g = _get(c, o["id"])
    assert g["payment_status"] != "paid" and "late_payment_due" not in g
    FakeStripe.down = False
    assert _hook(c, "evt_3b_down", sid).json()["status"] == "processed"       # the gateway redelivers
    _a02_owed(c, o, sid)


def test_a02_cancelled_order_is_never_reopened(c):
    o, _, sid = _cancelled_unpaid(c)
    _run(c, lambda: shop_routes._process_paid_order(sid))
    _run(c, lambda: shop_routes._process_paid_order(sid))
    assert _get(c, o["id"])["status"] == "cancelled"
    _a02_owed(c, o, sid)


def test_a02_expired_order_follows_the_existing_revival_rule_even_after_a_crash(c, monkeypatch):
    """Unchanged rule: an order cancelled by the 15-minute payment expiry is restored when its stock can be taken back. A crash
    after the claim used to lose that decision; the completion repair must not erase the sale before the late repair runs."""
    pid = _product(c, qty=5)
    o = _order(c, pid)
    sid = _attempt(c, o)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"created_at": PAST}}))
    _run(c, lambda: stock.expire_one(o["id"]))
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, pid) == 5
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    from order_completion import repair_incomplete_completions
    _run(c, lambda: repair_incomplete_completions())                         # runs first: must wait
    assert _get(c, o["id"]).get("completion_due") is True
    _expire_lease(c, o["id"])
    _late_repair(c)
    g = _get(c, o["id"])
    assert g["status"] == "processing" and g["payment_status"] == "paid" and not g.get("needs_refund") and "late_payment_due" not in g
    assert _stock(c, pid) == 4 and _ledger(c, o["id"], "SALE_COLLECTED") == 1
    assert _run(c, lambda: db.commission_plans.count_documents({"_id": o["id"]})) == 1
    _late_repair(c)
    _run(c, lambda: repair_incomplete_completions())
    assert _ledger(c, o["id"], "SALE_COLLECTED") == 1 and _stock(c, pid) == 4 and _cases(c, o["id"]) == []


def test_a02_cancellation_and_capture_racing_end_in_exactly_one_valid_state(c):
    for _ in range(4):
        pid = _product(c)
        o = _order(c, pid)
        sid = _attempt(c, o)
        with ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(lambda: _cancel(c, o).status_code)
            f2 = ex.submit(lambda: _run(c, lambda: shop_routes._process_paid_order(sid)))
            f1.result(), f2.result()
        _sweep(c)
        g = _get(c, o["id"])
        cases = _cases(c, o["id"])
        if g["status"] == "cancelled" and g["payment_status"] == "paid":
            # cancelled with money in: exactly one obligation for the full amount (late payment, or a cancellation after payment)
            assert len(cases) == 1 and cases[0]["amount_paise"] == o["total_paise"]
            assert cases[0]["source_key"] in (f"late:{o['id']}", f"cancel:{o['id']}") and "late_payment_due" not in g
        elif g["status"] == "cancelled":
            assert g["payment_status"] == "pending" and cases == []          # cancelled before any money: nothing owed
        else:
            assert g["payment_status"] == "paid" and cases == []             # the payment won: an ordinary paid order


# ======================================================================== maintenance wiring
def test_maintenance_runs_late_payment_repair_before_completion(c, monkeypatch):
    o, _, sid = _cancelled_unpaid(c)
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    _expire_lease(c, o["id"])
    from cron_routes import run_maintenance
    mark = now_iso()
    out = _run(c, lambda: run_maintenance())
    assert "late_payments" in out and out["late_payments"]["failed"] == 0
    # resolved exactly once during maintenance (by the bounded repair inside the expiry step, which runs first)
    runs = _run(c, lambda: db.job_runs.find({"job": "late_payment_repair", "started_at": {"$gte": mark}}, {"_id": 0}).to_list(20))
    assert sum(r["updated"] for r in runs) == 1
    _a02_owed(c, o, sid)


# ======================================================================== reconciliation: liabilities domain
def _fingerprint(c):
    async def go():
        out = {}
        for name in sorted(await db.list_collection_names()):
            out[name] = sorted(json.dumps(d, default=str, sort_keys=True) for d in await db[name].find({}).to_list(None))
        return out
    return _run(c, go)


def _liab(c):
    return _run(c, lambda: reconciliation.liabilities())


def test_recon_clean_state_has_no_false_positive_and_is_read_only(c):
    _sweep(c)
    d = _liab(c)
    assert d["status"] == "ok", d["issues"][:5]
    before = _fingerprint(c)
    _run(c, lambda: reconciliation.run())
    r = c.get("/api/admin/finance/reconciliation", params={"domain": "liabilities"}, headers=_hdr("fin"))
    assert r.status_code == 200 and r.json()["domains"]["liabilities"]["status"] == "ok"
    assert _fingerprint(c) == before


def _injected(c, mutate, undo, check, reason):
    mutate()
    try:
        d = _liab(c)
        assert d["checks"][check] >= 1, d["checks"]
        hit = [i for i in d["issues"] if i["reason"] == reason]
        assert hit and {"severity", "order_id", "payment_session", "liability_id", "amount_paise", "currency", "gateway",
                        "detected_at", "remediation"} <= set(hit[0])
        return hit[0]
    finally:
        undo()
        assert _liab(c)["status"] == "ok"


def test_recon_detects_missing_liability(c):
    o, _, sid = _paid_order(c)
    hit = _injected(c, lambda: _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled"}})),
                    lambda: _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "processing"}})),
                    "cancelled_money_without_obligation", "cancelled_order_with_captured_money_and_no_obligation")
    assert hit["severity"] == "critical" and hit["payment_session"] == sid and hit["gateway"] == "stripe" \
        and hit["amount_paise"] == o["total_paise"]


def test_recon_detects_duplicate_liability(c):
    o, _, _ = _cancelled_unpaid(c)
    o2, pid, _ = _paid_order(c)
    assert _cancel(c, o2).status_code == 200
    extra = {}

    cancelled_o2 = _get(c, o2["id"])

    def mutate():
        extra["case"] = _run(c, lambda: returns_routes.open_refund_case(cancelled_o2, "late_payment", o2["total_paise"], "dup",
                                                                         f"late:{o2['id']}"))[0]

    def undo():
        _run(c, lambda: db.refund_cases.delete_one({"id": extra["case"]["id"]}))
    _injected(c, mutate, undo, "duplicate_order_liability", "more_than_one_order_level_liability")


def test_recon_detects_refund_owed_order_marked_active_or_as_revenue(c):
    o, _, sid = _cancelled_unpaid(c)
    _run(c, lambda: shop_routes._process_paid_order(sid))
    _sweep(c)
    _injected(c, lambda: _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "processing"}})),
              lambda: _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled"}})),
              "refund_owed_order_active", "refund_owed_but_order_active")
    _injected(c, lambda: _run(c, lambda: db.commission_plans.insert_one({"_id": o["id"], "items": [], "completed_at": None})),
              lambda: _run(c, lambda: db.commission_plans.delete_one({"_id": o["id"]})),
              "refund_owed_order_has_revenue", "refund_owed_order_recorded_as_revenue")


def test_recon_detects_orphan_liability(c):
    pid = _product(c)
    o = _order(c, pid)
    extra = {}

    def mutate():
        extra["case"] = _run(c, lambda: returns_routes.open_refund_case(o, "cancellation", 100, "orphan", f"cancel:{o['id']}"))[0]

    def undo():
        _run(c, lambda: db.refund_cases.delete_one({"id": extra["case"]["id"]}))
    _injected(c, mutate, undo, "orphan_liability", "liability_without_money_in")


def test_recon_detects_liabilities_exceeding_money_in(c):
    o, _, _ = _paid_order(c)
    extra = {}

    def mutate():
        extra["case"] = _run(c, lambda: returns_routes.open_refund_case(o, "return", o["total_paise"] + 500, "too much", f"ret:{o['id']}"))[0]

    def undo():
        _run(c, lambda: db.refund_cases.delete_one({"id": extra["case"]["id"]}))
    _injected(c, mutate, undo, "liabilities_exceed_money_in", "liabilities_exceed_money_in")


def test_recon_detects_duplicate_payment_reference(c):
    a, _, sa = _paid_order(c)
    b, _, sb = _paid_order(c)
    _injected(c, lambda: _run(c, lambda: db.payment_transactions.update_many({"session_id": {"$in": [sa, sb]}},
                                                                            {"$set": {"razorpay_payment_id": "pay_DUP_3B"}})),
              lambda: _run(c, lambda: db.payment_transactions.update_many({"session_id": {"$in": [sa, sb]}},
                                                                         {"$unset": {"razorpay_payment_id": ""}})),
              "duplicate_payment_reference", "razorpay_payment_id_used_for_more_than_one_order")


def test_recon_detects_mismatched_payment_amount(c):
    o, _, sid = _paid_order(c)
    _run(c, lambda: db.payment_transactions.update_one({"session_id": sid}, {"$set": {"gateway_amount_paise": 1}}))
    try:
        d = _run(c, lambda: reconciliation.payments())
        assert any(i.get("issue") == "gateway_amount_differs_from_order_total" for i in d["issues"])
    finally:
        _run(c, lambda: db.payment_transactions.update_one({"session_id": sid}, {"$unset": {"gateway_amount_paise": ""}}))


def test_recon_interrupted_late_payment_is_reported_until_repaired(c, monkeypatch):
    o, _, sid = _cancelled_unpaid(c)
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    _expire_lease(c, o["id"])
    before = _fingerprint(c)
    d = _liab(c)
    assert d["checks"]["late_payment_unresolved"] == 1 and _fingerprint(c) == before      # reported, not repaired
    _late_repair(c)
    _sweep(c)
    assert _liab(c)["status"] == "ok"


# ======================================================================== review findings P03B-R01 / R02 / R03
def _expired_order(c, qty=1, stock_qty=5):
    pid = _product(c, qty=stock_qty)
    o = _order(c, pid, qty=qty)
    sid = _attempt(c, o)
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"created_at": PAST}}))
    _run(c, lambda: stock.expire_one(o["id"]))
    assert _get(c, o["id"])["status"] == "cancelled" and _stock(c, pid) == stock_qty
    return o, pid, sid


def test_r01_repair_after_a_crash_inside_the_revival_never_hands_the_stock_back(c):
    """Crash after the revival re-reserved the stock but before the order was restored; the late repair runs BEFORE stock
    recovery. It must finish that revival, not decide again (which released the revived stock: oversell)."""
    o, pid, sid = _expired_order(c, qty=2, stock_qty=5)
    _stock_fault("before_finish_revival")
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    stock._FAULT = None
    assert _stock(c, pid) == 3 and _get(c, o["id"])["status"] == "cancelled"   # re-reserved, not yet restored
    _expire_lease(c, o["id"])
    _late_repair(c)                                                          # before run_recovery
    g = _get(c, o["id"])
    assert g["status"] == "processing" and not g.get("needs_refund") and "late_payment_due" not in g
    assert _stock(c, pid) == 3                                               # the revival's stock stays reserved, once
    _run(c, lambda: stock.run_recovery(limit=50, min_age_s=0))
    _late_repair(c)
    assert _stock(c, pid) == 3 and _ledger(c, o["id"], "SALE_COLLECTED") == 1 and _cases(c, o["id"]) == []


def test_r02_a_stale_actor_after_its_lease_expired_changes_nothing(c, monkeypatch):
    """The paying request is slower than its lease: the repair restores the order, the vendor starts work, then the original
    request continues from its stale read. It must not release / re-reserve stock, reset the vendor's progress or flag a refund."""
    o, pid, sid = _expired_order(c, qty=1, stock_qty=5)
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    stale = _get(c, o["id"])                                                 # what the slow request read: cancelled
    _expire_lease(c, o["id"])
    _late_repair(c)
    assert _get(c, o["id"])["status"] == "processing" and _stock(c, pid) == 4
    _run(c, lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"fulfilments.0.status": "accepted"}}))
    before = _get(c, o["id"])
    _run(c, lambda: stock.handle_late_payment(stale, allow_revive=True))     # the stale actor resumes
    assert _run(c, lambda: stock._flag_refund(o["id"], "stale")) is False
    after = _get(c, o["id"])
    assert _stock(c, pid) == 4 and after["fulfilments"][0]["status"] == "accepted" and not after.get("needs_refund")
    assert after.get("revive_count") == before.get("revive_count") and after["status"] == "processing"


def test_r03_redelivery_after_the_lease_finishes_the_decision_at_once(c, monkeypatch):
    o, _, sid = _cancelled_unpaid(c)
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    _run(c, lambda: shop_routes._process_paid_order(sid))                   # within the lease: waits
    assert "late_payment_due" in _get(c, o["id"])
    _expire_lease(c, o["id"])
    _run(c, lambda: shop_routes._process_paid_order(sid))                   # the gateway redelivers: decided now
    _a02_owed(c, o, sid)


def test_r03_refund_recorded_before_the_decision_prevents_revival_and_a_second_liability(c, monkeypatch):
    o, pid, sid = _expired_order(c, qty=1, stock_qty=5)
    monkeypatch.setattr(late_payments, "_fault", lambda p, **k: (_ for _ in ()).throw(Crash(p)) if p == "late_after_claim" else None)
    with pytest.raises(Crash):
        _run(c, lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    r = c.post(f"/api/admin/orders/{o['id']}/refund", json={"reference": "RFND-3B-0001", "reason": "Customer asked"}, headers=_hdr("fin"))
    assert r.status_code == 200, r.text                                      # finance records the refund in the window
    _expire_lease(c, o["id"])
    _late_repair(c)
    _sweep(c)
    g = _get(c, o["id"])
    assert g["status"] == "cancelled" and g.get("needs_refund") is True and _stock(c, pid) == 5      # not restored
    live = [x for x in _cases(c, o["id"]) if x["status"] in ("awaiting_review", "initiated", "failed")]
    assert len(live) == 1 and sum(x["amount_paise"] for x in live) == o["total_paise"]             # one liability, once
    assert _liab(c)["checks"]["liabilities_exceed_money_in"] == 0
