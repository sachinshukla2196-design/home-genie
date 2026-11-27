"""Programme 03: READ-ONLY financial reconciliation report. Safe to run against any database: it writes nothing.

Prints, as JSON, the same report as GET /api/admin/finance/reconciliation (reconciliation.run): payments, wallets, withdrawals,
settlements, vendor ledger, refunds, commissions and stock - each `ok`, `attention` (with record ids / order numbers / operation
keys) or `error`. No names, contact details or bank details are printed.

Usage (MONGO_URL and DB_NAME must be set):
    python scripts/financial_reconciliation_report.py [domain ...]
Exit code: 0 when every domain is ok, 1 when any needs attention, 2 when a check failed to run.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import reconciliation  # noqa: E402


def main() -> int:
    wanted = sys.argv[1:] or None
    unknown = [d for d in (wanted or []) if d not in reconciliation.DOMAINS]
    if unknown:
        print(f"unknown domain(s): {unknown}; choose from {list(reconciliation.DOMAINS)}", file=sys.stderr)
        return 2
    rep = asyncio.run(reconciliation.run(wanted))
    print(json.dumps(rep, indent=2, default=str))
    return {"ok": 0, "attention": 1}.get(rep["status"], 2)


if __name__ == "__main__":
    sys.exit(main())
