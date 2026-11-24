# HOME GENIES — Database index, integrity and repair audit (Programme 02 / W5)

Date 2026-11-24. Working tree of `main` @ `d31cb74` (Programme 00 / 01 / DEF-03 / W8 / W6 work uncommitted); checkpoint
`~/home-genie-checkpoints/hg-20261124-1320-pre-w5-worktree.tar.gz`. Nothing staged, committed, pushed or deployed. Every test ran on the
isolated test MongoDB (7.0.45, 127.0.0.1:27018, throwaway databases). **No production data was read and no production migration was
run**: everything below about production is a statement about the code, not about the live database.
Readiness reference: `HOME_GENIES_PROGRAMME_02_READINESS.md` W5 (B-025). Earlier evidence kept: `HOME_GENIES_DATABASE_ARCHITECTURE.md`.

## 1. Summary
| Area | Found | Done in W5 | Left (reason) |
|---|---|---|---|
| B-004 protective-index verification | money guard exact and fail-closed; **`plan()` disagreed with the guard** (an identical index under another name counted as present, so the migration never repaired a money area the guard kept blocked); collation and text-index language not compared | `plan()` uses the guard's rule (own name + exact definition); collation and text language are part of the definition | — |
| Duplicate detection | multikey keys (`variants.sku`) compared as whole arrays; a missing field and `null` counted as different keys | one pipeline for migration and money report: arrays unwound, missing = null, documents counted once | production duplicates unknown until the dry run runs on a production copy (owner, with P1-01) |
| Migration model | idempotent, refuse-and-report, legacy replace-after-check; no run history, no version, no preview of duplicates | `spec_version()` fingerprint, `index_migrations` run records (interrupted runs detected and reported), `dry_run()` lists every create / refusal (with duplicate counts) / replacement / conflict | production process unchanged (still `vendor_foundation_migrate.py`, P1-01) |
| Uniqueness under races (proven by tests) | **KYC: 3 records for one member** from a double submission; **counters: the same number issued 3 times** on a sequence's first use (invoice, refund, settlement, ticket numbers have no unique index of their own); cron run id recorded 6 times | unique `kyc_records_user_unique`, `counters_id_unique`, `cron_runs_run_id_unique` (+ the losing writer updates / answers "duplicate" instead of failing) | effective only after the migration runs |
| Hot-path queries | 227 call sites with no supporting index (excluding `_id`); **every member login scanned the whole `users` collection** (the e-mail `$or` branch cannot use the partial unique index); stock journal lookups per reservation step and per movement line scanned their collections | 37 justified non-unique indexes (29 for request / admin queries, 8 for repair sweeps that run inside requests) plus the 3 unique ones above (§6); 107 unindexed call sites remain, all on small admin / configuration collections or ad-hoc admin search | — |
| Repair jobs | 16 sweeps on the resumable runner (Programme 01 / DEF-03) are complete (17 with W5), **but six of them run inside requests and, with nothing to repair, examined every order / journal row on each checkout, order view or returns page** (measured up to ~210,000 documents per checkout at 30,000 orders); **`prune_stock_markers` pruned at most 200 per day and could stop entirely** (skipped records filled every batch); the runner tracked at most 1,000 open failures | prune moved onto the runner; failure tracking unbounded; 8 sweep-selection indexes → 0-2 keys examined (§6.3) | capped reads in reports and dashboards (§6.2), stale "processing" webhook events (P03) |
| TTL / retention | 3 operational TTLs exist and are correct (BSON dates); most candidate collections store ISO **strings**, which a TTL index can never expire | read-only `retention.expiry_report()` + `scripts/db_maintenance_report.py` (counts, age profile, records past their own expiry) | every period is owner decision P0-05; nothing deleted, no TTL created |

Tests: new suite `test_w5_index_integrity` (58 tests). Evidence for the defects: 11 defect tests, each run on its own against the
unchanged code, failed exactly as described (renamed index, collation, text language, multikey and null duplicates, prune throughput,
prune starvation, failure records > 1,000, KYC race, counter race, cron race); the concurrent-sweep test passed before and after
(the handlers are claim-based). The unindexed hot paths are evidenced by the static analysis (§6) and by explain plans. Full
regression and live suites: §10.

## 2. Collection and index inventory
Generated from the code (`db.<collection>.<method>` call sites in `backend/*.py` and `scripts/*.py`, parsed with Python's AST) and
`db_indexes.SPECS`. Class: F financial integrity, S security / identity, C catalogue / customer, O operations. Index tags: U unique,
**B-004** = a money-protection index checked by `money_guard`, *W5* = added by this workstream. Every collection is confirmed in code;
none is invented. `_id` is always indexed and is not listed.

| Group | Collection | Purpose | Class | Owning modules (call sites) | Reads / writes | Indexes after W5 | Retention class |
|---|---|---|---|---|---|---|---|
| Identity | `account_invitations` | vendor owner / staff invitations | S | vendor_invitations (7), vendor_onboarding (1) | 4 / 4 | `account_invitations_token_unique` (token_hash; U); `account_invitations_user_status` (user_id,status) | owner decision |
| Identity | `contact_change_requests` | admin contact changes | S | contact_change (10) | 5 / 5 | `contact_change_user_status` (user_id,status) | owner decision |
| Identity | `kyc_records` | PAN / Aadhaar / bank (plaintext - W2) | S F | admin_routes (8), wallet_routes (6) | 8 / 6 | `kyc_records_user_unique` (user_id; U, *W5*) | never auto-delete |
| Identity | `login_attempts` | failed-login counters (lockout) | S | auth_routes (9), scripts/seed_test_backend (1) | 2 / 8 | `login_attempts_identifier` (identifier) | owner decision |
| Identity | `otp_sessions` | one-time passcodes (hashed) | S | providers (8) | 3 / 5 | `otp_identifier_purpose` (identifier,purpose) | owner decision |
| Identity | `password_reset_requests` | admin-handled resets | S | auth_routes (4), admin_routes (3) | 2 / 5 | `_id` only | owner decision |
| Identity | `password_reset_tokens` | single-use reset tokens | S | auth_routes (3) | 0 / 3 | `password_reset_tokens_hash` (token_hash; *W5*) | owner decision |
| Identity | `rate_limits` | request counters | S | core (1), scripts/seed_test_backend (1) | 0 / 2 | `rate_limits_key_window_unique` (key,w; U); `rate_limits_expires` (expires_at; TTL) | ttl in place |
| Identity | `registration_requests` | sign-up records | S | admin_routes (6), auth_routes (5) | 7 / 4 | `_id` only | owner decision |
| Identity | `revoked_tokens` | logged-out session ids | S | core (2) | 1 / 1 | `revoked_tokens_expires` (expires_at; TTL) | ttl in place |
| Identity | `users` | accounts of every role; login identifiers; sponsor link | S F | admin_routes (34), auth_routes (34), vendor_onboarding (12) … | 106 / 48 | `users_email_partial_unique` (email; U, partial); `users_distributor_id_unique` (distributor_id; U); `users_mobile_unique` (mobile; U, sparse); `users_id` (id); `users_vendor_application_unique` (vendor_application_id; U, partial); `users_role` (role; *W5*); `users_sponsor_status` (sponsor_user_id,status; *W5*); `users_email_lookup` (email; *W5*); `users_username` (username; *W5*) | — |
| Customer | `addresses` | address book | C | customer_routes (9) | 5 / 4 | `addresses_id_unique` (id; U); `addresses_user` (user_id,deleted_at) | — |
| Customer | `notifications` | in-app messages | C | wallet_routes (4), governance_routes (3), core (2) … | 7 / 3 | `notifications_user` (user_id) | owner decision |
| Customer | `wishlist_items` | wishlist | C | customer_routes (7) | 5 / 2 | `wishlist_user_product_variant_unique` (user_id,product_id,variant_sku; U) | — |
| Vendor | `benefit_grants` | benefit grants | O | vendor_benefits (8) | 6 / 2 | `benefit_grants_vendor_programme_status` (vendor_id,programme_id,status) | — |
| Vendor | `benefit_programmes` | benefit programmes | O | vendor_benefits (6) | 5 / 1 | `benefit_programmes_key_unique` (key; U) | — |
| Vendor | `vendor_agreements` | commercial agreements (rates) | F | commercial_terms (11), vendor_onboarding (2), commercial_routes (1) … | 12 / 3 | `vendor_agreements_vendor_status` (vendor_id,status,effective_from:-1; *W5*) | never auto-delete |
| Vendor | `vendor_applications` | apply-to-sell | O | vendor_applications (13), scripts/demo_environment (2), auth_routes (1) … | 10 / 7 | `vendor_applications_id_unique` (id; U); `vendor_applications_number_unique` (number; U); `vendor_applications_open_mobile_unique` (open_mobile; U, partial); `vendor_applications_status_created` (status,created_at:-1) | — |
| Vendor | `vendor_change_requests` | profile / bank change requests | S F | governance_routes (6), vendor_routes (1) | 5 / 2 | `_id` only | — |
| Vendor | `vendor_documents` | compliance documents | S | governance_routes (10), vendor_onboarding (4), vendor_history (1) … | 12 / 4 | `vendor_documents_vendor_created` (vendor_id,created_at:-1) | never auto-delete |
| Vendor | `vendor_members` | vendor staff | S | vendor_staff_routes (7), vendor_staff (1) | 5 / 3 | `members_vendor_user_v2` (vendor_id,user_id; U, partial); `members_user_unique` (user_id; U, partial); `members_vendor_status` (vendor_id,status); `members_token` (token_hash) | — |
| Vendor | `vendor_policy` | vendor policy singleton | O | governance_routes (2), vendor_history (1), vendor_onboarding (1) | 3 / 1 | `_id` only | — |
| Vendor | `vendor_status_history` | status audit | O | governance_routes (2), vendor_history (1), vendor_onboarding (1) … | 4 / 1 | `vendor_history_vendor_at` (vendor_id,at:-1) | — |
| Vendor | `vendors` | vendor accounts | F | vendor_onboarding (11), vendor_routes (10), finance_routes (7) … | 45 / 13 | `vendors_id_unique` (id; U); `vendors_user_unique` (user_id; U); `vendors_code_unique` (vendor_code; U, partial); `vendors_application_unique` (application_id; U, partial) | — |
| Catalogue | `files` | upload records | S | storage (2), governance_routes (1), retention (1) | 3 / 1 | `files_storage_path` (storage_path; *W5*) | owner decision |
| Catalogue | `merch_sections` | merchandising | C | merchandising (8) | 4 / 4 | `merch_sections_status_position` (status,position) | — |
| Catalogue | `product_categories` | categories | C | server (1), shop_routes (1) | 1 / 1 | `product_categories_name_unique` (name; U) | — |
| Catalogue | `product_drafts` | product studio drafts | C | pim (14) | 8 / 6 | `product_drafts_id_unique` (id; U); `product_drafts_vendor_status` (vendor_id,status,updated_at:-1); `product_drafts_one_open_per_product` (product_id; U, partial) | — |
| Catalogue | `products` | products, variants, stock, idempotency markers | C F | vendor_routes (35), admin_routes (13), pim (12) … | 72 / 28 | `products_id` (id); `products_sku_unique` (sku; U); `products_variant_sku_unique` (variants.sku; U, partial); `products_vendor_created` (vendor_id,created_at:-1); `products_pending_revision` (pending_revision.status; partial); `products_text` (text(name,brand,keywords,subcategory,short_description)); `products_shop_category_price` (is_active,approval_status,category,selling_price) | — |
| Stock | `stock_movements` | stock movement history | F | vendor_routes (7), stock (3), vendor_reports (3) … | 6 / 9 | `stock_movements_txn_line` (txn_id,line; *W5*); `stock_movements_product_created` (product_id,created_at:-1; *W5*); `stock_movements_order` (order_id; *W5*) | never auto-delete |
| Stock | `stock_txns` | stock journal (crash-safe reservation) | F | stock (12) | 5 / 7 | `stock_txns_key_unique` (key; U, **B-004**); `stock_txns_status_updated` (status,updated_at); `stock_txns_id` (id; *W5*); `stock_txns_unfinalized` (finalized,status,updated_at; *W5*); `stock_txns_unbound` (bound,kind,status,updated_at; *W5*); `stock_txns_unpruned` (pruned,updated_at; *W5*) | never auto-delete |
| Orders | `order_submissions` | duplicate-submission claims | F | order_protection (5) | 1 / 4 | `order_submissions_expires` (expires_at; TTL) | ttl in place |
| Orders | `orders` | orders, fulfilments, payment state | F | shop_routes (34), stock (27), returns_routes (21) … | 120 / 48 | `orders_id` (id); `orders_order_number_unique` (order_number; U, **B-004**); `orders_payment_status_created` (payment_method,payment_status,status,created_at); `orders_fulfilment_vendor_created` (fulfilments.vendor_id,created_at:-1); `orders_seller_created` (seller_user_id,created_at:-1); `orders_user_payment_status` (user_id,payment_status); `orders_completion_due` (completion_due; partial); `orders_payment_status_created_at` (payment_status,created_at:-1; *W5*); `orders_restock_intents_open` (updated_at; partial, *W5*); `orders_needs_refund` (needs_refund; partial, *W5*); `orders_fulfilment_refund_due` (fulfilments.refund_due; partial, *W5*); `orders_refund_due_cancel` (refund_due_cancel; partial, *W5*) | never auto-delete |
| Payments | `payment_references` | UPI / bank references (replay) | F | shop_routes (2) | 1 / 1 | `_id` only | never auto-delete |
| Payments | `payment_transactions` | gateway payment attempts | F | shop_routes (16), payment_events (3), admin_routes (2) … | 12 / 12 | `payment_transactions_session` (session_id); `payment_transactions_order_created` (order_id,created_at; *W5*) | never auto-delete |
| Payments | `webhook_events` | gateway events (idempotency) | F | payment_events (9) | 6 / 3 | `webhook_events_event_unique` (event_id; U, partial, **B-004**); `webhook_events_status_created` (status,created_at:-1); `webhook_events_session` (session_id) | never auto-delete |
| Refunds | `order_refunds` | refunds | F | shop_routes (7), returns_routes (3), ledger (2) … | 11 / 4 | `order_refunds_id` (id; *W5*); `order_refunds_order_created` (order_id,created_at; *W5*) | never auto-delete |
| Refunds | `refund_cases` | refund obligations | F | returns_routes (21), admin_order_ops (2), admin_routes (1) … | 18 / 7 | `refund_cases_source_key_unique` (source_key; U, **B-004**); `refund_cases_status_created` (status,created_at); `refund_cases_id` (id; *W5*); `refund_cases_order_created` (order_id,created_at; *W5*) | never auto-delete |
| Refunds | `return_cases` | returns | F | returns_routes (17), admin_order_ops (2), financial_ops (1) … | 17 / 6 | `return_cases_vendor_created` (vendor_id,created_at:-1); `return_cases_user_created` (user_id,created_at:-1); `return_cases_id` (id; *W5*); `return_cases_order_created` (order_id,created_at; *W5*) | never auto-delete |
| Refunds | `returns_policy` | returns policy singleton | O | returns_routes (2) | 1 / 1 | `_id` only | — |
| Vendor money | `finance_policy` | finance policy | F | finance_routes (2) | 1 / 1 | `_id` only | — |
| Vendor money | `financial_approvals` | maker-checker approvals | F | financial_approvals (10) | 5 / 5 | `_id` only | never auto-delete |
| Vendor money | `settlements` | settlements | F | finance_routes (9), vendor_reports (2), ledger (1) | 10 / 2 | `settlements_vendor_created` (vendor_id,created_at:-1); `settlements_one_open_per_vendor` (vendor_id; U, partial, **B-004**); `settlements_id` (id; *W5*) | never auto-delete |
| Vendor money | `vendor_ledger` | vendor ledger | F | ledger (12), finance_routes (8), returns_routes (2) … | 25 / 1 | `vendor_ledger_source_key_unique` (source_key; U, **B-004**); `vendor_ledger_vendor_posted` (vendor_id,posted_at:-1) | never auto-delete |
| HomeGenie money | `activation_history` | activation log | O | activation_routes (1) | 0 / 1 | `_id` only | — |
| HomeGenie money | `commission_plans` | per-order distribution plans | F | commission (4), finance_routes (4), wallet_reconcile (3) … | 13 / 2 | `_id` only | — |
| HomeGenie money | `commissions` | commission records | F | commission (10), admin_routes (4), homegenie_metrics (3) … | 23 / 8 | `commissions_referred_user` (referred_user_id); `commissions_user_created` (user_id,created_at:-1); `commissions_id` (id; *W5*); `commissions_order` (order_id; *W5*); `commissions_release_unapplied` (release.applied; partial, *W5*) | never auto-delete |
| HomeGenie money | `referral_codes` | registration codes | O | admin_routes (6), auth_routes (3) | 5 / 4 | `referral_codes_code` (code; *W5*) | — |
| HomeGenie money | `referral_relationships` | sponsor links | F | admin_routes (3), historical_audit (2), wallet_routes (2) … | 7 / 2 | `referral_relationships_sponsor` (sponsor_id; *W5*); `referral_relationships_referred` (referred_user_id; *W5*) | — |
| HomeGenie money | `wallet_transactions` | wallet ledger | F | historical_audit (3), wallet_reconcile (3), financial_ops (2) … | 11 / 2 | `wallet_transactions_user` (user_id); `wallet_transactions_op_key_unique` (op_key; U, partial, **B-004**) | never auto-delete |
| HomeGenie money | `wallets` | wallet aggregates | F | core (6), historical_audit (4), admin_routes (3) … | 14 / 5 | `wallets_user_unique` (user_id; U, **B-004**) | — |
| HomeGenie money | `withdrawal_payout_refs` | payout references (replay) | F | admin_routes (5) | 3 / 2 | `_id` only | never auto-delete |
| HomeGenie money | `withdrawal_requests` | withdrawals | F | admin_routes (7), wallet_routes (2), finance_routes (1) … | 8 / 3 | `withdrawal_requests_user_created` (user_id,created_at:-1); `withdrawal_requests_id` (id; *W5*) | never auto-delete |
| Support | `support_tickets` | vendor support tickets | O | governance_routes (11) | 8 / 3 | `support_vendor_updated` (vendor_id,updated_at:-1); `support_status_urgent_updated` (status,urgent:-1,updated_at:-1) | — |
| Audit | `audit_logs` | who did what | S | admin_order_ops (1), admin_routes (1), core (1) | 2 / 1 | `audit_logs_entity_created` (entity_id,created_at:-1; *W5*); `audit_logs_created` (created_at:-1; *W5*) | never auto-delete |
| Jobs | `cron_runs` | cron runs | O | cron_routes (8) | 3 / 5 | `cron_runs_run_id_unique` (run_id; U, *W5*) | owner decision |
| Jobs | `index_migrations` | index migration runs (W5) | O | vendor_lifecycle (5), scripts/db_maintenance_report (1) | 3 / 3 | `_id` only | never auto-delete |
| Jobs | `job_checkpoints` | sweep resume points | O | sweeps (4), finance_routes (1), scripts/db_maintenance_report (1) | 3 / 3 | `_id` only | never auto-delete |
| Jobs | `job_failures` | open sweep failures (retry) | O | sweeps (3), scripts/db_maintenance_report (1) | 2 / 2 | `job_failures_job` (job; *W5*) | never auto-delete |
| Jobs | `job_runs` | sweep run records | O | sweeps (1) | 0 / 1 | `_id` only | owner decision |
| Jobs | `money_migrations` | paise migration marker | O | money_migration (1) | 0 / 1 | `_id` only | — |
| Platform | `business_settings` | settings singleton | O | core (2), server (2), admin_routes (1) | 2 / 3 | `_id` only | — |
| Platform | `counters` | sequence numbers (orders, invoices, refunds, settlements...) | F | core (2), vendor_lifecycle (2) | 1 / 3 | `counters_id_unique` (id; U, *W5*) | — |
| Platform | `demo_batches` | demo seed bookkeeping (local only) | O | scripts/demo_environment (1) | 0 / 1 | `_id` only | — |
| Platform | `test_sms_notices` | test SMS adapter (tests only) | O | providers (1) | 0 / 1 | `_id` only | owner decision |
| Platform | `test_sms_outbox` | test SMS adapter (tests only) | O | providers (1) | 0 / 1 | `_id` only | owner decision |

66 collections; 115 index specs (40 added by W5); 1042 call sites analysed.

**Index specs:** 76 before W5 → 115 after (40 added; the non-unique `kyc_records_user` becomes a legacy index replaced by
`kyc_records_user_unique` only after the duplicate check passes). Collections without any specification beyond `_id` are small
singletons or admin-only lists (§5.3).

## 3. Programme 01 B-004 protective-index verification
`money_guard.AREAS` protects 8 unique indexes in 7 areas (ledger, refunds, wallet ×2, webhooks, settlements, stock, orders). Each
specification was re-read against the code that relies on it:

| Index | Keys / options | Write path that relies on it | Correct? |
|---|---|---|---|
| `vendor_ledger_source_key_unique` | `source_key`, unique | `ledger.post_entry` (one row per logical movement) | yes |
| `refund_cases_source_key_unique` | `source_key`, unique | `returns_routes` case creation per obligation | yes |
| `wallet_transactions_op_key_unique` | `op_key`, unique, partial `op_key: string` | `financial_ops` release / clawback intents; legacy rows without `op_key` are outside the index by design | yes |
| `wallets_user_unique` | `user_id`, unique | `core.get_or_create_wallet` (one wallet per user) | yes |
| `webhook_events_event_unique` | `event_id`, unique, partial `event_id: string` | `payment_events.claim` (one claim per gateway event) | yes |
| `settlements_one_open_per_vendor` | `vendor_id`, unique, partial `status ∈ {requested, approved}` | settlement request (one open settlement per vendor; paid / rejected ones are outside) | yes |
| `stock_txns_key_unique` | `key`, unique | `stock._new_txn` (one journal entry per logical stock change) | yes |
| `orders_order_number_unique` | `order_number`, unique | order creation | yes |

No collation is used or needed (all keys are machine identifiers). Field order is single-field everywhere, so compound order is not a
risk for B-004.

**Required test scenarios (all in `test_w5_index_integrity`; earlier B-004 tests in `test_programme01_money_guard` still pass):**
| # | Scenario | Result |
|---|---|---|
| 1 | required index exists and matches exactly | ready; plan "present" |
| 2 | required index missing | plan "missing"; only that area blocked (HTTP 503 `FIN_INDEX_NOT_READY`); reads unaffected (existing P01 tests) |
| 3 | index with incorrect options: not unique / no partial filter (P01 tests), **case-insensitive collation (W5 defect)**, **text index with another language (W5 defect)**, **identical definition under another name (W5 defect: plan said present)** | conflict in plan and guard alike; apply() never drops or rebuilds it (a person renames / removes it) |
| 4 | duplicate data prevents creation | apply() refuses that one index, names nothing personal; money report lists business keys and record ids; nothing deleted or merged; **multikey and missing-vs-null duplicates now found (W5 defects)** |
| 5 | unrelated indexes present | no effect on plan or guard |
| 6 | verification repeated | identical results, zero writes (`index_information` only) |
| 7 | MongoDB unavailable | guard state `unknown` for every area, `ready: False`, writes refused with 503; recovers when the database answers |

## 4. Index migration architecture
**Model (unchanged in principle):** `db_indexes.SPECS` is the only definition; `apply()` is the only code that changes indexes and is
run only by the migration command (`scripts/vendor_foundation_migrate.py --apply` → `vendor_lifecycle.migrate`); application startup
runs the read-only `check_missing()` and `money_guard.startup_report()` and never changes an index. `apply()` creates missing indexes,
refuses a unique index while duplicates exist, replaces a listed legacy index only after its replacement is proven safe, restores the
legacy index if creation fails, never deletes a document and never drops an unlisted index.

**Added by W5:**
- `spec_version()` — a fingerprint of SPECS + LEGACY; any definition change changes it.
- `index_migrations` — every applying run writes `{spec_version, started_at, status: running}` and finishes with
  `done | incomplete`, the created / dropped / failed / conflict index names and whether money protection is ready. A run found still
  `running` by the next run was interrupted: it is marked `interrupted` and listed in that run's report.
- `dry_run()` (and in `migrate(apply=False)`) — read-only preview: every index that would be created (keys + options), every creation
  that would be refused with the number of duplicate key values, every legacy index that would be replaced, every conflict left for a
  person. Proven write-free.
- `scripts/db_maintenance_report.py` — read-only: dry run, money readiness, money duplicates (record ids), last migration, sweep
  checkpoints / open failures per job, retention report.

**Interrupted migration.** Each `create_index` is atomic; re-running finishes the job. The one non-atomic step is a legacy replacement
(drop old → create new): a process killed between the two leaves neither index (for `users.email`, `vendor_members`, now `kyc_records`).
That gap is detected (`interrupted` run) and closed by re-running; it is never a money index (none of the B-004 indexes has a legacy
predecessor). Tested.

**Where verification runs:** startup (read-only log of missing / conflicting indexes and of each blocked money area), every money write
(`money_guard.ensure`, cached 300 s when ready / 15 s when not), finance diagnostics (`/api/admin/finance/system-integrity`), and the
maintenance report. **Proposal (not applied):** add `scripts/db_maintenance_report.py` to the deployment checklist — run it read-only
against the target database before and after every deployment that changes SPECS, and require `money_protection.ready` and an empty
`would_fail` before switching traffic. The production migration itself stays the owner's P1-01 step (verified backup → dry run →
`--apply` → maintenance report).

**Risks:** (1) the 40 W5 indexes are missing on production until P1-01 runs — startup logs them as missing (no write is blocked:
none is a money-guard index); (2) building indexes on a large production collection takes time and I/O (MongoDB 4.2+ builds
without a collection lock; run off-peak); (3) the three new unique indexes are refused if production already holds duplicates — the
dry run on a production copy will show it, and the legacy KYC index stays until then.

## 5. Duplicate-data findings
Test databases only: the duplicates created by the tests were detected, reported and left untouched. **Production is unknown** —
no production data was accessed. The places where production duplicates are most likely, given the races proven in §1, are
`kyc_records` (more than one record per member), `counters` (two counters for one sequence → repeated invoice / refund / settlement /
ticket numbers) and `cron_runs` (repeated run ids). The dry run (`would_fail`) and `money_guard.duplicate_report()` will list them on a
production copy; every resolution is a per-record human decision (finance for money keys). No automatic deletion or merge exists.

## 6. Query performance — indexes added (each tied to a real query)
| Index | Query (file:line) | Why it matters | Write / storage cost |
|---|---|---|---|
| `stock_txns_id` | `stock._status` (stock.py:131), finalise (196), recovery / prune | read on **every step of every stock reservation / release**; the journal grows ≥ 2 rows per order | one key per journal row |
| `stock_movements_txn_line` | `stock._log_movement` (stock.py:203) | read **before every movement line is written**; the collection grows per order line, so each write scanned all history | one key per movement; reduces total cost |
| `stock_movements_product_created` | vendor inventory history (vendor_routes.py:715) | sorted history per product | one key per movement |
| `stock_movements_order` | dispatch movement lookup (vendor_routes.py:997) | per dispatch | one key per movement |
| `commissions_id` | release / admin actions (commission.py:361-425, admin_routes.py:613-626, shop_routes.py:613) | 12 call sites; commissions grow up to 3 per order | one key |
| `commissions_order` | refund clawback (shop_routes.py:688), admin order view, audit | per refund | one key |
| `order_refunds_id`, `order_refunds_order_created` | refund execution (11 sites); **ledger reconcile sweep per order** (ledger.py:181, 211) | the sweep visits every order → one scan per order without it | two keys |
| `refund_cases_id`, `refund_cases_order_created`; `return_cases_id`, `return_cases_order_created` | case actions (7 + 7 sites), returns per order (returns_routes.py:600, financial_ops.py:39, homegenie_metrics.py:83) | case / return actions and HomeGenie metrics | two keys each |
| `settlements_id`, `withdrawal_requests_id` | finance actions (4 + 4 sites) | maker-checker actions | one key each |
| `payment_transactions_order_created` | `stock.payment_in_progress` / expiry (stock.py:424, 455), admin order view | **run for every order the expiry sweep visits** | one key |
| `users_role` | admin notifications in refund / stock flows (stock.py:354, returns_routes.py:63, …), dashboard counts | 16 sites on the largest collection | low-cardinality key; small |
| `users_sponsor_status`, `referral_relationships_sponsor` | **member referral page and dashboard** (wallet_routes.py:73-74, 283) | per member page view | one key each |
| `referral_relationships_referred`, `referral_codes_code` | registration, admin, audit | per registration | one key each |
| `users_email_lookup`, `users_username` | **member login** `$or` email / mobile / distributor id (auth_routes.py:348); admin login `$or` username / e-mail (545); admin-team checks | **every login was a full `users` scan** (explain: `COLLSCAN`; now `IXSCAN` on all branches); login is public, so this was also a cheap load lever | one key each; uniqueness stays with `users_email_partial_unique` |
| `files_storage_path` | `/api/files/{path}` (storage.py:139), signed-upload check (governance_routes.py:547) | **every image request** | one key per upload |
| `audit_logs_entity_created`, `audit_logs_created` | admin order history (admin_order_ops.py:184), audit viewer (admin_routes.py:1455) | audit log grows with every admin action; had no index at all | two keys |
| `vendor_agreements_vendor_status` | commercial terms (commercial_terms.py:53-123, 9 sites) | active agreement look-up per vendor | one key |
| `password_reset_tokens_hash` | reset token claim (auth_routes.py:503) | security path | one key |
| `orders_payment_status_created_at` | admin dashboard figures (admin_routes.py:95-101), activation list | per admin dashboard load; the existing payment index leads with `payment_method` | one key |
| `job_failures_job` | start of every sweep (sweeps.py:49) — sweeps also run at request time (checkout / order views) | per sweep | tiny |
| `counters_id_unique`, `cron_runs_run_id_unique`, `kyc_records_user_unique` | integrity (§1) | see §1 | tiny |

All 34 hot queries are asserted to plan as `IXSCAN` (no `COLLSCAN`) in `test_hot_query_uses_an_index`.

### 6.1 Not indexed, on purpose (107 call sites)
Small or singleton collections and admin-only lists where an index would cost writes for no measurable gain: `registration_requests`,
`password_reset_requests`, `contact_change_requests`, `vendor_change_requests`, `account_invitations` (kind / vendor), `benefit_*`,
`vendor_policy`, `returns_policy`, `finance_policy`, `business_settings`, `merch_sections`, `support_tickets` (by id), `vendor_documents`
(by id), `vendors` (by status), `commission_plans` (`completed_at` / `funding`, finance diagnostics), `withdrawal_payout_refs`
(`withdrawal_id`), audit scripts. Also not indexable as written: admin user search with an unanchored regex on `full_name`
(admin_order_ops.py:78) and `orders` boolean flags read by diagnostics (`completion_blocked`, `commissions_paid`,
`duplicate_payments.status`) — candidates for partial indexes if those diagnostics become frequent (P05).

### 6.2 Unbounded or silently capped reads (not changed — reports, W4 / P05)
| Where | Read | Effect beyond the cap | Owner workstream |
|---|---|---|---|
| admin_routes.py:101 | all paid orders `to_list(5000)` summed in Python | **dashboard total revenue understates** after 5,000 paid orders; should be a `$group` sum | W4 / P05 |
| badges.py:35 | a member's paid orders this month `to_list(5000)` | monthly badge sales understated after 5,000 orders in a month (eligibility figure) | P05 (owner visibility) |
| wallet_routes.py:278 | member commissions `to_list(2000)` | dashboard "today" / pending figures understated | P05 |
| finance_routes.py:103 | vendor ledger statement `to_list(20000)` | statement truncated after 20,000 rows | P03 |
| admin_routes.py:122, 365, 586-597, 643, 783, 1492-1502; vendor_reports.py | list / report endpoints capped at 1,000-5,000 | lists truncated (already D3 / D37) | W4 |
| wallet_reconcile.py:104-120, historical_audit.py, vendor_lifecycle.py:119, 127 | read-only audits capped at 10,000-100,000 | audit silently partial at that scale | P05 |
Large aggregations on request paths: none found beyond the merchandising best-seller aggregate (merchandising.py:127; covered by the
order payment / created indexes).

### 6.3 Repair sweeps that run inside requests (measured)
`stock.expire_pending_online_orders(limit=50, max_seconds=2)` runs on checkout and order views (shop_routes.py:281, 400) and calls
five sweeps; `returns_routes.ensure_cases_for_flagged_orders(max_seconds=3)` runs three on the returns page (returns_routes.py:283).
The runner sorts every selection by `id`, so when no index serves the selection the planner walks the whole `id` index and examines
every document — on every such request, even when there is nothing to repair. Throwaway database, 30,000 settled orders, 60,000
settled journal rows, 30,000 released commissions; first batch exactly as the runner reads it (`explain` executionStats):

| Sweep | Runs on | Before W5 (keys / docs examined) | W5 query indexes only | W5 final | Index that serves it |
|---|---|---|---|---|---|
| expire_pending_online | checkout, order views | 0 / 0 | 0 / 0 | 0 / 0 | `orders_payment_status_created` (P01) |
| expire_upi_claims | checkout, order views | **30,000 / 30,000** | 0 / 0 | 0 / 0 | `orders_payment_status_created_at` |
| stock_expiry_self_heal | checkout, order views | **30,000 / 30,000** | 0 / 0 | 0 / 0 | `orders_payment_status_created_at` |
| stock_txn_recovery | checkout, order views | **120,000 / 120,000** | **60,000 / 60,000** | 2 / 0 | `stock_txns_status_updated` + `stock_txns_unfinalized` + `stock_txns_unbound` |
| stock_restock_intents | checkout, order views | **30,000 / 30,000** | **30,000 / 30,000** | 0 / 0 | `orders_restock_intents_open` (partial) |
| refund_obligations_late | returns page, cron | **30,000 / 30,000** | **30,000 / 30,000** | 0 / 0 | `orders_needs_refund` (partial) |
| refund_obligations_not_supplied | returns page, cron | **30,000 / 30,000** | **30,000 / 30,000** | 0 / 0 | `orders_fulfilment_refund_due` (partial) |
| refund_obligations_cancel | returns page, cron | **30,000 / 30,000** | **30,000 / 30,000** | 0 / 0 | `orders_refund_due_cancel` (partial) |
| completion_repair | cron | 0 / 0 | 0 / 0 | 0 / 0 | `orders_completion_due` (P01, partial) |
| commission_release_finish | cron | 0 / 30,000 (collection scan) | 30,000 / 30,000 | 0 / 0 | `commissions_release_unapplied` (partial) |
| stock_marker_prune | cron | 60,000 / 60,000 | 60,000 / 60,000 | 1 / 0 | `stock_txns_unpruned` |
| commission_release | cron (daily) | 0 / 30,000 | 30,000 / 30,000 | 30,000 / 30,000 | none — one full pass per day by design |
| dispatch_deadlines | cron (daily) | 30,000 / 30,000 | — | 0 / 0 here (data-dependent) | none added — one pass per day by design |

Per checkout / order view that is about **210,000 documents examined before W5 → 2 index keys after**, at 30,000 orders, growing
linearly with history (a single query of that size would by itself exceed the 2-3 s inline budgets well before production scale).
The selections and the runner are unchanged (no DEF-03 / Programme 01 logic touched); the partial indexes hold only flagged
documents, the three `stock_txns` indexes one key per journal row. Locked in by `test_request_time_sweeps_do_not_scan_settled_history`
(≤ 5 documents / ≤ 10 keys with 3,000 settled orders and 6,000 settled journal rows). Ledger, settlement and dispatch reconciliations
and the daily commission release remain full passes by design (cron only, 40 s budget, resumable).

## 7. TTL and retention (owner decision P0-05 — nothing created, nothing deleted)
**Existing TTLs (correct, unchanged):** `rate_limits.expires_at`, `revoked_tokens.expires_at`, `order_submissions.expires_at` — all
written as BSON dates, all operational data with no value after expiry.

**Key technical finding:** every other candidate stores its time fields as ISO **strings** (`now_iso()`, `.isoformat()`). MongoDB TTL
indexes only expire BSON dates, so a TTL index on `otp_sessions.expires_at`, `password_reset_tokens.expires_at` etc. would be accepted
and **silently never delete anything**. Any approved retention therefore needs either a BSON date field written alongside (code change
+ backfill) or a scheduled, audited delete job — a design choice that follows P0-05.

| Collection | Purpose | Governing field | Benefit of expiry | Risk of deletion | Value | Proposed decision for the owner |
|---|---|---|---|---|---|---|
| otp_sessions | hashed passcodes | `expires_at` (string) | removes dead codes | none after expiry except abuse investigation | security | P0-05: keep N days after expiry |
| password_reset_tokens | hashed reset tokens | `expires_at` (string) | as above | as above | security | P0-05 |
| login_attempts | lockout counters | `last` (string) | stale counters | deleting resets a lockout | security | P0-05: only well after the lockout window |
| password_reset_requests, contact_change_requests, account_invitations | admin-handled identity actions | `created_at` / `requested_at` | smaller collections | loses identity-change audit | audit | P0-05 (audit period) |
| registration_requests | sign-up records with personal data | `created_at` | DPDP minimisation | loses registration evidence | legal | P0-05 + legal (L12) |
| notifications | member messages | `created_at` | size | members lose history | service | P0-05 |
| cron_runs, job_runs | run records | `created_at` / `started_at` | size | operations history | ops | P0-05 (keep ≥ recent window for de-duplication) |
| files (soft-deleted only) | upload records | `created_at`, `is_deleted` | storage | a live image stops working if misapplied | evidence | P0-05 + object-store policy |
| test_sms_outbox / notices | test adapter only | `created_at` | — | — | none | should never exist in production |
| job_failures, job_checkpoints, index_migrations, stock_txns, stock_movements, audit_logs, orders, payment_transactions, webhook_events, payment_references, order_refunds, refund_cases, return_cases, settlements, vendor_ledger, wallet_transactions, wallets, commissions, withdrawal_requests, withdrawal_payout_refs, financial_approvals, kyc_records, vendor_documents, vendor_agreements | financial, payment, refund, settlement, identity, audit or live recovery state | — | — | evidence lost, replay protection lost or retries forgotten | financial / legal / audit / recovery | **never auto-delete by age**; archival or deletion only by a separate, approved policy (KYC: P0-05 / L12 / W2) |

`retention.expiry_report()` (read-only) reports, per collection: documents, counts older than 1 / 7 / 30 / 90 / 365 days, records past
their own expiry field, soft-deleted files. It proposes no period.

## 8. Repair and release job inventory
All sweeps run on `sweeps.run_sweep` (Programme 01 B-005, DEF-03): keyset order on a stable unique key, checkpoint per batch, resume
after interruption, per-record isolation, failures recorded in `job_failures` and retried next pass, run records in `job_runs`, time
budget, idempotent handlers (state-filtered claims). Concurrency: there is no run lease; two runs of one job may visit the same records,
and the claim-based handlers make each change exactly once (tested with two concurrent runs, 600 records).

| Job | Module | Collection / selection | Dry run | Notes |
|---|---|---|---|---|
| expire_pending_online | stock.py | unpaid online orders past the window | no (skipped in maintenance dry run) | request-time + cron |
| expire_upi_claims | stock.py | overdue UPI claims | no | |
| stock_expiry_self_heal | stock.py | cancelled orders with unreleased lines | yes | DEF-03 |
| stock_txn_recovery | stock.py | interrupted journal transactions (age ≥ 120 s) | yes | DEF-03 |
| stock_restock_intents | stock.py | durable restock intents | yes | DEF-03 |
| **stock_marker_prune** | stock.py | finalised, unpruned journal rows older than 7 days | n/a (skipped in dry run) | **W5: was `find().limit(200)` — see §1** |
| completion_repair | order_completion.py | `completion_due` orders (paid, not finished) | yes | B-003; blocked while money protection missing |
| refund_obligations_late / _not_supplied / _cancel | returns_routes.py | orders flagged with a refund obligation | yes | every obligation gets its case |
| returns_reconcile | returns_routes.py | inspected return cases | yes | |
| ledger_reconcile | ledger.py | orders whose vendor ledger may be incomplete | yes | now indexed per order (§6) |
| settlements_reconcile | finance_routes.py | paid settlements | yes | |
| dispatch_deadlines | vendor_routes.py | orders awaiting dispatch | no | alerts only |
| commission_plans_resume / commission_release_finish / commission_release | commission.py | open plans; half-applied releases; due commissions | yes | B-005 |
| wallet_reconcile.reconcile | wallet_reconcile.py | read-only report | — | capped reads (§6.2) |
| historical_audit / programme01_reconcile | scripts | read-only reports | — | capped reads (§6.2) |
| payment events | payment_events.py | not a sweep: gateway re-deliveries take over a stale `processing` claim; finance retries failed events from the inbox | — | an event left `processing` after the gateway stops retrying is visible only through the inbox filter (P03) |

## 9. Remaining fixed limits and incomplete recovery
- None in the repair sweeps after W5 (`limit` / `batch` arguments are page sizes).
- `stock._flag_refund` notifies at most 20 super admins (`to_list(20)`) — notification fan-out, not recovery.
- Capped read-only reports and dashboards: §6.2.
- Stale `processing` webhook events are not raised as failures automatically (P03).
- No run lease for sweeps: duplicate visits are harmless only because every handler is claim-based; a future non-idempotent handler
  would need a lease (recorded as a rule in `sweeps.py`'s contract).

## 10. Verification
- **Defects reproduced first** (each test run alone on the unchanged code): renamed index (plan said present), collation, text
  language, multikey duplicates (0 found, 1 real), missing-vs-null duplicates (0 / 1), prune throughput (200 of 450), prune starvation
  (0 of 5), failure records > 1,000 (5 never cleared), KYC race (3 records), counter race (W0001 issued 3 times), cron race (6 runs).
  Request-time sweep scans measured on 30,000 orders (§6.3 of the W5 audit).
- **Focused suite** `test_w5_index_integrity`: **58 passed** (verification ×8, duplicates ×3, migration ×3, repair jobs ×5, races ×3,
  34 hot-path explains, request-time sweep scans, retention report).
- **Focused existing suites:** test_db_indexes 8, test_programme01_money_guard 13, test_vendor_foundation 16, test_stock_recovery 25,
  test_def03_stock_recovery 15, test_programme01_sweeps 8, test_stock_reservation 13, test_stock_expiry_race 39, test_identity_batch4 9,
  test_withdrawal_controls 33, test_governance_security 16, test_discovery_merch_b13 11, test_security_batch0 63,
  test_programme01_cross_module 14 — all passed.
- **Full in-process regression** (final code; file hashes checked unchanged before and after the run): **73 suites, 1,522 passed,
  0 failed, 0 skipped, 0 errors, 0 not run** (W6 baseline 72 suites / 1,464 + the 58 new tests). No existing test changed.
- **Live-server suites** (uvicorn, disposable DB): **96 passed, 6 skipped** (same skips and counts as Programme 01 / W6; `test_health_dashboard`
  counted from its SMS-on run as before). Every server logged "DB initialisation complete".
- **Lint:** pyflakes over `backend/*.py` + `scripts/*.py` — 0 new findings against the baseline; new files clean.
- **Not run:** frontend checks and browser checks (no frontend file changed in W5).

## 11. Files changed (W5)
Code: `backend/db_indexes.py` (40 specs, 1 legacy replacement, exact-name plan, collation / text-language comparison, shared duplicate
pipeline, `spec_version`, `dry_run`), `backend/money_guard.py` (shared duplicate pipeline), `backend/vendor_lifecycle.py` (migration
run records, dry-run preview), `backend/stock.py` (`prune_stock_markers` on the sweep runner), `backend/sweeps.py` (unbounded failure
tracking), `backend/cron_routes.py` (prune budget; duplicate cron delivery answered as duplicate), `backend/wallet_routes.py` (concurrent
KYC submission becomes an update), `backend/admin_routes.py` (admin KYC create answers 409 on a concurrent create). New:
`backend/retention.py`, `backend/scripts/db_maintenance_report.py`, `backend/tests/test_w5_index_integrity.py`. No existing test changed.

## 12. Remaining risks and owner decisions
- **P1-01 (existing):** the production migration now also creates the 40 W5 indexes; run the dry run on a production copy first.
- **P0-05 (existing):** every retention period in §7, and the choice between BSON-date TTL fields and an audited delete job.
- **W5-01 (new, owner):** how to resolve duplicates the dry run may find in `kyc_records` (which record is authoritative per member)
  and `counters` (which sequence value continues; whether already-issued duplicate invoice / refund / settlement numbers need a
  correction notice) — only if the production dry run reports any.
- Capped dashboard / report figures (§6.2) → W4 / P05; stale webhook claims → P03; sweep lease → only if a non-idempotent handler is
  ever added.
