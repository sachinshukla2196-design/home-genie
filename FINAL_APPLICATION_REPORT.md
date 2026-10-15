# Anjali Herbal Life Ayurveda India LLP — Final Application Report
Date: 15 Oct 2026 · Environment inspected: PREVIEW (DB `anjali_ayurveda`). Production (anjaliherbal.life) runs its own database and was NOT read or modified.

## A. Executive summary
- Financial engine corrected to the authoritative rule: **Company 30% of S, Commission Pool 70% of S, GD–MDD positional rates applied to the pool** (45% of pool paid, 55% of pool retained — not normalised). Mandated ₹1,500 test passes exactly (BD ₹157.50 … total ₹472.50, company ₹1,027.50).
- Team Purchase Income now pays 2.5% of S to **every eligible GREEN upline in the first nine actual positions** (was level-1 only).
- New auditable refund engine: full/partial refunds, proportional clawback, paid-cancellation only reverses when a payment return is recorded, idempotent per refund reference, over-refund blocked, activation revert on full refund, BV reduces with refunds.
- 60/60 isolated financial tests PASS (`backend/tests/test_financial_engine_isolated.py`, runs on a throwaway DB, drops it afterwards).
- Cleanup: **2 user IDs removed** (confirmed synthetic fixtures) + orphan residue of 2 previously deleted test IDs. All genuine users preserved. No collection was truncated or reset.
- Overall status: **WORKING in preview**; production needs redeploy + two secrets (see K).

## B. Inventory
Backend (FastAPI, `/app/backend`): `server.py` (bootstrap, catalogue seed only when catalogue empty, admin seed from env, demo seeder permanently removed), `core.py` (db, wallet ledger `add_wallet_transaction`, audit, settings, referral tree), `auth_routes.py` (OTP/password/Google/admin login), `shop_routes.py` (products, orders, Razorpay/Stripe/UPI/manual payments, `_process_paid_order`, 70%-pool matrix, repurchase, team purchase, refund engine), `wallet_routes.py` (wallet, team, KYC, withdrawals, dashboard, rank/BV), `admin_routes.py` (users, approvals, orders, refunds, KYC, withdrawals, MFI, club income, income rules, reports, audit), `income_config.py` (versioned rate configs), `club_income.py` (Royalty/Master/Super Club), `cron_routes.py` (monthly cron), `providers.py` (Twilio), `storage.py` (object storage).
Frontend (React, `/app/frontend/src/pages`): Landing, Login, Register, AuthCallback, Dashboard, Products, ProductDetail, Cart, Checkout, Orders, OrderDetail, Wallet, Withdrawals, Referral, Team (Ranks/Matrix/Tree/List), KYC, Profile, Notifications, Legal; admin: Dashboard, Users, Products, Orders (+Refund), KYC, Withdrawals, Commissions, MonthlyIncome (+Club income), IncomeRules, Reports, Settings, AuditLogs, SecureLogin.
Database collections: users, registration_requests, referral_relationships, referral_codes, orders, order_refunds (new), payment_transactions, commissions, wallets, wallet_transactions, withdrawal_requests, kyc_records, activation_records, notifications, audit_logs, business_settings, income_rule_configs, monthly_income_runs, cron_runs, products, product_categories, counters, otp_*, files.
Integrations: Razorpay (TEST keys), Twilio SMS (trial-blocked), Emergent Google Sign-In, Emergent Object Storage, Postal pincode API, platform cron (`.emergent/crons.yml`).

## C. Feature status
| Feature | Status |
|---|---|
| Registration → admin approval → Distributor ID | WORKING |
| ₹100 direct referral at approval (once) | WORKING (test T8) |
| Activation ≥₹1,500 admin-confirmed / Razorpay | WORKING (T1, T6) |
| 45%-of-70%-pool positional matrix | WORKING (T1, T2) |
| Personal Repurchase 5% (skip first) | WORKING (T3) |
| Team Purchase 2.5% × 9 positions | WORKING (T1, T2) |
| Monthly Fixed Income 1% equal split | WORKING (existing, T9) |
| Royalty/Master/Super Club | WORKING per your 13-Oct decision (own-team turnover, exact rank, monthly cron) |
| Refund full/partial/paid-cancel | WORKING (T4–T7) |
| Wallet ledger/reconciliation | WORKING (all IDs ledger == wallet) |
| Withdrawals (GREEN + verified KYC + atomic debit) | WORKING — KEEP, no change |
| Team/Matrix/Tree screens | WORKING (real downline, IDs + names) |
| Twilio OTP | BLOCKED (trial account) |
| Razorpay live | PENDING (test keys) |
| Legal page content | NOT IMPLEMENTED (placeholder text) |
| Production data verification | NOT VERIFIED (no access from preview) |

## D. Financial engine (new)
S = subtotal excl. GST. `company_direct = 30%·S`, `pool = 70%·S`, position k gets `rate_k · pool` if that actual sponsor ancestor is GREEN, else ₹0 (retained). Stored per order in `orders.allocation {subtotal, company_direct, commission_pool, rank_commissions_paid, pool_retained, company_total}`. Rounding: `Decimal` ROUND_HALF_UP to paise (`money2`).
Mandated example (S ₹1,500, GST ₹75, total ₹1,575): company 450 · pool 1,050 · GD 0 · BD 157.50 · AD 52.50 · CD 52.50 · PD 52.50 · MD 52.50 · RD 42 · DD 31.50 · MDD 31.50 · commissions 472.50 · retained 577.50 · company total 1,027.50 · 1,027.50 + 472.50 = 1,500 OK (test T1).
Other plans unchanged and separate: referral ₹100, repurchase 5% of S, team 2.5% of S per eligible position, MFI 1% pool, clubs per rule.

## E. Records removed (preview DB only)
| Record | Evidence | Removed |
|---|---|---|
| Users ANJ000219 "FRN C", ANJ000220 "FRN D" | Created 2026-09-24 20:32:16 in the same second as ANJ000218 by actor=None during a scripted test burst (15 purchase commissions in 2 s); no `registration_requests`; sponsor ANJ000218 never existed as a user; no orders/KYC/withdrawals; placeholder names | 2 users, 2 wallets, 1 ledger txn (₹100 test referral), 1 commission, 2 relationships, 1 notification |
| Orphan ₹100 referral credit to ANJ000000 for ANJ000240 | ANJ000240 approved+deleted during the 2026-10-11 testing-agent run; user record absent; no relationship | 1 commission, 1 ledger txn; ANJ000000 wallet −₹100 (200 → 100) |
| Orphan wallet `bdcf9a00…` | Owner user no longer exists, balance ₹0 | 1 wallet |
**Total user IDs removed: 2.** Cleanup logged in `audit_logs` id `cleanup-2026-10-15`. Kept for your review (ambiguous, not deleted): none remaining.

## F. Preservation confirmation
Remaining users: ANJ000000, ANJ000215 (Rahul Sharma), ANJ000216 (Priya Verma), ADMIN001 (super admin). Master ID MST000001 referral code intact. Relationships MST000001→ANJ000215→ANJ000216 intact. Order ORD000076 (₹1,500 activation of ANJ000215) and its ledger intact. No `delete_many({})`, no collection drop, no wallet reset on the preview DB; test scripts only ever touch throwaway DBs (`*_tmp`) which they drop.

## G. Reconciliation (preview DB after cleanup)
ANJ000000 wallet ₹100 = 1 referral credit (ANJ000215) OK · ANJ000215 wallet ₹100 = 1 referral credit (ANJ000216) OK · ANJ000216 ₹0 OK · ADMIN001 ₹0 OK · 0 duplicate commission groups · 0 withdrawals · 0 orphan records.

## H. Code quality & security findings
- FIXED: `_process_paid_order` non-atomic paid claim (concurrent Razorpay verify + webhook) → now aborts unless it wins the atomic claim (test: 4 concurrent → 1 activation record).
- FIXED: dashboard/team income counted REVERSED commissions.
- FIXED: `status=refunded` via plain status change reversed everything without a refund reference — now blocked; Refund action requires reference + amount.
- FIXED: float rounding → Decimal half-up for all new money math.
- OK: all admin routes behind `require_admin`; withdrawals atomic; ledger immutable (originals never deleted; clawbacks linked by `reference = order:refund:<ref>`).
- NOTE: `admin DELETE /orders/{id}` hard-deletes an order (pre-existing). Recommend disabling for paid orders — not changed without approval.

## I. Changes (files/functions)
- `backend/shop_routes.py`: `COMPANY_DIRECT_PCT`, `COMMISSION_POOL_PCT`, `money2`, `commission_pool`; `_distribute_purchase_commission` (pool base, allocation snapshot); `_credit_team_purchase` (9 positions); `_credit_personal_repurchase` (rounding); `reverse_order_financials` (partial/idempotent/paid-cancel); `_process_paid_order` (atomic claim).
- `backend/admin_routes.py`: `update_order_status` (refund via status blocked, cancel never auto-reverses); new `POST /api/admin/orders/{id}/refund` (`RefundBody`).
- `backend/wallet_routes.py`: `_personal_bv` (refund-aware), dashboard label, CREDITED-only income.
- `frontend/src/pages/admin/AdminOrders.js`: Refund button (amount, mandatory reference, optional cancel).
- `backend/tests/test_financial_engine_isolated.py`: 60-assertion isolated suite.

## J. Test evidence
Isolated suite: 60 PASS / 0 FAIL — covers exact ₹1,500 chart, 9-position chain, ineligible positions + company retention, GST exclusion, concurrent payment ×4, activation, first-purchase repurchase exclusion, repurchase on 2nd order, team purchase 9/7 positions, partial refund 50%, duplicate refund reference rejected, remaining refund, over-refund blocked, repeated reversal, paid-cancel without return keeps credits, activation refund → RED, unpaid cancelled → 0 credits, referral idempotency via real approve flow, MFI exclusion, BV before/after refunds, ledger == wallet for every ID.
API checks (preview, admin JWT): refund without reference → 400; status=refunded → 400 guidance; over-amount → 400; dashboard breakdown label updated.
Startup after cleanup: backend healthy (`/api/products` 200). Reseed prevention: demo seeder removed from code; catalogue seed only when empty; test suite uses throwaway DB.
NOT RUN: real Razorpay webhook (test keys only), real SMS, production DB reconciliation.

## K. Remaining work / production limits
1. Redeploy to apply; add production secret `WEBHOOK_CRON_SECRET` (for the monthly club-income cron).
2. Production data was NOT inspected; any production test IDs need the same evidence-based review there (I can run the same read-only inspection via the deployer diagnostics on request).
3. Twilio upgrade; Razorpay live keys; Legal page content.

## L. Decisions needed from you
1. Historical orders in PRODUCTION paid under the old 45%-of-S formula: leave as-is (recommended, no retroactive change) or report affected records for manual adjustment?
2. Disable hard-delete of PAID orders in admin (recommended)?
3. `admin DELETE /orders` aside, no other approvals pending.
