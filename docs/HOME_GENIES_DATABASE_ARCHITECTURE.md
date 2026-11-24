# HOME GENIES — Database architecture (independent inspection)

Scope: `backend/*.py`, `backend/scripts/*.py`, `backend/db_indexes.py`, `backend/vercel.json` at git `main @ d31cb74` (clean tree).
Method: static reading only. No database was connected, no test or server was run. Every statement below is either
**[V] verified in code** (file:function:line given) or **[S] suspicion / inference** (marked as such).

Data store: a single MongoDB database (`core.py:36`, `client[DB_NAME]`) accessed with Motor 3.3.1 / PyMongo 4.6.3. All ids are
UUID4 strings in an `id` field (`core.new_id`, `core.py:53`); MongoDB `_id` is an ObjectId except where it is deliberately used as an
idempotency key (listed in section 6). **No multi-document transactions are used anywhere** ([V] `grep start_session|with_transaction`
→ no hits; `financial_ops.py:3-14` states this as a design choice).

---

## 1. Collection inventory

61 collections are referenced (`grep -ohE "db\.[a-z_]+"` over `backend/*.py` and `backend/scripts/*.py`; `db.list_collection_names` is a
method, not a collection). Reference counts in brackets show how central each collection is.

### 1.1 Identity and access

| Collection | Purpose | Key fields | Owning module(s) | References | Indexes (db_indexes.SPECS) |
|---|---|---|---|---|---|
| `users` [157] | Every login: customer, distributor (HomeGenie), vendor owner, vendor_staff, 4 admin roles | `id`, `distributor_id` (HG…/CU…/VD…/VS…/HGADM…), `role`, `status` (red/green/customer/not_applicable), `account_status`, `email`, `mobile`, `password_hash`, `password_changed_at`, `must_change_password`, `blocked`, `deleted_at`, `kyc_status`, `aadhaar_number`, `photo`, `sponsor_user_id`, `vendor_application_id`, `env_credential_marker` | core, auth_routes, admin_routes, admin_team | `sponsor_user_id`→users; `vendor_application_id`→vendor_applications; `default_address_id`→addresses | `users_email_partial_unique` (unique, partial string), `users_distributor_id_unique` (unique, **not partial**), `users_mobile_unique` (unique sparse), `users_id`, `users_vendor_application_unique` (unique partial). **Missing:** `role`, `username` |
| `registration_requests` [11] | Record of each sign-up (kept after auto-activation) | `id`, `mobile`, `email`, `password_hash`, `aadhaar_number`, `status` | auth_routes.register_request (l.233), admin_routes.activate_registration | creates `users` | **none** |
| `otp_sessions` [8] | Hashed single-use OTP per identifier+purpose | `identifier`, `purpose`, `code_hash` (HMAC-SHA256 with `OTP_PEPPER`), `attempts`, `used`, `expires_at` | providers.otp_create/otp_verify (l.131-197) | — | `otp_identifier_purpose`. **No TTL** (rows kept forever) |
| `login_attempts` [10] | Lockout counters | `identifier` (email/mobile/`admin:<ip>:<user>`), `count`, `last` | auth_routes.login (l.338), admin_login (l.534) | — | `login_attempts_identifier`. **No TTL** |
| `rate_limits` [2] | Fixed-window counters | `key`, `w`, `n`, `expires_at` (BSON date) | core.rate_limit (l.482) | — | `rate_limits_key_window_unique` (unique), `rate_limits_expires` (**TTL 0**) |
| `revoked_tokens` [2] | Logged-out JWT ids | `_id`=jti, `user_id`, `expires_at` | core.revoke_token_from_request (l.513) | users | `revoked_tokens_expires` (**TTL 0**) |
| `password_reset_tokens` [3] | Google-recovery reset tokens (sha256 stored) | `user_id`, `token_hash`, `used`, `expires_at` | auth_routes.forgot_google (l.468) | users | **none** (looked up by `token_hash`, l.503) ; no TTL |
| `password_reset_requests` [7] | "Ask admin to reset" queue | `user_id`, `mobile`, `full_name`, `status` | auth_routes.forgot_request (l.752) | users | **none** |
| `contact_change_requests` [10] | Admin-proposed mobile/email change awaiting holder OTP / super-admin recovery | `id`, `user_id`, `old`, `new`, `status`, `requested_by`, `history` | contact_change.py | users | `contact_change_user_status` |
| `account_invitations` [8] | Vendor-owner set-password invitations | `token_hash`, `user_id`, `vendor_id`, `status`, `expires_at` | vendor_invitations.issue (l.42) | users, vendors | `account_invitations_token_unique` (unique), `account_invitations_user_status` |
| `test_sms_outbox`, `test_sms_notices` [1] | Plain-text OTPs/notices, **only** when `SMS_TEST_ADAPTER=true` and `DB_NAME` ends in `_test` | `mobile`, `code` | providers._send_sms_otp (l.64) | — | none |

### 1.2 Catalogue and stock

| Collection | Purpose | Key fields | Owner | References | Indexes |
|---|---|---|---|---|---|
| `products` [100] | Platform and vendor products, variants, pending revision, price history | `id`, `sku`, `variants[].sku`, `vendor_id`, `approval_status`, `is_active`, `archived`, `admin_takedown`, `stock`, `stock_ops`, `pending_revision`, `price_history` | admin_routes, vendor_routes, pim, stock, discovery | `vendor_id`→vendors | `products_id`, `products_sku_unique`, `products_variant_sku_unique` (partial), `products_vendor_created`, `products_pending_revision` (partial), `products_text` (**text**, weights name10/brand5/keywords5/subcategory3/short1, `default_language:none`), `products_shop_category_price` |
| `product_drafts` [14] | Product studio drafts | `id`, `vendor_id`, `product_id`, `status` | pim.py | products, vendors | `product_drafts_id_unique`, `product_drafts_vendor_status`, `product_drafts_one_open_per_product` (unique partial) |
| `product_categories` [2] | Category names | `name` | server._init_db (l.276) | — | `product_categories_name_unique` |
| `stock_txns` [13] | Stock reservation/release journal with idempotency key | `key`, `kind`, `order_id`, `lines`, `status` | stock.py (l.110) | orders, products | `stock_txns_key_unique`, `stock_txns_status_updated` |
| `stock_movements` [14] | Human-readable stock movement log | `_id`=`mv:<txn>:<line>` (stock.py:193) or ObjectId (manual adjustments), `product_id`, `delta`, `reason`, `actor_id` | stock, admin_routes, vendor_routes | products, stock_txns | **none** (queried by `txn_id`+`line`, `product_id`) |
| `merch_sections` [8] | Home-page merchandising | `id`, `status`, `position`, `kind`, `link` | merchandising.py | products | `merch_sections_status_position` |
| `wishlist_items` [7] | Wishlist | `user_id`, `product_id`, `variant_sku` | customer_routes | users, products | `wishlist_user_product_variant_unique` |
| `files` [2] | Registry of uploaded images in Emergent object storage | `storage_path`, `owner_id`, `folder`, `is_deleted` | storage._upload_image (l.98) | users | **none** — queried on **every public image request** (`storage.serve_file`, l.120) |

### 1.3 Orders, payments, refunds, returns

| Collection | Purpose | Key fields | Owner | References | Indexes |
|---|---|---|---|---|---|
| `orders` [163] | Order header + embedded `items[]`, `fulfilments[]` (per vendor, with `events[]`), `address` snapshot, payment and COD state, `restock_intents[]`, `duplicate_payments[]`, `rejected_upi_claims[]` | `id`, `order_number`, `user_id`, `seller_user_id`, `status`, `payment_status`, `payment_method`, `total` + `total_paise`, `subtotal(_paise)`, `refunded_amount`/`refunded_paise`, `needs_refund`, `delivered_at`, `money_version` | shop_routes, admin_routes, vendor_routes, returns_routes, stock | users (`user_id`, `seller_user_id`), products/vendors via items/fulfilments | `orders_id`, `orders_order_number_unique`, `orders_payment_status_created`, `orders_fulfilment_vendor_created`, `orders_seller_created`. **Missing: `user_id`** (customer order list `shop_routes.my_orders` l.379, admin user detail, manual payment l.885, returns ownership checks) |
| `payment_transactions` [22] | One row per gateway attempt / manual confirmation | `session_id` (Stripe cs_…, Razorpay order_…, `admin_<order>`, `manual_<order>`), `order_id`, `provider`, `amount` (float), `status`, `payment_status` | shop_routes | orders, users | `payment_transactions_session` (**non-unique**). **Missing: `order_id`** |
| `payment_references` [2] | One bank/UPI UTR → one order | `_id`=normalised UTR | shop_routes._reserve_payment_reference (l.857) | orders | `_id` |
| `webhook_events` [9] | Razorpay event inbox (PII-free summary) | `event_id`, `type`, `gateway_order_id`, `amount_paise`, `status`, `attempts[]` | payment_events.py | payment_transactions, orders | `webhook_events_event_unique` (unique partial), `webhook_events_status_created`, `webhook_events_session` |
| `order_refunds` [11] | One refund event per (order, reference) | `_id`=`id`=`<order>:refund:<ref>`, `amount_paise`, `status`, `case_id` | shop_routes.reverse_order_financials (l.598) | orders, refund_cases | `_id` only (idempotency key). **Missing: `order_id`** (ledger.py:173) |
| `refund_cases` [22] | Refund workflow (maker-checker) | `id`, `source_key`, `order_id`, `status`, `initiated_by`, `initiators[]`, `confirming_reference` | returns_routes | orders, return_cases | `refund_cases_source_key_unique`, `refund_cases_status_created`. **Missing: `id`, `order_id`** |
| `return_cases` [24] | Customer returns | `id`, `order_id`, `user_id`, `vendor_id`, `status`, `lines[]` | returns_routes | orders, users, vendors | `return_cases_vendor_created`, `return_cases_user_created`. **Missing: `id`, `order_id`** |
| `addresses` [9] | Address book | `id`, `user_id`, `deleted_at` | customer_routes | users | `addresses_id_unique`, `addresses_user` |
| `returns_policy` [2] | Return window policy (single doc) | `id`, `window_days`, `version` | returns_routes.set_policy | — | none (single doc) |

### 1.4 Money: HomeGenie rewards

| Collection | Purpose | Key fields | Owner | References | Indexes |
|---|---|---|---|---|---|
| `wallets` [19] | Aggregate balances per user | `user_id`, 4 float fields + 4 `*_paise` twins, `applied_ops[]` (unbounded array of applied op keys) | core.wallet_apply (l.301), financial_ops.move_wallet_once (l.48), admin_routes.review_withdrawal | users | `wallets_user_unique` |
| `wallet_transactions` [13] | Wallet ledger rows | `user_id`, `type`, `direction`, `amount`+`amount_paise`, `status` (CREDITED/DEBITED/PENDING/HELD/INFO/CLAWBACK/PAID/REJECTED), `op_key` | core.add_wallet_transaction (l.318), financial_ops.ensure_ledger (l.38) | users, orders (reference) | `wallet_transactions_user`, `wallet_transactions_op_key_unique` (unique partial) |
| `commissions` [33] | Per-order commission shares | `_id`=`id`=key (new rows), `order_id`, `user_id`, `status`, `amount_paise`, `release{op_key,applied}`, `reversal_records[]`, `distribution{}`, `manual_hold` | commission.py, financial_ops | orders, users | `commissions_referred_user`, `commissions_user_created`. **Missing: `id` (legacy rows have ObjectId `_id`), `order_id`, `status`+`released_at`** (cron scan commission.py:308) |
| `commission_plans` [14] | Frozen commission plan per order | `_id`=order id, `items[]`, `completed_at` | commission.py (l.169) | orders | `_id` |
| `withdrawal_requests` [11] | HomeGenie payout requests | `id`, `user_id`, `amount_paise`, `status`, `approved_by`, `paid_by`, `payout_reference` | wallet_routes.request_withdrawal, admin_routes.review_withdrawal | users | `withdrawal_requests_user_created`. **Missing: `id`, `status`** |
| `withdrawal_payout_refs` [5] | One payout UTR → one withdrawal | `_id`=UTR | admin_routes.review_withdrawal (l.880) | withdrawal_requests | `_id` |
| `kyc_records` [13] | Member PAN / Aadhaar / bank | `user_id`, `pan`, `aadhaar`, `bank_account`, `ifsc`, `account_holder_name`, `status`, `version`, `last_edited_by` | wallet_routes.submit_kyc (l.113), admin_routes | users | `kyc_records_user` (**not unique** — concurrent first submissions can create two records) |
| `referral_codes` [9] | Admin referral codes | `code`, `active`, `uses`, `is_master` | admin_routes.gen_referral_code | users | **none** (no unique on `code`) |
| `referral_relationships` [9] | Sponsor links | `sponsor_id`, `referred_user_id` | auth_routes.register | users | **none** |
| `activation_history` [1] | HomeGenie activation approvals | `user_id`, `event` | activation_routes (l.104) | users, orders | none |
| `notifications` [10] | In-app notices | `user_id`, `type`, `read`, `meta.dedupe` | core.create_notification | users | `notifications_user`. Missing `user_id`+`meta.dedupe` (core.notify_order_vendors l.508) |

### 1.5 Money: vendors

| Collection | Purpose | Key fields | Owner | References | Indexes |
|---|---|---|---|---|---|
| `vendors` [58] | Vendor business record | `id`, `user_id`, `vendor_code`, `status`, `pan`, `gstin`, `bank_account`, `bank_account_name`, `ifsc`, `onboarding{}`, `owner_activation` | vendor_routes, vendor_onboarding, vendor_lifecycle.move | users, vendor_applications | `vendors_id_unique`, `vendors_user_unique`, `vendors_code_unique`, `vendors_application_unique` |
| `vendor_ledger` [18] | Immutable vendor money ledger | `source_key`, `vendor_id`, `type` (SALE_COLLECTED/SALE_REVERSAL/REFUND/ADJUSTMENT/SETTLEMENT_PAID/COMMISSION), `amount_paise`, `order_id`, `reverses` | ledger.post_entry (l.45) | vendors, orders | `vendor_ledger_source_key_unique`, `vendor_ledger_vendor_posted`. Missing `vendor_id`+`order_id`+`type` (ledger.py:61, 126) |
| `settlements` [13] | Vendor payouts | `id`, `vendor_id`, `amount_paise`, `status`, `created_by`, `approved_by`, `paid_by`, `events[]` | finance_routes | vendors, vendor_ledger | `settlements_vendor_created`, `settlements_one_open_per_vendor` (unique partial on `status ∈ {requested, approved}`) |
| `finance_policy` [2] | Settlement policy (single doc) | `active`, `version`, `min_settlement_paise` | finance_routes.admin_set_policy | — | none |
| `financial_approvals` [10] | Maker-checker queue | `_id`=`<kind>:<key>`, `maker_id`, `checker_id`, `status`, `payload` | financial_approvals.py | users, wallets/vendor_ledger | `_id` |
| `vendor_agreements` [15] | Commercial terms (commission %) per vendor | `id`, `vendor_id`, `status`, `version`, `commission_pct` | commercial_terms.py | vendors | **none** |
| `vendor_change_requests` [7] | Vendor bank-change requests (full new account number in `payload`) | `id`, `vendor_id`, `kind`, `status`, `payload` | governance_routes (l.189-252) | vendors | **none** |
| `benefit_programmes`, `benefit_grants` [6/8] | Vendor advancement benefits | `key`; `vendor_id`, `programme_id`, `status` | vendor_benefits.py | vendors | `benefit_programmes_key_unique`, `benefit_grants_vendor_programme_status` |

### 1.6 Vendor governance and onboarding

| Collection | Purpose | Key fields | Owner | References | Indexes |
|---|---|---|---|---|---|
| `vendor_applications` [17] | Public "Apply to sell" | `id`, `number`, `mobile`, `open_mobile`, `password_hash`, `status` | vendor_applications.py | users, vendors | `vendor_applications_id_unique`, `_number_unique`, `_open_mobile_unique` (partial), `_status_created` |
| `vendor_members` [8] | Vendor staff memberships | `vendor_id`, `user_id`, `role`, `permissions[]`, `status`, `token_hash` | vendor_staff_routes, vendor_staff.authorize_staff | vendors, users | `members_vendor_user_v2` (unique partial), `members_user_unique` (unique partial), `members_vendor_status`, `members_token` |
| `vendor_documents` [16] | KYC/business documents (URL references) | `id`, `vendor_id`, `type`, `url`, `status`, `deleted` | governance_routes, vendor_onboarding | vendors | `vendor_documents_vendor_created` |
| `vendor_status_history` [5] | Append-only status changes | `vendor_id`, `from`, `to`, `actor`, `at` | vendor_history.record_vendor_status | vendors | `vendor_history_vendor_at` |
| `vendor_policy` [4] | Required documents (single doc) | — | governance_routes | — | none |
| `support_tickets` [11] | Vendor ↔ admin tickets | `id`, `number`, `vendor_id`, `status`, `urgent` | governance_routes | vendors | `support_vendor_updated`, `support_status_urgent_updated`. Missing `id` |

### 1.7 Platform / operations

| Collection | Purpose | Notes |
|---|---|---|
| `audit_logs` [3] | Audit trail (`core.log_audit`, l.378) | **No index at all.** Read with `.sort("created_at",-1).to_list(500)` (admin_routes.admin_audit l.1451) and `find({"entity_id": ...})` (admin_order_ops.order_detail). Grows without bound. |
| `business_settings` [5] | Settings + bootstrap flag | single docs `business_settings`, `catalogue_bootstrap` |
| `counters` [4] | Sequences (`next_sequence`, core.py:215) | `find_one_and_update` with upsert on `{"id": name}`; no unique index on `id` (first-use race could create two counters → duplicate numbers; order/settlement/refund numbers are only unique where an index exists: `orders_order_number_unique`, `vendor_applications_number_unique`) [S] |
| `cron_runs` [7] | Cron de-duplication | `run_id` — **no unique index**: `cron_routes.release_points` (l.47-51) is find-then-insert, so two concurrent deliveries can both run (the release itself is idempotent, so the effect is duplicated work, not duplicated money) |
| `money_migrations` [1] | money_migration bookkeeping | — |
| `demo_batches` [1] | scripts/demo_environment.py only | — |

---

## 2. Index management

* [V] `db_indexes.SPECS` (l.20-104) is the **only** declared index list: 73 specs (unique, compound, partial, 2 TTL, 1 text). No other
  `create_index` call exists outside `db_indexes.apply` (l.222/226).
* [V] Application start-up **only checks** (`server._init_db` → `db_indexes.check_missing`, l.183) and logs "N missing". Indexes are
  created **only** by `scripts/vendor_foundation_migrate.py --apply` (→ `vendor_lifecycle.migrate` → `db_indexes.apply`).
* [V] `apply()` refuses to create a unique index when duplicates exist (reports counts only, never values), drops the three `LEGACY`
  indexes only once the replacement is confirmed safe, and restores the legacy index if creation fails (l.209-232).
* **Consequence (reliability, P1 in Doc 3):** the idempotency of money paths depends on unique indexes that the running app does not
  create: `vendor_ledger_source_key_unique`, `wallet_transactions_op_key_unique`, `refund_cases_source_key_unique`,
  `webhook_events_event_unique`, `stock_txns_key_unique`, `settlements_one_open_per_vendor`, `wallets_user_unique`,
  `product_drafts_one_open_per_product`, `vendor_applications_open_mobile_unique`. Code such as `ledger.post_entry` (l.53-57) and
  `financial_ops.ensure_ledger` (l.40-45) relies on `DuplicateKeyError`; without the index a concurrent duplicate is silently inserted.
  If the migration was skipped on a database, these guarantees do not hold.

### 2.1 Queries on high-traffic paths with no supporting index [V]

| Collection.field(s) | Where it is queried | Traffic |
|---|---|---|
| `orders.user_id` | `shop_routes.my_orders` l.379 (every "My orders" view), `admin_routes.admin_user_detail` l.140, `manual_payment_by_distributor` l.885, `returns_routes` l.376/452 (`id`+`user_id` — `id` index covers) | High |
| `files.storage_path` | `storage.serve_file` l.120 — **every public image request** | Very high |
| `audit_logs.created_at`, `audit_logs.entity_id` | admin audit page, admin order detail | Medium, grows forever |
| `users.role` | every "notify all admins" fan-out (`governance_routes._notify_admins` l.30, `returns_routes._notify_admins` l.61, `shop_routes` l.334, `stock.py` l.329), admin dashboard counts | Medium |
| `users.username` | `auth_routes.admin_login` l.545 (`$or` with unindexed branch ⇒ collection scan per admin login) | Low |
| `payment_transactions.order_id` | `admin_routes.delete_order` l.562, `admin_order_ops.order_detail`, `stock.py` l.414 | Medium |
| `commissions.order_id` / `commissions.id` / `status`+`released_at` | `reverse_order_financials` l.648, `commission_status` l.613, `release_due_points` l.308 (daily cron, `to_list(5000)`) | Medium / cron |
| `refund_cases.id`, `refund_cases.order_id`; `return_cases.id`, `return_cases.order_id` | refund/return actions, `financial_ops.has_open_case` (called per commission in the release cron) | Medium / cron |
| `withdrawal_requests.id`, `.status` | admin review | Low |
| `password_reset_tokens.token_hash` | `auth_routes.forgot_google_reset` l.503 | Low |
| `referral_codes.code`, `referral_relationships.referred_user_id` | registration | Low |
| `vendor_agreements.vendor_id`, `vendor_change_requests.vendor_id/status`, `support_tickets.id` | vendor screens | Low |
| `orders.needs_refund`, `orders.refund_due_cancel`, `orders.fulfilments.refund_due`, `orders.duplicate_payments.status` | `returns_routes.ensure_cases_for_flagged_orders` l.209-216 — run on every `GET /admin/refund-cases` and by the cron | Medium |
| `orders.created_at` regex prefix | `admin_routes.admin_dashboard` l.92-99 (`{"$regex": "^YYYY-MM-DD"}`), `wallet_routes.leaderboard` | Medium |
| `products` unanchored case-insensitive regex | `discovery.suggest` (public, per keystroke, `pagination.text_filter`) — cannot use an index | Medium (public, unauthenticated) |

---

## 3. Duplicated models and conflicting sources of truth

| # | Conflict | Evidence | Assessment |
|---|---|---|---|
| D-1 | **Float rupees vs integer paise** on orders, items, commissions, wallets, wallet_transactions, withdrawals, order_refunds | `money_migration.FIELDS` l.19-28; `core._wallet_view` l.271; `money.paise_of` fallback reads | Paise is authoritative where present; floats are still written beside it (`core.wallet_apply` l.309-310). **Readers still using floats:** `admin_routes.admin_dashboard` sums `total` floats (l.97-101) and caps at 5,000 paid orders (`to_list(5000)`) → total revenue is wrong once >5,000 paid orders and ignores refunds; `wallet_routes.leaderboard` sums `subtotal` floats; `shop_routes.create_checkout` sends `float(order["total"])` to Stripe (l.426); `payment_transactions.amount` is float only and `razorpay_verify` re-derives paise from it (l.501). |
| D-2 | **Wallet aggregate vs wallet ledger** | Balance changes happen in `core.wallet_apply` / `financial_ops.move_wallet_once` / direct `$inc` in `admin_routes.review_withdrawal` l.904; ledger rows separately via `add_wallet_transaction` / `ensure_ledger` | The **aggregate is what is spent** (withdrawal check `require_available`, l.313). Ledger rows are written *after* the aggregate in `request_withdrawal` (wallet_routes l.177-180) — a crash between them leaves a moved balance with no row. Reconciliation exists only as a READ-ONLY offline module (`wallet_reconcile.py`, used by `scripts/historical_audit.py`); no cron or endpoint runs it. |
| D-3 | **`order.status` vs `order.fulfilments[].status`** | Admin can set `status` freely within rules (`admin_routes.update_order_status` l.389); vendors drive `fulfilments` (`vendor_routes.vendor_update_fulfilment`), which rolls `status` forward (l.931-933) | For vendor goods, payout eligibility reads fulfilments (`eligibility.delivered_at`), and the admin "delivered" is recorded only as `status_set_by_admin` (l.419). For platform goods (no fulfilments) the admin status **is** the delivery record (`delivered_at`, l.414). Two meanings of `status` coexist. |
| D-4 | **Vendor bank details** in `vendors` vs `vendor_change_requests.payload` vs `vendors.onboarding` | governance_routes l.194, 249; vendor_onboarding | Change requests keep the full requested account number after decision; `vendors` holds the live copy. |
| D-5 | **Member identity** in `users.aadhaar_number` vs `kyc_records.aadhaar`; `registration_requests` keeps `password_hash` + `aadhaar_number` after activation | auth_routes l.224-230; wallet_routes l.121; admin_routes.activate_registration | Three copies of identity data; the request copy of the password hash goes stale after a password change. `vendor_applications.password_hash` is also kept after conversion. |
| D-6 | **Order money totals vs ledgers** | `orders.refunded_paise` vs `order_refunds` vs `vendor_ledger REFUND` vs `commissions.reversal_records` | Designed to be rebuildable (`ledger.reconcile_ledger`, cron); consistent only while the unique indexes in section 2 exist. |
| D-7 | **Two Stripe implementations** | `shop_routes` l.11-16 (`emergentintegrations` private package if importable, else `stripe_checkout.py`) | Behaviour on Emergent hosting cannot be verified from this repo. |
| D-8 | **Stale deployment copy** | `deploy/vercel-api/backend/*.py` (git-ignored, present locally) differs from `backend/` in 11 of 12 files; `deploy/vercel-api/vercel.json` schedules only `release-points` | If that project were deployed it would run old code. |
| D-9 | **Roles duplicated as string constants** | `core.ADMIN_ROLES`, `auth_routes.ADMIN_ROLES`, `FINANCE_ROLES` in 4 modules, `MONEY_ADMIN_ROLES`, `FINANCE_CONFIRM_ROLES`, `CANCEL_PAID_ROLES`, `POLICY_ROLES`, `DOC_REVIEW_ROLES`, … | Consistent today; drift risk. See Doc 2. |

---

## 4. Migration and maintenance scripts (`backend/scripts/`)

| Script | What it does | Idempotent | Rewrites history? |
|---|---|---|---|
| `vendor_foundation_migrate.py` | Dry run by default; `--apply` fills missing `vendors.vendor_code`, moves the `vendor` counter past existing codes, applies `db_indexes.apply()` | Yes (second run is a no-op) | No. Only sets `vendor_code` where missing; drops 3 legacy indexes after safe replacement |
| `migrate_money_paise.py` (+ `money_migration.py`) | Adds `*_paise` twins to orders, items, commissions, wallet_transactions, wallets, withdrawals, order_refunds; `--verify` recomputes totals | Yes (skips fields that already have a twin) | No (float fields untouched) |
| `historical_audit.py` | Read-only JSON report: duplicate wallets, legacy distributions, index plan, wallet reconciliation | n/a | No writes |
| `customer_role_report.py` | Read-only list of red distributors that look like pure shoppers | n/a | No writes |
| `hash_admin_password.py` | Prints a bcrypt hash for `ADMIN_PASSWORD_HASH` | n/a | No DB access |
| `seed_test_backend.py` | Seeds test accounts; **refuses** unless `DB_NAME` ends in `_test` and is not `homegenies` | Yes | Deletes `login_attempts`/`rate_limits` in the test DB only |
| `demo_environment.py` | Seeds/cleans a demo dataset through real routes; guarded to `127.0.0.1:27018` and `*_demo_test` DB names; `cleanup --apply` deletes `is_demo` docs | Yes | Test DB only. KNOWN_GAPS R-12 says it uses old contracts |

No migration framework / version table exists beyond `money_migrations`; ordering of scripts is documented only in
`docs/PRODUCTION_READINESS_CHECKLIST.md`.

---

## 5. Data isolation [V]

* **Customer/HomeGenie:** own orders (`get_order` owner check l.388), addresses (`customer_routes` filters `user_id` on every query,
  l.149-219), returns (`returns_routes` l.376, 452, 557), wallet/KYC/withdrawals/notifications keyed by `user["id"]`, HomeGenie
  metrics by `seller_user_id`/`user_id` (`homegenie_metrics` l.132-198) with customer first name only.
* **Vendor:** every vendor route derives `vendor_id` from the session (`vendor_routes.require_vendor_user` l.66, `_vendor_of`); order
  queries use `fulfilments.vendor_id` (`_orders_base` / `_orders_money_base` l.760-768, `vendor_orders` l.772); ticket relations are checked against own records
  (`governance_routes._check_related` l.276).
* **Vendor staff:** `vendor_staff.authorize_staff` (l.185) binds the request to the membership's vendor and an explicit path rule.
* **Admins:** see Doc 2; the admin side has no per-record scoping (every admin role sees all customers).
* No IDOR was found in the routes read; the Batch 11 audit reports the same (section E).

---

## 6. Financial ledgers, audit records and immutability

| Record | Immutability mechanism | Gaps |
|---|---|---|
| `vendor_ledger` | Append-only by convention (`ledger.py` docstring l.3-6); unique `source_key` per business event; corrections are new rows with `reverses` | No DB-level protection (any code path or DB user can update/delete). Uniqueness needs the migration. |
| `wallet_transactions` | `op_key` unique (partial); rows inserted, not updated, by money paths | Legacy rows without `op_key` have no idempotency; aggregate written before row in withdrawal request. |
| `order_refunds` | `_id` = event key | — |
| `commissions` | `_id` = key for new rows; state transitions via conditional updates; reversal intents | Legacy commissions lack the key. |
| `financial_approvals` | `_id` = kind:key; pending→approving→approved CAS (`financial_approvals.approve` l.96) | — |
| `settlements` | `events[]` append; CAS per transition (`finance_routes.settlement_action` l.371) | — |
| `vendor_status_history` | Append-only helper | — |
| `audit_logs` | `DELETE /api/admin/audit-logs` refuses and records the attempt (`admin_routes.clear_audit_logs` l.1456) | **No index, no hash chain, no write-once storage, no export/retention.** Several sensitive reads are not audited: `GET /admin/reports/{r}` and `/export` (full mobile/email, admin_routes l.1484-1507), `GET /admin/users` (l.118), `GET /admin/kyc`. `log_audit` is best-effort inside the request (an exception after the business write loses the audit row). |

Idempotency keys in use: `payment_references._id` (UTR), `withdrawal_payout_refs._id`, `order_refunds._id`, `commission_plans._id`,
`commissions._id`, `financial_approvals._id`, `stock_movements._id = mv:<txn>:<line>`, `wallet_transactions.op_key`,
`wallets.applied_ops[]`, `vendor_ledger.source_key`, `refund_cases.source_key`, `stock_txns.key`, `webhook_events.event_id`,
`cron_runs.run_id` (not unique), client `request_id` / `idempotency_key` on wallet credits and vendor adjustments.

---

## 7. Background jobs

| Trigger | Route | Work | Guard |
|---|---|---|---|
| Vercel cron `0 20 * * *` (`backend/vercel.json`) | `GET /api/cron/release-points` (`cron_routes.release_points_vercel` l.57) | `commission.release_due_points` inline, one run per UTC day (`run_id = vercel-YYYY-MM-DD`) | `Authorization: Bearer <CRON_SECRET or WEBHOOK_CRON_SECRET>`, `hmac.compare_digest` (l.17-23); empty secret ⇒ 401 |
| Emergent webhook | `POST /api/cron/release-points` (l.39) | same, as a BackgroundTask | same |
| Vercel cron `30 20 * * *` | `GET /api/cron/expire-pending-orders` (l.72) | expire unpaid online orders + UPI claims, stock crash recovery, refund-case creation, dispatch deadline alerts, `reconcile_ledger`, `reconcile_settlements` | same |
| Lazy sweeps on user requests | `my_orders` (l.378), `get_order` (`expire_one`), `list_refund_cases` (`ensure_cases_for_flagged_orders`) | partial sweeps | — |

Reliability notes: both crons run once a day on a 60 s function limit (`vercel.json` `maxDuration: 60`); release processes at most 5,000
commissions per run (`commission.py` l.307-313) with several queries per commission and unindexed look-ups — risk of time-out and
silent truncation as volume grows. No job status alerting exists (`cron_runs` is written but nothing reads it except de-duplication).
`expire-pending-orders` is not listed in `deploy/ENVIRONMENT.md`.

---

## 8. Data retention

* TTL indexes: only `rate_limits` and `revoked_tokens` (db_indexes l.40-43).
* Kept forever: `otp_sessions` (hashes + mobile numbers), `login_attempts`, `password_reset_tokens`, `password_reset_requests`,
  `registration_requests` (incl. `password_hash`, `aadhaar_number`), `vendor_applications` (incl. `password_hash`),
  `notifications`, `audit_logs` (incl. IP and e-mail), `webhook_events`, `cron_runs`, `stock_movements`, `files` (soft delete flag only).
* Account deletion is **deactivation only**: `admin_routes.delete_user` (l.1237) sets `account_status: deleted`, `blocked: true` and
  explicitly states "Personal-data anonymisation is not performed: no retention policy is defined yet". No customer self-deletion or
  data-export endpoint exists.

---

## 9. Sensitive personal data at rest

| Data | Where stored | At rest | Exposure controls |
|---|---|---|---|
| Aadhaar number (full 12 digits) | `users.aadhaar_number`, `registration_requests.aadhaar_number`, `kyc_records.aadhaar` | **Plaintext** | Masked in responses (`core.clean_user` l.106, `admin_routes.admin_kyc` l.645, `wallet_routes.get_kyc` l.102) |
| PAN | `kyc_records.pan`, `vendors.pan` | **Plaintext** | Masked (`_mask_pan`, `_public_vendor`) |
| Bank account + IFSC + holder | `kyc_records`, `vendors`, `vendor_change_requests.payload` | **Plaintext** | Masked in responses; audit stores only IFSC / masked values |
| GSTIN, business registration | `vendors`, `vendors.onboarding` | Plaintext | Returned to admins |
| KYC documents | `vendor_documents.url` → Cloudinary (`type: authenticated` when signed upload is used, governance_routes l.494) or any https link | External | URL visible to admins; no server-side signed-URL viewing path found |
| Profile photos, product images | Emergent object storage via `files` | External | Served **publicly without authentication** by path (`/api/files/{path}`, storage l.118) with `Cache-Control: public, immutable` |
| Profile photo as data URI | `users.photo` (up to 4 MB, `auth_routes.update_photo` l.582) | Plaintext in the user document | Loaded on every authenticated request (`get_current_user` returns the whole document) |
| Mobile, e-mail, address | `users`, `addresses`, `orders.address`, `vendor_applications`, `password_reset_requests`, `login_attempts.identifier`, `otp_sessions.identifier` | Plaintext | Masked for `accounts_admin` only in the new order screen (`admin_order_ops` l.21, 156); full in `/admin/users`, `/admin/orders`, reports export |
| Passwords | `users.password_hash` (bcrypt), also `registration_requests` and `vendor_applications` | bcrypt (`core.hash_password` l.65) | Never returned (`clean_user`, projections) |
| OTP codes | `otp_sessions.code_hash` = HMAC-SHA256(`OTP_PEPPER`, code) | Hashed; pepper defaults to empty string (`providers.py` l.20) | 6-digit space is small, so the hash protects little if the DB leaks while a code is live |
| Tokens (invites, resets) | sha256 hashes | Hashed | — |
| Audit IPs and e-mails | `audit_logs.ip`, `user_email` | Plaintext | Readable by every admin role |

**No application-level encryption exists** (`grep encrypt|fernet|cryptography` → no hits). Encryption at rest depends entirely on the
MongoDB host (Atlas configuration is not in the repo) — **[S] not verifiable here**. KNOWN_GAPS R-9 acknowledges this.

---

## 10. Backup and recovery

* **No backup, snapshot, export or restore tooling exists in the repo** ([V] no `mongodump`/`mongorestore`/snapshot script; only
  checklist text in `docs/PRODUCTION_READINESS_CHECKLIST.md` "mongodump of the target database" and "Backup and restore drill", both unchecked).
* Rollback note from the Batch 11 audit (section F) still applies: code rollback below `money_version 3` would mis-compute refunds;
  documented strategy is "restore code and refuse refunds on money_version 3 orders, or roll forward only".
* Self-repair routines (`reconcile_ledger`, `reconcile_settlements`, `reconcile_returns`, stock recovery) rebuild derived records but
  are **not** a substitute for backup: they read the same database.
* [S] Point-in-time recovery depends on the Atlas tier chosen by the owner; not visible in the repo.

---

## 11. Summary of database risks (ranked)

1. **P1** Money idempotency relies on unique indexes that only an out-of-band migration creates (section 2).
2. **P1** Plaintext Aadhaar / PAN / bank data in four collections with no app-level encryption and no retention (section 9).
3. **P1** No backup/restore mechanism or drill in the repo (section 10).
4. **P2** Missing indexes on `orders.user_id`, `files.storage_path`, `audit_logs`, `users.role`, `payment_transactions.order_id`,
   `commissions.order_id/status`, `refund_cases/return_cases.id/order_id` (section 2.1).
5. **P2** Admin dashboard revenue summed from floats and truncated at 5,000 orders (D-1).
6. **P2** No retention / anonymisation; OTP, login, reset and registration records kept forever (section 8).
7. **P3** `kyc_records.user_id`, `referral_codes.code`, `cron_runs.run_id`, `counters.id` lack unique constraints.
8. **P3** Unbounded embedded arrays: `wallets.applied_ops`, `orders.restock_intents`, `orders.fulfilments[].events`,
   `payment_transactions.gateway_events`, `webhook_events.attempts` [S: growth risk at scale].

---
## Programme 01 additions (2026-11-23) — earlier content kept as found
**New collections**
| Collection | Purpose | Key |
|---|---|---|
| `job_checkpoints` | resumable sweep position per job (`last_key`, `updated_at`) and `<job>:last_complete` counts | `_id` = job name |
| `order_submissions` | one claim per identical order submission (duplicate-click protection) | `_id` = SHA-256 fingerprint; TTL on `expires_at` |

**New fields:** `orders.completion_due` (marker written with the paid claim), `orders.completion {outcome, source, at, …}`,
`orders.paid_notified`, `orders.completion_blocked`; `refund_cases.last_booking_error`, `refund_cases.booking_shortfall_paise`;
`order_refunds.retried_at` / `attempts` (a rejected event re-claimed); refund case kind `returned_to_origin` (key `rto:<order>:<vendor>`);
`cron_runs` documents with `job: "maintenance"`.

**New index specs** (`db_indexes.SPECS`, created only by the migration): `orders_user_payment_status`, `order_submissions_expires` (TTL),
`orders_completion_due` (partial). **Index readiness is now enforced:** `money_guard` refuses money writes per area while any of
`vendor_ledger_source_key_unique`, `refund_cases_source_key_unique`, `wallet_transactions_op_key_unique`, `wallets_user_unique`,
`webhook_events_event_unique`, `settlements_one_open_per_vendor`, `stock_txns_key_unique`, `orders_order_number_unique` is missing or
different. The migration output now includes `money_duplicates` (record ids per duplicated business key) and `money_protection`.

Still open from the list above: `orders.user_id`-only, `files.storage_path`, `audit_logs`, TTLs on `otp_sessions` / `login_attempts` /
`password_reset_tokens` (B-025, Programme 02).

## Programme 02 / W5 additions (2026-11-24) — earlier content kept as found
Full audit: `HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md` (generated inventory of all 66 collections, 115 index specs, 1,042
database call sites). The status of each earlier finding:

| Earlier finding (§2 / §2.1 / §7 / §8 above) | W5 outcome |
|---|---|
| `orders.user_id` standalone | served by `orders_user_payment_status` (P01, `user_id` leads); explain-tested |
| `files.storage_path` (every image request) | `files_storage_path` |
| `audit_logs` (no index) | `audit_logs_entity_created`, `audit_logs_created` |
| `users.role`; `users.username` (admin login `$or` ⇒ scan) | `users_role`, `users_username`; **member login also scanned all users** (the e-mail `$or` branch cannot use the partial unique index) → `users_email_lookup` beside it |
| `payment_transactions.order_id`; `commissions.order_id` / `id`; refund / return case `id` / `order_id`; `withdrawal_requests.id`; `password_reset_tokens.token_hash`; `referral_codes.code`, `referral_relationships.referred_user_id`; `vendor_agreements.vendor_id` | one index each (W5 audit §6) |
| `orders` refund flags read by `ensure_cases_for_flagged_orders` | partial indexes `orders_needs_refund`, `orders_fulfilment_refund_due`, `orders_refund_due_cancel`; also journal recovery / restock intents (inline on checkout and order views) — measured ~210,000 documents examined per checkout → 2 keys |
| `orders.created_at` regex prefix (admin dashboard) | `orders_payment_status_created_at` (anchored prefix regex uses the index bounds) |
| `products` unanchored case-insensitive regex (`discovery.suggest`) | unchanged — cannot use an index; the text index serves search (B13) |
| Uniqueness: `kyc_records.user_id`, `cron_runs.run_id`, `counters.id` | all three unique (each race reproduced first: 3 KYC records for one member; the same sequence number issued 3 times; 6 cron run records) |
| TTL on `otp_sessions`, `login_attempts`, `password_reset_tokens` (§8) | **not created** — retention is owner decision P0-05, and these fields are ISO strings, which a TTL index would never expire; read-only `retention.expiry_report()` instead |
| Index management (§2): checks vs creation | unchanged model; added `dry_run()` (duplicate counts), `spec_version()`, `index_migrations` run records (interrupted runs detected), exact-name `plan()` consistent with the money guard, collation / text-language comparison, multikey and missing-vs-null duplicate counting |
| Background jobs (§7) | `prune_stock_markers` (200 per day, could starve) → resumable sweep; failure tracking no longer capped at 1,000 |

New collection: `index_migrations` (`_id` run id; `spec_version`, `started_at`, `status` running / done / incomplete / interrupted,
`finished_at`, created / dropped / failed / conflict index names, `money_protection_ready`). New read-only modules: `retention.py`,
`scripts/db_maintenance_report.py`. Production: none of the W5 indexes exist until the owner runs the migration (P1-01).
