# HOME GENIES — Module completion matrix (independent inspection)

Inspection of `main` @ `d31cb74` (clean tree), 2026-11-23. Inspection only: no test suite was run, no server started, no
existing file changed. Route-level evidence: `docs/HOME_GENIES_FRONTEND_BACKEND_MAP.md` (same date). This document does **not**
reuse the earlier `docs/MARKETPLACE_MODULE_COMPLETION_MATRIX.md`; it re-derives every status from code and test files and lists
where the earlier documents disagree (§18).

> **Test run (added by the lead architect, same programme):** the full in-process regression was run separately on `d31cb74`
> against the isolated test database: 62 suites, 1,290 passed, **2 failed** (`test_vendor_foundation`, Batch 14 contact-state
> regression, backlog B-008), 0 skipped. The seven live-server suites were not run. The "assumption" note below therefore holds
> for every in-process suite except those two tests.

## How to read this

**Status (exactly one per row)**
1 Implemented and verified (meaningful automated tests exercise it) · 2 Implemented but insufficiently tested · 3 Partially
implemented · 4 UI exists but backend incomplete · 5 Backend exists but UI incomplete · 6 Not implemented · 7 Blocked by owner
decision (`docs/OWNER_DECISION_REGISTER.md`) · 8 Blocked by external integration · 9 Deprecated or duplicated.

**Priority of each gap**: P0 financial integrity / security / data loss · P1 core business workflow incomplete · P2 important
operational capability · P3 enhancement.

**What "verified" means here.** Status 1 requires backend tests in `backend/tests/` that call the capability (found by reading
test names, docstrings and the paths/functions they reference). The tests were **not run** by this inspection; their pass state is
taken from nothing — it is an ASSUMPTION that they pass. The frontend has exactly one automated test (`frontend/src/components/Pager.test.js`);
**no screen is covered by automated tests**, so status 1 always means "backend verified, UI not automatically tested".
Seven suites need a live server (`test_cycle9_upi_ref`, `test_health_dashboard`, `test_it11_emailless`, `test_otp_auth`,
`test_production_hardening`, `test_regrequest_flow`, `test_upi_adminlogin` — they read a base URL); three files are scripts with no
pytest functions (`test_cod_and_badges`, `test_commission_engine`, `test_financial_engine_isolated`). 71 `test_*.py` files hold
964 `def test_` functions (parametrisation expands them).

**Cron/background jobs (all verified in `backend/vercel.json` + `backend/cron_routes.py`)**: J1 `GET /api/cron/release-points`
daily 20:00 UTC → `commission.release_due_points`; J2 `GET /api/cron/expire-pending-orders` daily 20:30 UTC →
`stock.expire_pending_online_orders`, `prune_stock_markers`, `returns_routes.ensure_cases_for_flagged_orders`, `reconcile_returns`,
`vendor_routes.sweep_dispatch_deadlines`, `ledger.reconcile_ledger`, `finance_routes.reconcile_settlements`. Both require the
cron bearer secret. The HTTP cron endpoints themselves: J2 path is referenced in 7 test files (e.g. `test_stock_reservation.py`),
J1 path in none (its function is tested directly). No other scheduler exists; FastAPI `BackgroundTasks` is used only by the POST
variant of J1.

Abbreviations: `T:` = test files; collections are MongoDB collection names used via `db.<name>`.

---

## A. Customer ecosystem

| ID | Sub-capability | Frontend | Backend API · service | Collections | Permissions | States · jobs · external | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|---|---|---|
| A1 | Registration (customer or member, mobile OTP when SMS works) | `Register.js` | POST `/api/auth/register-request/send-otp`, `/register-request` (`auth_routes.py:157,171`) | users, otp_sessions, registration_requests, referral_codes, referral_relationships | public, rate-limited | Twilio SMS (K3) | `test_registration_flow`, `test_registration_referral`, `test_identity_batch4`, live `test_regrequest_flow`, `test_it11_emailless`, `test_otp_auth` | 1 | — |
| A2 | Login (password, OTP login) | `Login.js`, `AuthExtras.js LoginOtp` | `/api/auth/login`, `/login-otp/send|verify` | users, login_attempts, otp_sessions, revoked_tokens | public | lockout, OTP attempt budget | `test_security_batch0`, `test_recovery_and_ledger`, `test_batch12_remediation` (C-1), live `test_otp_auth` | 1 | — |
| A3 | Google sign-in | `Login.js` → `AuthCallback.js` | `/api/auth/google/session` (`auth_routes.py:413`) calling `demobackend.emergentagent.com` (`:390`) | users | public | Emergent OAuth broker (K7) | `test_identity_batch4`, `test_batch12_remediation` (mocked) | 8 | Works only while the Emergent auth broker is reachable; no first-party Google OAuth · P2 |
| A4 | Password recovery (SMS OTP, Google-proven e-mail, admin-handled request) | `AuthExtras.js ForgotPassword` | `/api/auth/forgot/otp/*`, `/forgot/google*`, `/forgot/send` | password_reset_requests, password_reset_tokens, otp_sessions | public | admin queue on `AdminUsers` | `test_forgot_google`, `test_security_batch0`, `test_recovery_and_ledger` | 1 | — |
| A5 | Discovery: search, filters, facets, suggestions, sorting, paging | `Products.js` | `/api/catalog/search|facets|suggest` (`discovery.py:41-106`) | products (text index, `db_indexes.py`) | public | — | `test_discovery_merch_b13` (incl. query plans) | 1 | — |
| A6 | Product detail with variants; shop projection hides pending revisions / compliance docs | `ProductDetail.js` | `/api/products/{id}` (`shop_routes.py:80`, `P_SHOP` `:66`) | products | public | — | `test_catalogue_batch3`, `test_pim_batch12` | 1 | — |
| A7 | Related products; recently viewed | `RelatedProducts.js` (recent list in `localStorage hg_recent_products`) | `/api/catalog/products/{id}/related`, `/api/catalog/products` | products | public | — | `test_discovery_merch_b13` (related, by-ids) | 1 | recently-viewed is client-only (not cross-device) · P3 |
| A8 | Merchandised shop home | `MerchSections.js` on `Dashboard`/`Products` | `/api/merch/home` (`merchandising.py:143`) | merch_sections, products, orders (bestsellers) | public | dates evaluated at read time | `test_discovery_merch_b13` | 1 | — |
| A9 | Cart | `Cart.js`, `context/CartContext.js` | none (server re-prices at order creation) | — (browser `localStorage hg_cart`) | — | — | none (no frontend tests) | 2 | no server cart: lost across devices, no stock/price check before checkout · P3 |
| A10 | Checkout & order creation (GST-inclusive per-line snapshot, address snapshot, seller attribution, stock reservation) | `Checkout.js` | POST `/api/orders` (`shop_routes.py:146`); `stock.py` | orders, products, stock_txns, counters, addresses | get_current_user | order `pending` → reserved 15 min (`stock.py:30`) → J2 expiry | `test_stock_reservation`, `test_catalogue_batch3`, `test_customer_batch13`, `test_money_exact`, `test_order_lifecycle_races` | 1 | Order is created before the payment provider is known to be configured (Stripe/Razorpay 503 leaves a pending order holding stock) · P1 |
| A11 | Address book (default, soft delete, checkout snapshot) | `Addresses.js`, `Checkout.js` | `/api/addresses*` (`customer_routes.py:163-212`) | addresses | get_current_user, per-account isolation | — | `test_customer_batch13` | 1 | — |
| A12 | Separate billing address on invoices | — | — | — | — | — | — | 7 | D-18 · P3 |
| A13 | Wishlist | `Wishlist.js`, `WishButton.js` | `/api/wishlist*` (`customer_routes.py:261-309`) | wishlist_items | get_current_user | live availability; no price alerts by design | `test_customer_batch13` | 1 | — |
| A14 | Pay online — Razorpay client checkout + signature verify | `Checkout.js razorpayPay` | POST `/api/payments/razorpay/order`, `/verify` (`shop_routes.py:459,487`) | payment_transactions, orders | get_current_user | authorised-not-captured waits for webhook (F4) | none call these two routes (grep of `backend/tests`); webhook path tested (F4) | 2 | client verify path untested; live gateway never exercised (KNOWN_GAPS R-15) · P1 |
| A15 | Pay online — Stripe Checkout (default "Place order" button for method `online`) | `Checkout.js placeOrder`, `PaymentSuccess.js` | POST `/api/payments/checkout`, GET `/api/payments/status/{sid}` (unauthenticated), POST `/api/webhook/stripe` (`shop_routes.py:419,769,787`); `stripe_checkout.py` or Emergent `emergentintegrations` (`shop_routes.py:11-16`) | payment_transactions, orders | get_current_user; status route public | Stripe (K2); default key `sk_test_emergent` placeholder → 503 (`shop_routes.py:39,411`) | live `test_upi_adminlogin` (card test **skipped** without keys); `test_stock_reservation` mentions the route; **no test of `/api/webhook/stripe`** | 8 | Unconfigured by default; webhook not recorded in `webhook_events` (no reconciliation); errors only `print()`ed; `success_url` built from client `origin_url` · P1 |
| A16 | Pay by UPI (manual claim, finance confirms exact amount + unique UTR) | `Checkout.js upiPay` | POST `/api/payments/upi-claim` (`shop_routes.py:808`) | orders, payment_references | get_current_user | `pending→claimed`; 24 h claim expiry (S-9) | `test_payment_integrity_batch1`, `test_owner_decisions`, `test_order_lifecycle_races`, `test_stock_reservation`, live `test_cycle9_upi_ref` | 1 | — |
| A17 | Cash on delivery order | `Checkout.js` | POST `/api/orders` (method cod) | orders | get_current_user | `cod_pending` | `test_cod_rules`, `test_cod_route_logic`, `test_cod_safeguards` | 1 | — |
| A18 | Order list, detail, tracking (vendor fulfilment status + carrier/tracking number typed by vendor) | `Orders.js`, `OrderDetail.js` | GET `/api/orders`, `/api/orders/{id}` (`shop_routes.py:377,383`) | orders | owner or any admin role (`:387`) | no courier tracking (I3) | `test_operations`, `test_security_batch0`, `test_vendor_core` | 1 | — |
| A19 | Customer cancellation (pre-dispatch) | `OrderSelfService.js` | POST `/api/orders/{id}/cancel` (`returns_routes.py:372`) | orders, refund_cases, stock_txns | get_current_user (own order) | paid cancel → refund case | `test_returns_refunds`, `test_order_lifecycle_races`, `test_refund_return_controls` | 1 | — |
| A20 | Return / replacement request | `OrderSelfService.js` | POST `/api/orders/{id}/returns` (`returns_routes.py:446`), GET `/api/returns` | return_cases | get_current_user | `requested→approved/contested/rejected→…` | `test_returns_refunds`, `test_refund_return_controls`, `test_e2e_vendor_integration` | 1 | — |
| A21 | Return ship-back with tracking; withdraw a return | none (no buttons) | POST `/api/returns/{rid}/ship`, `/cancel` (`returns_routes.py:581,590`) | return_cases | get_current_user | `approved→in_transit`; `→cancelled` | `test_returns_refunds`, `test_e2e_vendor_integration` | 5 | customer cannot record return tracking or withdraw; vendor can still `receive` from `approved` · P2 |
| A22 | Return photos | `OrderSelfService.js` always sends `photos: []` | accepted by `request_return` | return_cases | — | — | — | 5 | no photo evidence for damaged-goods returns · P2 |
| A23 | Refund status on order | `OrderSelfService.js` (refunded amount + payment status) | `refunded_paise` on order | orders, refund_cases | — | refund case flow (G7) | via G7 tests | 2 | customer sees amount only, not the refund case stage/reference · P3 |
| A24 | Invoice | `OrderDetail.js` printable card (`window.print()`, `:47`), invoice number shown | `invoice_number` assigned at payment (`shop_routes.py:725,742`; `stock.py:355`; `finance_routes.py:444`) | orders, counters | owner | — | indirect (payment tests) | 3 | browser print only; no PDF, no per-seller GST tax invoice / seller GSTIN, D-18 billing address · P1 (see O19) |
| A25 | In-app notifications | `Notifications.js`, `AppLayout.js` bell | `/api/notifications`, `/read-all` (`wallet_routes.py:199,212`) | notifications | get_current_user | last 100 only | `test_governance_security` (notifications), many tests assert notifications are created | 2 | no per-item read, no paging (100 cap) · P3 |
| A26 | Notification preferences | — | — | — | — | — | — | 6 | not implemented · P3 |
| A27 | Customer support tickets / complaints | none (`Legal.js` support page is static text) | none (support tickets are vendor-only: `governance_routes.py:293-381`) | — | — | — | — | 6 | no way to raise or track a customer complaint in-app · P1 (see O18) |
| A28 | Profile, profile photo, password change | `Profile.js`, `AccountSettings.js` | PUT `/api/auth/profile`, `/profile/photo`, POST `/api/uploads/profile-photo`, PUT `/api/auth/change-password` | users, files | get_current_user | Emergent object storage (K5) | change-password: `test_governance_security`, `test_security_batch0`; **profile & photo: none** | 2 | profile update and photo upload untested · P3 |
| A29 | Self-service mobile number change | none | PUT `/api/auth/change-mobile/send|verify` (`auth_routes.py:772,793`) | users, otp_sessions | get_current_user | SMS | `test_otp_auth`, `test_security_batch0` | 5 | no screen · P3 |
| A30 | Confirm/reject admin-proposed contact change | `ContactChangeBanner.js` | `/api/auth/contact-change*` (`contact_change.py`) | contact_change_requests | get_current_user | OTP | `test_security_batch0` | 1 | — |
| A31 | Account deletion / data export by the customer | — (privacy text promises it "by contacting support") | admin deactivation only (`admin_routes.py:1237`) | users | — | — | — | 6 | see L12 · P2 |

## B. HomeGenie member ecosystem (role `distributor`)

| ID | Sub-capability | Frontend | Backend API · service | Collections | Permissions | States · jobs · external | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|---|---|---|
| B1 | Member registration with sponsor / reference code | `Register.js` | `/api/auth/register-request`; `/api/auth/reference-codes` unused | users, referral_codes, referral_relationships | public | no recruitment reward (owner rule) | `test_registration_referral`, live `test_production_hardening` | 1 | — |
| B2 | Activation RED → GREEN (admin approves a qualifying paid order) | `AdminActivations.js` | `/api/admin/activations*` (`activation_routes.py`), `activation_rules.py` | users, orders, activation_history | admin/super_admin | `red→green` | `test_activation`, `test_activation_rules`, `test_owner_decisions` | 1 | — |
| B3 | Share links & seller attribution (`?ref=`) | `lib/sellerRef.js`, `ProductDetail.js:36` | `seller_ref` on POST `/api/orders` (`shop_routes.py:213`) | orders (`seller_user_id`) | green distributor to share | — | `test_homegenie_batch5`, `test_homegenie_metrics_b13`, `test_role_eligibility_wallets` | 1 | — |
| B4 | Commission statement (basis, state, reasons) | `CommissionStatement.js` in `Wallet.js` | `/api/commissions/statement` (`wallet_routes.py:32`) | commissions, commission_plans | get_current_user | pending→available/held/reversed | `test_batch12_remediation`, `test_payout_eligibility` | 1 | — |
| B5 | Wallet & transactions | `Wallet.js` | `/api/wallet`, `/api/wallet/transactions` | wallets, wallet_transactions | get_current_user | — | `test_money_exact`, `test_role_eligibility_wallets`, `test_recovery_and_ledger` | 1 | — |
| B6 | KYC submission (PAN, Aadhaar, bank) | `Kyc.js` | GET/POST `/api/kyc` (`wallet_routes.py:95,113`) | kyc_records, users | get_current_user (**any role may submit**) | `submitted→verified/rejected`; second-person rule (S-8) | `test_homegenie_batch5`, `test_owner_decisions`, `test_security_batch0` | 1 | plaintext storage and role gap tracked in L9/L10 |
| B7 | Withdrawal requests | `Withdrawals.js` | GET/POST `/api/withdrawals` (`wallet_routes.py:152,157`) | withdrawal_requests, wallets, withdrawal_payout_refs | distributor + green inline | `requested→approved→paid / rejected` | `test_withdrawal_controls`, `test_money_exact`, `test_batch12_remediation` (C-13) | 1 | — |
| B8 | Dashboard metrics HG-03 (IST ranges, attributed orders masked) | `HomeGeniePerformance.js` | `/api/homegenie/metrics`, `/orders` | orders, commissions | distributor inline | — | `test_homegenie_metrics_b13` | 1 | — |
| B9 | Referral page | `Referral.js` | `/api/referral` (`wallet_routes.py:69`) | referral_relationships | get_current_user | — | live `test_health_dashboard` only | 2 | only a live-server suite touches it · P3 |
| B10 | Leaderboard / rewards journey | `Rewards.js`, `JourneyCard.js` | `/api/leaderboard` (`wallet_routes.py:233`), `/api/dashboard` | users, commissions | get_current_user | — | none for `/api/leaderboard` | 2 | untested · P3 |
| B11 | Monthly badge | none | `/api/badge` (`wallet_routes.py:219`), `badges.py` | orders | get_current_user | — | script `test_cod_and_badges` (no pytest functions), `test_admin_governance_batch2` mentions badge | 5 | endpoint unused by UI · P3 |
| B12 | HomeGenie performance reports | — | — | — | — | — | — | 6 | not started (earlier matrix agrees) · P3 |
| B13 | Depth-based / purchase-level team commission | — | retired (S-7); `test_production_hardening` retires its old tests | — | — | — | — | 9 | intentionally retired |

## C. Vendor ecosystem (owner `vendor`, staff `vendor_staff`)

| ID | Sub-capability | Frontend | Backend API · service | Collections | Permissions (staff) | States · jobs · external | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|---|---|---|
| C1 | Apply to sell (mobile OTP) | `VendorApply.js` | `/api/vendor-applications[/send-otp]` | vendor_applications, otp_sessions | public | `new→in_review→converting→converted/declined/duplicate` | `test_vendor_applications`, `test_batch12_remediation` (C-16) | 1 | — |
| C2 | Admin-run onboarding with checklist | `AdminVendorOnboarding.js`, `AdminVendorCreate.js` | `vendor_onboarding.py`, POST `/api/admin/vendors/create` | vendors, vendor_documents, users | super_admin/admin (view +support) | `onboarding→ready_for_review` | `test_vendor_onboarding`, `test_vendor_foundation`, `test_e2e_vendor_integration` | 1 | — |
| C3 | Final approval / rejection (super admin) | same | `/final-review` (`vendor_onboarding.py:654`), legacy `/decision` (`vendor_routes.py:1032`) | vendors, vendor_status_history | super_admin | `vendor_lifecycle.TRANSITIONS` | `test_vendor_authority`, `test_vendor_onboarding` | 1 | two approval routes (see C34) |
| C4 | Owner invitation & activation | `VendorOwnerInvite.js`; admin `owner-access` button | `/api/vendor/invitation/owner*`, `/owner-access`; parallel `/owner-invitation*` | account_invitations, users | token / super_admin | link valid 72 h (`vendor_invitations.py:20`) | `test_owner_invitation`, `test_e2e_vendor_integration` | 1 | owner invitation e-mail via Emergent (K4) |
| C5 | Vendor sign-in | `VendorAuth.js VendorLogin` | `/api/auth/login` | users | — | onboarding accounts refused | `test_vendor_onboarding` | 1 | — |
| C6 | Business profile edit + per-status profile overview (VEN-05) | `VendorProfile.js` | PUT `/api/vendor/me`, GET `/api/vendor/me/profile-overview` (`vendor_routes.py:166,201`) | vendors, vendor_documents, vendor_change_requests | owner only | `CONTACT_ONLY` statuses | PUT `/vendor/me`: `test_vendor_foundation`, `test_governance_security`, `test_vendor_applications`; **profile-overview: no test** (grep) | 2 | Batch 14 overview & contact validation untested · P2 |
| C7 | Compliance documents (vendor upload, admin review) | `Governance.js`, `AdminVendorOnboarding.js` | `/api/vendor/documents*`, `/api/admin/vendor-documents/{id}/review` | vendor_documents | owner; reviewer super_admin/admin/support | `pending→approved/rejected` | `test_governance_security`, `test_vendor_onboarding` | 1 | — |
| C8 | Bank-detail change requests | `Governance.js`, `AdminOperations.js` | `/api/vendor/me/bank-change`, `/api/admin/vendor-change-requests*` | vendor_change_requests | owner; decision super_admin/accounts_admin | `pending→approved/rejected` | `test_governance_security`, `test_vendor_authority` | 1 | — |
| C9 | Verification, requirements, status history | `Governance.js` | `/api/vendor/me/verification|requirements|history` | vendors, vendor_status_history | owner | — | `test_governance_security` | 1 | — |
| C10 | Product studio: drafts, template fields, variants, versioned autosave, submit | `VendorProductStudio.js` → `ProductStudio.js` | `/api/vendor/pim/*`, `/api/pim/template` (`pim.py`) | product_drafts, products | products.create / products.edit / products.submit | draft `open→submitted`; one open draft per product (index) | `test_pim_batch12`, `test_staff_permissions_batch12` | 1 | "discard draft" (DELETE) has no button · P3 |
| C11 | Product list, pause/resume, archive | `VendorProducts.js` | `/api/vendor/products`, `/listing`, `/archive` | products | products.read / products.archive | — | `test_catalogue_batch3`, `test_vendor_core`, `test_catalogue_dashboard` | 1 | — |
| C12 | Product CSV export | `VendorProducts.js` | `/api/vendor/products/export.csv` | products | products.read | — | `test_catalogue_dashboard` | 1 | — |
| C13 | Product CSV import onto the PIM fields (VEN-04) | `ImportDialog.js` | POST `/api/vendor/products/import` (`vendor_routes.py:588`); columns `catalogue.CSV_COLUMNS` (`catalogue.py:164`) | products, stock_movements | products.submit | all-or-nothing validate/commit | `test_catalogue_dashboard` (legacy columns) | 3 | Columns lack `hsn_code`, `highlights`, `model_number`, `image_alt`, template attributes, variants; an update **does not check `pending_revision`** (PUT does, `:511`) and hides a live approved product (`:677-681`) · P1 |
| C14 | Legacy direct create/update of products | none (`ProductForm` not rendered) | POST/PUT `/api/vendor/products` (`vendor_routes.py:442,509`) | products | products.submit | material change → pending + hidden | `test_vendor_operations`, `test_vendor_core` | 9 | superseded by C10 but still callable · P2 (retire or align with PIM) |
| C15 | Inventory: adjustments with reasons, history, stock CSV import | `VendorInventory.js` | `/stock`, `/stock-history`, import mode `stock` | products, stock_movements | inventory.adjust / inventory.read / **products.submit for stock import** | — | `test_catalogue_dashboard`, `test_vendor_operations`, `test_staff_permissions_batch12` | 1 | stock import needs `products.submit` instead of `inventory.adjust` (inventory-manager preset cannot import) · P3 |
| C16 | Orders list & detail | `VendorOrders.js`, `components/vendor/OrderDetail.js` | `/api/vendor/orders[/{id}]` | orders | orders.read | `VENDOR_VISIBLE_PAYMENT` | `test_vendor_core`, `test_operations` | 1 | — |
| C17 | Fulfilment steps (accept, reject, pack, dispatch with carrier/tracking, delivered, delivery failed, RTO) | `OrderDetail.js`, `VendorDispatch.js` | POST `/api/vendor/orders/{id}/fulfilment` (`vendor_routes.py:872`) | orders (fulfilments), stock_txns | per step `FULFILMENT_PERMISSION` | `vendor_routes.FLOW` (`:35`) | `test_vendor_operations`, `test_staff_permissions_batch12`, `test_platform_batch9_10`, `test_finance_ledger` | 1 | — |
| C18 | Delivery proof (VEN-06) | — | delivered = vendor note only (`admin_order_ops.py:169`) | — | — | — | — | 7 | D-04 · P1 |
| C19 | Dispatch deadline alerts | `VendorNotifications.js` | `vendor_routes.sweep_dispatch_deadlines` via J2 | notifications | — | J2 daily | `test_operations` | 1 | daily cadence only |
| C20 | Return-to-origin receipt & inspection | `OrderDetail.js:38` | POST `/api/vendor/orders/{id}/return-inspection` | orders, stock_movements | returns.inspect | restock only after inspection | `test_followup_a2`, `test_stock_recovery` | 1 | — |
| C21 | Customer returns: approve/contest, receive, inspect, replacement dispatch | `VendorReturns.js` | `/api/vendor/returns*` (`returns_routes.py:599-677`) | return_cases, refund_cases | returns.read / respond / inspect | `requested→approved→in_transit→received→inspected→refund_pending/replacement_due→closed` | `test_returns_refunds`, `test_vendor_operations`, `test_refund_return_controls` | 1 | — |
| C22 | Earnings: summary, ledger, settlements, statement CSV | `VendorFinance.js` / `VendorEarnings.js` | `/api/vendor/finance/*` (`finance_routes.py:54-95`) | vendor_ledger, settlements | finance.read / finance.export | — | `test_finance_ledger`, `test_staff_permissions_batch12` | 1 | — |
| C23 | COD view | `VendorCod.js` | `/api/vendor/finance/cod` | orders | finance.read | — | `test_finance_ledger`, `test_cod_safeguards` | 1 | — |
| C24 | Commercial terms acceptance | `VendorTerms.js` | `/api/vendor/finance/terms[/{aid}/accept]` | vendor_agreements | finance.read / owner | versioned, effective dates | `test_commercial_terms` | 1 | — |
| C25 | Current report + CSV | `VendorReports.js` | `/api/vendor/reports/current[.csv]` | orders, vendor_ledger | reports.read / reports.export | — | `test_vendor_reports`, `test_reports_benefits` | 1 | — |
| C26 | Advancement & benefit eligibility | `VendorAdvancement.js` | `/api/vendor/reports/advancement`, `/api/vendor/advancement/eligibility` | benefit_programmes, benefit_grants | reports.read / owner (inconsistent) | — | `test_vendor_reports`, `test_reports_benefits` | 1 | staff access inconsistency · P3 |
| C27 | Dashboard / analytics | `VendorDashboard.js`, `VendorAnalytics.js` | `/api/vendor/dashboard` (`vendor_dashboard.py:78`) | orders, products | reports.read | — | `test_catalogue_dashboard`, `test_vendor_reports` | 2 | earlier docs: figure review "NOT STARTED"; two screens on one endpoint · P3 |
| C28 | Notifications inbox | `VendorNotifications.js` | `/api/vendor/notifications`, `/api/notifications/*read*` | notifications | any member | — | `test_governance_security`, `test_operations` | 1 | — |
| C29 | Support tickets to HOME GENIES | `VendorSupport.js` | `/api/vendor/support/tickets*` | support_tickets | owner only | `open→answered→…` | `test_governance_security`, screen-contract `test_admin_operations_batch7` | 1 | — |
| C30 | Staff: invite, roles (12 presets + custom), suspend, reactivate, revoke, accept | `VendorStaff.js`, `VendorStaffInvite.js` | `vendor_staff_routes.py`, `vendor_staff.py` | vendor_members, users | owner only | invitation 72 h (`INVITE_HOURS`) | `test_vendor_staff`, `test_staff_permissions_batch12` | 1 | — |
| C31 | Button-level hiding for staff | menu only (`VendorLayout.js NAV_PERMISSION`) | server refuses anyway | — | — | — | — | 3 | not started per roadmap · P3 |
| C32 | Password / security | `VendorSecurity.js` | PUT `/api/auth/change-password` | users | any | — | `test_governance_security` | 1 | — |
| C33 | Suspended vendor keeps obligations only | `VendorGate obligations` | `require_vendor_obligations` | vendors | — | `suspended` | `test_platform_batch9_10` | 1 | — |
| C34 | Duplicate vendor routes/screens (`/vendor/finance`≡`/earnings`, `/dispatch`+`/returns`≡`/shipping`, owner-invitation vs owner-access, decision vs final-review) | see map §9 | — | — | — | — | — | 9 | consolidate · P3 |
| C35 | Image / document upload (Cloudinary signed) | `ImageInput.js` | POST `/api/vendor/uploads/sign` (`governance_routes.py:481`) | — | products.create/edit | Cloudinary (K6); 503 when unconfigured | `test_governance_security` (signature only) | 8 | depends on Cloudinary configuration · P2 |
| C36 | Vendor merchandising requests | — | — | — | — | — | — | 7 | D-19 · P3 |

## D. Platform admin ecosystem

| ID | Sub-capability | Frontend | Backend API · service | Collections | Permissions | States · jobs · external | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|---|---|---|
| D1 | Admin sign-in (separate URL) | `AdminSecureLogin.js` | `/api/auth/admin-login` | users, login_attempts | public | blocked admin = wrong password (L6) | `test_admin_governance_batch2`, `test_batch12_remediation`, live suites | 1 | — |
| D2 | Admin dashboard | `AdminDashboard.js` | `/api/admin/dashboard` (`admin_routes.py:80`) | users, orders, wallets | admin | — | live `test_health_dashboard`, `test_otp_auth`, `test_upi_adminlogin`, `test_cycle9_upi_ref` | 2 | in-process tests absent · P3 |
| D3 | Users: list, edit, block, deactivate | `AdminUsers.js` | `/api/admin/users*` | users | admin; vendor accounts super_admin/admin; admin targets super_admin | `account_status` | `test_admin_governance_batch2`, `test_security_batch0`, `test_batch12_remediation` | 1 | list unpaged and capped at 1000 (`admin_routes.py:122`); support_admin can deactivate customers/members · P2 |
| D4 | Credential reset & reset-request queue | `AdminUsers.js` | `/reset-password`, `/password-reset-requests*` | users, password_reset_requests | super_admin/admin | forced change + OTP when SMS | `test_otp_auth`, `test_recovery_and_ledger`, `test_security_batch0` | 1 | D-11 (no-SMS resets) open |
| D5 | Registration-request queue | `AdminUsers.js` tab | `/api/admin/registration-requests*` | registration_requests | admin | legacy — startup auto-activates (`server.py:_init_db`) | `test_registration_flow`, live `test_regrequest_flow` | 9 | legacy queue still shown · P3 |
| D6 | Referral codes | `AdminUsers.js` | `/api/admin/referral-codes*` | referral_codes | admin | — | none (grep) | 2 | untested · P3 |
| D7 | Contact-change requests | `AdminUsers.js` | `contact_change.py` admin routes | contact_change_requests | admin; recovery super_admin | — | `test_security_batch0` | 1 | — |
| D8 | Admin team (create admin, change role) | `AdminTeam.js` | `admin_team.py` | users | super_admin | — | `test_admin_governance_batch2` | 1 | — |
| D9 | Platform role expansion (Finance/Catalogue/Ops/Reports roles, custom) | — | 4 fixed roles (`core.py:44`) | — | — | — | — | 7 | D-16 · P2 |
| D10 | KYC review / edit (second-person) | `AdminKyc.js` | `/api/admin/kyc*` | kyc_records, users | review admin; edit finance | S-8 | `test_homegenie_batch5`, `test_owner_decisions`, `test_security_batch0` | 1 | D-06 open |
| D11 | Activations | `AdminActivations.js` | `activation_routes.py` | users, activation_history | admin/super_admin | — | `test_activation` | 1 | — |
| D12 | Withdrawals review & pay (KYC re-check, approver ≠ payer) | `AdminWithdrawals.js` | `/api/admin/withdrawals*` | withdrawal_requests, withdrawal_payout_refs | finance | — | `test_withdrawal_controls`, `test_batch12_remediation` | 1 | bank transfer itself is manual (K9) |
| D13 | Manual wallet credit (maker-checker) | `AdminUsers.js` + `AdminOperations.js` approvals | `/api/admin/wallet/credit`, `financial_approvals.py` | financial_approvals, wallets | finance; checker ≠ maker | `pending→approving→approved/rejected` | `test_manual_money_controls`, `test_batch12_remediation` (C-18) | 1 | — |
| D14 | Commission administration (list, manual release/hold) | none | `/api/admin/commissions`, `PUT /{id}/status` (`admin_routes.py:596,606`) | commissions | admin / finance | — | `test_manual_money_controls`, `test_payout_eligibility` | 5 | no screen · P2 |
| D15 | Order operations: paged list, detail, masked audited CSV | `AdminOrderOps.js` | `admin_order_ops.py` | orders | admin; export not support | — | `test_admin_order_ops_b13` | 1 | — |
| D16 | Admin order status change | `AdminOrderOps.js`, `AdminOrders.js` | PUT `/api/admin/orders/{id}/status` (`admin_routes.py:389`) | orders | **any admin incl. support_admin**; paid cancel super_admin/admin | free-form status list, no transition graph (`:388`); vendor goods "delivered" has no payout effect | `test_payout_eligibility`, `test_admin_order_ops_b13` | 1 | R-2 / D-04 · P2 |
| D17 | Payment exceptions: UPI confirm/reject, manual payment, COD collected, refund (maker), remove abandoned order | `AdminOrders.js` (`/admin/orders/exceptions`) | `shop_routes.py:874-986`, `admin_routes.py:460,548`, `shop_routes.py:293` | orders, payment_transactions, refund_cases | finance; COD admin/super_admin | — | `test_payment_integrity_batch1`, `test_owner_decisions`, `test_cod_safeguards`, `test_followup_a2` | 1 | — |
| D18 | Old unpaged admin order list (`GET /api/admin/orders`) + separate old page | `AdminOrders.js` | `admin_routes.py:361` (cap 1000) | orders | admin | — | `test_followup_a2` | 9 | merge into order ops · P3 |
| D19 | Payment event inbox & retry | `AdminPaymentEvents` | `payment_events.py:190,207` | webhook_events | finance | processed/ignored/unmatched/rejected/failed | `test_payment_events_b14` | 1 | — |
| D20 | Financial approvals queue | `AdminOperations.js` | `financial_approvals.py` | financial_approvals | finance, maker ≠ checker, stale takeover 5 min | — | `test_manual_money_controls`, `test_admin_operations_batch7` | 1 | — |
| D21 | Refund cases (initiate, confirm by second finance admin, fail/retry, resolve) | `AdminOperations.js` | `/api/admin/refund-cases*` (`returns_routes.py:240,273`) | refund_cases, order_refunds | admin initiates; finance confirms/resolves | `REFUND_FLOW` (`:262`) | `test_returns_refunds`, `test_refund_return_controls`, `test_batch12_remediation` | 1 | — |
| D22 | Return decisions (approve/reject contested) | `AdminOperations.js` | `/api/admin/returns*` | return_cases | admin | — | `test_returns_refunds`, `test_refund_return_controls` | 1 | — |
| D23 | Vendor settlements (create, approve, pay, fail) | `AdminOperations.js` | `/api/admin/finance/settlements*` | settlements, vendor_ledger | finance; creator ≠ approver ≠ payer except creator=payer | `SETTLE_FLOW` (`finance_routes.py:277`) | `test_finance_ledger`, `test_commercial_terms`, `test_payout_eligibility` | 1 | D-02 · see O3 |
| D24 | COD discrepancies | `AdminOperations.js` | `/api/admin/finance/cod-discrepancies*` | orders | list admin; resolve finance | — | `test_cod_safeguards`, `test_finance_ledger` | 1 | — |
| D25 | Duplicate payments | `AdminOperations.js` | `/api/admin/payments/duplicates*` | orders | finance | `refund_due→refunded` | screen-contract `test_admin_operations_batch7` | 2 | only a screen-contract test · P2 |
| D26 | Vendor support inbox | `AdminOperations.js` | `/api/admin/support/tickets` + `/reply`; detail GET unused | support_tickets | admin | — | `test_governance_security`, `test_admin_operations_batch7` | 2 | no thread view; no assignment/SLA · P3 |
| D27 | Vendor ledger view & adjustments | none | `/api/admin/finance/vendors/{id}/ledger`, `/adjustments` (`finance_routes.py:228,244`) | vendor_ledger, financial_approvals | admin / finance | maker-checker | `test_finance_ledger` | 5 | no screen to raise an adjustment although approvals are on screen · P2 |
| D28 | Settlement finance policy (dual approval, minimum) | none | `/api/admin/finance/policy` | finance_policy | finance | — | `test_finance_ledger`, `test_admin_governance_batch2` | 5 | no screen · P3 |
| D29 | Catalogue moderation: revisions with diff, new products, admin drafts for a vendor | `AdminCatalogue.js` | `pim.py:350-424`, `vendor_routes.py:1060,1073` | product_drafts, products | review vendor_admin; preparer ≠ approver | — | `test_pim_batch12`, `test_vendor_operations` | 1 | price history not shown (`pim.py:466` unused) · P3 |
| D30 | Admin image/document upload in studio & merchandising | `ImageInput.js` | POST `/api/vendor/uploads/sign` → 403 for admins | — | — | — | — | 4 | admins can only paste https links · P2 |
| D31 | Platform-own products (direct CRUD, stock, takedown, permanent delete) | `AdminProducts.js` | `admin_routes.py:220-347`, `storage.py:113` | products, stock_movements, files | admin; vendor products super_admin/admin | takedown | `test_catalogue_batch3`, `test_vendor_authority`, live `test_regrequest_flow`; image upload untested | 2 | separate write model from PIM (map §9) · P3 |
| D32 | Merchandising (sections, schedule, order, preview) | `AdminMerchandising.js` | `merchandising.py` | merch_sections | list admin; write vendor_admin | draft/published/unpublished | `test_discovery_merch_b13` | 1 | — |
| D33 | Vendors list & lifecycle decisions; vendor product decisions | `AdminVendors.js` | `vendor_routes.py:1012-1073` | vendors, products | vendor_admin; super_admin actions | `TRANSITIONS` | `test_vendor_authority`, `test_vendor_foundation` | 1 | — |
| D34 | Vendor applications inbox | `AdminVendorApplications.js` | `vendor_applications.py` | vendor_applications | view +support; act vendor_admin | — | `test_vendor_applications` | 1 | — |
| D35 | Commercial agreements | `AdminAgreements.js` | `commercial_routes.py` | vendor_agreements | create/approve finance | versioned | `test_commercial_terms`, `test_admin_screens_backend` | 1 | — |
| D36 | Benefit programmes & proposals | `AdminBenefits.js` | `vendor_benefits.py` | benefit_programmes, benefit_grants | finance | proposal→approved/rejected, expiry | `test_reports_benefits`, `test_admin_screens_backend` | 1 | — |
| D37 | Reports & exports (8 legacy reports) | `AdminReports.js` | `/api/admin/reports/{r}[/export]` (`admin_routes.py:1464-1507`) | users, orders, payment_transactions, referral_relationships, commissions, wallet_transactions, withdrawal_requests | **any admin incl. support_admin** | — | `test_security_batch0` (no sensitive fields), live `test_production_hardening` | 3 | float (non-paise) money columns, no date range, 2000/5000 row caps, export not audited, e-mail+mobile exported to support role · P1 |
| D38 | Settings (money settings finance-only) | `AdminSettings.js` | `/api/admin/settings` | business_settings | admin; money fields finance | audited | `test_admin_governance_batch2`, `test_commission_model` | 1 | — |
| D39 | Returns-policy administration | none | PUT `/api/admin/returns/policy` | returns_policy | super_admin/admin | audited, versioned | `test_returns_refunds` | 5 | no screen; D-05 governs authority · P2 |
| D40 | Vendor policy | none | PUT `/api/admin/vendor-policy` | vendor_policy | vendor_admin | — | `test_governance_security`, `test_vendor_authority` | 5 | no screen · P3 |
| D41 | Audit log viewer | `AdminAuditLogs.js` | GET `/api/admin/audit-logs` (last 500) | audit_logs | admin | append-only (DELETE → 405) | `test_admin_governance_batch2` | 3 | no filter/paging: older records unreachable from UI · P2 |
| D42 | Category / attribute template management | — (templates in `catalogue_templates.py`) | — | — | — | — | — | 6 | code change needed per template (R-13) · P3 |
| D43 | User detail screen | none | GET `/api/admin/users/{id}` | users | admin | — | none | 5 | · P3 |
| D44 | Role-aware admin UI (hide actions a role cannot perform) | nav-level only (`AdminLayout.js:15-32`) | server refuses | — | — | — | — | 3 | · P3 |

## E. Shared backend services

| ID | Sub-capability | Where | Collections | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|
| E1 | JWT sessions (`type: access`, exp/sub), logout revocation via `jti`, password-change invalidation | `core.py:77-165`, `auth_routes.py:819` | revoked_tokens, users | `test_identity_batch4`, `test_batch12_remediation` (L9), `test_security_batch0` | 1 | tokens issued before `jti` not revocable (R-6, time-bounded) |
| E2 | OTP service (hashed, attempts reserved atomically, daily budget) | `providers.py:131-197` | otp_sessions, test_sms_outbox | `test_batch12_remediation` (C-1), `test_otp_auth` (live) | 1 | delivery needs Twilio (K3) |
| E3 | Rate limiting + client IP | `core.py:445-500` | rate_limits | `test_governance_security`, `test_recovery_and_ledger`, `test_batch12_remediation` (C-2) | 1 | trust depends on D-10 |
| E4 | Audit log (append-only, hardened IP) | `core.py:378`, `admin_routes.py:1456` | audit_logs | `test_admin_governance_batch2` | 1 | — |
| E5 | Notification writer | `core.create_notification` (`core.py:359`), `notify_order_vendors` | notifications | asserted in many suites (`test_operations`, `test_returns_refunds`) | 2 | in-app only (J3) |
| E6 | E-mail sender | `core.send_email` (`core.py:402`) → Emergent | — | `test_owner_invitation` (delivery mocked/absent) | 8 | only used for vendor owner invitations (`vendor_invitations.py:50`) · P2 |
| E7 | File storage + `/api/files` | `storage.py` → Emergent object storage (`EMERGENT_LLM_KEY`) | files | `test_governance_security`, `test_returns_refunds`, `test_vendor_core` (files path) | 8 | external dependency (K5) · P2 |
| E8 | Pagination helper | `pagination.py` | — | `test_followup_a2` | 1 | — |
| E9 | Exact money (paise) + migration | `money.py`, `money_migration.py`, `scripts/migrate_money_paise.py` | money_migrations | `test_money_exact` | 1 | legacy float fields still read by reports (D37) |
| E10 | Settings | `core.get_settings` | business_settings | `test_admin_governance_batch2` | 1 | — |
| E11 | Sequences (order, invoice, vendor code) | `core.next_sequence`, `vendor_lifecycle.VENDOR_CODE` | counters | `test_vendor_foundation` (vendor codes) | 1 | — |
| E12 | Index management (read-only check at startup; explicit apply) | `db_indexes.py` | all | `test_db_indexes` | 1 | — |
| E13 | Config guard (503 on missing env), CORS, Vercel lazy init / DB-down 503 | `server.py:121-170` | — | `test_vercel_cors_dbdown` | 1 | — |
| E14 | Crash-safe intents (stock, commission, approvals takeover) | `stock.py`, `commission.py`, `financial_approvals.py` | stock_txns, commission_plans | `test_stock_recovery`, `test_crash_safe_distribution`, `test_crash_safe_finance` | 1 | — |

## F. Commerce & order engine

| ID | Sub-capability | Backend · service | States | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|
| F1 | Order pricing (GST-inclusive, per-line GST/HSN snapshot, COD fee) | `shop_routes.create_order` (`:146`), `money.py` | — | `test_catalogue_batch3` (CAT-02), `test_money_exact` | 1 | — |
| F2 | Stock reservation / release / expiry (15 min) / crash recovery | `stock.py` | `PRE_DISPATCH`, restock intents | `test_stock_reservation`, `test_stock_expiry_race`, `test_stock_recovery` | 1 | Vercel cron is daily; expiry otherwise runs lazily on checkout/order views (`cron_routes.py:74-75`) |
| F3 | Paid-order state machine (`_process_paid_order`, idempotent, late payment → needs_refund) | `shop_routes.py:666-760` | payment `pending/claimed/paid/cod_pending/cod_discrepancy/partially_refunded/refunded` | `test_order_lifecycle_races`, `test_payment_integrity_batch1`, 19 suites reference it | 1 | — |
| F4 | Razorpay webhook reconciliation (HMAC, normalise, match, validate, apply once, retry) | `payment_events.py` | webhook_events outcomes | `test_payment_events_b14`, `test_payment_integrity_batch1` | 1 | live gateway untested (R-15) |
| F5 | Stripe path | `shop_routes.py:410-456,769-800`, `stripe_checkout.py` | — | none for the webhook | 8 | see A15 · P1 |
| F6 | Order-level status vs vendor fulfilments (roll-up to delivered when every group finished) | `vendor_routes.vendor_update_fulfilment`, `eligibility.py` | `FLOW` (`vendor_routes.py:35`) | `test_batch12_remediation` (C-5, C-7), `test_payout_eligibility` | 1 | — |
| F7 | Cancellation (customer, vendor reject, admin cancel paid) | `returns_routes.py:372`, `admin_routes.py:389-460` | → refund case | `test_returns_refunds`, `test_refund_return_controls`, `test_order_lifecycle_races` | 1 | — |
| F8 | Returns & replacements engine | `returns_routes.py` | `ACTIVE_RETURN_STATES` (`:37`) | `test_returns_refunds`, `test_refund_return_controls`, `test_followup_a2` | 1 | customer-side steps missing (A21) |
| F9 | Abandoned order removal (archive, never erase) | `admin_routes.py:548` | archived | `test_payment_integrity_batch1` (FIN-07) | 1 | — |
| F10 | Promotions, coupons, discounts | — | — | — | 6 | KNOWN_GAPS "promotional pricing" · P3 |
| F11 | Shipping charges / PIN serviceability | — (no `shipping_fee`/serviceability code, grep) | — | — | 6 | · P2 |

## G. Financial & commission engine

| ID | Sub-capability | Backend · service | Collections | Permissions | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|---|
| G1 | Commission plan freeze & distribution (30/10/5 on taxable base, eligibility rule `distributor_green_v1`) | `commission.py` | commission_plans, commissions, wallets | system | `test_commission_model`, `test_crash_safe_distribution`, `test_role_eligibility_wallets`, script `test_commission_engine` | 1 | — |
| G2 | Commission release after delivery + return window (J1) | `commission.release_due_points`, `cron_routes.py:39-69` | cron_runs | cron secret | function: `test_crash_safe_finance`, `test_payout_eligibility`, `test_refunds_and_retention` (+8 more); **HTTP cron route: none** | 1 | add an endpoint test for the cron auth · P3 |
| G3 | Commission clawback on refund / return; sale reversal nets refunds | `commission.py`, `ledger.post_sale_reversal` | commissions, wallets, vendor_ledger | system | `test_crash_safe_finance`, `test_refunds_and_retention`, `test_batch12_remediation` (C-6) | 1 | — |
| G4 | Clawback on per-line taxable value for mixed-GST orders | — (proportional to gross, R-8/L5) | — | — | — | 3 | money accuracy on mixed-GST refunds · P0 (low magnitude) |
| G5 | Vendor ledger postings (sale, refund shares, commission, adjustments) | `ledger.py` | vendor_ledger | system/finance | `test_finance_ledger`, `test_recovery_and_ledger`, `test_e2e_vendor_integration` | 1 | — |
| G6 | Payout eligibility (delivery per vendor + window; holds) | `eligibility.py` | — | — | `test_payout_eligibility`, `test_batch12_remediation` | 1 | — |
| G7 | Settlement workflow | `finance_routes.py:277-387` | settlements | finance | `test_finance_ledger`, `test_commercial_terms`, `test_owner_decisions` | 1 | — |
| G8 | Refund execution through the payment provider | `returns_routes.verify_provider_refund` returns False (`:266`) | refund_cases | finance | — | 8 | money is returned outside the system; only a reference is recorded · P1 |
| G9 | Payout execution (vendor settlements, member withdrawals) to bank | manual reference only | withdrawal_payout_refs, settlements | finance | `test_withdrawal_controls` (references) | 8 | no payout API · P2 |
| G10 | Maker-checker approvals (wallet credit, vendor adjustment) | `financial_approvals.py` | financial_approvals | finance | `test_manual_money_controls` | 1 | — |
| G11 | COD collection evidence, short-collection review | `cod_rules.py`, `shop_routes.py:293`, `finance_routes.py:405` | orders | COD admin/super_admin; review finance | `test_cod_safeguards`, `test_cod_rules`, `test_cod_route_logic` | 1 | authority D-03 (O4) |
| G12 | Reconciliation (ledger, settlements, returns, refund cases) | `ledger.reconcile_ledger`, `finance_routes.reconcile_settlements`, `returns_routes.reconcile_returns` via J2 / `POST /api/admin/finance/reconcile` | — | finance | `test_finance_ledger`, `test_recovery_and_ledger`, `test_followup_a2` | 1 | — |
| G13 | UPI confirm vs expiry race leftovers (L2), concurrent confirms with different UTRs both 200 (L3) | `shop_routes.py:919` | payment_references | finance | not covered (KNOWN_GAPS R-7) | 3 | · P0 (low magnitude) |
| G14 | Finance reports (commission funding, non-distributor commissions, negative wallets) | `finance_routes.py:460-523` | commissions, wallets | finance | `test_commission_model`, `test_role_eligibility_wallets` | 5 | no screen · P2 |
| G15 | Historical wallet / commission audit (read-only) | `historical_audit.py`, `scripts/historical_audit.py` | — | operator | `test_historical_audit` | 1 | — |
| G16 | Tax classification authority (HSN/GST) | warning only in studio | — | — | — | 7 | D-15 · P1 |

## H. Product & catalogue engine

| ID | Sub-capability | Where | Collections | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|
| H1 | Category templates (4 pillars, sub-categories, attribute groups, conditional required, review flags) | `catalogue_templates.py`, `catalogue.py` | — | `test_pim_batch12` | 1 | admin management UI absent (D42) |
| H2 | Drafts, completeness, submit, revisions (live version kept on sale) | `pim.py`, `vendor_routes.apply_product_update(review=False)` | product_drafts, products | `test_pim_batch12` | 1 | — |
| H3 | Price history | `pim.py:466` | products.price_history | none for the endpoint | 5 | not shown in UI · P3 |
| H4 | New-product moderation & takedown/lift | `vendor_routes.py:1073`, `admin_routes.py:317-347` | products | `test_vendor_operations`, `test_catalogue_batch3` | 1 | — |
| H5 | Variants with per-variant stock, guarded writes (CAT-03) | `vendor_routes.apply_product_update` | products | `test_catalogue_batch3` | 1 | — |
| H6 | Bulk CSV import/export | see C12/C13 | — | `test_catalogue_dashboard` | 3 | VEN-04 · P1 |
| H7 | Legacy product form & direct write routes | `ProductForm.js`, `/api/vendor/products` POST/PUT | — | `test_vendor_operations` | 9 | · P2 |
| H8 | Search index & discovery | `discovery.py`, `db_indexes.py` | products | `test_discovery_merch_b13` | 1 | — |
| H9 | Scheduled publishing of products | — | — | — | 6 | roadmap "NOT STARTED" · P3 |
| H10 | Product ratings & reviews | — (no rating/review code beyond merchandising/vendor report fields) | — | — | 6 | · P3 |
| H11 | Product images & documents hosting | Cloudinary (vendor), Emergent storage (admin, `storage.py:113`) | files | `test_governance_security` | 8 | two storage back-ends; admin studio cannot use either for upload (D30) · P2 |

## I. Delivery & logistics

| ID | Sub-capability | Where | Tests | Status | Gap · priority |
|---|---|---|---|---|---|
| I1 | Vendor fulfilment state machine with carrier + tracking number | `vendor_routes.py:35,872` | `test_vendor_operations`, `test_staff_permissions_batch12` | 1 | — |
| I2 | Courier integration (labels, pickup, live tracking, COD remittance) | none (`cod_rules.py:11` "no courier or provider integration exists") | — | 6 | · P2 |
| I3 | Proof of delivery (VEN-06) | — | — | 7 | D-04 · P1 |
| I4 | Dispatch deadline alerts | J2 `sweep_dispatch_deadlines` | `test_operations` | 1 | daily cadence |
| I5 | Return-to-origin handling & inspection | `vendor_routes.py:952` | `test_followup_a2`, `test_stock_recovery` | 1 | — |
| I6 | Customer return shipment | `returns_routes.py:581` (no UI) | `test_returns_refunds` | 5 | A21 · P2 |
| I7 | Replacement dispatch | `returns_routes.py vendor_return_action replacement_dispatched` | `test_returns_refunds` | 1 | — |
| I8 | Admin-recorded delivery (no payout effect) | `admin_routes.py:389` (`status_set_by_admin`) | `test_payout_eligibility` | 7 | D-04 / R-2 · P2 |
| I9 | Shipping charges / serviceability | — | — | 6 | F11 · P2 |

## J. Notifications & communication

| ID | Sub-capability | Where | Tests | Status | Gap · priority |
|---|---|---|---|---|---|
| J1 | In-app notifications (customers/members) | `wallet_routes.py:199-215`, `Notifications.js` | `test_governance_security` | 2 | A25 · P3 |
| J2 | Vendor notification inbox (paged, filters) | `governance_routes.py:405` | `test_governance_security` | 1 | — |
| J3 | Transactional e-mail / SMS for orders, payments, shipping, refunds | none (`send_email` used once; SMS only OTP / account id / security notice, `providers.py:85,108`) | — | 6 | customers get no off-app confirmation · P2 |
| J4 | OTP SMS | `providers.py` (Twilio) | `test_otp_auth`, test adapter `SMS_TEST_ADAPTER` | 8 | K3 |
| J5 | Notification preferences / opt-outs | — | — | 6 | · P3 |
| J6 | Customer support tickets | — | — | 6 | A27 · P1 |
| J7 | Vendor support tickets | `governance_routes.py:293-381` | `test_governance_security` | 1 | — |
| J8 | Push / WhatsApp | — | — | 6 | · P3 |

## K. External integrations

| ID | Integration | Code | Config | Tests | Status | Gap · priority |
|---|---|---|---|---|---|---|
| K1 | Razorpay (checkout, verify, webhook) | `shop_routes.py:459-520`, `payment_events.py` | `RAZORPAY_KEY_ID/SECRET`, `RAZORPAY_WEBHOOK_SECRET` | webhook logic `test_payment_events_b14`; gateway calls none | 8 | needs staging run with test keys (R-15) · P1 |
| K2 | Stripe (via Emergent `emergentintegrations==0.2.0` in `requirements.txt:23`, else `stripe==14.4.1` SDK in `pyproject.toml`) | `shop_routes.py:11-16`, `stripe_checkout.py` | `STRIPE_API_KEY` (default placeholder), `STRIPE_WEBHOOK_SECRET` | card test skipped in live `test_upi_adminlogin` | 8 | decide one card gateway; Stripe unreconciled · P1 |
| K3 | Twilio SMS | `providers.py` | `TWILIO_*` | test adapter only | 8 | · P1 (OTP-dependent flows degrade without it) |
| K4 | E-mail (Emergent integrations API) | `core.py:397-417` | `EMERGENT_EMAIL_KEY` | — | 8 | · P2 |
| K5 | Object storage (Emergent) | `storage.py:14-16` | `EMERGENT_LLM_KEY`, `INTEGRATION_PROXY_URL` | indirect | 8 | profile photos / admin product images depend on it · P2 |
| K6 | Cloudinary signed uploads | `governance_routes.py:470-500` | cloud name / key / secret | `test_governance_security` (signature) | 8 | · P2 |
| K7 | Google OAuth through Emergent session broker | `auth_routes.py:390,413` | — | mocked in tests | 8 | · P2 |
| K8 | Provider refunds | stub `returns_routes.py:266` | — | — | 8 | G8 · P1 |
| K9 | Bank payouts | none | — | — | 6 | G9 · P2 |
| K10 | Courier | none | — | — | 6 | I2 · P2 |
| K11 | Error monitoring / alerting (e.g. Sentry) | none (R-10) | — | — | 6 | · P2 |
| K12 | GST e-invoicing / TCS reporting | none | — | — | 6 | O19 · P1 |

## L. Security & privacy

| ID | Sub-capability | Where | Tests | Status | Gap · priority |
|---|---|---|---|---|---|
| L1 | Platform RBAC (4 admin roles, finance sub-guards) | `core.py:44-200`, guard table in map §1 | `test_security_batch0`, `test_owner_decisions`, `test_vendor_authority` | 1 | — |
| L2 | Vendor tenant isolation + staff permission engine | `vendor_routes.require_vendor_user`, `vendor_staff.authorize_staff` | `test_vendor_core`, `test_staff_permissions_batch12`, `test_vendor_staff` | 1 | — |
| L3 | Session hardening (E1), OTP brute force (E2), lockout | see E | see E | 1 | — |
| L4 | Security headers, JSON 500 with error id | `server.py:167-216` | `test_platform_batch9_10` | 1 | — |
| L5 | Frontend Content-Security-Policy | none (`frontend/vercel.json` has only rewrites) | — | 6 | R-10 · P2 |
| L6 | Trusted proxy for client IP | `core.client_ip` | `test_batch12_remediation` (C-2) | 7 | D-10 hosting confirmation · P2 |
| L7 | Encryption at rest of PAN / Aadhaar / bank details | none (R-9) | — | 6 | · P0 |
| L8 | KYC submission limited to members | `wallet_routes.py:113` has no role check (L10) | — | 3 | · P2 |
| L9 | PII exposure to support role (legacy reports export e-mail/mobile; users list returns full user documents minus hash) | `admin_routes.py:118-128,1464-1507` | `test_security_batch0` checks hashes/Aadhaar/PAN absent | 3 | masking + export audit missing · P1 |
| L10 | Support-role write powers (order status, customer deactivation, settings non-money fields, referral codes) | `require_admin` on those routes | — | 7 | D-16 / D-04 · P2 |
| L11 | Upload safety (type sniffing, server-fixed folders, authenticated documents) | `storage.py:62`, `governance_routes.py:481` | `test_governance_security` | 1 | — |
| L12 | Data-subject rights (export, deletion, anonymisation) and retention policy | none; deactivation keeps all personal data (`admin_routes.py:1237` docstring) | — | 6 | · P2 (legal input needed) |
| L13 | Admin credential from environment, rotation, protected accounts | `server.py:_init_db`, `admin_team.py` | `test_admin_governance_batch2` (SEC-17) | 1 | — |
| L14 | Unauthenticated payment status lookup returns `order_id` by session id | `shop_routes.py:769` | — | 3 | · P3 |
| L15 | Legacy sign-up endpoint still public (`/api/auth/register`, stores `email_verified: False`) | `auth_routes.py:254` | `test_batch12_remediation` (C-3) | 9 | retire · P3 |
| L16 | Unverified legacy `email_verified: true` accounts (R-5) | data, not code | — | 7 | owner may run re-verification · P2 |

## M. Analytics & reporting

| ID | Sub-capability | Where | Tests | Status | Gap · priority |
|---|---|---|---|---|---|
| M1 | Admin dashboard KPIs | `admin_routes.py:80` | live suites only | 2 | · P3 |
| M2 | Admin legacy reports + CSV | `admin_routes.py:1464` | `test_security_batch0` | 3 | D37 · P1 |
| M3 | Admin order export (masked, audited, role-restricted) | `admin_order_ops.py:119` | `test_admin_order_ops_b13` | 1 | — |
| M4 | Vendor dashboard / analytics | `vendor_dashboard.py` | `test_catalogue_dashboard` | 2 | C27 |
| M5 | Vendor current report & CSV | `vendor_reports.py` | `test_vendor_reports` | 1 | — |
| M6 | Vendor advancement | `vendor_reports.py:226` | `test_vendor_reports`, `test_reports_benefits` | 1 | — |
| M7 | HomeGenie metrics | `homegenie_metrics.py` | `test_homegenie_metrics_b13` | 1 | — |
| M8 | Finance reports | `finance_routes.py:460-523` | `test_commission_model`, `test_role_eligibility_wallets` | 5 | G14 |
| M9 | HomeGenie performance reports | — | — | 6 | B12 · P3 |
| M10 | Product / funnel analytics (views, conversion) | — | — | 6 | · P3 |
| M11 | Audit trail reporting | `admin_routes.py:1451` | `test_admin_governance_batch2` | 3 | D41 · P2 |

## N. Infrastructure & reliability

| ID | Sub-capability | Where | Tests | Status | Gap · priority |
|---|---|---|---|---|---|
| N1 | Backend deployment (Vercel, root `backend`, 60 s limit) | `backend/vercel.json`, `pyproject.toml`, `deploy/ENVIRONMENT.md` | `test_vercel_cors_dbdown` | 2 | not production-verified (all docs agree) · P1 |
| N2 | Second deployment path `deploy/vercel-api` (copies backend; schedules only release-points) | `deploy/vercel-api/vercel.json`, `sync-backend.sh` | — | 9 | would skip J2 if used; untracked stale copy present locally · P2 |
| N3 | Scheduled jobs J1/J2 (daily; Vercel Hobby) | `cron_routes.py` | J2 path in 7 suites; J1 path none | 2 | daily cadence vs 15-min payment window; no job monitoring (cron_runs not surfaced) · P2 |
| N4 | Startup / lazy DB init, retry, 503 when DB down | `server.py:145-165,240-260` | `test_vercel_cors_dbdown` | 1 | — |
| N5 | Index migration tooling | `db_indexes.py` | `test_db_indexes` | 1 | — |
| N6 | Monitoring, alerting, log aggregation | none; payment paths use `print()` (`shop_routes.py:779,794`) | — | 6 | R-10 · P2 |
| N7 | Backups / disaster recovery | not in repository (ASSUMPTION: may exist at the MongoDB host) | — | 6 | evidence required · P1 |
| N8 | Staging environment & live HTTP suites | `scripts/seed_test_backend.py`, 7 live suites | run on a disposable server per engineering log (not re-run here) | 3 | R-11 staging run pending · P2 |
| N9 | Frontend automated tests | only `components/Pager.test.js` | — | 3 | no UI regression net · P2 |
| N10 | Frontend lint catches undefined identifiers | not enforced (R-14) | — | 3 | · P3 |
| N11 | Test-database guard (`*_test`, never production name) | `providers._test_sms_adapter`, test headers | all in-process suites | 1 | — |
| N12 | Script `customer_role_report.py` (D-12, read-only) | `backend/scripts/customer_role_report.py` (fields checked against `auth_routes.py:304`, `commission.py`, `shop_routes.py:239`) | none | 2 | untested; output prints masked mobiles · P3 |
| N13 | Script `demo_environment.py` (seed/cleanup demo data via real routes, local test DB only) | `backend/scripts/demo_environment.py` | none | 2 | every route it calls still exists (verified against the route table, incl. legacy POST `/api/vendor/products`); KNOWN_GAPS R-12 "old contracts" refers to payloads — not verifiable without running · P3 |
| N14 | Other scripts: `hash_admin_password.py` (none), `migrate_money_paise.py` (`test_money_exact`), `vendor_foundation_migrate.py` (`test_vendor_foundation`), `historical_audit.py` (`test_historical_audit`), `seed_test_backend.py` (none) | `backend/scripts/` | as listed | 2 | two scripts untested · P3 |

## O. Legal & business-policy dependencies

| ID | Item | Code today | Status | Priority |
|---|---|---|---|---|
| O1 | Legal pages (terms, privacy, returns, refunds, support) | static text `pages/Legal.js`; refunds text promises refunds "to the original payment method" which the system cannot execute (G8) | 3 | P1 (legal review + align text) |
| O2 | D-01 return window / commission hold (7 days) | `returns_policy.window_days`, `return_window_days` | 7 | P1 |
| O3 | D-02 settlement creator may also pay | `finance_routes.settlement_action` | 7 | P2 |
| O4 | D-03 COD cash confirmation authority | `cod_rules.CONFIRM_ROLES` = admin, super_admin | 7 | P1 |
| O5 | D-04 delivery confirmation and proof | vendor note only | 7 | P1 |
| O6 | D-05 who changes the return window | `returns_routes.POLICY_ROLES` | 7 | P2 |
| O7 | D-06 KYC verifier rules | last editor blocked only | 7 | P2 |
| O8 | D-09 COD fee on refunds; GST-inclusive vendor value (tax adviser) | finance chooses refund amount | 7 | P1 |
| O9 | D-10 hosting / trusted proxy | `core.client_ip` | 7 | P2 |
| O10 | D-11 admin reset without SMS | allowed | 7 | P2 |
| O11 | D-12 RED members → customers | report script only (N12) | 7 | P3 |
| O12 | D-14 launch-gap acceptance | — | 7 | P1 |
| O13 | D-15 HSN/GST authority | warning only | 7 | P1 |
| O14 | D-16 platform roles | 4 roles | 7 | P2 |
| O15 | D-17 staff money-adjacent access | `finance.read`/`finance.export` grantable to custom roles | 7 | P2 |
| O16 | D-18 billing address | single snapshot | 7 | P3 |
| O17 | D-19 vendor merchandising requests | admin-only | 7 | P3 |
| O18 | Consumer grievance mechanism for an e-commerce marketplace (ASSUMPTION: Indian Consumer Protection (E-Commerce) Rules 2020 require a grievance officer and complaint acknowledgement/tracking) | no complaint intake (A27) | 6 | P1 |
| O19 | GST-compliant tax invoices per seller, e-commerce operator TCS (ASSUMPTION: required under Indian GST for marketplace operators) | printable order page only (A24) | 6 | P1 |
| O20 | Direct-selling / multi-level commission compliance review of the HomeGenie model (ASSUMPTION: Consumer Protection (Direct Selling) Rules 2021 may apply to sponsor-based 30/10/5 commissions) | `commission.py` | 6 | P1 (not in the decision register) |

---

## 16. Status counts

Counted mechanically over every table row above (A–O, **266 sub-capabilities**; one status per row).

| Status | Total | A | B | C | D | E | F | G | H | I | J | K | L | M | N | O |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 Implemented and verified | 129 | 16 | 8 | 27 | 25 | 11 | 8 | 10 | 5 | 4 | 2 | 0 | 6 | 4 | 3 | 0 |
| 2 Implemented, insufficiently tested | 23 | 5 | 2 | 2 | 5 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 2 | 5 | 0 |
| 3 Partially implemented | 18 | 1 | 0 | 2 | 3 | 0 | 0 | 2 | 1 | 0 | 0 | 0 | 3 | 2 | 3 | 1 |
| 4 UI exists, backend incomplete | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 5 Backend exists, UI incomplete | 14 | 3 | 1 | 0 | 6 | 0 | 0 | 1 | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| 6 Not implemented | 29 | 3 | 1 | 0 | 1 | 0 | 2 | 0 | 2 | 2 | 4 | 4 | 3 | 2 | 2 | 3 |
| 7 Blocked by owner decision | 26 | 1 | 0 | 2 | 1 | 0 | 0 | 1 | 0 | 2 | 0 | 0 | 3 | 0 | 0 | 16 |
| 8 Blocked by external integration | 18 | 2 | 0 | 1 | 0 | 2 | 1 | 2 | 1 | 0 | 1 | 8 | 0 | 0 | 0 | 0 |
| 9 Deprecated or duplicated | 8 | 0 | 1 | 2 | 2 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 1 | 0 |

Some capabilities appear in two modules from different angles (e.g. A27 and J6 customer support; C13 and H6 CSV import; A15,
F5 and K2 Stripe); each row is counted once where it appears, so cross-cutting gaps are counted more than once.

## 17. Gap register — 25 most important gaps (ranked)

| Rank | Pri | Gap | Evidence |
|---|---|---|---|
| 1 | P0 | PAN / Aadhaar / bank details stored in plaintext | `wallet_routes.py:113` (`kyc_records`), KNOWN_GAPS R-9; L7 |
| 2 | P0 | Clawback on mixed-GST orders uses gross, not per-line taxable value | KNOWN_GAPS R-8; G4 |
| 3 | P0 | UPI confirm-vs-expiry leftovers and concurrent confirms with different UTRs both succeed | KNOWN_GAPS R-7; `shop_routes.py:919`; G13 |
| 4 | P1 | Vendor CSV import bypasses the PIM revision model: no `pending_revision` check, hides live approved products, lacks PIM fields (VEN-04) | `vendor_routes.py:588-690`, `:511` (PUT has the check), `catalogue.py:164`; C13 |
| 5 | P1 | Refunds and payouts are never executed through a provider; legal text promises refunds to the original payment method | `returns_routes.py:266`, `Legal.js` refunds; G8, G9, O1 |
| 6 | P1 | Default "Place order" uses Stripe, which is unconfigured by default, unreconciled (no `webhook_events`), and creates the order before failing | `Checkout.js:55-73`, `shop_routes.py:39,410-456,787`; A10, A15 |
| 7 | P1 | Customer complaint / support ticket channel missing | no customer route; vendor-only `governance_routes.py:293`; A27, O18 |
| 8 | P1 | Legacy admin reports: float money, no date range, row caps, unaudited export of e-mail/mobile to any admin incl. support | `admin_routes.py:1464-1507`; D37, L9 |
| 9 | P1 | Delivery proof / delivery authority undecided (VEN-06, D-04) | `admin_order_ops.py:169`; C18, O5 |
| 10 | P1 | Razorpay client verify path and live gateway never exercised by tests | no test references `/razorpay/order|verify`; R-15; A14, K1 |
| 11 | P1 | No GST tax invoice per seller / TCS; invoice is a browser print | `OrderDetail.js:47`; A24, O19 |
| 12 | P1 | Backups / DR not evidenced; production deployment unverified | N1, N7 |
| 13 | P1 | Owner decisions D-01, D-03, D-09, D-14, D-15 gate launch sign-off | `OWNER_DECISION_REGISTER.md`; O2-O13 |
| 14 | P1 | Direct-selling compliance of the sponsor commission model not reviewed | `commission.py`; O20 |
| 15 | P2 | Admins cannot upload images in the product studio or merchandising (403 on vendor signing route) | `ImageInput.js:52`, `governance_routes.py:481`; D30 |
| 16 | P2 | Admin vendor ledger view / adjustment creation has no screen (approvals queue exists) | `finance_routes.py:228,244`; D27 |
| 17 | P2 | Commission administration and finance reports have no screen | `admin_routes.py:596,606`, `finance_routes.py:460-523`; D14, G14 |
| 18 | P2 | Customer cannot submit return tracking, withdraw a return, or attach photos | `returns_routes.py:581,590`, `OrderSelfService.js` (`photos: []`); A21, A22 |
| 19 | P2 | No transactional e-mail/SMS for orders, payments, shipping, refunds | `core.send_email` used only in `vendor_invitations.py:50`; J3 |
| 20 | P2 | No monitoring/alerting; payment errors only printed | `shop_routes.py:779,794`; N6, K11 |
| 21 | P2 | Audit-log viewer limited to the last 500 rows, no filters | `admin_routes.py:1451`; D41 |
| 22 | P2 | Admin users list unpaged (1000 cap) and support role can deactivate customers / change order status | `admin_routes.py:118-128,389,1237`; D3, D16, L10 |
| 23 | P2 | No frontend CSP; no frontend automated tests beyond `Pager.test.js` | `frontend/vercel.json`; L5, N9 |
| 24 | P2 | VEN-05 profile overview has no dedicated test | `vendor_routes.py:166`; no test references `profile-overview`; C6 |
| 25 | P2 | Data-subject rights / retention policy absent (privacy page promises deletion on request) | `admin_routes.py:1237` docstring, `Legal.js` privacy; L12 |

Also tracked (P3, not ranked): notification preferences (A26/J5), self-service mobile change screen (A29), price-history UI (H3),
category template admin (D42), duplicates to retire (C14, C34, D18, N2), stock import permission (C15), cron endpoint test (G2).

## 18. Documentation vs code differences

| Document · claim | What the code at `d31cb74` shows |
|---|---|
| `MARKETPLACE_MODULE_COMPLETION_MATRIX.md` · VEN-05 "NOT STARTED" | implemented in Batch 14 (`vendor_routes.py:148-213`, `VendorProfile.js:38-40,183`), untested |
| same · "Customer support tickets — PARTIALLY IMPLEMENTED (legal/support page)" | nothing implemented for customers (status 6); the support page is static text |
| same · "Cart, checkout, payment (online / UPI / COD) — COMPLETE AND VERIFIED" | Stripe webhook and Razorpay client verify have no tests; Stripe is unconfigured by default; card test skipped (R-15) |
| same · "Orders … return / replacement … COMPLETE AND VERIFIED" (Batch 8 self-service) | return ship-back and withdrawal have no UI; photos never sent |
| same · "Invoice breakdown — COMPLETE AND VERIFIED" | browser-printed order card; no PDF / seller tax invoice |
| same · "Operations (…) COMPLETE AND VERIFIED" | vendor adjustments and vendor ledger have no screen; ticket detail unused |
| same · "Order lookup … old Orders page kept for payment-exception actions" | still true; Batch 14 turned it into a tab but the old unpaged `GET /api/admin/orders` remains |
| `HOME_GENIES_AUTONOMOUS_ROADMAP.md` · "All Batch 12 work is uncommitted" | committed in `d31cb74` ("Batches 12-14") |
| same · "Latest verification … 57 suites / 1,247 passed" | the tree now has 71 `test_*.py` files (964 test functions); no newer full-regression figure is recorded in any doc |
| same · "Next executable task: Phase 7" | Phase 7 delivered in Batch 13 (`customer_routes.py`) |
| same / log · Product studio staff rule "writes need `products.write`" (engineering log Phase 4) | rules use the fine permissions `products.create` / `products.edit` / `products.submit` (`vendor_staff.py RULES`); `products.write` survives only as a legacy alias |
| All docs | no document describes Batch 14 (payment webhook reconciliation, VEN-05, orders-area merge) |
| `payment_events.py:1` · "Spec: docs/PAYMENT_RECONCILIATION_SPEC.md" | that file does not exist |
| `KNOWN_GAPS_AND_RISKS.md` · functional gap "webhook events linked to orders" | done for Razorpay (Batch 14), not for Stripe |
| same · "safe by design: a change to an approved product never hides it" | only on the studio path; legacy PUT and CSV import hide the product (`vendor_routes.py:486-487, 677-681`) |
| same · R-12 "demo_environment uses old contracts" | every endpoint it calls still exists; payload compatibility unverifiable statically |
| `ROLE_PERMISSION_MATRIX.md` · advancement is owner-only | `/api/vendor/reports/advancement` is open to staff with `reports.read` |
| `ENGINEERING_LOG_BATCH12_ONWARD.md` Phase 10 · merchandising "storage images only" | any `https://` URL is accepted (`validators.safe_image_refs`) |
| `OWNER_DECISION_REGISTER.md` D-05 · admin and super_admin may change the window | matches `POLICY_ROLES`; the 403 message says "Only a super admin…" (`returns_routes.py:84`) |
| `Legal.js` refunds policy · refunds "to the original payment method" | no provider refund integration (`returns_routes.py:266`) |
| `Legal.js` privacy · deletion on request | only deactivation, personal data retained (`admin_routes.py:1237`) |

## 19. Notes on method limits (assumptions)

- Test pass/fail is not known from this inspection (suites were deliberately not run). Status 1 rests on test **presence and
  content**, not on a green run.
- Coverage attribution was made by grepping each API path / function name in `backend/tests/*.py`; a test that reaches a path only
  through a helper with a different literal may have been missed (rows marked "none" were double-checked by function name where
  relevant, e.g. `release_due_points`).
- Legal items O18–O20 are flagged as ASSUMPTIONS about Indian law requiring professional confirmation.

---
## Programme 01 status changes (2026-11-23) — rows above kept as inspected at `d31cb74`
| Capability | Programme 00 finding | Status now (1–9) | Evidence |
|---|---|---|---|
| Vendor contact edit (VEN-05) | regression on main (2 failing tests) | 1 | `test_programme01_vendor_state` (34), `test_vendor_foundation` 16/16, browser |
| Returned-to-origin money effect | no money effect (P0) | 1 | `test_programme01_rto` (13), cross-module 4 / 9, browser |
| Refund confirmation integrity | confirmable with nothing booked (P0) | 1 | `test_programme01_refund_integrity` (11), cross-module 5 / 6, browser |
| Post-payment completion on every path | only the Razorpay webhook re-ran completion (P0) | 1 | `test_programme01_completion` (17), cross-module 7 / 8 |
| Index readiness / money-write protection | startup only logged missing indexes (P0) | 1 (code) — production migration pending | `test_programme01_money_guard` (13) |
| Repair and release jobs at any volume | fixed ceilings (500 / 200 / 5,000) | 1 | `test_programme01_sweeps` (8), cross-module 10 |
| Order-creation protection, reservation expiry | no order rate limit; COD holds stock | 1 (COD expiry: owner decision) | `test_programme01_order_protection` (18), cross-module 11 / 12 |
| Admin image upload (merchandising, admin studio) | always 403 | 1 | `test_programme01_admin_media` (29), cross-module 14, browser |
| Operations queues status display | found in Programme 01: every row read "Selling role pending" | 1 | browser |

---
**Reconciliation 2026-11-24 (correction note; rows above unchanged).** Superseded by `HOME_GENIES_CURRENT_MODULE_COMPLETION_MATRIX.md`
(303 rows: the 266 above + 9 Programme 01 capabilities + 8 Programme 01 decisions + 20 Marketing Studio rows). Two entries of the
Programme 01 appendix above are qualified there: "Operations queues status display" and "Admin image upload" are **Implemented,
verification incomplete** (browser check only / in-memory object store only), not "Implemented and verified".
