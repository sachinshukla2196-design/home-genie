import os
import hmac
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from core import db, now_iso
from club_income import distribute_club_income

router = APIRouter(prefix="/api/cron", tags=["cron"])
log = logging.getLogger("cron")


def _auth(request: Request):
    secret = os.environ.get("WEBHOOK_CRON_SECRET") or ""
    hdr = request.headers.get("authorization") or ""
    token = hdr[7:] if hdr.startswith("Bearer ") else ""
    if not secret or not token or not hmac.compare_digest(token, secret):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _previous_month() -> str:
    first = datetime.now(timezone.utc).replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


async def _run_club(month: str, run_id: str):
    try:
        res = await distribute_club_income(month, f"cron:{run_id}")
        log.info("club income %s: %s qualifiers, ₹%s, newly %s", month, res["qualifiers"], res["total_payout"], res["newly_credited"])
    except Exception as e:  # noqa
        log.exception("club income cron failed: %s", e)
        await db.cron_runs.update_one({"id": run_id}, {"$set": {"status": "failed", "error": str(e)}})


@router.post("/club-income")
async def cron_club_income(request: Request, bg: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _auth(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    run_id = request.headers.get("x-webhook-id") or (body or {}).get("run_id") or now_iso()
    if await db.cron_runs.find_one({"id": run_id}):
        return {"ok": True, "duplicate": True}
    month = _previous_month()
    await db.cron_runs.insert_one({"id": run_id, "job": "club-income", "month": month, "status": "queued", "created_at": now_iso()})
    bg.add_task(_run_club, month, run_id)
    return {"ok": True, "month": month, "run_id": run_id}
