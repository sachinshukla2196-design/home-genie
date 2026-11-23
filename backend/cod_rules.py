"""COD collection rules: pure functions and request models. No database, no I/O, no side effects.

Everything here can be tested by executing it directly, without MongoDB. The routes (`shop_routes.cod_collected`,
`finance_routes.resolve_cod_discrepancy`) and the commission guard (`commission.distribute_sale_commissions`) call
these functions, so the rules are written once.

Approved rules enforced here:
  * Only `admin` and `super_admin` may confirm collection. `accounts_admin` resolves discrepancies and never confirms.
  * The HomeGenie attributed to a sale never confirms it, even when that account is also an admin.
  * The collected amount is mandatory and is never defaulted to the order total.
  * Evidence is recorded, never "verified": no courier or provider integration exists, so `verified_by_system` is always False.
  * A manual exception, or any amount that differs from the order total, is held. It is never paid directly.
  * Resolving a held order needs a reason, the actual collected amount and collection evidence (type and reference) from a
    reviewer who is not the reporter. A note alone is not evidence, and a manual exception is not collection evidence.
"""
import os
import re
from decimal import Decimal, InvalidOperation
from typing import Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from money import paise_of

CONFIRM_ROLES = ("admin", "super_admin")                 # may confirm COD collection (accounts_admin may not)
VERIFIABLE_TYPES = ("courier_confirmation", "provider_confirmation")   # evidence types that can prove collection at review
# Technical sanity bound against typing errors, NOT a business limit: the product has no order-value cap to align with.
# Override with COD_MAX_AMOUNT_RUPEES if a real order can exceed it. Anything above the order total is held anyway.
MAX_AMOUNT_RUPEES = int(os.environ.get("COD_MAX_AMOUNT_RUPEES", "10000000"))
REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._/#:\-]{2,119}$")   # 3-120 chars, printable, no control characters


def _amount_is_valid(v: float) -> float:
    try:
        exponent = Decimal(str(v)).as_tuple().exponent
    except InvalidOperation:
        raise ValueError("amount is not a valid number")
    if isinstance(exponent, int) and exponent < -2:
        raise ValueError("amount can have at most 2 decimal places")
    return v


def _clean_reference(v: str) -> str:
    v = v.strip()                                        # trim first; the format rule applies to the trimmed value
    if not REFERENCE_RE.match(v):
        raise ValueError("evidence_reference must be 3-120 characters: letters, digits, space and . _ / # : -")
    return v


def _clean_text(v: str) -> str:
    v = v.strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in v):
        raise ValueError("text must not contain control characters")
    return v


def _clean_reason(v: str) -> str:
    v = _clean_text(v)
    if len(v) < 5:
        raise ValueError("reason must be at least 5 characters")
    return v


class CodCollectIn(BaseModel):
    """A collection confirmation. Every field except `note` is required; nothing is defaulted."""
    amount_collected: float = Field(gt=0, le=MAX_AMOUNT_RUPEES, allow_inf_nan=False)
    evidence_type: Literal["courier_confirmation", "provider_confirmation", "manual_exception"]
    evidence_reference: str
    note: str = Field(default="", max_length=300)

    @field_validator("amount_collected")
    @classmethod
    def _amount(cls, v: float) -> float:
        return _amount_is_valid(v)

    @field_validator("evidence_reference")
    @classmethod
    def _reference(cls, v: str) -> str:
        return _clean_reference(v)

    @field_validator("note")
    @classmethod
    def _note(cls, v: str) -> str:
        return _clean_text(v)


class CodResolveIn(BaseModel):
    """Independent review of a held COD order. All fields are required: a note alone is not evidence."""
    resolution: Literal["confirm_full", "accept_short"]
    reason: str = Field(max_length=300)
    collected_amount: float = Field(gt=0, le=MAX_AMOUNT_RUPEES, allow_inf_nan=False)    # what the reviewer found was actually collected
    evidence_type: Literal["courier_confirmation", "provider_confirmation"]            # manual_exception cannot prove collection
    evidence_reference: str

    @field_validator("collected_amount")
    @classmethod
    def _amount(cls, v: float) -> float:
        return _amount_is_valid(v)

    @field_validator("evidence_reference")
    @classmethod
    def _reference(cls, v: str) -> str:
        return _clean_reference(v)

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        return _clean_reason(v)


# --------------------------------------------------------------------------- authority (checked before any body or write)
def require_confirmer_role(user: dict) -> None:
    """Role gate. Runs before the order is loaded or the body is read."""
    if user.get("role") not in CONFIRM_ROLES:
        raise HTTPException(status_code=403, detail="Only an admin can confirm COD collection.")


def refuse_own_sale(user: dict, order: dict) -> None:
    """The HomeGenie attributed to a sale never confirms or reviews its collection, even if also an admin."""
    if order.get("seller_user_id") and order.get("seller_user_id") == user.get("id"):
        raise HTTPException(status_code=403, detail="A HomeGenie cannot confirm cash collection for their own sale.")


# --------------------------------------------------------------------------- parsing and classification
def parse_collection_evidence(raw) -> CodCollectIn:
    """Validate the request body AFTER authority has passed. Accepts a model instance or the raw JSON value."""
    if raw is None:
        raise HTTPException(status_code=422, detail="Collection evidence is required: amount_collected, evidence_type and evidence_reference.")
    if isinstance(raw, CodCollectIn):
        return raw
    if not isinstance(raw, dict):
        raise HTTPException(status_code=422, detail="Collection evidence must be a JSON object.")
    try:
        return CodCollectIn(**raw)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_messages(e))


def parse_resolution(raw) -> CodResolveIn:
    if isinstance(raw, CodResolveIn):
        return raw
    try:
        return CodResolveIn(**(raw if isinstance(raw, dict) else {}))
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_messages(e))


def _messages(e: ValidationError) -> list:
    return [{"loc": [str(x) for x in err["loc"]], "msg": err["msg"]} for err in e.errors()]


def hold_reason(evidence_type: str, collected_p: int, expected_p: int) -> Optional[str]:
    """None only when a courier or provider reference accompanies a collected amount equal to the order total.
    Otherwise the order is held, with the reason that is recorded on the discrepancy."""
    if evidence_type == "manual_exception":
        return "manual_exception"
    if collected_p != expected_p:
        return "amount_mismatch"
    return None


def check_resolution_amount(resolution: str, collected_p: int, expected_p: int) -> None:
    """The reviewer's amount must agree with the chosen resolution; an inconsistent review is refused, not adjusted."""
    if resolution == "confirm_full" and collected_p != expected_p:
        raise HTTPException(status_code=422, detail="confirm_full requires the collected amount to equal the order total.")
    if resolution == "accept_short" and not (0 < collected_p < expected_p):
        raise HTTPException(status_code=422, detail="accept_short requires a collected amount above zero and below the order total.")


# --------------------------------------------------------------------------- the commission guard
def collection_is_proven(order: dict) -> bool:
    """True only for a COD order whose full amount was recorded with courier or provider evidence, either by an admin at
    confirmation or by an independent reviewer at resolution. A manual exception, an unresolved hold, a short
    collection or a missing record is never proven. (Evidence is recorded, not verified by any integration.)"""
    c = order.get("cod_collection") or {}
    # Batch 12 (audit C-10): a later partial refund does not undo the proof that the cash was collected; without this the
    # remaining commission of a partly refunded COD order could never be released while the vendor side was payable.
    return (order.get("payment_status") in ("paid", "partially_refunded")
            and c.get("type") in VERIFIABLE_TYPES
            and isinstance(c.get("collected_paise"), int)
            and c.get("collected_paise") == c.get("expected_paise"))


# --------------------------------------------------------------------------- refund ceiling
def refundable_total_paise(order: dict, total_p: int) -> int:
    """The most that can ever be refunded on an order. Normally the order total. For a COD order accepted short, the customer
    paid only the collected amount, so no more than that can be returned; the order total would refund cash never received.
    Online and fully collected orders are unchanged. (This is a ceiling taken from the payment record, not a new policy.)"""
    c = order.get("cod_collected_paise")
    if order.get("payment_method") == "cod" and isinstance(c, int) and not isinstance(c, bool) and 0 < c < total_p:
        return c
    return total_p


def refund_basis_paise(order: dict, total_p: int) -> int:
    """The value a refund is pro-rated against when it is split between vendors and HomeGenie commissions (Batch 12, audit
    C-11). It is the GOODS value the customer paid: the refundable total without the COD handling fee, which is neither the
    vendor's sale nor part of the commission base. Refunding all goods therefore takes back all of each share, whether or not
    the fee was refunded. A COD order accepted short keeps the collected amount as its basis (unchanged)."""
    base = refundable_total_paise(order, total_p)
    fee = order.get("cod_fee_paise")
    if isinstance(fee, int) and not isinstance(fee, bool) and 0 < fee < base:
        return base - fee
    return base


def unsupplied_goods_paise(order: dict) -> tuple:
    """Goods on the order that a vendor did not supply (its group ended rejected / cancelled / returned to origin), as
    (value the customer would pay for them, their commission base). Batch 12, audit C-8: on a COD order these goods are never
    paid for, so they are neither part of the cash to collect nor of the HomeGenie commission base."""
    from eligibility import NOT_SUPPLIED
    from money import mul_ratio
    gone = {f.get("vendor_id") for f in order.get("fulfilments") or [] if f.get("status") in NOT_SUPPLIED}
    if not gone:
        return 0, 0
    lines = [li for li in order.get("items", []) if li.get("vendor_id") in gone]
    line_p = sum(paise_of(li, "total_paise", "total") for li in lines)
    if order.get("prices_include_gst"):
        base_p = sum(li["taxable_paise"] if isinstance(li.get("taxable_paise"), int) else paise_of(li, "total_paise", "total") for li in lines)
        return line_p, base_p
    # older GST-exclusive orders: the line value is the base; the customer's price adds the order's GST proportionally
    subtotal_p = paise_of(order, "subtotal_paise", "subtotal")
    total_p = paise_of(order, "total_paise", "total")
    fee = order.get("cod_fee_paise") if isinstance(order.get("cod_fee_paise"), int) else 0
    return (mul_ratio(total_p - fee, line_p, subtotal_p) if subtotal_p else line_p), line_p


def expected_cod_paise(order: dict) -> int:
    """Cash to collect on a COD order: the total less the goods no vendor supplied (audit C-8)."""
    return paise_of(order, "total_paise", "total") - unsupplied_goods_paise(order)[0]
