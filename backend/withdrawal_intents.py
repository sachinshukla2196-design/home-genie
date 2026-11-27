"""Programme 03 (B-022): crash-safe, idempotent withdrawal requests.

A withdrawal request is written FIRST, as a durable intent, before any money moves. The money then moves at most once, keyed by
the request id, and the request is opened for finance only after the money and its ledger row are both in place:

    reserving --(hold applied on the wallet, ledger row written)--> pending      (the existing REQUESTED state; finance reviews it)
    reserving --(hold could not be applied: balance too low)-------> not_reserved (terminal; no money ever moved)

Exclusion is decided on the wallet document itself, in one atomic update, exactly like pay / reject in admin_routes:
- the hold pushes  `withdrawal_hold:<id>`  into wallet.applied_ops and moves available -> pending, only if neither the hold nor
  the void marker is already there and the available balance covers the amount;
- closing a request that never held money pushes `withdrawal_void:<id>`, only if the hold is not there.
So for any one request either the hold or the void wins, never both, and neither applies twice - whatever crashes or races.

Recovery (`repair_withdrawal_requests`, run by the daily maintenance) finishes every request left in `reserving` by a crash:
the hold is present -> the ledger row is ensured and the request is opened (pending); the hold is absent -> the void is recorded
and the request is closed as not_reserved. Recovery never reserves money a member did not see reserved.

Nothing here changes who may withdraw, how much, when, the approval workflow, fees or payout methods.
"""
import logging
from typing import Optional

from core import db, now_iso, new_id, paise_to_float, get_or_create_wallet, create_notification, log_audit

logger = logging.getLogger("homegenies")

RESERVING, NOT_RESERVED, OPEN = "reserving", "not_reserved", "pending"
STALE_SECONDS = 120          # a request still reserving after this long is treated as interrupted by the repair sweep
SYSTEM_ACTOR = {"id": "system", "email": None, "role": "system"}


def hold_op(wd_id: str) -> str:
    return f"withdrawal_hold:{wd_id}"


def void_op(wd_id: str) -> str:
    return f"withdrawal_void:{wd_id}"


async def _ops(user_id: str) -> set:
    w = await db.wallets.find_one({"user_id": user_id}, {"_id": 0, "applied_ops": 1}) or {}
    return set(w.get("applied_ops") or [])


async def apply_hold(wr: dict) -> str:
    """Try to move available -> pending for this request, at most once. Returns 'held' (now or earlier), 'void' (the request was
    closed without money) or 'insufficient' (balance too low; nothing moved, nothing recorded)."""
    from money_guard import ensure as _money_guard
    await _money_guard("wallet", "withdrawals")
    await get_or_create_wallet(wr["user_id"])
    amt, hop, vop = int(wr["amount_paise"]), hold_op(wr["id"]), void_op(wr["id"])
    res = await db.wallets.update_one(
        {"user_id": wr["user_id"], "applied_ops": {"$nin": [hop, vop]}, "available_balance_paise": {"$gte": amt}},
        {"$inc": {"available_balance_paise": -amt, "available_balance": paise_to_float(-amt),
                  "pending_balance_paise": amt, "pending_balance": paise_to_float(amt)},
         "$push": {"applied_ops": hop}, "$set": {"updated_at": now_iso()}})
    if res.modified_count == 1:
        return "held"
    ops = await _ops(wr["user_id"])
    if hop in ops:
        return "held"
    if vop in ops:
        return "void"
    return "insufficient"


async def apply_void(wr: dict) -> str:
    """Record that this request will never hold money, unless the hold already happened. Returns 'void' or 'held'."""
    from money_guard import ensure as _money_guard
    await _money_guard("wallet", "withdrawals")
    await get_or_create_wallet(wr["user_id"])
    hop, vop = hold_op(wr["id"]), void_op(wr["id"])
    res = await db.wallets.update_one({"user_id": wr["user_id"], "applied_ops": {"$nin": [hop, vop]}},
                                      {"$push": {"applied_ops": vop}, "$set": {"updated_at": now_iso()}})
    if res.modified_count == 1:
        return "void"
    return "held" if hop in await _ops(wr["user_id"]) else "void"


async def open_request(wr: dict, actor: Optional[dict] = None, request=None, settings: Optional[dict] = None) -> bool:
    """The hold is in place: ensure its ledger row, then claim reserving -> pending (marking the member notice and the audit record
    as due in the same update), then write them. Returns whether this call opened the request."""
    from financial_ops import ensure_ledger
    amt = int(wr["amount_paise"])
    await ensure_ledger({"id": new_id(), "user_id": wr["user_id"], "type": "WITHDRAWAL", "status": "HELD", "direction": "debit",
                         "amount": paise_to_float(amt), "amount_paise": amt, "reference": wr["id"], "op_key": hold_op(wr["id"]),
                         "description": "Withdrawal request (held)", "created_at": now_iso()})
    now = now_iso()
    claimed = await db.withdrawal_requests.update_one({"id": wr["id"], "status": RESERVING},
                                                      {"$set": {"status": OPEN, "reserved_at": now, "updated_at": now,
                                                                "effects_due": True}})
    if claimed.modified_count != 1:
        return False
    await finish_effects(wr, actor=actor, request=request, settings=settings)
    return True


async def finish_effects(wr: dict, actor: Optional[dict] = None, request=None, settings: Optional[dict] = None) -> None:
    """The member notice and the audit record of an opened request. Each is written only if it is not there yet, and the
    `effects_due` flag is cleared afterwards, so a crash between them is finished by the sweep without duplicates."""
    amt = int(wr["amount_paise"])
    if not await db.notifications.find_one({"user_id": wr["user_id"], "meta.withdrawal_id": wr["id"], "meta.event": "requested"},
                                           {"_id": 1}):
        if settings is None:
            from core import get_settings
            settings = await get_settings()
        sym = settings.get("currency_symbol", "₹")
        whole = amt // 100
        await create_notification(wr["user_id"], "withdrawal", "Withdrawal requested",
                                  f"Your withdrawal of {sym}{whole} is pending review.",
                                  "निकासी अनुरोध", f"आपकी {sym}{whole} की निकासी समीक्षाधीन है।",
                                  meta={"withdrawal_id": wr["id"], "event": "requested"})
    if not await db.audit_logs.find_one({"action": "withdrawal_requested", "entity_id": wr["id"]}, {"_id": 1}):
        await log_audit(actor or SYSTEM_ACTOR, "withdrawal_requested", "withdrawal", wr["id"],
                        new_value={"amount": paise_to_float(amt), "amount_paise": amt,
                                   **({} if actor else {"completed_by": "withdrawal_request_repair"})}, request=request)
    await db.withdrawal_requests.update_one({"id": wr["id"], "effects_due": True}, {"$unset": {"effects_due": ""}})


async def close_unreserved(wr: dict, reason: str, actor: Optional[dict] = None, request=None) -> bool:
    """The void is recorded: claim reserving -> not_reserved. No money moved for this request. The call that wins the claim
    writes one audit record (actor: the member, or the system for the repair sweep)."""
    now = now_iso()
    res = await db.withdrawal_requests.update_one({"id": wr["id"], "status": RESERVING},
                                                  {"$set": {"status": NOT_RESERVED, "closed_reason": reason, "closed_at": now,
                                                            "updated_at": now}})
    if res.modified_count != 1:
        return False
    await log_audit(actor or SYSTEM_ACTOR, "withdrawal_request_not_reserved", "withdrawal", wr["id"],
                    new_value={"reason": reason, "amount_paise": int(wr["amount_paise"]), "money_moved": False}, request=request)
    return True


async def settle(wr: dict, actor: Optional[dict] = None, request=None, settings: Optional[dict] = None,
                 close_if_insufficient: bool = True) -> str:
    """Drive one request from reserving to its next stable state. Safe to repeat and to run concurrently. Returns the final status."""
    if wr.get("status") != RESERVING:
        return wr.get("status")
    outcome = await apply_hold(wr)
    if outcome == "insufficient" and close_if_insufficient:
        outcome = "void" if await apply_void(wr) == "void" else "held"
    if outcome == "held":
        await open_request(wr, actor=actor, request=request, settings=settings)
    elif outcome == "void":
        await close_unreserved(wr, "insufficient_balance", actor=actor, request=request)
    cur = await db.withdrawal_requests.find_one({"id": wr["id"]}, {"_id": 0, "status": 1}) or {}
    return cur.get("status") or RESERVING


async def repair_withdrawal_requests(dry_run: bool = False, max_seconds: Optional[float] = None, batch: int = 200,
                                     stale_seconds: int = STALE_SECONDS) -> dict:
    """Repair sweep: every request left in `reserving` for longer than `stale_seconds`. If its hold is on the wallet the request is
    opened (ledger row ensured, status pending); otherwise the void is recorded and it is closed as not_reserved. Recovery never
    applies a new hold - the member saw the request fail or time out, so money is not reserved behind their back."""
    from datetime import datetime, timedelta, timezone
    from sweeps import run_sweep
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)).isoformat()

    async def handle(wr, dry):
        held = hold_op(wr["id"]) in await _ops(wr["user_id"])
        if dry:
            return "eligible"
        if held:
            await open_request(wr)
            return "updated"
        if await apply_void(wr) == "held":            # the original request won the race after all: finish it instead
            await open_request(wr)
            return "updated"
        await close_unreserved(wr, "interrupted_before_reservation")
        return "updated"

    async def effects(wr, dry):
        if dry:
            return "eligible"
        await finish_effects(wr)
        return "updated"
    proj = {"_id": 0, "id": 1, "user_id": 1, "amount_paise": 1, "status": 1}
    out = await run_sweep("withdrawal_request_repair", "withdrawal_requests", {"status": RESERVING, "created_at": {"$lt": cutoff}},
                          handle, dry_run=dry_run, max_seconds=max_seconds, batch=batch, projection=proj)
    out["effects"] = await run_sweep("withdrawal_request_effects", "withdrawal_requests",
                                     {"effects_due": True, "updated_at": {"$lt": cutoff}}, effects, dry_run=dry_run,
                                     max_seconds=max_seconds, batch=batch, projection=proj)
    return out


async def withdrawal_audit(limit_report: int = 200) -> dict:
    """Read-only reconciliation of withdrawal requests against wallet operations and ledger rows (never writes).
    For every keyed request (one created by this module): pending/approved/paid/rejected need the hold and its HELD row;
    not_reserved must not have the hold; paid/rejected need their pay/reject op and ledger row. Every request (legacy included) whose
    pay / reject wallet move is applied while it is still open is reported (P03-A04)."""
    out = {"reserving": 0, "reserving_stale": 0, "keyed": 0, "legacy_unkeyed": 0, "issues": []}
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=STALE_SECONDS)).isoformat()
    async for wr in db.withdrawal_requests.find({}, {"_id": 0, "id": 1, "user_id": 1, "status": 1, "hold_op": 1,
                                                     "amount_paise": 1, "created_at": 1}):
        st = wr.get("status")
        if st == RESERVING:
            out["reserving"] += 1
            if (wr.get("created_at") or "") < cutoff:
                out["reserving_stale"] += 1
            continue
        ops = await _ops(wr["user_id"])
        # P03-A04: the pay / reject wallet move happened but the request was never finished (crash or 503 between the two).
        # Reported for a person - finishing needs the finance user and payout reference, so nothing is done automatically.
        if st in ("pending", "under_review", "approved") and \
                ({f"withdrawal_paid:{wr['id']}", f"withdrawal_rejected:{wr['id']}"} & ops):
            if len(out["issues"]) < limit_report:
                out["issues"].append({"withdrawal_id": wr["id"], "status": st, "issue": "wallet_settled_but_request_open"})
            continue
        if not wr.get("hold_op"):
            out["legacy_unkeyed"] += 1
            continue
        out["keyed"] += 1
        held = hold_op(wr["id"]) in ops
        problem = None
        if st == NOT_RESERVED and held:
            problem = "closed_but_held"
        elif st != NOT_RESERVED and not held:
            problem = "open_without_hold"
        elif st != NOT_RESERVED and not await db.wallet_transactions.find_one({"op_key": hold_op(wr["id"])}, {"_id": 1}):
            problem = "hold_ledger_missing"
        elif st in ("paid", "rejected"):
            op = f"withdrawal_{'paid' if st == 'paid' else 'rejected'}:{wr['id']}"
            if op not in ops or not await db.wallet_transactions.find_one({"op_key": op}, {"_id": 1}):
                problem = f"{st}_op_or_ledger_missing"
        if problem and len(out["issues"]) < limit_report:
            out["issues"].append({"withdrawal_id": wr["id"], "status": st, "issue": problem})
    return out
