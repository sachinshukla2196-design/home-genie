"""Add exact integer-paise twins to stored money fields (additive, idempotent, verified).

Usage (run from the backend folder; needs MONGO_URL and DB_NAME in the environment):
    python3 scripts/migrate_money_paise.py            # DRY RUN: report only, nothing is changed
    python3 scripts/migrate_money_paise.py --apply    # add the missing *_paise fields, then verify
    python3 scripts/migrate_money_paise.py --verify   # verification report only

Original float fields are never modified. Always run the dry run first and keep the printed totals.
Never run against production without a database backup and the owner's approval.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main():
    import money_migration as mm
    from core import db
    mode = "apply" if "--apply" in sys.argv else "verify" if "--verify" in sys.argv else "dry-run"
    print(f"database: {os.environ.get('DB_NAME')}   mode: {mode}")
    if mode == "apply":
        print("BEFORE:", json.dumps(await mm.plan(db), indent=2, default=str))
        print("ADDED :", json.dumps(await mm.apply(db), indent=2))
    elif mode == "dry-run":
        print(json.dumps(await mm.plan(db), indent=2, default=str))
        print("\nNothing was changed. Re-run with --apply to add the missing fields.")
        return
    report = await mm.verify(db)
    print("VERIFY:", json.dumps(report, indent=2))
    print("\nRESULT:", "ALL TOTALS RECONCILE" if report["ok"] else "MISMATCH - investigate before relying on paise fields")
    sys.exit(0 if report["ok"] else 1)


asyncio.run(main())
