"""Programme 01 (B-005): one resumable, keyset-paginated sweep runner for every repair / release job.

Why: the old jobs read `find(...).sort(...).limit(N)` and stopped, so records beyond the first N (oldest 500 paid orders, first
5,000 commissions, first 200 flagged orders) were never reached. Offset pagination (`skip`) is not used either: inserts and state
changes during a run shift offsets and skip or repeat records.

How:
  - Records are read in batches ordered by a STABLE UNIQUE key (default `id`, a UUID string; `_id` where a collection has no
    `id`), each batch strictly after the last key seen: `{key: {$gt: last}}`. A record changing state mid-run is never read
    twice in a pass; a record inserted mid-run is either reached in this pass or in the next one.
  - After each batch the last key is written to `job_checkpoints` (one document per job). An interrupted run (crash, time limit)
    resumes after that key. A pass that reaches the end clears the checkpoint, so the next run starts a fresh full pass.
  - Every record runs in its own try/except: one failure is counted and reported, and the sweep continues.
  - `dry_run=True` never writes: not the handler (it is told), not the checkpoint.
  - `max_seconds` stops a run early (Vercel functions have a hard limit) with the checkpoint saved; the next run continues.

Handlers return one of: "updated" (changed something), "eligible" (would change - dry run), "skipped", "blocked".
Handlers must be idempotent: the record after the checkpoint may be re-processed after a crash.

DEF-03 (2026-11-24) additions, used by every sweep:
  - A record whose handler raises is recorded in `job_failures` (`_id` = "<job>:<key>", attempts, last error, first / last time).
    It stays eligible, so the next pass retries it; when it later succeeds its failure record is removed. `failures_open` in the
    summary is the number of records of this job still failing.
  - Every run that did something (changed, would change, blocked, failed or stopped early) is recorded in `job_runs` with its
    counts. An idle run (nothing scanned, no checkpoint) writes nothing at all, so the frequent request-time calls stay cheap.
"""
import logging
import time
from typing import Awaitable, Callable, Optional

from core import db, now_iso

logger = logging.getLogger("homegenies")

OUTCOMES = ("updated", "eligible", "skipped", "blocked")


async def run_sweep(job: str, collection: str, query: dict, handler: Callable[[dict, bool], Awaitable[str]], *,
                    key: str = "id", batch: int = 200, dry_run: bool = False, max_seconds: Optional[float] = None,
                    projection: Optional[dict] = None, resume: bool = True, max_failures_reported: int = 50) -> dict:
    ck = await db.job_checkpoints.find_one({"_id": job}) if resume else None
    last = (ck or {}).get("last_key")
    started = time.monotonic()
    started_at = now_iso()
    out = {"job": job, "dry_run": dry_run, "resumed_from": last, "scanned": 0, **{k: 0 for k in OUTCOMES}, "failed": 0,
           "failures": [], "complete": False}
    # keys of this job that failed on an earlier run: a success clears their failure record (DEF-03). W5: all of them - this read
    # was capped at 1,000, so a later success left the failure records beyond the cap open for good (keys only; small documents).
    failing = {f["key"] for f in await db.job_failures.find({"job": job}, {"_id": 0, "key": 1}).to_list(None)}
    proj = dict(projection) if projection else None
    if proj is not None and proj.get(key) == 0:
        proj.pop(key)
    if proj is not None and key not in proj and any(v for v in proj.values()):
        proj[key] = 1
    while True:
        q = query if last is None else {"$and": [query, {key: {"$gt": last}}]}
        docs = await db[collection].find(q, proj).sort(key, 1).limit(batch).to_list(batch)
        if not docs:
            out["complete"] = True
            break
        for d in docs:
            out["scanned"] += 1
            rkey = str(d.get(key))
            try:
                res = await handler(d, dry_run)
                out[res if res in OUTCOMES else "skipped"] += 1
                if rkey in failing and not dry_run:
                    await db.job_failures.delete_one({"_id": f"{job}:{rkey}"})
                    failing.discard(rkey)
            except Exception as e:          # one bad record never stops the sweep
                out["failed"] += 1
                err = f"{type(e).__name__}: {str(e)[:200]}"
                if len(out["failures"]) < max_failures_reported:
                    out["failures"].append({"key": rkey, "error": err})
                logger.exception("sweep %s: record %s failed", job, d.get(key))
                if not dry_run:             # retryable: the record stays eligible; the next pass tries it again
                    await db.job_failures.update_one({"_id": f"{job}:{rkey}"},
                                                     {"$set": {"job": job, "key": rkey, "last_error": err, "last_at": now_iso()},
                                                      "$setOnInsert": {"first_at": now_iso()}, "$inc": {"attempts": 1}}, upsert=True)
                    failing.add(rkey)
            last = d.get(key)
        if not dry_run:
            await db.job_checkpoints.update_one({"_id": job}, {"$set": {"last_key": last, "updated_at": now_iso()},
                                                               "$setOnInsert": {"started_at": now_iso()}}, upsert=True)
        if len(docs) < batch:
            out["complete"] = True
            break
        if max_seconds is not None and time.monotonic() - started > max_seconds:
            break
    out["next_key"] = None if out["complete"] else last
    out["failures_open"] = len(failing)
    idle = out["scanned"] == 0 and ck is None
    if out["complete"] and not dry_run and not idle:
        await db.job_checkpoints.delete_one({"_id": job})
        await db.job_checkpoints.update_one({"_id": f"{job}:last_complete"}, {"$set": {"at": now_iso(), "scanned": out["scanned"],
                                                                                       "failed": out["failed"]}}, upsert=True)
    active = out["updated"] or out["eligible"] or out["blocked"] or out["failed"] or not out["complete"]
    if active and not dry_run:              # DEF-03: an execution record for every run that did (or left) something
        await db.job_runs.insert_one({"job": job, "started_at": started_at, "finished_at": now_iso(),
                                      **{k: out[k] for k in ("resumed_from", "next_key", "complete", "scanned", "updated", "eligible",
                                                             "skipped", "blocked", "failed", "failures_open")},
                                      "failures": out["failures"][:10]})
    return out
