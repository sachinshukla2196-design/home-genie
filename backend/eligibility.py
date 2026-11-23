"""Owner decisions 2 and 3 (2026-11-20): when money earned on an order becomes payable.

One rule, used by BOTH separate financial systems — HomeGenie commission release (commission.release_due_points) and vendor
settlement eligibility (ledger.balances / settlement creation) — so the two can never disagree about an order:

  An order's earnings become payable only after it was DELIVERED and the applicable RETURN WINDOW has fully passed, and only
  while nothing is unresolved: no open return or refund case, no refund obligation, no payment problem (unpaid, refunded,
  COD discrepancy, duplicate capture awaiting refund) and the order is not cancelled.

The return window is configuration, not code: the customer returns policy (`returns_policy.window_days`). A commission also
keeps its own frozen hold (`release_after_days`); the longer of the two applies. The durations themselves must be confirmed
by the owner before launch (see docs/ENGINEERING_LOG_BATCHES_0-4.md).
"""
from datetime import datetime, timedelta, timezone
from typing import Optional


PAYABLE_PAYMENT = ("paid", "partially_refunded")


async def return_window_days() -> int:
    from returns_routes import get_returns_policy
    p = await get_returns_policy()
    try:
        return max(int(p.get("window_days") or 0), 0)
    except (TypeError, ValueError):
        return 0


def _parse(ts) -> Optional[datetime]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# A vendor group that ended without supplying the goods. Its part of the order is reversed / refunded through its own flow,
# so it no longer stands in the way of the rest of the order being delivered (Batch 12, audit C-7).
NOT_SUPPLIED = ("rejected", "cancelled", "returned_to_origin")


def _fulfilment_delivered_at(f: dict, order: dict) -> Optional[datetime]:
    """The fulfilment's delivered event; for older records without one, its own `delivered_at`, then the order's delivery
    time (the fulfilment status itself is the vendor's delivery record; only the timestamp is borrowed)."""
    times = [_parse(e.get("at")) for e in f.get("events") or [] if e.get("status") == "delivered"]
    times = [t for t in times if t]
    return max(times) if times else (_parse(f.get("delivered_at")) or _parse(order.get("delivered_at")) or _parse(order.get("updated_at")))


def delivered_at(order: dict, vendor_id: Optional[str] = None) -> Optional[datetime]:
    """When the order (or one vendor's part of it) was delivered - or None.

    Batch 12 (audit C-5): the evidence of delivery is the VENDOR FULFILMENT, recorded by the vendor's dispatch flow. An order
    status typed by an admin, a COD cash confirmation or a vendor step on a cancelled order no longer starts any payout clock.
    - With `vendor_id`: that vendor's fulfilment must be delivered (vendor settlement is per vendor).
    - Without: every vendor group must be finished - delivered, or ended without supplying (rejected / cancelled / returned
      to origin) - and at least one delivered; the time is the latest delivery (HomeGenie commission is per order).
    - An order with no vendor fulfilments (goods sold by the platform itself) keeps the order-level record: status delivered
      and `delivered_at`, falling back to `updated_at` for orders delivered before that field existed."""
    groups = order.get("fulfilments") or []
    if groups:
        if vendor_id is not None:
            groups = [f for f in groups if f.get("vendor_id") == vendor_id]
            if not groups:
                return None
        if any(f.get("status") not in ("delivered", *NOT_SUPPLIED) for f in groups):
            return None
        times = [_fulfilment_delivered_at(f, order) for f in groups if f.get("status") == "delivered"]
        times = [t for t in times if t]
        return max(times) if times else None
    if order.get("status") != "delivered":
        return None
    return _parse(order.get("delivered_at")) or _parse(order.get("updated_at"))


async def payout_block(order: Optional[dict], now: Optional[datetime] = None, hold_days: int = 0,
                       window: Optional[int] = None, vendor_id: Optional[str] = None) -> Optional[str]:
    """None when the order's earnings may be paid out now; otherwise a short reason code (why it is still held).
    `vendor_id` limits the delivery test to that vendor's part of the order (vendor settlement)."""
    from financial_ops import has_open_case
    if not order:
        return "order_missing"
    now = now or datetime.now(timezone.utc)
    if order.get("status") == "cancelled":
        return "cancelled"
    if order.get("payment_status") not in PAYABLE_PAYMENT:
        return f"payment_{order.get('payment_status')}"
    if order.get("needs_refund") or order.get("refund_due_cancel"):
        return "refund_due"
    if any(d.get("status") == "refund_due" for d in order.get("duplicate_payments") or []):
        return "duplicate_payment_refund_due"
    d = delivered_at(order, vendor_id)
    if not d:
        return "not_delivered"
    days = max(hold_days or 0, await return_window_days() if window is None else window)
    if now < d + timedelta(days=days):
        return "return_window_open"
    if await has_open_case(order["id"]):
        return "open_return_or_refund"
    return None
