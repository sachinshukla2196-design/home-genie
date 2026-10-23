"""Vendor ledger: immutable, linked, idempotent financial records in exact integer paise.

RULES
- Entries are NEVER edited or deleted. A correction is a new entry that points at the one it reverses.
- Every entry has a unique `source_key`; posting the same business event twice is a no-op (payment callbacks, retries,
  recovery and concurrent requests cannot create duplicates).
- The ledger is always rebuildable from the order records: `reconcile_ledger()` posts anything that is missing, so a crash
  between "payment confirmed" and "ledger entry written" is repaired by the next sweep.
- Vendor money is kept apart from HomeGenie reward wallets and customer balances (separate collection, separate code).

WHAT IS RECORDED (and what is deliberately NOT)
- SALE_COLLECTED : value of the vendor's own lines once the customer's payment is confirmed (online payment captured or
                   COD cash confirmed). Item value only; taxes/fees are not attributed to the vendor.
- SALE_REVERSAL  : the vendor rejected/cancelled that order before dispatch, so the sale is taken back.
- REFUND         : the vendor's share of a customer refund (provisional basis: vendor item value / order total).
- ADJUSTMENT     : admin correction with a mandatory reason.
- SETTLEMENT_PAID: money paid out to the vendor (negative), recorded only when an admin marks a settlement paid.
- Commissions, platform fees, deductions and the settlement schedule are NOT applied here: those policies are not approved.
  Until they are, `vendor payable` = sales - reversals - refunds +/- adjustments, clearly labelled provisional.
"""
from typing import Optional

from pymongo.errors import DuplicateKeyError

from core import db, now_iso, new_id
from money import paise_of, mul_ratio, paise_to_float

SALE = "SALE_COLLECTED"
SALE_REVERSAL = "SALE_REVERSAL"
REFUND = "REFUND"
ADJUSTMENT = "ADJUSTMENT"
SETTLEMENT_PAID = "SETTLEMENT_PAID"
TYPES = (SALE, SALE_REVERSAL, REFUND, ADJUSTMENT, SETTLEMENT_PAID)

SALE_BLOCKING_FULFILMENT = {"rejected", "cancelled"}      # no sale for a vendor who did not supply the goods
HELD_PAYMENT_STATUSES = {"cod_discrepancy"}


def vendor_lines_paise(order: dict, vendor_id: str) -> int:
    return sum(paise_of(li, "total_paise", "total") for li in order.get("items", []) if li.get("vendor_id") == vendor_id)


async def post_entry(vendor_id: str, etype: str, amount_paise: int, source_key: str, *, order_id: Optional[str] = None,
                     actor: str = "system", reason: str = "", reverses: Optional[str] = None, meta: Optional[dict] = None):
    """Append one entry. Returns (entry, created). Posting an existing `source_key` returns the original, unchanged."""
    assert etype in TYPES and isinstance(amount_paise, int) and amount_paise != 0, (etype, amount_paise)
    now = now_iso()
    e = {"id": new_id(), "vendor_id": vendor_id, "type": etype, "amount_paise": amount_paise,
         "amount": paise_to_float(amount_paise), "currency": "INR", "order_id": order_id, "source_key": source_key,
         "reverses": reverses, "reason": reason, "actor": actor, "meta": meta or {}, "status": "posted",
         "posted_at": now, "effective_at": now}
    try:
        await db.vendor_ledger.insert_one(dict(e))
        return e, True
    except DuplicateKeyError:
        return await db.vendor_ledger.find_one({"source_key": source_key}, {"_id": 0}), False


async def _entries(vendor_id: str, order_id: str, etype: str) -> int:
    rows = await db.vendor_ledger.find({"vendor_id": vendor_id, "order_id": order_id, "type": etype}, {"_id": 0, "amount_paise": 1}).to_list(1000)
    return sum(r["amount_paise"] for r in rows)


def _sale_eligible(order: dict, fulfilment: dict) -> bool:
    return (order.get("payment_status") in ("paid", "partially_refunded", "refunded") and not order.get("needs_refund")
            and fulfilment.get("status") not in SALE_BLOCKING_FULFILMENT)


async def post_order_collected(order: dict, scale: Optional[tuple] = None) -> int:
    """Post the SALE entry for every vendor on a paid order. Idempotent. Returns how many entries were created.
    `scale=(collected_paise, expected_paise)` is used when an admin accepted a short COD collection."""
    n = 0
    if order.get("needs_refund") or order.get("payment_status") not in ("paid", "partially_refunded", "refunded"):
        return 0
    for f in order.get("fulfilments", []):
        if not _sale_eligible(order, f):
            continue
        amt = vendor_lines_paise(order, f["vendor_id"])
        sc = scale or ((order["cod_collected_paise"], paise_of(order, "total_paise", "total")) if isinstance(order.get("cod_collected_paise"), int)
                       and order.get("cod_collected_paise") != paise_of(order, "total_paise", "total") else None)
        if sc:
            amt = mul_ratio(amt, sc[0], sc[1])
        if amt > 0:
            _, created = await post_entry(f["vendor_id"], SALE, amt, f"sale:{order['id']}:{f['vendor_id']}", order_id=order["id"],
                                          meta={"order_number": order.get("order_number"), "payment_method": order.get("payment_method")})
            n += 1 if created else 0
    return n


async def post_sale_reversal(order: dict, vendor_id: str) -> bool:
    """The vendor rejected/cancelled a paid order: take back the sale that was recorded for it. Idempotent."""
    sale = await db.vendor_ledger.find_one({"source_key": f"sale:{order['id']}:{vendor_id}"}, {"_id": 0})
    if not sale:
        return False
    _, created = await post_entry(vendor_id, SALE_REVERSAL, -sale["amount_paise"], f"salerev:{order['id']}:{vendor_id}",
                                  order_id=order["id"], reverses=sale["id"], reason="Vendor did not fulfil the order")
    return created


async def post_refund_shares(order: dict, refund: dict) -> int:
    """Post each vendor's share of one customer refund event. The refund that closes the order takes exactly the remainder,
    so the vendor's refunds always add up to the sale to the paisa. Idempotent per (refund event, vendor)."""
    n = 0
    total_p = paise_of(order, "total_paise", "total")
    amt_p = refund["amount_paise"] if isinstance(refund.get("amount_paise"), int) else paise_of(refund, "amount_paise", "amount")
    closes = bool(order.get("financials_reversed")) and refund.get("closes_order", False)
    only = refund.get("vendor_id")        # a refund for ONE vendor's returned goods is theirs entirely; otherwise split by value
    for f in order.get("fulfilments", []):
        vid = f["vendor_id"]
        if only and vid != only:
            continue
        sale = await _entries(vid, order["id"], SALE)
        if sale <= 0:
            continue
        base = sale + await _entries(vid, order["id"], SALE_REVERSAL)          # what is still attributable to the vendor
        prior = -await _entries(vid, order["id"], REFUND)
        share = amt_p if only else (mul_ratio(base, amt_p, total_p) if total_p else 0)
        if closes and not only:
            share = base - prior
        share = max(min(share, base - prior), 0)
        if share > 0:
            _, created = await post_entry(vid, REFUND, -share, f"refund:{refund['id']}:{vid}", order_id=order["id"],
                                          meta={"refund_event": refund["id"], "basis": "vendor item value / order total (provisional)"})
            n += 1 if created else 0
    return n


async def reconcile_ledger(limit: int = 500) -> dict:
    """Repair sweep: derive every missing entry from the order records. Safe to run any time, any number of times."""
    sales = reversals = refunds = 0
    q = {"payment_status": {"$in": ["paid", "partially_refunded", "refunded"]}, "needs_refund": {"$ne": True},
         "fulfilments.0": {"$exists": True}}
    async for o in db.orders.find(q, {"_id": 0}).sort("paid_at", 1).limit(limit):
        sales += await post_order_collected(o)
        for f in o.get("fulfilments", []):
            if f.get("status") in SALE_BLOCKING_FULFILMENT and await post_sale_reversal(o, f["vendor_id"]):
                reversals += 1
        async for r in db.order_refunds.find({"order_id": o["id"], "status": "completed"}, {"_id": 0}).sort("created_at", 1):
            refunds += await post_refund_shares(o, r)
    return {"sales": sales, "reversals": reversals, "refunds": refunds}


async def balances(vendor_id: str) -> dict:
    """Vendor money split by what each number means. All values are integer paise."""
    agg = await db.vendor_ledger.aggregate([{"$match": {"vendor_id": vendor_id}},
                                            {"$group": {"_id": "$type", "n": {"$sum": "$amount_paise"}, "c": {"$sum": 1}}}]).to_list(20)
    by = {r["_id"]: r["n"] for r in agg}
    sales, rev, ref, adj, paid = (by.get(SALE, 0), by.get(SALE_REVERSAL, 0), by.get(REFUND, 0), by.get(ADJUSTMENT, 0), by.get(SETTLEMENT_PAID, 0))
    payable_before_settlements = sales + rev + ref + adj
    open_settle = await db.settlements.aggregate([{"$match": {"vendor_id": vendor_id, "status": {"$in": ["requested", "approved"]}}},
                                                  {"$group": {"_id": None, "n": {"$sum": "$amount_paise"}}}]).to_list(1)
    under_settlement = open_settle[0]["n"] if open_settle else 0
    settled = -paid
    return {"currency": "INR", "eligible_sales_paise": sales, "sale_reversals_paise": rev, "refunds_paise": ref,
            "adjustments_paise": adj, "vendor_payable_paise": payable_before_settlements,
            "settled_paise": settled, "settlement_in_progress_paise": under_settlement,
            "pending_settlement_paise": payable_before_settlements - settled,
            "available_for_settlement_paise": payable_before_settlements - settled - under_settlement,
            "provisional": True,
            "provisional_note": "Before commissions, fees and deductions: those policies are not approved yet."}
