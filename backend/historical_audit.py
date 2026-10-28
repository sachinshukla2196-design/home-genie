"""READ-ONLY historical audit: duplicate wallets, legacy commission distribution, and index/migration readiness.

Nothing in this module writes to the database. It uses only find, aggregate, count, distinct and index_information,
and the migration dry run (vendor_lifecycle.migrate with apply=False), which is read-only by construction.

It produces findings and PROPOSED repair manifests. It never merges or deletes a wallet, never credits or debits an
account, and never changes an index. Reports contain stable identifiers (user, wallet, order, commission and operation
keys) and counts. They contain no names, e-mail addresses, mobile numbers or addresses.

Classification of a legacy distribution (an order flagged commissions_paid without a commission_plan):
  verified      every commission matches the amount recorded with it (stored percent x stored subtotal), has exactly one
                ledger credit with the same user, type and amount, the direct recipient is the order's seller, and the
                referral and team recipients match the referral_relationships rows written at registration.
  inconsistent  a check above fails: amount, ledger count, direct recipient, referral/team recipient, or a refund that
                is not reflected in the commissions.
  unverifiable  the evidence needed for a check is missing (no commissions with no recorded reason, no stored percent,
                or no referral record). Nothing is concluded from the absence of evidence.
"""
from collections import Counter

from core import db
from money import mul_pct, paise_of
from wallet_reconcile import expected_aggregates

COMMISSION_TYPES = ["COMMISSION_DIRECT", "COMMISSION_REFERRAL", "COMMISSION_TEAM"]
FIELDS = ("available_balance", "pending_balance", "total_earned", "total_withdrawn")


def _sid(value) -> str:
    return str(value) if value is not None else None


async def wallet_audit() -> dict:
    """Duplicate wallets, their balances against the ledger, duplicate operation keys, and a manifest proposal."""
    duplicated = await db.wallets.aggregate([
        {"$group": {"_id": "$user_id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}, {"$sort": {"_id": 1}}]).to_list(100000)
    users = []
    for d in duplicated:
        uid = d["_id"]
        wallets = await db.wallets.find({"user_id": uid}, {"_id": 1, "applied_ops": 1, **{f + "_paise": 1 for f in FIELDS}}).sort("_id", 1).to_list(100)
        rows = await db.wallet_transactions.find({"user_id": uid}, {"_id": 0, "op_key": 1, "type": 1, "status": 1,
                                                                    "direction": 1, "amount_paise": 1, "amount": 1}).to_list(100000)
        ledger_keys = [r["op_key"] for r in rows if r.get("op_key")]
        dup_keys = sorted(k for k, n in Counter(ledger_keys).items() if n > 1)
        # each operation key counts once; a repeated key means the ledger itself is not trustworthy for this user
        seen, counted = set(), []
        for r in rows:
            if r.get("op_key"):
                if r["op_key"] in seen:
                    continue
                seen.add(r["op_key"])
            counted.append(r)
        expected = expected_aggregates(counted)
        per_wallet = []
        for w in wallets:
            stored = {f: int(w.get(f + "_paise") or 0) for f in FIELDS}
            applied = set(w.get("applied_ops") or [])
            per_wallet.append({"wallet_id": _sid(w["_id"]), "stored_paise": stored,
                               "matches_ledger": stored == {f: expected[f] for f in FIELDS},
                               "applied_markers": len(applied), "covers_ledger_keys": set(ledger_keys) <= applied})
        candidates = [w for w in per_wallet if w["matches_ledger"]]
        reasons = []
        if dup_keys:
            verdict = "not_derivable"
            reasons.append("the ledger repeats operation keys, so no balance can be derived from it")
        elif len(candidates) == 1:
            verdict = "derivable_candidate"
            reasons.append("exactly one wallet agrees with the ledger; the others must still be reviewed before any action")
        elif not candidates:
            verdict = "not_derivable"
            reasons.append("no wallet agrees with the ledger")
        else:
            verdict = "not_derivable"
            reasons.append("more than one wallet agrees with the ledger")
        if dup_keys:
            reasons.append("ledger holds duplicate operation keys")
        users.append({"user_ref": _sid(uid), "wallet_count": len(wallets), "wallets": per_wallet,
                      "ledger_expected_paise": {f: expected[f] for f in FIELDS},
                      "ledger_rows": len(rows), "duplicate_operation_keys": dup_keys,
                      "classification": verdict, "manual_review": True, "reasons": reasons})
    # balances of single wallets that disagree with the ledger (not caused by duplication, but relevant to migration)
    single_drift = []
    singles = await db.wallets.aggregate([{"$group": {"_id": "$user_id", "n": {"$sum": 1}}}, {"$match": {"n": 1}}]).to_list(100000)
    single_ids = {s["_id"] for s in singles}
    async for w in db.wallets.find({"user_id": {"$in": list(single_ids)}}, {"_id": 1, "user_id": 1, **{f + "_paise": 1 for f in FIELDS}}):
        rows = await db.wallet_transactions.find({"user_id": w["user_id"]}, {"_id": 0, "type": 1, "status": 1, "direction": 1,
                                                                             "amount_paise": 1, "amount": 1}).to_list(100000)
        expected = expected_aggregates(rows)
        if any(int(w.get(f + "_paise") or 0) != expected[f] for f in FIELDS):
            single_drift.append(_sid(w["user_id"]))
    manifest = [{"user_ref": u["user_ref"], "action": "manual_review", "executed": False,
                 "canonical_wallet_id": (next(w["wallet_id"] for w in u["wallets"] if w["matches_ledger"])
                                         if u["classification"] == "derivable_candidate" else None),
                 "wallet_ids_to_retire_after_review": [w["wallet_id"] for w in u["wallets"]
                                                       if not (u["classification"] == "derivable_candidate" and w["matches_ledger"])],
                 "note": "Never merge automatically. Preserve every ledger row and wallet document; retire a wallet only after review."}
                for u in users]
    return {"duplicate_wallet_users": users, "duplicate_wallet_count": len(users), "single_wallets_drifting_from_ledger": sorted(single_drift),
            "proposed_repair_manifest": manifest}


async def _ledger_for_order(order_id: str) -> list:
    return await db.wallet_transactions.find({"reference": order_id, "type": {"$in": COMMISSION_TYPES}},
                                             {"_id": 0, "user_id": 1, "type": 1, "direction": 1, "status": 1,
                                              "amount_paise": 1, "op_key": 1}).to_list(1000)


async def _referral_evidence(seller_id: str):
    """Who referred the seller and who referred that referrer, from the referral rows written at registration."""
    link = await db.referral_relationships.find_one({"referred_user_id": seller_id}, {"_id": 0, "sponsor_id": 1})
    if not link:
        return None
    referrer_id = link["sponsor_id"]
    up = await db.referral_relationships.find_one({"referred_user_id": referrer_id}, {"_id": 0, "sponsor_id": 1})
    return {"referrer": referrer_id, "team": up["sponsor_id"] if up else None}


async def classify_order(o: dict) -> dict:
    reasons, status = [], "verified"
    subtotal_p = paise_of(o, "subtotal_paise", "subtotal")
    comms = await db.commissions.find({"order_id": o["id"]}, {"_id": 1, "type": 1, "user_id": 1, "amount_paise": 1, "amount": 1,
                                                              "percent": 1, "status": 1, "reversed_paise": 1}).to_list(1000)
    ledger = await _ledger_for_order(o["id"])
    refunded_p = paise_of(o, "refunded_paise", "refunded_amount")
    if not comms:
        if o.get("commission_note") == "seller_not_approved":
            return {"order_ref": o["id"], "classification": "verified", "reasons": ["seller was not approved; no commissions recorded for that reason"],
                    "commission_count": 0, "ledger_rows": len(ledger)}
        return {"order_ref": o["id"], "classification": "unverifiable",
                "reasons": ["flagged as distributed but no commission records exist and no reason is recorded"],
                "commission_count": 0, "ledger_rows": len(ledger)}
    seller = o.get("seller_user_id")
    evidence = await _referral_evidence(seller) if seller else None
    expected_by_type = {"COMMISSION_REFERRAL": (evidence or {}).get("referrer"), "COMMISSION_TEAM": (evidence or {}).get("team")}
    for c in comms:
        if c.get("percent") is None:
            status = _worse(status, "unverifiable")
            reasons.append(f"{c['type']}: no stored rate to check the amount against")
        else:
            expected = mul_pct(subtotal_p, float(c["percent"]))
            if paise_of(c, "amount_paise", "amount") != expected:
                status = _worse(status, "inconsistent")
                reasons.append(f"{c['type']}: amount differs from stored rate x subtotal")
        credits = [r for r in ledger if r["type"] == c["type"] and r.get("direction") == "credit"
                   and r["user_id"] == c["user_id"] and r.get("amount_paise") == c.get("amount_paise")]
        if len(credits) != 1:
            status = _worse(status, "inconsistent")
            reasons.append(f"{c['type']}: {len(credits)} matching ledger credits (expected 1)")
        if c["type"] == "COMMISSION_DIRECT" and c["user_id"] != seller:
            status = _worse(status, "inconsistent")
            reasons.append("direct commission recipient is not the order's seller")
        if c["type"] in expected_by_type:
            want = expected_by_type[c["type"]]
            if evidence is None:
                status = _worse(status, "unverifiable")
                reasons.append(f"{c['type']}: no referral record for the seller")
            elif want is None:
                if c["user_id"] is not None:
                    status = _worse(status, "inconsistent")
                    reasons.append(f"{c['type']}: paid but the referral record has no such recipient")
            elif c["user_id"] != want:
                status = _worse(status, "inconsistent")
                reasons.append(f"{c['type']}: recipient differs from the referral record")
    present = {c["type"] for c in comms}
    if seller and "COMMISSION_DIRECT" not in present:
        status = _worse(status, "unverifiable")
        reasons.append("no direct commission recorded; cannot confirm the seller was eligible at payment time")
    for typ, want in expected_by_type.items():
        if want and typ not in present:
            status = _worse(status, "unverifiable")
            reasons.append(f"{typ}: the referral record names a recipient but none was recorded; eligibility at payment time cannot be confirmed")
    if refunded_p > 0 and not any(c.get("reversed_paise") for c in comms) and not any(c["status"] == "REVERSED" for c in comms):
        status = _worse(status, "inconsistent")
        reasons.append("the order has a refund but no commission reflects it")
    if not reasons:
        reasons.append("all recorded checks pass")
    return {"order_ref": o["id"], "classification": status, "reasons": reasons, "commission_count": len(comms),
            "commission_ids": sorted(_sid(c["_id"]) for c in comms), "ledger_rows": len(ledger),
            "operation_keys_present": sorted(r["op_key"] for r in ledger if r.get("op_key")),
            "payment_status": o.get("payment_status")}


_RANK = {"verified": 0, "unverifiable": 1, "inconsistent": 2}


def _worse(current: str, new: str) -> str:
    return new if _RANK[new] > _RANK[current] else current


async def legacy_distribution_audit() -> dict:
    plan_ids = set(await db.commission_plans.distinct("_id"))
    flagged = await db.orders.find({"commissions_paid": True}, {"_id": 0}).sort("id", 1).to_list(100000)
    orders = [o for o in flagged if o["id"] not in plan_ids]
    results = [await classify_order(o) for o in orders]
    counts = Counter(r["classification"] for r in results)
    return {"flagged_orders": len(flagged), "flagged_without_plan": len(orders),
            "counts": {k: counts.get(k, 0) for k in ("verified", "inconsistent", "unverifiable")},
            "orders": results,
            "manual_review_required": [r["order_ref"] for r in results if r["classification"] != "verified"],
            "automatic_payouts_made": 0}


async def index_readiness() -> dict:
    from db_indexes import SPECS, _duplicates, plan
    from vendor_lifecycle import migrate
    p = await plan()
    unique = []
    for s in SPECS:
        if s.get("unique"):
            unique.append({"index": s["name"], "collection": s["coll"], "duplicate_values": await _duplicates(s)})
    dry_run = await migrate(apply=False)
    return {"plan": p, "unique_index_duplicates": unique,
            "vendor_migration_dry_run": {"duplicates": {k: len(v) for k, v in dry_run["duplicates"].items()},
                                         "backfill_needed": len(dry_run["backfilled"]), "sequence_moved_to": dry_run["sequence_moved_to"]},
            "startup_creates_indexes": False}


async def full_audit() -> dict:
    wallets = await wallet_audit()
    legacy = await legacy_distribution_audit()
    indexes = await index_readiness()
    blockers = []
    if wallets["duplicate_wallet_count"]:
        blockers.append("duplicate wallets exist: wallets_user_unique cannot be created until they are reviewed")
    if any(u["duplicate_values"] for u in indexes["unique_index_duplicates"]):
        blockers.append("unique index duplicates exist; apply() will refuse those indexes")
    if legacy["manual_review_required"]:
        blockers.append("legacy distributions need manual financial review")
    return {"wallets": wallets, "legacy_distribution": legacy, "indexes": indexes, "production_blockers": blockers}
