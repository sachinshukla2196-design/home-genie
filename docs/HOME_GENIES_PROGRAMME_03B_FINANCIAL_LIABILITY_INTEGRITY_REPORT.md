# HOME GENIES — Programme 03-B: financial liability integrity (P03-A01, P03-A02)

Date: 2026-11-27 · Repository `/home/guru/Desktop/home-genie` · Branch **`programme-03-payments-finance`** @ `bf412c0` (the directive
named `main` @ `383e811`; that checkpoint predates Programme 03, whose audit findings, reconciliation framework and report this batch
builds on — they exist only on this branch, so the work was done here; `main` is untouched) · Working tree **uncommitted**.
Checkpoint: `~/home-genie-checkpoints/hg-20261127-1617-pre-p03b-full-worktree.tar.gz` (full tree incl. `.git`, 2,547 entries,
verified readable). Isolated test MongoDB (127.0.0.1:27018, throwaway databases) and a fake Stripe only.

## 1. Executive summary
Both High findings of the Programme 03 audit are fixed by making the refund obligation durable **in the same conditional database
update as the financial transition that creates it**, using the system's existing liability model (order-level obligation markers +
refund cases with unique source keys + the resumable obligation sweep). No new financial system, no change to any refund, cancellation,
commission, revival or gateway rule; no money moves and no provider is called when an obligation is recorded.

- **P03-A01** — a customer's cancellation of a paid order now writes `refund_due_cancel` in the cancellation claim itself, and the claim
  is conditional on the payment state the request read. The settle step (restock, sale reversal, one `cancel:<order>` case) is
  idempotent and the existing sweep finishes it after any crash. The same "payment lands between read and claim" race is closed in the
  admin cancellation.
- **P03-A02** — a payment claimed on a cancelled order now writes `late_payment_due` (with a lease) in the paid claim itself. The
  unchanged decision (restore an expired order if stock remains, else `needs_refund` → one `late:<order>` case) runs under that lease;
  a new repair sweep finishes interrupted decisions; order completion waits while a decision is pending.
- **Reconciliation** gains a `liabilities` domain (missing, interrupted, duplicated, orphaned obligations; refund owed but active / earning;
  duplicate payment references), read-only, each issue with severity, ids, amount, gateway, reason, time and remediation.

## 2. Root causes
**P03-A01** (`returns_routes.customer_cancel`, as found): claim `status → cancelled` (no marker, not conditional on payment state) →
restock → sale reversal for each group → `open_refund_case(cancel:<order>)`. A crash, a 503 from the money guard, or a timeout after the
claim left a paid, cancelled order with nothing pointing at the money owed; the obligation sweep only looks for markers. A payment
landing between the request's read (unpaid) and its claim produced the same state through a race; the admin cancellation had the race too.

**P03-A02** (`shop_routes._process_paid_order`, as found): claim `payment_status → paid, completion_due` on the cancelled order →
`handle_late_payment` (revive, or `_flag_refund` → `needs_refund`). A crash between them left paid + cancelled with no `needs_refund`;
the completion step then **skipped the cancelled order and cleared `completion_due`**, removing the last trace. All payment paths
(Stripe webhook / poll, Razorpay webhook / verify, UPI confirmation, manual payment) converge on this claim, so all were affected.

## 3. Architecture selected (and why it is safe)
MongoDB multi-document transactions were not used: they need a replica set, the isolated test database is a standalone server
(verified: `rs.status()` → `NoReplicationEnabled`), the production topology is not visible to this work, and no code path in the
repository uses transactions today (0 call sites) — introducing the first one for this fix would add an untested deployment
dependency. The codebase's proven pattern is single-document atomicity + durable markers + idempotent keyed effects + resumable sweeps (B-001…B-005, B-022), and
the obligation can be expressed entirely on the order document at the moment of the transition. Each correction is a field added to an
EXISTING conditional single-document update, so the transition and the obligation commit or fail together.

| Transition | Same update now also writes | Then (idempotent, keyed) | If interrupted |
|---|---|---|---|
| customer cancel of a paid order (claim also pins `payment_status`) | `refund_due_cancel: true` | restock intents (exactly once per line) → sale + commission reversal (`salerev:` / `commrev:` keys) → case `cancel:<order>` (unique) → marker cleared | `ensure_cases_for_flagged_orders` → `settle_paid_cancellation` (now finishes pending restock intents first, so the reversal sees the final groups) |
| admin cancel (claim now also pins `payment_status`) | `refund_due_cancel` (existing) | same | same |
| payment claim on a cancelled order | `late_payment_due {session_id, revivable, at, lease_until, attempts}` | under the lease: unchanged rule — revive (keyed revive stock txn) or `needs_refund` (conditional) → marker cleared → completion (earns only if revived) | `late_payments.repair_late_payments` (maintenance, before completion repair) takes the expired lease conditionally and drives the same decision; then `late:<order>` case by the obligation sweep |

State on the order: **active paid** → (cancel) **cancelled + refund_due_cancel** → **cancelled + case open** (marker cleared);
**cancelled unpaid** → (capture) **cancelled + paid + late_payment_due** → either **processing (restored, earns)** or
**cancelled + needs_refund** → **case `late:` open**. Refund cases keep their own existing state machine (awaiting_review → initiated →
confirmed by a second finance user / failed / resolved); recording an obligation never initiates or executes a refund.

Idempotency: obligation keys are unique (`refund_cases.source_key`, money-guard area `refunds`, fails closed without the index); the
cancellation and the payment claim are conditional (one winner); `_flag_refund` is conditional; revival is a keyed stock transaction with
a per-transaction guard; vendor-ledger effects are keyed. Concurrency: the late-payment lease is taken in the claim and re-taken by the
repair only after expiry with a conditional update; even after an expired lease every effect underneath stays keyed.

## 4. Repair system
- `late_payments.repair_late_payments` — keyset sweep (`sweeps.run_sweep`) over orders whose `late_payment_due.lease_until` has passed;
  per-record isolation, failures recorded in `job_failures` (visible in Finance → system integrity), attempts and last attempt time on the
  marker, dry run, time budget; never creates a payment (it acts only on a claim the payment path already wrote). Index
  `orders_late_payment_due` (partial). Runs in the daily maintenance before the completion repair.
- `returns_routes.ensure_cases_for_flagged_orders` (existing) — now also finishes customer-cancellation obligations (same marker).
- `order_completion.complete_paid_order` waits while `late_payment_due` is present (previously it would clear `completion_due`).

## 5. Reconciliation (`reconciliation.liabilities`, API `?domain=liabilities`, script)
Attention checks: cancelled order with captured money and no obligation (**critical**); interrupted late-payment decision (lease expired);
refund owed but order active; refund owed but order earned revenue (commission plan / net sale); more than one order-level obligation
(cancellation + late payment) for the same order; obligations exceeding the money received; obligation on an order with no money in;
one gateway payment id / bank reference used for more than one order. Informational: late-payment decisions in progress. Each issue:
severity, order id / number, payment session, liability id(s), amount (paise), currency, gateway, reason, detection time, remediation
category. Read-only (whole-database fingerprint before / after in tests); never repairs.

## 6. Files changed
| File | Change |
|---|---|
| `backend/returns_routes.py` | customer cancel: marker in the claim, claim pinned to the read payment state, settle via `settle_paid_cancellation`; settle finishes restock intents first, reverses every pre-dispatch group on a customer cancellation (R05), reuses an existing case; the `late:` case covers only what other open cases do not (R03); crash-injection hooks |
| `backend/admin_routes.py` | admin cancel claim pinned to the read payment state |
| `backend/shop_routes.py` | late-payment marker in the paid claim on a cancelled order; decision via `late_payments` under the claim's lease; a redelivery of the same payment finishes an interrupted decision (R03) |
| `backend/stock.py` | fences (R02): the late release touches only generation-0 stock, `finish_revival` restores only a cancelled order, `_flag_refund` marks only a cancelled order; the inline expiry sweep also runs the late-payment repair after stock recovery (R03) |
| `backend/late_payments.py` (new) | marker, lease, `resolve_late_payment` with a re-run-safe decision (started revival finished, never re-decided; no revival once a refund is recorded — R01 / R03), `repair_late_payments` |
| `backend/order_completion.py` | completion waits while a late-payment decision is pending |
| `backend/db_indexes.py` | `orders_late_payment_due` (partial query index) |
| `backend/cron_routes.py` | late-payment repair in the daily maintenance (before completion repair) |
| `backend/reconciliation.py` | `liabilities` domain (open promises vs money still held, R09); refunds check excludes pending late-payment decisions |
| `backend/tests/test_p03b_liability_integrity.py` (new) | 47 tests (below) |
| docs | this report + control documents |

## 7. Test results
All runs on the final code, isolated test MongoDB (127.0.0.1:27018, standalone, throwaway databases), fake Stripe / fake sessions;
no gateway, provider, notification or production system was touched.

| Run | Result | Baseline (P03 first package) |
|---|---|---|
| New suite `test_p03b_liability_integrity` | **47 passed**, 0 failed, 0 skipped (also re-run alone: 47 passed) | — (new) |
| Full backend regression (80 suites, each in its own process) | **1,728 passed, 0 failed, 0 skipped, 0 errors** — see note 1 | 79 suites, 1,681 passed (+47 new = 1,728) |
| Of which the directly affected suites (cancellation, payment, refund, commission, stock, wallet, reconciliation: e.g. `test_returns_refunds`, `test_refund_return_controls`, `test_refunds_and_retention`, `test_stock_expiry_race`, `test_stock_recovery`, `test_stock_reservation`, `test_withdrawal_controls`, `test_role_eligibility_wallets`, P03 suites) | all passed | all passed |
| Live-server suites (canonical set, SMS off: 5 suites; SMS on: 2 suites) | **96 passed, 6 skipped**, 0 failed | 96 passed, 6 skipped |
| Backend lint (pyflakes, all backend modules + new test) | no new findings (one baseline finding disappeared: `wallet_routes` `Optional` is used since P03) | — |
| Frontend `npm run quality` | exit 0 — lint 176 files, **0 errors**, 9 existing warnings; unit tests **15 / 15** (4 suites); build guards all ✓; production build OK (`REACT_APP_BACKEND_URL=https://api.example.test`) | identical |
| Browser (production build + throwaway API, Chrome headless) | **4 / 4 pass**: customer cancels a PAID order on desktop 1366 and mobile 390, plainly and with the first response lost + retry. Each: order cancelled, payment state untouched, marker cleared, exactly one `cancel:<order>` case for the full 120,000 paise in `awaiting_review`, stock back to 50, no console errors, no horizontal overflow, design unchanged (screenshots reviewed) | — |

**Skips (6, all live, all unchanged and expected):** `test_production_hardening` 4 — retired flows (`RETIRED`: ₹100 registration / activation
payouts no longer exist; one also needs one admin to approve and pay, which the two-person rule refuses; one depends on a retired test's
order); `test_upi_adminlogin` 2 — card checkout is not configured on the test server (no gateway credentials by design).

**Note 1 — environmental failure, not a defect:** in the full run `test_db_indexes::test_importing_the_backend_changes_no_indexes`
timed out (its subprocess import has a 180 s limit; the suite took 340 s while the machine was loaded). Re-run alone on the same code:
**8 / 8 passed in 29 s**. The count above includes the re-run. Separately, the original runner process ended with the previous
working session after 60 suites; the 20 suites not yet run were run on the same code and all passed (597 tests) — every suite ran once.

**Flaky / unverified:** no flaky test observed (the new suite passed in every run on the final code: inside the full regression and alone). Not verifiable here: behaviour on a
MongoDB replica set or sharded cluster (the fix does not depend on either); real gateway timing; production index state (P1-01).

**UPI admin-login 503 (directive question) — harness readiness only, with one deployment note.** Reproduced and explained:
`startup_report` checks money-guard readiness when the server starts, against an EMPTY test database, and caches "not ready" for
15 s (`BAD_TTL`); the live seed creates the indexes after start, so a suite run alone straight after seeding gets 503 ("money write
refused: protective indexes not ready") — 6 failures. The same suite with a 16 s pause after seeding: **13 passed, 2 skipped, 0
"not ready" refusals**. In the canonical multi-suite run other suites run first, so it never shows. Production relevance: only if the
application starts before the P1-01 indexes exist — money writes are then refused (fail closed, the intended behaviour) for up to 15 s
after the indexes appear, and self-heal. The inverse (index dropped while cached as ready) lasts up to 300 s. Recorded as P03B-OPS-01
(runbook note); no code changed and the guard was not bypassed.

## 8. Post-implementation audit
An independent adversarial review read the finished change (read-only) and found three NEW problems in the first implementation,
all caused by the repair now being able to run the late-payment decision a second time. Each was reproduced by a test that fails on
the first implementation and passes on the final one.

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| P03B-R01 | **High** | Repair after a crash between the revival's stock re-reservation and the order's restore re-ran the release: the revived stock went back to the shelf while the order became active (oversell) | **Fixed** — a revival that has started is finished by the stock engine's own recovery (`_recover_one_txn`), never decided again. Test `test_r01_…` (old: stock 5, expected 3) |
| P03B-R02 | Medium | The lease was not a fence: a request outliving its lease could act on a stale read after the repair restored the order (second release / re-reserve, vendor progress reset, refund flag on an active order) | **Fixed** — state fences under the lease: the late release touches only the expiry's generation-0 stock; `finish_revival` restores only a still-cancelled order; `_flag_refund` marks only a cancelled order. Test `test_r02_…` (old: refund flagged on an active order) |
| P03B-R03 | Medium | An interrupted decision could wait up to a day (daily maintenance only); a refund recorded meanwhile could be followed by a revival, or by a second `late:` liability on top of an open case | **Fixed** — the bounded repair also runs inside the inline expiry sweep (after stock recovery) and on a redelivery of the same payment; an order with any refund recorded / case is never restored; the `late:` case covers only what other open cases do not already promise (same rule as the cancellation case, G1). Tests `test_r03_…` |
| P03B-R04 | Medium (pre-existing) | COD collection / discrepancy resolution claims do not exclude cancelled orders | = **P03-A03**, out of this batch's scope (directive §13); still detected by reconciliation (`cancelled_money_without_obligation`) |
| P03B-R05 | Low | Customer cancel's sale reversal relied on the restock step marking groups cancelled, which older orders without `stock_reserved` skip | **Fixed** — for a customer cancellation every pre-dispatch group's sale is reversed (as before) |
| P03B-R06 | Low (rule alignment) | The customer cancellation case now uses the owner-approved G1 amount (refundable minus what other OPEN cases promise), as the admin cancellation always did; if that other case is later closed without paying, the cancellation case is not topped up | Recorded; the only other case possible at customer-cancel time is an admin refund case. Owner awareness via P03B-OD-02 |
| P03B-R07 | Low | `refund_due_cancel` can remain on an order whose state changed so that nothing is owed; the sweep re-checks it harmlessly | Open (cosmetic) |
| P03B-R08 | Not a defect | Settle finishing restock intents first | Confirmed safe |
| P03B-R09 | Low | Reconciliation false positive: one legacy refund event confirming two cases looked like over-promising; the same unrecorded order is reported in both `refunds` and `liabilities` | **Fixed** (open promises compared with the money still held); double reporting kept deliberately (counts vs detailed issue) |
| P03B-R10 | Low | Test gaps / weak assertions | **Fixed** — R01 / R02 / R03 tests added; the "always true" assertions removed; the race test checks the case key and amount |
| P03B-UX-01 | Low (pre-existing, copy) | Found by the browser check: a customer's own cancellation shows the shipment note "Order cancelled by admin" (shared restock step text, unchanged since before P03-B) | Open — copy fix in a UX pass; money unaffected |
| P03B-OPS-01 | Low (ops) | Money-guard readiness cache delays recovery by up to 15 s after indexes are created on a running server (see §7) | Open — runbook note under P1-01; guard unchanged |

**Directive §12 questions** (answers after the fixes): a crash can no longer leave captured money on a cancelled order without a
durable record on any path changed here (every write that cancels an order or marks it paid was re-checked; the COD claims are
P03-A03); a cancellation becomes durable only together with its obligation; late payments cannot escape (marker in the paid claim on
every gateway path); duplicate webhooks, status checks and repair workers converge on the unique `cancel:` / `late:` keys; repair and
live request are serialised by the lease and fenced by state; refund cases are never deleted by the application and keep their
existing two-person confirmation; no provider refund exists (DEF-11), so none can run twice; finance sees every obligation (refund
cases, Needs-refund queue, reconciliation); all amounts are integer paise; unique indexes back every obligation key (money guard
`refunds` fails closed); permissions are unchanged; the repairs are safe to repeat (tested twice and concurrently).
