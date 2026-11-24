"""Programme 02 / W5: READ-ONLY database maintenance report. Safe to run against any database: it writes nothing.

It prints, as JSON:
  - index_dry_run      : what the index migration would create / refuse (with duplicate counts) / replace, and open conflicts
  - money_protection   : which money areas are writable (B-004 protective indexes present exactly)
  - money_duplicates   : business keys held by more than one record, with record ids (for a person to resolve)
  - last_migration     : the most recent index migration run (spec version, outcome) - `index_migrations`
  - sweeps             : repair-job checkpoints, open failures per job and the last completed pass
  - retention          : TTL / retention eligibility (counts only; no periods - owner decision P0-05)

Usage (MONGO_URL and DB_NAME must be set):
    python scripts/db_maintenance_report.py
The index migration itself stays `python scripts/vendor_foundation_migrate.py [--apply]` (after a verified backup).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import db_indexes  # noqa: E402
import money_guard  # noqa: E402
import retention  # noqa: E402
from core import db  # noqa: E402


async def sweeps_state() -> dict:
    jobs = {}
    async for ck in db.job_checkpoints.find({}):
        name, _, tail = str(ck["_id"]).partition(":")
        j = jobs.setdefault(name, {})
        if tail == "last_complete":
            j["last_complete"] = {"at": ck.get("at"), "scanned": ck.get("scanned"), "failed": ck.get("failed")}
        else:
            j["in_progress_after"] = ck.get("last_key")
            j["checkpoint_updated_at"] = ck.get("updated_at")
    async for f in db.job_failures.aggregate([{"$group": {"_id": "$job", "open": {"$sum": 1}, "max_attempts": {"$max": "$attempts"}}}]):
        jobs.setdefault(f["_id"], {})["open_failures"] = {"records": f["open"], "max_attempts": f["max_attempts"]}
    return jobs


async def main() -> dict:
    return {"database": os.environ.get("DB_NAME"), "spec_version": db_indexes.spec_version(),
            "index_dry_run": await db_indexes.dry_run(),
            "money_protection": await money_guard.readiness(force=True),
            "money_duplicates": await money_guard.duplicate_report(),
            "last_migration": await db.index_migrations.find_one({}, sort=[("started_at", -1)]),
            "sweeps": await sweeps_state(),
            "retention": await retention.expiry_report()}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), indent=2, default=str))
