# HOME GENIES — Programme 03 engineering report (first package)

Date: 2026-11-27 · Base: `main` @ `383e811` (= `origin/main`) · Working tree: **uncommitted** (nothing staged, committed, pushed, merged or
deployed). Everything below was verified against the isolated test MongoDB (127.0.0.1:27018, throwaway databases) and fakes; no
production database, live credential, real payment, payout, withdrawal or financial notification was used.

Scope (owner directive "Autonomous Programme 03"): **DEF-05** Stripe payment-completion integrity, **B-022** crash-safe withdrawal
requests, **B-023** immutable settlement order and bank snapshots, a financial reconciliation framework, and a Programme 03
architecture-wide audit with a defect / dependency register. Only these tasks and the tightly related defects needed to make them safe
were changed. No commission percentage, depth, eligibility or method; no refund, withdrawal, settlement, COD or cancellation rule; no
vendor liability allocation; no two-person rule; no permission was broadened; no floating-point money was introduced; no new key
material (A-01 unresolved); P1-01 remains the hard production gate.

## 1. DEF-05 — Stripe payment-completion integrity

**As found.** `POST /api/webhook/stripe` and the public `GET /api/payments/status/{sid}` completed an order as soon as Stripe (or the
Emergent wrapper) reported the session paid / complete: no amount, currency or order check, no `webhook_events` record, no finance
retry, `print()` logging; the poll ran for any provider's session id.

**Now** (`payment_events.py` Stripe section; `shop_routes.py` `create_checkout`, `payment_status`, `stripe_webhook`):
1. **Only Stripe's own record decides.** `apply_stripe` reads the checkout session server-to-server (`get_checkout_status`) and
   never uses the webhook body's or the browser's figures.
2. **Validation before any state change:** our payment attempt exists for that session with provider `stripe` (or none, for attempts
   created before DEF-05) → the attempt's order exists → Stripe says `payment_status == "paid"` → `metadata.order_id` (when present)
   is the attempt's order → currency `INR` → `amount_total` (integer paise) `==` the order's `total_paise`. Otherwise the event is
   recorded `unmatched`, `ignored` or `rejected` with the reason, and nothing else changes.
3. **One record per delivery**, same table and rules as Razorpay: webhook → `stripe:<event id>`; status poll → one event per session
   `stripe:checkout:<session>`, created only once Stripe says paid (an early poll leaves nothing behind that could block the real
   one). Claim with the unique index, stale-claim takeover (120 s), final outcomes never re-applied, attempts history, `provider:
   "stripe"`. Stored facts: amount (paise), currency, gateway status — no metadata, customer or card data.
4. **One state machine.** A valid payment is applied only through `shop_routes._process_paid_order` (conditional claim) and the
   idempotent `order_completion.complete_paid_order` (sale, invoice, commission plan, notices); a crash after the claim leaves
   `completion_due` for the repair sweep or the finance retry. Late / cancelled / already-paid orders follow the existing rules
   (duplicate capture recorded for refund; never re-opened).
5. **Recovery:** a failed event is `failed` (500 to Stripe, which re-delivers); finance can retry it from the payment-events inbox;
   the retry re-reads Stripe (a changed amount is then rejected).
6. **Checkout** sends the exact paise total and records `amount_paise` and `provider: "stripe"` on the attempt.
7. The poll checks only unpaid Stripe attempts (never Razorpay / UPI / manual ones) and logs failures without exception text.

Unchanged: Stripe stays unconfigured by default (DEF-06 / P0-01); the poll stays public (P03-OD-03); a rejected captured payment
creates no refund obligation automatically (P03-OD-04, part of B-020).

## 2. B-022 — crash-safe, idempotent withdrawal requests

**As found** (`wallet_routes.request_withdrawal`): wallet debit → ledger row → request insert → notice → audit, each a separate write.
A crash after the debit left money in `pending` with no request (stranded); a client retry after a lost response created a second
request and a second hold.

**Now** (`withdrawal_intents.py`, `wallet_routes.py`):

| Step | Write | Crash right after it → what finishes it |
|---|---|---|
| 1 | request inserted `reserving` (`hold_op = withdrawal_hold:<id>`; optional `request_key`, unique per member) | no money moved; retry with the key settles it, or the sweep records the void and closes it `not_reserved` |
| 2 | one wallet update: `available −= amt`, `pending += amt`, `applied_ops += hold`, only if neither hold nor void is there and `available ≥ amt` | money held; retry or sweep writes the ledger row and opens it |
| 3 | HELD ledger row, `op_key = hold` (unique) | retry or sweep opens it |
| 4 | claim `reserving → pending` + `effects_due` | retry or sweep writes the notice / audit |
| 5 | member notice, audit (each written only if absent), `effects_due` cleared | — |

- **Exclusion:** closing a request writes `withdrawal_void:<id>` with a conditional update that requires the hold to be absent; the hold
  requires the void to be absent. On one wallet document, exactly one wins — so a request either holds money or is `not_reserved`.
- **Idempotency:** same key → the same request (`already: true`), never a second hold; same key with another amount → 409; a key whose
  attempt was closed stays closed (400). Requests without a key (older clients) are still crash-safe.
- **Insufficient balance** is refused before anything is written; if the balance drops between that check and the atomic hold, the
  request is closed `not_reserved` and the member gets the same 400.
- **Repair sweep** `withdrawal_request_repair` (+ `withdrawal_request_effects`) runs in the daily maintenance on requests older than
  120 s: hold present → open; absent → void and close. It never places a new hold. Keyset, checkpointed, per-record isolation, dry run.
- **Frontend** (`Withdrawals.js`): one key per attempt, reused after a lost response / 5xx, renewed after an answer.
- Finance cannot act on a `reserving` request; `not_reserved` requests are hidden from the member and from member metrics
  (P03-OD-02). Indexes: `withdrawal_requests_user_key_unique` (money_guard area `withdrawals`, fails closed),
  `withdrawal_requests_reserving`, `withdrawal_requests_effects_due`.
- Unchanged: who may withdraw, amounts, KYC rule, approval, maker-checker, payout reference rule, fees, methods.

## 3. B-023 — immutable settlement order and bank snapshots

**As found:** a settlement stored only its amount; nothing recorded which orders made the balance eligible or which bank details the
payout was requested against.

**Now** (`settlement_snapshot.py`, `ledger.eligible_detail`, `finance_routes.py`): at creation each settlement stores `snapshot` and
`snapshot_digest` (SHA-256 of the canonical JSON):
- **basis:** requested amount and the balance figures it was checked against (available, pending, in progress, payable, settled,
  awaiting eligibility, eligible, non-order entries, orders total, held orders) — integer paise; `orders_total + non_order == eligible`
  is asserted when the snapshot is built;
- **orders:** every eligible order with its net ledger amount (sale − commission ± reversals / refunds), every held order with its
  reason; the stored list is capped (2,000 / 500) but the count, total and a digest over the full list are always kept;
- **bank (minimum):** holder name, IFSC, account masked (`XXXX` + last four), last four, the last approved bank-change request id.
  The full account number is never copied, logged or hashed (a plain hash of an account number is brute-forceable; no new key — A-01).

Immutability: no code path updates `snapshot`; `settlement_action` sets only status fields. `mark_paid` additionally refuses (409) a
settlement whose snapshot no longer verifies (altered evidence) or whose vendor bank details changed since the request — the
existing "balance changed: reject and create a new one" pattern (P03-OD-01). Legacy settlements without a snapshot behave as before.
The snapshot is evidence, not authority to pay: maker-checker and the live eligibility check still decide. Views: list → summary
(bank part for finance roles only), new finance-only detail endpoint, not shown to vendors; Operations → Settlements shows the
recorded basis and the masked payee.

## 4. Financial reconciliation framework
`reconciliation.py` (+ `GET /api/admin/finance/reconciliation`, finance-only; `scripts/financial_reconciliation_report.py`, exit code
0 / 1 / 2). Read-only (proved by fingerprinting every collection before and after), each domain isolated (one failing check is
reported `error` and hides nothing), ids / order numbers / operation keys / counts only.

| Domain | Checks (attention when non-zero) | Informational |
|---|---|---|
| payments | paid order whose attempt is not paid; paid order without attempt; captured attempt neither applied nor recorded as duplicate / refund; failed events; events stuck `processing` past the stale window; verified gateway amount ≠ order total | rejected / unmatched events for review |
| wallets | wallet aggregates ≠ ledger (`wallet_reconcile`); commission intent issues; incomplete distributions | legacy unverifiable releases, orphan ledger users |
| withdrawals | requests stuck `reserving`; keyed request without its hold / HELD row, closed with a hold, paid / rejected without op + row | legacy unkeyed requests, notices due |
| settlements | snapshot digest mismatch / amount differs / above recorded available; paid without ledger entry; more than one open per vendor | legacy without snapshot |
| vendor_ledger | vendor settled beyond what is owed | vendors checked |
| refunds | refund obligation without a case (dry-run sweep); failed cases | cases by state |
| commissions | `completion_due`; completion blocked for finance; paid order without plan; paid vendor group without sale entry | unfunded plans for review |
| stock | negative stock; unfinished stock journal / restock intents (dry-run recovery) | — |
| liabilities (**added P03-B**) | cancelled order with captured money and no obligation (critical); late-payment decision interrupted (lease expired); refund owed but order active / earning; more than one order-level obligation; obligations above money still held; obligation with no money in; one gateway payment id / bank reference on more than one order. Each issue: severity, order, payment session, liability ids, paise, currency, gateway, reason, detected at, remediation | late-payment decisions in progress |

## 5. Verification (2026-11-27; isolated test MongoDB 127.0.0.1:27018, throwaway databases; fakes for Stripe)
| Check | Result |
|---|---|
| New suites (final code) | `test_p03_stripe_integrity` 26/26 · `test_p03_withdrawal_requests` 40/40 · `test_p03_settlement_snapshot` 11/11 · `test_p03_reconciliation` 17/17 — **94 passed** |
| The new tests detect the defects (old code in a scratch copy) | Stripe 23 of 26 fail on the old code · withdrawals 31 of the first 38 fail · snapshots 11 of 11 fail · pay-path guard test fails (old route returned 503 *after* moving the wallet) |
| Full in-process regression | **79 suites, 1,678 passed, 0 failed, 0 skipped** (run before three late, local changes: closure audit, pay-path guard, reconciliation check). The **17 suites those changes touch were re-run on the final code: all passed** (406 tests). Final state: 79 suites, **1,681 passed**, 0 failed, 0 skipped |
| Live (server-dependent) suites | canonical set **96 passed, 6 skipped** (same skips as the baseline: card tests without keys, 4 production-hardening skips). Recorded honestly: a first run had 4 failures in `test_upi_adminlogin` from 25 s read timeouts at order creation that did not reproduce on the immediate re-run of the same set; a solo run of that suite gets 503 because it starts before the server's 15 s index-readiness cache expires (harness ordering, not code) |
| Backend lint (pyflakes vs a baseline from `HEAD`) | no new findings; one old finding removed (`wallet_routes.py` unused `Optional`) |
| Frontend | lint 0 errors / 9 warnings (all pre-existing, none in changed files) · unit tests 15/15 · build guards pass · production build succeeds (the build correctly refuses a plain-http API URL) |
| Browser (Chrome, production build, throwaway API) | member withdrawal on desktop + mobile: one request per submit; **a lost response followed by a retry created exactly one request with the same key**; no console errors; no horizontal overflow. Finance Operations → Settlements shows the recorded basis and masked payee; the full account number is not on the page |
| Reconciliation on the browser-test database | all eight domains `ok`; script exit code 0 |
| Production / live credentials / real money | none used |

## 7. Files changed
| File | Why |
|---|---|
| `backend/payment_events.py` | DEF-05: Stripe event record, validation against Stripe's record, poll event, provider on claim, Stripe retry; completion source label |
| `backend/shop_routes.py` | DEF-05: checkout records exact paise + provider; status poll and webhook go through the validated path; structured logging |
| `backend/withdrawal_intents.py` (new) | B-022: hold / void exclusion, open / close, notice + audit once, repair sweeps, withdrawal audit |
| `backend/wallet_routes.py` | B-022: `request_key`, intent-first route, hidden `not_reserved`, internal fields not returned |
| `backend/admin_routes.py` | P03-A04: money guard before the withdrawal pay / reject wallet move |
| `backend/settlement_snapshot.py` (new) | B-023: snapshot build, digest, verify, bank fingerprint, summary, audit |
| `backend/ledger.py` | B-023: `eligible_detail` (same decision as `_eligible_paise`, with composition); `_eligible_paise` now uses it |
| `backend/finance_routes.py` | B-023: snapshot on create, pay-time verification / bank check, admin views, detail endpoint; reconciliation endpoint |
| `backend/reconciliation.py` (new), `backend/scripts/financial_reconciliation_report.py` (new) | reconciliation framework |
| `backend/db_indexes.py`, `backend/money_guard.py` | 3 withdrawal indexes; money-guard area `withdrawals` |
| `backend/cron_routes.py` | withdrawal repair in the daily maintenance |
| `backend/homegenie_metrics.py` | member metrics exclude `not_reserved` requests |
| `frontend/src/pages/Withdrawals.js` | per-attempt idempotency key |
| `frontend/src/pages/admin/AdminOperations.js` | settlement "Recorded basis" column |
| `backend/tests/test_p03_*.py` (4 new) | tests above |
| docs (this report + 9 control documents) | records |

## 8. Owner decisions, remaining work, readiness
Owner decisions P03-OD-01 … 05 are in `HOME_GENIES_OWNER_DECISION_REGISTER.md`; remaining work and audit items in
`HOME_GENIES_REMAINING_WORK_REGISTER.md` (§1, §6, §8). Readiness: **local** — ready (all checks above); **sandbox** — needs Stripe /
Razorpay test keys and P0-01 to exercise gateways; **production migration** — P1-01 (now also the three withdrawal indexes; withdrawals
are refused until it runs); **public launch** — not ready (P03-A01 / A02 open; owner / legal decisions; provider refunds and payouts).

## 6. Programme 03 audit — defect / dependency register
Method: an independent read-only review of every money module (shop_routes, payment_events, order_completion, commission,
financial_ops, wallet_routes, admin_routes, finance_routes, ledger, returns_routes, stock, cron_routes, financial_approvals,
vendor_routes, eligibility, cod_rules, commercial_terms) against the codebase's own integrity patterns, followed by verification
by the engineering session. **V** = re-verified in code by this session (and, where marked, by a failing test on the old code);
**R** = reviewer evidence with file:line, not independently re-verified — treat as "needs confirmation" before fixing.

| ID | Class | Area | Finding | Evidence | Status |
|---|---|---|---|---|---|
| P03-A01 | **High** (V) | Customer cancel of a paid order | The cancel claim does not write the `refund_due_cancel` marker (the admin cancel does, atomically); the sale reversal and refund case are separate later writes. A crash or a 503 between them leaves a cancelled, paid order with no case and no marker — invisible to the obligation sweep. | `returns_routes.py:478-495` vs `admin_routes.py:426-427` | **Fixed 2026-11-27 (Programme 03-B)** — marker written in the claim, claim pinned to the payment state; `HOME_GENIES_PROGRAMME_03B_FINANCIAL_LIABILITY_INTEGRITY_REPORT.md`. |
| P03-A02 | **High** (V) | Late payment on an expired / cancelled order | The paid claim on a cancelled order sets `completion_due`; if the process dies (or `release_stock` returns 503) before `handle_late_payment`, the completion step skips cancelled orders and clears the marker: paid + cancelled, no `needs_refund`, no case. Affects Razorpay, UPI and Stripe alike (shared state machine). | `shop_routes.py:774-797`; `order_completion.py:67-74` | **Fixed 2026-11-27 (Programme 03-B)** — `late_payment_due` marker with lease in the paid claim, repair sweep, completion waits; `HOME_GENIES_PROGRAMME_03B_FINANCIAL_LIABILITY_INTEGRITY_REPORT.md`. |
| P03-A03 | Medium (R) | COD discrepancy resolve after cancel | `resolve_cod_discrepancy` / `cod_collected` claims do not exclude cancelled orders; an admin cancel of a `cod_discrepancy` order sets no refund marker. | `finance_routes.py:464-491`; `shop_routes.py:338-377`; `admin_routes.py:422-427` | Open — next package (add `status ≠ cancelled` to the claims). Detected by the reconciliation report if it happens. |
| P03-A04 | Medium (V, red test) | Withdrawal pay / reject | The wallet moved before the first money-guard check (inside `ensure_ledger`), so a 503 or crash left the wallet settled while the request stayed `approved`; nothing reported it. | `admin_routes.py` review_withdrawal | **Fixed (tightly related to B-022):** guard before any money moves (test fails on the old code: 503 returned *after* the wallet moved); `withdrawal_audit` / reconciliation report `wallet_settled_but_request_open`. Finishing stays manual (needs the payer and reference). |
| P03-A05 | Medium (R) | Return-window policy | `PUT /admin/returns/policy` (drives payout eligibility) allows the `admin` role; message says super admin only; the equivalent setting is finance-only. | `returns_routes.py:34, 66-90` | Owner-blocked: **D-05** (already open; this adds evidence). Not changed (permission rule). |
| P03-A06 | Needs verification (R) | KYC / bank verification | Any admin role incl. support_admin can mark KYC (incl. bank) verified, which gates withdrawals. | `admin_routes.py:735-762` | Owner-blocked: **D-06** / P0-02. |
| P03-A07 | Low (R) | Financial approvals | An HTTPException during execution marks the approval `failed`, which cannot be re-approved even if part of an idempotent action ran. | `financial_approvals.py:96-105` | Open — P03 later package (retryable `approving`). |
| P03-A08 | Low (R) | Vendor platform commission arithmetic | Commission percent is a float converted to basis points with `round()` (half-even on binary floats). | `commercial_terms.py:30-47` | Open — fix with Decimal half-up + 2-decimal validation; with B-024 / P0-04 (does not change agreed rates). |
| P03-A09 | Low (R) | Manual payment by HomeGenie ID | Picks the newest payable order, which may be an expired one; no post-check that the order became paid. | `shop_routes.py:944-969` | Open — P03 later package (require order id / post-check, like UPI confirm). |
| P03-A10 | Low (R) | Ledger "not supplied" set | Ledger sale eligibility omits `returned_to_origin`, which eligibility and vendor routes treat as not supplied. | `ledger.py:36, 72-74`; `eligibility.py:42` | Open — before B-024. |
| P03-A11 | Needs verification (R) | Maintenance time budget | Each sweep gets ≥ 1 s after the budget; time checked per batch. | `cron_routes.py:104-125`; `sweeps.py:85-89` | P05 (needs production timings). |
| P03-A12 | Already fixed (DEF-05) | Stripe | Verified by the reviewer. Residual: `origin_url` not allow-listed for the success / cancel redirect; public poll. | `shop_routes.py` create_checkout | Residual Low (open redirect after payment) — P03 later; poll → P03-OD-03. |
| P03-A13 | Already fixed (B-022) | Withdrawal requests | Residual: `request_key` optional, so API clients without it get no retry de-duplication (still crash-safe). | `wallet_routes.py` | Kept optional for compatibility; make required once no older client exists (P03 later). |
| P03-A14 | Already fixed (B-023) | Settlements | Residual: an open settlement created before snapshots existed skips the bank-change check. | `finance_routes.py` mark_paid | Recommendation with P03-OD-01: reject and recreate open legacy settlements at deployment (operational, finance). |
| P03-A15 | Already fixed (reconciliation) | Reconciliation | The obligation check only saw marked orders, so A01–A03 would read "ok". | `reconciliation.py` | **Fixed:** `refunds.unrecorded_cancelled_money` (tested). |
| P03-A16 | Already known | — | G13 reference reserved before claim; DEF-04 / B-021; B-024 commission not returned on refunds; B-012; D-02; DEF-11. | — | Unchanged. |

**Dependencies.** (1) A01–A03 before the refund-obligation figures can be treated as complete evidence (the report now flags them
meanwhile). (2) P1-01 (production index migration) before go-live — several defects above are triggered by a 503 after a state change,
and withdrawals / payments are refused until it runs. (3) A04's repair pattern (operation keys + sweep) before any payout batching or
payout-provider integration (G9 / K9). (4) A05 / A06 with D-05 / D-06 / P0-02 (and A-01 for bank data). (5) A10 before B-024 / P0-04.
(6) DEF-11 provider refunds and A12 hardening depend on the gateway decision P0-01.
