"""Programme 01 / B-002: a refund case is confirmed ONLY on a completed refund booking of exactly its amount. A rejected or
zero booking never counts as a refund: the case stays open, nothing is released, and the failure is recorded and audited.

Integration, THROWAWAY MongoDB. Run alone: `pytest tests/test_programme01_refund_integrity.py -n 0`.
"""
import os
import threading

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_p01_refund_test", "JWT_SECRET": "p01-refund-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
import db_indexes  # noqa: E402
import ledger  # noqa: E402
import returns_routes  # noqa: E402
from commission import release_due_points  # noqa: E402
from core import db, now_iso, new_id  # noqa: E402
from eligibility import payout_block  # noqa: E402
from p01_harness import World, seed_world  # noqa: E402

S = {}


@pytest.fixture(scope="module")
def w():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            await db_indexes.apply()
            await seed_world(S, "RI")
        client.portal.call(seed)
        yield World(client, S, "RISELL")
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _open(w, o, amount, key=None, vendor_id=None, kind="goodwill"):
    case, _ = w.run(lambda: returns_routes.open_refund_case(o, kind, amount, "test case", key or (kind + ":" + new_id()), vendor_id=vendor_id))
    return case


# ================================================================ the valid path
def test_valid_booking_confirms_with_the_booked_amount_and_full_audit(w):
    o = w.paid_order([(w.product("va", 1000), 2)])
    case = _open(w, o, 50000)
    assert w.act("adm", case["id"], "initiate").status_code == 200
    r = w.confirm("fin2", case["id"], "UTR-RI-OK-" + o["id"][:6])
    assert r.status_code == 200, r.text
    got = w.case(case["id"])
    ev = w.events(o["id"], "completed")
    assert got["status"] == "confirmed" and len(ev) == 1 and ev[0]["case_id"] == case["id"]
    assert got["amount_refunded_paise"] == ev[0]["amount_paise"] == 50000 and "booking_shortfall_paise" not in got
    assert w.get(o["id"])["refunded_paise"] == 50000
    for action in ("refund_case_initiate", "refund_case_confirm"):
        assert w.audits(action, case["id"]), action
    assert w.audits("order_financials_reversed", o["id"])


def test_initiated_but_not_confirmed_moves_no_money_and_holds_payouts(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    w.deliver("va", o["id"])
    w.age(o["id"])
    case = _open(w, o, 30000, vendor_id=S["va"]["id"])
    assert w.act("adm", case["id"], "initiate").status_code == 200
    fresh = w.get(o["id"])
    assert fresh["payment_status"] == "paid" and not fresh.get("refunded_paise") and w.events(o["id"]) == []
    assert w.run(lambda: payout_block(fresh)) == "open_return_or_refund"
    assert w.run(lambda: payout_block(fresh, vendor_id=S["va"]["id"])) == "open_return_or_refund"
    w.run(release_due_points)
    assert all(x["released_at"] is None and x.get("reversed_paise", 0) == 0 for x in w.comms(o["id"]))


# ================================================================ rejected bookings
def test_booking_more_than_is_still_refundable_is_rejected_and_the_case_stays_open(w):
    o = w.paid_order([(w.product("va", 1000), 2)])                     # 2,000
    x = _open(w, o, 150000)
    y = _open(w, o, 100000)
    assert w.act("adm", x["id"], "initiate").status_code == 200        # both initiated while 2,000 was refundable
    assert w.act("adm", y["id"], "initiate").status_code == 200
    assert w.confirm("fin2", y["id"], "UTR-RI-Y-" + o["id"][:6]).status_code == 200      # 1,000 refunded
    comm_before = w.comms(o["id"])
    ref = "UTR-RI-X-" + o["id"][:6]
    r = w.confirm("fin2", x["id"], ref)
    assert r.status_code == 409 and "no longer has this much" in r.json()["detail"]
    got = w.case(x["id"])
    assert got["status"] == "initiated" and "confirming_reference" not in got
    assert got["last_booking_error"]["reason"] == "exceeds_refundable"
    assert any(e["status"] == "booking_rejected" for e in got["events"])
    assert w.audits("refund_case_booking_rejected", x["id"])
    assert w.get(o["id"])["refunded_paise"] == 100000                  # nothing more was booked
    assert w.comms(o["id"]) == comm_before                             # no further clawback
    held = w.get(o["id"])
    assert w.run(lambda: payout_block(held)) is not None               # the open case still holds the order
    # finance corrects it: fail, re-initiate at the right amount, confirm with the SAME bank reference
    assert w.act("fin", x["id"], "fail", note="Amount was too high").status_code == 200
    assert w.act("adm", x["id"], "retry", amount=1000).status_code == 200
    assert w.confirm("fin2", x["id"], ref).status_code == 200
    got = w.case(x["id"])
    assert got["status"] == "confirmed" and got["amount_refunded_paise"] == 100000
    assert w.get(o["id"])["payment_status"] == "refunded" and w.wallet_ok()


def test_a_rejected_event_left_by_a_race_can_be_retried_once_with_the_same_reference(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    case = _open(w, o, 40000)
    ref = "UTR-RI-RACE-" + o["id"][:6]
    eid = f"{o['id']}:refund:{ref}"
    w.run(lambda: db.order_refunds.insert_one({"_id": eid, "id": eid, "order_id": o["id"], "amount": 400.0, "amount_paise": 40000,
                                               "closes_order": False, "reference": ref, "case_id": case["id"], "status": "rejected",
                                               "created_at": now_iso()}))
    assert w.act("adm", case["id"], "initiate").status_code == 200
    outs = []
    ts = [threading.Thread(target=lambda: outs.append(w.confirm("fin2", case["id"], ref).status_code)) for _ in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert outs.count(200) == 1
    assert len(w.events(o["id"], "completed")) == 1 and w.get(o["id"])["refunded_paise"] == 40000


def test_zero_value_case_can_never_be_confirmed(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    cid = new_id()
    w.run(lambda: db.refund_cases.insert_one({"id": cid, "number": "RFD-Z" + cid[:4], "source_key": "zero:" + cid, "order_id": o["id"],
                                              "order_number": o["order_number"], "user_id": o["user_id"], "kind": "goodwill", "amount_paise": 0,
                                              "status": "initiated", "initiated_by": S["adm"]["id"], "initiators": [S["adm"]["id"]],
                                              "events": [], "created_at": now_iso(), "updated_at": now_iso()}))
    r = w.confirm("fin2", cid, "UTR-RI-ZERO")
    assert r.status_code == 409 and "zero" in r.json()["detail"]
    assert w.case(cid)["status"] == "initiated" and w.events(o["id"]) == []
    # the legitimate way to close it is an explicit finance decision without a refund
    assert w.act("fin", cid, "resolve", note="Duplicate case, nothing owed").status_code == 200
    assert w.case(cid)["outcome"] == "no_refund"


def test_nothing_left_to_refund_is_rejected(w):
    o = w.paid_order([(w.product("va", 500), 1)])
    full = _open(w, o, o["total_paise"])
    extra = _open(w, o, 1000)
    assert w.act("adm", full["id"], "initiate").status_code == 200
    assert w.act("adm", extra["id"], "initiate").status_code == 200
    assert w.confirm("fin2", full["id"], "UTR-RI-FULL-" + o["id"][:6]).status_code == 200
    r = w.confirm("fin2", extra["id"], "UTR-RI-EXTRA-" + o["id"][:6])
    assert r.status_code == 409 and w.case(extra["id"])["status"] == "initiated"
    assert len(w.events(o["id"], "completed")) == 1


# ================================================================ duplicates, concurrency, two-person rule
def test_duplicate_and_concurrent_confirmation_books_once(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    case = _open(w, o, 60000)
    assert w.act("adm", case["id"], "initiate").status_code == 200
    ref = "UTR-RI-CC-" + o["id"][:6]
    outs = []
    ts = [threading.Thread(target=lambda: outs.append(w.confirm("fin2", case["id"], ref).status_code)) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert outs.count(200) == 1
    assert w.confirm("fin2", case["id"], ref).status_code == 400          # already confirmed
    assert len(w.events(o["id"], "completed")) == 1 and w.get(o["id"])["refunded_paise"] == 60000
    assert sum(len(c.get("reversal_records", [])) for c in w.comms(o["id"])) == 1


def test_a_reference_used_by_another_case_is_refused(w):
    o = w.paid_order([(w.product("va", 1000), 2)])
    a, b = _open(w, o, 30000), _open(w, o, 30000)
    ref = "UTR-RI-SAME-" + o["id"][:6]
    for x in (a, b):
        assert w.act("adm", x["id"], "initiate").status_code == 200
    assert w.confirm("fin2", a["id"], ref).status_code == 200
    r = w.confirm("fin2", b["id"], ref)
    assert r.status_code == 409 and w.case(b["id"])["status"] == "initiated" and "confirming_reference" not in w.case(b["id"])


def test_the_initiator_cannot_confirm_and_support_cannot_confirm(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    case = _open(w, o, 20000)
    assert w.act("fin", case["id"], "initiate").status_code == 200
    assert w.confirm("fin", case["id"], "UTR-RI-SELF").status_code == 403
    assert w.confirm("support", case["id"], "UTR-RI-SUP").status_code == 403
    assert w.events(o["id"]) == []


def test_failed_then_retried_refund_books_once(w):
    o = w.paid_order([(w.product("va", 1000), 1)])
    case = _open(w, o, 25000)
    assert w.act("adm", case["id"], "initiate").status_code == 200
    assert w.act("fin", case["id"], "fail", note="Bank transfer bounced").status_code == 200
    assert w.events(o["id"]) == []
    assert w.act("adm", case["id"], "retry").status_code == 200
    assert w.confirm("fin2", case["id"], "UTR-RI-RETRY-" + o["id"][:6]).status_code == 200
    assert len(w.events(o["id"], "completed")) == 1


# ================================================================ settlement and commission while a refund is pending
def test_vendor_settlement_and_commission_wait_for_the_vendors_pending_refund(w):
    pa, pb = w.product("va", 1000), w.product("vb", 1000)
    o = w.paid_order([(pa, 1), (pb, 1)])
    w.deliver("va", o["id"])
    w.deliver("vb", o["id"])
    w.age(o["id"])
    case = _open(w, o, 100000, vendor_id=S["vb"]["id"], kind="return")       # a return of B's goods
    assert w.act("adm", case["id"], "initiate").status_code == 200
    fresh = w.get(o["id"])
    assert w.run(lambda: payout_block(fresh, vendor_id=S["vb"]["id"])) == "open_return_or_refund"
    assert w.run(lambda: payout_block(fresh, vendor_id=S["va"]["id"])) is None       # A is not held by B's refund
    w.run(release_due_points)
    assert all(x["released_at"] is None for x in w.comms(o["id"]))
    assert w.confirm("fin2", case["id"], "UTR-RI-MV-" + o["id"][:6]).status_code == 200
    assert len(w.ledger(o["id"], "REFUND", "vb")) == 1 and w.ledger(o["id"], "REFUND", "va") == []
    cm = w.comms(o["id"])[0]
    assert abs(cm["reversed_paise"] - cm["amount_paise"] / 2) <= 0.5
    w.run(release_due_points)
    assert w.comms(o["id"])[0]["released_at"] is not None and w.wallet_ok()
    assert w.run(ledger.reconcile_ledger)["refunds"] == 0                        # nothing left to repair
