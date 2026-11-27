# HOME GENIES — Financial Architecture Audit

Independent principal-architect review of every money path. **Inspection only** (no code, test, config or existing document was
changed; no suite or server was run). Baseline `main @ d31cb74`, clean. Citations are `file:function:line` relative to `backend/`.

Legend: **[V]** verified by reading the full code path · **[S]** suspicion that needs a runtime probe or an owner answer.
P0 = money can be lost / double-paid / mis-stated in normal operation · P1 = same under a realistic failure, race or
mis-deployment, or a breach of an approved financial rule · P2 = significant control or accuracy gap · P3 = hygiene.

Approved rules (not re-opened): HomeGenie commission 30 / 10 / 5 % of the **taxable** value of attributed sales; payout only after
delivery + return window (S-2, S-3); maker-checker / two-person rules (S-4, S-8); GST-inclusive prices (S-1). Only defects
against them are reported.

---

## 0. Ranked findings

| # | Rank | Finding | Evidence |
|---|---|---|---|
| F-1 | **P0** [V] | **RTO on a prepaid order has no financial effect.** No `refund_due`, no refund case, no `SALE_REVERSAL`, no commission hold. Multi-vendor: the RTO group is "not supplied", the order counts as delivered, and the HomeGenie commission on goods the customer never received is released after the window (breach of S-2). Single-vendor: the vendor sale and commission sit held for ever and the customer is not refunded unless an admin notices. | `vendor_routes.py:45` (`RESTOCK_ON`), `vendor_update_fulfilment:906-924`; `ledger.py:36` (`SALE_BLOCKING_FULFILMENT` excludes RTO); `eligibility.py:42`, `delivered_at:53-76`, `payout_block:79-103` |
| F-2 | P1 [V] | **A refund case can be marked `confirmed` (customer told "refund processed", payout hold lifted) while nothing is booked.** `reverse_order_financials` returns `{"rejected": True, "refund_amount": 0}` when the stored event's `closes_order` flag no longer matches (two cases confirmed concurrently on one order, or a crashed confirmation retried after another refund). `refund_case_action` handles `duplicate` and `conflict` but not `rejected`, and sets `status: confirmed`, `amount_refunded_paise: 0`. No clawback, no vendor refund share, order stays `paid`/`partially_refunded` and payable. | `shop_routes._reserve_refund:540-541`, `reverse_order_financials:634-637`; `returns_routes.refund_case_action:330-338` |
| F-3 | P1 [V] | **Paid-order side effects are not recoverable outside the Razorpay webhook.** `_process_paid_order` claims `paid` first, then posts vendor sales, notifies, and freezes the commission plan. A crash / timeout / exception after the claim (e.g. in `post_commission`, `notify_order_vendors`, `create_notification`) leaves no plan; every later call returns at "already paid". Vendor sales are repaired only by `reconcile_ledger` (see F-5); commissions are **never** repaired and `distribution_audit` does not detect "paid + attributed + no plan". Applies to Stripe webhook/status poll, Razorpay client verify, UPI confirm, manual payment, COD confirm, COD resolve. | `shop_routes._process_paid_order:726-761`, `cod_collected:343-366`; `finance_routes.resolve_cod_discrepancy:430-452`; contrast `payment_events.complete_paid_order:147-157`; `commission.release_due_points:305`; `wallet_reconcile.distribution_audit:83-98` |
| F-4 | P1 [V] | **Unique indexes that carry idempotency are only *checked* at startup, never enforced.** If the migration is not applied the app runs and silently loses: one vendor SALE per (order, vendor) (`vendor_ledger.source_key`), one wallet ledger row per op (`wallet_transactions.op_key`), one refund case per source, one open settlement per vendor, one stock journal per key, one webhook event per id. Fail-open. (`_id`-keyed collections — `commission_plans`, `commissions`, `order_refunds`, `payment_references`, `financial_approvals`, `withdrawal_payout_refs` — are safe.) | `server.py:262-263` → `db_indexes.check_missing:184-190`; specs `db_indexes.py:38,42,52,54,59,65`; `ledger.post_entry:53-57`; `financial_ops.ensure_ledger:38-45`; `finance_routes.create_settlement:312-315` |
| F-5 | P1 [V] | **`reconcile_ledger` repairs only the 500 oldest paid orders, every run.** Query sorted by `paid_at` ascending with `limit(500)` and no cursor; once more than 500 paid orders exist, missing vendor sales / reversals / refund shares on newer orders are never repaired — the guarantee stated in `ledger.py` and `FINANCIAL_STATE_MACHINE.md` silently stops. | `ledger.reconcile_ledger:163-175`; callers `cron_routes.expire_pending_orders:84`, `finance_routes.admin_reconcile:398` |
| F-6 | P1 [V] | **Approved commission rates are runtime-mutable by one finance admin** (S-4 maker-checker, S-7 fixed 30/10/5). | `admin_routes.admin_update_settings:997-1010`, `MONEY_POLICY_SETTINGS:970`; read per order in `commission._freeze_plan:149-151` |
| F-7 | P1 [V] | **Manual payment (`/admin/payments/manual`) is single-person** and UPI confirmation has no confirmer ≠ buyer check: a finance admin can mark their own order paid with any unused 6+ char reference and the exact amount. (S-4.) Same buyer gap in COD confirmation (`refuse_own_sale` checks the seller only). | `shop_routes.manual_payment_by_distributor:873-910`, `upi_confirm:918-948`; `cod_rules.refuse_own_sale:119-123` |
| F-8 | P2 [V] | **Stripe path has no parity with Razorpay reconciliation:** the webhook and the unauthenticated status poll apply a payment on `payment_status == "paid"` alone — no amount or currency check against the order, no `webhook_events` record (no audit trail, no retry queue, not visible in "Payment events"), no `complete_paid_order` retry (F-3). Amount is server-set at session creation, so mis-application risk is low; the reconciliation/audit gap is real. Under the Emergent package the webhook signature check is outside the repo [S]. | `shop_routes.payment_status:768-783`, `stripe_webhook:786-798`; `stripe_checkout.handle_webhook:96-106` (returns no amount); contrast `payment_events.apply:126-136` |
| F-9 | P2 [V] | **Batch sweeps can starve.** `release_due_points` loads only the first 5,000 pending commissions (no sort, no cursor): if 5,000 are blocked (undelivered), eligible ones beyond never release. `ensure_cases_for_flagged_orders` scans `needs_refund` orders with `limit(200)` but never clears the marker, so new late-payment cases beyond 200 are never created. | `commission.py:305,307,314`; `returns_routes.ensure_cases_for_flagged_orders:209` |
| F-10 | P2 [V] | **Refund cases can over-commit the refundable amount.** `_complete_inspection`, `customer_cancel` and the late-payment case size themselves from `refundable_paise` without netting other open cases (only `settle_paid_cancellation`, `settle_vendor_rejection` and the admin Refund action net them). At confirmation the engine silently caps (`amt_p = min(amt_p, remaining_p)`), so finance may pay out the case amount while the books record less; the mismatch is not flagged. | `returns_routes._complete_inspection:700`, `customer_cancel:403`, `ensure_cases_for_flagged_orders:211`; `shop_routes.reverse_order_financials:618-621` |
| F-11 | P2 [V] | **Money received outside the happy path is not recorded as owed:** (a) UPI money for an order whose claim expired — `upi_confirm` returns 409 ("refund it") before reserving the reference, nothing is recorded; (b) customer paid by UPI and also by Razorpay — the gateway capture is applied, then `upi_confirm` returns "Order already paid" with no duplicate record; (c) a Razorpay event rejected for amount/currency mismatch is final with no refund-due record. | `shop_routes.upi_confirm:926-929`; `payment_events.apply:129-133`; contrast `_flag_unapplied_capture:676-693` |
| F-12 | P2 [V] | **Withdrawal request is not crash-safe:** wallet moves available→pending first (`wallet_apply`, no op key), then the HELD ledger row, then the request document. A crash between leaves money reserved with no request to pay or reject; no detector. | `wallet_routes.request_withdrawal:173-186` |
| F-13 | P2 [V] | **Vendor platform commission:** (a) charged from approval even if the vendor never accepted; (b) a draft approved after its `effective_from` applies retroactively to earlier uncharged orders, because every `post_order_collected` run (incl. the reconcile sweep) re-invokes `post_commission`; (c) never returned on customer refunds/returns (only on non-supply), so a fully returned order leaves the vendor owing the commission — policy undefined per `commercial_terms.py:13-14` [S on intent]. | `commercial_terms.effective_agreement:51-55`, `approve:88-104` (no effective-date re-check); `ledger.post_order_collected:90`, `post_commission:94-108`, `post_sale_reversal:125-130` |
| F-14 | P2 [V] | **Settlement is a bare amount:** not linked to the orders/entries it pays, no bank-account snapshot, payable to a vendor approved with missing bank/KYC documents; bank change approved by one finance admin. Post-settlement refunds drive the vendor negative with no recovery workflow. | `finance_routes.create_settlement:291-318`, `_post_settlement_paid:369-373`; `governance_routes.decide_change:232-258`; `vendor_onboarding.final_review:653-668` |
| F-15 | P2 [V] | **"Resolve without refund" is single-person** and leaves an attached return case in `refund_pending` for ever (holds payouts indefinitely); for a vendor-rejection case it releases commission on goods never supplied without any refund. | `returns_routes.refund_case_action:298-303`; `financial_ops.has_open_case:29-35` |
| F-16 | P2 [V] | **Money state changes without an `audit_logs` entry:** order → `paid` via Stripe webhook/status poll and Razorpay client verify (only `payment_transactions` updated); automatic order cancellation in `settle_vendor_rejection`; lazy wallet paise upgrade. Collection-level records (ledgers, `order_refunds`, `webhook_events` for Razorpay) partly compensate. | `shop_routes._process_paid_order:726-761`; `returns_routes.settle_vendor_rejection:194-197`; `core.get_or_create_wallet:279-298` |
| F-17 | P2 [V] | Clawback is pro-rated on GST-inclusive goods value, not per-line taxable value — inexact on mixed-GST orders (known R-8/L5; base rule is "taxable value"). | `shop_routes._reverse_commission:576-578` |
| F-18 | P2 [S] | **COD cash custody is not modelled:** the vendor ledger credits the vendor's full line value at COD confirmation regardless of who holds the cash (platform courier vs vendor's own courier). If vendors self-ship COD, settlements would pay cash the vendor already holds. | `ledger.post_order_collected:70-91`; `shop_routes.cod_collected:343-366` |
| F-19 | P3 [V] | `wallets.applied_ops` grows without bound (one entry per distribution / release / clawback / withdrawal) and every wallet write matches `$ne` on it. | `financial_ops.move_wallet_once:48-58`; `admin_routes.review_withdrawal:895` |
| F-20 | P3 [V] | Checker may approve a manual credit to their own wallet (Batch 11 L4). | `financial_approvals.approve:85-115`; `admin_routes.apply_wallet_credit:1358-1388` |
| F-21 | P3 [V] | Misc: `manual_payment_by_distributor` always targets the member's *latest* payable order and audits `paid` even if the claim lost; `razorpay_create_order` / `create_checkout` accept COD orders (capture then flagged duplicate); COD of an all-unsupplied order expects only the COD fee; `delete_order` checks a non-existent `commissions.reference_order_id`. | `shop_routes:885-907`, `:419-436,459-469`; `cod_rules.expected_cod_paise:229-231`; `admin_routes.delete_order:563` |

---

## 1. Order splitting and vendor-level allocation

- One order, one `fulfilments[]` entry per distinct `vendor_id`; lines without a vendor are platform-owned and have no fulfilment
  (`shop_routes.create_order:249-258`). Lines snapshot `vendor_id`, `price_paise`, `total_paise` (GST-inclusive),
  `taxable_paise`, `gst_paise`, `gst_rate`, `hsn_code` (`:190-204`). Totals: `subtotal_paise` = Σ taxable (commission base),
  `items_total_paise` = Σ inclusive, `total_paise` = items + COD fee (`:220-235`). [V]
- Vendor allocation is per line: `ledger.vendor_lines_paise:40-41` = Σ vendor's `total_paise` (inclusive). Vendor platform
  commission is on that inclusive value (`post_commission:102`) — D-09 (tax adviser) still open. [V]
- Invoice: one invoice number per order (`next_sequence("invoice")`), rendered client-side; no seller GSTIN / per-vendor tax
  invoice [S compliance gap, D-18/D-09].

## 2. Inventory reservation and release (`stock.py`, `stock_txns`)

| Operation | Key / mechanism | Crash recovery | Verdict |
|---|---|---|---|
| Reserve at order creation | `stock_txns.key = reserve:<order>`; per line atomic `$inc` + marker `stock_ops.<m>` in the same product update (`_apply_line:59-86`); commit/rollback arbiter (`_arbiter`) | `abandon_reservation` if the order insert fails (`:237-245`); `recover_stock_txns` for stale txns (min age 120 s) | Sound [V] (requires `stock_txns_key_unique`, F-4) |
| Release (expiry, cancel, vendor reject) | `release:<order>:<line>:<gen>`; `stock_released` per line | restock intents stored atomically with the state change and replayed (`run_intents:531`, `process_restock_intents`) | Sound [V] |
| Late-payment revival | settle expiry release first, then `revive:<order>:<n>` all-or-nothing (`handle_late_payment:366-394`) | `finish_revival` idempotent on `revive_done_txn` | Sound [V] |
| Return restock | `retrestock:<case>:<i>` after inspection only | `reconcile_returns` | Sound [V] |
| Vendor manual adjustment | conditional `$inc` (no negative) | none; no idempotency key (retry doubles) | P3 |
| Admin cancel fulfilment overwrite | `restock_on_confirmed_cancellation` and `expire_one` `$set` the whole `fulfilments` array from a prior read | a concurrent vendor reject in that window loses its `refund_due` marker | P3 [S] race |

## 3. Payment reconciliation — per path

| Path | Authentication | Amount / currency check | Event record | Apply | Recovery of side effects | Verdict |
|---|---|---|---|---|---|---|
| Razorpay webhook `POST /webhook/razorpay` | HMAC-SHA256 raw body (`payment_events.verify_signature:48`) | ✔ INR + amount == order `total_paise` (`apply:129-133`) | ✔ `webhook_events` unique `event_id`, claim/stale takeover (`claim:74-91`), attempts history | `_process_paid_order` | ✔ `complete_paid_order` re-runs sale + commission on every processed event (`:139-140`) | Sound, except F-11c |
| Razorpay client verify `POST /payments/razorpay/verify` | HMAC of order|payment (SDK) + server fetch | ✔ amount == `tx.amount`; ✘ currency not checked (`:505-509`) | ✘ (only `payment_transactions.razorpay_payment_id`) | `_process_paid_order` on `captured`; `authorized` waits (`:512-516`) | ✘ (F-3) — covered only if the webhook also arrives | P2 |
| Stripe webhook `POST /webhook/stripe` | `stripe.Webhook.construct_event` (repo shim) / Emergent package [S] | ✘ | ✘ | `_process_paid_order` | ✘ | F-8 |
| Stripe status poll `GET /payments/status/{sid}` (no auth) | trusted fetch from Stripe | ✘ (`amount_total` fetched but unused) | ✘ | `_process_paid_order` | ✘ | F-8 |
| UPI claim → confirm / reject | customer claim; finance confirm/reject (`require_finance_admin:830`) | ✔ exact amount (`_check_amount:852`); reference unique by `_id` (`_reserve_payment_reference:857`) | `payment_transactions` `manual_<order>`; audit `upi_payment_confirmed` | `_process_paid_order`; post-check returns 409 if not paid (`:942-945`) | ✘ (F-3) | F-7, F-11a/b; R-7 (L2/L3) open |
| Manual payment | finance, single person | ✔ exact amount | `admin_<order>` tx; audit | `_process_paid_order` (no post-check) | ✘ | F-7, F-21 |
| COD collect | admin / super_admin, single person (D-03) | ✔ equals expected (`hold_reason:153`) else `cod_discrepancy` | audit `cod_collected` | CAS `cod_pending → paid` (`:343-355`) | ✘ (F-3) | F-7 buyer gap |
| COD resolve | finance, ≠ reporter, ≠ seller | ✔ per resolution | audit | CAS `cod_discrepancy → paid` | ✘ (F-3) | Sound otherwise |

**Core claim (`_process_paid_order:696-761`).** CAS on `payment_status ∈ {pending, claimed}`, `payment_method ≠ cod` and the
cancellation state read (`:726-728`), 3 attempts. A second capture for an already-paid order is recorded once as
`duplicate_payments[]` refund-due and blocks payouts (`_flag_unapplied_capture:676-693`; `eligibility.payout_block:93-94`). Invoice number is
drawn before the claim (gaps on lost claims; accepted). After the claim: `post_order_collected` → `notify_order_vendors` →
customer notification → `distribute_sale_commissions` — any exception in the middle skips the rest permanently (F-3).

## 4. Refund allocation

Flow: refund case (`awaiting_review → initiated → confirmed`, confirm by a different finance admin, `refund_case_action:273-368`)
→ `reverse_order_financials(order, reference, case_id, vendor_id)`:
1. event `order_refunds._id = <order>:refund:<reference>` (insert-or-read; amount fixed at first insert) [V];
2. `_reserve_refund` CAS on `refunded_paise` (or the legacy float) + `$push refund_event_ids` (`:531-555`) [V];
3. resume an incomplete commission plan, then `_reverse_commission` per commission with a recorded intent in
   `reversal_records[]` (`op_key clawback:<event>:<commission>`) and `snapshot_filter` CAS (`:558-595`) [V];
4. `ledger.post_refund_shares` — whole amount to the named vendor, else pro rata on `base = sale + reversals` over the goods basis
   (excl. COD fee), the closing refund takes the exact remainder (`ledger.py:134-160`) [V];
5. event `completed` + audit.

Idempotency: per (order, reference) event; retry with the same reference resumes. **Defects:** F-2 (rejected event still confirms
the case), F-10 (silent cap), F-17 (mixed GST), F-15 (no-refund resolution). Provider refunds are never verified
(`verify_provider_refund:266` always false) — all refunds are manual reconciliation. No sweep resumes `order_refunds` stuck in
`processing`; resumption depends on a finance admin re-confirming with the same reference (P3).

## 5. Commission allocation, release and reversal

| Step | Mechanism | Idempotency | Crash recovery |
|---|---|---|---|
| Plan | `commission_plans._id = order_id`, recipients + exact paise frozen once (`_freeze_plan:123-179`); base = taxable subtotal minus unsupplied COD goods (`:133-135`) | `_id` | resumed by `release_due_points:305` and the refund path — **only if the plan exists** (F-3) |
| Distribution | `commissions._id = dist:<order>:<type>` → ledger row `op_key` → `move_wallet_once` (`applied_ops`) → `distribution.applied` (`_apply_item:182-220`) | `_id` + unique `op_key` + `applied_ops` | ✔ |
| Release | intent `release{op_key, amount, applied:false}` set by CAS `snapshot_filter`, then `finish_release` (`release_due_points:337-346`, `financial_ops.finish_release:67-88`) | `op_key` | ✔ unfinished intents finished first (`:307-309`) |
| Clawback | `reversal_records[]` intent then `finish_reversal` (pending pool or available) | `op_key` | ✔ on the next refund call for the same event |
| Manual release / hold | `release_commission_now:352` (same conditions); hold flag (`admin_routes.commission_status:605-635`) | CAS | ✔ |

Eligibility (`commission.is_commission_eligible:72`): role `distributor` + `green`; buyer never earns; skipped shares not
redirected. 30/10/5 read from settings (F-6). Funding shortfall only flagged (`funding_snapshot:93`). Released-then-clawed
commissions can make `available_balance` negative; new withdrawals are refused and paying a reserved one is blocked
(`review_withdrawal:895-910`). Release scale limit F-9.

## 6. Vendor payable (`ledger.balances`, `_eligible_paise`)

`vendor_payable = SALE + SALE_REVERSAL + REFUND + ADJUSTMENT + COMMISSION`; `available_for_settlement = min(payable − settled,
eligible) − open settlements`, where `eligible` sums each order's entries only if `payout_block(order, vendor_id)` is `None`,
plus entries without an order (adjustments, payouts) (`ledger.py:178-225`). Per-vendor delivery (`delivered_at(order, vendor_id)`).
[V] Sound arithmetic; F-1 leaves RTO sales held for ever; F-13 commission questions; O(entries + orders) with a DB query per
order (`has_open_case`) on every balance read and for every vendor in `admin_vendor_balances` (P3 performance). The module
docstring still says commissions are not applied and payable is provisional (`ledger.py:18-19`) while `balances` returns
`provisional: False` — doc drift.

## 7. Settlement eligibility and flow (`finance_routes.py`)

`requested` (finance; policy active; vendor selling; amount ≤ available) → `approved` (≠ creator) → `paid` (≠ approver, reference
≥ 3, re-checked `≤ min(pending, available + in-progress)`) → `SETTLEMENT_PAID` entry `settle:<sid>`; `rejected` / `failed`
need a reason (`:291-373`). One open settlement per vendor by unique partial index (F-4 if missing). Crash between `paid` and the
ledger entry repaired by `reconcile_settlements:376-383` (cron + admin). [V] Gaps: F-14; creator = payer allowed (D-02);
`require_dual_approval` policy flag is stored but unused (two-person is unconditional — fine, but dead config); no "paid → failed"
reversal for a bounced transfer (P3).

## 8. COD (`cod_rules.py`, `shop_routes.cod_collected`, `finance_routes` discrepancy)

Expected cash = total − goods whose vendor rejected / cancelled / RTO'd (`expected_cod_paise:229`); commission base excludes them
(`cod_collected:347-348`); any mismatch or manual evidence → `cod_discrepancy` held for a different finance reviewer, who must give
courier/provider evidence; `accept_short` posts vendor sales pro rata and keeps commission held (`short_collection_held`, no
release path until the owner sets a policy). Commission requires `collection_is_proven` everywhere (`commission.py:268,238,321,378`).
Vendor view of COD state `finance_routes._cod_state:129`. [V] Gaps: F-3, F-7 (buyer), F-18 [S], D-03 open, F-21 (fee-only
expectation).

## 9. HomeGenie withdrawal

Request: green distributor, KYC verified, `wallet_apply` conditional debit available→pending (`require_available`), HELD row,
request doc (`wallet_routes.request_withdrawal:157-194`). Review: approve (finance, KYC re-check), mark_paid (≠ approver, KYC
re-check, unique payout reference `withdrawal_payout_refs._id`, wallet move guarded by `applied_ops ∌ {pay, reject}` and
`available ≥ 0`), reject returns the reservation; ledger row by `op_key`; status CAS; retry finishes (`admin_routes:806-940`). [V]
Sound except F-12 and: the request snapshots no bank details (KYC at pay time is used; acceptable because KYC changes reset to
pending); no idempotency key on the request (P3).

## 10. Financial approvals (`financial_approvals.py`)

Wallet credit and vendor adjustment only: `_id = kind:key`, payload-equality on resubmission, CAS `pending → approving`, stale
takeover after 5 minutes (never by the maker), idempotent executors (`admin_credit:<request_id>`, `adj:<vendor>:<key>`). [V] Sound.
Not covered by the approval engine although they move or decide money: commission-rate and return-window settings (F-6, D-05),
manual payment (F-7), refund-case "resolve without refund" (F-15), vendor bank change (F-14), activation (single admin),
COD confirmation (D-03).

## 11. Idempotency inventory

| Effect | Key | Enforced by | Fail-open without migration? |
|---|---|---|---|
| Order paid | CAS on `payment_status` | document update | no |
| Vendor SALE / COMMISSION / REFUND / REVERSAL / SETTLEMENT | `vendor_ledger.source_key` | unique index | **yes** (F-4) |
| Commission plan / record | `_id` | `_id` | no |
| Wallet ledger row | `wallet_transactions.op_key` | unique partial index | **yes** (`ensure_ledger` pre-check narrows but does not close the race) |
| Wallet aggregate move | `wallets.applied_ops` `$ne` | single-document atomic update | no |
| Refund event | `order_refunds._id` | `_id` | no |
| Refund case per obligation | `refund_cases.source_key` | unique index | **yes** |
| Settlement one-open | partial unique on `vendor_id` | unique index | **yes** |
| Payment reference (UPI/manual) | `payment_references._id` | `_id` | no |
| Webhook event | `webhook_events.event_id` | unique partial index | **yes** |
| Stock txn | `stock_txns.key` | unique index | **yes** |
| Withdrawal payout ref | `withdrawal_payout_refs._id` | `_id` | no |
| Withdrawal request | — | none | n/a (P3) |
| Stripe event | — | none (relies on order CAS) | n/a (F-8) |

## 12. Crash-recovery matrix (crash right after the named step)

| Flow / step | Outcome | Repaired by |
|---|---|---|
| create_order: stock reserved, order insert fails | stock returned | `abandon_reservation` / `recover_stock_txns` ✔ |
| `_process_paid_order`: after claim, before vendor sale | sale missing | `reconcile_ledger` ✔ **only within the oldest 500** (F-5); Razorpay webhook ✔ |
| `_process_paid_order` / COD: after claim, before commission plan | commission never credited, undetected | Razorpay webhook only (F-3) |
| distribution: after plan, mid-recipients | partial | `release_due_points` resumes ✔ (COD needs proof) |
| release: after intent | wallet not moved | `release_due_points:307` ✔ |
| refund: event created, before reservation | — | same-reference re-confirm ✔ (or F-2 if another refund intervened) |
| refund: reserved, before clawbacks/vendor shares | order marked refunded, books partial | same-reference re-confirm ✔; vendor shares also by `reconcile_ledger` (F-5); no automatic sweep (P3) |
| settlement: `paid` status, before ledger | vendor over-shown as unpaid | `reconcile_settlements` ✔ |
| withdrawal request: after wallet move | reserved money with no request | none (F-12) |
| withdrawal pay/reject: after wallet move | — | retry finishes ✔ |
| approval: in `approving` | — | stale takeover ✔ |
| return inspection: after `inspected` | — | `reconcile_returns` ✔ |
| paid cancellation / vendor rejection | — | markers `refund_due_cancel` / `fulfilments.refund_due` → `ensure_cases_for_flagged_orders` ✔ (late-payment branch can starve, F-9) |

## 13. Legacy float vs paise

- Orders, commissions, wallets, withdrawals, refunds carry `*_paise` beside floats; every calculation reads paise with a float
  fallback (`money.paise_of:632`). Writers update both in the same update (`wallet_apply:301-315`, `move_wallet_once`,
  `_reserve_refund:548`). Wallet reads return values derived from paise (`core._wallet_view:271-276`). [V]
- Disagreement is possible but harmless to calculation: wallet float counters are `$inc`-ed with rounded floats and may drift by
  binary-float error; only display/report code reads floats directly (`wallet_routes.dashboard:266-294` commission sums,
  `leaderboard` `$sum: "$subtotal"`, `admin_routes` REPORTS). Reports therefore can differ from the ledger by float error (P3).
- `payment_transactions.amount` is float only; Razorpay verify converts it with `to_paise` (exact for values produced by
  `paise_to_float`). [V]
- `_reserve_refund` guards legacy orders on the exact float read (`:544-545`); `money_migration.py` is additive and
  verifiable. Lazy wallet upgrade (`get_or_create_wallet:288-296`) writes paise from floats without an audit row (F-16).

## 14. Audit history

`audit_logs` is append-only through the API (`DELETE` refused and itself logged, `admin_routes.clear_audit_logs:1456-1460`), IP
via hardened `client_ip`. No hash chain / external sink (tamper-evidence P3). Gaps in F-16. Ledgers (`vendor_ledger`,
`wallet_transactions`, `order_refunds`, `webhook_events`, `refund_cases.events`, `settlements.events`) are the stronger trail.

---

## 15. Doc-vs-code differences (financial)

| Document | Claim | Code |
|---|---|---|
| `payment_events.py` docstring | "Spec: docs/PAYMENT_RECONCILIATION_SPEC.md" | File does not exist; no `docs/PAYMENT_*` file exists. |
| `FINANCIAL_STATE_MACHINE.md` | online `pending → paid` "(gateway capture / webhook, verified amount)" | Stripe webhook / status poll verify no amount or currency (F-8). |
| `FINANCIAL_STATE_MACHINE.md` | "`reconcile_ledger` rebuilds anything missing" | Oldest 500 paid orders only (F-5). |
| `FINANCIAL_STATE_MACHINE.md` | "Percentages 30 / 10 / 5 unchanged (S-7)" | Editable by one finance admin (F-6). |
| `FINANCIAL_STATE_MACHINE.md` | Refund case `confirm` = refund booked | Can confirm with nothing booked (F-2). |
| `FINANCIAL_STATE_MACHINE.md` | Payout needs "no refund obligation"; RTO listed as a fulfilment end | RTO creates no obligation (F-1). |
| `OWNER_DECISION_REGISTER.md` S-4 | Manual payment confirmation maker-checker | Single person (F-7). |
| `ledger.py` module docstring | Commissions / fees not applied; payable "provisional" | `post_commission` charges agreements; `balances()` returns `provisional: False`. |
| `commercial_terms.py` docstring | "commission … calculated once, when the sale is posted; later agreements never change past commissions" | Re-invoked by every `post_order_collected` run; a late-approved, back-dated agreement charges previously uncharged orders (F-13b). |
| `ENGINEERING_LOG_BATCH12_ONWARD.md` | Everything uncommitted; ends at Batch 13 | Committed in `d31cb74`; Batch 14 (payment reconciliation) undocumented. |
| `PRODUCTION_READINESS_CHECKLIST.md` | Index migration is a staging step | Correct, but the app does not refuse to run without it (F-4); Batch 14 `webhook_events_status_created` / `_session` not listed. |
| `KNOWN_GAPS_AND_RISKS.md` | "webhook events linked to orders" missing | Done for Razorpay; Stripe has no event record. |
| `HOME_GENIES_BATCH11_PRE_RELEASE_AUDIT.md` §D | "Online payment … webhooks (HMAC + unique webhook_events) … Sound" | Holds for Razorpay only; Stripe never wrote `webhook_events`. L2, L3, L4, L5, L13, L14 still open; C-12, C-19, C-20 remain owner decisions. |

## 16. Not verified
No runtime probes (concurrency findings F-2, F-10 are from code reading of the CAS conditions); Emergent `emergentintegrations`
Stripe package; production index state; real gateway payloads; hosting topology.

---
## Programme 01 resolution (2026-11-23) — the findings above are kept as found; this section records what changed
Details and tests: `PROGRAMME_01_TECHNICAL_SPECIFICATIONS.md`. Nothing below is production-verified.

| Finding | Status after Programme 01 |
|---|---|
| RTO had no money effect; commission released on undelivered goods (B-001, P0) | **Resolved.** RTO of a paid group records `refund_due` atomically, reverses that vendor's sale and platform commission, opens one `returned_to_origin` refund case; commission held then clawed back proportionally on refund; restock only after inspection. Historical RTO orders reported, not rewritten. |
| Refund case confirmable with nothing booked (B-002, P0) | **Resolved.** Exact booking; confirmation only on a completed event of the case's amount; a rejected / zero booking leaves the case open, records and audits the failure, allows a corrected retry with the same reference. |
| Commission lost after a crash on non-webhook paths (B-003, P0) | **Resolved.** One shared idempotent completion for every payment path; `completion_due` written with the paid claim; finished by a retry or the repair sweep; refunded-before-plan orders blocked for finance. |
| Idempotency depended on an index migration the app never checks (B-004, P0) | **Resolved in code** (money writes fail closed per area with exact index checks; duplicates reported by record). **Production migration not run** — owner action P1-01. |
| `reconcile_ledger` 500 cap; release 5,000 caps; obligations 200 cap (B-005) | **Resolved.** Keyset sweeps with checkpoints, isolation, dry run, time budget; maintenance runs recorded. |
| Vendor B's open case held vendor A's settlement | **Changed** (directive §5.3): vendor-specific cases hold only that vendor's settlement; order-wide cases and the HomeGenie commission still wait. |
| Refund cases may promise more than is refundable (B-021) | **Still open** — now visible: the exact booking refuses the excess at confirmation, and the cross-module reconciliation reports it as `over_promised`. |
| Single-person money actions, runtime commission rates, Stripe gaps, unrecorded money owed (B-012/13/15/20) | Unchanged — Programme 03. |

Reconciliation used by the cross-module suite (integer paise, no balancing entries):
`paid − COD fee − refunds booked − refund owed for not-supplied groups = net vendor goods (SALE_COLLECTED + SALE_REVERSAL + REFUND)`;
each HomeGenie commission's reversal = credited × refunded / goods value (±1 paisa); wallet aggregates = wallet ledger;
stock = start − units still reserved.

## Programme 03 resolution (2026-11-27) — the findings above are kept as found; this section records what changed
Details, tests and evidence: `HOME_GENIES_PROGRAMME_03_ENGINEERING_REPORT.md`. Local / isolated test database only; nothing is
production-verified, committed or deployed.

| Finding | Status after Programme 03 |
|---|---|
| F-8 / DEF-05 — Stripe webhook and status poll completed orders without an amount / currency / order check and recorded no event (§3) | **Resolved in code.** Both paths read Stripe's own session record server-to-server and pay only when it says `paid`, in INR, for exactly the order's `total_paise`, for the order of OUR payment attempt (`metadata.order_id`, provider `stripe`). One `webhook_events` record per webhook delivery (Stripe event id) and one per checkout session for the poll (created only once Stripe says paid), with the Razorpay claim / stale takeover / outcome / attempts / finance-retry rules; the retry re-reads Stripe, never the stored figures. Applied only through `_process_paid_order` + `complete_paid_order`. A Razorpay attempt can never be paid by a Stripe event. Still **unconfigured by default** (P0-01 / DEF-06 unchanged). |
| §9 — withdrawal request not crash-safe, no idempotency key (B-022) | **Resolved.** Intent first (`reserving`), then one keyed hold on the wallet (`applied_ops withdrawal_hold:<id>`, conditional on the available balance), then the HELD ledger row (`op_key`), then `reserving → pending`. A void marker (`withdrawal_void:<id>`) excludes the hold atomically, so a request either holds money or is closed `not_reserved`, never both. Optional `request_key` (unique per member) makes retries return the same request; the repair sweep (daily maintenance) finishes or closes interrupted requests and never reserves new money. Notice and audit are written once (`effects_due`). Eligibility, limits, approval, payout unchanged. |
| §7 — settlements recorded no order basis and no payee bank details (B-023) | **Resolved.** Each new settlement stores an immutable snapshot (eligible orders with net ledger amounts, held orders with reasons, non-order entries, the balance figures, the requested amount, payee bank details masked: holder, IFSC, last four, last approved bank-change id) and its SHA-256 digest. No code path updates it; `mark_paid` refuses a snapshot that does not verify or whose bank details changed since the request (reject and re-request). Legacy settlements (no snapshot) behave as before. The snapshot is evidence, not authority to pay. |
| No single reconciliation across money domains | **Added.** `reconciliation.py` (+ `GET /api/admin/finance/reconciliation`, `scripts/financial_reconciliation_report.py`): payments, wallets, withdrawals, settlements, vendor ledger, refunds, commissions, stock; read-only (proven by a full-database fingerprint before / after); each domain isolated. |
| Single-person money actions, runtime commission rates, unrecorded money owed, over-promising refund cases, provider refunds, bank payouts (B-012/13/20/21, G8, G9) | Unchanged — owner decisions / external integrations (see the Programme 03 report §J–K). |

## Programme 03-B resolution (2026-11-27) — P03-A01 / P03-A02
Detail: `HOME_GENIES_PROGRAMME_03B_FINANCIAL_LIABILITY_INTEGRITY_REPORT.md`. Uncommitted; local only.

| Finding | Status |
|---|---|
| P03-A01 — customer cancellation of a paid order committed without a durable obligation; a payment landing between read and claim could also produce paid + cancelled + unrecorded (customer and admin cancel) | **Resolved.** `refund_due_cancel` in the cancellation claim; claims pinned to the payment state read; idempotent settle (restock → reversal → one `cancel:` case → marker cleared), finished by the existing obligation sweep after any crash. |
| P03-A02 — payment claimed on a cancelled order; a crash before the late-payment decision lost the obligation and completion cleared its marker | **Resolved.** `late_payment_due` (with lease) in the paid claim on every payment path; unchanged decision under the lease; `repair_late_payments` in the daily maintenance; completion waits while a decision is pending. |
| No check for duplicated / orphaned liabilities or revenue on refund-owed orders | **Added** — reconciliation `liabilities` domain. |
