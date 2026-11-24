# HOME GENIES — Engineering log, Batch 12 onward

Baseline `ce4ab93`. Everything below is uncommitted. Verified only on the isolated test MongoDB (`hg-test-mongo`, throwaway
`*_test` databases). Two Claude sessions briefly worked in this tree at the same time (one resumed after a restart); the overlap was
stopped, the later session took sole ownership, and the duplicate code it found was removed.

## Phase 2 — security fixes (Batch 11 audit)

| Audit | Change | Where |
|---|---|---|
| C-1 | `otp_verify` reserves an attempt atomically (`used:false, attempts<max` → `$inc`) before comparing, consumes the code with a second conditional update, and counts every attempt against `otp_attempts_identifier` (20 per identifier+purpose per day, across codes) | `providers.py`, `core.RATE_LIMITS` |
| C-2 | `client_ip` uses `X-Forwarded-For` only on Vercel or behind a private/loopback peer, and then the rightmost entry (`TRUSTED_PROXY_HOPS` for longer chains); otherwise the socket peer | `core.client_ip` |
| C-3 | legacy `/api/auth/register` stores `email_verified: False` (only the mobile was proven) | `auth_routes.register` |
| C-9 | `/forgot/google` and its reset require an eligible, active account whose e-mail is verified or Google-linked | `auth_routes.forgot_google*` |
| C-16 | `POST /api/vendor-applications/send-otp`; when SMS works the application needs the code, and the applicant account is `mobile_verified` | `vendor_applications`, `vendor_onboarding`, `VendorApply.js` |
| C-17 | block / deactivate of `vendor` / `vendor_staff` accounts limited to `VENDOR_ADMIN_ROLES`; staff refused while the owner is blocked / deleted / suspended | `admin_routes._guard_vendor_account`, `vendor_staff.authorize_staff` |
| L6 | admin-login answers a blocked / deactivated admin exactly like a wrong password | `auth_routes.admin_login` |
| L9 | sessions require `exp`, `sub` and `type: access` (every token since the first release has it) | `core._decode` |

## Phase 3 — money integrity (Batch 11 audit)

| Audit | Change | Where |
|---|---|---|
| C-4 | `POST /api/admin/orders/{id}/refund` no longer moves money: it initiates the order's open refund case (or a new `admin_refund` case / the cancellation case) as the MAKER with the reference proposed; a different finance admin confirms through the case flow | `admin_routes.refund_order`, `returns_routes.initiate_case_as` |
| L1 | retry keeps the first `initiated_by`; every initiator is recorded in `initiators` and refused at confirmation | `returns_routes.refund_case_action` |
| C-5 | delivery for payouts = vendor fulfilments: `eligibility.delivered_at(order, vendor_id)` reads fulfilments (all finished, at least one delivered); admin "delivered" on vendor goods is recorded as `status_set_by_admin` only; regression from delivered unsets `delivered_at`; vendors cannot move a cancelled/refunded order forward; COD confirmation records payment, not delivery | `eligibility.py`, `admin_routes.update_order_status`, `vendor_routes.vendor_update_fulfilment`, `shop_routes._cod_delivery_fields`, `finance_routes.resolve_cod_discrepancy` |
| C-7 | order rolls to delivered when every group is delivered or ended without supplying; vendor settlement eligibility is per vendor (`payout_block(..., vendor_id)`) | same + `ledger._eligible_paise` |
| C-6 | `post_sale_reversal` reverses only `sale − refunds already posted`; commission return posted independently (idempotent key) | `ledger.py` |
| C-8 | `expected_cod_paise` and `commission_base_paise` exclude goods whose vendor rejected / cancelled / returned to origin; ledger scales against the expected amount | `cod_rules`, `shop_routes.cod_collected`, `commission._freeze_plan`, `ledger.post_order_collected` |
| C-10 | `collection_is_proven` accepts `partially_refunded` | `cod_rules` |
| C-11 | refund splits use the goods value without the COD fee (`refund_basis_paise`) | `cod_rules`, `ledger.post_refund_shares`, `shop_routes._reverse_commission` |
| C-13 | withdrawal approve and mark-paid re-check KYC (`require_kyc_for_withdrawal`) | `admin_routes.review_withdrawal` |
| C-18 | approvals stuck in `approving` are listed with pending ones and can be taken over after 5 minutes (never by the maker); a fresh claim is never taken, so concurrent clicks still execute once | `financial_approvals.approve` |
| C-21 | statement reads legacy float amounts; lines carry basis (percent × base), reversal reasons | `wallet_routes.my_commission_statement` |
| C-14, C-15, L12, L15 | customer home + `MemberOnly` route guard + 4-tab mobile bar; statement chip shows the commission's real state and cards on phones; credit toast; staff landing page | frontend |

Eligibility fallback for older records: a delivered fulfilment without a delivered event or timestamp uses the order's
`delivered_at`; an order without vendor fulfilments (platform goods) keeps the order-level record.

### Tests changed (each contradicted an approved rule; reason recorded in the test)
- `test_payout_eligibility`: `_set` records delivery on the fulfilments; "admin marking delivered records the delivery time" →
  "is recorded but is not the delivery" (C-5).
- `test_refund_return_controls::test_g2_an_already_released_commission_is_clawed_back_proportionally`: release now reached with both
  vendors delivered; vendor B's goods refunded through a return case (the old setup released while B was still "new" — C-5/C-7).
- `test_returns_refunds`: the one-step refund test became "records the open case for a second finance admin" (C-4, decision S-4).
- `test_followup_a2`, `test_money_exact`, `test_payment_integrity_batch1`: refunds confirmed by a second finance admin (C-4).
- `test_forgot_google`: seeded accounts have a proven e-mail (C-9).
- `test_finance_ledger`, `test_e2e_vendor_integration`: deliveries recorded through `tests/delivery_helper.py` (C-5).

## Phase 4 — product information management

- `catalogue_templates.py` (data only): sub-categories and labelled attribute groups for the four pillars, field types
  text/textarea/number/date/select/multi/bool, required flags (all products or listed sub-categories), variant-capable fields,
  review flags for legal/regulatory checks. `catalogue.ATTRIBUTE_SPECS` is derived from it; the original keys keep their original
  validation, so existing products stay valid.
- `pim.py`: `GET /api/pim/template`; vendor drafts `/api/vendor/pim/drafts[...]` (create, versioned save, get, list, submit,
  discard), `GET /api/vendor/pim/products/{id}/revision`; admin `/api/admin/pim/drafts[...]` (on a vendor's behalf),
  `/api/admin/pim/revisions`, `/api/admin/pim/products/{id}/revision[/decision]`, `/price-history`.
- Shared server functions in `vendor_routes`: `create_vendor_product`, `apply_product_update(review=…)`,
  `changed_review_fields`. New product fields `highlights`, `model_number`, `image_alt` (validated; alt text only for the
  product's own images). Approval writes the first `price_history` entry; approved revisions append one when price/GST/HSN change.
- A vendor PUT to a product with a pending revision is refused (409). Shop endpoints use `P_SHOP`, which never returns
  `pending_revision`, `price_history`, `compliance_documents` or reviewer identities (this also closes an existing exposure of
  vendor compliance documents to the public product API).
- Indexes: `product_drafts_id_unique`, `product_drafts_vendor_status`, `product_drafts_one_open_per_product` (unique, partial on
  open drafts), `products_pending_revision` (partial).
- Staff rules: studio reads need `products.read`, writes need `products.write`.
- Frontend: `components/catalogue/ProductStudio.js` (8 sections, autosave with version conflict detection, per-section status,
  price breakdown, bulk variant generation, template-driven details, documents, review & preview), vendor routes
  `/vendor/products/new`, `/:id/edit`, `/studio/:draftId`; vendor list shows drafts and pending / returned changes;
  `pages/admin/AdminCatalogue.js` (changes to review with a live-vs-proposed diff, new products, drafts, add for a vendor).

## Phase 5 — granular vendor staff permissions

- `vendor_staff.PERMISSION_INFO` (18 permissions: module, label, description, risk), `LEGACY_IMPLIES` (old coarse permissions
  imply the new ones), `effective_permissions`, `PRESETS` (12 new least-privilege presets + the 5 originals, two of them now marked
  older), `PRESET_INFO`, `FULFILMENT_PERMISSION`, `member_can` / `require_member_permission`. Rules may name one permission or a
  tuple (any of); handler-level checks for fulfilment steps and studio create / edit.
- Direct product create / change / import now need `products.submit` (they send products to review); listing / archive need
  `products.archive`; stock adjustments `inventory.adjust`; CSV downloads `reports.export` / `finance.export`.
- `GET /api/vendor/staff` adds `permission_info`, `preset_info`, `preset_effective`; `/vendor/me` returns effective permissions.
- `VendorStaff.js`: grouped permission picker with descriptions and risk badges, "what this role can do" preview, high-risk
  warning; older presets hidden from new invitations.
- Docs: `ROLE_PERMISSION_MATRIX.md`, `PRODUCT_INFORMATION_MANAGEMENT_SPEC.md`, `FINANCIAL_STATE_MACHINE.md`,
  `MARKETPLACE_MODULE_COMPLETION_MATRIX.md`, `KNOWN_GAPS_AND_RISKS.md`, `PRODUCTION_READINESS_CHECKLIST.md`.

## Found and fixed along the way
- Public product API returned the whole product document, exposing vendor compliance documents (pre-existing) and, after Phase 4,
  would have exposed pending revisions: shop endpoints now use `P_SHOP`.
- Admin revision panel overflowed at 390 px (grid item without `min-w-0`).
- A same-checker immediate retake of an `approving` approval (first C-18 attempt) let concurrent clicks all run the executor; now
  only stale claims can be taken over.

## Test status (latest, 2026-11-21)
Full regression: 57 suites, 1,247 passed, 0 failed. New suites: `test_batch12_remediation` (26), `test_pim_batch12` (11),
`test_staff_permissions_batch12` (20). Script tests 2/2 PASS. Live HTTP suites not run.

---

# Batch 13 (2026-11-23)

Baseline re-verified independently before starting: 57 suites, 1,247 passed, 0 failed (matches the Batch 12 report). New checkpoint of
the uncommitted work: `~/home-genie-checkpoints/hg-20261123-1122-batch12-worktree.tar.gz` (61 files). No other session was running.

## Phase 7 — address book and wishlist (`customer_routes.py`)
Address book with server validation, per-account isolation, single default pointer (race-free), soft delete, checkout by
`address_id` copied into the order as a snapshot; typed checkout addresses are now validated (10-digit mobile, 6-digit PIN, lengths,
no `<>`). Wishlist unique per account / product / option, live state (available / choose option / out of stock / unavailable),
honest price-change indicator (no alerts), only products on sale. Screens: Addresses, checkout picker, Wishlist, heart button.
Spec: `CUSTOMER_ADDRESS_AND_WISHLIST_SPEC.md`. Tests: `test_customer_batch13` (10).

## Phase 8 — HomeGenie dashboard metrics, HG-03 (`homegenie_metrics.py`)
Traced every old figure (UTC days, gross commission ignoring reversals, `paid`-only sales, own purchases as "orders"). New metrics
endpoint with written definitions (IST ranges, paise, one order once), daily trend that sums to the totals, held reasons from the
finance rule, attributed orders server-paged with the customer's first name only. Dashboard UI replaced the old tiles / 7-day chart.
Spec: `HOMEGENIE_DASHBOARD_METRICS.md`. Tests: `test_homegenie_metrics_b13` (7: reconciliation, IST boundaries, trend sums, reasons,
paging and masking, privacy, a real attributed order through the API).

## Phase 9 — admin order operations, ADM-06 (`admin_order_ops.py`)
Paged / filtered / sorted list, audited masked CSV export (not support), one order detail with every source and each vendor's part
separately; status change now records a reason. Spec: `ADMIN_ORDER_OPERATIONS_SPEC.md`. Tests: `test_admin_order_ops_b13` (5).

## Phase 10 — merchandising (`merchandising.py`)
Banners, collections, featured products / categories, new arrivals, real bestsellers; draft / publish / unpublish / delete, dates
evaluated at read time, ordering, preview, audit; only products on sale and in stock are shown; internal links and storage images only.
Spec: `MARKETPLACE_MERCHANDISING_SPEC.md`. Tests in `test_discovery_merch_b13`.

## Phase 11 — discovery (`discovery.py`)
Server-side search (weighted text index), filters (category, sub-category, brand, price, stock, attributes), sorting, paging,
suggestions, facets, related products, recently viewed by id. `db_indexes` learned to compare text indexes by weights.
Tests: `test_discovery_merch_b13` (11, including query-plan checks for TEXT / IXSCAN).

## Fixes found along the way
- `log_audit` recorded the leftmost (forgeable) `X-Forwarded-For`; it now uses the hardened `client_ip`.
- Admin order list had no paging / masking (fixed by the new endpoints; the old list stays for the payment-exception workflows).

## The seven server-dependent suites (disposable server `hg_b13_live_test`, `~/.cache/hg-test/live/run_live.sh`)
| Suite | Before | After | Classification of each change |
|---|---|---|---|
| test_regrequest_flow | 21/22 | **22/22** | obsolete expectation: category "Herbal" is not one of the four owner-locked pillars |
| test_it11_emailless | 3/3 (SMS off) | **3/3** | — (registration with SMS on correctly needs a code, SEC-05) |
| test_otp_auth | 27/31 | **31/31** | obsolete: admin via member login (SEC-11); environment: the suite sends > 20 OTPs from one IP, so the test server runs with `RATE_LIMIT_SCALE=5` (code unchanged) |
| test_health_dashboard | 3/8 | **8/8** | environment: internal health URL now configurable (`TEST_INTERNAL_HEALTH_URL`); missing test data: demo wallet 500/500/1000 seeded in the test DB; obsolete: admin via member login |
| test_production_hardening | 4/11 | **7 passed, 4 skipped** | obsolete: approval queue removed (registration activates at once), admin OTP gets the generic answer (anti-enumeration), ₹100-referral assertion inverted to "recruiting pays nobody" (owner rule: no recruitment earnings); **retired with a written reason**: 20 %/12 % purchase-level depth commission and the withdrawal flow built on it (S-7; covered in-process) |
| test_upi_adminlogin | 7/15 | **13 passed, 2 skipped** | obsolete: admin via member login; UPI confirmation needs the exact amount (Batch 1); missing test data: activation product retired → any product on sale; **environment skip**: card checkout without gateway credentials (live credentials are forbidden in tests) |
| test_cycle9_upi_ref | 5/12 | **12/12** | obsolete: admin via member login; exact amount required |
No genuine application defect was found by these suites in Batch 13. Skips are explicit and give their reason.

---
# Programme 01 — money and data integrity (2026-11-23)
Baseline `main` @ `d31cb74` (= `origin/main`). Checkpoints: `~/home-genie-checkpoints/hg-20261123-1621-pre-programme01-worktree.tar.gz`
(Programme 00 docs), `hg-20261123-1753-programme01-worktree.tar.gz` (mid-programme working tree). Nothing staged / committed / pushed.
A second Claude session (home-genie-5f) asked about ownership mid-programme; it stayed read-only throughout.

## Baseline (clean export of d31cb74, isolated test MongoDB)
62 suites, 1,290 passed, 2 failed (`test_vendor_foundation`: state "RJ"), 0 skipped. (An earlier baseline attempt was stopped because it
ran against files already being edited; it was re-run on a `git archive` export.)

## What was built (details: PROGRAMME_01_TECHNICAL_SPECIFICATIONS.md)
- New modules: `money_guard.py` (B-004), `order_completion.py` (B-003), `sweeps.py` (B-005), `order_protection.py` (B-006),
  `scripts/programme01_reconcile.py` (report-only by default).
- Changed: `vendor_onboarding`, `vendor_routes` (B-008, B-001), `returns_routes` (B-001, B-002, B-005), `shop_routes` (B-002, B-003,
  B-006), `eligibility`, `financial_ops` (B-001), `ledger`, `commission`, `finance_routes`, `cron_routes`, `stock` (B-005, B-006),
  `payment_events` (B-003, B-004), `core`, `db_indexes`, `vendor_lifecycle`, `server` (B-004), `governance_routes`, `storage`,
  `merchandising` (B-009); frontend `ImageInput`, `AdminMerchandising`, `ProductStudio` (B-009), `AdminOperations` (status display).

## Existing tests changed (each with a comment in the file; no assertion weakened)
- `test_batch12_remediation`: vendor A's settlement is no longer held by vendor B's case (directive §5.3 replaces the Batch 12 rule).
- `test_crash_safe_finance` (4 places), `test_stock_recovery` (1): sweeps now isolate a failing record, so a simulated crash inside a
  sweep is observed as a failed record; the state checks after it are unchanged.
- `test_cod_route_logic` (fake database): points the shared completion at the fake and stubs the index guard (covered against MongoDB
  in `test_programme01_money_guard`).
- New `tests/conftest.py` raises the order limits only for older suites that place many orders for one test account; the Programme 01
  suite runs at the production defaults.

## Defects found by the verification itself
- Browser check: the admin product studio's Images / Documents steps crashed — a Programme 01 change used `base` outside its scope.
  Fixed (flag passed through the step context). Neither the build nor lint caught it (B-040).
- Browser check: Operations queues showed "Selling role pending" for every refund / return / settlement / ticket (pre-existing). Fixed
  with the existing `Pill`.
- Browser check: the admin signing endpoint answered 503 when Cloudinary is absent, producing a console error before the fallback;
  it now answers `{"configured": false}`.
- Pre-existing, not changed: the Operations page requests the finance approvals queue for non-finance admins (403) — B-039 / P1-08.
- Observed: after a migration in one process, other running instances refuse money writes for up to 15 s (negative cache).

## Final verification
- In-process regression: **71 suites, 1,449 passed, 0 failed, 0 skipped** (Programme 01 suites: vendor_state 34, rto 13, refund_integrity 11,
  completion 17, money_guard 13, sweeps 8, order_protection 18, admin_media 29, cross_module 14).
- Live-server suites (`~/.cache/hg-test/live/run_live.sh`): **96 passed, 6 skipped** — identical to Batch 13. Skips:
  `test_upi_adminlogin` ×2 card checkout without gateway credentials (live credentials forbidden); `test_production_hardening` ×4 retired
  pre-HOME GENIES commission model (S-7) and its dependent. `test_health_dashboard::test_register_send_otp` needs the SMS test adapter
  (passes with it on).
- Browser (throwaway `hg_p01_ui_test`, object store replaced in memory): 72 checks passed at 1366 and 390 px — vendor contact save with
  state RJ, vendor RTO order, vendor finance (both vendors), admin orders, RTO refund initiate (admin) and confirm (other finance admin),
  rejected booking shows its error and never "confirmed", merchandising and admin-studio uploads, external link refused, support /
  accounts refused; no sideways scroll, no broken images, no console errors except the documented pre-existing 403. Note: saving a
  banner with an uploaded image cannot be shown on plain-http localhost (B-041).
- Frontend production build: compiles, no warnings; frontend tests 7/7; pyflakes: no new findings vs `d31cb74`.

---
**Reconciliation 2026-11-24 (correction; entries above unchanged).** The Programme 01 statement that every repair and release job now
processes the full dataset holds for the money jobs (ledger, commission release, refund obligations, returns, settlements, completion,
prepaid / UPI expiry, dispatch alerts). Two stock-repair loops remain capped: stock-journal crash recovery (`stock.run_recovery`, 20 per
run via the expiry sweep) and the stuck-expiry self-heal (`limit`). Recorded as DEF-03 in `HOME_GENIES_REMAINING_WORK_REGISTER.md`.
Current documents: `HOME_GENIES_MASTER_ROADMAP_CURRENT.md` and companions.

---
# DEF-03 corrective package — stock recovery completeness (2026-11-24)
Baseline: `main` @ `d31cb74` = `origin/main`; working tree 32 modified + 33 untracked (Programme 00 / 01 / reconciliation work),
checkpoint `~/home-genie-checkpoints/hg-20261124-1138-pre-def03-worktree.tar.gz`. No other session active. Nothing staged / committed.

**Environment note.** The machine had restarted at 10:06; Docker Desktop and the isolated test MongoDB (`hg-test-mongo`, 127.0.0.1:27018)
were down, so the first test attempt errored at connection setup (no test ran). Docker Desktop was started and only `hg-test-mongo` was
started again; all results below were produced after that.

**Causes.** (A) `stock.run_recovery(limit=20)` → `recover_stock_txns` / `process_restock_intents`: `find(q).limit(limit)`, no order, no
checkpoint, no per-record isolation — a persistently failing record starved the rest and one exception aborted the run. (B) the
stuck-expiry self-heal in `expire_pending_online_orders`: `find(stuck).limit(limit)` with the same behaviour, releasing without
re-checking eligibility.

**Changes.** `stock.py`: `recover_stock_txns`, `process_restock_intents`, new `heal_stuck_expiries` on `sweeps.run_sweep` with a re-check
before each record; `_recover_one_txn` (the unchanged per-transaction step, extracted); compensating journal rows for abandoned committed
reservations (`_log_undo`, `abandoned_after_commit` flag on both abandon paths; `_log_movement` ignores compensating rows when checking
for the forward row); `run_recovery` / dry-run counts. `sweeps.py`: `job_failures` (record, retry, clear on success, `failures_open`),
`job_runs` (one record per non-idle run), no writes for idle runs. `cron_routes.run_maintenance(dry_run=True)` reports `stock_recovery`
and `stuck_expiries`. New test file `tests/test_def03_stock_recovery.py` (15). No existing test was changed.

**Found while testing.** The journal (`stock_movements`) did not record the give-back of an abandoned reservation that had committed
(counter right, journal −1 only) — pre-existing; corrected going forward with a compensating row; historical rows are not rewritten.
A retried self-heal that finished a release created by an earlier interrupted call reported "skipped" (count only) — the handler now
judges success by the order's unreleased lines.

**Verification.**
- Focused: `test_def03_stock_recovery` 15 passed, repeated 4 times (15/15 each).
- Affected suites before the full run: stock_recovery 25, stock_reservation 13, stock_expiry_race 39, order_lifecycle_races 36,
  returns_refunds 25, programme01_sweeps 8, programme01_order_protection 18, programme01_cross_module 14 — all passed.
- Full in-process regression: **72 suites, 1,464 passed, 0 failed, 0 skipped** (previous: 71 suites, 1,449).
- Live-server suites: **96 passed, 6 skipped** — unchanged: `test_upi_adminlogin` ×2 card checkout without gateway credentials;
  `test_production_hardening` ×4 retired pre-HOME GENIES commission model (S-7) and its dependent.
- pyflakes: no new findings vs `d31cb74`. Frontend: not changed — build and browser checks not required and not run.

**Remaining.** Historical journals of reservations rolled back before this change keep only their −1 row. `prune_stock_markers`
(housekeeping; its query shrinks as it works) keeps a 200-per-run limit. `job_runs` has no retention (no period invented).

---
# Programme 02 / W8 — frontend static analysis and build protection (2026-11-24)
(No separate Programme 02 log exists; this running log continues.) Baseline `main` @ `d31cb74`, working tree 32 modified + 34 untracked,
checkpoint `~/home-genie-checkpoints/hg-20261124-1211-pre-w8-worktree.tar.gz`. No other session. Nothing staged / committed.

**Root cause of undefined names passing the build.** CRA 5's webpack ESLint plugin (ESLint 8.57.1 inside react-scripts) uses only
`eslint-config-react-app/base` as base config — parser and environments, no correctness rules — and expects the project to extend
`react-app` (package.json `eslintConfig` or an `.eslintrc`). This project had neither; `craco.config.js` `eslint.configure` merged only the
react-hooks rules into that base. `no-undef`, `react/jsx-no-undef` and all import checks were therefore off, which is how `base` used
outside its component compiled (Programme 01 product-studio Images / Documents steps) and the Batch 13 dashboard crash before it. The
top-level ESLint 9 package needs a flat config and was never used by anything.

**Changes (frontend only).** New `frontend/.eslintrc.js` (single source; extends react-app; ES2020 globals; error / warning rules listed in
`HOME_GENIES_PROGRAMME_02_READINESS.md` W8 outcome); `craco.config.js` `eslint: { mode: "file" }` (replaces the hooks-only merge; hooks
rules still apply through react-app); new `scripts/eslint-alias-resolver.js` (resolves `@/` to `src/`, and exports-only packages through
Node); new `scripts/lint.js`, `scripts/check-build-guard.js`; package.json scripts `test:ci`, `lint`, `build:check`, `quality`
(`build` unchanged). Code fixes forced by the new errors: removed the dead earlier copies of 3 duplicated i18n keys in each language of
`src/i18n/vendorPanel.js` (6 errors); `globalThis` in `Pager.test.js` resolved by the ES2020 environment (no test change); the
`react-resizable-panels` false positive resolved by the resolver (no exception). Warnings cleaned: 8 unused named imports in
`AdminLayout.js`, `VendorLayout.js`, `ProductStudio.js`, `AdminAgreements.js`, `AdminProducts.js`, `VendorSecurity.js`.

**Proof of no behaviour change.** i18n: all 1,232 effective key / value pairs of `vendorPanel` evaluated from HEAD and from the working tree
are identical. Imports: production bundles built before / after (source maps) contain the same 1,156 modules; only the 6 edited files differ
in source, and only in their import lines; the minified bundle has the same length (variable naming differs).

**Verification.**
- `npm run build:check`: 13/13 (incl. the exact Product Studio pattern → `no-undef 'base'`).
- Real `npm run build` on a scratch copy with a fixture imported from `src/index.js`: undefined identifier → FAIL (`no-undef`); unresolved
  `@/` import → FAIL (webpack "Module not found"); invalid named import → FAIL (webpack "Attempted import error"; `import/named` also errors);
  control without fixture → PASS. Fixtures existed only in the scratch copy; the repository never contained them.
- `npm run lint`: 172 files, 0 errors, 9 warnings (classified in the remaining-work register §8). `npm run quality`: exit 0
  (lint, frontend tests 7/7 in 2 suites, guards, production build).
- Browser (throwaway API + `hg_w8_ui_test`, 1366 and 390 px): all 8 admin Product Studio steps, the Documents-step upload input after
  "Add document", admin dashboard / products / agreements / catalogue, vendor dashboard / security / profile / products — 74/74, no error
  boundary, no page or console errors, no sideways scroll; approved design unchanged.
- Backend: not changed (0 non-frontend files differ from the checkpoint); backend tests not re-run for W8 (no backend change).

**Not done (recorded).** Repository-tracked browser smoke suite (readiness W8 criterion c) — VG-01. 9 lint warnings remain. No dependency
was added or upgraded (W6 not started); the unused top-level ESLint 9 devDependency is left for W6 to decide.

---
# Programme 02 / W6 — dependency security audit and controlled upgrades (2026-11-24)
Baseline `main` @ `d31cb74` (Programme 00 / 01 / DEF-03 / W8 work uncommitted); checkpoint
`~/home-genie-checkpoints/hg-20261124-1229-pre-w6-worktree.tar.gz`. No other session. Nothing staged / committed / pushed / deployed.
Full report: `HOME_GENIES_DEPENDENCY_AUDIT_W6.md`.

**Audit.** `pip-audit` 2.10.1 (PyPI + OSV, `--no-deps` on exact pins) on `backend/requirements.txt` (minus the private
`emergentintegrations` and the `litellm` wheel URL) and on a fresh resolution of the production set (`deploy/vercel-api/requirements.txt`
+ stripe = `pyproject.toml`); `npm audit` on `frontend/package-lock.json`. Production set: starlette, PyJWT (1 critical), pymongo,
dnspython. Emergent set: those plus certifi (critical), urllib3, aiohttp, multidict, pyasn1, black, pillow, python-jose, ecdsa, filelock,
oauthlib. npm: 38 findings (22 high) — axios, react-router, zod (direct, runtime / unused) and the CRA toolchain.

**Changes.**
- `backend/pyproject.toml`, `deploy/vercel-api/requirements.txt`, `backend/requirements.txt`: fastapi 0.133.1, starlette 1.3.1, PyJWT 2.15.0,
  pymongo 4.18.3, motor 3.7.1, dnspython 2.9.2; `requirements.txt` only: certifi 2026.10.18, urllib3 2.8.0, aiohttp 3.14.4, multidict 6.9.1,
  yarl 1.25.1, pyasn1 0.6.5, black 26.10.1. Smallest versions that clear the advisories; exact pins; `pip check` clean.
- `backend/core.py`: `uri_parser.parse_uri(mongo_url)` inside the existing import-time `try` (PyMongo 4.18 no longer resolves
  `mongodb+srv` while constructing the client). Found by the candidate regression: `test_vercel_cors_dbdown::
  test_unresolvable_srv_host_gives_503_not_import_crash` failed (generic 503 instead of the `MONGO_URL_INVALID` diagnostic). Test unchanged;
  it passes on both PyMongo 4.6.3 and 4.18.3.
- `frontend/package.json` / `package-lock.json`: axios 1.20.0, react-router-dom 7.18.2, postcss 8.5.23, eslint 8.57.1 (was 9.23.0), removed
  zod, @eslint/js, globals; `overrides: { underscore: 1.13.8 }`; `npm audit fix` in-range transitive patches (follow-redirects, node-forge,
  body-parser, set-cookie-parser). Installed with `npm ci` from the verified lockfile; no `--force` / `--legacy-peer-deps` on any command
  (the pre-existing `.npmrc` `legacy-peer-deps=true` applies to every install; a strict-peer dry run shows W6 needs no peer override).

**Correction to the W8 entry above.** W8 recorded the top-level ESLint 9 as "never used by anything". It is used: `eslint-plugin-import`
`require`s `eslint` from the top-level `node_modules` (export maps for `import/named`, `no-unused-modules`); removing it crashed `npm run
lint` and `build:check`. It is now pinned to the engine react-scripts runs (8.57.1); lint output and all 13 guard results are identical to W8.

**Not changed (recorded).** yarn `packageManager` / `resolutions` (ignored by npm; W6-R3); Emergent-only packages with major-only or no fix
(W6-R2, D-10); CRA toolchain findings (W6-R1, decision W6-01). VG-01 stays open.

**Verification.**
- **Backend lint:** pyflakes over `backend/*.py` — 32 findings, identical to the `d31cb74` and DEF-03 baselines (0 new).
- **Candidate regression** (scratch venv with the new pins, before the `core.py` shim): 72 suites, 1,463 passed, 1 failed
  (`test_vercel_cors_dbdown::test_unresolvable_srv_host_gives_503_not_import_crash`) → root cause §5.1 of the audit report → shim.
- **Final full in-process regression** (real test venv upgraded to the new pins; `pip freeze` identical to the verified candidate venv;
  pre-W6 freeze saved for rollback): **72 suites, 1,464 passed, 0 failed, 0 skipped** — same count as the DEF-03 baseline. Integration areas
  covered through the HTTP stack: auth / JWT (≈ 35 suites), payments and webhooks (≈ 50), database and money paths (all), uploads
  (multipart in `test_programme01_admin_media`, `test_programme01_cross_module`), jobs / sweeps / cron (≈ 70); 67 suites start the app with
  `with TestClient` (startup hooks run).
- **Upload limits under Starlette 1.3.1** (scratch test reusing the admin-media fixtures): 1.5 MB and 4.9 MB images accepted (200);
  5 MB + 16 B refused with the application's own "Maximum size is 5 MB" (not a parser error).
- **Live-server suites** (uvicorn, `~/.cache/hg-test/live/run_live.sh`, disposable DB): **96 passed, 6 skipped** — identical to Programme 01
  (`test_health_dashboard` counted from the SMS-on run as before; its `test_register_send_otp` needs the SMS test adapter and fails with SMS
  off exactly as in the pre-W6 log). Every server logged "Application startup complete", "DB initialisation complete" and a clean shutdown
  → `@app.on_event` hooks run under Starlette 1.3.1 / FastAPI 0.133.1.
- **Frontend:** `npm ci` from the verified lockfile; `npm run lint` 172 files, 0 errors, 9 warnings (identical to W8); `npm run test:ci`
  7/7 in 2 suites; `npm run build:check` 13/13; `npm run quality` exit 0; production build `main.adee6fad.js` 551.17 kB gzip (repo build
  byte-identical to the verified scratch build). Bundle: 1,159 modules (W8: 1,156).
- **W8 compatibility:** real `craco build` on a scratch copy with injected fixtures fails for an undefined name (`no-undef`), an unresolved
  `@/` import ("Module not found"), an invalid named re-export and an invalid named import ("Attempted import error"); `import/named` is
  still proven by the `build:check` guard; standalone lint and the build use the same `.eslintrc.js` and now the same single ESLint 8.57.1.
  Fixtures existed only in the scratch copy.
- **Browser** (throwaway API on the upgraded backend + `hg_w6_ui_test`, production bundle with axios 1.20.0 / react-router 7.18.2, 1366 and
  390 px): **64/64** — UI logins (customer, HomeGenie member, admin) issuing JWTs, protected-route redirects, catch-all route, history back,
  deep-link reload, axios 401 error path (message shown, no token, no crash), 7 customer, 5 member and 8 admin screens; no page errors, no
  5xx, no sideways scroll; the only 4xx / console error is the deliberate wrong-password 401. Approved design unchanged (screenshots
  reviewed). One check was corrected during the run: at 390 px each page `h1` is hidden by design (`index.css:318-320`), so text is now
  read from the DOM rather than the visible text.
- **Audit after:** production backend 0 advisories (PyPI and OSV); Emergent set 5 packages; npm 26 (13 high, 4 moderate, 9 low; none in
  the bundle).

---
# Programme 02 / W5 — database index, integrity and repair audit (2026-11-24)
Baseline `main` @ `d31cb74` (Programme 00 / 01 / DEF-03 / W8 / W6 work uncommitted); checkpoint
`~/home-genie-checkpoints/hg-20261124-1320-pre-w5-worktree.tar.gz`. No other session. Nothing staged / committed / pushed / deployed.
No production data read, no production migration run. Full report: `HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md`.

**Method.** Read `db_indexes.py`, `money_guard.py`, `sweeps.py`, `stock.py`, `cron_routes.py`, the migration (`vendor_lifecycle.migrate`)
and every sweep; parsed every `db.<collection>.<method>` call (1,042) with Python's AST and matched filters / sorts to the index
specs; measured sweep selections with `explain` executionStats on a throwaway 30,000-order dataset. Every defect below was reproduced
by a test (or a measurement) **before** it was changed.

**Defects found and fixed.**
1. `db_indexes.plan()` counted an identical index under another name as present while `money_guard` refused it → the migration never
   repaired a money area the guard kept blocked. `plan()` now uses the guard's rule (own name + exact definition).
2. Collation and text-index language were not part of the compared definition (a case-insensitive unique index passed as exact).
3. Duplicate counting grouped multikey keys by the whole array and treated missing ≠ null; one shared pipeline now serves the
   migration and `money_guard.duplicate_report` (arrays unwound, missing = null, documents counted once).
4. `prune_stock_markers`: `find().limit(200)` once a day — at most 200 per day, and skipped (unbound) records could fill every batch
   for good. Now a resumable `run_sweep` (same selection and skip rule).
5. `sweeps.run_sweep` loaded at most 1,000 open failures, so later successes never cleared the rest.
6. Races (tests reproduced them): a double KYC submission created 3 records for one member; concurrent first use of a sequence issued
   the same number 3 times (invoice / refund / settlement / ticket numbers have no unique index of their own); one cron delivery id
   recorded 6 runs. Unique `kyc_records_user_unique` (replaces the non-unique index via LEGACY), `counters_id_unique`,
   `cron_runs_run_id_unique`; the KYC submit turns a lost race into an update, the admin KYC create answers 409, the cron POST answers
   "duplicate".
7. Hot paths without an index — notably **every member login scanned all users** (the e-mail `$or` branch cannot use the partial unique
   index) and **six repair sweeps that run inside checkout / order views / the returns page examined every order or journal row** with
   nothing to repair (~210,000 documents per checkout at 30,000 orders). 37 justified query indexes; selections unchanged.

**Added.** `db_indexes.dry_run()` (creates / refusals with duplicate counts / replacements / conflicts), `spec_version()`,
`index_migrations` run records with interrupted-run detection (in `vendor_lifecycle.migrate`), `retention.py` (read-only TTL
eligibility; no periods), `scripts/db_maintenance_report.py` (read-only). No TTL created or changed; nothing deleted.

**Not changed (recorded).** Production migration (P1-01); retention periods (P0-05); capped dashboard / report figures (W4 / P05);
stale `processing` webhook claims (P03); sweep lease (handlers are claim-based). Residual items W5-R1…W5-R6; decision W5-01.

**Verification.**
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

---
# Programme 02 / W4 — reports, exports and sensitive-data protection (2026-11-24)
Baseline `main` @ `d31cb74` (Programme 00 / 01 / DEF-03 / W8 / W6 / W5 work uncommitted); checkpoint
`~/home-genie-checkpoints/hg-20261124-1516-pre-w4-worktree.tar.gz`. No other session. Nothing staged / committed / pushed / deployed.
No production data read. Full report: `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md`. **D-16 not decided; no access added.**

**Method.** All 296 routes extracted from code (AST); 58 report-type GET routes and all five CSV exports read; every field that leaves
the server classified (identity, financial, personal, business). Nine defects reproduced against the pre-W4 code (HEAD + checkpoint,
throwaway DB) before changing anything: support_admin exported the payment report; accounts_admin listed identity-document links;
full mobile / e-mail in the registrations CSV; payment session id in the payments report; leading-space formula active; product
category formula raw; vendor statement accepted start after end; report / statement exports unaudited; exports cacheable.

**Changes.** New `exports.py` (one formula rule `csv_cell`, `csv_text`, `csv_response` no-store + `X-Export-Id`, `date_bounds`, `check_size`
413, `audit_export` with redacted filters, masks). Legacy reports: mobile / e-mail / session id masked for every role in screen and CSV;
money printed from integer paise; dates; `total` / `truncated`; `report_viewed` audit; CSV export follows `EXPORT_ROLES` (support refused,
interim D16-W4-1), > 5,000 refused, failure path audited. Order CSV: > 5,000 refused, all cells sanitised, `audit_export` (search text
redacted; the legacy `orders_exported` record kept). Vendor statement / current report / catalogue CSVs: audited (scope
`vendor:<id>`), size limits, start ≤ end, no-store. `catalogue.csv_safe` / `finance_routes._csv_safe` delegate to `csv_cell`. Frontend: `AdminReports.js` (Export only for export roles, error state instead of
"No data", date filters, row count / truncation / masked note, failure toast), `kit.downloadCsv` (server's refusal message shown;
nothing saved on failure).

**Tried and reverted.** Limiting `GET /api/admin/vendors/{id}/documents` to the document reviewers (accounts_admin refused) failed
`test_vendor_authority::test_accounts_admin_cannot_review_documents` in the full regression: that test states accounts_admin may still READ
the listing. It is therefore an authorised, tested access — reverted (comment only remains) and recorded as D-16 sub-question D16-W4-6.

**Existing tests changed.** `test_security_batch0`: `test_no_report_or_export_leaks_credentials_or_aadhaar` and
`test_csv_export_neutralises_formulas` exported as support_admin; their export calls now use the super admin (all assertions kept) and the
first also asserts support_admin is refused. No other existing test changed.

**Verification.**
- **New suite** `test_w4_export_security`: **63 passed** (access control 1-8, masking 9-15, export integrity 16-25, regression 26-30,
  money from paise and report totals 31-32).
- **Existing suites run alongside:** test_admin_order_ops_b13 5, test_vendor_reports 15, test_vendor_staff 11, test_governance_security 16,
  test_vendor_onboarding 46, test_admin_screens_backend 3, test_security_batch0 63 (2 export calls moved to the super admin, +1 support
  refusal assertion), test_staff_permissions_batch12 20, test_identity_batch4 9, test_catalogue_batch3 24, test_vendor_foundation 16,
  test_e2e_vendor_integration 3, test_homegenie_metrics_b13 7, test_vendor_authority 78 — all passed.
- **Full in-process regression** (final code; file hashes unchanged during the run): **74 suites, 1,585 passed, 0 failed, 0 skipped,
  0 errors, 0 not run** (1,522 before W4 + 63 new). An earlier full run (1,584 passed, 1 failed) caught the documents-listing
  restriction breaking `test_vendor_authority`; that change was reverted (D16-W4-6) and the full run repeated.
- **Live-server suites:** **96 passed, 6 skipped** (unchanged).
- **Backend lint:** pyflakes 0 new findings against the baseline.
- **Frontend:** `npm run quality` exit 0 — lint 0 errors / 9 existing warnings, unit tests 7/7, build guards 13/13, production build.
- **Browser** (throwaway API + `hg_w4_ui_test`, 1366 and 390 px): **50/50** — Export shown only to export roles (super / accounts yes,
  support no); contact masked on screen and in the downloaded CSV; sales money exact from paise; an invalid range shows an error, not
  "No data"; a refused order export shows the server's message and downloads nothing; vendor statement download (own rows, formula
  neutralised); no page errors, no sideways scroll; approved design unchanged (screenshots reviewed).

---
# Autonomous cycle (2026-11-24): application audit, Programme 02 W7 and W1 (CSP)
Baseline `main` @ `d31cb74` (= origin; Programme 00 / 01 / DEF-03 / W8 / W6 / W5 / W4 work uncommitted); backend files identical to the W4
final regression (74 suites / 1,585 passed). Checkpoint `~/home-genie-checkpoints/hg-20261124-1701-pre-cycle-p02-worktree.tar.gz`
(98 files). One session, no other process. Nothing staged / committed / pushed / deployed; no production access.

**Application audit (reconciliation evidence).** Static map of every frontend API call against every backend route: 271 calls, 296
routes, **0 calls to a missing endpoint**; 41 routes without an auth dependency, all intentionally public (sign-in / registration /
password reset, catalogue, signed webhooks, secret-checked cron, health, token invitations, payment status — L14 known); 48 guarded routes
no screen calls (finance diagnostics N15, admin finance screens B-030, superseded legacy product endpoints, owner-invitation admin
endpoints, customer return ship / cancel, mobile change, badge) — all already recorded as "backend complete, frontend incomplete" or
deprecated. Browser crawl of every admin page and Operations tab as each of the 4 admin roles: 16 refused requests (W7 below).

**W7 — Operations Approvals / role-aware admin UI.** Found: admin 6, accounts 3, support 7 refused requests on page load (Operations
approvals and duplicate payments requested before the role check; Benefits promised a read-only view the server refuses; payment events,
activations, vendor applications, team opened by address) and actions the server refuses (COD collect, merchandising editing, catalogue
decisions, add-for-vendor). Done, frontend only: `src/lib/roles.js` (the server's role sets, each naming its backend constant;
`tests/test_w7_role_sets_in_sync.py` fails on drift), `src/components/RoleGate.js` (note instead of the page, page not mounted),
`App.js` routes, `AdminOperations.js` (`useList(..., enabled)`), `AdminOrders.js`, `AdminMerchandising.js`, `AdminCatalogue.js`. No server
rule changed. P1-08 (explain vs hide) stays open; the existing "explain" form is kept.

**W1 — criterion (d) only.** `frontend/vercel.json` security headers (strict CSP, frame-ancestors / X-Frame-Options, nosniff, referrer,
permissions) and `npm run build` with `INLINE_RUNTIME_CHUNK=false` (no inline script in `index.html`). `src/securityHeaders.test.js`.
Second factor, recovery, admin session lifetime wait for P0-06; cookie-based tokens for D-10.

**Defects in my own checks, corrected before relying on them:** a login wait matched the login URL itself; the COD button lives on the
payment-exceptions page; the framing test first ran inside a page that already had our CSP, and then counted Chrome's error page as
content — both fixed so the test proves `frame-ancestors`.

**Verification.**
- **Backend:** full in-process regression **75 suites, 1,587 passed, 0 failed, 0 skipped, 0 errors, 0 not run** (1,585 before + 2 new in
  `test_w7_role_sets_in_sync`); backend application code unchanged this cycle (file hashes checked). Live-server suites **96 passed,
  6 skipped** (unchanged). Backend lint: pyflakes clean on the new test.
- **Frontend:** `npm run quality` exit 0 — lint 176 files, 0 errors, 9 existing warnings; unit tests **15 passed in 4 suites** (new:
  `RoleGate.test.js` 4, `securityHeaders.test.js` 4); build guards 13/13; production build (no inline script in `index.html`).
- **Browser (throwaway API + `hg_cycle_ui_test`):** 4-role admin crawl (22 pages + 8 Operations tabs) before: 16 refused requests; after:
  **0** (repeated under the production headers); W7 role-by-role checks **112/112** at 1366 and 390 px (repeated under the production
  headers, 112/112); CSP checks **38/38** at 1366 and 390 px; design unchanged (screenshots reviewed).
