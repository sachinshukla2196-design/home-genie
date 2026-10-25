"""Vendor foundation migration. A dry run unless `--apply` is given. Safe to repeat: a second run changes nothing.

It never deletes records. It fills missing vendor codes, moves the vendor code sequence past existing codes, creates the identity
indexes, and reports duplicates for a person to resolve.

Usage (MONGO_URL and DB_NAME must be set):
    python scripts/vendor_foundation_migrate.py            # report only
    python scripts/vendor_foundation_migrate.py --apply    # write
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from vendor_lifecycle import migrate  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(asyncio.run(migrate(apply="--apply" in sys.argv)), indent=2, default=str))
