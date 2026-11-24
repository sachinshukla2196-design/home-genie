"""Programme 01 operational check and repair. REPORT ONLY unless `--apply` is given.

What it does (MONGO_URL and DB_NAME must point at the database to check):
  - money protection: which money areas are blocked because a protective unique index is missing or different (B-004);
  - duplicate business keys that would stop those indexes from being created, by record id (B-004) - never deleted here;
  - paid orders still awaiting their post-payment completion, or blocked for finance (B-003);
  - vendor groups returned to origin BEFORE Programme 01 with no refund case (B-001) - for a finance decision, never changed;
  - every repair sweep in dry-run: how many records each would change (B-003 / B-005).
With `--apply` it then runs the daily maintenance pass for real (the same idempotent, resumable sweeps the cron runs).
It never creates or changes an index: that is `scripts/vendor_foundation_migrate.py --apply`, after a verified backup.

Usage:
    python scripts/programme01_reconcile.py              # report only
    python scripts/programme01_reconcile.py --apply      # report, then run the maintenance sweeps
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


async def main(apply: bool) -> dict:
    from money_guard import readiness, duplicate_report
    from order_completion import completion_audit
    from returns_routes import historical_rto_report
    from cron_routes import run_maintenance
    report = {"apply": apply,
              "money_protection": await readiness(force=True),
              "money_duplicates": await duplicate_report(),
              "completion": await completion_audit(),
              "historical_rto_without_case": await historical_rto_report(),
              "dry_run": await run_maintenance(budget_seconds=None, dry_run=True)}
    if apply:
        if not report["money_protection"]["ready"]:
            report["applied"] = "refused: protective indexes are not ready (run the index migration first)"
        else:
            report["applied"] = await run_maintenance(budget_seconds=None)
    return report


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main("--apply" in sys.argv)), indent=2, default=str))
