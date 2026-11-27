"""Platform cron endpoints (secret-gated, ack-fast)."""
import os
import hmac
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from pymongo.errors import DuplicateKeyError

from core import db, now_iso, new_id

log = logging.getLogger("homegenies")
router = APIRouter(prefix="/api/cron", tags=["cron"])

# Programme 01 (B-005): one cron invocation spends at most this long on sweeps (the platform stops a function at 60 s). Every
# sweep is resumable, so work that does not fit continues from its checkpoint on the next run.
RUN_BUDGET_SECONDS = float(os.environ.get("CRON_RUN_BUDGET_SECONDS") or 40)

# WEBHOOK_CRON_SECRET (Emergent) or CRON_SECRET (Vercel Cron sends it as a Bearer token).
CRON_SECRET = os.environ.get("WEBHOOK_CRON_SECRET") or os.environ.get("CRON_SECRET", "")


def _authorise(request: Request):
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer ") or not CRON_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth.split(" ", 1)[1].strip()
    if not hmac.compare_digest(token, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")


async def _run_release(run_id: str):
    from commission import release_due_points
    try:
        # Programme 01 (B-005): bounded run (Vercel functions stop at 60 s); the next run resumes from the checkpoint
        result = await release_due_points(max_seconds=RUN_BUDGET_SECONDS)
        await db.cron_runs.update_one({"run_id": run_id},
                                      {"$set": {"status": "done", "result": result, "finished_at": now_iso()}})
    except Exception as e:  # pragma: no cover - defensive
        log.exception("points release failed")
        await db.cron_runs.update_one({"run_id": run_id},
                                      {"$set": {"status": "failed", "error": str(e), "finished_at": now_iso()}})


@router.post("/release-points")
async def release_points(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _authorise(request)
    try:
        envelope = await request.json()
    except Exception:
        envelope = {}
    run_id = request.headers.get("x-webhook-id") or envelope.get("run_id") or new_id()
    existing = await db.cron_runs.find_one({"run_id": run_id}, {"_id": 0})
    if existing:
        return {"ok": True, "duplicate": True, "run_id": run_id}
    try:
        await db.cron_runs.insert_one({"id": new_id(), "run_id": run_id, "job": "release-points",
                                       "status": "queued", "created_at": now_iso()})
    except DuplicateKeyError:            # W5: a concurrent delivery of the same run won (unique index cron_runs_run_id_unique)
        return {"ok": True, "duplicate": True, "run_id": run_id}
    background.add_task(_run_release, run_id)
    return {"ok": True, "run_id": run_id}


@router.get("/release-points")
async def release_points_vercel(request: Request):
    """Vercel Cron calls GET once a day. Serverless functions can't run work after responding,
    so this runs the (idempotent) release inline; one run per UTC day."""
    _authorise(request)
    from datetime import datetime, timezone
    run_id = "vercel-" + datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if await db.cron_runs.find_one({"run_id": run_id, "status": "done"}, {"_id": 0}):
        return {"ok": True, "duplicate": True, "run_id": run_id}
    await db.cron_runs.update_one({"run_id": run_id}, {"$setOnInsert": {"id": new_id(), "run_id": run_id, "job": "release-points",
                                                                       "created_at": now_iso()}, "$set": {"status": "running"}}, upsert=True)
    await _run_release(run_id)
    return {"ok": True, "run_id": run_id, "result": (await db.cron_runs.find_one({"run_id": run_id}, {"_id": 0})).get("result")}


@router.get("/expire-pending-orders")
async def expire_pending_orders(request: Request):
    """Cancels unpaid online orders older than the payment window and returns their reserved stock.
    Idempotent. (Vercel Hobby cron runs at most daily; checkout and order views also run this sweep.)"""
    _authorise(request)
    started = now_iso()
    result = await run_maintenance(RUN_BUDGET_SECONDS)
    # Programme 01 (B-005): every maintenance run leaves a record (counts, failures by record key; no personal data)
    await db.cron_runs.insert_one({"id": new_id(), "run_id": "maint-" + new_id(), "job": "maintenance", "status": "done",
                                   "created_at": started, "finished_at": now_iso(), "result": result})
    return {"ok": True, **result}


async def run_maintenance(budget_seconds: float = None, dry_run: bool = False) -> dict:
    """Programme 01 (B-003 / B-005): the daily repair pass, in dependency order, within one time budget. Every step is
    idempotent and resumable; a step that runs out of time continues from its checkpoint next time. `dry_run` reports what
    each sweep would change and writes nothing (expiry, stock recovery and marker pruning are skipped in a dry run)."""
    import time
    from stock import expire_pending_online_orders, prune_stock_markers
    from ledger import reconcile_ledger
    from finance_routes import reconcile_settlements
    from returns_routes import reconcile_returns, ensure_cases_for_flagged_orders
    from vendor_routes import sweep_dispatch_deadlines
    from order_completion import repair_incomplete_completions
    end = None if budget_seconds is None else time.monotonic() + budget_seconds

    def left():
        return None if end is None else max(end - time.monotonic(), 1.0)
    out = {"dry_run": dry_run}
    if not dry_run:
        out["expired"] = await expire_pending_online_orders(limit=500, max_seconds=left())      # also runs crash recovery
    else:                                   # DEF-03: what stock crash recovery and the expiry self-heal would do
        from stock import run_recovery, heal_stuck_expiries
        out["stock_recovery"] = await run_recovery(limit=200, dry_run=True, max_seconds=left())
        out["stuck_expiries"] = await heal_stuck_expiries(limit=200, dry_run=True, max_seconds=left())
    out["completion_repair"] = await repair_incomplete_completions(dry_run=dry_run, max_seconds=left())   # paid orders finished first
    from withdrawal_intents import repair_withdrawal_requests
    out["withdrawal_requests"] = await repair_withdrawal_requests(dry_run=dry_run, max_seconds=left())   # P03 B-022
    out["refund_obligations"] = await ensure_cases_for_flagged_orders(dry_run=dry_run, max_seconds=left())   # every obligation has its case
    out["returns_repaired"] = await reconcile_returns(dry_run=dry_run, max_seconds=left())
    if not dry_run:
        out["markers_pruned"] = await prune_stock_markers(max_seconds=left())      # W5: complete, resumable sweep
        out["deadline_alerts"] = await sweep_dispatch_deadlines(max_seconds=left())
    out["ledger"] = await reconcile_ledger(dry_run=dry_run, max_seconds=left())
    out["settlements_repaired"] = await reconcile_settlements(dry_run=dry_run, max_seconds=left())
    return out
