# HOME GENIES — Batch 11: Independent Pre-Release Audit

Date: 2026-11-20 · Scope: the working tree on `main` at HEAD `5b7adc2` plus all uncommitted work (Batches 0–10)
Method: code tracing; executable probes against throwaway databases on the isolated test MongoDB (`127.0.0.1:27018`); full test reproduction; a throwaway local API server and headless Chrome. Three reviewers who had not seen the implementation's own reports audited finance, security, and journeys/database. I re-checked every Critical and High item below in the code myself.
Audit only: no application code, configuration, tests or data were changed; nothing was staged, committed, pushed or deployed; no production system was contacted.

---

## A. Executive release verdict: **NOT READY**

The core order, payment, stock and ledger mechanics are sound under concurrency, and the test suite passes. However, the audit confirmed:

- **one account-takeover chain** (OTP attempt limit bypassed by parallel requests);
- **two Google-related takeover paths**;
- **several ways money becomes payable without a real delivery, or without the two-person rule** (one-step refund, admin "delivered", vendor delivering a cancelled order);
- **ledger errors on partial refunds and multi-vendor orders**.

Several of my earlier engineering-log claims are wrong (section B). The live HTTP suites still fail on stale contracts and missing fixture data. The release should go to staging only after the Phase 1–3 fixes in section I.

---

## B. Verified facts vs. claims that could not be reproduced

### Baseline (verified)
| Item | Value |
|---|---|
| Branch / HEAD | `main` / `5b7adc2ec060c4945ff813dbb8d328e5de9c812c` |
| Modified (tracked) | 66 files, +1978 / −477 lines |
| Untracked | 27 files (5 backend modules, 1 script, 10 test files, 3 docs, 8 frontend files) |
| Staged | 0 · Stashes: 0 |
| Integrity | SHA-256 of all 93 changed/untracked files taken at the start and compared at the end: **identical** |

### Claims reproduced
- 54 in-process regression suites: **1,190 passed, 0 failed** (reproduced independently).
- Script tests: `test_commission_engine` PASS, `test_cod_and_badges` PASS; `test_financial_engine_isolated` skips itself (club income was removed in 96f8719, before this work; the file is unchanged since baseline).
- Frontend production build: compiles with `CI=true` (warnings fail such a build), built into a scratch folder.
- pyflakes: 49 warnings now vs 52 at baseline; **no new warnings**. `git diff --check` clean.
- GST-inclusive maths (taxable = inclusive × 100/(100+rate), half-up; COD fee outside the commission base); UPI 24 h expiry and its races; webhook idempotency; maker-checker on wallet credits and vendor adjustments (self-approval refused, concurrent approvals execute once); one open settlement per vendor; refunds capped at the amount paid.
- The migration is idempotent, rewrites no history, and TTL fields are real BSON dates (section F).
- Every frontend API call maps to an existing backend route and method (206 direct calls checked).

### Claims that are false or overstated
| Claim (engineering log) | Reality |
|---|---|
| "Settlement: creator ≠ approver ≠ payer, always" | **False.** Only creator ≠ approver and approver ≠ payer are enforced; the creator may mark the settlement paid (`finance_routes.py` ≈ l.336–344). The test `test_settlement_two_person_rule_cannot_be_switched_off` actually asserts that the creator may pay. Owner decision 4 literally requires create ≠ approve, which holds. |
| "Refund case: initiator ≠ confirmer" | Holds only inside the case flow. Bypassed by `POST /api/admin/orders/{id}/refund` (single person) and by fail→retry, which overwrites `initiated_by` (C-4, D). |
| "One rule for both money systems… can never disagree" | **False** for COD orders after a partial refund: vendor settlement treats the order as eligible, commission release does not (F7). |
| "`delivered_at` recorded by every path that delivers" | It is also recorded by paths that do **not** deliver: admin status change, COD cash confirmation, and a vendor "delivered" step on a cancelled order (C-5). |
| "Customer: no earning, no withdrawal" | Backend: true. Frontend: customers still see Rewards, Points/"Request Withdrawal" and Share pages, which show their CU id as a share code (C-14). |
| "KYC editor cannot verify" | Only the *last* editor is blocked; an earlier editor can verify after someone else's trivial edit (D). |
| Live suites "not run" | Now run on a throwaway server. They still fail, because of stale contracts and missing fixture data (section G). |

---

## C. Critical and high-priority defects

Every item was reproduced by an executed probe unless marked *(code reading)*. Probe scripts are in the session scratchpad: `fin/`, `sec/`, `jdb/`, `ui/`.

| # | Sev. | Defect | Where | Evidence |
|---|---|---|---|---|
| C-1 | **CRITICAL** | **OTP attempt limit bypassed by parallel requests → account takeover.** Attempts are read, compared and incremented in separate steps. Affects login-OTP, forgot-password reset, contact change, change-mobile and forced change. | `providers.py:otp_verify` (≈ l.164–184) | 36 concurrent login-OTP guesses: 35×400, then 200 with a token; recorded attempts 31 (limit 5). 20 concurrent forgot-OTP resets: correct one 200; attacker's new password then logs in. I confirmed the separate read/`$inc` in the code. |
| C-2 | HIGH (deployment-dependent) | **`X-Forwarded-For` spoofing defeats every IP rate limit and the admin lockout key.** `client_ip` trusts the first XFF entry. | `core.py:client_ip` (l.450) | Rotating XFF: 65 logins with no 429; 12 wrong admin passwords then the correct one gives 200 with no lockout; 30 SMS sent where the same IP is stopped at 20. Vercel's edge is documented to overwrite XFF; **not verified for this deployment**. |
| C-3 | HIGH | **Google sign-in pre-hijack via the legacy `POST /api/auth/register`.** It sets `email_verified: True` without proof. The victim's later "Sign in with Google" lands in the attacker's account. | `auth_routes.py:register` (≈ l.288), `google_session` (≈ l.432) | Probe: the attacker registers with the victim's Gmail; the victim's Google login gives `mode: login` into the attacker's account; the attacker's password still works. The route is still mounted although the UI no longer uses it. |
| C-4 | HIGH | **Refund maker-checker bypass.** A single finance admin can refund any paid order via the one-step endpoint, and can confirm their own open case through it. | `admin_routes.py:refund_order` (l.439), `returns_routes.confirm_open_cases_for_order` | Initiate 200 → own confirm via the case route 403 → one-step refund 200, case `confirmed`, initiator = confirmer. Partial refund with no case: 200. |
| C-5 | HIGH | **Money becomes payable without a real delivery:** (a) any admin role, **including support_admin**, can set status `delivered` and start the payout clock; the customer then cannot return (fulfilment not delivered); (b) `delivered → shipped` keeps `delivered_at`; (c) a vendor "delivered" step flips an admin-**cancelled** order to delivered (unconditional update); (d) COD cash confirmation sets delivered regardless of fulfilment. | `admin_routes.update_order_status` (l.375–401), `vendor_routes.vendor_update_fulfilment` (l.803–804), `shop_routes.cod_collected` (≈ l.291), `finance_routes.resolve_cod_discrepancy` (≈ l.431), `eligibility.delivered_at` | (a) support sets delivered with fulfilment `new`: commission RELEASED by cron, vendor ₹2,000 settleable, customer return refused 400. (c) cancelled → delivered, then `payout_block` None. Confirmed in code. |
| C-6 | HIGH | **Vendor ledger goes negative** when a partial refund precedes a vendor rejection or cancellation: the sale reversal ignores earlier REFUND entries. | `ledger.py:post_sale_reversal` (l.109), `post_refund_shares` | Ledger `SALE +100000, REFUND −20000, SALE_REVERSAL −100000` gives vendor net −₹200 on an order it never fulfilled; reconcile does not repair it. |
| C-7 | HIGH (**new regression**) | **Multi-vendor order where one vendor rejects or cancels: earnings are held forever.** The order rolls to delivered only if *every* fulfilment is delivered, and eligibility requires order status delivered. | `vendor_routes.py` l.801–804, `eligibility.py` l.46–47 | Vendor A delivers, B rejects: order stays `shipped`, `payout_block = not_delivered` at +60 days. HomeGenie ₹450 and vendor A ₹1,050 never payable. Confirmed in code. |
| C-8 | HIGH (pre-existing) | **COD multi-vendor order with a rejected vendor:** the expected cash is the full total, and commission is computed on the full subtotal, including the rejected goods. | `shop_routes.cod_collected`, `commission.py` ≈ l.133 | Commission 60000 paise on base 200000 released; correct 30000. Recording the real cash amount creates a discrepancy instead. |
| C-9 | HIGH/MED | **Google account recovery ignores email ownership.** `/forgot/google` issues a reset token for an account whose email was never verified (while Google sign-in refuses the same account with 409). | `auth_routes.py:forgot_google` (≈ l.476–487) | Unverified-email account: Google login 409, but `/forgot/google` reset 200, then the new password logs in. |

### Medium
| # | Defect | Where / evidence |
|---|---|---|
| C-10 | COD commission remainder stuck forever after any partial refund (`collection_is_proven` requires `paid`); the vendor side pays out | `cod_rules.py` l.175; probe: release skipped, manual release 409 |
| C-11 | Refunding all goods on a COD order with a fee: the vendor and the HomeGenie keep part of the value (pro-rated against total incl. fee) | `ledger.post_refund_shares` l.143, `shop_routes._reverse_commission` l.584; vendor keeps ₹47.62, commission ₹13.61 stuck |
| C-12 | A plain `admin` (non-finance) controls `returns_policy.window_days`, which now decides when money is payable; 0 means immediately settleable | `returns_routes.py` `POLICY_ROLES` l.35; probe 200 → `payout_block` None |
| C-13 | Withdrawal can be approved and paid after the bank details were changed and KYC fell back to pending | `admin_routes.review_withdrawal` ≈ l.765–890; probe approve 200, mark_paid 200 |
| C-14 | Customer UI shows HomeGenie screens: dashboard "pending approval" banner, raised Rewards button, Points wallet with "Request Withdrawal", Share page offering the CU id as a share code | `AppLayout.js` l.174 (bottom Rewards not gated), `Dashboard.js` l.33–75, routes not gated; browser check at 390 px. Backend refuses correctly |
| C-15 | **Commission statement status badge is wrong on every line** ("Selling role pending", even when released): it reuses the member red/green badge | `CommissionStatement.js` l.40 → `StatusBadge.js`; screenshot at 390 px |
| C-16 | Public "Apply to sell" creates an active vendor login for any unregistered mobile or email without OTP (squatting; reaches KYC and document upload) | `vendor_applications.py` l.80–98, `vendor_onboarding.py` l.373–377 |
| C-17 | support_admin and accounts_admin can block or deactivate vendor owners (bypassing `VENDOR_ADMIN_ROLES`); vendor staff keep working after their owner is blocked | `admin_routes.block_user`/`delete_user`; `vendor_staff.authorize_staff` |
| C-18 | Financial approval stuck in `approving` after a non-HTTP crash: no retry or reject path, and not listed in the UI | `financial_approvals.py:approve` ≈ l.84–100; probe: retry 409, reject 409 |
| C-19 | COD cash confirmation is allowed for `admin`, refused for `accounts_admin`, and is single-person; this conflicts with the spirit of decision 4 (finance-only confirmation) | `cod_rules.py` l.24 `CONFIRM_ROLES` |
| C-20 | KYC: only the *last* editor is blocked from verifying; any admin role (including support) can verify | `admin_routes.review_kyc` ≈ l.709 |
| C-21 | Commission statement shows ₹0 for legacy commissions without `amount_paise` (release pays them) | `wallet_routes.py` l.41; only if `migrate_money_paise.py` was not applied in production |

### Low (summary)
- L1 Fail→retry launders the refund initiator.
- L2 A UPI confirm that loses to expiry leaves the UTR reserved and a `paid` transaction row behind.
- L3 Two concurrent UPI confirms with different UTRs both return 200 (one sale is posted).
- L4 A checker can approve a credit to their own wallet; the credit target is resolved at approval time.
- L5 Clawback is pro-rated on the gross price, not on the taxable base, for mixed-GST orders.
- L6 Admin-login accepts the password of a *blocked* admin (the token is then refused): a password oracle.
- L7 The lockout is keyed on the identifier: anyone can lock a member out for 15 minutes.
- L8 Sign-up OTP endpoints reveal registered mobile numbers and emails.
- L9 Tokens without `jti`/`exp`/`type` are accepted; a `google_signup` token used as a Bearer token gives a 500.
- L10 `POST /api/kyc` stores full PAN, Aadhaar and bank details in plaintext, from any role.
- L11 Uploads are read fully before the 5 MB check; the profile photo accepts any `http://` or SVG data URL.
- L12 Admin credit toast shows "₹undefined".
- L13 Seller-ref is cleared before payment succeeds.
- L14 A cancelled UPI-claimed order stays `claimed`.
- L15 Staff without `reports.read` land on a 403 dashboard.
- L16 Legacy orders without delivery events use `updated_at` (any edit restarts the window).
- L17 `OrderSelfService` toasts a message field the API never returns.
- L18 Customer returns have no "ship back" or "withdraw" button.
- L19 Admin products: only the four pillar categories are accepted, so legacy products in other categories cannot be edited without re-categorising *(code reading)*.

---

## D. Financial state-machine and permission audit

Roles in code: `super_admin`, `admin`, `accounts_admin`, `support_admin`, `distributor` (HomeGenie), `customer`, `vendor`, `vendor_staff`. **There is no `finance_admin` role**; "finance" means `super_admin` and `accounts_admin`.

| Workflow | Endpoints → guard | Collections | States | Verdict |
|---|---|---|---|---|
| Online payment | razorpay verify (customer, HMAC, amount), webhooks (HMAC + unique `webhook_events`), stripe status | orders, payment_transactions, webhook_events | `pending → paid` via CAS in `_process_paid_order` | Sound; replays idempotent |
| UPI claim / confirm / expiry | `POST /payments/upi-claim` (customer); `PUT /admin/payments/upi-confirm\|upi-reject/{id}` (finance) | orders, payment_references (`_id` = UTR), stock_txns | `pending → claimed → paid \| claim_expired` | Sound for races; L2, L3, L14 |
| Manual payment | `POST /admin/payments/manual` (finance) | same | → paid | Finance only; single person |
| COD | `POST /orders/{id}/cod-collected` (admin, super); `POST /admin/finance/cod-discrepancies/{id}/resolve` (finance, resolver ≠ reporter) | orders, ledger, commissions | `cod_pending → paid \| cod_discrepancy` | C-5d, C-8, C-10, C-19 |
| Duplicate capture | `GET /admin/payments/duplicates`, `POST …/{order}/refunded` (finance, single person) | orders.duplicate_payments | `refund_due → refunded` | Works; single person |
| Delivery | admin status (**any admin**), vendor fulfilment, COD confirm, COD resolve | orders.delivered_at | — | **C-5, C-7** |
| Commission release | cron `release_due_points`; `PUT /admin/commissions/{id}/status` (money admin) | commissions, wallet_transactions (unique `op_key`), wallets | `PENDING → RELEASED \| REVERSED/PARTIALLY_REVERSED` | Idempotent; eligibility input corruptible (C-5, C-7, C-10) |
| Vendor settlement | `POST /admin/finance/settlements`, `…/{sid}/action` (finance) | settlements (one open per vendor, unique partial), vendor_ledger (unique `source_key`) | `requested → approved → paid \| rejected \| failed` | Creator ≠ approver ✔, approver ≠ payer ✔, **creator = payer allowed**; concurrent approve gives `[200,400,400]`, concurrent pay gives one SETTLEMENT_PAID ✔ |
| Refunds | case flow `POST /admin/refund-cases/{id}/action` (initiate: any admin; confirm: finance, ≠ initiator); one-step `POST /admin/orders/{id}/refund` (finance, single) | refund_cases, order_refunds, ledger, commissions | `awaiting_review → initiated → confirmed \| failed → resolved` | **C-4**, L1; amounts capped ✔; concurrent confirms record once ✔ |
| Wallet credit / vendor adjustment | `POST /admin/wallet/credit`, `POST /admin/finance/vendors/{id}/adjustments` (submit) → `/admin/finance/approvals/{id}/approve\|reject` (finance, ≠ maker) | financial_approvals | `pending → approving → approved \| failed \| rejected` | Holds, including under concurrency; C-18, L4. **No other unapproved credit path found** (all writes to wallets, wallet_transactions and vendor_ledger grepped) |
| Withdrawals | request (green distributor with KYC); review (approver ≠ payer) | withdrawals, wallets | — | C-13 |
| Ledger and reversals | `post_entry` (unique `source_key`), reconcile cron | vendor_ledger | — | **C-6**, C-11, L5 |

**Bypass attempts:**
- Alternate endpoints: **found** (C-4 refund, C-5 delivery).
- Concurrency: none found; every CAS held.
- Retries: none found; idempotency keys held.
- Direct API calls by non-finance roles: refused everywhere except the delivery, COD and policy-window paths (C-5, C-12, C-19).

---

## E. Security and privacy audit

**Verified working:**
- Every inactive state (blocked, deleted, suspended staff, pending, blocked admin) gets 401 on existing tokens.
- Admins are refused on member, OTP and Google logins.
- Logout revokes the token (TTL index on `revoked_tokens`).
- `alg=none` and HS512 tokens are rejected.
- The `must_change_password` gate holds.
- Admin Team: no creation of `super_admin`, no self-action, a super admin cannot be blocked or reset.
- Password reset is limited to super/admin and cannot target equal or higher admins.
- Contact changes stay pending until confirmed.
- No `password_hash` or `env_credential_marker` appears in any response checked; admin KYC lists are masked; vendors see only their own lines' shipping fields; no IDOR found on orders, returns or KYC.
- Security headers are present on 401/404/422/500.
- The 500 response has an error id and no stack trace.
- CORS has an allow-list; an unknown origin gets no allow-origin header.

**Defects:**
- C-1, C-2, C-3, C-9 (account takeover).
- C-16, C-17, C-20.
- L6–L11.
- **Suspected** *(code reading)*:
  - Without SMS configured, an admin who resets a member's password knows the temporary password, and the forced change then needs no OTP, so the admin can take the account over (a documented trade-off).
  - A super admin can complete a contact change alone by creating a helper admin.

Permission matrix (measured): see the security probe output in the scratchpad (`sec/routes.txt`). Key rows: support_admin can block or delete vendor owners (200), verify KYC (200), set orders delivered (200), and decide returns. It cannot reset passwords, release money, confirm payments or reach the team pages.

---

## F. Database, migration and rollback assessment

- **New collections:** `revoked_tokens` (TTL), `financial_approvals` (`_id = kind:key`), `contact_change_requests`.
- **New fields (all additive):**
  - Users: `customer` role/status, `must_change_password`, `env_credential_marker`, `pending_contact_change`.
  - KYC: `version`, `last_edited_by`.
  - Orders: `prices_include_gst`, `money_version 3`, `items_total_paise`, line GST snapshots, `delivered_at`, `claimed_at`, `return_claimed`, payment status `claim_expired`.
  - Settings: `upi_claim_expiry_hours`.
- **New indexes (9 of 58 specs):** 7 non-unique (safe on any data); `webhook_events_event_unique` (unique, partial on string `event_id`); `revoked_tokens_expires` (TTL; field written as a BSON date ✔; `rate_limits.expires_at` also a date ✔).
- **Build safety:** if production holds duplicate webhook `event_id`s (possible: the old code used find-then-insert), that one index fails, is reported, and the migration continues. **Until it exists, webhook de-duplication is not guaranteed** (S3).
- **Idempotency (executed on a seeded legacy database):**
  - Dry run: 0 changes.
  - Apply #1: 53 created, legacy `email_1` swapped, 1 failure (seeded duplicate); documents touched: 1 vendor (`vendor_code` fill) and 1 counter.
  - Apply #2: nothing created, 0 documents changed.
  - After the duplicate was removed: the index was created.
  - Fresh database: 58/58.
  - A crash between dropping the legacy index and creating its replacement recovers on rerun.
- **Server startup does not create indexes;** it only logs "58 missing". The migration must run before traffic.
- **No history rewrite:** startup and scripts add no bulk updates to orders, users, ledger or commissions; `customer_role_report.py` is read-only.
- **Rollback to 5b7adc2 is NOT safe without preparation:**
  - Proven: the old refund maths over-refunds new GST-inclusive orders by 5% (110250 vs 105000 paise).
  - *(Code reading)* Revoked tokens become valid again, the forced-change and contact gates disappear, the old startup re-applies the env admin password over an in-app change, and the old `clean_user` exposes `env_credential_marker` (a bcrypt hash of the env admin secret) via `/auth/me` and `/admin/users`.
  - Pending approvals would never execute.
- **Backup requirement:** take a full `mongodump` immediately before the migration and the deploy. Treat rollback as "restore code **and** block refunds on `money_version 3` orders", or roll forward only.

---

## G. Test results

| Suite group | Result |
|---|---|
| 54 in-process suites | **1,190 passed, 0 failed** |
| Script tests | 2 PASS; `test_financial_engine_isolated` **skips itself** (feature removed before baseline) |
| Frontend build | Compiled successfully (`CI=true`) |
| Static | pyflakes no new warnings; `compileall` OK; `git diff --check` clean |
| Live suite `test_regrequest_flow` | 21 passed, **1 failed** (category "Herbal" is not one of the four pillars: stale test) |
| Live `test_it11_emailless` | 3 passed (SMS adapter off) |
| Live `test_otp_auth` | 27 passed, **4 failed**: 3 from the per-IP OTP limit of 20/h added in Batch 0/4 (the suite sends 23 from one IP); 1 admin at member login (SEC-11). Stale tests |
| Live `test_production_hardening` | 4 passed, 1 skipped, **5 failed, 1 error**: approval-based registration removed (accounts activate immediately), admin OTP now gets the generic reply, category pillars. Stale tests |
| Live `test_upi_adminlogin` | 7 passed, **8 errors**: fixture logs the admin in via the member login (SEC-11); needs an "activation product" seed |
| Live `test_cycle9_upi_ref` | 5 passed, **7 errors**: same fixture causes |
| Live `test_health_dashboard` | 3 passed, **4 failed, 1 error**: needs a server on :8001, a demo wallet seeded with ₹500, admin via member login, SMS for send-otp |

- **Live run conditions:** a throwaway uvicorn server on `hg_b11_live_test` (later dropped), indexes applied, admin from test-only env values, demo member seeded. Between suites I cleared rate-limit state, because all suites share one IP.
- **Live failure analysis:** none of the live failures points to a new application defect, but **they are not passes**. Each must be updated to the current contract, or given fixtures, before the live set can be claimed green. Test changes were outside this audit's mandate.
- **Coverage gap:** none of the 1,190 passing tests caught C-1 to C-8. One test (`test_settlement_two_person_rule_cannot_be_switched_off`) encodes the creator-may-pay behaviour that the engineering log claimed is forbidden.

**Browser check:** production build served via a local proxy to the throwaway API, Chrome, 1366 px and 390 px. Screens covered:
- customer cart, checkout and order invoice;
- member wallet and commission statement;
- admin Operations (approvals) and Orders;
- vendor Orders, plus the drawer with fulfilment actions.

All loaded, with **no console errors and no horizontal overflow**. Data flowed end to end: a share-link order gave a ₹600 commission on a ₹2,000 taxable base, held with "Return window still open"; the approval queue showed the pending ₹250 credit.

Defects seen in the browser:
- C-15: wrong status badge on the statement.
- C-14: customer sees the HomeGenie pages.
- On mobile, the statement's "Note" column (the hold reason) is off-screen and needs a horizontal swipe.
- `/vendor/orders/:id` redirects to `/`; the detail opens as a drawer from the list.

---

## H. Launch-gap classification

| Gap | Class | Reason |
|---|---|---|
| Address book | Acceptable post-launch | Checkout pre-fills from the profile; purchases work |
| Wishlist | Optional enhancement | No money or safety impact |
| HG-03 HomeGenie dashboard figures | Required before public launch | Members act on money figures; wrong numbers create disputes and support load |
| ADM-06 admin order detail / pagination | Required before public launch | Ops can't investigate the exceptions in C-5/C-7 at volume; list caps hide records |
| VEN-04 CSV import | Acceptable post-launch | Manual product entry works |
| VEN-05 vendor profile per status | Acceptable post-launch | Status gating works server-side |
| VEN-06 delivery proof | **Required before public launch** (becomes a blocker together with C-5) | Delivery now starts every payout clock; without proof, "delivered" is an unverified claim |
| Staff home page without `reports.read` | Required before public launch | Staff land on a 403; small fix |
| External error monitoring | Required before public launch | Money paths fail silently into logs; error ids exist but nobody is alerted |
| Frontend CSP | Acceptable post-launch | API headers present; React escapes output; add for defence in depth |
| Outdated `demo_environment.py` | Acceptable post-launch (never run in production) | Dev tool only; fails on the new contracts |

**Launch blockers come from the defects themselves:** C-1 to C-9.

---

## I. Remediation plan (ordered by risk and dependency)

1. **Phase 1, takeover (blocks staging):**
   - Atomic OTP attempts: one `find_one_and_update` with `attempts < max` plus `used: false`, and a per-identifier window.
   - Trusted-proxy `client_ip`: use the platform's real client-IP header and ignore client-supplied XFF.
   - Unmount the legacy `/auth/register`, or require email proof there.
   - `forgot_google` must require `email_verified` / `google_linked`.
   - Mobile OTP on "Apply to sell".
   - Tests for each, including a parallel-guess test.
2. **Phase 2, delivery integrity (blocks money):**
   - `delivered_at` only when fulfilments are delivered.
   - Admin "delivered" restricted (owner decision) and requiring a reason or proof.
   - Clear or ignore `delivered_at` when the status regresses.
   - Make the vendor roll-up conditional on the order not being cancelled or refunded.
   - COD confirm must not set delivered.
   - Per-vendor eligibility for multi-vendor orders, treating rejected and cancelled as terminal (C-7).
3. **Phase 3, refunds and ledger:**
   - Route the one-step refund through the case flow, or require a second finance admin.
   - `retry` keeps the original initiator; `fail` gets a role check.
   - Sale reversal net of prior refunds (C-6).
   - Exclude rejected vendors' lines from the COD expected cash and the commission base (C-8).
   - Pro-rate refunds on goods value, not fee-inclusive total (C-11).
   - Align COD release with `partially_refunded` (C-10).
   - Clawback on the taxable base (L5).
   - Add regression tests reproducing each probe.
4. **Phase 4, governance:**
   - Policy-window role, or a separate finance-owned payout hold (C-12).
   - KYC re-check at withdrawal approve and pay (C-13).
   - Vendor-owner block/delete limited to `VENDOR_ADMIN_ROLES`, and staff refused when the owner is inactive (C-17).
   - Stuck-approval recovery (C-18).
   - KYC verifier must not be any editor of the current version (C-20).
   - COD confirmer roles per owner decision (C-19).
   - UPI race cleanup (L2, L3).
5. **Phase 5, UI:**
   - Statement badge (C-15).
   - Customer gating of nav and routes (C-14).
   - ₹undefined toast.
   - Staff landing page.
   - Mobile hold-reason column.
   - Seller-ref after payment.
6. **Phase 6, tests and environment:**
   - Update the 7 live suites to the current contracts and add their fixtures (owner approval to change tests).
   - Correct the engineering-log claims.
   - Update `demo_environment.py`.
   - Error monitoring.
7. **Phase 7, staging:**
   - `mongodump`; run the migration (dry-run, then apply).
   - Resolve any webhook duplicates.
   - Set `FRONTEND_PUBLIC_URL`; verify Twilio and the XFF behaviour on the real host.
   - Create the second finance admin.
   - Full live suites on staging.
   - Re-audit Phases 1–3.

---

## J. Owner decisions required

1. **Return window duration** (`returns_policy.window_days`, currently 7; commission hold 7): still unconfirmed.
2. **Settlement:** may the person who created a settlement also mark it paid? (Decision 4 forbids create = approve only. The log claimed three people; the code allows two.)
3. **COD cash confirmation:** which roles (finance only, operations admin, or both), and does it need a second person?
4. **Who may mark an order "delivered" manually,** and what proof is required (also VEN-06)?
5. **Who may change the return window,** now that it controls when money is payable (finance/super only, or a separate payout hold)?
6. **KYC verification:** may `support_admin` verify? Must the verifier differ from *every* editor of the current version?
7. **One-step refund:** remove it, or keep it for finance with a mandatory second person?
8. **Multi-vendor orders:** confirm that a delivering vendor and its HomeGenie are paid even when another vendor on the same order rejects.
9. **COD fee on refunds:** is it refunded when all goods are returned? Tax adviser: vendors receiving the GST-inclusive line value.
10. **Hosting:** confirm the backend runs behind Vercel's edge (XFF overwritten), or name the trusted proxy header.
11. **Admin-initiated password reset when SMS is unavailable:** accept that the admin knows the temporary password, or require SMS before resets are allowed?
12. **Existing RED members:** convert any to customers (report only; no automatic conversion).
13. **Approval to update the 7 live suites** to the current contracts (this changes existing tests).
14. **Acceptance of the launch-gap classifications** in section H.
