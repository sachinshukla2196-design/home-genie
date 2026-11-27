"""Programme 01 (B-004): money-changing writes FAIL CLOSED when the unique indexes that make them duplicate-proof are absent.

The money paths are idempotent because MongoDB rejects a second record with the same business key (a vendor ledger `source_key`,
a refund case `source_key`, a wallet `op_key`, one wallet per user, a gateway `event_id`, one open settlement per vendor, a stock
journal `key`, an order number). Those indexes are created ONLY by the migration (`db_indexes.apply()`, run by
`scripts/vendor_foundation_migrate.py --apply`). Without them a retry or a race can write the same money twice.

`ensure(*areas)` is called at the start of every write path in an area. It compares the live index definitions with
`db_indexes.SPECS` - name, key pattern, uniqueness, sparse and partial filter, exactly (`db_indexes.plan`) - and raises HTTP 503
`FIN_INDEX_NOT_READY` when any required index is missing or defined differently. Reads never call it, so browsing, order history,
reports and dashboards keep working. It never creates or changes an index (that stays a deliberate migration step).

The result is cached per process for a short time (positive results longer than negative ones), so the check costs one
`index_information` round per collection per cache period, not per request.
"""
import logging
import time

from fastapi import HTTPException

logger = logging.getLogger("homegenies")

# area -> the unique indexes (db_indexes.SPECS names) its writes rely on for idempotency
AREAS = {
    "ledger": ("vendor_ledger_source_key_unique",),
    "refunds": ("refund_cases_source_key_unique",),
    "wallet": ("wallet_transactions_op_key_unique", "wallets_user_unique"),
    "webhooks": ("webhook_events_event_unique",),
    "settlements": ("settlements_one_open_per_vendor",),
    "stock": ("stock_txns_key_unique",),
    "orders": ("orders_order_number_unique",),
    "withdrawals": ("withdrawal_requests_user_key_unique",),       # Programme 03 (B-022): one request per idempotency key
}
OK_TTL, BAD_TTL = 300.0, 15.0
_cache = {"at": 0.0, "state": None}


def required_indexes() -> dict:
    return {a: list(n) for a, n in AREAS.items()}


async def readiness(force: bool = False) -> dict:
    """{ready, areas: {area: {state: ok|missing|conflict, missing: [...], conflict: [...]}}, checked_at}. Read-only."""
    now = time.monotonic()
    st = _cache["state"]
    if not force and st is not None and now - _cache["at"] < (OK_TTL if st["ready"] else BAD_TTL):
        return st
    import db_indexes
    by_name = {s["name"]: s for s in db_indexes.SPECS}
    needed = {n for names in AREAS.values() for n in names}
    unknown = needed - set(by_name)
    if unknown:                                    # a programming error: an area names an index that is not in SPECS
        raise RuntimeError(f"money_guard names unknown indexes: {sorted(unknown)}")
    # Exact check: the index must exist under ITS OWN NAME with exactly the specified keys and options. A similar index under
    # another name, or the right name with other options (not unique, no / different partial filter), does not count.
    missing, conflict = set(), set()
    try:
        from core import db
        infos = {}
        for n in sorted(needed):
            spec = by_name[n]
            if spec["coll"] not in infos:
                infos[spec["coll"]] = await db[spec["coll"]].index_information()
            info = infos[spec["coll"]]
            if n in info and db_indexes._matches(info[n], spec):
                continue
            if n in info or any(db_indexes._key(i) == db_indexes._key(spec) for i in info.values()):
                conflict.add(n)
            else:
                missing.add(n)
    except Exception as e:                         # the database could not be read: nothing can be proven, so fail closed
        logger.error("money guard: index check failed (%s)", type(e).__name__)
        state = {"ready": False, "error": type(e).__name__,
                 "areas": {a: {"state": "unknown", "missing": [], "conflict": []} for a in AREAS}}
        _cache.update(at=now, state=state)
        return state
    areas = {}
    for a, names in AREAS.items():
        m, c = [n for n in names if n in missing], [n for n in names if n in conflict]
        areas[a] = {"state": "conflict" if c else ("missing" if m else "ok"), "missing": m, "conflict": c}
    state = {"ready": all(v["state"] == "ok" for v in areas.values()), "areas": areas}
    _cache.update(at=now, state=state)
    return state


def reset_cache() -> None:
    _cache.update(at=0.0, state=None)


async def ensure(*areas: str) -> None:
    """Raise 503 unless every index protecting `areas` is present exactly as specified."""
    bad = [a for a in areas if a not in AREAS]
    if bad:
        raise RuntimeError(f"unknown money guard area(s): {bad}")
    st = await readiness()
    failing = [a for a in areas if st["areas"].get(a, {}).get("state") != "ok"]
    if failing:
        logger.error("money write refused: protective indexes not ready for %s (%s)", failing,
                     {a: st["areas"].get(a) for a in failing})
        raise HTTPException(status_code=503, detail={"code": "FIN_INDEX_NOT_READY",
                                                     "message": "This action is temporarily unavailable while the payment records are "
                                                                "being protected. Nothing was changed. Please try again later.",
                                                     "areas": failing})


async def duplicate_report(limit_per_index: int = 50) -> dict:
    """Read-only. For each money-protection index, the business keys held by more than one record and the ids of those records,
    so a person can decide which record is authoritative. Nothing is deleted, merged or changed here, and money writes for an
    affected area stay blocked (its index cannot be created) until the duplicates are resolved. These are business keys
    (ledger / refund / wallet-operation / event / stock keys, order numbers) - no personal data is listed."""
    import db_indexes
    from core import db
    by_name = {s["name"]: s for s in db_indexes.SPECS}
    out = {}
    for area, names in AREAS.items():
        for n in names:
            spec = by_name[n]
            # W5: the same pipeline the migration uses (missing = null, array elements unwound, documents counted once)
            rows = await db[spec["coll"]].aggregate(db_indexes.duplicate_pipeline(spec, with_ids=True)
                                                    + [{"$limit": limit_per_index}]).to_list(limit_per_index)
            if rows:
                out[n] = {"area": area, "collection": spec["coll"],
                          "duplicates": [{"key": r["_id"], "count": len(r["docs"]), "record_ids": sorted(r["ids"])[:20]} for r in rows]}
    return {"clean": not out, "indexes": out}


async def startup_report() -> dict:
    """Called at application startup: one clear log line per unprotected area (no data values)."""
    st = await readiness(force=True)
    if st["ready"]:
        logger.info("money guard: all protective indexes present")
    else:
        for a, v in st["areas"].items():
            if v["state"] != "ok":
                logger.error("money guard: area %s is BLOCKED (%s; missing=%s conflict=%s). Run the index migration "
                             "(scripts/vendor_foundation_migrate.py --apply) after a verified backup.", a, v["state"], v["missing"], v["conflict"])
    return st
