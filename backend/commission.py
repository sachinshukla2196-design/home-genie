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
from core import (db, now_iso, new_id, get_settings, add_wallet_transaction, wallet_apply,
                 create_notification, log_audit)
from datetime import datetime, timezone, timedelta
from money import to_paise, paise_to_float, mul_pct, paise_of
from cod_rules import collection_is_proven
from pymongo.errors import DuplicateKeyError

logger = logging.getLogger("homegenies")

DIRECT_PCT_KEY = "commission_direct_pct"
REFERRAL_PCT_KEY = "commission_referral_pct"
TEAM_PCT_KEY = "commission_team_pct"
RETURN_WINDOW_KEY = "return_window_days"

TXN_DIRECT = "COMMISSION_DIRECT"
TXN_REFERRAL = "COMMISSION_REFERRAL"
TXN_TEAM = "COMMISSION_TEAM"

# Hold period policy: the default (7 days) applies only when the stored value is ABSENT (None). An explicit 0 means
# zero days. Negative, fractional, boolean or non-numeric values are invalid: such a commission is never released
# automatically and is reported, instead of being guessed at.
RELEASE_DEFAULT_DAYS = 7


def release_days(value):
    """Hold period in whole days, or None when the stored value is invalid."""
    if value is None:
        return RELEASE_DEFAULT_DAYS
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value) if value >= 0 else None


def remaining_paise(c: dict) -> int:
    """The part of a commission still owed: credited amount minus everything reversed by refunds (exact paise)."""
    return paise_of(c, "amount_paise", "amount") - paise_of(c, "reversed_paise", "reversed_amount")


def snapshot_filter(c: dict) -> dict:
    """A filter that matches the commission exactly as it was read. A concurrent release or refund changes one of
    these fields, so a stale writer's update matches nothing and it must re-read the record."""
    f = {"status": c.get("status"), "released_at": c.get("released_at")}
    for key in ("reversed_paise", "reversed_amount"):
        f[key] = c[key] if key in c else {"$exists": False}
    return f


async def _approved(user_id: str):
    if not user_id:
        return None
    u = await db.users.find_one({"id": user_id}, {"_id": 0})
    if u and u.get("status") == "green":
        return u
    return None


async def _freeze_plan(order: dict, seller_id: str):
    """Decide the recipients and exact amounts ONCE, with the approved rules, and store them as the distribution plan.
    The plan is created with a single insert keyed by the order id, so only one attempt can create it. Retries use the
    stored plan, so a referral or approval changing later cannot alter what was decided. Returns an error code or None."""
    settings = await get_settings()
    window = release_days(settings.get(RETURN_WINDOW_KEY))
    if window is None:
        # an invalid return window is never guessed at: nothing is decided, so the order can be processed again later
        logger.error("return_window_days is invalid; commissions for order %s not credited", order.get("id"))
        return "invalid_return_window"
    base_p = paise_of(order, "subtotal_paise", "subtotal")
    sym = settings.get("currency_symbol", "Rs ")
    seller = await _approved(seller_id)
    items, note = [], None
    if not seller:
        note = "seller_not_approved"
    else:
        referrer = await _approved(seller.get("sponsor_user_id"))
        team = await _approved((referrer or {}).get("sponsor_user_id"))
        plan = [
            (seller, float(settings.get(DIRECT_PCT_KEY, 30.0)), TXN_DIRECT, "Direct sales commission"),
            (referrer, float(settings.get(REFERRAL_PCT_KEY, 10.0)), TXN_REFERRAL, "Referral commission"),
            (team, float(settings.get(TEAM_PCT_KEY, 5.0)), TXN_TEAM, "Team sales commission"),
        ]
        buyer_id = order.get("user_id")
        for person, pct, txn_type, label in plan:
            if not person or pct <= 0:
                continue
            if buyer_id and person["id"] == buyer_id:
                continue          # nobody earns on their own purchase, in any role; the skipped amount stays unpaid and is not redirected
            amount_p = mul_pct(base_p, pct)          # exact, rounded half-up to the paisa
            if amount_p <= 0:
                continue
            items.append({"type": txn_type, "label": label, "user_id": person["id"], "distributor_id": person.get("distributor_id"),
                          "percent": pct, "amount_paise": amount_p, "seller_user_id": seller["id"],
                          "seller_distributor_id": seller.get("distributor_id")})
    doc = {"_id": order["id"], "order_id": order["id"], "order_number": order["order_number"], "items": items,
           "base_paise": base_p, "base": paise_to_float(base_p), "currency_symbol": sym, "window": window,
           "created_at": now_iso(), "completed_at": None}
    try:
        await db.commission_plans.insert_one(doc)
    except DuplicateKeyError:
        return None                                    # another attempt froze the plan first; its plan is used
    if note:
        await db.orders.update_one({"id": order["id"]}, {"$set": {"commission_note": note}})
    return None


async def _apply_item(plan: dict, item: dict) -> bool:
    """One recipient's movement, in recoverable steps: commission record, ledger row, wallet move, applied marker.
    Returns True when this call moved the wallet."""
    key = f"dist:{plan['order_id']}:{item['type']}"
    existing = await db.commissions.find_one({"_id": key}, {"_id": 0, "distribution": 1})
    if existing and (existing.get("distribution") or {}).get("applied"):
        return False
    amount_p = int(item["amount_paise"])
    amount = paise_to_float(amount_p)
    pct = item["percent"]
    try:
        await _insert_commission({
            "_id": key, "id": key, "order_id": plan["order_id"], "order_number": plan["order_number"],
            "user_id": item["user_id"], "distributor_id": item.get("distributor_id"),
            "seller_user_id": item["seller_user_id"], "seller_distributor_id": item.get("seller_distributor_id"),
            "type": item["type"], "percent": pct, "base_amount": plan["base"], "base_paise": plan["base_paise"],
            "amount": amount, "amount_paise": amount_p, "status": "PENDING", "release_after_days": plan["window"],
            "created_at": plan["created_at"], "released_at": None,
            "distribution": {"op_key": key, "applied": False}})
    except DuplicateKeyError:
        pass                                           # the record exists from an earlier attempt
    from financial_ops import ensure_ledger, move_wallet_once
    sym = plan["currency_symbol"]
    await ensure_ledger({
        "id": new_id(), "user_id": item["user_id"], "type": item["type"], "direction": "credit",
        "amount": amount, "amount_paise": amount_p, "status": "PENDING", "reference": plan["order_id"], "op_key": key,
        "description": f"{item['label']} ({pct:g}% of {sym}{plan['base']:g}) - order {plan['order_number']}",
        "created_at": now_iso()})
    moved = await move_wallet_once(item["user_id"], {"pending_balance": amount_p}, key)
    await _mark_distribution_applied(key)
    if moved:
        await create_notification(
            item["user_id"], "commission", f"{item['label']} earned",
            f"{amount:g} points are pending on order {plan['order_number']}. "
            f"They become available {plan['window']} days after delivery of the return window.",
            f"{item['label']} अर्जित",
            f"ऑर्डर {plan['order_number']} पर {amount:g} पॉइंट्स लंबित हैं। "
            f"वापसी अवधि के {plan['window']} दिन बाद ये उपलब्ध हो जाएंगे।")
    return moved


async def _insert_commission(doc: dict) -> None:
    await db.commissions.insert_one(doc)


async def _mark_distribution_applied(key: str) -> None:
    await db.commissions.update_one({"_id": key, "distribution.op_key": key}, {"$set": {"distribution.applied": True}})


async def resume_distribution(order_id: str) -> dict:
    """Finish a frozen plan: every recipient not yet applied is applied, in the same order. Safe to call repeatedly and
    concurrently. The order flag is set only when every recipient is complete."""
    plan = await db.commission_plans.find_one({"_id": order_id}, {"_id": 0})
    if not plan:
        return {"credited": 0, "reason": "no_plan"}
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "payment_method": 1, "payment_status": 1, "cod_collection": 1})
    if (order or {}).get("payment_method") == "cod" and not collection_is_proven(order):
        # resume is reached from the release cron and the refund path too; neither may finish a distribution that the
        # COD proof rule would refuse. The incomplete plan stays visible to wallet_reconcile for operator review.
        return {"credited": 0, "reason": "cod_collection_not_proven"}
    newly = 0
    for item in plan["items"]:
        if await _apply_item(plan, item):
            newly += 1
    keys = [f"dist:{order_id}:{item['type']}" for item in plan["items"]]
    applied = await db.commissions.count_documents({"_id": {"$in": keys}, "distribution.applied": True}) if keys else 0
    complete = applied == len(plan["items"])
    if complete:
        if plan.get("completed_at") is None:
            await db.commission_plans.update_one({"_id": order_id, "completed_at": None}, {"$set": {"completed_at": now_iso()}})
        await db.orders.update_one({"id": order_id, "commissions_paid": {"$ne": True}},
                                   {"$set": {"commissions_paid": True, "commissions_paid_at": now_iso()}})
    result = {"credited": newly, "base": plan["base"], "complete": complete}
    if newly == 0 and complete:
        result["reason"] = "already_processed"
    return result


async def distribute_sale_commissions(order: dict, buyer: dict, request=None) -> dict:
    """Credit PENDING commissions for one paid order. Crash-safe and idempotent (see financial_ops and the plan above).

    The order flag is set only after every recipient is complete. An order flagged before this change (no plan) is never
    re-paid: it is reported by distribution_audit() instead."""
    seller_id = order.get("seller_user_id")
    if not seller_id or seller_id == buyer.get("id"):
        return {"credited": 0, "reason": "no_attributed_seller"}
    if order.get("payment_method") == "cod" and not collection_is_proven(order):
        # defence in depth: a manual exception, an unresolved hold, a short collection or a missing record never earns commission
        return {"credited": 0, "reason": "cod_collection_not_proven"}
    if await db.commission_plans.find_one({"_id": order["id"]}, {"_id": 1}) is None:
        current = await db.orders.find_one({"id": order["id"]}, {"_id": 0, "commissions_paid": 1})
        if (current or {}).get("commissions_paid"):
            return {"credited": 0, "reason": "already_processed"}      # historical flag without a plan: never re-paid
        error = await _freeze_plan(order, seller_id)
        if error:
            return {"credited": 0, "reason": error}
    result = await resume_distribution(order["id"])
    if result.get("complete"):
        await log_audit(None, "commissions_credited", "order", order["id"],
                        new_value={"recipients": result["credited"]}, request=request)
    return result


async def release_due_points(now: datetime = None) -> dict:
    """Release commissions whose hold period has passed, for the UNREVERSED remainder only.

    Crash-safe (see financial_ops): first the releases recorded by an earlier, interrupted run are finished; then each
    eligible commission gets a release INTENT in one conditional update that matches the record exactly as read, and the
    intent is finished. A commission is held while its order has an unresolved return or refund case. A fully reversed
    commission is REVERSED and is never released. Repeated and concurrent runs cannot pay the same commission twice.
    """
    from financial_ops import finish_release, has_open_case
    now = now or datetime.now(timezone.utc)
    finished = released = skipped = invalid = held = 0
    for plan in await db.commission_plans.find({"completed_at": None}, {"_id": 1}).to_list(5000):
        await resume_distribution(plan["_id"])          # an interrupted distribution is completed before anything is released
    for c in await db.commissions.find({"release.applied": False}, {"_id": 0}).to_list(5000):
        if await finish_release(c):
            finished += 1
    cursor = db.commissions.find({"status": {"$in": ["PENDING", "PARTIALLY_REVERSED"]}, "released_at": None, "manual_hold": {"$ne": True},
                                  "distribution.applied": {"$ne": False}}, {"_id": 0})
    for c in await cursor.to_list(5000):
        days = release_days(c.get("release_after_days"))
        if days is None:
            invalid += 1
            logger.error("commission %s has an invalid release_after_days; not released", c.get("id"))
            continue
        try:
            created = datetime.fromisoformat(str(c["created_at"]).replace("Z", "+00:00"))
        except Exception:
            skipped += 1
            continue
        if now < created + timedelta(days=days):
            continue
        order = await db.orders.find_one({"id": c["order_id"]}, {"_id": 0})
        if not order or order.get("payment_status") not in ("paid", "partially_refunded"):
            skipped += 1
            continue
        if await has_open_case(c["order_id"]):
            held += 1           # the remainder waits until the return or refund case is resolved
            continue
        amount_p = remaining_paise(c)
        if amount_p <= 0:
            skipped += 1
            continue
        op = f"release:{c['id']}"
        intent = await db.commissions.update_one(
            {"id": c["id"], **snapshot_filter(c)},
            {"$set": {"status": "RELEASED", "released_at": now_iso(), "released_paise": amount_p,
                      "released_amount": paise_to_float(amount_p),
                      "release": {"op_key": op, "amount_paise": amount_p, "applied": False}}})
        if intent.modified_count != 1:
            continue            # a refund or another run changed this record first; it is re-read on the next run
        if await finish_release(await db.commissions.find_one({"id": c["id"]}, {"_id": 0})):
            released += 1
    logger.info("points release: %s released, %s finished, %s skipped, %s held, %s invalid",
                released, finished, skipped, held, invalid)
    return {"released": released, "finished_interrupted": finished, "skipped": skipped, "held": held, "invalid": invalid}


async def release_commission_now(commission_id: str, now: datetime = None) -> dict:
    """Administrative "release now": the same release as the points cron, applied to ONE commission, with the same conditions.

    It is not an override. It never releases inside the return window, for an order that is not paid, for COD whose full
    collection is unproven, while a return or refund case is open, for a distribution that is incomplete, or beyond what is
    still owed after clawbacks. The money moves only through the recorded release intent (finish_release): ledger row,
    one-time wallet move, applied marker. Repeats and races cannot move it twice. Returns {"ok": True, ...} or
    {"ok": False, "code": <http status>, "detail": <reason>}."""
    from financial_ops import finish_release
    now = now or datetime.now(timezone.utc)
    c = await db.commissions.find_one({"id": commission_id}, {"_id": 0})
    if not c:
        return {"ok": False, "code": 404, "detail": "Commission not found."}
    if (c.get("release") or {}).get("applied") is False:
        await finish_release(c)                              # finish an interrupted release; nothing new is decided
        c = await db.commissions.find_one({"id": commission_id}, {"_id": 0})
    if c.get("released_at") or c.get("status") == "RELEASED":
        return {"ok": True, "already": True, "status": c.get("status")}
    if c.get("status") not in ("PENDING", "PARTIALLY_REVERSED", "HELD"):
        return {"ok": False, "code": 409, "detail": f"A {c.get('status')} commission cannot be released."}
    if (c.get("distribution") or {}).get("applied") is False:
        return {"ok": False, "code": 409, "detail": "This commission's distribution is not complete."}
    days = release_days(c.get("release_after_days"))
    if days is None:
        return {"ok": False, "code": 409, "detail": "This commission has an invalid release period."}
    try:
        created = datetime.fromisoformat(str(c["created_at"]).replace("Z", "+00:00"))
    except Exception:
        return {"ok": False, "code": 409, "detail": "This commission has no valid creation date."}
    if now < created + timedelta(days=days):
        return {"ok": False, "code": 409, "detail": "The return window has not ended, so this commission cannot be released yet."}
    order = await db.orders.find_one({"id": c["order_id"]}, {"_id": 0})
    if not order or order.get("payment_status") not in ("paid", "partially_refunded") or order.get("needs_refund") or order.get("status") == "cancelled":
        return {"ok": False, "code": 409, "detail": "The order is not in a paid, active state."}
    if order.get("payment_method") == "cod" and not collection_is_proven(order):
        return {"ok": False, "code": 409, "detail": "COD collection for this order is not proven."}
    from financial_ops import has_open_case as _open
    if await _open(c["order_id"]):
        return {"ok": False, "code": 409, "detail": "A return or refund case is open on this order."}
    amount_p = remaining_paise(c)
    if amount_p <= 0:
        return {"ok": False, "code": 409, "detail": "Nothing remains to release on this commission."}
    intent = await db.commissions.update_one(
        {"id": c["id"], **snapshot_filter(c)},
        {"$set": {"status": "RELEASED", "released_at": now_iso(), "released_paise": amount_p, "released_amount": paise_to_float(amount_p),
                  "manual_hold": False, "release": {"op_key": f"release:{c['id']}", "amount_paise": amount_p, "applied": False}}})
    if intent.modified_count != 1:
        return {"ok": True, "already": True, "status": "RELEASED"}      # the cron or another admin changed it first
    await finish_release(await db.commissions.find_one({"id": c["id"]}, {"_id": 0}))
    return {"ok": True, "released_paise": amount_p, "status": "RELEASED"}
