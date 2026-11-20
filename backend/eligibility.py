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


def delivered_at(order: dict) -> Optional[datetime]:
    """When the order was delivered. Older orders delivered before `delivered_at` existed fall back to the latest
    'delivered' fulfilment event; an order that is not delivered has no delivery time at all."""
    d = _parse(order.get("delivered_at"))
    if d:
        return d
    if order.get("status") != "delivered":
        return None
    times = [_parse(e.get("at")) for f in order.get("fulfilments") or [] for e in f.get("events") or [] if e.get("status") == "delivered"]
    times = [t for t in times if t]
    return max(times) if times else _parse(order.get("updated_at"))


async def payout_block(order: Optional[dict], now: Optional[datetime] = None, hold_days: int = 0,
                       window: Optional[int] = None) -> Optional[str]:
    """None when the order's earnings may be paid out now; otherwise a short reason code (why it is still held)."""
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
    d = delivered_at(order)
    if not d:
        return "not_delivered"
    days = max(hold_days or 0, await return_window_days() if window is None else window)
    if now < d + timedelta(days=days):
        return "return_window_open"
    if await has_open_case(order["id"]):
        return "open_return_or_refund"
    return None
