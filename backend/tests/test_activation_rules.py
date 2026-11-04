"""Activation rules that need no database (pure functions in activation_rules)."""
import pytest

from activation_rules import ACTIVATION_MIN_PAISE, disqualification, evidence_summary, is_qualifying

COD_OK = {"type": "courier_confirmation", "reference": "AWB-1", "expected_paise": 262500, "collected_paise": 262500, "recorded_by": "a"}


def _order(**kw):
    base = {"subtotal_paise": 250000, "total_paise": 262500, "payment_method": "online", "payment_status": "paid", "status": "processing"}
    base.update(kw)
    return base


def test_threshold_is_pre_gst_two_thousand_five_hundred_rupees():
    assert ACTIVATION_MIN_PAISE == 250000
    assert is_qualifying(_order(subtotal_paise=250000))
    assert disqualification(_order(subtotal_paise=249999)) == "subtotal_below_minimum"


def test_gst_and_cod_fee_never_count_toward_the_threshold():
    # subtotal 2,000 + GST 5% + COD fee: the total passes 2,500 but the qualifying amount does not
    assert disqualification(_order(subtotal_paise=200000, total_paise=300000)) == "subtotal_below_minimum"
    assert disqualification(_order(subtotal_paise=240000, total_paise=999999, payment_method="cod", payment_status="paid",
                                   cod_collection={**COD_OK, "expected_paise": 999999, "collected_paise": 999999})) == "subtotal_below_minimum"


@pytest.mark.parametrize("kw,reason", [
    ({"payment_status": "pending"}, "payment_not_confirmed"),
    ({"payment_status": "payment_pending"}, "payment_not_confirmed"),
    ({"payment_status": "cod_pending", "payment_method": "cod"}, "payment_not_confirmed"),
    ({"payment_status": "cod_discrepancy", "payment_method": "cod"}, "payment_not_confirmed"),
    ({"status": "cancelled"}, "order_cancelled_or_unfulfillable"),
    ({"needs_refund": True}, "order_cancelled_or_unfulfillable"),
    ({"payment_status": "refunded"}, "order_refunded"),
    ({"payment_status": "partially_refunded"}, "order_refunded"),
    ({"refunded_paise": 1}, "order_refunded"),
])
def test_orders_that_are_not_financially_valid_do_not_qualify(kw, reason):
    assert disqualification(_order(**kw)) == reason


@pytest.mark.parametrize("collection", [
    None,                                                                   # legacy paid COD without evidence
    {**COD_OK, "type": "manual_exception"},                                 # asserted, not proven
    {**COD_OK, "collected_paise": 200000},                                  # short collection
])
def test_cod_without_proven_full_collection_does_not_qualify(collection):
    o = _order(payment_method="cod", **({"cod_collection": collection} if collection else {}))
    assert disqualification(o) == "cod_collection_not_proven"


def test_cod_with_proven_full_collection_qualifies_and_evidence_is_summarised_as_recorded():
    o = _order(payment_method="cod", cod_collection=COD_OK)
    assert is_qualifying(o)
    ev = evidence_summary(o)
    assert ev["kind"] == "cod_collection" and ev["evidence_reference"] == "AWB-1" and ev["verified_by_system"] is False


def test_online_evidence_summary():
    assert evidence_summary(_order(payment_reference="pay_X", paid_at="t"))["kind"] == "online_payment"
