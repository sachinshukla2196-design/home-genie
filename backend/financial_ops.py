"""Crash-safe financial operations: the steps that move money for a commission release or a refund clawback.

No multi-document transactions are used. The local and test databases are standalone MongoDB servers, and the
production topology is not part of this repository, so correctness must not depend on transactions. Instead every
money movement is recorded as an INTENT on its commission before any money moves, and every step is idempotent:

  intent   commission.release, or an entry of commission.reversal_records  (op_key, amount, applied=False)
  ledger   wallet_transactions row carrying op_key; op_key is UNIQUE (migration index), so it exists at most once
  wallet   the aggregate is moved once: the update matches only while op_key is absent from wallet.applied_ops, and
           pushes op_key in the same atomic update
  applied  the intent is marked applied

A crash between any two steps leaves an intent that a later run finishes without moving money twice. Nothing in this
module changes a balance except through move_wallet_once.
"""
import logging

from pymongo.errors import DuplicateKeyError

from core import db, now_iso, new_id, get_or_create_wallet, create_notification
from money import paise_to_float

logger = logging.getLogger("homegenies")

# Cases that keep a commission remainder on hold. Anything not listed here is resolved.
OPEN_REFUND_CASE_STATES = ["awaiting_review", "initiated", "failed"]


async def has_open_case(order_id: str) -> bool:
    """True while the order has an unresolved refund case or an active return case."""
    from returns_routes import ACTIVE_RETURN_STATES
    if await db.refund_cases.find_one({"order_id": order_id, "status": {"$in": OPEN_REFUND_CASE_STATES}}, {"_id": 1}):
        return True
    return bool(await db.return_cases.find_one(
        {"order_id": order_id, "status": {"$in": list(ACTIVE_RETURN_STATES) + ["refund_pending"]}}, {"_id": 1}))


async def ensure_ledger(row: dict) -> None:
    """Insert a ledger row once per op_key. The check is followed by the unique index, which closes the race."""
    if await db.wallet_transactions.find_one({"op_key": row["op_key"]}, {"_id": 1}):
        return
    try:
        await db.wallet_transactions.insert_one(dict(row))
    except DuplicateKeyError:
        pass        # a concurrent attempt wrote the same op_key first


async def move_wallet_once(user_id: str, deltas_paise: dict, op_key: str) -> bool:
    """Move wallet aggregates by exact paise, at most once per op_key. Returns False when op_key was already applied."""
    await get_or_create_wallet(user_id)
    inc = {}
    for field, delta in deltas_paise.items():
        inc[field + "_paise"] = int(delta)
        inc[field] = paise_to_float(int(delta))
    res = await db.wallets.update_one(
        {"user_id": user_id, "applied_ops": {"$ne": op_key}},
        {"$inc": inc, "$push": {"applied_ops": op_key}, "$set": {"updated_at": now_iso()}})
    return res.modified_count == 1


async def _mark_applied(commission_id: str, op_key: str) -> None:
    await db.commissions.update_one({"id": commission_id, "release.op_key": op_key}, {"$set": {"release.applied": True}})
    await db.commissions.update_one({"id": commission_id, "reversal_records.op_key": op_key},
                                    {"$set": {"reversal_records.$.applied": True}})


async def finish_release(c: dict) -> bool:
    """Complete a recorded release: ledger row, then the wallet move, then the applied marker. Safe to repeat."""
    rec = c.get("release") or {}
    if not rec or rec.get("applied"):
        return False
    op = rec["op_key"]
    amount_p = int(rec["amount_paise"])
    amount = paise_to_float(amount_p)
    await ensure_ledger({
        "id": new_id(), "user_id": c["user_id"], "type": "POINTS_RELEASED", "direction": "credit",
        "amount": amount, "amount_paise": amount_p, "status": "INFO", "reference": c["order_id"], "op_key": op,
        "description": f"Points released for order {c.get('order_number')}", "created_at": now_iso()})
    moved = await move_wallet_once(c["user_id"], {"pending_balance": -amount_p, "available_balance": amount_p,
                                                  "total_earned": amount_p}, op)
    await _mark_applied(c["id"], op)
    if moved:
        await create_notification(
            c["user_id"], "points", "Points available",
            f"{amount:g} points from order {c.get('order_number')} are now available.",
            "पॉइंट्स उपलब्ध",
            f"ऑर्डर {c.get('order_number')} के {amount:g} पॉइंट्स अब उपलब्ध हैं।")
    return moved


async def finish_reversal(c: dict, rec: dict) -> bool:
    """Complete one recorded clawback for a refund event. Safe to repeat."""
    if rec.get("applied"):
        return False
    op = rec["op_key"]
    claw_p = int(rec["claw_paise"])
    claw = paise_to_float(claw_p)
    if rec["was_pending"]:
        deltas, status = {"pending_balance": -claw_p}, "INFO"           # never released: leaves the pending pool
    else:
        deltas, status = {"available_balance": -claw_p, "total_earned": -claw_p}, "CLAWBACK"
    await ensure_ledger({
        "id": new_id(), "user_id": c["user_id"], "type": "COMMISSION_CLAWBACK", "direction": "debit",
        "amount": claw, "amount_paise": claw_p, "status": status, "reference": rec["event_id"], "op_key": op,
        "description": f"Commission reversed on refund of order {rec.get('order_number', '')}".strip(), "created_at": now_iso()})
    moved = await move_wallet_once(c["user_id"], deltas, op)
    await _mark_applied(c["id"], op)
    return moved
