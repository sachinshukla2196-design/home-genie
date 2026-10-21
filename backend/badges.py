"""HomeGenie monthly badges.

Badges are earned on the value of qualifying sales made through a HomeGenie's share link
in the current calendar month (product price before GST). Thresholds are editable in
Admin -> Settings. A badge is recognition only - it does not change any commission rate.
"""
from datetime import datetime, timezone

from core import db, get_settings

DEFAULT_TIERS = [
    ("Bronze", 10000.0),
    ("Silver", 25000.0),
    ("Gold", 50000.0),
    ("Diamond", 100000.0),
]


async def _tiers():
    s = await get_settings()
    return [
        (s.get("badge_t1_name", "Bronze"), float(s.get("badge_t1_sales", 10000.0))),
        (s.get("badge_t2_name", "Silver"), float(s.get("badge_t2_sales", 25000.0))),
        (s.get("badge_t3_name", "Gold"), float(s.get("badge_t3_sales", 50000.0))),
        (s.get("badge_t4_name", "Diamond"), float(s.get("badge_t4_sales", 100000.0))),
    ]


async def monthly_badge(user_id: str, month: str = None) -> dict:
    """Current-month sales value, the badge earned and progress to the next one."""
    month = month or datetime.now(timezone.utc).strftime("%Y-%m")
    orders = await db.orders.find(
        {"seller_user_id": user_id, "payment_status": "paid",
         "created_at": {"$regex": f"^{month}"}},
        {"_id": 0, "subtotal": 1}).to_list(5000)
    sales = round(sum(float(o.get("subtotal") or 0) for o in orders), 2)

    tiers = await _tiers()
    earned, earned_index = None, -1
    for i, (name, threshold) in enumerate(tiers):
        if sales >= threshold:
            earned, earned_index = name, i
    nxt = tiers[earned_index + 1] if earned_index + 1 < len(tiers) else None
    remaining = round(max(nxt[1] - sales, 0), 2) if nxt else 0.0
    progress = round(min(sales / nxt[1] * 100, 100), 1) if nxt else 100.0

    return {
        "month": month,
        "sales_value": sales,
        "orders": len(orders),
        "badge": earned,
        "next_badge": nxt[0] if nxt else None,
        "next_target": nxt[1] if nxt else None,
        "remaining": remaining,
        "progress_pct": progress,
        "tiers": [{"name": n, "sales": t} for n, t in tiers],
    }
