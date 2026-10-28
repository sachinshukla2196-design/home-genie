"""COD rules that need no database: executed directly (pure functions and request models in cod_rules)."""
import pytest
from fastapi import HTTPException

from cod_rules import (CodCollectIn, CodResolveIn, check_resolution_amount, collection_is_proven, hold_reason, parse_collection_evidence,
                       parse_resolution, refuse_own_sale, require_confirmer_role)

GOOD = {"amount_collected": 1180.0, "evidence_type": "courier_confirmation", "evidence_reference": "AWB-1234"}
RES = {"resolution": "confirm_full", "reason": "Checked remittance", "collected_amount": 1180.0,
       "evidence_type": "courier_confirmation", "evidence_reference": "AWB-9"}


def _status(fn, *a):
    with pytest.raises(HTTPException) as e:
        fn(*a)
    return e.value.status_code


@pytest.mark.parametrize("role,ok", [("admin", True), ("super_admin", True), ("accounts_admin", False), ("support_admin", False),
                                     ("distributor", False), ("vendor", False), (None, False)])
def test_only_admin_and_super_admin_may_confirm(role, ok):
    if ok:
        require_confirmer_role({"role": role})
    else:
        assert _status(require_confirmer_role, {"role": role}) == 403


def test_own_sale_is_refused_even_for_an_admin_but_other_sales_are_not():
    assert _status(refuse_own_sale, {"id": "u1", "role": "admin"}, {"seller_user_id": "u1"}) == 403
    refuse_own_sale({"id": "u2", "role": "admin"}, {"seller_user_id": "u1"})
    refuse_own_sale({"id": "u2", "role": "admin"}, {})


@pytest.mark.parametrize("bad", [
    None, "text", [],
    {k: v for k, v in GOOD.items() if k != "amount_collected"},
    {**GOOD, "amount_collected": 0}, {**GOOD, "amount_collected": -1}, {**GOOD, "amount_collected": "abc"},
    {**GOOD, "amount_collected": float("nan")}, {**GOOD, "amount_collected": float("inf")},
    {**GOOD, "amount_collected": 10_000_001}, {**GOOD, "amount_collected": 10.123},
    {**GOOD, "evidence_type": "word_of_mouth"}, {**GOOD, "evidence_type": None},
    {**GOOD, "evidence_reference": ""}, {**GOOD, "evidence_reference": "   "}, {**GOOD, "evidence_reference": "ab"},
    {**GOOD, "evidence_reference": "A" * 121}, {**GOOD, "evidence_reference": "AWB\n123"}, {**GOOD, "evidence_reference": "<script>x</script>"},
    {**GOOD, "note": "n" * 301}, {**GOOD, "note": "bad\x00note"},
])
def test_invalid_collection_evidence_is_refused(bad):
    assert _status(parse_collection_evidence, bad) == 422


def test_valid_evidence_is_trimmed_and_never_defaulted():
    e = parse_collection_evidence({**GOOD, "evidence_reference": "  AWB-1234  ", "note": " ok "})
    assert e.evidence_reference == "AWB-1234" and e.note == "ok" and e.amount_collected == 1180.0
    assert isinstance(parse_collection_evidence(CodCollectIn(**GOOD)), CodCollectIn)
    assert "amount_collected" in CodCollectIn.model_fields and CodCollectIn.model_fields["amount_collected"].is_required()


@pytest.mark.parametrize("etype,collected,expected,want", [
    ("courier_confirmation", 118000, 118000, None), ("provider_confirmation", 118000, 118000, None),
    ("courier_confirmation", 100000, 118000, "amount_mismatch"), ("courier_confirmation", 118001, 118000, "amount_mismatch"),
    ("manual_exception", 118000, 118000, "manual_exception"), ("manual_exception", 5, 118000, "manual_exception")])
def test_hold_reason(etype, collected, expected, want):
    assert hold_reason(etype, collected, expected) == want


@pytest.mark.parametrize("bad", [
    None, {}, {"resolution": "confirm_full", "note": "Verified against courier record"},          # a note alone
    {**RES, "evidence_type": "manual_exception"}, {**RES, "evidence_reference": " "}, {**RES, "reason": "ok"}, {**RES, "reason": ""},
    {**RES, "collected_amount": 0}, {**RES, "collected_amount": float("nan")}, {**RES, "resolution": "maybe"},
    {k: v for k, v in RES.items() if k != "collected_amount"}, {k: v for k, v in RES.items() if k != "evidence_reference"}])
def test_incomplete_resolution_evidence_is_refused(bad):
    assert _status(parse_resolution, bad) == 422


def test_complete_resolution_is_accepted():
    r = parse_resolution({**RES, "evidence_reference": " AWB-9 ", "reason": " Checked remittance "})
    assert isinstance(r, CodResolveIn) and r.evidence_reference == "AWB-9" and r.reason == "Checked remittance"


def test_resolution_amount_must_agree_with_the_resolution():
    check_resolution_amount("confirm_full", 118000, 118000)
    check_resolution_amount("accept_short", 100000, 118000)
    assert _status(check_resolution_amount, "confirm_full", 100000, 118000) == 422
    assert _status(check_resolution_amount, "accept_short", 118000, 118000) == 422
    assert _status(check_resolution_amount, "accept_short", 0, 118000) == 422


def _paid(**c):
    return {"payment_status": "paid", "cod_collection": {"type": "courier_confirmation", "expected_paise": 100, "collected_paise": 100, **c}}


def test_collection_is_proven_only_for_a_fully_evidenced_paid_order():
    assert collection_is_proven(_paid()) and collection_is_proven(_paid(type="provider_confirmation"))
    assert not collection_is_proven(_paid(type="manual_exception"))
    assert not collection_is_proven(_paid(collected_paise=90))
    assert not collection_is_proven(_paid(collected_paise="100"))
    assert not collection_is_proven({**_paid(), "payment_status": "cod_discrepancy"})
    assert not collection_is_proven({"payment_status": "paid"})
    assert not collection_is_proven({})


# ---------------------------------------------------------------- refund ceiling and provider-reference formats
from cod_rules import refundable_total_paise  # noqa: E402


@pytest.mark.parametrize("order,want", [
    ({"payment_method": "cod", "cod_collected_paise": 100000}, 100000),          # accepted short: only the collected cash is refundable
    ({"payment_method": "cod", "cod_collected_paise": 118000}, 118000),          # fully collected
    ({"payment_method": "cod", "cod_collected_paise": 200000}, 118000),          # over-collection never raises the ceiling
    ({"payment_method": "cod"}, 118000),                                         # no collected record: unchanged
    ({"payment_method": "cod", "cod_collected_paise": 0}, 118000),
    ({"payment_method": "cod", "cod_collected_paise": True}, 118000),            # a bool is not an amount
    ({"payment_method": "online", "cod_collected_paise": 5}, 118000),            # online orders never use this field
])
def test_refund_ceiling(order, want):
    assert refundable_total_paise(order, 118000) == want


@pytest.mark.parametrize("ref", ["AWB-1234567", "pay_Abc123XYZ789", "rfnd_Q1w2E3r4T5", "UTR-TRIM-1", "412345678901", "AWB/2024/001",
                                 "REF#778", "TXN:2024-10-28", "DTDC D12345678", "1Z999AA10123456784", "a.b_c-d"])
def test_supported_reference_formats_are_accepted(ref):
    assert parse_collection_evidence({**GOOD, "evidence_reference": ref}).evidence_reference == ref


@pytest.mark.parametrize("ref", ["-AWB123", "AWB+123", "AWB@123", "AWB(123)", "AWB123’", "भारत123"])
def test_documented_limitation_references_outside_the_allowlist_are_refused(ref):
    """KNOWN LIMITATION: no provider integration or sample exists in the repository to justify widening the allowlist."""
    assert _status(parse_collection_evidence, {**GOOD, "evidence_reference": ref}) == 422
