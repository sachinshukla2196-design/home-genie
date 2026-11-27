"""Programme 03: the financial reconciliation framework. READ-ONLY.

One report across every money domain, built from the existing per-domain checks plus the Programme 03 ones:

  payments     paid orders vs their payment attempts, captured attempts not applied to an order, verified gateway amounts vs
               order totals, payment events needing attention (failed / stuck / rejected / unmatched)
  wallets      wallet aggregates vs the wallet ledger (wallet_reconcile), commission intents, distribution audit
  withdrawals  every keyed withdrawal request vs its wallet operations and ledger rows (withdrawal_intents.withdrawal_audit)
  settlements  snapshot integrity (settlement_snapshot.audit), paid settlements without their ledger entry, open-per-vendor rule
  vendor_ledger  vendors settled beyond what they were owed
  refunds      refund obligations without a case; cancelled orders with money in and no obligation record at all; cases by state
  commissions  paid orders without a commission plan / vendor groups without their sale entry (order_completion), unfunded plans
  stock        negative stock, stock journal transactions left unfinished (stock crash recovery, dry run)
  liabilities  (Programme 03-B) captured money on cancelled orders without an obligation; interrupted late-payment decisions;
               refund owed but the order is active or earned revenue; duplicated / orphaned refund liabilities; one gateway
               payment or bank reference used for more than one order - each issue with severity, ids, amount, gateway, reason,
               detection time and a remediation category

Nothing here writes: only find / count / aggregate / distinct, and the repair sweeps in DRY-RUN mode (which write nothing).
Every domain is isolated: one failing check is reported as `error` and never hides the others. Reports carry record ids, order
numbers, operation keys and counts - never names, e-mail addresses, mobile numbers, addresses or bank details.
"""
import logging
from datetime import datetime, timedelta, timezone

from core import db, now_iso
from money import paise_of

logger = logging.getLogger("homegenies")
LIMIT = 100              # ids listed per issue type (counts are always complete)


def _domain(checks: dict, issues: list, attention: tuple) -> dict:
    """`attention` names the checks whose non-zero value means something needs a person (the others are informational)."""
    bad = any(checks.get(k) for k in attention)
    return {"status": "attention" if bad or issues else "ok", "checks": checks, "attention_checks": list(attention),
            "issues": issues[:LIMIT]}


async def payments() -> dict:
    issues, mismatch, unapplied, missing_tx = [], 0, 0, 0
    q = {"payment_status": "paid", "payment_method": {"$ne": "cod"}, "paid_session_id": {"$type": "string"}}
    async for o in db.orders.find(q, {"_id": 0, "id": 1, "order_number": 1, "paid_session_id": 1, "total_paise": 1, "total": 1}):
        tx = await db.payment_transactions.find_one({"session_id": o["paid_session_id"]}, {"_id": 0})
        if not tx:
            missing_tx += 1
            issues.append({"order": o.get("order_number") or o["id"], "issue": "paid_without_payment_attempt"})
            continue
        if tx.get("payment_status") != "paid":
            mismatch += 1
            issues.append({"order": o.get("order_number") or o["id"], "issue": "order_paid_attempt_not_paid"})
        gw = tx.get("gateway_amount_paise")
        if isinstance(gw, int) and gw != paise_of(o, "total_paise", "total"):
            mismatch += 1
            issues.append({"order": o.get("order_number") or o["id"], "issue": "gateway_amount_differs_from_order_total"})
    async for tx in db.payment_transactions.find({"payment_status": "paid"}, {"_id": 0, "session_id": 1, "order_id": 1}):
        o = await db.orders.find_one({"id": tx.get("order_id")}, {"_id": 0, "paid_session_id": 1, "duplicate_payments": 1,
                                                                   "order_number": 1, "needs_refund": 1, "payment_status": 1})
        if not o:
            unapplied += 1
            issues.append({"session": tx["session_id"], "issue": "paid_attempt_without_order"})
        elif o.get("paid_session_id") != tx["session_id"] and \
                not any(d.get("session_id") == tx["session_id"] for d in o.get("duplicate_payments") or []) and not o.get("needs_refund"):
            unapplied += 1
            issues.append({"order": o.get("order_number"), "session": tx["session_id"], "issue": "captured_not_applied_or_flagged"})
    from payment_events import STALE_SECONDS
    stale = (datetime.now(timezone.utc) - timedelta(seconds=STALE_SECONDS)).isoformat()
    ev = {s: await db.webhook_events.count_documents({"status": s}) for s in ("failed", "rejected", "unmatched")}
    ev_stuck = await db.webhook_events.count_documents({"status": "processing", "claimed_at": {"$lt": stale}})
    return _domain({"status_mismatch": mismatch, "attempt_missing": missing_tx, "captured_unapplied": unapplied,
                    "events_failed": ev["failed"], "events_stuck": ev_stuck,
                    "events_rejected_for_review": ev["rejected"], "events_unmatched_for_review": ev["unmatched"]}, issues,
                   ("status_mismatch", "attempt_missing", "captured_unapplied", "events_failed", "events_stuck"))


async def wallets() -> dict:
    from wallet_reconcile import reconcile
    r = await reconcile()
    dist = r["distribution_audit"]
    issues = [{"user_id": d.get("user_id"), "issue": d.get("issue") or f"{d.get('field')}_differs_by_{d.get('difference_paise')}_paise"}
              for d in r["discrepancies"]]
    issues += [{"commission_id": i["commission_id"], "issue": i["issue"]} for i in r["commission_issues"]]
    return _domain({"wallets_checked": r["wallets_checked"], "aggregate_issues": len(r["discrepancies"]),
                    "commission_intent_issues": len(r["commission_issues"]),
                    "distribution_incomplete_issues": len(dist["incomplete_plans"]),
                    "legacy_released_unverified": r["legacy_released_unverified"],
                    "legacy_flagged_without_plan": len(dist["flagged_without_plan"]),
                    "orphan_ledger_users": len(r["orphan_ledger_users"])}, issues,
                   ("aggregate_issues", "commission_intent_issues", "distribution_incomplete_issues"))


async def withdrawals() -> dict:
    from withdrawal_intents import withdrawal_audit
    a = await withdrawal_audit(limit_report=LIMIT)
    return _domain({"keyed_checked": a["keyed"], "legacy_unkeyed": a["legacy_unkeyed"], "reserving_now": a["reserving"],
                    "reserving_stuck": a["reserving_stale"], "record_issues": len(a["issues"]),
                    "effects_due": await db.withdrawal_requests.count_documents({"effects_due": True})}, a["issues"],
                   ("reserving_stuck", "record_issues"))


async def settlements() -> dict:
    import settlement_snapshot as SS
    a = await SS.audit(limit_report=LIMIT)
    issues = list(a["issues"])
    ledger_missing = 0
    async for s in db.settlements.find({"status": "paid"}, {"_id": 0, "id": 1, "number": 1}):
        if not await db.vendor_ledger.find_one({"source_key": f"settle:{s['id']}"}, {"_id": 1}):
            ledger_missing += 1
            issues.append({"settlement_id": s["id"], "number": s.get("number"), "issue": "paid_without_ledger_entry"})
    multi = await db.settlements.aggregate([{"$match": {"status": {"$in": ["requested", "approved"]}}},
                                            {"$group": {"_id": "$vendor_id", "n": {"$sum": 1}}}, {"$match": {"n": {"$gt": 1}}}]).to_list(None)
    issues += [{"vendor_id": m["_id"], "issue": "more_than_one_open_settlement"} for m in multi]
    return _domain({"with_snapshot": a["with_snapshot"], "legacy_without_snapshot": a["legacy_without_snapshot"],
                    "snapshot_issues": len(a["issues"]), "ledger_entry_missing": ledger_missing, "open_rule_issues": len(multi)}, issues,
                   ("snapshot_issues", "ledger_entry_missing", "open_rule_issues"))


async def vendor_ledger() -> dict:
    import ledger as L
    issues, overpaid, checked = [], 0, 0
    for vid in await db.vendor_ledger.distinct("vendor_id"):
        b = await L.balances(vid)
        checked += 1
        if b["pending_settlement_paise"] < 0:
            overpaid += 1
            issues.append({"vendor_id": vid, "issue": "settled_more_than_owed", "difference_paise": b["pending_settlement_paise"]})
    return _domain({"vendors_checked": checked, "vendors_overpaid": overpaid}, issues, ("vendors_overpaid",))


async def refunds() -> dict:
    from returns_routes import ensure_cases_for_flagged_orders
    dry = await ensure_cases_for_flagged_orders(dry_run=True, max_seconds=20)       # per obligation kind, dry run (writes nothing)
    missing = sum(int((r or {}).get("eligible", 0)) for r in dry.values())
    # P03-A15: money in on a cancelled order with NO obligation marker and NO case is invisible to the marker-driven sweep
    # (audit P03-A01 customer cancel, P03-A02 late payment crash, P03-A03 COD resolve after cancel). Reported, never repaired here.
    unmarked = []
    q = {"status": "cancelled", "payment_status": {"$in": ["paid", "partially_refunded"]}, "needs_refund": {"$ne": True},
         "refund_due_cancel": {"$ne": True}, "fulfilments.refund_due": {"$ne": True}, "late_payment_due": {"$exists": False}}
    async for o in db.orders.find(q, {"_id": 0, "id": 1, "order_number": 1}):
        if not await db.refund_cases.find_one({"order_id": o["id"]}, {"_id": 1}):
            unmarked.append({"order": o.get("order_number") or o["id"], "issue": "cancelled_with_money_in_and_no_refund_record"})
    states = {s: await db.refund_cases.count_documents({"status": s})
              for s in ("awaiting_review", "initiated", "confirmed", "failed", "resolved")}
    return _domain({"obligations_without_case": missing, "unrecorded_cancelled_money": len(unmarked), "cases_failed": states["failed"],
                    **{f"cases_{k}": v for k, v in states.items() if k != "failed"}}, unmarked,
                   ("obligations_without_case", "unrecorded_cancelled_money", "cases_failed"))


async def commissions() -> dict:
    from order_completion import completion_audit
    a = await completion_audit(limit_report=LIMIT)
    unfunded = await db.commission_plans.count_documents({"funding.sufficient": False})
    issues = [{"order": x, "issue": "paid_without_commission_plan"} for x in a["paid_without_plan"]]
    issues += [{"order_vendor": x, "issue": "paid_vendor_group_without_sale_entry"} for x in a["paid_vendor_groups_without_sale"]]
    return _domain({"completion_due": a["completion_due"], "completion_blocked_for_finance": a["completion_blocked"],
                    "plan_missing": len(a["paid_without_plan"]), "sale_entry_missing": len(a["paid_vendor_groups_without_sale"]),
                    "plans_unfunded_for_review": unfunded}, issues,
                   ("completion_due", "completion_blocked_for_finance", "plan_missing", "sale_entry_missing"))


async def stock() -> dict:
    from stock import run_recovery
    neg = await db.products.find({"$or": [{"stock": {"$lt": 0}}, {"variants.stock": {"$lt": 0}}]}, {"_id": 0, "id": 1}).to_list(LIMIT)
    rec = await run_recovery(limit=200, dry_run=True, max_seconds=20)

    def n(x):
        return (x.get("eligible", 0) + x.get("updated", 0)) if isinstance(x, dict) else int(x or 0)
    stuck = n(rec.get("txns")) + n(rec.get("intents"))
    return _domain({"stock_negative": len(neg), "journal_stuck": stuck},
                   [{"product_id": p["id"], "issue": "negative_stock"} for p in neg], ("stock_negative", "journal_stuck"))


LIABILITY_LIVE_STATES = ("awaiting_review", "initiated", "failed", "confirmed")      # a case that still owes or has paid money
MONEY_IN = ("paid", "partially_refunded", "refunded")


def _issue(severity: str, reason: str, remediation: str, order: dict = None, *, payment=None, liability=None, amount=None,
           gateway=None) -> dict:
    o = order or {}
    return {"severity": severity, "reason": reason, "order_id": o.get("id"), "order_number": o.get("order_number"),
            "payment_session": payment, "liability_id": liability, "amount_paise": amount, "currency": "INR",
            "gateway": gateway, "detected_at": now_iso(), "remediation": remediation}


async def _gateway(order: dict):
    sid = order.get("paid_session_id")
    if not sid:
        return None, None
    tx = await db.payment_transactions.find_one({"session_id": sid}, {"_id": 0, "provider": 1})
    return sid, (tx or {}).get("provider")


async def liabilities() -> dict:
    """Programme 03-B (P03-A01 / P03-A02): every captured payment is accounted for - a valid sale, a recorded refund obligation,
    a refund in progress / done, or a pending late-payment decision; and no obligation is duplicated or orphaned."""
    issues, c = [], {"cancelled_money_without_obligation": 0, "late_payment_unresolved": 0, "late_payment_pending": 0,
                     "refund_owed_order_active": 0, "refund_owed_order_has_revenue": 0, "duplicate_order_liability": 0,
                     "liabilities_exceed_money_in": 0, "orphan_liability": 0, "duplicate_payment_reference": 0}
    now = now_iso()
    # 1. money in on a cancelled order with no obligation of any kind (P03-A01 / P03-A02 / P03-A03 symptoms)
    q = {"status": "cancelled", "payment_status": {"$in": ["paid", "partially_refunded"]}, "needs_refund": {"$ne": True},
         "refund_due_cancel": {"$ne": True}, "fulfilments.refund_due": {"$ne": True}, "late_payment_due": {"$exists": False}}
    async for o in db.orders.find(q, {"_id": 0, "id": 1, "order_number": 1, "paid_session_id": 1, "total_paise": 1, "total": 1}):
        if not await db.refund_cases.find_one({"order_id": o["id"]}, {"_id": 1}):
            c["cancelled_money_without_obligation"] += 1
            sid, gw = await _gateway(o)
            issues.append(_issue("critical", "cancelled_order_with_captured_money_and_no_obligation", "open_refund_obligation",
                                 o, payment=sid, amount=paise_of(o, "total_paise", "total"), gateway=gw))
    # 2. late payments whose decision is still pending (lease expired = interrupted; else in progress)
    async for o in db.orders.find({"late_payment_due": {"$exists": True}}, {"_id": 0, "id": 1, "order_number": 1, "late_payment_due": 1,
                                                                            "total_paise": 1, "total": 1}):
        m = o["late_payment_due"]
        if (m.get("lease_until") or "") < now:
            c["late_payment_unresolved"] += 1
            tx = await db.payment_transactions.find_one({"session_id": m.get("session_id")}, {"_id": 0, "provider": 1}) or {}
            issues.append(_issue("high", "late_payment_decision_interrupted", "run_late_payment_repair", o, payment=m.get("session_id"),
                                 amount=paise_of(o, "total_paise", "total"), gateway=tx.get("provider")))
        else:
            c["late_payment_pending"] += 1
    # 3. a refund is owed, yet the order is active or earned revenue (the payment silently treated as a sale)
    async for o in db.orders.find({"needs_refund": True}, {"_id": 0, "id": 1, "order_number": 1, "status": 1, "paid_session_id": 1,
                                                         "total_paise": 1, "total": 1}):
        sid, gw = await _gateway(o)
        if o.get("status") != "cancelled":
            c["refund_owed_order_active"] += 1
            issues.append(_issue("high", "refund_owed_but_order_active", "finance_review", o, payment=sid, gateway=gw))
        sales = await db.vendor_ledger.aggregate([{"$match": {"order_id": o["id"], "type": {"$in": ["SALE_COLLECTED", "SALE_REVERSAL"]}}},
                                                  {"$group": {"_id": None, "n": {"$sum": "$amount_paise"}}}]).to_list(1)
        if await db.commission_plans.find_one({"_id": o["id"]}, {"_id": 1}) or (sales and sales[0]["n"] > 0):
            c["refund_owed_order_has_revenue"] += 1
            issues.append(_issue("high", "refund_owed_order_recorded_as_revenue", "finance_review", o, payment=sid, gateway=gw))
    # 4. duplicated / orphaned liabilities
    per_order = await db.refund_cases.aggregate([
        {"$match": {"status": {"$in": list(LIABILITY_LIVE_STATES)}}},
        {"$group": {"_id": "$order_id", "total": {"$sum": "$amount_paise"}, "kinds": {"$push": "$kind"}, "ids": {"$push": "$id"},
                    "amounts": {"$push": "$amount_paise"}, "states": {"$push": "$status"}}}]).to_list(None)
    for g in per_order:
        o = await db.orders.find_one({"id": g["_id"]}, {"_id": 0, "id": 1, "order_number": 1, "payment_status": 1, "total_paise": 1,
                                                        "total": 1, "paid_session_id": 1, "refunded_paise": 1, "refunded_amount": 1})
        if not o or o.get("payment_status") not in MONEY_IN:
            c["orphan_liability"] += 1
            issues.append(_issue("medium", "liability_without_money_in", "finance_review", o or {"id": g["_id"]},
                                 liability=g["ids"][0], amount=g["total"]))
            continue
        order_level = [k for k in g["kinds"] if k in ("cancellation", "late_payment")]
        if len(order_level) > 1:
            c["duplicate_order_liability"] += 1
            issues.append(_issue("high", "more_than_one_order_level_liability", "finance_review_duplicate", o, liability=",".join(g["ids"]),
                                 amount=g["total"]))
        open_total = sum(a for a, st in zip(g["amounts"], g["states"]) if st in ("awaiting_review", "initiated", "failed"))
        remaining = paise_of(o, "total_paise", "total") - paise_of(o, "refunded_paise", "refunded_amount")
        if open_total > remaining:            # open promises beyond the money still held (confirmed refunds already reduced it)
            c["liabilities_exceed_money_in"] += 1
            issues.append(_issue("high", "liabilities_exceed_money_in", "finance_review_duplicate", o, liability=",".join(g["ids"]),
                                 amount=open_total))
    # 5. one gateway payment / bank reference used for more than one order
    for field in ("razorpay_payment_id", "reference"):
        dup = await db.payment_transactions.aggregate([
            {"$match": {field: {"$type": "string", "$ne": ""}}},
            {"$group": {"_id": f"${field}", "orders": {"$addToSet": "$order_id"}}},
            {"$match": {"orders.1": {"$exists": True}}}]).to_list(None)
        for d in dup:
            c["duplicate_payment_reference"] += 1
            issues.append(_issue("high", f"{field}_used_for_more_than_one_order", "finance_review",
                                 {"id": ",".join(sorted(x for x in d["orders"] if x))}))
    return _domain(c, issues, ("cancelled_money_without_obligation", "late_payment_unresolved", "refund_owed_order_active",
                               "refund_owed_order_has_revenue", "duplicate_order_liability", "liabilities_exceed_money_in",
                               "orphan_liability", "duplicate_payment_reference"))


DOMAINS = {"payments": payments, "wallets": wallets, "withdrawals": withdrawals, "settlements": settlements,
           "vendor_ledger": vendor_ledger, "refunds": refunds, "commissions": commissions, "stock": stock,
           "liabilities": liabilities}


async def run(domains=None) -> dict:
    """The full report (or the named domains). Read-only; safe to run at any time."""
    out = {"generated_at": now_iso(), "read_only": True, "domains": {}}
    for name, fn in DOMAINS.items():
        if domains and name not in domains:
            continue
        try:
            out["domains"][name] = await fn()
        except Exception as e:                      # one domain failing never hides the others
            logger.exception("reconciliation domain %s failed", name)
            out["domains"][name] = {"status": "error", "error": type(e).__name__, "checks": {}, "issues": []}
    st = [d["status"] for d in out["domains"].values()]
    out["status"] = "error" if "error" in st else ("attention" if "attention" in st else "ok")
    return out
