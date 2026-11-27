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
COMMISSION = "COMMISSION"          # negative when charged on a sale, positive when returned for an unfulfilled order
TYPES = (SALE, SALE_REVERSAL, REFUND, ADJUSTMENT, SETTLEMENT_PAID, COMMISSION)

SALE_BLOCKING_FULFILMENT = {"rejected", "cancelled"}      # no sale for a vendor who did not supply the goods
HELD_PAYMENT_STATUSES = {"cod_discrepancy"}


def vendor_lines_paise(order: dict, vendor_id: str) -> int:
    return sum(paise_of(li, "total_paise", "total") for li in order.get("items", []) if li.get("vendor_id") == vendor_id)


async def post_entry(vendor_id: str, etype: str, amount_paise: int, source_key: str, *, order_id: Optional[str] = None,
                     actor: str = "system", reason: str = "", reverses: Optional[str] = None, meta: Optional[dict] = None):
    """Append one entry. Returns (entry, created). Posting an existing `source_key` returns the original, unchanged."""
    assert etype in TYPES and isinstance(amount_paise, int) and amount_paise != 0, (etype, amount_paise)
    from money_guard import ensure as _money_guard          # Programme 01 (B-004): fail closed without the unique indexes
    await _money_guard("ledger")
    now = now_iso()
    e = {"id": new_id(), "vendor_id": vendor_id, "type": etype, "amount_paise": amount_paise,
         "amount": paise_to_float(amount_paise), "currency": "INR", "order_id": order_id, "source_key": source_key,
         "reverses": reverses, "reason": reason, "actor": actor, "meta": meta or {}, "status": "posted",
         "posted_at": now, "effective_at": now}
    # Programme 01 (B-005): repair passes mostly meet entries that already exist; look the key up first (one round trip).
    # The unique index on source_key still decides any race between two writers.
    existing = await db.vendor_ledger.find_one({"source_key": source_key}, {"_id": 0})
    if existing:
        return existing, False
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
        # a COD order accepted short: scale each sale by collected / expected (expected excludes unsupplied goods - C-8)
        exp_p = order["cod_expected_paise"] if isinstance(order.get("cod_expected_paise"), int) else paise_of(order, "total_paise", "total")
        sc = scale or ((order["cod_collected_paise"], exp_p) if isinstance(order.get("cod_collected_paise"), int)
                       and order.get("cod_collected_paise") != exp_p else None)
        if sc:
            amt = mul_ratio(amt, sc[0], sc[1])
        if amt > 0:
            _, created = await post_entry(f["vendor_id"], SALE, amt, f"sale:{order['id']}:{f['vendor_id']}", order_id=order["id"],
                                          meta={"order_number": order.get("order_number"), "payment_method": order.get("payment_method")})
            n += 1 if created else 0
            await post_commission(order, f["vendor_id"], amt)
    return n


async def post_commission(order: dict, vendor_id: str, sale_paise: int) -> int:
    """Charge the commission of the approved agreement in force on the order date. The agreement version is stored on the entry,
    so later agreements never change it. No approved agreement on that date means no commission."""
    from commercial_terms import effective_agreement, commission_for
    on = (order.get("paid_at") or order.get("created_at") or "")[:10]
    agreement = await effective_agreement(vendor_id, on) if on else None
    if not agreement:
        return 0
    charge = commission_for(agreement, sale_paise)
    if charge <= 0:
        return 0
    _, created = await post_entry(vendor_id, COMMISSION, -charge, f"comm:{order['id']}:{vendor_id}", order_id=order["id"],
                                  meta={"agreement_id": agreement["id"], "version": agreement["version"], "commission_pct": agreement["commission_pct"],
                                        "fixed_fee_paise": agreement["fixed_fee_paise"], "sale_paise": sale_paise})
    return 1 if created else 0


async def post_sale_reversal(order: dict, vendor_id: str) -> bool:
    """The vendor rejected/cancelled a paid order: take back the sale that was recorded for it. Idempotent."""
    sale = await db.vendor_ledger.find_one({"source_key": f"sale:{order['id']}:{vendor_id}"}, {"_id": 0})
    if not sale:
        return False
    # Batch 12 (audit C-6): take back only what is still attributed to the vendor. Refund shares already posted for this order
    # reduced it; reversing the full sale on top of them would leave the vendor negative on goods it never supplied.
    refunded = max(-await _entries(vendor_id, order["id"], REFUND), 0)
    remaining = sale["amount_paise"] - refunded
    created = False
    if remaining > 0:
        _, created = await post_entry(vendor_id, SALE_REVERSAL, -remaining, f"salerev:{order['id']}:{vendor_id}",
                                      order_id=order["id"], reverses=sale["id"], reason="Vendor did not fulfil the order",
                                      meta={"sale_paise": sale["amount_paise"], "already_refunded_paise": refunded})
    # no sale, no commission: return what was charged for this order (idempotent by its own key)
    charged = -sum(r["amount_paise"] for r in await db.vendor_ledger.find({"vendor_id": vendor_id, "order_id": order["id"], "type": COMMISSION},
                                                                          {"_id": 0, "amount_paise": 1}).to_list(1000))
    if charged > 0:
        await post_entry(vendor_id, COMMISSION, charged, f"commrev:{order['id']}:{vendor_id}", order_id=order["id"],
                         reason="Commission returned: vendor did not fulfil the order")
    return created


async def post_refund_shares(order: dict, refund: dict) -> int:
    """Post each vendor's share of one customer refund event. The refund that closes the order takes exactly the remainder,
    so the vendor's refunds always add up to the sale to the paisa. Idempotent per (refund event, vendor)."""
    n = 0
    from cod_rules import refund_basis_paise
    total_p = refund_basis_paise(order, paise_of(order, "total_paise", "total"))     # goods value the sale shares (audit C-11)
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


async def _missing_entries(o: dict) -> int:
    """Read-only (dry run): how many ledger entries reconcile_ledger would post for this order."""
    n = 0
    for f in o.get("fulfilments", []):
        vid = f["vendor_id"]
        has_sale = await db.vendor_ledger.find_one({"source_key": f"sale:{o['id']}:{vid}"}, {"_id": 1})
        if _sale_eligible(o, f) and not has_sale and vendor_lines_paise(o, vid) > 0:
            n += 1
        if f.get("status") in SALE_BLOCKING_FULFILMENT and has_sale and \
                not await db.vendor_ledger.find_one({"source_key": f"salerev:{o['id']}:{vid}"}, {"_id": 1}):
            n += 1
    async for r in db.order_refunds.find({"order_id": o["id"], "status": "completed"}, {"_id": 0, "id": 1, "vendor_id": 1}):
        for f in o.get("fulfilments", []):
            if r.get("vendor_id") and r["vendor_id"] != f["vendor_id"]:
                continue
            if await db.vendor_ledger.find_one({"source_key": f"sale:{o['id']}:{f['vendor_id']}"}, {"_id": 1}) and \
                    not await db.vendor_ledger.find_one({"source_key": f"refund:{r['id']}:{f['vendor_id']}"}, {"_id": 1}):
                n += 1
    return n


async def reconcile_ledger(limit: int = 500, dry_run: bool = False, max_seconds: Optional[float] = None) -> dict:
    """Repair sweep: derive every missing entry from the order records. Safe to run any time, any number of times.

    Programme 01 (B-005): it used to read only the 500 oldest paid orders and stop. It now walks EVERY paid order with vendor
    goods in pages of `limit`, by order id, resuming from its checkpoint after an interruption (sweeps.run_sweep). Entries are
    only ever ADDED under their unique business key; an existing entry is never changed or deleted. `dry_run` writes nothing
    and counts the orders that would get entries."""
    from sweeps import run_sweep
    tot = {"sales": 0, "reversals": 0, "refunds": 0}
    q = {"payment_status": {"$in": ["paid", "partially_refunded", "refunded"]}, "needs_refund": {"$ne": True},
         "fulfilments.0": {"$exists": True}}

    async def handle(o, dry):
        if dry:
            return "eligible" if await _missing_entries(o) else "skipped"
        before = dict(tot)
        tot["sales"] += await post_order_collected(o)
        for f in o.get("fulfilments", []):
            if f.get("status") in SALE_BLOCKING_FULFILMENT and await post_sale_reversal(o, f["vendor_id"]):
                tot["reversals"] += 1
        async for r in db.order_refunds.find({"order_id": o["id"], "status": "completed"}, {"_id": 0}).sort("created_at", 1):
            tot["refunds"] += await post_refund_shares(o, r)
        return "updated" if tot != before else "skipped"
    sweep = await run_sweep("ledger_reconcile", "orders", q, handle, batch=limit, dry_run=dry_run, max_seconds=max_seconds,
                            projection={"_id": 0})
    return {**tot, "sweep": sweep}


async def _eligible_paise(vendor_id: str):
    """Sum of ledger entries that may be settled now (decision 3), and how many orders are still held."""
    d = await eligible_detail(vendor_id)
    return d["eligible_paise"], d["held_orders"]


async def eligible_detail(vendor_id: str) -> dict:
    """The same decision as `_eligible_paise`, with its composition: the net ledger amount of every order that may be settled now,
    of every order still held (with the reason code), and of the entries with no order. Integer paise. Read-only.
    Programme 03 (B-023): the settlement snapshot records this as evidence of what the settlement was based on."""
    from eligibility import payout_block, return_window_days
    rows = await db.vendor_ledger.find({"vendor_id": vendor_id}, {"_id": 0, "amount_paise": 1, "order_id": 1}).to_list(None)
    by_order, free = {}, 0
    for r in rows:
        if r.get("order_id"):
            by_order[r["order_id"]] = by_order.get(r["order_id"], 0) + r["amount_paise"]
        else:
            free += r["amount_paise"]
    out = {"eligible_paise": free, "held_orders": 0, "non_order_paise": free, "eligible": [], "held": []}
    if not by_order:
        return out
    window = await return_window_days()
    orders = {o["id"]: o for o in await db.orders.find({"id": {"$in": list(by_order)}}, {"_id": 0}).to_list(None)}
    for oid, amt in sorted(by_order.items()):
        o = orders.get(oid)
        reason = await payout_block(o, window=window, vendor_id=vendor_id)
        item = {"order_id": oid, "order_number": (o or {}).get("order_number"), "amount_paise": amt}
        if reason is None:
            out["eligible_paise"] += amt
            out["eligible"].append(item)
        elif amt:
            out["held_orders"] += 1
            out["held"].append({**item, "reason": reason})
    return out


async def balances(vendor_id: str) -> dict:
    """Vendor money split by what each number means. All values are integer paise."""
    agg = await db.vendor_ledger.aggregate([{"$match": {"vendor_id": vendor_id}},
                                            {"$group": {"_id": "$type", "n": {"$sum": "$amount_paise"}, "c": {"$sum": 1}}}]).to_list(20)
    by = {r["_id"]: r["n"] for r in agg}
    sales, rev, ref, adj, paid = (by.get(SALE, 0), by.get(SALE_REVERSAL, 0), by.get(REFUND, 0), by.get(ADJUSTMENT, 0), by.get(SETTLEMENT_PAID, 0))
    comm = by.get(COMMISSION, 0)
    payable_before_settlements = sales + rev + ref + adj + comm
    open_settle = await db.settlements.aggregate([{"$match": {"vendor_id": vendor_id, "status": {"$in": ["requested", "approved"]}}},
                                                  {"$group": {"_id": None, "n": {"$sum": "$amount_paise"}}}]).to_list(1)
    under_settlement = open_settle[0]["n"] if open_settle else 0
    eligible, held_orders = await _eligible_paise(vendor_id)
    settled = -paid
    return {"currency": "INR", "eligible_sales_paise": sales, "sale_reversals_paise": rev, "refunds_paise": ref,
            "adjustments_paise": adj, "commissions_paise": comm, "vendor_payable_paise": payable_before_settlements,
            "settled_paise": settled, "settlement_in_progress_paise": under_settlement,
            "pending_settlement_paise": payable_before_settlements - settled,
            # Decision 3: only money from orders that are delivered, past the return window and free of open returns, refunds or
            # payment problems can be settled. Entries on held orders wait; entries with no order (adjustments, payouts) count.
            "available_for_settlement_paise": min(payable_before_settlements - settled, eligible) - under_settlement,
            "awaiting_eligibility_paise": max(payable_before_settlements - settled - eligible, 0),
            "held_orders": held_orders,
            "provisional": False,
            "provisional_note": "Platform commission under the approved agreement is already deducted. Money from an order becomes "
                                "available after delivery and the return window, with no open return, refund or payment issue."}
