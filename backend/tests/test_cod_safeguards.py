"""Phase 3A: COD collection safeguards.

- The HomeGenie attributed to a COD sale can never confirm its collection (backend refusal, even if also an admin).
- Only an admin confirms collection; authority is checked before the evidence.
- Evidence (amount, evidence type, reference) is required and validated; nothing is defaulted.
- A manual exception or an amount mismatch is HELD for finance review, never marked paid directly.
- A discrepancy must be closed by a different finance admin from the one who reported it.
- Repeated confirmation does not duplicate commission or ledger entries.

Orders are inserted directly as fixtures (the cart flow is not under test here). Every money effect is produced by the
real confirmation and resolution routes.

In-process, THROWAWAY database (dropped at the end); needs MONGO_URL in the environment.
Run this file in its own pytest process: `pytest tests/test_cod_safeguards.py -n 0`.
"""
import os

import pytest

os.environ.update({"VERCEL": "1", "DB_NAME": "homegenies_cod_safeguards_test", "JWT_SECRET": "cod-safeguards-test-" + "k" * 40,
                   "CORS_ORIGINS": "https://home-genie-9zfc.vercel.app", "CRON_SECRET": "cron-test-secret"})
os.environ.pop("WEBHOOK_CRON_SECRET", None)
os.environ.pop("ADMIN_EMAIL", None)

from fastapi.testclient import TestClient  # noqa: E402
import server  # noqa: E402
from core import db, hash_password, create_token, now_iso, new_id  # noqa: E402

PW = "Cod-Safe-Pass-1234"
S = {}
TOTAL_P = 118000          # Rs 1,180.00 (subtotal 1,000.00 + GST 5% + COD fee 130.00)
SUBTOTAL_P = 100000


def _hdr(uid):
    return {"Authorization": f"Bearer {create_token(uid)}"}


def _person(key, role="distributor", status="green", sponsor=None):
    uid = new_id()
    S[key] = uid
    return {"id": uid, "distributor_id": "C" + uid[:7].upper(), "full_name": key, "mobile": "9" + f"{abs(hash(uid)) % 10**9:09d}",
            "email": f"{key}-{uid[:6]}@example.com", "password_hash": hash_password(PW), "role": role, "status": status,
            "account_status": "active", "sponsor_user_id": sponsor, "created_at": now_iso(), "updated_at": now_iso()}


@pytest.fixture(scope="module")
def c():
    with TestClient(server.app) as client:
        async def seed():
            await server.client.drop_database(os.environ["DB_NAME"])
            await server._init_db()
            from db_indexes import apply
            await apply()
            team = _person("team")                                   # the upline: three commission levels need it
            referrer = _person("referrer", sponsor=team["id"])
            seller = _person("seller", sponsor=referrer["id"])
            people = [team, referrer, seller, _person("buyer"), _person("admin", role="admin"), _person("super", role="super_admin"),
                      _person("finance", role="accounts_admin"), _person("finance2", role="accounts_admin"),
                      _person("distributor"), _person("vendor", role="vendor")]
            await db.users.insert_many([dict(u) for u in people])
        client.portal.call(seed)
        yield client
        client.portal.call(lambda: server.client.drop_database(os.environ["DB_NAME"]))


def _run(c, fn):
    return c.portal.call(fn)


def _cod_order(c, key, seller="seller"):
    oid = new_id()
    order = {"id": oid, "order_number": "CS-" + oid[:6].upper(), "user_id": S["buyer"], "seller_user_id": S[seller],
             "payment_method": "cod", "payment_status": "cod_pending", "status": "placed",
             "subtotal": SUBTOTAL_P / 100, "subtotal_paise": SUBTOTAL_P, "total": TOTAL_P / 100, "total_paise": TOTAL_P,
             "fulfilments": [], "items": [], "refunded_paise": 0, "refunded_amount": 0.0, "created_at": now_iso()}
    _run(c, lambda: db.orders.insert_one(dict(order)))
    S["order_" + key] = oid
    return oid


def _state(c, oid):
    return _run(c, lambda: db.orders.find_one({"id": oid}, {"_id": 0}))


def _commissions(c, oid):
    return _run(c, lambda: db.commissions.count_documents({"order_id": oid}))


def _ledger(c, oid):
    return _run(c, lambda: db.wallet_transactions.count_documents({"reference": oid}))


def _body(amount=TOTAL_P / 100, etype="courier_confirmation", ref="AWB-TEST-7001"):
    return {"amount_collected": amount, "evidence_type": etype, "evidence_reference": ref}


def _confirm(c, oid, who, body=None):
    return c.post(f"/api/orders/{oid}/cod-collected", headers=_hdr(S[who]), json=body)


# ================================================================ who may confirm
def test_the_attributed_homegenie_cannot_confirm_their_own_collection_even_with_evidence(c):
    oid = _cod_order(c, "self")
    assert _confirm(c, oid, "seller", _body()).status_code == 403
    assert _state(c, oid)["payment_status"] == "cod_pending"
    assert _commissions(c, oid) == 0 and _ledger(c, oid) == 0


def test_an_attributed_homegenie_who_is_also_an_admin_cannot_confirm_their_own_sale(c):
    oid = _cod_order(c, "self-admin")
    _run(c, lambda: db.users.update_one({"id": S["seller"]}, {"$set": {"role": "admin"}}))
    try:
        assert _confirm(c, oid, "seller", _body()).status_code == 403
        assert _state(c, oid)["payment_status"] == "cod_pending"
    finally:
        _run(c, lambda: db.users.update_one({"id": S["seller"]}, {"$set": {"role": "distributor"}}))


@pytest.mark.parametrize("who", ["distributor", "vendor", "finance"])   # accounts_admin resolves discrepancies but never confirms
def test_unauthorised_actors_cannot_confirm_collection_whatever_the_body(c, who):
    oid = _cod_order(c, "unauth-" + who)
    assert _confirm(c, oid, who, _body()).status_code == 403
    assert _confirm(c, oid, who, None).status_code == 403                 # authority is checked before evidence
    assert _state(c, oid)["payment_status"] == "cod_pending"


# ================================================================ evidence validation
def test_a_missing_evidence_body_is_rejected(c):
    oid = _cod_order(c, "no-body")
    r = _confirm(c, oid, "admin", None)
    assert r.status_code == 422
    assert _state(c, oid)["payment_status"] == "cod_pending"


@pytest.mark.parametrize("bad", [
    {"evidence_type": "courier_confirmation", "evidence_reference": "AWB-1"},                       # no amount
    {"amount_collected": 0, "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1"},  # zero amount
    {"amount_collected": 1180, "evidence_type": "word_of_mouth", "evidence_reference": "AWB-1"},    # unknown type
    {"amount_collected": 1180, "evidence_type": "courier_confirmation", "evidence_reference": "ab"},  # too short
    {"amount_collected": 1180, "evidence_type": "courier_confirmation", "evidence_reference": "   "},  # blank
    {"amount_collected": -5, "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1"},  # negative
    {"amount_collected": "abc", "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1"},  # malformed
    {"amount_collected": 99999999, "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1"},  # excessive
    {"amount_collected": 1180.123, "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1"},  # sub-paisa
    {"amount_collected": 1180, "evidence_type": "courier_confirmation", "evidence_reference": "A" * 121},  # oversized
])
def test_incomplete_or_invalid_evidence_is_rejected_safely(c, bad):
    oid = _cod_order(c, "bad-" + str(abs(hash(str(bad))) % 10000))
    assert _confirm(c, oid, "admin", bad).status_code == 422
    assert _state(c, oid)["payment_status"] == "cod_pending"
    assert _commissions(c, oid) == 0 and _ledger(c, oid) == 0


# ================================================================ valid confirmation records evidence and actor
def test_a_valid_courier_confirmation_is_recorded_with_its_evidence_and_confirming_actor(c):
    oid = _cod_order(c, "valid")
    r = _confirm(c, oid, "admin", _body(ref="AWB-TEST-8001"))
    assert r.status_code == 200, r.text
    o = _state(c, oid)
    assert o["payment_status"] == "paid" and o["status"] == "delivered"
    assert o["cod_collected_role"] == "admin" and o["cod_collected_by"] == S["admin"]
    ev = o["cod_collection"]
    assert ev["type"] == "courier_confirmation" and ev["reference"] == "AWB-TEST-8001"
    assert ev["recorded_by"] == S["admin"] and ev["verified_by_system"] is False
    assert ev["expected_paise"] == TOTAL_P and ev["collected_paise"] == TOTAL_P
    assert _commissions(c, oid) == 3                                       # attributed seller, referrer and team are green


def test_repeated_valid_confirmation_does_not_duplicate_commission_or_ledger_entries(c):
    oid = _cod_order(c, "repeat")
    assert _confirm(c, oid, "admin", _body()).status_code == 200
    comm, led = _commissions(c, oid), _ledger(c, oid)
    again = _confirm(c, oid, "admin", _body())
    assert again.status_code == 200 and again.json().get("already") is True
    assert _commissions(c, oid) == comm and _ledger(c, oid) == led


# ================================================================ discrepancies are held, never silently complete
def test_an_amount_mismatch_is_held_for_finance_review_and_not_treated_as_collected(c):
    oid = _cod_order(c, "short")
    r = _confirm(c, oid, "admin", _body(amount=1000.0))
    assert r.status_code == 200 and r.json()["discrepancy"] is True and r.json()["reason"] == "amount_mismatch"
    o = _state(c, oid)
    assert o["payment_status"] == "cod_discrepancy" and "cod_collected_at" not in o
    assert o["cod_discrepancy"]["status"] == "open" and o["cod_discrepancy"]["reason"] == "amount_mismatch"
    assert _commissions(c, oid) == 0 and _ledger(c, oid) == 0


def test_a_manual_exception_is_held_even_when_the_amount_matches(c):
    oid = _cod_order(c, "manual")
    r = _confirm(c, oid, "admin", _body(etype="manual_exception", ref="REV-TEST-9001"))
    assert r.status_code == 200 and r.json()["reason"] == "manual_exception"
    o = _state(c, oid)
    assert o["payment_status"] == "cod_discrepancy" and o["cod_discrepancy"]["evidence"]["type"] == "manual_exception"
    assert _commissions(c, oid) == 0 and _ledger(c, oid) == 0


def _resolve_body(resolution="confirm_full", amount=TOTAL_P / 100, etype="courier_confirmation", ref="AWB-REVIEW-5001", reason="Checked against courier remittance"):
    return {"resolution": resolution, "reason": reason, "collected_amount": amount, "evidence_type": etype, "evidence_reference": ref}


def _resolve(c, oid, who, body):
    return c.post(f"/api/admin/finance/cod-discrepancies/{oid}/resolve", headers=_hdr(S[who]), json=body)


def test_the_discrepancy_reporter_cannot_close_their_own_discrepancy(c):
    oid = _cod_order(c, "maker")
    _confirm(c, oid, "super", _body(amount=1000.0))                        # super_admin reports the mismatch
    assert _resolve(c, oid, "super", _resolve_body()).status_code == 403
    assert _state(c, oid)["payment_status"] == "cod_discrepancy"
    assert _commissions(c, oid) == 0


def test_a_note_alone_or_incomplete_review_evidence_cannot_resolve_a_hold(c):
    oid = _cod_order(c, "note-only")
    _confirm(c, oid, "admin", _body(etype="manual_exception", ref="REV-TEST-9003"))
    for bad in ({"resolution": "confirm_full", "note": "Verified against courier record"},
                {**_resolve_body(), "evidence_type": "manual_exception"},          # a manual exception is not collection evidence
                {**_resolve_body(), "evidence_reference": "  "},
                {**_resolve_body(), "reason": "ok"},
                {**_resolve_body(), "collected_amount": 0},
                _resolve_body(amount=500.0),                                       # confirm_full must equal the order total
                _resolve_body("accept_short", amount=TOTAL_P / 100)):              # accept_short must be below the total
        assert _resolve(c, oid, "finance2", bad).status_code == 422, bad
    o = _state(c, oid)
    assert o["payment_status"] == "cod_discrepancy" and o["cod_discrepancy"]["status"] == "open"
    assert _commissions(c, oid) == 0 and _ledger(c, oid) == 0


def test_a_manual_exception_resolved_with_full_review_evidence_credits_once_and_persists_the_reviewer(c):
    oid = _cod_order(c, "closeout")
    _confirm(c, oid, "admin", _body(etype="manual_exception", ref="REV-TEST-9002"))
    assert _commissions(c, oid) == 0                                       # asserted, not proven: nothing credited yet
    r = _resolve(c, oid, "finance2", _resolve_body(ref="AWB-REVIEW-9002"))
    assert r.status_code == 200, r.text
    o = _state(c, oid)
    assert o["payment_status"] == "paid"
    d = o["cod_discrepancy"]
    assert d["status"] == "resolved" and d["resolved_by"] == S["finance2"] and d["resolved_at"] and d["note"]
    assert d["resolution_evidence"]["type"] == "courier_confirmation" and d["resolution_evidence"]["reference"] == "AWB-REVIEW-9002"
    assert d["resolution_evidence"]["collected_paise"] == TOTAL_P and d["reported_by"] == S["admin"]
    assert o["cod_collection"]["recorded_by"] == S["finance2"] and o["cod_collection"]["verified_by_system"] is False
    assert _commissions(c, oid) == 3
    led = _ledger(c, oid)
    assert _resolve(c, oid, "finance2", _resolve_body()).status_code == 404       # already resolved; nothing repeats
    assert _commissions(c, oid) == 3 and _ledger(c, oid) == led


def test_accept_short_closes_the_order_but_never_distributes_commission(c):
    oid = _cod_order(c, "accept-short")
    _confirm(c, oid, "admin", _body(amount=1000.0))
    r = _resolve(c, oid, "finance2", _resolve_body("accept_short", amount=1000.0))
    assert r.status_code == 200, r.text
    o = _state(c, oid)
    assert o["payment_status"] == "paid" and o["commission_note"] == "short_collection_held"
    assert o["cod_short_collected"] is True and o["cod_shortfall_paise"] == TOTAL_P - 100000 and o["cod_collected_paise"] == 100000
    assert _commissions(c, oid) == 0
    led = _ledger(c, oid)
    assert _resolve(c, oid, "finance2", _resolve_body("accept_short", amount=900.0)).status_code == 404      # cannot change the recorded amount
    assert _state(c, oid)["cod_collected_paise"] == 100000 and _ledger(c, oid) == led


def test_a_legacy_paid_cod_order_without_evidence_never_gains_commission_or_resumes_a_plan(c):
    from commission import distribute_sale_commissions, resume_distribution
    oid = _cod_order(c, "legacy")
    _run(c, lambda: db.orders.update_one({"id": oid}, {"$set": {"payment_status": "paid", "status": "delivered"}}))   # no cod_collection record
    order, buyer = _state(c, oid), _run(c, lambda: db.users.find_one({"id": S["buyer"]}, {"_id": 0}))
    assert _run(c, lambda: distribute_sale_commissions(order, buyer))["reason"] == "cod_collection_not_proven"
    _run(c, lambda: db.commission_plans.insert_one({"_id": oid, "order_id": oid, "items": [], "base": 0, "completed_at": None}))
    assert _run(c, lambda: resume_distribution(oid))["reason"] == "cod_collection_not_proven"
    assert _commissions(c, oid) == 0


def test_the_attributed_homegenie_cannot_resolve_their_own_sales_hold(c):
    oid = _cod_order(c, "seller-resolve")
    _confirm(c, oid, "admin", _body(amount=1000.0))
    _run(c, lambda: db.users.update_one({"id": S["seller"]}, {"$set": {"role": "accounts_admin"}}))
    try:
        assert _resolve(c, oid, "seller", _resolve_body()).status_code == 403
    finally:
        _run(c, lambda: db.users.update_one({"id": S["seller"]}, {"$set": {"role": "distributor"}}))
    assert _state(c, oid)["payment_status"] == "cod_discrepancy" and _commissions(c, oid) == 0


def test_the_commission_path_itself_refuses_an_unproven_cod_collection(c):
    """Defence in depth: even a direct call cannot credit commission for a manual exception or an unpaid COD order."""
    from commission import distribute_sale_commissions
    oid = _cod_order(c, "guard")
    _confirm(c, oid, "admin", _body(etype="manual_exception", ref="REV-TEST-9004"))
    order, buyer = _state(c, oid), _run(c, lambda: db.users.find_one({"id": S["buyer"]}, {"_id": 0}))
    assert _run(c, lambda: distribute_sale_commissions(order, buyer))["reason"] == "cod_collection_not_proven"
    forged = {**order, "payment_status": "paid", "cod_collection": {**order["cod_discrepancy"]["evidence"], "expected_paise": TOTAL_P, "collected_paise": TOTAL_P}}
    assert _run(c, lambda: distribute_sale_commissions(forged, buyer))["reason"] == "cod_collection_not_proven"
    assert _commissions(c, oid) == 0


# ================================================================ compatibility
def test_a_non_cod_order_is_still_refused_before_any_evidence_is_considered(c):
    oid = new_id()
    _run(c, lambda: db.orders.insert_one({"id": oid, "order_number": "CS-ONLINE", "user_id": S["buyer"], "seller_user_id": S["seller"],
                                          "payment_method": "online", "payment_status": "paid", "status": "placed",
                                          "subtotal_paise": SUBTOTAL_P, "total_paise": TOTAL_P, "total": TOTAL_P / 100,
                                          "subtotal": SUBTOTAL_P / 100, "fulfilments": [], "items": [], "created_at": now_iso()}))
    assert _confirm(c, oid, "admin", _body()).status_code == 400


# ================================================================ evidence model (no database needed)
def test_blank_or_short_evidence_reference_is_refused_by_the_model_itself():
    """Trimming must happen before the length rule; a blank reference must never reach the route as evidence."""
    from pydantic import ValidationError
    from cod_rules import CodCollectIn
    for ref in ["   ", "", "ab", "  a  "]:
        with pytest.raises(ValidationError):
            CodCollectIn(amount_collected=1180, evidence_type="courier_confirmation", evidence_reference=ref)
    accepted = CodCollectIn(amount_collected=1180, evidence_type="courier_confirmation", evidence_reference="  AWB-1234  ")
    assert accepted.evidence_reference == "AWB-1234"


def test_refunds_after_accept_short_are_capped_at_the_cash_collected_and_never_duplicate(c):
    """Integration (needs MongoDB): collected 1,000.00 of 1,180.00, then repeated and concurrent refund attempts."""
    import asyncio
    import shop_routes
    oid = _cod_order(c, "short-refund")
    _confirm(c, oid, "admin", _body(amount=1000.0))
    assert _resolve(c, oid, "finance2", _resolve_body("accept_short", amount=1000.0)).status_code == 200
    admin = {"id": S["admin"], "role": "admin"}

    async def refund(amount, ref):
        return await shop_routes.reverse_order_financials(oid, admin, None, refund_amount=amount, reference=ref, reason="test")

    over = _run(c, lambda: refund(1180.0, "RF-OVER"))                       # a full-total refund is clamped, never above the collected cash
    assert over["refund_amount"] == 1000.0
    o = _state(c, oid)
    assert o["refunded_paise"] == 100000 and o["payment_status"] == "refunded"
    refunds = _run(c, lambda: db.vendor_ledger.count_documents({"order_id": oid, "type": "REFUND"}))
    assert _run(c, lambda: refund(1180.0, "RF-OVER")).get("duplicate") is True            # same reference: no second refund
    assert _run(c, lambda: refund(1.0, "RF-EXTRA")).get("refund_amount") == 0.0           # nothing refundable remains
    assert _state(c, oid)["refunded_paise"] == 100000
    assert _run(c, lambda: db.vendor_ledger.count_documents({"order_id": oid, "type": "REFUND"})) == refunds

    oid2 = _cod_order(c, "short-refund-concurrent")
    _confirm(c, oid2, "admin", _body(amount=1000.0))
    _resolve(c, oid2, "finance2", _resolve_body("accept_short", amount=1000.0))

    async def race():
        return await asyncio.gather(*[shop_routes.reverse_order_financials(oid2, admin, None, refund_amount=600.0, reference=f"RF-RACE-{i}", reason="t")
                                      for i in range(3)], return_exceptions=True)
    _run(c, race)
    assert _state(c, oid2)["refunded_paise"] <= 100000                       # concurrent refunds can never exceed the ceiling
