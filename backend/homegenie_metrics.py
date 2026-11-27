"""HomeGenie dashboard metrics (Batch 13, Phase 8 — fixes HG-03). Definitions: docs/HOMEGENIE_DASHBOARD_METRICS.md.

Every figure is read from the authoritative records, never recalculated from percentages:
- orders attributed to the member (`orders.seller_user_id` = the member; one order counts once however many vendors it has),
- the member's commission records (`commissions.user_id`; amounts, reversals and release state as the finance engine wrote them),
- the member's withdrawal requests.
Money is integer paise. Dates are filtered on Indian Standard Time day boundaries (inclusive `from` and `to` dates), converted to
the UTC ISO timestamps the records carry. The range applies to orders by `created_at`, commissions by `created_at` and
withdrawals by `created_at`; balances (held / released totals of the wallet) are also given all-time.
"""
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from core import db, get_current_user
from money import paise_of

router = APIRouter(prefix="/api", tags=["homegenie-metrics"])
IST = ZoneInfo("Asia/Kolkata")
PAID_EVER = ("paid", "partially_refunded", "refunded")          # money was received for the order
MAX_RANGE_DAYS = 366


def ist_range(frm: Optional[str], to: Optional[str]) -> tuple:
    """Inclusive IST dates -> [start, end) as UTC ISO strings. Default: the last 30 days including today."""
    today = datetime.now(IST).date()
    try:
        d_to = date.fromisoformat(to) if to else today
        d_from = date.fromisoformat(frm) if frm else d_to - timedelta(days=29)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must look like 2026-11-23.")
    if d_from > d_to:
        raise HTTPException(status_code=400, detail="The start date is after the end date.")
    if (d_to - d_from).days >= MAX_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Choose a range of at most {MAX_RANGE_DAYS} days.")
    start = datetime.combine(d_from, time.min, IST).astimezone(timezone.utc).isoformat()
    end = datetime.combine(d_to + timedelta(days=1), time.min, IST).astimezone(timezone.utc).isoformat()
    return d_from, d_to, start, end


def ist_day(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(IST).date().isoformat()
    except ValueError:
        return None


def goods_paise(o: dict) -> int:
    """Value of the goods on the order as the customer pays it (GST included for GST-inclusive orders), without the COD fee."""
    if isinstance(o.get("items_total_paise"), int):
        return o["items_total_paise"]
    total = paise_of(o, "total_paise", "total")
    fee = o.get("cod_fee_paise") if isinstance(o.get("cod_fee_paise"), int) else 0
    return max(total - fee, 0)


def order_state(o: dict, returned: bool) -> str:
    """One label per order for the attributed-orders list (most decisive state first)."""
    from eligibility import delivered_at
    ps = o.get("payment_status")
    if ps == "refunded":
        return "refunded"
    if o.get("status") == "cancelled":
        return "cancelled"
    if ps not in PAID_EVER:
        return "awaiting_payment"
    if returned:
        return "returned"
    if ps == "partially_refunded":
        return "partially_refunded"
    if delivered_at(o):
        return "delivered"
    return "paid"


async def _returned_orders(order_ids: list) -> set:
    from returns_routes import COUNTED_RETURN_STATES
    rows = await db.return_cases.find({"order_id": {"$in": order_ids}, "status": {"$in": COUNTED_RETURN_STATES}}, {"_id": 0, "order_id": 1}).to_list(None)
    return {r["order_id"] for r in rows}


def comm_net(c: dict) -> int:
    return max(paise_of(c, "amount_paise", "amount") - paise_of(c, "reversed_paise", "reversed_amount"), 0)


async def compute(uid: str, start: str, end: str) -> dict:
    from eligibility import delivered_at
    orders = await db.orders.find({"seller_user_id": uid, "created_at": {"$gte": start, "$lt": end}}, {"_id": 0}).to_list(None)
    ids = [o["id"] for o in orders]
    returned = await _returned_orders(ids)
    paid = [o for o in orders if o.get("payment_status") in PAID_EVER]
    m = {
        "attributed_orders": len(orders),
        "attributed_order_lines": sum(len(o.get("items") or []) for o in orders),
        "paid_orders": len(paid),
        "delivered_orders": sum(1 for o in paid if o.get("status") != "cancelled" and delivered_at(o)),
        "cancelled_orders": sum(1 for o in orders if o.get("status") == "cancelled"),
        "returned_orders": len(returned & {o["id"] for o in paid}),
        "refunded_orders": sum(1 for o in orders if o.get("payment_status") == "refunded"),
        "partially_refunded_orders": sum(1 for o in orders if o.get("payment_status") == "partially_refunded"),
        "gross_sales_paise": sum(goods_paise(o) for o in paid),
        "refunded_sales_paise": sum(min(paise_of(o, "refunded_paise", "refunded_amount"), goods_paise(o)) for o in paid),
    }
    m["net_sales_paise"] = m["gross_sales_paise"] - m["refunded_sales_paise"]
    comms = await db.commissions.find({"user_id": uid, "created_at": {"$gte": start, "$lt": end}}, {"_id": 0}).to_list(None)
    direct = [c for c in comms if c.get("type") == "COMMISSION_DIRECT"]
    m.update({
        "commission_basis_paise": sum(paise_of(c, "base_paise", "base_amount") for c in direct),
        "commission_earned_paise": sum(paise_of(c, "amount_paise", "amount") for c in comms),
        "commission_reversed_paise": sum(paise_of(c, "reversed_paise", "reversed_amount") for c in comms),
        "commission_held_paise": sum(comm_net(c) for c in comms if not c.get("released_at") and c.get("status") != "REVERSED"),
        "commission_released_paise": sum(comm_net(c) for c in comms if c.get("released_at")),
        "commission_by_type": {t: sum(comm_net(c) for c in comms if c.get("type") == t)
                               for t in ("COMMISSION_DIRECT", "COMMISSION_REFERRAL", "COMMISSION_TEAM")},
    })
    # P03 (B-022): a request closed as not_reserved never held money, so it is not a withdrawal request in these figures
    wds = await db.withdrawal_requests.find({"user_id": uid, "created_at": {"$gte": start, "$lt": end}, "status": {"$ne": "not_reserved"}},
                                            {"_id": 0}).to_list(None)
    m.update({
        "withdrawal_requests": len(wds),
        "withdrawal_requested_paise": sum(paise_of(w, "amount_paise", "amount") for w in wds),
        "withdrawals_paid": sum(1 for w in wds if w.get("status") == "paid"),
        "withdrawals_paid_paise": sum(paise_of(w, "amount_paise", "amount") for w in wds if w.get("status") == "paid"),
        "withdrawals_pending_paise": sum(paise_of(w, "amount_paise", "amount") for w in wds if w.get("status") in ("pending", "under_review", "approved")),
    })
    return {"metrics": m, "orders": orders, "commissions": comms, "returned": returned}


@router.get("/homegenie/metrics")
async def homegenie_metrics(frm: Optional[str] = None, to: Optional[str] = None, user: dict = Depends(get_current_user)):
    """The member's own dashboard figures for an IST date range, with a daily trend and held-commission reasons."""
    from eligibility import payout_block
    if user.get("role") != "distributor":
        raise HTTPException(status_code=403, detail="Available to HomeGenie members only.")
    d_from, d_to, start, end = ist_range(frm, to)
    r = await compute(user["id"], start, end)
    days = [(d_from + timedelta(days=i)).isoformat() for i in range((d_to - d_from).days + 1)]
    trend = {d: {"date": d, "sales_paise": 0, "orders": 0, "commission_paise": 0} for d in days}
    for o in r["orders"]:
        d = ist_day(o.get("created_at"))
        if d in trend and o.get("payment_status") in PAID_EVER:
            trend[d]["orders"] += 1
            trend[d]["sales_paise"] += goods_paise(o) - min(paise_of(o, "refunded_paise", "refunded_amount"), goods_paise(o))
    for c in r["commissions"]:
        d = ist_day(c.get("created_at"))
        if d in trend:
            trend[d]["commission_paise"] += comm_net(c)
    # why held: all-time unreleased commissions (what the member is waiting for), grouped by the finance rule's own reason
    open_comms = await db.commissions.find({"user_id": user["id"], "released_at": None, "status": {"$nin": ["REVERSED"]}}, {"_id": 0}).to_list(None)
    o_ids = list({c["order_id"] for c in open_comms})
    o_map = {o["id"]: o for o in await db.orders.find({"id": {"$in": o_ids}}, {"_id": 0}).to_list(None)}
    reasons = {}
    for c in open_comms:
        why = await payout_block(o_map.get(c["order_id"]), hold_days=c.get("release_after_days") or 0) or "due_for_release"
        if c.get("status") == "HELD":
            why = "held_by_finance"
        bucket = reasons.setdefault(why, {"reason": why, "count": 0, "amount_paise": 0})
        bucket["count"] += 1
        bucket["amount_paise"] += comm_net(c)
    wallet = await db.wallets.find_one({"user_id": user["id"]}, {"_id": 0}) or {}
    return {"range": {"from": d_from.isoformat(), "to": d_to.isoformat(), "timezone": "Asia/Kolkata"},
            "metrics": r["metrics"], "trend": list(trend.values()), "held_reasons": sorted(reasons.values(), key=lambda x: -x["amount_paise"]),
            "wallet_now": {"available_paise": paise_of(wallet, "available_balance_paise", "available_balance"),
                           "pending_paise": paise_of(wallet, "pending_balance_paise", "pending_balance"),
                           "withdrawn_paise": paise_of(wallet, "total_withdrawn_paise", "total_withdrawn")}}


@router.get("/homegenie/orders")
async def homegenie_orders(frm: Optional[str] = None, to: Optional[str] = None, state: Optional[str] = None, page: int = 1,
                           page_size: int = 20, user: dict = Depends(get_current_user)):
    """Orders attributed to the member, newest first, server-side paged. The customer is shown by first name only."""
    if user.get("role") != "distributor":
        raise HTTPException(status_code=403, detail="Available to HomeGenie members only.")
    from pagination import clamp_page, page_meta
    d_from, d_to, start, end = ist_range(frm, to)
    page, page_size = clamp_page(page, page_size)
    rows = await db.orders.find({"seller_user_id": user["id"], "created_at": {"$gte": start, "$lt": end}}, {"_id": 0}) \
        .sort([("created_at", -1), ("id", 1)]).to_list(None)
    returned = await _returned_orders([o["id"] for o in rows])
    items = []
    comms = {c["order_id"]: c for c in await db.commissions.find({"user_id": user["id"], "type": "COMMISSION_DIRECT",
                                                                  "order_id": {"$in": [o["id"] for o in rows]}}, {"_id": 0}).to_list(None)}
    for o in rows:
        st = order_state(o, o["id"] in returned)
        if state and st != state:
            continue
        c = comms.get(o["id"])
        items.append({"order_number": o.get("order_number"), "created_at": o.get("created_at"), "state": st,
                      "goods_paise": goods_paise(o), "refunded_paise": min(paise_of(o, "refunded_paise", "refunded_amount"), goods_paise(o)),
                      "lines": len(o.get("items") or []), "vendors": len({li.get("vendor_id") for li in o.get("items") or []}),
                      "customer": ((o.get("address") or {}).get("full_name") or "").split(" ")[0][:20],
                      "commission": None if not c else {"net_paise": comm_net(c), "status": c.get("status"), "released_at": c.get("released_at")}})
    total = len(items)
    return {"items": items[(page - 1) * page_size: page * page_size], **page_meta(total, page, page_size),
            "range": {"from": d_from.isoformat(), "to": d_to.isoformat()}}
