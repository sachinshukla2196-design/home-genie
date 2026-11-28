# HOME GENIES — Deployment runbook: P1-01 index migration + release of `main` @ `041db6d`

For: the owner / whoever holds production MongoDB and Vercel access. Nothing here has been run against production.
Release contents: Programme 01, 02, 03 and 03-B (all on `main`).

**Why the order matters:** since Programme 01 the API refuses every money write (orders, payments, refunds, withdrawals,
settlements, stock) with HTTP 503 `FIN_INDEX_NOT_READY` until its protective unique indexes exist. Deploy the API before the
migration and checkout stops working. The migration is repeatable, never deletes records, and is a dry run unless `--apply` is given.

## 0. Before you start
- [ ] A quiet window (no checkout traffic expected for ~30 min).
- [ ] A **verified backup** of the production database (take it, then confirm you can list / restore it).
- [ ] A machine with Python 3.11+ and this repository checked out at `main` (`git checkout main && git pull`, HEAD `041db6d`).
- [ ] `pip install -r backend/requirements.txt` in a virtualenv.
- [ ] Production `MONGO_URL` and `DB_NAME` exported in that shell only (never commit or paste them anywhere).

All commands run from `backend/`.

## 1. Read-only checks (write nothing)
```bash
python scripts/db_maintenance_report.py > pre_report.json        # what the migration would create / refuse, duplicates, money areas
python scripts/vendor_foundation_migrate.py > pre_migrate.json   # migration dry run
python scripts/financial_reconciliation_report.py > pre_recon.json; echo "recon exit $?"   # 0 ok, 1 attention, 2 check error
```
**Stop and resolve before step 2 if** `pre_report.json` → `index_dry_run` lists any index it would *refuse* or any
`money_duplicates`, or `pre_migrate.json` → `duplicates` is non-empty. A unique index cannot be built over duplicate records; those
records need a person to decide (do not delete them blindly). Keep `pre_recon.json` as the baseline (attention items found here
pre-date this release).

## 2. Apply the indexes
```bash
python scripts/vendor_foundation_migrate.py --apply > migrate.json
python scripts/db_maintenance_report.py > post_report.json
```
Check: `migrate.json` → `indexes_failed` is `[]`; `post_report.json` → `money_protection` shows every area writable and
`last_migration` has outcome success. Running `--apply` again must change nothing.
This also creates the Programme 03 / 03-B indexes (withdrawal requests, settlement snapshots, `orders_late_payment_due`).

## 3. Deploy the API (`deploy/vercel-api`)
```bash
cd deploy/vercel-api && ./sync-backend.sh && vercel deploy --prod
```
(Vercel CLI logged in as the project owner. On the Hobby plan Vercel blocks deployments of commits not authored by the owner —
see `.github/workflows/deploy-frontend.yml`; deploy from the owner's account or a Pro team.)
If the API was already running before step 2, **wait 15 s or redeploy/restart** after the migration: a running instance caches
"not ready" for up to 15 s (P03B-OPS-01).

## 4. Deploy the frontend
GitHub → Actions → "Deploy frontend to Vercel" → Run workflow (or `vercel deploy --prod` in `frontend/`).
`REACT_APP_BACKEND_URL` must be the API's `https://` origin (the build refuses anything else).

## 5. Verify (≤ 15 min)
- [ ] `GET https://<api>/api/health` → `{"status":"ok"}`.
- [ ] Finance user → Finance → System integrity (`/api/admin/finance/system-integrity`): every money area ready.
- [ ] Place one small real order end to end with a staff card / UPI (owner's choice), see it marked paid, then cancel it from the
      customer's order page: the order shows cancelled and one refund case appears in Finance → Refunds (`awaiting_review`).
      Process that refund through the normal two-person flow.
- [ ] `python scripts/financial_reconciliation_report.py` → compare with `pre_recon.json`: no new attention items
      (`liabilities` domain is new in this release — anything it reports is a pre-existing record to review, not a deploy fault).
- [ ] Vercel → API logs: no `money write refused` lines after the first minute.

## 6. Roll back
- Code: Vercel → Deployments → previous production deployment → "Promote to production" (API and frontend separately).
- Indexes: leave them. The older code does not depend on their absence, and they never delete data.
- Data: restore the step-0 backup only if a data problem is proven; it discards orders placed since.

## Still open at release (not fixed by deploying)
Open launch-blocking owner decisions (29, `HOME_GENIES_OWNER_DECISION_REGISTER.md`), P03-A03 (cash-on-delivery collection on a
cancelled order — detected by reconciliation), VG-07 (production behaviour never verified — this runbook's step 5 is the first check).
