"""Order stock engine: durable, idempotent stock reservation / release with crash recovery.

Business rules (owner-approved, unchanged):
- Stock is reserved when an order is created. COD orders keep their reservation once created.
- An ONLINE order whose payment is still pending after PENDING_ONLINE_TTL_MINUTES (15) is cancelled ("payment_timeout")
  and its stock returned. Orders with a UPI claim awaiting admin verification are never expired.
- A confirmed cancellation restocks only goods that have not left; returned goods restock only after inspection.

How crashes are survived WITHOUT MongoDB transactions (the local database is a standalone server):
- Every stock movement is a journaled transaction in `stock_txns` (unique `key` => creating it twice is a no-op).
- A transaction's effect on one product line is ONE atomic update on the product document that both changes the stock
  counter and writes an idempotency marker (`stock_ops.<marker>`) in the same document. Replaying a line can therefore
  never apply it twice, whether the replay is a retry, a concurrent request, or crash recovery.
- Commit vs rollback is decided exactly once by a conditional status update (the "arbiter"). A rollback poisons lines that
  were not applied yet, so a late concurrent runner cannot apply them afterwards.
- Anything interrupted is finished by `run_recovery()` (cron + opportunistic): stale pending/rolling_back transactions are
  driven to a terminal state, committed ones are finalised (movement log, per-line flags), and durable "restock intents"
  recorded on the order are replayed. Failure-injection tests exercise a crash at every step.
- Recovery only touches work older than STOCK_RECOVERY_MIN_AGE_SECONDS (default 120 s, longer than the 60 s function limit)
  so it never competes with a request that is still running.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from pymongo.errors import DuplicateKeyError

from core import db, now_iso, new_id, create_notification, log_audit

PENDING_ONLINE_TTL_MINUTES = int(os.environ.get("PENDING_PAYMENT_TTL_MINUTES", "15"))
# Programme 01 (B-006): an order whose payment the gateway has already reported (a payment id is recorded on its attempt - the
# customer paid, capture or confirmation is still on its way) keeps its stock this much longer before it may expire. A payment
# that still arrives after expiry is handled by the existing late-payment rule (revive if the stock is there, else refund owed).
PAYMENT_IN_PROGRESS_GRACE_MINUTES = int(os.environ.get("PAYMENT_IN_PROGRESS_GRACE_MINUTES", "60"))
RECOVERY_MIN_AGE_S = int(os.environ.get("STOCK_RECOVERY_MIN_AGE_SECONDS", "120"))
SYSTEM = {"id": "system", "email": None, "role": "system"}
EXPIRY_REASON = "payment_timeout"
PRE_DISPATCH = {"new", "accepted", "packed"}   # goods are still with the vendor / warehouse
NOT_SHIPPED_ORDER_STATUS = {"shipped", "delivered"}

# Test hook: set to a callable(point, **ctx) that raises to simulate a crash at that point. None in production.
_FAULT = None


def _fault(point: str, **ctx):
    if _FAULT is not None:
        _FAULT(point, **ctx)


def _cutoff_iso(now: Optional[datetime] = None) -> str:
    return ((now or datetime.now(timezone.utc)) - timedelta(minutes=PENDING_ONLINE_TTL_MINUTES)).isoformat()


def _age_cutoff(seconds: Optional[int] = None) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=RECOVERY_MIN_AGE_S if seconds is None else seconds)).isoformat()


# ---------------------------------------------------------------------------------------------- line primitive
def _mk(prefix: str, txn_id: str, i: int) -> str:
    return f"{prefix}_{txn_id}_{i}"


async def _apply_line(txn_id: str, ln: dict, delta: int, need_available: bool) -> str:
    """Apply ONE line atomically and exactly once. Returns applied | already | short | missing | compensated."""
    pid, q, vsku = ln["product_id"], ln["quantity"], ln.get("variant_sku")
    m, c = f"stock_ops.{_mk('m', txn_id, ln['i'])}", f"stock_ops.{_mk('c', txn_id, ln['i'])}"
    flt = {"id": pid, m: {"$exists": False}, c: {"$exists": False}}
    inc = {"stock": delta}
    if vsku:
        cond = {"sku": vsku}
        if need_available:
            cond["stock"] = {"$gte": q}
        flt["variants"] = {"$elemMatch": cond}
        inc["variants.$.stock"] = delta
    elif need_available:
        flt["stock"] = {"$gte": q}
    res = await db.products.update_one(flt, {"$inc": inc, "$set": {m: now_iso()}})
    if res.modified_count == 1:
        return "applied"
    doc = await db.products.find_one({"id": pid}, {"_id": 0, "stock_ops": 1, "variants.sku": 1})
    if doc is None:
        return "missing"
    ops = doc.get("stock_ops") or {}
    if _mk("m", txn_id, ln["i"]) in ops:
        return "already"
    if _mk("c", txn_id, ln["i"]) in ops:
        return "compensated"
    if vsku and vsku not in [v.get("sku") for v in doc.get("variants") or []]:
        return "missing"
    return "short"


async def _compensate_line(txn_id: str, ln: dict, delta: int):
    """Undo a line if it was applied, otherwise poison it so it can never be applied later. Idempotent."""
    pid, vsku = ln["product_id"], ln.get("variant_sku")
    m, c = f"stock_ops.{_mk('m', txn_id, ln['i'])}", f"stock_ops.{_mk('c', txn_id, ln['i'])}"
    flt = {"id": pid, m: {"$exists": True}, c: {"$exists": False}}
    inc = {"stock": -delta}
    if vsku:
        flt["variants"] = {"$elemMatch": {"sku": vsku}}
        inc["variants.$.stock"] = -delta
    res = await db.products.update_one(flt, {"$inc": inc, "$set": {c: now_iso()}})
    if res.modified_count != 1:
        await db.products.update_one({"id": pid, m: {"$exists": False}, c: {"$exists": False}}, {"$set": {c: now_iso()}})


# ---------------------------------------------------------------------------------------------- transactions
def _sign(kind: str) -> int:
    return -1 if kind in ("reserve", "revive") else 1


async def _new_txn(key: str, kind: str, order_id: str, reason: str, actor_id: str, lines: list):
    from money_guard import ensure as _money_guard          # Programme 01 (B-004): fail closed without the unique indexes
    await _money_guard("stock")
    now = now_iso()
    doc = {"id": new_id(), "key": key, "kind": kind, "order_id": order_id, "reason": reason, "actor_id": actor_id,
           "lines": lines, "status": "pending", "finalized": False, "bound": False, "created_at": now, "updated_at": now}
    try:
        await db.stock_txns.insert_one(dict(doc))
        return doc, True
    except DuplicateKeyError:
        return await db.stock_txns.find_one({"key": key}, {"_id": 0}), False


async def _arbiter(txn_id: str, frm: str, to: str, extra: Optional[dict] = None) -> bool:
    res = await db.stock_txns.update_one({"id": txn_id, "status": frm}, {"$set": {"status": to, "updated_at": now_iso(), **(extra or {})}})
    return res.modified_count == 1


async def _status(txn_id: str) -> dict:
    return await db.stock_txns.find_one({"id": txn_id}, {"_id": 0})


async def _run_txn(txn: dict) -> str:
    """Drive a transaction to committed / rolled_back. Safe to call repeatedly and concurrently."""
    txn = await _status(txn["id"]) or txn
    if txn["status"] in ("committed", "rolled_back"):
        return txn["status"]
    sign = _sign(txn["kind"])
    need = sign < 0
    if txn["status"] == "pending":
        short = None
        for ln in txn["lines"]:
            _fault("before_line", txn=txn, line=ln)
            r = await _apply_line(txn["id"], ln, sign * ln["quantity"], need)
            _fault("after_line", txn=txn, line=ln)
            if r in ("short", "compensated") or (r == "missing" and need):
                short = ln
                break
        _fault("before_decision", txn=txn)
        if short is None:
            if await _arbiter(txn["id"], "pending", "committed"):
                return "committed"
        else:
            await _arbiter(txn["id"], "pending", "rolling_back", {"short": {"i": short["i"], "product_id": short["product_id"]}})
        txn = await _status(txn["id"])
        if txn["status"] == "committed":
            return "committed"
    if txn["status"] == "rolling_back":
        # DEF-03: a reservation that had COMMITTED (its movement is on the journal) and is now abandoned because its order was
        # never saved gets a compensating movement, so stock_movements keeps agreeing with the counter. A rollback of a
        # transaction that never committed (a short line) logs nothing, as before (net zero, no forward row).
        after_commit = bool(txn.get("abandoned_after_commit"))
        for ln in txn["lines"]:
            if after_commit:
                await _log_movement(txn, ln, sign)             # the reservation being undone is on the journal (idempotent)
            _fault("before_compensate", txn=txn, line=ln)
            await _compensate_line(txn["id"], ln, sign * ln["quantity"])
            if after_commit:
                await _log_undo(txn, ln, sign)
        await _arbiter(txn["id"], "rolling_back", "rolled_back")
    return (await _status(txn["id"]))["status"]


async def _finalize(txn: dict):
    """Idempotent follow-up of a COMMITTED transaction: movement log + per-line order flags. Safe to replay."""
    txn = await _status(txn["id"]) or txn
    if txn.get("finalized") or txn["status"] != "committed":
        return
    sign = _sign(txn["kind"])
    for ln in txn["lines"]:
        _fault("before_finalize_line", txn=txn, line=ln)
        await _log_movement(txn, ln, sign)
        if txn["kind"] == "reserve":
            await _low_stock_alert(txn, ln)
        if txn["kind"] == "release":
            # Only while the line is still at the generation this release was created for: a stale finalizer of an old
            # release must not mark a line released after a later revival re-reserved it (the counter would disagree).
            gen, key = ln.get("gen", 0), f"items.{ln['i']}.release_gen"
            at_gen = {key: gen} if gen else {"$or": [{key: 0}, {key: {"$exists": False}}]}
            await db.orders.update_one({"id": txn["order_id"], **at_gen}, {"$set": {f"items.{ln['i']}.stock_released": True, key: gen + 1}})
        elif txn["kind"] == "revive":
            await db.orders.update_one({"id": txn["order_id"]}, {"$set": {f"items.{ln['i']}.stock_released": False}})
    _fault("before_finalized_flag", txn=txn)
    set_bound = {"bound": True} if txn["kind"] in ("release", "restock_return") else {}
    await db.stock_txns.update_one({"id": txn["id"]}, {"$set": {"finalized": True, "updated_at": now_iso(), **set_bound}})


async def _log_movement(txn: dict, ln: dict, sign: int):
    """One movement row per (transaction, line), even when several runners finalize the same transaction at once.
    The row's _id is derived from the transaction and line, so a concurrent second insert is refused by MongoDB itself
    (an upsert on a non-unique filter could insert twice). A row written before this change (random _id) is found first."""
    if await db.stock_movements.find_one({"txn_id": txn["id"], "line": ln["i"], "compensates": {"$ne": True}}, {"_id": 1}):
        return
    try:
        await db.stock_movements.insert_one({
            "_id": f"mv:{txn['id']}:{ln['i']}", "id": new_id(), "txn_id": txn["id"], "line": ln["i"], "product_id": ln["product_id"],
            "variant_sku": ln.get("variant_sku"), "delta": sign * ln["quantity"], "reason": txn["reason"], "order_id": txn["order_id"],
            "actor_id": txn["actor_id"], "created_at": now_iso()})
    except DuplicateKeyError:
        pass                                          # another runner logged this line first


async def _log_undo(txn: dict, ln: dict, sign: int):
    """DEF-03: the compensating journal row of an abandoned, previously committed reservation line. Exactly once (derived _id)."""
    try:
        await db.stock_movements.insert_one({
            "_id": f"mv:{txn['id']}:{ln['i']}:undo", "id": new_id(), "txn_id": txn["id"], "line": ln["i"], "product_id": ln["product_id"],
            "variant_sku": ln.get("variant_sku"), "delta": -sign * ln["quantity"], "reason": "reservation_abandoned", "compensates": True,
            "order_id": txn["order_id"], "actor_id": "system", "created_at": now_iso()})
    except DuplicateKeyError:
        pass


async def _low_stock_alert(txn: dict, ln: dict):
    """Tell the vendor when a sale takes a product (or variant) down to/below its low-stock threshold. Once per txn line."""
    p = await db.products.find_one({"id": ln["product_id"]}, {"_id": 0, "stock": 1, "variants": 1, "low_stock_threshold": 1, "vendor_id": 1, "name": 1})
    if not p or not p.get("vendor_id"):
        return
    now = p["stock"] if not ln.get("variant_sku") else next((v["stock"] for v in p.get("variants") or [] if v["sku"] == ln["variant_sku"]), None)
    if now is None:
        return
    threshold = p.get("low_stock_threshold", 5)
    if now > threshold or now + ln["quantity"] <= threshold:
        return                                         # still healthy, or it was already low before this sale
    v = await db.vendors.find_one({"id": p["vendor_id"]}, {"_id": 0, "user_id": 1})
    key = f"{txn['id']}:{ln['i']}"
    if v and not await db.notifications.find_one({"user_id": v["user_id"], "meta.dedupe": key}, {"_id": 1}):
        await create_notification(v["user_id"], "stock", "Low stock", f"{p['name']} is down to {now} in stock.", meta={"product_id": ln["product_id"], "dedupe": key})


async def _mark_bound(key: str):
    await db.stock_txns.update_one({"key": key}, {"$set": {"bound": True, "updated_at": now_iso()}})


# ---------------------------------------------------------------------------------------------- order placement
async def reserve_for_order(order_id: str, line_items: list, actor_id: str) -> Optional[dict]:
    """Reserve stock for every line, all-or-nothing. Returns None on success, or {"name", "product_id"} of the short line.
    The caller inserts the order afterwards and then calls `mark_reserve_bound(order_id)`."""
    lines = [{"i": i, "product_id": li["product_id"], "variant_sku": li.get("variant_sku"), "quantity": li["quantity"]}
             for i, li in enumerate(line_items)]
    txn, _ = await _new_txn(f"reserve:{order_id}", "reserve", order_id, "order_placed", actor_id, lines)
    status = await _run_txn(txn)
    if status == "committed":
        await _finalize(txn)
        return None
    short = (await _status(txn["id"])).get("short") or {}
    name = next((li.get("name") for i, li in enumerate(line_items) if i == short.get("i")), None) or "an item"
    return {"name": name, "product_id": short.get("product_id")}


async def abandon_reservation(order_id: str):
    """The order could not be saved after its stock was reserved: give the stock back right away (recovery would do it
    later anyway). Idempotent."""
    res = await db.stock_txns.update_one({"key": f"reserve:{order_id}", "status": "committed", "bound": {"$ne": True}},
                                         {"$set": {"status": "rolling_back", "abandoned_after_commit": True, "updated_at": now_iso()}})
    if res.modified_count == 1:
        t = await db.stock_txns.find_one({"key": f"reserve:{order_id}"}, {"_id": 0})
        await _run_txn(t)
        await _mark_bound(t["key"])


async def mark_reserve_bound(order_id: str):
    await _mark_bound(f"reserve:{order_id}")


# ---------------------------------------------------------------------------------------------- release / re-reserve
async def release_stock(order_id: str, reason: str, actor_id: str, vendor_id: Optional[str] = None,
                        eligible: Optional[Callable[[dict], bool]] = None) -> int:
    """Return reserved stock for an order's lines (optionally one vendor's / only `eligible` lines). Exactly once per line.
    Returns the number of lines this call released (a concurrent or recovered call may have released the others)."""
    order = await db.orders.find_one({"id": order_id, "stock_reserved": True}, {"_id": 0, "items": 1})
    if not order:
        return 0
    restored = 0
    for i, li in enumerate(order.get("items", [])):
        if vendor_id is not None and li.get("vendor_id") != vendor_id:
            continue
        if eligible is not None and not eligible(li):
            continue
        if li.get("stock_released") is True:
            continue
        gen = li.get("release_gen", 0)
        line = {"i": i, "product_id": li["product_id"], "variant_sku": li.get("variant_sku"), "quantity": li["quantity"], "gen": gen}
        txn, created = await _new_txn(f"release:{order_id}:{i}:{gen}", "release", order_id, reason, actor_id, [line])
        _fault("after_txn_created", txn=txn)
        if await _run_txn(txn) == "committed":
            await _finalize(txn)
            if created:
                restored += 1
    return restored


async def reserve_again(order_id: str, reason: str) -> bool:
    """Re-reserve previously released lines (late payment on an expired order). All-or-nothing, exactly once."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "items": 1, "revive_count": 1})
    if not order:
        return False
    lines = [{"i": i, "product_id": li["product_id"], "variant_sku": li.get("variant_sku"), "quantity": li["quantity"]}
             for i, li in enumerate(order.get("items", [])) if li.get("stock_released") is True]
    if not lines:
        return True
    txn, _ = await _new_txn(f"revive:{order_id}:{order.get('revive_count', 0)}", "revive", order_id, reason, "system", lines)
    if await _run_txn(txn) == "committed":
        await _finalize(txn)
        return True
    return False


async def restock_returned_lines(case_id: str, order_id: str, lines: list, actor_id: str, reason: str = "return_inspected_resellable") -> int:
    """Put RETURNED goods that passed inspection back into stock: exactly once per (return case, line), any quantity.
    `lines` = [{product_id, variant_sku?, quantity}]. Crash-safe like every other stock transaction. Returns lines created."""
    made = 0
    for i, ln in enumerate(lines):
        line = {"i": i, "product_id": ln["product_id"], "variant_sku": ln.get("variant_sku"), "quantity": ln["quantity"]}
        txn, created = await _new_txn(f"retrestock:{case_id}:{i}", "restock_return", order_id, reason, actor_id, [line])
        if await _run_txn(txn) == "committed":
            await _finalize(txn)
            made += 1 if created else 0
    return made


async def reserve_replacement(case_id: str, order_id: str, lines: list, actor_id: str) -> bool:
    """Take stock for a REPLACEMENT shipment, all-or-nothing and exactly once per case."""
    ls = [{"i": i, "product_id": ln["product_id"], "variant_sku": ln.get("variant_sku"), "quantity": ln["quantity"]} for i, ln in enumerate(lines)]
    txn, _ = await _new_txn(f"replace:{case_id}", "reserve", order_id, "replacement_shipped", actor_id, ls)
    if await _run_txn(txn) == "committed":
        await _finalize(txn)
        await _mark_bound(txn["key"])
        return True
    return False


# ---------------------------------------------------------------------------------------------- order-level effects
async def _flag_refund(order_id: str, reason: str) -> bool:
    """Idempotent: mark a paid-but-unfulfillable order for refund and alert admin + customer (first caller only)."""
    res = await db.orders.update_one({"id": order_id, "needs_refund": {"$ne": True}},
                                     {"$set": {"needs_refund": True, "needs_refund_reason": reason,
                                               "needs_refund_at": now_iso(), "updated_at": now_iso()}})
    if res.modified_count != 1:
        return False
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    await log_audit(SYSTEM, "late_payment_needs_refund", "order", order_id, new_value={"reason": reason})
    for a in await db.users.find({"role": "super_admin"}, {"_id": 0, "id": 1}).to_list(20):
        await create_notification(a["id"], "order", "Refund needed",
                                  f"Order {order.get('order_number')} was paid after it had expired or been cancelled "
                                  f"and cannot be fulfilled. Please refund the customer.", meta={"order_id": order_id})
    await create_notification(order["user_id"], "order", "Payment received - refund coming",
                              f"We received your payment for order {order.get('order_number')} after it had expired or been cancelled, "
                              f"so it cannot be fulfilled. It will be refunded.", meta={"order_id": order_id})
    return True


async def finish_revival(order_id: str, txn_id: str, distribute: bool = False):
    """Idempotent: after stock was re-reserved, restore the order, ensure its invoice (and optionally its commissions)."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    now = now_iso()
    fl = [{**f, "status": "new", "events": [*f.get("events", []),
           {"status": "new", "at": now, "by": "system", "note": "Payment received after timeout; order restored"}]}
          for f in order.get("fulfilments", [])]
    res = await db.orders.update_one(
        {"id": order_id, "revive_done_txn": {"$ne": txn_id}},
        {"$set": {"status": "processing", "fulfilments": fl, "revived_after_timeout": True, "revive_done_txn": txn_id,
                  "updated_at": now}, "$inc": {"revive_count": 1}, "$unset": {"cancel_reason": "", "cancelled_at": ""}})
    if res.modified_count == 1:
        await log_audit(SYSTEM, "order_revived_late_payment", "order", order_id)
    from core import next_sequence
    if not (await db.orders.find_one({"id": order_id}, {"_id": 0, "invoice_number": 1}) or {}).get("invoice_number"):
        inv = await next_sequence("invoice", "INV", 6)
        await db.orders.update_one({"id": order_id, "invoice_number": None}, {"$set": {"invoice_number": inv}})
    if distribute:
        order = await db.orders.find_one({"id": order_id}, {"_id": 0})
        buyer = await db.users.find_one({"id": order["user_id"]}, {"_id": 0})
        if buyer:
            from commission import distribute_sale_commissions
            await distribute_sale_commissions(order, buyer)


async def handle_late_payment(order: dict, allow_revive: bool = True) -> bool:
    """Called once, by the single caller that just claimed 'paid' for an order that is already cancelled.

    - Expired by the 15-minute rule (`allow_revive=True`): atomically take the stock back if available. True = revived
      (continue as a normal paid order). False = not available: flagged `needs_refund`.
    - Cancelled by an admin (`allow_revive=False`): the admin's decision stands; flagged `needs_refund`.
    A `needs_refund` order gets no commission and no invoice, and vendors never see it.
    """
    oid = order["id"]
    if allow_revive:
        # Settle the expiry's stock return FIRST. An expiry that is still in flight (or was interrupted after its claim)
        # would otherwise return the stock after the revival below had re-reserved only the lines already marked
        # released, leaving an active order with no stock behind it. release_stock uses the expiry's own transaction
        # keys, so this finishes that same return exactly once; then every line is released and is re-reserved together.
        await release_stock(oid, "order_payment_timeout", "system")
        n = (await db.orders.find_one({"id": oid}, {"_id": 0, "revive_count": 1}) or {}).get("revive_count", 0)
        if await reserve_again(oid, "order_revived_late_payment"):
            _fault("before_finish_revival", order=order)
            txn = await db.stock_txns.find_one({"key": f"revive:{oid}:{n}"}, {"_id": 0})
            await finish_revival(oid, txn["id"] if txn else "none")
            if txn:
                await _mark_bound(txn["key"])
            return True
        await _flag_refund(oid, "paid_after_timeout_out_of_stock")
        await _mark_bound(f"revive:{oid}:{n}")
        return False
    await _flag_refund(oid, "paid_after_cancellation")
    return False


# ---------------------------------------------------------------------------------------------- expiry
async def payment_in_progress(order_id: str) -> bool:
    """True while a gateway has reported a payment for this order that is not applied yet and the grace period has not ended."""
    tx = await db.payment_transactions.find_one(
        {"order_id": order_id, "payment_status": {"$ne": "paid"},
         "$or": [{"razorpay_payment_id": {"$exists": True, "$nin": [None, ""]}}, {"gateway_events.0": {"$exists": True}}]},
        {"_id": 0, "created_at": 1})
    if not tx:
        return False
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "created_at": 1})
    limit = (datetime.now(timezone.utc) - timedelta(minutes=PENDING_ONLINE_TTL_MINUTES + PAYMENT_IN_PROGRESS_GRACE_MINUTES)).isoformat()
    return bool(o) and (o.get("created_at") or "") > limit


async def expire_one(order_id: str) -> bool:
    """Cancel one overdue unpaid online order and return its stock. Safe to call concurrently / repeatedly.
    Programme 01 (B-006): not while a reported gateway payment is still within its grace period."""
    if await payment_in_progress(order_id):
        return False
    now = now_iso()
    claim = await db.orders.update_one(   # a payment that lands first wins: only a still-unpaid pending online order expires
        {"id": order_id, "payment_method": "online", "payment_status": "pending", "status": "payment_pending",
         "created_at": {"$lt": _cutoff_iso()}},
        {"$set": {"status": "cancelled", "cancel_reason": EXPIRY_REASON, "cancelled_at": now, "updated_at": now}})
    if claim.modified_count != 1:
        return False
    _fault("after_expiry_claim", order_id=order_id)
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    await release_stock(order_id, "order_payment_timeout", "system")
    fl = [{**f, "status": "cancelled", "events": [*f.get("events", []),
           {"status": "cancelled", "at": now, "by": "system", "note": "Payment not completed in time"}]}
          for f in o.get("fulfilments", [])]
    if fl:
        await db.orders.update_one({"id": order_id}, {"$set": {"fulfilments": fl}})
    await db.payment_transactions.update_many({"order_id": order_id, "payment_status": {"$ne": "paid"}},
                                              {"$set": {"status": "expired", "updated_at": now}})
    await log_audit(SYSTEM, "order_payment_timeout", "order", order_id,
                    old_value={"status": "payment_pending"}, new_value={"status": "cancelled", "reason": EXPIRY_REASON})
    await create_notification(o["user_id"], "order", "Order cancelled",
                              f"Order {o.get('order_number')} was cancelled because payment was not completed within "
                              f"{PENDING_ONLINE_TTL_MINUTES} minutes. You can place the order again.",
                              meta={"order_id": order_id})
    return True


UPI_CLAIM_EXPIRED = "upi_claim_expired"


async def expire_upi_claim(order_id: str, hours: float) -> bool:
    """Decision 9: an unverified UPI claim older than `hours` expires. Atomic and race-safe: a finance confirmation that lands
    first wins (the claim must still be "claimed"); once expired, a confirmation is refused. Stock comes back exactly once."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    now = now_iso()
    claim = await db.orders.update_one(
        {"id": order_id, "payment_status": "claimed", "status": {"$ne": "cancelled"},
         "$or": [{"claimed_at": {"$lt": cutoff}}, {"claimed_at": {"$exists": False}, "updated_at": {"$lt": cutoff}}]},
        {"$set": {"status": "cancelled", "payment_status": "claim_expired", "cancel_reason": UPI_CLAIM_EXPIRED,
                  "cancelled_at": now, "updated_at": now}})
    if claim.modified_count != 1:
        return False
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    await release_stock(order_id, "upi_claim_expired", "system")
    # Vendors never see an unverified claim (FIN-02), so no fulfilment has started: all of them are cancelled.
    fl = [{**f, "status": "cancelled", "events": [*f.get("events", []),
           {"status": "cancelled", "at": now, "by": "system", "note": "UPI payment was not verified in time"}]}
          for f in o.get("fulfilments", [])]
    if fl:
        await db.orders.update_one({"id": order_id}, {"$set": {"fulfilments": fl}})
    await log_audit(SYSTEM, "upi_claim_expired", "order", order_id, old_value={"payment_status": "claimed"},
                    new_value={"payment_status": "claim_expired", "status": "cancelled", "after_hours": hours})
    await create_notification(o["user_id"], "order", "Order cancelled",
                              f"Order {o.get('order_number')} was cancelled because your UPI payment could not be verified within "
                              f"{int(hours)} hours. If money left your account, contact support with the UTR.",
                              meta={"order_id": order_id})
    return True


async def expire_upi_claims(limit: int = 100, max_seconds: Optional[float] = None) -> int:
    from core import get_settings
    hours = float((await get_settings()).get("upi_claim_expiry_hours") or 24)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    from sweeps import run_sweep       # Programme 01 (B-006): every overdue claim, not only the first `limit`
    n = 0

    async def one(o, _dry):
        nonlocal n
        if await expire_upi_claim(o["id"], hours):
            n += 1
            return "updated"
        return "skipped"
    await run_sweep("expire_upi_claims", "orders",
                    {"payment_status": "claimed", "status": {"$ne": "cancelled"},
                     "$or": [{"claimed_at": {"$lt": cutoff}}, {"claimed_at": {"$exists": False}, "updated_at": {"$lt": cutoff}}]},
                    one, batch=limit, max_seconds=max_seconds, projection={"_id": 0, "id": 1})
    return n


async def expire_pending_online_orders(limit: int = 100, max_seconds: Optional[float] = None) -> int:
    """Sweep: expire overdue unpaid online orders, finish interrupted expiries, and run crash recovery.

    Programme 01 (B-006): every overdue order is reached (resumable keyset sweep; `limit` is the page size) instead of only the
    first `limit`. Only ONLINE orders still `pending` expire: a paid order, a UPI claim under review (its own 24 h rule) and every
    cash-on-delivery order are never touched here - COD follows the seller's fulfilment (accept / reject) and the customer's
    own cancellation, and no automatic COD expiry exists (owner decision, see OWNER_DECISION_REGISTER)."""
    from sweeps import run_sweep
    n = 0

    async def one(o, _dry):
        nonlocal n
        if await expire_one(o["id"]):
            n += 1
            return "updated"
        return "skipped"
    await run_sweep("expire_pending_online", "orders",
                    {"payment_method": "online", "payment_status": "pending", "status": "payment_pending",
                     "created_at": {"$lt": _cutoff_iso()}}, one, batch=limit, max_seconds=max_seconds, projection={"_id": 0, "id": 1})
    n += await expire_upi_claims(limit, max_seconds=max_seconds)
    # Self-heal: cancelled by expiry but interrupted before the stock was returned (e.g. a function timeout).
    n += await heal_stuck_expiries(limit, max_seconds=max_seconds)
    await run_recovery(limit=20, max_seconds=max_seconds)     # DEF-03: 20 is the page size now, not a per-run ceiling
    return n


# DEF-03: an order whose expiry (payment timeout, or UPI claim expiry) was recorded but whose stock was not fully returned
STUCK_EXPIRY_Q = {"$or": [{"cancel_reason": EXPIRY_REASON, "payment_status": "pending"},
                          {"cancel_reason": UPI_CLAIM_EXPIRED, "payment_status": "claim_expired"}], "stock_reserved": True,
                  "items": {"$elemMatch": {"stock_released": {"$ne": True}}}}


async def _unreleased_lines(order_id: str) -> int:
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "items.stock_released": 1})
    return sum(1 for li in (o or {}).get("items", []) if li.get("stock_released") is not True)


async def heal_stuck_expiries(limit: int = 100, dry_run: bool = False, max_seconds: Optional[float] = None) -> int:
    """DEF-03 (2026-11-24): return the stock of EVERY expired order whose release was interrupted.

    It used to read `find(stuck).limit(limit)` with no order: a record that kept failing stayed first and starved the rest, and
    one exception stopped the whole call. Now it is a resumable keyset sweep (sweeps.run_sweep: id order, checkpoint, per-record
    isolation, failures recorded and retried, dry run, time budget). Each order is RE-CHECKED just before its release, so an order
    a late payment revived meanwhile (payment no longer pending) is left alone. The release itself is the existing exactly-once
    `release_stock` (journal key per line and generation), so a retry or a second worker never returns stock twice."""
    from sweeps import run_sweep
    n = 0

    async def one(o, dry):
        nonlocal n
        if not await db.orders.find_one({"$and": [STUCK_EXPIRY_Q, {"id": o["id"]}]}, {"_id": 1}):
            return "skipped"                                   # no longer stuck (finished elsewhere, or revived)
        if dry:
            n += 1                                             # dry run: the number of orders that would be healed
            return "eligible"
        before = await _unreleased_lines(o["id"])
        await release_stock(o["id"], "order_payment_timeout", "system")
        if await _unreleased_lines(o["id"]) < before:          # counts a release finished here even if an earlier call created it
            n += 1
            return "updated"
        return "skipped"
    await run_sweep("stock_expiry_self_heal", "orders", STUCK_EXPIRY_Q, one, batch=limit, dry_run=dry_run, max_seconds=max_seconds,
                    projection={"_id": 0, "id": 1})
    return n


# ---------------------------------------------------------------------------------------------- confirmed cancellation
async def restock_on_confirmed_cancellation(order_id: str, prev_status: str, actor: dict) -> dict:
    """An admin has CONFIRMED a cancellation. Return stock only for lines whose goods have not left: a vendor line while its
    fulfilment is new/accepted/packed; a platform-owned line while the order was not shipped/delivered. Dispatched /
    delivered / returned goods are NOT restocked here (returns restock only after receipt + inspection). Pre-dispatch
    fulfilments are cancelled so the vendor stops work."""
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o or not o.get("stock_reserved"):
        return {"restocked_lines": 0, "skipped": "no reservation"}
    fstatus = {f["vendor_id"]: f.get("status") for f in o.get("fulfilments", [])}

    def eligible(li: dict) -> bool:
        if li.get("vendor_id"):
            return fstatus.get(li["vendor_id"]) in PRE_DISPATCH
        return prev_status not in NOT_SHIPPED_ORDER_STATUS

    n = await release_stock(order_id, "order_cancelled_confirmed", actor.get("id", "system"), eligible=eligible)
    _fault("after_cancel_release", order_id=order_id)
    now = now_iso()
    fl, changed = [], False
    for f in o.get("fulfilments", []):
        if f.get("status") in PRE_DISPATCH:
            f = {**f, "status": "cancelled", "events": [*f.get("events", []),
                 {"status": "cancelled", "at": now, "by": actor.get("id", "system"), "note": "Order cancelled by admin"}]}
            changed = True
        fl.append(f)
    if changed:
        await db.orders.update_one({"id": order_id}, {"$set": {"fulfilments": fl}})
    return {"restocked_lines": n}


# ---------------------------------------------------------------------------------------------- durable restock intents
def intent(kind: str, actor_id: str, **kw) -> dict:
    """A restock decision recorded ATOMICALLY with the state change that caused it (same update), replayed if interrupted."""
    return {"id": new_id(), "kind": kind, "actor_id": actor_id, "at": now_iso(), **kw}


async def run_intents(order_id: str) -> int:
    """Execute and clear every pending restock intent on an order; returns the lines restocked by this call.
    Idempotent: release_stock is exactly-once per line, so replaying an interrupted intent can never double-restock."""
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "restock_intents": 1})
    lines = 0
    for it in (o or {}).get("restock_intents") or []:
        if it["kind"] in ("admin_cancel", "confirmed_cancel"):
            lines += (await restock_on_confirmed_cancellation(order_id, it.get("prev_status", ""), {"id": it["actor_id"]}))["restocked_lines"]
        elif it["kind"] == "vendor_release":
            lines += await release_stock(order_id, it["reason"], it["actor_id"], vendor_id=it["vendor_id"])
        _fault("before_intent_clear", order_id=order_id, intent=it)
        await db.orders.update_one({"id": order_id}, {"$pull": {"restock_intents": {"id": it["id"]}}})
    return lines


# ---------------------------------------------------------------------------------------------- recovery
def _recoverable_txn_q(min_age_s: Optional[int] = None) -> dict:
    return {"updated_at": {"$lt": _age_cutoff(min_age_s)}, "$or": [
        {"status": {"$in": ["pending", "rolling_back"]}},
        {"status": "committed", "finalized": {"$ne": True}},
        {"kind": {"$in": ["reserve", "revive"]}, "status": {"$in": ["committed", "rolled_back"]}, "bound": {"$ne": True}}]}


async def recover_stock_txns(limit: int = 50, min_age_s: Optional[int] = None, dry_run: bool = False,
                             max_seconds: Optional[float] = None) -> int:
    """Finish interrupted transactions older than the minimum age.

    DEF-03 (2026-11-24): every recoverable transaction is reached - a resumable keyset sweep over `stock_txns` by `id` (page size
    `limit`) instead of `find(q).limit(limit)` with no order, where a transaction that kept failing starved the others and one
    exception stopped the run. Each transaction is re-checked just before it is driven (a live request may have finished it); the
    drive itself is the existing arbiter / per-line marker engine, so a retry or a concurrent worker can never apply a line twice."""
    from sweeps import run_sweep
    q = _recoverable_txn_q(min_age_s)
    n = 0

    async def one(doc, dry):
        nonlocal n
        t = await db.stock_txns.find_one({"$and": [q, {"id": doc["id"]}]}, {"_id": 0})
        if not t:
            return "skipped"                                   # finished meanwhile by its own request or another worker
        if dry:
            n += 1                                             # dry run: the number of transactions that would be driven
            return "eligible"
        await _recover_one_txn(t)
        n += 1
        return "updated"
    await run_sweep("stock_txn_recovery", "stock_txns", q, one, batch=limit, dry_run=dry_run, max_seconds=max_seconds,
                    projection={"_id": 0, "id": 1})
    return n


async def _recover_one_txn(t: dict) -> None:
    """The unchanged per-transaction recovery step (moved out of the loop for DEF-03)."""
    status = await _run_txn(t)
    if status == "committed":
        await _finalize(t)
    t = await _status(t["id"])
    if t["kind"] == "reserve" and not t.get("bound"):
        if await db.orders.find_one({"id": t["order_id"]}, {"_id": 1}):
            await _mark_bound(t["key"])                       # order exists: the reservation is real
        elif t["status"] == "committed":                      # reserved stock but no order: abandon + give it back
            res = await db.stock_txns.update_one({"id": t["id"], "status": "committed", "bound": {"$ne": True}},
                                                 {"$set": {"status": "rolling_back", "abandoned_after_commit": True, "updated_at": now_iso()}})
            if res.modified_count == 1:
                await _run_txn(t)
                await _mark_bound(t["key"])
        else:
            await _mark_bound(t["key"])
    elif t["kind"] == "revive" and not t.get("bound"):
        if t["status"] == "committed":
            await finish_revival(t["order_id"], t["id"], distribute=True)
        else:
            await _flag_refund(t["order_id"], "paid_after_timeout_out_of_stock")
        await _mark_bound(t["key"])


async def process_restock_intents(limit: int = 50, min_age_s: Optional[int] = None, dry_run: bool = False,
                                  max_seconds: Optional[float] = None) -> int:
    """Replay durable restock intents left on orders by an interrupted request. DEF-03: resumable keyset sweep over every such
    order (page size `limit`), each re-checked first; `run_intents` is exactly-once per line. Returns the lines restocked."""
    from sweeps import run_sweep
    q = {"restock_intents.0": {"$exists": True}, "updated_at": {"$lt": _age_cutoff(min_age_s)}}
    lines = 0

    async def one(o, dry):
        nonlocal lines
        if not await db.orders.find_one({"$and": [q, {"id": o["id"]}]}, {"_id": 1}):
            return "skipped"
        if dry:
            lines += 1                                         # dry run: the number of orders with intents to replay
            return "eligible"
        lines += await run_intents(o["id"])
        return "updated"
    await run_sweep("stock_restock_intents", "orders", q, one, batch=limit, dry_run=dry_run, max_seconds=max_seconds,
                    projection={"_id": 0, "id": 1})
    return lines


async def prune_stock_markers(days: int = 7, limit: int = 200, max_seconds: Optional[float] = None) -> int:
    """Housekeeping: drop idempotency markers of long-finished transactions (they are never replayed once terminal).

    Programme 02 / W5: this used `find(q).limit(200)` with no order, once per daily maintenance run, so (a) at most 200 transactions
    were pruned per day and a larger daily volume left product `stock_ops` growing without bound, and (b) records it must skip
    (unbound reservations) stayed in the result and, once 200 of them existed, filled every batch so nothing was pruned again.
    Now it is a resumable keyset sweep (sweeps.run_sweep: id order, checkpoint, per-record isolation, time budget); `limit` is the
    page size. The selection and the skip rule are unchanged. Returns the number of transactions pruned in this run."""
    from sweeps import run_sweep
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    q = {"status": {"$in": ["committed", "rolled_back"]}, "finalized": True, "pruned": {"$ne": True}, "updated_at": {"$lt": cutoff}}
    pruned = [0]

    async def one(t: dict, dry_run: bool) -> str:
        if t["kind"] in ("reserve", "revive") and not t.get("bound"):
            return "skipped"                    # recovery must bind or compensate it first; its markers stay
        for ln in t["lines"]:
            await db.products.update_one({"id": ln["product_id"]}, {"$unset": {f"stock_ops.{_mk('m', t['id'], ln['i'])}": "",
                                                                              f"stock_ops.{_mk('c', t['id'], ln['i'])}": ""}})
        r = await db.stock_txns.update_one({"id": t["id"], "pruned": {"$ne": True}}, {"$set": {"pruned": True}})
        if r.modified_count:
            pruned[0] += 1
            return "updated"
        return "skipped"                        # a concurrent run pruned it first
    await run_sweep("stock_marker_prune", "stock_txns", q, one, batch=limit, max_seconds=max_seconds,
                    projection={"_id": 0, "id": 1, "kind": 1, "bound": 1, "lines": 1})
    return pruned[0]


async def run_recovery(limit: int = 50, min_age_s: Optional[int] = None, dry_run: bool = False,
                       max_seconds: Optional[float] = None) -> dict:
    """Stock crash recovery: interrupted journal transactions, then durable restock intents. DEF-03: both are complete, resumable
    sweeps; `limit` is the page size. A dry run reports what would be recovered and writes nothing."""
    return {"txns": await recover_stock_txns(limit, min_age_s, dry_run=dry_run, max_seconds=max_seconds),
            "intents": await process_restock_intents(limit, min_age_s, dry_run=dry_run, max_seconds=max_seconds)}
