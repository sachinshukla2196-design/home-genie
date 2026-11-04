"""HomeGenie activation rules: pure, no database.

Owner-approved (Phase 3B.1):
  * A qualifying activation purchase has a PRE-GST merchandise subtotal of at least Rs 2,500. GST, the COD fee and other
    charges never count toward it.
  * The order must be financially valid. Online: confirmed paid through the normal lifecycle. COD: collection fully proven
    under the Phase 3A rules. A held discrepancy, unproven collection or short collection never qualifies.
  * Activation is never automatic: an admin reviews and approves RED -> GREEN.
  * Approval never creates or replays commission.
"""
from cod_rules import collection_is_proven
from money import paise_of

ACTIVATION_MIN_PAISE = 250_000          # Rs 2,500.00, pre-GST subtotal


def qualifying_subtotal_paise(order: dict) -> int:
    return paise_of(order, "subtotal_paise", "subtotal")


def disqualification(order: dict) -> str:
    """'' when the order qualifies as an activation purchase, otherwise the reason it does not."""
    if qualifying_subtotal_paise(order) < ACTIVATION_MIN_PAISE:
        return "subtotal_below_minimum"
    if order.get("status") == "cancelled" or order.get("needs_refund"):
        return "order_cancelled_or_unfulfillable"
    if paise_of(order, "refunded_paise", "refunded_amount") > 0 or order.get("payment_status") in ("refunded", "partially_refunded"):
        return "order_refunded"
    if order.get("payment_status") != "paid":
        return "payment_not_confirmed"
    if order.get("payment_method") == "cod" and not collection_is_proven(order):
        return "cod_collection_not_proven"           # held, short, manual-exception, legacy without evidence
    return ""


def is_qualifying(order: dict) -> bool:
    return disqualification(order) == ""


def evidence_summary(order: dict) -> dict:
    """What made the order valid, for the review screen and the stored activation record. Evidence is recorded, not verified."""
    if order.get("payment_method") == "cod":
        c = order.get("cod_collection") or {}
        return {"kind": "cod_collection", "evidence_type": c.get("type"), "evidence_reference": c.get("reference"),
                "collected_paise": c.get("collected_paise"), "recorded_by": c.get("recorded_by"), "verified_by_system": False}
    return {"kind": "online_payment", "payment_method": order.get("payment_method"), "payment_reference": order.get("payment_reference"),
            "paid_at": order.get("paid_at")}
