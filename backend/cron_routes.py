"""Platform cron endpoints (secret-gated, ack-fast)."""
import os
import hmac
import asyncio
import logging
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from core import db, now_iso, new_id

log = logging.getLogger("homegenies")
router = APIRouter(prefix="/api/cron", tags=["cron"])

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
        result = await release_due_points()
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
    await db.cron_runs.insert_one({"id": new_id(), "run_id": run_id, "job": "release-points",
                                   "status": "queued", "created_at": now_iso()})
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
