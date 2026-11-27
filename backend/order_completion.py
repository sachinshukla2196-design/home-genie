"""Programme 01 (B-003): ONE post-payment completion step for every payment path.

Every route that turns an order into "paid" (Stripe status poll and webhook, Razorpay verify and webhook, admin UPI confirmation,
admin manual payment, COD collection, COD discrepancy resolution, late-payment revival) writes the durable marker
`completion_due: True` in the SAME atomic update that claims the order as paid, then calls `complete_paid_order`. If the process
dies after the claim, the marker survives and the completion is finished by:
  - the next call on the same payment (a retried webhook / verify / status poll / confirmation re-runs it), or
  - the repair sweep `repair_incomplete_completions` (cron, and scripts/programme01_reconcile.py).

Completion is idempotent step by step - nothing here writes money directly:
  1. invoice number (only when missing, conditional update)
  2. vendor SALE entries (ledger.post_order_collected - unique `sale:<order>:<vendor>` keys)
  3. HomeGenie commission plan + credits (commission.distribute_sale_commissions - plan frozen once per order, crash-safe)
  4. one-time "paid" notifications for online payments (conditional flag; never repeated by a retry)
  5. the marker is cleared and `completion` is stamped.

An order that must not earn (refund owed after a late payment, cancelled, not in a paid state) is skipped and its marker is cleared
with the reason. An order refunded BEFORE its commission plan ever existed is not given a fresh full plan (that would credit
commission on refunded goods): it is flagged `completion_blocked` for finance and reported, never guessed.
"""
import logging
from typing import Optional

from core import db, now_iso, next_sequence, create_notification, log_audit

logger = logging.getLogger("homegenies")

PAID = ("paid", "partially_refunded")


async def _ensure_invoice(order: dict) -> Optional[str]:
    if order.get("invoice_number"):
        return order["invoice_number"]
    inv = await next_sequence("invoice", "INV", 6)
    await db.orders.update_one({"id": order["id"], "$or": [{"invoice_number": None}, {"invoice_number": {"$exists": False}}]},
                               {"$set": {"invoice_number": inv}})
    fresh = await db.orders.find_one({"id": order["id"]}, {"_id": 0, "invoice_number": 1})
    return (fresh or {}).get("invoice_number")


async def _notify_once(order: dict, invoice_number: Optional[str]) -> None:
    claim = await db.orders.update_one({"id": order["id"], "paid_notified": {"$ne": True}}, {"$set": {"paid_notified": True}})
    if claim.modified_count != 1:
        return
    from core import notify_order_vendors
    await notify_order_vendors(order, "New order", f"New paid order {order.get('order_number')}: please accept and pack it.")
    await create_notification(order["user_id"], "payment_success", "Payment successful",
                              f"Payment received for order {order['order_number']}. Invoice {invoice_number} generated.",
                              "भुगतान सफल",
                              f"ऑर्डर {order['order_number']} का भुगतान प्राप्त हुआ। इनवॉइस {invoice_number} बन गया।")


async def _finish(order_id: str, outcome: str, source: str, extra: dict = None) -> None:
    await db.orders.update_one({"id": order_id}, {"$unset": {"completion_due": ""},
                                                  "$set": {"completion": {"outcome": outcome, "source": source, "at": now_iso(), **(extra or {})}}})


async def complete_paid_order(order_or_id, request=None, source: str = "", notify: Optional[bool] = None,
                              dry_run: bool = False) -> dict:
    """Finish everything that follows a confirmed payment. Safe to call any number of times, concurrently, from any path.
    Returns {"outcome": completed | skipped | blocked | would_complete, ...}."""
    oid = order_or_id if isinstance(order_or_id, str) else order_or_id["id"]
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    if not order:
        return {"outcome": "skipped", "reason": "order_missing"}
    if order.get("late_payment_due"):
        # Programme 03-B: a payment landed on a cancelled order and its outcome (restore or refund) is not decided yet. Wait -
        # skipping now would clear `completion_due` and lose the sales / commission of an order about to be restored.
        return {"outcome": "skipped", "reason": "late_payment_pending"}
    why = None
    if order.get("needs_refund"):
        why = "refund_owed"
    elif order.get("status") == "cancelled":
        why = "cancelled"
    elif order.get("payment_status") not in PAID:
        why = f"payment_{order.get('payment_status')}"
    if why:
        if not dry_run and order.get("completion_due"):
            await _finish(oid, "skipped", source, {"reason": why})
        return {"outcome": "skipped", "reason": why}
    plan = await db.commission_plans.find_one({"_id": oid}, {"_id": 1})
    refunded = int(order.get("refunded_paise") or 0) > 0 or order.get("payment_status") == "partially_refunded"
    seller = order.get("seller_user_id") and order.get("seller_user_id") != order.get("user_id")
    from cod_rules import collection_is_proven
    would_earn = seller and (order.get("payment_method") != "cod" or collection_is_proven(order))
    if refunded and plan is None and would_earn and not order.get("commissions_paid"):
        if not dry_run:
            await db.orders.update_one({"id": oid}, {"$set": {"completion_blocked": "refunded_before_commission_plan"}})
            await _finish(oid, "blocked", source, {"reason": "refunded_before_commission_plan"})
            await log_audit(None, "order_completion_blocked", "order", oid, new_value={"reason": "refunded_before_commission_plan"})
        return {"outcome": "blocked", "reason": "refunded_before_commission_plan"}
    if dry_run:
        return {"outcome": "would_complete", "has_plan": plan is not None}
    from money_guard import ensure as _money_guard    # B-004: nothing is written unless the duplicate protections exist;
    await _money_guard("ledger", "wallet")            # the marker stays, so the sweep finishes it once they do
    invoice = await _ensure_invoice(order)
    order = await db.orders.find_one({"id": oid}, {"_id": 0})
    from ledger import post_order_collected
    sales = await post_order_collected(order)
    # the buyer's id is always known from the order, so a self-attributed sale is refused even if the user record is gone
    buyer = await db.users.find_one({"id": order.get("user_id")}, {"_id": 0}) or {"id": order.get("user_id")}
    from commission import distribute_sale_commissions
    comm = await distribute_sale_commissions(order, buyer, request)
    if notify if notify is not None else order.get("payment_method") != "cod":
        await _notify_once(order, invoice)
    await _finish(oid, "completed", source, {"sales_posted": sales, "commission": (comm or {}).get("reason") or "credited"})
    return {"outcome": "completed", "sales_posted": sales, "commissions": comm, "invoice_number": invoice}


async def repair_incomplete_completions(dry_run: bool = False, max_seconds: Optional[float] = None, batch: int = 200) -> dict:
    """Repair sweep: every order whose payment was claimed but whose completion did not finish (`completion_due`). Keyset
    pagination with a durable checkpoint (sweeps.run_sweep), per-order error isolation, dry-run support."""
    from sweeps import run_sweep

    async def handle(o, dry):
        res = await complete_paid_order(o["id"], source="repair_sweep", dry_run=dry)
        return {"completed": "updated", "would_complete": "eligible", "blocked": "blocked"}.get(res["outcome"], "skipped")
    return await run_sweep("completion_repair", "orders", {"completion_due": True}, handle, dry_run=dry_run,
                           max_seconds=max_seconds, batch=batch, projection={"_id": 0, "id": 1})


async def completion_audit(limit_report: int = 200) -> dict:
    """Report-only diagnostic (never writes): paid orders whose post-payment state disagrees with their payment state."""
    out = {"completion_due": await db.orders.count_documents({"completion_due": True}),
           "completion_blocked": await db.orders.count_documents({"completion_blocked": {"$exists": True}}),
           "paid_without_plan": [], "paid_vendor_groups_without_sale": []}
    q = {"payment_status": {"$in": list(PAID)}, "needs_refund": {"$ne": True}, "status": {"$ne": "cancelled"}}
    async for o in db.orders.find(q, {"_id": 0, "id": 1, "order_number": 1, "seller_user_id": 1, "user_id": 1, "payment_method": 1,
                                      "commissions_paid": 1, "fulfilments": 1, "cod_collection": 1, "payment_status": 1}).sort("id", 1):
        seller = o.get("seller_user_id") and o.get("seller_user_id") != o.get("user_id")
        if seller and not o.get("commissions_paid") and len(out["paid_without_plan"]) < limit_report:
            from cod_rules import collection_is_proven
            if o.get("payment_method") != "cod" or collection_is_proven(o):
                if not await db.commission_plans.find_one({"_id": o["id"]}, {"_id": 1}):
                    out["paid_without_plan"].append(o.get("order_number") or o["id"])
        for f in o.get("fulfilments") or []:
            if f.get("status") in ("rejected", "cancelled") or len(out["paid_vendor_groups_without_sale"]) >= limit_report:
                continue
            if not await db.vendor_ledger.find_one({"source_key": f"sale:{o['id']}:{f['vendor_id']}"}, {"_id": 1}):
                out["paid_vendor_groups_without_sale"].append(f"{o.get('order_number') or o['id']}:{f['vendor_id']}")
    return out
