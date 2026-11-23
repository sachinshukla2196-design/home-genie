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
