"""Safe migration of stored rupee floats to exact integer paise.

PRINCIPLES
- ADDITIVE ONLY. For every money field `X` this adds `X_paise` (an integer). The original float field and every other
  field are never modified, so financial history is never rewritten and the migration can be rolled back by simply
  ignoring (or unsetting) the new fields.
- IDEMPOTENT. A field that already has its paise twin is skipped; running it again changes nothing.
- VERIFIED. `verify()` recomputes every total two independent ways (exact Decimal sum of the original floats, and the sum
  of the new paise fields) and reports any record whose float was not a clean 2-decimal amount.
- DRY-RUN FIRST. `plan()` changes nothing; `apply()` is only run explicitly (see scripts/migrate_money_paise.py).

Records created by the current code already carry paise fields; this brings OLDER records to the same shape.
"""
from decimal import Decimal
from typing import Optional

from money import to_paise, paise_to_float

# collection -> list of (float_field, paise_field); a field may be a dotted path into the document root only
FIELDS = {
    "orders": [("subtotal", "subtotal_paise"), ("gst_amount", "gst_paise"), ("total", "total_paise"),
               ("cod_fee", "cod_fee_paise"), ("refunded_amount", "refunded_paise")],
    "commissions": [("amount", "amount_paise"), ("base_amount", "base_paise"), ("reversed_amount", "reversed_paise")],
    "wallet_transactions": [("amount", "amount_paise")],
    "wallets": [("available_balance", "available_balance_paise"), ("pending_balance", "pending_balance_paise"),
                ("total_earned", "total_earned_paise"), ("total_withdrawn", "total_withdrawn_paise")],
    "withdrawal_requests": [("amount", "amount_paise")],
    "order_refunds": [("amount", "amount_paise")],
}
# order line items carry price/total
ITEM_FIELDS = [("price", "price_paise"), ("total", "total_paise")]


def _is_num(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)


def _exact(v) -> Decimal:
    return Decimal(str(v))


async def _scan(db, collection: str):
    """Yield (doc_ref, float_field, paise_field, float_value, existing_paise_or_None) for every money field."""
    proj = {"_id": 1, "id": 1, "items": 1}
    for f, p in FIELDS[collection]:
        proj[f] = 1
        proj[p] = 1
    async for d in db[collection].find({}, proj):
        ref = d.get("id") or d["_id"]
        for f, p in FIELDS[collection]:
            if _is_num(d.get(f)):
                yield ref, f, p, d[f], (d.get(p) if isinstance(d.get(p), int) else None)
        if collection == "orders":
            for i, it in enumerate(d.get("items") or []):
                for f, p in ITEM_FIELDS:
                    if _is_num(it.get(f)):
                        yield ref, f"items.{i}.{f}", f"items.{i}.{p}", it[f], (it.get(p) if isinstance(it.get(p), int) else None)


async def plan(db) -> dict:
    """Read-only: how many fields would be added, per collection, and which values are not clean 2-decimal amounts."""
    out = {}
    for coll in FIELDS:
        todo = total = 0
        unclean = []
        async for ref, f, p, v, pv in _scan(db, coll):
            total += 1
            if pv is None:
                todo += 1
                if _exact(v) != _exact(paise_to_float(to_paise(v))):
                    unclean.append({"id": str(ref), "field": f, "value": v})
        out[coll] = {"money_fields": total, "to_add": todo, "unclean_count": len(unclean), "unclean_values": unclean[:50]}
    return out


async def apply(db, batch_note: str = "") -> dict:
    """Add the missing paise fields. Never changes an existing field. Returns counts and records the run."""
    added = {}
    for coll in FIELDS:
        n = 0
        async for ref, f, p, v, pv in _scan(db, coll):
            if pv is not None:
                continue
            filt = {"_id": ref} if not isinstance(ref, str) else ({"id": ref} if coll != "order_refunds" else {"$or": [{"id": ref}, {"_id": ref}]})
            filt[p] = {"$exists": False}          # never overwrite an existing exact value
            res = await db[coll].update_one(filt, {"$set": {p: to_paise(v)}})
            n += res.modified_count
        added[coll] = n
    from core import now_iso, new_id
    await db.money_migrations.insert_one({"id": new_id(), "kind": "money_paise_backfill", "at": now_iso(), "added": added, "note": batch_note})
    return added


async def verify(db) -> dict:
    """Two-way check. For every (collection, field): exact Decimal sum of the ORIGINAL floats vs sum of paise / 100.
    `ok` is True when every field has its paise twin and the totals match to the paisa (fields whose original float was not
    a clean 2-decimal amount are counted separately: their paise value is the half-up rounding, the float is untouched)."""
    report, all_ok = {}, True
    for coll in FIELDS:
        sums = {}
        async for ref, f, p, v, pv in _scan(db, coll):
            key = "items." + f.split(".")[-1] if f.startswith("items.") else f
            s = sums.setdefault(key, {"float_sum": Decimal(0), "paise_sum": 0, "missing": 0, "unclean": 0})
            s["float_sum"] += _exact(v)
            if pv is None:
                s["missing"] += 1
            else:
                s["paise_sum"] += pv
            if _exact(v) != _exact(paise_to_float(to_paise(v))):
                s["unclean"] += 1
        for key, s in sums.items():
            ok = s["missing"] == 0 and (s["unclean"] > 0 or Decimal(s["paise_sum"]) / 100 == s["float_sum"])
            all_ok &= ok
            report[f"{coll}.{key}"] = {"float_sum": str(s["float_sum"]), "paise_sum_rupees": str(Decimal(s["paise_sum"]) / 100),
                                       "missing_paise": s["missing"], "unclean_values": s["unclean"], "ok": ok}
    return {"ok": all_ok, "fields": report}
