"""READ-ONLY historical financial audit. Run it against a database an authorised operator has chosen.

It prints (or writes with --out) a JSON report: duplicate wallets, legacy commission distributions, index readiness and
the migration dry run. It writes nothing to the database and has no option that would apply a repair.

Usage (MONGO_URL and DB_NAME must be set in the environment; never paste credentials into a command or a report):
    python scripts/historical_audit.py                       # prints the report
    python scripts/historical_audit.py --out report.json     # writes the report to a local file
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def main() -> None:
    from historical_audit import full_audit
    report = asyncio.run(full_audit())
    text = json.dumps(report, indent=2, default=str, sort_keys=True)
    if "--out" in sys.argv:
        path = sys.argv[sys.argv.index("--out") + 1]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"report written to {path}")
    else:
        print(text)


if __name__ == "__main__":
    main()
