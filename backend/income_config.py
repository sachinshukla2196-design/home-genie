"""DB-backed, versioned Income & Commission rule configs.

- Rates live in the `income_rule_configs` collection (NOT hardcoded as the source of truth).
- Every publish creates a new immutable version; prior versions are preserved.
- Rates apply PROSPECTIVELY from `effective_at`. Already-posted commissions keep the rule
  version stamped on them and are never recalculated.
- Payout-inactive categories (Royalty/Master Club/Super Club) can be configured but DO NOT
  trigger any payout — their multi-qualifier allocation formula is still undefined.
- Monthly Fixed Income: only the pool % is configurable; the equal-GREEN-ID distribution is fixed.
"""
from core import db, now_iso

INCOME_CATEGORIES = [
    {"key": "PERSONAL_REPURCHASE", "name": "Personal Repurchase Income", "default_rate": 5.0,
     "payout_active": True, "defined": True,
     "note": "Paid to the self-purchasing distributor on paid orders after their first purchase. Base = order subtotal (excl GST)."},
    {"key": "TEAM_PURCHASE", "name": "Team Purchase Income", "default_rate": 2.5,
     "payout_active": True, "defined": True,
     "note": "Paid to the direct sponsor on their level-1 team's product purchases (sponsor must be GREEN)."},
    {"key": "ROYALTY", "name": "Royalty Income (RD)", "default_rate": 5.0,
     "payout_active": False, "defined": False,
     "note": "Rate configurable; payout NOT active — allocation among multiple RD qualifiers is undefined."},
    {"key": "MASTER_CLUB", "name": "Master Club Income (CD)", "default_rate": 3.0,
     "payout_active": False, "defined": False,
     "note": "Rate configurable; payout NOT active — CD allocation among multiple qualifiers is undefined."},
    {"key": "SUPER_CLUB", "name": "Super Club Income (PD)", "default_rate": 3.0,
     "payout_active": False, "defined": False,
     "note": "Rate configurable; payout NOT active — PD allocation among multiple qualifiers is undefined."},
    {"key": "MONTHLY_FIXED_INCOME", "name": "Monthly Fixed Income Pool", "default_rate": 1.0,
     "payout_active": True, "defined": True,
     "note": "Pool = this % of eligible monthly turnover (excl GST), split equally among eligible GREEN IDs. Distribution rule is fixed."},
]

CATEGORY_KEYS = {c["key"] for c in INCOME_CATEGORIES}
DEFAULT_RATES = {c["key"]: c["default_rate"] for c in INCOME_CATEGORIES}


async def resolve_rate(category: str, default_rate: float = None, at_iso: str = None) -> dict:
    """Return the rule that applies at `at_iso` (defaults to now): the latest PUBLISHED config
    whose effective_at <= at. Falls back to the hardcoded default (version 0) when none exists."""
    at = at_iso or now_iso()
    cfg = await db.income_rule_configs.find_one(
        {"category": category, "status": "published", "effective_at": {"$lte": at}},
        sort=[("effective_at", -1), ("version", -1)],
    )
    if not cfg:
        dr = DEFAULT_RATES.get(category, 0.0) if default_rate is None else default_rate
        return {"rate": float(dr), "version": 0, "enabled": True}
    return {"rate": float(cfg["rate_percent"]), "version": int(cfg["version"]),
            "enabled": bool(cfg.get("enabled", True))}
