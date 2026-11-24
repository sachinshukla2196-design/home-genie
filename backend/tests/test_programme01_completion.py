"""Programme 01 / B-003: every payment path finishes through ONE idempotent completion step (order_completion), guarded by a
durable `completion_due` marker written with the paid claim; a crash at any point is finished by a retry of the same payment or
by the resumable repair sweep, with no duplicate money effects.

Paths exercised: gateway completion entry (`_process_paid_order` - what the Stripe status poll / webhook and the Razorpay verify
call; the SDKs themselves are not configured in tests), Razorpay webhook (signed, in-process), admin UPI confirmation, admin
manual payment, COD collection, COD discrepancy resolution.

Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_completion.py -n 0`.
"""
import hashlib
import hmac
import json
import os
import threading

import pytest

SECRET = "p01-webhook-secret"
os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_completion_test", "JWT_SECRET": "p01-completion-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret",
                   "RAZORPAY_WEBHOOK_SECRET": SECRET})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import commission  # noqa: E402
import order_completion  # noqa: E402
import returns_routes  # noqa: E402
import shop_routes  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402
from p01_harness import World, seed_world, hdr  # noqa: E402

S = {}


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "PC")
        client.portal.call(seed)
        yield World(client, S, "PCSELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _completed(w, oid, vendors=("va",)):
    """The full post-payment state: marker gone, completion stamped, invoice, vendor sale per group, frozen commission plan."""
    o = w.get(oid)
    assert o["payment_status"] == "paid" and "completion_due" not in o, o.get("completion")
    assert o["completion"]["outcome"] == "completed" and o.get("invoice_number")
    for v in vendors:
        assert len(w.ledger(oid, "SALE_COLLECTED", v)) == 1
    plan = w.plan(oid)
    assert plan is not None and plan.get("completed_at")
    return o


def _notifications(w, oid, kind="payment_success"):
    number = w.get(oid)["order_number"]
    return w.run(lambda: db.notifications.count_documents({"type": kind, "message": {"$regex": number}}))


def _pay(w, o, sid=None):
    sid = sid or w.tx(o)
    w.run(lambda: shop_routes._process_paid_order(sid))
    return sid


# ================================================================ every path ends in the same completed state
def test_gateway_entry_point_completes(w):
    o = w.order([(w.product("va", 1000), 1)])
    _pay(w, o)
    _completed(w, o["id"])
    assert w.get(o["id"])["completion"]["source"].startswith("payment:")


def test_razorpay_webhook_completes(w):
    o = w.order([(w.product("va", 1000), 1)])
    gid = "order_rzp_p01_" + o["id"][:8]
    w.run(lambda: db.payment_transactions.insert_one({"id": new_id(), "session_id": gid, "order_id": o["id"], "user_id": o["user_id"],
                                                      "amount": o["total"], "currency": "INR", "provider": "razorpay", "status": "initiated",
                                                      "payment_status": "pending", "created_at": now_iso()}))
    w.run(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"razorpay_order_id": gid}}))
    entity = {"id": "pay_" + gid, "order_id": gid, "status": "captured", "currency": "INR", "amount": o["total_paise"]}
    body = json.dumps({"event": "payment.captured", "payload": {"payment": {"entity": entity}}}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    for _ in range(2):                                  # the gateway delivers the same event twice
        r = w.c.post("/api/webhook/razorpay", content=body, headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_" + gid,
                                                                       "Content-Type": "application/json"})
        assert r.status_code == 200, r.text
    _completed(w, o["id"])


def test_admin_upi_confirmation_completes(w):
    o = w.order([(w.product("va", 1000), 1)])
    assert w.c.post("/api/payments/upi-claim", json={"order_id": o["id"], "reference": "UPI-P01-" + o["id"][:6]},
                    headers=hdr(S["cust"]["id"])).status_code == 200
    r = w.c.put(f"/api/admin/payments/upi-confirm/{o['id']}", json={"reference": "UTRP01" + o["id"][:6], "amount": o["total"]},
                headers=hdr(S["fin"]["id"]))
    assert r.status_code == 200, r.text
    _completed(w, o["id"])


def test_admin_manual_payment_completes(w):
    o = w.order([(w.product("va", 1000), 1)], who="seller", seller=False)      # the HomeGenie's own purchase, no attribution
    r = w.c.post("/api/admin/payments/manual", json={"distributor_id": S["seller"]["distributor_id"], "reference": "BANK-P01-" + o["id"][:6],
                                                    "amount": o["total"]}, headers=hdr(S["fin"]["id"]))
    assert r.status_code == 200, r.text
    got = w.get(o["id"])
    assert got["payment_status"] == "paid" and "completion_due" not in got and got["completion"]["outcome"] == "completed"
    assert len(w.ledger(o["id"], "SALE_COLLECTED", "va")) == 1
    assert w.comms(o["id"]) == []                          # self-purchase: never a commission


def test_cod_collection_completes_without_online_notification(w):
    o = w.order([(w.product("va", 1000), 1)], method="cod")
    w.deliver("va", o["id"])
    o = w.get(o["id"])
    body = {"amount_collected": o["total"], "evidence_type": "courier_confirmation", "evidence_reference": "COD-P01-" + o["id"][:6]}
    r = w.c.post(f"/api/orders/{o['id']}/cod-collected", json=body, headers=hdr(S["adm"]["id"]))
    assert r.status_code == 200, r.text
    _completed(w, o["id"])
    assert w.get(o["id"]).get("paid_notified") is not True


def test_cod_discrepancy_resolution_completes_and_a_short_collection_earns_no_commission(w):
    o = w.order([(w.product("va", 1000), 1)], method="cod")
    w.deliver("va", o["id"])
    o = w.get(o["id"])
    body = {"amount_collected": o["total"] - 100, "evidence_type": "courier_confirmation", "evidence_reference": "COD-SHORT-" + o["id"][:6]}
    assert w.c.post(f"/api/orders/{o['id']}/cod-collected", json=body, headers=hdr(S["adm"]["id"])).json().get("discrepancy")
    r = w.c.post(f"/api/admin/finance/cod-discrepancies/{o['id']}/resolve",
                 json={"resolution": "accept_short", "collected_amount": o["total"] - 100, "evidence_type": "courier_confirmation",
                       "evidence_reference": "COD-SHORT-REV", "reason": "Courier remitted less; accepted after review"},
                 headers=hdr(S["fin"]["id"]))
    assert r.status_code == 200, r.text
    got = w.get(o["id"])
    assert got["payment_status"] == "paid" and "completion_due" not in got and got["completion"]["outcome"] == "completed"
    assert len(w.ledger(o["id"], "SALE_COLLECTED", "va")) == 1 and w.plan(o["id"]) is None


# ================================================================ crashes at every point, then recovery
@pytest.mark.parametrize("where", ["after_paid_claim", "after_vendor_sale", "after_plan_frozen", "before_notification"])
def test_a_crash_at_any_point_is_finished_by_a_retry_of_the_same_payment(w, monkeypatch, where):
    o = w.order([(w.product("va", 1000), 1)])
    sid = w.tx(o)
    boom = RuntimeError("simulated crash: " + where)
    if where == "after_paid_claim":
        monkeypatch.setattr(order_completion, "complete_paid_order", lambda *a, **k: (_ for _ in ()).throw(boom))
    elif where == "after_vendor_sale":
        async def fail(*a, **k):
            raise boom
        monkeypatch.setattr(commission, "distribute_sale_commissions", fail)
    elif where == "after_plan_frozen":
        async def fail(*a, **k):
            raise boom
        monkeypatch.setattr(commission, "resume_distribution", fail)
    else:
        async def fail(*a, **k):
            raise boom
        monkeypatch.setattr(order_completion, "_notify_once", fail)
    with pytest.raises(RuntimeError):
        w.run(lambda: shop_routes._process_paid_order(sid))
    mid = w.get(o["id"])
    assert mid["payment_status"] == "paid" and mid.get("completion_due") is True     # the marker survived the crash
    monkeypatch.undo()
    w.run(lambda: shop_routes._process_paid_order(sid))                               # the same payment reported again
    _completed(w, o["id"])
    w.run(lambda: shop_routes._process_paid_order(sid))                               # and again: nothing more happens
    assert len(w.ledger(o["id"], "SALE_COLLECTED")) == 1 and len(w.comms(o["id"])) == 1
    assert _notifications(w, o["id"]) == 1


def test_a_crash_is_finished_by_the_repair_sweep_when_the_payment_never_comes_back(w, monkeypatch):
    o = w.order([(w.product("va", 1000), 1)])
    sid = w.tx(o)

    async def fail(*a, **k):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(commission, "distribute_sale_commissions", fail)
    with pytest.raises(RuntimeError):
        w.run(lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    dry = w.run(lambda: order_completion.repair_incomplete_completions(dry_run=True))
    assert dry["eligible"] >= 1 and w.plan(o["id"]) is None and w.get(o["id"]).get("completion_due")   # dry run wrote nothing
    res = w.run(order_completion.repair_incomplete_completions)
    assert res["updated"] >= 1 and res["failed"] == 0 and res["complete"]
    _completed(w, o["id"])


def test_concurrent_completion_calls_have_one_effect(w):
    o = w.order([(w.product("va", 1000), 1), (w.product("vb", 500), 1)])
    sid = w.tx(o)
    ts = [threading.Thread(target=lambda: w.run(lambda: shop_routes._process_paid_order(sid))) for _ in range(3)]
    ts += [threading.Thread(target=lambda: w.run(lambda: order_completion.complete_paid_order(o["id"], source="test"))) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    w.run(lambda: order_completion.complete_paid_order(o["id"], source="test"))
    _completed(w, o["id"], vendors=("va", "vb"))
    assert len(w.comms(o["id"])) == 1 and _notifications(w, o["id"]) == 1


def test_a_second_different_payment_is_a_duplicate_not_a_second_completion(w):
    o = w.order([(w.product("va", 1000), 1)])
    _pay(w, o)
    _pay(w, o, sid=w.tx(o, sid="cs_second_" + o["id"][:8]))
    got = w.get(o["id"])
    assert any(d.get("status") == "refund_due" for d in got.get("duplicate_payments") or [])
    assert len(w.ledger(o["id"], "SALE_COLLECTED")) == 1 and len(w.comms(o["id"])) == 1


# ================================================================ orders that must not earn
def test_unpaid_order_is_never_completed(w):
    o = w.order([(w.product("va", 1000), 1)])
    res = w.run(lambda: order_completion.complete_paid_order(o["id"], source="test"))
    assert res["outcome"] == "skipped" and w.plan(o["id"]) is None and w.ledger(o["id"]) == []


def test_payment_for_an_admin_cancelled_order_owes_a_refund_and_clears_the_marker(w):
    o = w.order([(w.product("va", 1000), 1)])
    w.run(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"status": "cancelled", "cancel_reason": "admin_cancelled"}}))
    _pay(w, o)
    got = w.get(o["id"])
    assert got.get("needs_refund") and "completion_due" not in got and got["completion"]["outcome"] == "skipped"
    assert w.plan(o["id"]) is None and w.ledger(o["id"]) == []


def test_refund_booked_before_the_plan_existed_is_blocked_not_guessed(w, monkeypatch):
    o = w.order([(w.product("va", 1000), 2)])
    sid = w.tx(o)

    async def fail(*a, **k):
        raise RuntimeError("simulated crash")
    monkeypatch.setattr(commission, "distribute_sale_commissions", fail)
    with pytest.raises(RuntimeError):
        w.run(lambda: shop_routes._process_paid_order(sid))
    monkeypatch.undo()
    paid = w.get(o["id"])
    case, _ = w.run(lambda: returns_routes.open_refund_case(paid, "goodwill", 50000, "partial", "pb:" + o["id"]))
    assert w.act("adm", case["id"], "initiate").status_code == 200
    assert w.confirm("fin2", case["id"], "UTR-PC-PB-" + o["id"][:6]).status_code == 200
    res = w.run(lambda: order_completion.complete_paid_order(o["id"], source="test"))
    assert res["outcome"] == "blocked" and w.plan(o["id"]) is None
    assert w.get(o["id"])["completion_blocked"] == "refunded_before_commission_plan"
    assert w.run(order_completion.completion_audit)["completion_blocked"] >= 1


# ================================================================ the sweep: pagination, checkpoints, isolation
def test_sweep_processes_more_than_one_batch_resumes_from_its_checkpoint_and_isolates_failures(w, monkeypatch):
    pid = w.product("va", 100, stock=1000)
    ids = []
    for _ in range(25):
        o = w.order([(pid, 1)], seller=False)
        sid = w.tx(o)
        w.run(lambda: db.orders.update_one({"id": o["id"]}, {"$set": {"payment_status": "paid", "paid_at": now_iso(),
                                                                       "paid_session_id": sid, "completion_due": True}}))
        ids.append(o["id"])
    bad = sorted(ids)[7]
    real = order_completion.complete_paid_order

    async def flaky(oid, *a, **k):
        if oid == bad:
            raise RuntimeError("this one record is broken")
        return await real(oid, *a, **k)
    monkeypatch.setattr(order_completion, "complete_paid_order", flaky)
    first = w.run(lambda: order_completion.repair_incomplete_completions(batch=10, max_seconds=0))
    assert not first["complete"] and first["scanned"] == 10 and first["next_key"]
    ck = w.run(lambda: db.job_checkpoints.find_one({"_id": "completion_repair"}))
    assert ck and ck["last_key"] == first["next_key"]
    rest = w.run(lambda: order_completion.repair_incomplete_completions(batch=10))
    assert rest["complete"] and rest["resumed_from"] == first["next_key"]
    assert first["failed"] + rest["failed"] == 1 and rest["failures"] or first["failures"]
    assert w.run(lambda: db.job_checkpoints.find_one({"_id": "completion_repair"})) is None
    monkeypatch.undo()
    assert sum(1 for i in ids if "completion_due" in w.get(i)) == 1                     # only the broken one is left
    again = w.run(order_completion.repair_incomplete_completions)                       # once fixed, the next run finishes it
    assert again["updated"] == 1 and all("completion_due" not in w.get(i) for i in ids)
