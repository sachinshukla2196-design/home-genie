# HOME GENIES — Master implementation backlog (Programme 00)

Baseline `main` @ `d31cb74`. Every item cites the companion audit document that holds the evidence (MA = master architecture,
MM = module matrix, FB = frontend/backend map, DB = database, PM = permission matrix, IR = integration register, WF = workflow
audit, FA = financial audit, SR = security & reliability, MS = Marketing Studio). "Verified" = re-checked in code by the lead
architect in this programme; others are reviewer findings from code reading (not runtime-probed).

Priority: **P0** financial integrity / security / data-loss risk · **P1** core business workflow incomplete · **P2** important
operational capability · **P3** enhancement. "Decision" = blocked by an owner decision (OWNER_DECISION_REGISTER).

## P0
| ID | Gap | Evidence | Depends on |
|---|---|---|---|
| B-001 | **Prepaid order returned to origin (RTO) has no financial effect**: `returned_to_origin` not in `RESTOCK_ON`, so no `refund_due`, no refund case, no sale reversal; on a multi-vendor order eligibility counts the RTO group as "not supplied" and the rest (incl. commission on the RTO goods) becomes payable. Customer has no way back to the money. **Verified** (`vendor_routes.py:45`, `eligibility.py:42`). | WF, FA | — |
| B-002 | **Refund case can be confirmed with nothing booked**: `reverse_order_financials` may return `rejected`/0 (concurrent confirmations on one order, retry after another refund); `refund_case_action` treats it as confirmed (no clawback, no vendor share, payouts released). | FA (`shop_routes` 540-541, 634-637; `returns_routes` 330-338) | — |
| B-003 | **Commission plan lost after a crash on most payment paths**: order claimed paid first; sales / commission written after; a crash leaves no plan and every retry returns "already paid". Only the Razorpay webhook re-runs completion (`payment_events.complete_paid_order`); Stripe, Razorpay verify, UPI, manual, COD do not; `distribution_audit` does not detect it. | FA | — |
| B-004 | **Money de-duplication depends on indexes the app never creates**; startup only logs missing indexes. Until `scripts/vendor_foundation_migrate.py --apply` has run in production, duplicate ledger / wallet / refund / settlement / webhook effects are possible. **Verified** (`server._init_db` → `db_indexes.check_missing`). Production state unknown. | DB, SR, FA | owner: run + confirm migration |

## P1
| ID | Gap | Evidence | Depends on |
|---|---|---|---|
| B-005 | `reconcile_ledger` only scans the 500 oldest paid orders (no cursor) — repairs silently stop at scale. **Verified** (`ledger.py:163-168`). Similar starvation: commission release 5,000 cap, `ensure_cases` 200. | FA | — |
| B-006 | Unpaid COD (and any) orders hold stock indefinitely; `POST /api/orders` has no rate limit or open-order cap; expiry sweeps only online orders. **Verified** (`shop_routes.create_order`, `stock.expire_pending_online_orders`). | SR | — |
| B-007 | Plaintext Aadhaar / PAN / bank numbers in `users`, `registration_requests`, `kyc_records`, `vendors`, `vendor_change_requests`; no retention / anonymisation; privacy page promises deletion the code does not do. | SR, DB, MM | decision: retention policy |
| B-008 | **Regression on main (Batch 14)**: vendor contact validation rejects stored state codes (e.g. `"RJ"`), so approved vendors cannot save contact changes; 2 failing tests in `test_vendor_foundation`. **Verified by test run.** | MA §5 | — |
| B-009 | Admin image upload always 403: `ImageInput` calls `/api/vendor/uploads/sign` (`require_approved_vendor`) from merchandising and the admin product studio. **Verified.** | FB | — |
| B-010 | Admin accounts: password-only, 7-day tokens in `localStorage`, lockout per IP + username (distributed guessing unbounded), no frontend CSP / frame protection. | SR | decision: admin 2FA method |
| B-011 | Google sign-in / recovery trust `demobackend.emergentagent.com` to state the authenticated e-mail. **Verified** (`auth_routes.py:390`). | SR, IR | decision: identity provider |
| B-012 | Commission rates (30 / 10 / 5) are runtime-editable by one finance admin (`admin_update_settings`) — conflicts with locked decisions S-4 / S-7. | FA | decision |
| B-013 | Single-person money actions: manual payment, UPI confirm, COD confirm, vendor bank-change approval (applied directly), commission release, closing a refund case "without refund"; confirmer is not checked against the buyer. | FA, PM | decisions D-03 + S-4 scope |
| B-014 | Customer support tickets do not exist (vendor tickets do); customer-facing errors say "contact support" with no channel. | MM, WF | — |
| B-015 | Stripe path: no amount / currency check, no `webhook_events` record, no completion retry, `status=="complete"` treated as paid, unauthenticated status poll triggers processing; default "Place order" uses Stripe, fails 503 when unconfigured and leaves a stock-holding pending order. | FA, SR, FB | decision: which gateways at launch |
| B-016 | Product CSV import (VEN-04) bypasses the pending-revision rule, hides live approved products, lacks the new PIM fields. | MM | — |
| B-017 | No backups / restore tooling, no error monitoring, no cron / uptime alerting in the repo. | SR, MA | owner: hosting choices |
| B-018 | GST tax invoice per seller, TCS, e-invoicing not implemented (browser print of the order page only). | IR, MM | decision: tax adviser (D-09, D-15) |
| B-019 | Legacy admin reports export members' full mobile / e-mail to any admin role (incl. support) without an audit entry; float money; no date filter; row caps. | SR, MM | — |

## P2
| ID | Gap | Evidence |
|---|---|---|
| B-020 | Unrecorded money owed to customers: UPI paid after claim expiry, UPI + gateway double payment, gateway events rejected for mismatch — no refund-due record. | FA |
| B-021 | Refund cases can promise more than is refundable (return / customer-cancel / late-payment cases do not net other open cases). | FA |
| B-022 | Withdrawal request not crash-safe (wallet moved before the request record exists). | FA |
| B-023 | Settlements are bare amounts (not linked to orders or a bank snapshot); a vendor approved with missing documents can be paid. | FA |
| B-024 | Vendor platform commission charged without an accepted agreement; backdated agreements apply retroactively via reconcile; never returned on refunds (policy undefined). | FA — decision |
| B-025 | Missing indexes on hot paths: `orders.user_id`, `files.storage_path`, `audit_logs` (none), `payment_transactions.order_id`, `commissions.order_id/status`, `refund_cases`/`return_cases` `id`/`order_id`, `password_reset_tokens.token_hash`; non-unique where unique needed (`kyc_records.user_id`, `cron_runs.run_id`, `counters.id`); no TTL on `otp_sessions`, `login_attempts`, `password_reset_tokens`. | DB |
| B-026 | Admin role breadth beyond the documented matrix: support/admin can change platform product prices and stock, verify KYC alone, mark platform orders delivered (starts commission clock), decide returns; accounts-admin masking bypassed by `/admin/orders`, `/admin/users`, `/admin/refund-queue`. | PM, SR — decisions D-04, D-06, D-16 |
| B-027 | Delivery proof (VEN-06) — "delivered" is a vendor note only. | MM — decision D-04 |
| B-028 | No transactional e-mail / SMS for orders, payments, shipping, refunds; notification preferences not implemented. | MM, IR |
| B-029 | Customer returns: no return-shipment tracking or withdraw in the UI; photos never sent. "Pay now" on a pending order opens an empty checkout. | MM, WF |
| B-030 | Admin screens missing for vendor ledger / vendor adjustments (maker side), commission administration, finance reports; audit-log viewer capped at 500 with no filters; admin user list unpaged. | MM, FB |
| B-031 | Payment-exceptions screen loads only the newest 1,000 orders. | FA |
| B-032 | Dependency currency: FastAPI 0.110.1 / Starlette 0.37.2 likely affected by published Starlette advisories — run `pip-audit` / `npm audit` and upgrade in a controlled batch. | SR |
| B-033 | Environment hygiene: `deploy/ENVIRONMENT.md` misses `CLOUDINARY_*`, `FRONTEND_PUBLIC_URL`, `TRUSTED_PROXY_HOPS`, `RATE_LIMIT_SCALE`, `SMS_TEST_ADAPTER` (must never be set in production) and the second cron; Preview may hit the production API; stale `deploy/vercel-api/` copy. | IR, SR, MA |
| B-034 | Referral page labels a sponsor-registration link "Shop with me" — misleading and against the no-recruitment rule. | MS |
| B-035 | No automated UI tests (only `Pager.test.js`); R-14 undefined-name build checking awaits approval. | MM, KNOWN_GAPS R-14 |
| B-036 | Profile photo accepts `http://` links and data URIs up to 4 MB stored in the user document. | SR |
| B-037 | Lockout and enumeration: anyone can lock a member out for 15 minutes; sign-up OTP endpoints reveal registered numbers / e-mails (Batch 11 L7, L8). | SR |
| B-038 | Batch 14 leftovers: VEN-05 profile overview has no tests; `PAYMENT_RECONCILIATION_SPEC.md` referenced but missing; Batch 14 not documented. | MM, FA |

## P3
Clawback on mixed-GST orders approximate (R-8) · UPI confirm vs expiry leftovers and concurrent different-UTR confirms (R-7) ·
wallet `applied_ops` array grows without bound · commissions report exports absent columns · checker may approve a credit to own
wallet (L4) · cart not cleared on logout · `demo_environment.py` contract check · merchandising accepts any https image URL (doc says
storage only) · advancement report open to staff with `reports.read` (doc says owner only) · stock CSV import needs `products.submit`.

## Marketing Studio (new module) — see MS
MVP (no external integration): server-issued short share links with click recording and link previews, multi-channel share
buttons, admin-approved caption templates, posters drawn client-side, click → order conversion by channel in the HomeGenie
dashboard. Prerequisites: B-034, owner decisions OD-M1 (public product pages), OD-M3 (prices on posters), OD-M6 (attribution
rule), OD-M8 (template approval), CORS on `/api/files`, `/s/*` rewrite, indexes, privacy-notice update. Phase 2 / 3 per MS.

## Recommended sequence (dependencies)
1. **Programme 01 — Money and data integrity (P0 + B-005, B-006, B-008, B-009):** fix RTO (B-001) and refund confirmation
   (B-002); a shared, idempotent "complete paid order" step on every payment path (B-003); make startup refuse to run money writes
   without the unique indexes, or create them (B-004, with owner confirmation of the production migration); cursor-based sweeps
   (B-005); COD / order stock hold limits (B-006); the Batch 14 regression (B-008); admin upload signing (B-009). Each with
   regression tests. No dependency on owner decisions.
2. **Programme 02 — Security hardening (B-007, B-010, B-011, B-019, B-025, B-032, B-036, B-037):** field encryption + retention
   (needs a retention decision), admin 2FA, identity provider, export audit / masking, indexes, dependency upgrades.
3. **Programme 03 — Payments and finance governance (B-012, B-013, B-015, B-020–B-024, B-031):** depends on owner decisions
   (gateways at launch, two-person scope, COD authority D-03).
4. **Programme 04 — Customer service and notifications (B-014, B-028, B-029):** support tickets, transactional messages,
   notification preferences, returns UI.
5. **Programme 05 — Operations and observability (B-017, B-030, B-033, B-035):** backups, monitoring, alerting, admin finance
   screens, environment separation, UI tests.
6. **Programme 06 — Vendor completeness (B-016, B-027, B-038):** CSV import on PIM, delivery proof (after D-04), VEN-05 tests.
7. **Programme 07 — Tax and invoicing (B-018):** after the tax adviser's decisions.
8. **Programme 08 — Marketing Studio MVP:** after B-034 and OD-M1, OD-M3, OD-M6, OD-M8.

---
## Programme 01 outcome (2026-11-23) — the ranking above is kept as written in Programme 00
| ID | Status | Notes |
|---|---|---|
| B-008 | **Done** | state codes and names accepted, free text refused, stored records untouched |
| B-001 | **Done** | historical RTO orders reported for finance (P1-02); closing such a case without refund is P1-03 |
| B-002 | **Done** | |
| B-003 | **Done** | refunded-before-plan orders are blocked for finance, not guessed |
| B-004 | **Done in code; production migration pending (P1-01)** | deploy only after the migration — money writes are refused until then |
| B-005 | **Done** | large-volume full passes span several cron runs (resumable); incremental marker suggested for Programme 05 |
| B-006 | **Done** (COD auto-expiry not invented — P1-04; limits tunable — P1-05) | |
| B-009 | **Done** | local http limitation on saving a banner with an uploaded image (production https unaffected) |

New items found during Programme 01:
| ID | Priority | Item |
|---|---|---|
| B-039 | P2 | Operations page loads the finance approvals queue for non-finance admins (403 in the console) — P1-08 |
| B-040 | P2 | The frontend build does not catch undefined names (a Programme 01 change crashed a studio step until the browser check caught it); add undefined-name linting to the build (extends B-035 / R-14) |
| B-041 | P3 | Server-side uploads on a plain-http local server return `http://` URLs that the image validator refuses (local only) |
| B-042 | P3 | Ledger reconcile does a full pass over paid orders; add an incremental "needs reconcile" marker for large volumes |

**Recommended next:** Programme 02 (security hardening) as planned. Before it — and before any deployment of Programme 01 — the owner
runs the production index migration (P1-01) after a verified backup.


---
**Reconciliation 2026-11-24 (pointer; history above unchanged).** Current, authoritative documents: `HOME_GENIES_MASTER_ROADMAP_CURRENT.md`,
`HOME_GENIES_CURRENT_MODULE_COMPLETION_MATRIX.md`, `HOME_GENIES_OWNER_DECISION_REGISTER.md`, `HOME_GENIES_PROGRAMME_02_READINESS.md`,
`HOME_GENIES_REMAINING_WORK_REGISTER.md`.
