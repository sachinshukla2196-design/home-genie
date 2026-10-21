"""HOME GENIES commission engine and HomeGenie Points lifecycle.

Approved rules (owner-confirmed 21 Jun 2026):
  * Base            : product price BEFORE GST (order.subtotal).
  * Direct   30%    : to the HomeGenie whose share link produced the sale.
  * Referral 10%    : to the person who invited that HomeGenie (permanent).
  * Team      5%    : to the person who invited that referrer (one more level up).
  * Credited as PENDING, released to AVAILABLE after the return window.
  * 1 HomeGenie Point = Rs 1.

Eligibility (all must hold, else nothing is credited):
  1. The order is PAID.
  2. The sale is attributed to a HomeGenie's share link (order.seller_user_id).
  3. The seller is an approved HomeGenie (status == "green").
  4. The seller is NOT the buyer (own purchases earn no direct commission).
  5. Each upline recipient must themselves be an approved HomeGenie.
  6. Recruitment alone never earns anything - only qualifying product sales do.
"""
import logging
from core import (db, now_iso, new_id, money2, get_settings, add_wallet_transaction,
                 create_notification, log_audit)

logger = logging.getLogger("homegenies")

DIRECT_PCT_KEY = "commission_direct_pct"
REFERRAL_PCT_KEY = "commission_referral_pct"
TEAM_PCT_KEY = "commission_team_pct"
RETURN_WINDOW_KEY = "return_window_days"

TXN_DIRECT = "COMMISSION_DIRECT"
TXN_REFERRAL = "COMMISSION_REFERRAL"
TXN_TEAM = "COMMISSION_TEAM"


async def _approved(user_id: str):
    if not user_id:
        return None
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    if u and u.get("status") == "green":
        return u
    return None


async def distribute_sale_commissions(order: dict, buyer: dict, request=None) -> dict:
    """Credit PENDING commissions for one paid order. Idempotent via an atomic claim."""
    seller_id = order.get("seller_user_id")
    if not seller_id or seller_id == buyer.get("id"):
        return {"credited": 0, "reason": "no_attributed_seller"}

    claim = await db.orders.update_one(
        {"id": order["id"], "commissions_paid": {"$ne": True}},
        {"$set": {"commissions_paid": True, "commissions_paid_at": now_iso()}})
    if claim.modified_count != 1:
        return {"credited": 0, "reason": "already_processed"}

    seller = await _approved(seller_id)
    if not seller:
        await db.orders.update_one({"id": order["id"]},
                                   {"$set": {"commission_note": "seller_not_approved"}})
        return {"credited": 0, "reason": "seller_not_approved"}

    settings = await get_settings()
    base = float(order.get("subtotal") or 0)
    sym = settings.get("currency_symbol", "Rs ")
    window = int(settings.get(RETURN_WINDOW_KEY, 7))

    referrer = await _approved(seller.get("sponsor_user_id"))
    team = await _approved((referrer or {}).get("sponsor_user_id"))

    plan = [
        (seller, float(settings.get(DIRECT_PCT_KEY, 30.0)), TXN_DIRECT, "Direct sales commission"),
        (referrer, float(settings.get(REFERRAL_PCT_KEY, 10.0)), TXN_REFERRAL, "Referral commission"),
        (team, float(settings.get(TEAM_PCT_KEY, 5.0)), TXN_TEAM, "Team sales commission"),
    ]

    credited = 0
    for person, pct, txn_type, label in plan:
        if not person or pct <= 0:
            continue
        amount = money2(base * pct / 100.0)
        if amount <= 0:
            continue
        await add_wallet_transaction(
            person["id"], txn_type, amount, "PENDING",
            reference=order["id"],
            description=f"{label} ({pct:g}% of {sym}{base:g}) - order {order['order_number']}")
        await db.commissions.insert_one({
            "id": new_id(), "order_id": order["id"], "order_number": order["order_number"],
            "user_id": person["id"], "distributor_id": person.get("distributor_id"),
            "seller_user_id": seller["id"], "seller_distributor_id": seller.get("distributor_id"),
            "type": txn_type, "percent": pct, "base_amount": base, "amount": amount,
            "status": "PENDING", "release_after_days": window,
            "created_at": now_iso(), "released_at": None,
        })
        await create_notification(
            person["id"], "commission", f"{label} earned",
            f"{amount:g} points are pending on order {order['order_number']}. "
            f"They become available {window} days after delivery of the return window.",
            f"{label} अर्जित",
            f"ऑर्डर {order['order_number']} पर {amount:g} पॉइंट्स लंबित हैं। "
            f"वापसी अवधि के {window} दिन बाद ये उपलब्ध हो जाएंगे।")
        credited += 1

    await log_audit(None, "commissions_credited", "order", order["id"],
                    new_value={"base": base, "recipients": credited}, request=request)
    return {"credited": credited, "base": base}


async def release_due_points(now_days_fn=None) -> dict:
    """Move PENDING commissions to AVAILABLE once their return window has passed.

    Skips orders that were refunded, partially refunded or cancelled.
    """
    from datetime import datetime, timezone, timedelta
    released, skipped = 0, 0
    cursor = db.commissions.find({"status": "PENDING"}, {"_id": 0})
    for c in await cursor.to_list(5000):
        try:
            created = datetime.fromisoformat(str(c["created_at"]).replace("Z", "+00:00"))
        except Exception:
            continue
        due = created + timedelta(days=int(c.get("release_after_days") or 7))
        if datetime.now(timezone.utc) < due:
            continue
        order = await db.orders.find_one({"id": c["order_id"]}, {"_id": 0})
        if not order or order.get("payment_status") not in ("paid",):
            skipped += 1
            continue
        claim = await db.commissions.update_one(
            {"id": c["id"], "status": "PENDING"},
            {"$set": {"status": "RELEASED", "released_at": now_iso()}})
        if claim.modified_count != 1:
            continue
        amount = float(c["amount"])
        await db.wallets.update_one(
            {"user_id": c["user_id"]},
            {"$inc": {"pending_balance": -amount, "available_balance": amount, "total_earned": amount},
             "$set": {"updated_at": now_iso()}})
        await add_wallet_transaction(
            c["user_id"], "POINTS_RELEASED", amount, "INFO", reference=c["order_id"],
            description=f"Points released for order {c.get('order_number')}")
        await create_notification(
            c["user_id"], "points", "Points available",
            f"{amount:g} points from order {c.get('order_number')} are now available.",
            "पॉइंट्स उपलब्ध",
            f"ऑर्डर {c.get('order_number')} के {amount:g} पॉइंट्स अब उपलब्ध हैं।")
        released += 1
    logger.info("points release: %s released, %s skipped", released, skipped)
    return {"released": released, "skipped": skipped}
