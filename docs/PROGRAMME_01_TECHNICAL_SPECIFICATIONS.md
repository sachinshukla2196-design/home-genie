# HOME GENIES — Programme 01 technical specifications (money and data integrity)

Describes behaviour **as implemented** in the working tree after Programme 01 (baseline `main` @ `d31cb74`). Each section names
the code and the tests that prove it. Nothing here has been run against production; no production index migration has been run.

| § | Item | Backlog |
|---|---|---|
| 1 | Returned-to-origin financial handling | B-001 (P0) |
| 2 | Refund confirmation integrity | B-002 (P0) |
| 3 | Shared payment completion and recovery | B-003 (P0) |
| 4 | Financial index readiness | B-004 (P0) |
| 5 | Ledger repair and release jobs (sweeps) | B-005 (P1) |
| 6 | Stock reservation lifecycle and order-creation protection | B-006 (P1) |
| 7 | Admin media upload permissions | B-009 (P1) |
| 8 | Vendor contact state validation | B-008 (P1) |

---

## 1. Returned-to-origin (RTO) financial handling — B-001

**Source of truth.** A vendor group (one vendor's lines in an order, `orders.fulfilments[]`) reaches `returned_to_origin` only through
the vendor fulfilment API (`POST /api/vendor/orders/{id}/fulfilment`) along the server-enforced flow
`dispatched → delivery_failed → returned_to_origin` (re-dispatch allowed in between). A reason of at least 5 characters is required
(as for reject / cancel / delivery failed; the vendor screen already asked for one). An admin order-status change is never treated as
RTO or delivery.

**Money effect** — the same model as the owner-approved vendor rejection (G2). For a paid order (`paid` / `partially_refunded`):
1. The transition and `fulfilments.$.refund_due = true` are written in ONE conditional update (crash-safe marker).
2. The vendor's recorded sale for that group is reversed (`ledger.post_sale_reversal`, key `salerev:<order>:<vendor>`) and any
   platform commission charged on it returned (`commrev:` key). Idempotent.
3. ONE refund case for the group's lines plus their GST share (`returns_routes.settle_vendor_rejection`): kind `returned_to_origin`,
   key `rto:<order>:<vendor>`, capped by what is still refundable and not already promised. The marker is then cleared.
   **No money moves**: the case follows the two-person refund flow (§2).
4. HomeGenie commission is held while the case is open and, when the refund is confirmed, clawed back in proportion to the refund
   (`shop_routes._reverse_commission`) — the undelivered group's share. The remainder releases normally afterwards.
5. Stock returns only after the vendor's receipt inspection (`return-inspection`, resellable), once.

**Multi-vendor.** Vendor A delivered, vendor B RTO: only B's sale is reversed and only B's lines are owed; A's sale stands.
`financial_ops.has_open_case(order, vendor_id)` ignores open cases that belong to ANOTHER vendor's goods (their refund is that vendor's
share alone, `ledger.post_refund_shares`), so A's settlement is not held by B's case; order-wide cases still hold every vendor.
This replaces the Batch 12 rule "any open case holds every vendor" (the one test that encoded it, in `test_batch12_remediation.py`,
was updated with a comment).

**Crash window.** `eligibility.payout_block` returns `refund_due` while a not-supplied group still carries the marker (whole order for
commission; only that vendor for settlement). The repair sweep `ensure_cases_for_flagged_orders` reverses the sale and opens the case.

**Unpaid COD RTO:** no case, no ledger entries.

**Historical RTO (before Programme 01)** is never rewritten automatically (`SALE_BLOCKING_FULFILMENT` deliberately unchanged).
`returns_routes.historical_rto_report()` (report-only; also in `scripts/programme01_reconcile.py`) lists them with the group value and
whether the sale was reversed, for a finance decision.

**Not decided here:** proof of delivery / RTO evidence (D-04). The vendor's RTO step only records a liability and reverses the vendor's
own sale (the conservative direction); paying the customer still needs two finance admins.

Tests: `tests/test_programme01_rto.py` (13), cross-module scenarios 4, 9; browser: vendor RTO order, admin refund initiate + confirm.

## 2. Refund confirmation integrity — B-002

`awaiting_review → initiated (maker) → confirmed (a different finance admin)`. Confirmation calls
`shop_routes.reverse_order_financials(..., exact=True)`:
- **Exact booking:** more than is still refundable is REJECTED (never silently lowered); a zero amount or a non-refundable order is
  rejected. `why`: `exceeds_refundable` | `nothing_refundable` | `order_not_refundable`.
- **Confirmed only if** the refund event `<order>:refund:<reference>` exists, is `completed`, belongs to this case and is > 0.
  `amount_refunded_paise` comes from the event. A legacy event booked lower than the case (possible only before Programme 01) is
  recorded as `booking_shortfall_paise`.
- **Rejected / zero booking** (`returns_routes._booking_failed`): the confirmation claim is released, `last_booking_error` and a
  `booking_rejected` case event are recorded, audit `refund_case_booking_rejected`, HTTP 409 with a clear message. The case stays
  `initiated` (open), so every payout on the order stays held. Finance can fail it, re-initiate the right amount and confirm again,
  **with the same bank reference** (the rejected event booked nothing and is re-claimed atomically; concurrent retries book once).
- An interrupted booking returns 409 "confirm again with the same reference" and keeps the claim.
- A zero-value case can never be confirmed; it is closed with the finance `resolve` action (outcome `no_refund`).
- Unchanged: initiator ≠ confirmer; finance roles only; one reference per refund; a booked refund cannot be failed or resolved away.

Admin screen: the Operations queues (refunds, returns, settlements, support) now show each record's own status (they showed the member
badge "Selling role pending" for every row — a pre-existing display bug found in the browser check), using the existing `Pill`.

Tests: `tests/test_programme01_refund_integrity.py` (11), cross-module 5, 6; browser: rejected booking shows the error, never "confirmed".

## 3. Shared payment completion and recovery — B-003

**One step** — `order_completion.complete_paid_order(order_id, source=…)` — for every path that turns an order paid: the gateway
entry `_process_paid_order` (Stripe status poll and webhook, Razorpay verify), the Razorpay webhook (`payment_events.complete_paid_order`
delegates), admin UPI confirmation, admin manual payment, COD collection, COD discrepancy resolution, late-payment revival.
Idempotent steps: invoice if missing → vendor SALE entries (unique keys) → frozen HomeGenie commission plan + credits → one-time
"paid" notifications for online payments (`paid_notified`) → clear the marker, stamp `completion {outcome, source, at}`.

**Durable marker** `completion_due: true` is written in the SAME atomic update that claims the order paid. After a crash:
the same payment reported again finishes it (same `paid_session_id`; transaction record also completed), a repeated COD confirmation
finishes it, otherwise the repair sweep `order_completion.repair_incomplete_completions` (cron; keyset, checkpointed, dry-run) does.

**Must not earn:** refund owed (late payment), cancelled, unpaid → skipped, marker cleared with the reason. Refund booked BEFORE the
plan existed → `completion_blocked = "refunded_before_commission_plan"` (a fresh full plan would pay commission on refunded goods);
reported, never guessed.

Diagnostics: `order_completion.completion_audit()` (report-only); `GET /api/admin/finance/system-integrity` (finance; counts only).

Tests: `tests/test_programme01_completion.py` (17), cross-module 7, 8.

## 4. Financial index readiness — B-004

`money_guard.py` — areas and the unique indexes their idempotency relies on:

| Area | Index (`db_indexes.SPECS`) |
|---|---|
| ledger | `vendor_ledger_source_key_unique` |
| refunds | `refund_cases_source_key_unique` |
| wallet | `wallet_transactions_op_key_unique` (partial), `wallets_user_unique` |
| webhooks | `webhook_events_event_unique` (partial) |
| settlements | `settlements_one_open_per_vendor` (partial) |
| stock | `stock_txns_key_unique` |
| orders | `orders_order_number_unique` |

- **Exact check:** under its own name with exactly the specified keys, uniqueness, sparse and partial filter. Other options under the
  name, or the same keys under another name → `conflict`; absent → `missing`; database read error → not ready (fail closed).
- **Fail closed, HTTP 503 `FIN_INDEX_NOT_READY` ("Nothing was changed")** at: `ledger.post_entry`, `open_refund_case`, wallet writes
  (`financial_ops.ensure_ledger` / `move_wallet_once`, `core.wallet_apply` / `add_wallet_transaction`), settlement creation, stock
  journal, Razorpay webhook claim (gateway retries), order creation, refund engine, refund-case confirmation (before the claim),
  shared completion (before any write; the marker stays). Reads never check.
- **Cache:** per process; 300 s when ready, 15 s when not; `db_indexes.apply()` resets it in its own process. Other running instances
  pick up a completed migration within 15 s (observed in the browser check) — no restart needed.
- **Never creates or changes an index.** That stays the migration (`scripts/vendor_foundation_migrate.py --apply`), which refuses to
  build a unique index over duplicates.
- **Duplicates:** `money_guard.duplicate_report()` (read-only) lists each duplicated business key with its record ids; included in the
  migration output. Nothing is deleted or merged; the area stays blocked until a person resolves them.
- **Startup:** one log line per blocked area. New non-guard index specs: `orders_user_payment_status`, `order_submissions_expires`
  (TTL), `orders_completion_due` (partial).

### Owner deployment instruction (NOT executed in Programme 01)
1. Take a production backup and **verify** it (restore into a scratch database; compare document counts).
2. With production `MONGO_URL` / `DB_NAME`: `python backend/scripts/vendor_foundation_migrate.py` (dry run). Read `money_duplicates`
   and `indexes_plan`. If any money duplicates are listed, stop and decide each record with finance.
3. `python backend/scripts/vendor_foundation_migrate.py --apply`. Expect `indexes_failed: []` and `money_protection.ready: true`.
4. `python backend/scripts/programme01_reconcile.py` (report only): completion backlog, historical RTO without a case, sweep counts.
5. Deploy the Programme 01 code only after step 3 succeeded — before it, every money write is refused by design.

Tests: `tests/test_programme01_money_guard.py` (13), cross-module 13.

## 5. Ledger repair and release jobs — B-005

`sweeps.run_sweep(job, collection, query, handler, key="id", batch, dry_run, max_seconds)`: keyset pagination on a stable unique key
(`{key: {$gt: last}}`, never `skip`), checkpoint in `job_checkpoints` after every batch, resume after interruption, checkpoint cleared
when a pass completes (`<job>:last_complete` keeps counts), per-record try/except (failures counted and reported by record key; the
sweep continues), dry run writes nothing (not even the checkpoint), time budget. Summary: `scanned, updated, eligible, skipped,
blocked, failed, failures[], complete, resumed_from, next_key`.

Converted (old ceiling → none): ledger reconcile (500 oldest paid orders), commission release (5,000 × 3 phases), refund obligations
(200 × 3 kinds), returns repair (100), settlement repair (no isolation before), dispatch-deadline alerts (500), prepaid expiry
(100 / 500), UPI-claim expiry (100), completion repair (new). Old return keys are kept.

**Cron:** `/api/cron/expire-pending-orders` → `cron_routes.run_maintenance(budget)` in dependency order (expiry → completion repair →
refund obligations → returns → markers → deadlines → ledger → settlements) within `CRON_RUN_BUDGET_SECONDS` (default 40 s, below the
60 s platform limit); each run is stored in `cron_runs` (`job: maintenance`). `/api/cron/release-points` uses the same budget. Inline
callers are bounded (2–3 s). Finance: `POST /api/admin/finance/reconcile?dry_run=true` (applied runs audited).

**Safeguards:** entries are only added under unique business keys; an existing entry is never changed or deleted (`ledger.post_entry`
looks the key up first, the unique index decides races); release rules unchanged; money moves only through recorded intents.

**Limitation:** a full ledger pass costs ~5–10 ms per paid order on the local test database; at large volume a pass spans several
cron runs (it resumes). An incremental "dirty" marker is recommended later (Programme 05).

Tests: `tests/test_programme01_sweeps.py` (8), cross-module 10.

## 6. Stock reservation lifecycle and order-creation protection — B-006

**Order creation** (`order_protection.py`, before anything is reserved):
- Duplicate submission: same account + same cart (items, options, quantities, address, method) within `ORDER_SUBMIT_WINDOW_SECONDS`
  (60) returns the same order (`duplicate_submission: true`); one atomic claim per fingerprint (`order_submissions._id`); a failed
  attempt releases it; a paid or cancelled order frees it.
- Rate limits: per account `ORDER_CREATE_PER_USER_10MIN` (10), per IP `ORDER_CREATE_PER_IP_10MIN` (60, generous for shared networks);
  `RATE_LIMIT_SCALE` applies; 429 with `Retry-After`.
- Open-order cap `ORDER_OPEN_UNPAID_MAX` (5): online `pending` / UPI `claimed`, and COD orders with a seller group still `new`. At the
  cap the next order is refused (429, clear message). Nothing is cancelled.

**Reservation release:**
- Online `pending` orders expire after `PENDING_PAYMENT_TTL_MINUTES` (15, unchanged) — now a full keyset sweep.
- Payment in progress: a gateway payment recorded on the attempt (`razorpay_payment_id` or a gateway event) keeps the stock for
  `PAYMENT_IN_PROGRESS_GRACE_MINUTES` (60) more.
- Payment after expiry: existing late-payment rule (revive if stock remains, else refund owed + case); duplicates change nothing.
- **COD is never expired by this sweep.** COD stock returns only on seller rejection / pre-dispatch cancellation, customer cancellation
  of an untouched order or admin-confirmed cancellation — each exactly once. Automatic COD expiry is an owner decision (register).
- Stock journal unchanged: atomic per-line reservation, never negative, released once, per vendor group.

Tests: `tests/test_programme01_order_protection.py` (18, at production defaults), cross-module 11, 12. `tests/conftest.py` raises the
limits only for older suites that place many orders for one test account.

## 7. Admin media upload permissions — B-009

- `POST /api/admin/uploads/sign` (new): `super_admin`, `admin` only (`require_vendor_admin`, the guard of merchandising and the admin
  studio). Server-fixed folder `homegenies/platform/{products|merchandising}`, random id, `overwrite=false`, `jpg,png,webp`; secret
  never returned; rate-limited; audited (`admin_upload_signed`). Without Cloudinary it answers `{"configured": false}` (not an error).
- `POST /api/admin/uploads/image?kind=product|merchandising` (new) and `/api/admin/uploads/product-image` (now content roles only):
  real type sniffed from the bytes (header and name not trusted), 5 MB max, empty refused, server-chosen path
  (`home-genies/<folder>/<admin>/<uuid>.<ext>` — no traversal, no overwrite), recorded in `files`, audited; storage failure → 502,
  nothing recorded. The client file name is kept as a label only (basename, ≤120 chars).
- Vendor signing unchanged and vendor-only; a vendor's Cloudinary image must be in its own folder (platform-folder images accepted for
  admin-prepared products).
- Merchandising images must be validated uploads (`governance_routes.validate_platform_images`): our Cloudinary platform folder, a
  stored file on record and not deleted (`/api/files/...`, same site), or a bundled same-site asset (`/brand/...`). Existing sections
  keep their stored images; editing requires a valid one.
- Frontend: `ImageInput` `admin` / `kind` props (admin screens only): signs with the admin endpoint and otherwise uploads through the
  server. The admin product studio passes the flag through its step context. No visual change.
- **Local limitation:** on a plain-http `127.0.0.1` server the stored file URL is `http://…`, which the existing image validator refuses,
  so a banner cannot be SAVED with an uploaded image in that setup; the upload itself works and the file is served. Production (https)
  is unaffected; saving with a stored upload is covered by the API tests.

Tests: `tests/test_programme01_admin_media.py` (29), cross-module 14; browser: merchandising and admin studio uploads, refusal of an
external link, support / accounts refused.

## 8. Vendor contact state validation — B-008

`vendor_onboarding.normalise_indian_state`: accepts the canonical state / UT names (any letter case, extra spaces) and two-letter codes
(ISO 3166-2:IN plus common aliases CG, TS, UK, OD, DN, DD); returns the stored form (canonical name, or the upper-case code as sent);
rejects anything else. Contact-only saves cannot blank a stored state; drafts may leave it blank but never free text. Stored records are
never rewritten by validation.

Tests: `tests/test_programme01_vendor_state.py` (34), `test_vendor_foundation.py` (16/16); browser: contact save with state `RJ`.

---

## 9. DEF-03 correction — stock recovery completeness (2026-11-24)
Found by the master reconciliation (2026-11-24); corrected by a separate corrective package. §5 above described the money sweeps;
two stock-repair loops had been left on fixed limits.

**Causes (as found).**
- *Stock-journal crash recovery* — `stock.run_recovery(limit=20)`, called only from `expire_pending_online_orders` (daily cron and the
  2 s request-time call in order creation and the order list). Its two finders, `recover_stock_txns` and `process_restock_intents`,
  were `find(q).limit(limit)` with no sort, no checkpoint and no per-record error handling: a transaction or order that kept failing
  stayed at the head of the unsorted result and starved everything behind it, and one exception aborted the whole call.
- *Stuck-expiry self-heal* — inside `expire_pending_online_orders`: `find(stuck).limit(limit)` (limit 50 / 100 / 500 by caller) over
  orders cancelled by payment timeout or UPI-claim expiry whose stock was not fully returned. Same starvation / abort behaviour, and it
  released stock without re-checking that the order was still expired.

**Correction.**
- `stock.recover_stock_txns`, `stock.process_restock_intents` and the new `stock.heal_stuck_expiries` are resumable keyset sweeps
  (`sweeps.run_sweep`: stable `id` order, checkpoint per batch, per-record isolation, time budget, dry run). `limit` is now the page size,
  not a per-run ceiling. Jobs: `stock_txn_recovery`, `stock_restock_intents`, `stock_expiry_self_heal`.
- Each record is **re-checked immediately before it is acted on** (same eligibility query plus its id): a transaction finished meanwhile by
  its own request or another worker, or an order a late payment revived, is skipped.
- The stock effect is unchanged and exactly-once: the existing arbiter / per-line marker engine for journal transactions, the existing
  `release_stock` journal key per line and generation for releases. Retries, concurrent workers and duplicate scheduler calls cannot apply
  a line twice. No stock lifecycle rule changed; cash-on-delivery orders are never matched by either sweep.
- **Journal completeness (found while testing):** an abandoned reservation that had already committed (stock reserved, its order never
  saved) was given back to the counter, but `stock_movements` kept only the −1 reservation row. Such a rollback now first ensures the
  forward row exists and then writes one compensating row (`_id` `mv:<txn>:<line>:undo`, `compensates: true`, reason
  `reservation_abandoned`). The transaction is flagged `abandoned_after_commit` by both abandon paths (recovery and
  `abandon_reservation`). Rollbacks of transactions that never committed (a short line) still log nothing (net zero). Historical rolled-back
  reservations are not rewritten.
- `sweeps.run_sweep` (all sweeps): a failing record is recorded in `job_failures` (attempts, last error, first / last time), stays eligible
  and is retried on the next pass; its failure record is removed when it succeeds; `failures_open` is reported. Every run that changed,
  would change, blocked, failed or stopped early writes one `job_runs` record with its counts; an idle run (nothing scanned, no
  checkpoint) writes nothing, so the request-time calls stay cheap.
- The daily maintenance dry run (`cron_routes.run_maintenance(dry_run=True)`, used by `scripts/programme01_reconcile.py`) now reports
  `stock_recovery` and `stuck_expiries` (what would be recovered), writing nothing.

**Scheduling and limits.** Unchanged scheduler: the daily cron (40 s budget) and the bounded request-time calls (2 s). Recovery still
only touches work older than `STOCK_RECOVERY_MIN_AGE_SECONDS` (120 s) so it never competes with a running request. A large backlog is
finished over successive bounded runs from the checkpoint; a completed pass clears the checkpoint, so records that become eligible
later are found by the next run.

Tests: `tests/test_def03_stock_recovery.py` (15) — >20 interrupted reservations and >20 stuck expiries over bounded runs, a crash halfway
(isolated, recorded, retried), a database error on one record, checkpoint resume, two concurrent workers, duplicate cron invocation,
records becoming ineligible mid-run (revived order, transaction finished elsewhere), newly eligible records after a completed pass,
repeated runs never releasing twice, live and COD orders never restored, a mixed recovery, dry run, idle runs; each ends with the stock
reconciliation (counter = start + journal movements = start − units still reserved; at most one forward and one compensating row per line).
