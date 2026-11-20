# HOME GENIES — Engineering log: owner decisions (2026-11-20) and Batches 5–10

Continues `docs/ENGINEERING_LOG_BATCHES_0-4.md`. Baseline `5b7adc2`; all work uncommitted. Verified only on the isolated test
MongoDB (`hg-test-mongo`, throwaway `*_test` databases) and a local headless-Chrome check. Nothing is production-verified.

## Owner decisions — how each was implemented

| # | Decision | Implementation | Tests |
|---|---|---|---|
| 1 | Prices are GST-inclusive | `shop_routes.create_order`: each line's taxable value = inclusive × 100 / (100 + rate), rate = the product's own valid GST rate, else the platform setting (no rate invented). Order `subtotal` = taxable total (the commission and activation base, so 30/10/5 is unchanged in percentage), `gst_amount` = GST contained, `total` = inclusive goods + COD fee. Lines snapshot `gst_rate`, `taxable_paise`, `gst_paise`, `hsn_code`. Refunds of new orders use the inclusive line value (no extra GST share); older GST-exclusive orders keep their original refund maths. Invoice shows taxable value, GST included and total. `money_version` 3, `prices_include_gst: true` | `test_catalogue_batch3` (rates, mixed rates, COD fee), `test_money_exact`, refund suites |
| 2 | Commission payable after delivery + return window | `eligibility.payout_block` — one rule for both money systems. Commission release (cron and manual "release now") requires: delivered (`delivered_at`), the longer of the return-policy window and the commission's frozen hold has passed, no open return/refund case, no refund obligation, payment not refunded/unpaid/COD discrepancy, no duplicate payment awaiting refund, not cancelled. `delivered_at` is now recorded by every path that delivers an order | `test_payout_eligibility` |
| 3 | Vendor settlement after delivery + return window; unresolved orders held | `ledger.balances`: `available_for_settlement` counts only ledger entries of eligible orders (plus entries with no order, e.g. adjustments and payouts); new `awaiting_eligibility_paise`, `held_orders`. Settlement creation is capped by it; "mark paid" re-checks it | `test_payout_eligibility`, `test_finance_ledger` |
| 4 | Finance-only payment confirmation; maker-checker | UPI confirm / reject and manual payment: `super_admin`, `accounts_admin` only. New `financial_approvals.py`: wallet credits and vendor adjustments are requested by one finance admin and executed only when a different finance admin approves (idempotent, compare-and-set, audited with both people). Settlement: creator ≠ approver ≠ payer, always (the policy flag can no longer switch it off). Refund case: initiator ≠ confirmer | `test_owner_decisions` (decision 4 group), `test_manual_money_controls`, `test_finance_ledger`, refund suites |
| 5 | Distinct CUSTOMER role | Sign-up offers "Shop as a customer" (`account_type=customer`): role `customer`, id `CU######`, no sponsor link, no earning, no withdrawal, never activatable. The existing sign-up still creates a RED distributor. Existing users are not converted; `scripts/customer_role_report.py` is a read-only report for the owner | `test_owner_decisions` (decision 5 group) |
| 6 | Final vendor approval super-admin only | Unchanged (already enforced) | `test_vendor_authority` |
| 7 | Depth-based commission inactive | No change to percentages or depth logic | — |
| 8 | KYC second person | The admin who last edited KYC details cannot verify them; a member's own resubmission clears the marker | `test_owner_decisions` |
| 9 | UPI claim expiry 24 h | Setting `upi_claim_expiry_hours` (default 24). Sweep `stock.expire_upi_claims`: claim → `claim_expired`, order cancelled, stock released once, audited, customer notified. Confirmation after expiry is refused (409) and nothing is marked paid; a confirmation that wins first stops the expiry; a rejection returns the order to the normal unpaid path | `test_owner_decisions` (incl. interleaving race) |
| 10 | Reset authority | Password reset: `super_admin` and `admin` only (support/finance refused), all Batch 0 safeguards kept | `test_owner_decisions` |

## Batches

| Batch | Delivered | Status |
|---|---|---|
| 5 HomeGenie | Share-link attribution (Batch 5 part 1), KYC screens, **commission statement** (`GET /api/commissions/statement`, Wallet page: earned / released / waiting / reversed, and why each line is held) | Completed and tested (API); screens browser-checked |
| 6 Vendor finance | Decision 3 eligibility, maker-checker (decision 4), duplicate-payment refund recording lifts holds | Completed and tested; **return-window duration still to be confirmed before launch** |
| 7 Admin operations | `/admin/operations`: approvals queue, refund cases (initiate / confirm by another admin / fail / close), contested returns, vendor balances + settlements (request / approve / pay), COD discrepancies, duplicate payments, bank-change approvals, support replies. `/admin/kyc`, `/admin/team` (earlier) | Completed; API contract tested; screens browser-checked |
| 8 Customer | Customer role, search + sort, order self-service (cancel, return / replacement with quantities, refund status), profile details + password change, GST-inclusive cart/checkout/invoice | Completed; browser-checked. Address book and wishlist **not built** (no backend existed; not required for purchase) |
| 9 Vendor | Suspended vendors keep access to paid orders and open returns (not selling), permission-aware staff menu, absolute owner-invitation link | Completed and tested |
| 10 Hardening | Security headers on every response, JSON 500 with error id (CORS kept) instead of raw errors, hot-lookup indexes (`users.id`, `orders.id`, `products.id`, `payment_transactions.session_id`, `kyc_records.user_id`, `login_attempts.identifier`, contact changes) | Completed and tested |

## API changes in this round

| Endpoint | Change |
|---|---|
| `PUT /api/admin/payments/upi-confirm/{id}`, `/upi-reject/{id}`, `POST /api/admin/payments/manual` | finance roles only; confirm returns 409 if the claim expired meanwhile |
| `POST /api/admin/wallet/credit`, `POST /api/admin/finance/vendors/{id}/adjustments` | now create a pending request (`status: pending_approval`); nothing moves until approved |
| new `GET/POST /api/admin/finance/approvals[/{id}/approve|reject]` | maker-checker queue |
| `POST /api/admin/finance/settlements/{id}/action` | creator ≠ approver ≠ payer always; payment capped by eligible money |
| `POST /api/admin/refund-cases/{id}/action` | confirm refused for the initiator |
| `POST /api/admin/users/{id}/reset-password` | super_admin / admin only |
| `PUT /api/admin/kyc/{id}` | verify refused for the last editor |
| `POST /api/auth/register-request` | `account_type` (`homegenie` default, `customer`) |
| new `GET /api/admin/payments/duplicates`, `POST /api/admin/payments/duplicates/{order_id}/refunded` | duplicate-capture handling |
| new `GET /api/commissions/statement` | member statement |
| order responses | GST-inclusive fields (see decision 1) |
| vendor balances | `available_for_settlement_paise` now eligibility-based; `awaiting_eligibility_paise`, `held_orders`; `provisional: false` |
| vendor order / return routes | also open to suspended vendors |

## Data changes (additive, backward compatible)
New collection `financial_approvals`. New fields: orders `delivered_at`, `claimed_at`, `prices_include_gst`, `items_total_paise`,
lines `gst_rate`/`taxable_paise`/`gst_paise`; settings `upi_claim_expiry_hours`; users role `customer`. Older orders keep their
GST-exclusive figures and refund maths. Orders delivered before `delivered_at` existed fall back to the latest delivered fulfilment
event or `updated_at` (documented in `eligibility.delivered_at`). New index specs are non-unique except those listed in the first log.

## Owner confirmations still needed before launch
1. **Return-window duration** (`returns_policy.window_days`, today 7) and the commission hold (`return_window_days`, today 7) — both configurable; the longer applies.
2. **Tax adviser confirmation** that vendors receive the GST-inclusive line value (vendor is the GST-liable seller, platform deducts its commission) — this is how the ledger works today; no other split was invented.
3. Whether any existing RED members should become customers (report only; no automatic conversion).

## Known gaps (not done in this round)
- Address book and wishlist (no backend; checkout prefills from profile).
- HomeGenie dashboard figure corrections (HG-03), admin order detail / server-side pagination on all admin lists (ADM-06), vendor CSV import fixes (VEN-04), vendor profile screens per status (VEN-05), delivery proof (VEN-06), staff landing page for staff without `reports.read`.
- Error monitoring service (only logging with error ids), CSP for the frontend host.
- `backend/scripts/demo_environment.py` still uses the old one-step payment / credit contracts and will fail until updated.
- Live HTTP suites (7) not run; payment gateways, Twilio, email and Google not exercised.

## Final verification (2026-11-20, isolated test MongoDB only)
- Full in-process regression: 54 suites, **1190 passed, 0 failed** (`test_finance_ledger` re-run after a lint-only edit: 21 passed).
- Script tests: `test_commission_engine` PASS, `test_cod_and_badges` PASS. `test_financial_engine_isolated` skips itself (club income was removed in 96f8719, before this work).
- Not run: 7 live HTTP suites (`test_health_dashboard`, `test_regrequest_flow`, `test_it11_emailless`, `test_upi_adminlogin`, `test_otp_auth`, `test_production_hardening`, `test_cycle9_upi_ref`). They need a running staging server.
- Frontend: `CI=true craco build` compiled successfully. Headless-Chrome check of 16 screens: no console errors and no horizontal overflow at 390 px.
- Lint: no new pyflakes warnings compared with the baseline. `git diff --check` is clean.
