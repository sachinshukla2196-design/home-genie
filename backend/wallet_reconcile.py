"""READ-ONLY reconciliation of wallet aggregates against the wallet ledger (wallet_transactions).

Wallet balances are aggregates moved by core.wallet_apply. Each ledger row is written by core.add_wallet_transaction.
Some writers also move the aggregates directly and then write an informational row whose status moves nothing:
    POINTS_RELEASED (INFO)     commission released: pending -> available and total_earned
    COMMISSION_CLAWBACK (INFO) pending commission cancelled: pending reduced
    WITHDRAWAL HELD            withdrawal requested: available -> pending
    WITHDRAWAL PAID            withdrawal paid: pending -> total_withdrawn
    WITHDRAWAL REJECTED        withdrawal rejected: pending -> available
The rules below reproduce those effects from the ledger. Amounts are integer paise. Nothing here writes to the database.
"""
from core import db, to_paise, WALLET_FIELDS


def _paise(row: dict) -> int:
    if isinstance(row.get("amount_paise"), int):
        return row["amount_paise"]
    return to_paise(float(row.get("amount") or 0))


def expected_aggregates(rows: list) -> dict:
    """The wallet aggregates implied by one user's ledger rows."""
    def total(pred):
        return sum(_paise(r) for r in rows if pred(r))

    credited = total(lambda r: r.get("status") == "CREDITED" and r.get("direction") == "credit")
    released = total(lambda r: r.get("type") == "POINTS_RELEASED")
    clawback_released = total(lambda r: r.get("status") == "CLAWBACK")
    pending_credit = total(lambda r: r.get("status") == "PENDING")
    pending_cancelled = total(lambda r: r.get("type") == "COMMISSION_CLAWBACK" and r.get("status") == "INFO")
    debited = total(lambda r: r.get("status") == "DEBITED" and r.get("direction") == "debit")
    held = total(lambda r: r.get("type") == "WITHDRAWAL" and r.get("status") == "HELD")
    paid = total(lambda r: r.get("type") == "WITHDRAWAL" and r.get("status") == "PAID")
    rejected = total(lambda r: r.get("type") == "WITHDRAWAL" and r.get("status") == "REJECTED")

    total_earned = credited + released - clawback_released
    total_withdrawn = debited + paid
    open_holds = held - paid - rejected                       # withdrawals requested and not yet settled
    return {
        "total_earned": total_earned,
        "total_withdrawn": total_withdrawn,
        "pending_balance": pending_credit - released - pending_cancelled + open_holds,
        "available_balance": total_earned - total_withdrawn - open_holds,
    }


async def _has_ledger(op_key: str) -> bool:
    return bool(await db.wallet_transactions.find_one({"op_key": op_key}, {"_id": 1}))


async def intent_issues(user_id: str = None):
    """Commission-level checks against the ledger. A commission marked released must have its release ledger row.
    Incomplete intents are reported as they are; nothing is changed here. Returns (issues, legacy_unverified_count)."""
    query = {"user_id": user_id} if user_id else {}
    query["$or"] = [{"release": {"$exists": True}}, {"reversal_records.0": {"$exists": True}}, {"status": "RELEASED"},
                    {"distribution": {"$exists": True}}]
    issues, legacy = [], 0
    async for c in db.commissions.find(query, {"_id": 0}):
        dist = c.get("distribution")
        if dist:
            if not await _has_ledger(dist["op_key"]):
                issues.append({"commission_id": c["id"], "issue": "distribution_ledger_missing" if dist.get("applied")
                               else "distribution_incomplete", "op_key": dist["op_key"]})
            elif not dist.get("applied"):
                issues.append({"commission_id": c["id"], "issue": "distribution_incomplete", "op_key": dist["op_key"]})
        rel = c.get("release")
        if rel:
            if not await _has_ledger(rel["op_key"]):
                issues.append({"commission_id": c["id"], "issue": "release_ledger_missing", "op_key": rel["op_key"]})
            if not rel.get("applied"):
                issues.append({"commission_id": c["id"], "issue": "release_incomplete", "op_key": rel["op_key"]})
        elif c.get("status") == "RELEASED":
            legacy += 1                                    # released before intents were recorded: cannot be verified per commission
        for rec in c.get("reversal_records", []):
            has = await _has_ledger(rec["op_key"])
            if rec.get("applied") and not has:
                issues.append({"commission_id": c["id"], "issue": "clawback_ledger_missing", "op_key": rec["op_key"]})
            if not rec.get("applied"):
                issues.append({"commission_id": c["id"], "issue": "clawback_incomplete", "op_key": rec["op_key"]})
    return issues, legacy


async def distribution_audit() -> dict:
    """Read-only: orders whose distribution cannot be verified or is incomplete. Reports order ids and operation keys only."""
    plan_ids = set(await db.commission_plans.distinct("_id"))
    flagged = await db.orders.find({"commissions_paid": True}, {"_id": 0, "id": 1}).to_list(100000)
    legacy = sorted(o["id"] for o in flagged if o["id"] not in plan_ids)
    incomplete = []
    async for plan in db.commission_plans.find({"completed_at": None}, {"_id": 1, "items": 1}):
        keys = [f"dist:{plan['_id']}:{item['type']}" for item in plan.get("items", [])]
        done = await db.commissions.count_documents({"_id": {"$in": keys}, "distribution.applied": True})
        if done != len(keys):
            incomplete.append({"order_id": plan["_id"], "keys": keys, "applied": done})
    flag_missing = []
    async for plan in db.commission_plans.find({"completed_at": {"$ne": None}}, {"_id": 1}):
        if not await db.orders.find_one({"id": plan["_id"], "commissions_paid": True}, {"_id": 1}):
            flag_missing.append(plan["_id"])
    return {"flagged_without_plan": legacy, "incomplete_plans": incomplete, "complete_but_unflagged": sorted(flag_missing)}


async def reconcile(user_id: str = None) -> dict:
    """Compare stored wallet aggregates (exact paise) with the ledger. Returns discrepancies; never changes data."""
    wallet_query = {"user_id": user_id} if user_id else {}
    wallets = await db.wallets.find(wallet_query, {"_id": 0}).to_list(100000)
    discrepancies, checked = [], 0
    for w in wallets:
        uid = w.get("user_id")
        if any(not isinstance(w.get(f + "_paise"), int) for f in WALLET_FIELDS):
            discrepancies.append({"user_id": uid, "issue": "legacy wallet not upgraded to paise"})
            continue
        rows = await db.wallet_transactions.find({"user_id": uid}, {"_id": 0}).to_list(100000)
        expected = expected_aggregates(rows)
        checked += 1
        for field, value in expected.items():
            stored = w[field + "_paise"]
            if stored != value:
                discrepancies.append({"user_id": uid, "field": field, "stored_paise": stored, "ledger_paise": value,
                                      "difference_paise": stored - value})
    # ledger history whose wallet no longer exists (e.g. a deleted user's history kept for audit): reported, not a balance error
    duplicates = await db.wallets.aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}]).to_list(100000)
    for d in duplicates:
        discrepancies.append({"user_id": d["_id"], "issue": "duplicate_wallet", "wallets": d["n"]})
    wallet_users = {w.get("user_id") for w in wallets}
    orphan_users = set()
    if not user_id:
        async for r in db.wallet_transactions.find({}, {"_id": 0, "user_id": 1}):
            if r.get("user_id") not in wallet_users:
                orphan_users.add(r.get("user_id"))
    issues, legacy = await intent_issues(user_id)
    return {"wallets_checked": checked, "discrepancies": discrepancies, "commission_issues": issues,
            "legacy_released_unverified": legacy, "distribution_audit": await distribution_audit(), "orphan_ledger_users": sorted(u for u in orphan_users if u)}
