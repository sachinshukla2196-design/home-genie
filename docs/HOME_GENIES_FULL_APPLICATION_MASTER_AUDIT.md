# HOME GENIES — Full Application Master Audit

**Type:** read-only status audit. No source, test, schema, data, dependency or deployment was changed.
**Code version audited:** `main` @ `5b7adc2ec060c4945ff813dbb8d328e5de9c812c` (2026-11-14 17:01 +0530)
**Audit date:** 2026-11-17
**Environment used:** the source tree, plus the isolated local test MongoDB `hg-test-mongo` (127.0.0.1:27018) with one throwaway `hg_audit_<suite>_test` database per suite. Production, Atlas, the live site and live payment gateways were **not** accessed. Everything about production is **NOT VERIFIED**.

### Evidence labels used throughout

| Label | Meaning |
|---|---|
| **VERIFIED** | I read the code myself and/or an automated test passed during this audit |
| **IMPLEMENTED (not verified)** | The code exists but was not exercised at runtime |
| **PARTIAL** | Some of the feature exists; the gap is stated |
| **MISSING** | No code found |
| **BROKEN** | The code exists but fails in the way described |
| **DOC≠CODE** | Documentation and implementation disagree |
| **NOT VERIFIED** | Could not be inspected (production, real providers, mobile rendering) |

**Screen statuses:** COMPLETE / PARTIAL / UI ONLY / BACKEND ONLY / BROKEN / MISSING / NOT VERIFIED.

**Defect IDs** (for example `SEC-01`) refer to section Z.

---

## A. Executive summary

HOME GENIES is a substantial, working codebase:
- **Backend:** FastAPI, 42 modules, about 11.8k lines.
- **Frontend:** React 19, 105 files, about 17.1k lines.
- **Tests:** 58 test files, about 15.4k lines.
- **Pillars:** all three are present (HomeGenie network selling, Vendor marketplace, Customer shop), with one Admin panel.

The **money engines are the strongest part**:
- integer-paise ledgers;
- idempotency keys;
- crash-safe commission distribution;
- stock reservation journals;
- refund and return safeguards (Phase 3B.7).

They are well tested. All **984 in-process tests pass**.

The application is **not ready for real operations**. Five issues block that:

1. **Two P0 security defects** (both checked against the code myself during this audit):
   - **SEC-01:** any admin role, including `support_admin`, can reset any account's password, including the super admin's. The new password comes back in plain text. This is a privilege escalation.
   - **SEC-02:** `GET /admin/reports/registrations` returns full user records, including `password_hash` and unmasked Aadhaar, to every admin role.
2. **Payment integrity gaps:**
   - Any admin role can mark an order paid (UPI confirm or manual payment) with no amount check, no unique UTR and no second approver (FIN-01).
   - Vendors can ship orders whose UPI payment was only "claimed", never verified (FIN-02).
3. **Core selling flows don't work end to end from the UI:**
   - Products with variants cannot be bought (CAT-01).
   - GST is a single global rate, ignoring each product's rate (CAT-02).
   - HomeGenie sales are almost never credited to the seller, because the seller link is captured only on the landing page (HG-01).
   - HomeGenie withdrawals can't complete: there is no KYC screen, and with only one admin account the "payer ≠ approver" rule blocks every payout (HG-02).
4. **Many finished backend workflows have no screen** (OPS-02):
   - admin: refund cases, returns arbitration, settlements, vendor ledger and adjustments, COD discrepancies, bank-change approvals, KYC review, support replies;
   - customer: cancel order, request a return.
5. **Admin Settings "Save" silently drops most fields** (ADM-01), and there is **no way to create admins or change roles** (OPS-01).

**Defect register (section Z):**

| Severity | Count |
|---|---|
| P0 | 2 |
| P1 | 21 |
| P2 | 36 |
| P3 | 22 |

**Readiness (section AA):**
- Ready with limitations: vendor onboarding, vendor panel, vendor staff, inventory, HomeGenie commission engine.
- Not ready: security, payments, admin operations, customer experience, catalogue, returns operations, vendor finance, HomeGenie payouts.
- Not verified: mobile layout, integrations, production deployment.

The recommended next step is **Batch 0: security hotfix** (section AB). It is small, isolated, and should come before anything else.

---

## B. Repository and Git status

| Item | Value |
|---|---|
| Repository | `/home/guru/Desktop/home-genie`, remote `origin` = github.com/sachinshukla2196-design/home-genie |
| Branch | `main` |
| HEAD | `5b7adc2ec060c4945ff813dbb8d328e5de9c812c`: "feat(home-genies): vendor onboarding checklist is advisory; super admin can approve anytime" |
| Latest commit date | 2026-11-14 17:01:45 +0530 |
| Commit count | 137 (85 since 2026-10-01) |
| Working tree | **clean**: no modified, staged or untracked files (`git status --porcelain -uall` is empty) |
| Ahead / behind origin/main | 0 / 0, as of the last local fetch (no fetch was performed during the audit) |
| Unfinished or uncommitted work | none |
| Frontend / backend present | yes / yes (`frontend/`, `backend/`, plus a legacy `deploy/vercel-api/`) |

**Difference from the last audited version:**
- The previous formal audit documents are `docs/VENDOR_PANEL_AUDIT_AND_PLAN.md` (written at `fcc88e3`, 2026-10-23) and `HOME_GENIES_STATUS_REPORT.pdf` (2026-10-22).
- Since then, these phases were added:
  - activation and financial controls;
  - commission eligibility and withdrawal controls;
  - stock-expiry race safety;
  - payment/cancellation consistency;
  - Phase 3B.7 refund and return safeguards;
  - vendor applications, onboarding and super-admin approval;
  - the cream/chocolate/gold theme;
  - the local demo environment tool;
  - the advisory onboarding checklist.
- Both earlier documents are therefore out of date (section F).

**Test environments available:**
- `hg-test-mongo` Docker container on 127.0.0.1:27018 (isolated).
- `backend/scripts/demo_environment.py`: a seed and cleanup tool for `*_demo_test` databases only, not run during this audit.
- Seven "live" suites need a deployed backend plus admin credentials (section X).

**Documentation available:** listed in section F.

**Missing environment configuration (local):**
- There is no `backend/.env` or `frontend/.env` on disk, and none is tracked in git.
- Local runs need `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `CORS_ORIGINS` and `ADMIN_*` supplied.
- Env vars read in code but not documented in `deploy/ENVIRONMENT.md`:
  - `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `CLOUDINARY_UPLOAD_PRESET` (vendor image upload depends on these);
  - `RATE_LIMIT_SCALE`, `COD_MAX_AMOUNT_RUPEES`, `VENDOR_TERMS_VERSION`, `STOCK_RECOVERY_MIN_AGE_SECONDS`.
- `OTP_PEPPER` is documented but defaults to an empty string.

**Pending operator action carried over:** the production index migration (`cd backend && python scripts/vendor_foundation_migrate.py --apply`) has not been confirmed as run. If it hasn't run, several uniqueness guarantees are absent in production (PLT-03).

---

## C. Complete system architecture

```
            Browser (React 19 SPA, CRA + craco; JWT in localStorage "anj_token")
                │  HTTPS  Authorization: Bearer <JWT HS256, 7 days>
                ▼
   Vercel project 1: frontend/   (SPA rewrite → index.html; build fails without REACT_APP_BACKEND_URL)
                │  axios → REACT_APP_BACKEND_URL + "/api"   (frontend/src/lib/api.js)
                ▼
   Vercel project 2: backend/   FastAPI app server.py:app (Python serverless, maxDuration 60 s)
     middleware: CORS (exact origins, '*' refused) → _ensure_initialised (503 on config problems; lazy DB init)
     19 routers, all under /api/*
     Vercel Cron (backend/vercel.json): /api/cron/release-points 20:00 UTC
                                        /api/cron/expire-pending-orders 20:30 UTC   (Bearer CRON_SECRET)
                │  Motor (async)
                ▼
   MongoDB (Atlas in production — NOT VERIFIED), ~52 collections

   External integrations
     Stripe Checkout + signed webhook  /api/webhook/stripe          (STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET)
     Razorpay order/verify + HMAC webhook /api/webhook/razorpay     (RAZORPAY_*)
     UPI manual: customer claim → admin confirm;  COD: admin confirms cash with evidence
     Twilio SMS (OTP; fail-closed 503 when disabled)                (TWILIO_*, OTP_*)
     Email: Emergent-managed Resend proxy (vendor owner invitation only)   (EMERGENT_EMAIL_KEY)
     Images: Emergent object storage (admin/profile, served via /api/files/*) + Cloudinary signed upload (vendors)
     Google sign-in: Emergent Auth (hard-coded demobackend.emergentagent.com session check)
```

**Backend modules, grouped:**

| Group | Modules |
|---|---|
| Core and platform | `server.py` (app, routers, CORS, lazy init, super-admin seed); `core.py` (DB client, JWT, `get_current_user`, role gates, rate limiter, `log_audit`, `wallet_apply`, `send_email`); `db_indexes.py` (46 index specs, created only by migration); `pagination.py`; `validators.py`; `money.py` / `money_migration.py` (integer paise); `storage.py`; `providers.py` (Twilio) |
| Auth and identity | `auth_routes.py`, `activation_routes.py`, `activation_rules.py` |
| Shop, payments, orders | `shop_routes.py` (catalogue, orders, Stripe, Razorpay, UPI, COD, `_process_paid_order`, `reverse_order_financials`), `stripe_checkout.py`, `stock.py`, `catalogue.py`, `cod_rules.py`, `returns_routes.py` |
| HomeGenie money | `commission.py` (frozen plans, distribution, release), `ledger.py` (vendor ledger), `wallet_routes.py`, `wallet_reconcile.py`, `badges.py`, `cron_routes.py` |
| Admin | `admin_routes.py`, `finance_routes.py`, `financial_ops.py`, `governance_routes.py`, `historical_audit.py` |
| Vendor pillar | `vendor_routes.py`, `vendor_lifecycle.py`, `vendor_applications.py`, `vendor_onboarding.py`, `vendor_invitations.py`, `vendor_staff.py`, `vendor_staff_routes.py`, `vendor_dashboard.py`, `vendor_reports.py`, `vendor_history.py`, `vendor_benefits.py`, `commercial_terms.py`, `commercial_routes.py` |

**Cross-cutting behaviour:**
- **Authentication:**
  - JWT, re-read from the database on every request (`core.get_current_user`).
  - Blocked, suspended, deleted and not-activated accounts are refused.
  - A password change revokes older tokens.
  - Logout does **not** revoke tokens (SEC-12).
- **Authorisation:**
  - FastAPI dependencies: `require_admin` (4 admin roles), `require_vendor_admin` (super_admin, admin), finance gates (super_admin, accounts_admin), `require_approved_vendor`.
  - Vendor staff go through `authorize_staff`, a regex allow-list per path.
- **Audit:**
  - `log_audit` writes `audit_logs` on most writes.
  - Not audited: password-reset dismiss, finance reconcile, document deletion.
  - super_admin can delete the whole log (AUD-01).
- **Logging and errors:**
  - plain `logging.basicConfig`;
  - no global exception handler, no security headers, **no error monitoring** (PLT-06).
- **Background jobs:**
  - two daily Vercel crons;
  - order expiry is also swept lazily;
  - `POST` cron variants use `BackgroundTasks`, which is unreliable on serverless.
- **Collections:** about 52. The main ones are `users`, `orders`, `products`, `vendors`, `vendor_ledger`, `settlements`, `commissions`, `commission_plans`, `wallets`, `wallet_transactions`, `withdrawal_requests`, `kyc_records`, `refund_cases`, `return_cases`, `stock_txns`, `stock_movements`, `notifications`, `audit_logs`.

---

## D. Admin panel — every module

There are four admin roles. `ADMIN_ROLES = {super_admin, admin, accounts_admin, support_admin}` (core.py:44).

### D.1 Screen inventory

| Screen | Route | Status | Notes |
|---|---|---|---|
| Dashboard | `/admin` | PARTIAL | All counts are live database queries. Revenue is miscomputed: includes refund-due orders, drops partially refunded ones, never subtracts refunds, capped at 5000 orders, days bucketed by `created_at` in UTC (ADM-05). Pending KYC and withdrawals are computed but not displayed. |
| Users | `/admin/users` | PARTIAL | Edit, block, deactivate, reset password, credit wallet, reference codes, registration requests. Search is client-side only; capped at 1000 rows; no role management; vendor_staff and admins are not listed. "Delete" is a soft deactivate, but the confirm text says "permanently delete". |
| Products | `/admin/products` | PARTIAL | Create, edit, activate, delete, one image. No variants, CSV, search, category picker or history. **Edit overwrites live stock** (CAT-03). Uses the public `/products` endpoint, capped at 200. |
| Orders | `/admin/orders` | PARTIAL | Status change, refund, delete, COD confirm, UPI confirm, manual payment. No detail view, search or pagination; refund cases and returns are not wired in. |
| Activations | `/admin/activations` | COMPLETE | RED→GREEN approval: atomic, audited. No demotion. |
| Withdrawals | `/admin/withdrawals` | PARTIAL | Approve, mark paid with reference, reject; maker-checker is enforced. The payout bank details are never shown (FIN-10). |
| Vendors | `/admin/vendors` | PARTIAL | Review, suspend, reinstate, vendor-product approve/reject. No "close" action; capped at 500 rows. |
| Add vendor | `/admin/vendors/new` | COMPLETE | Creates the vendor in onboarding. |
| Vendor applications | `/admin/vendor-applications` | COMPLETE | Review, decline, duplicate, convert, edit (VERIFIED by `test_vendor_applications`, 51 tests). |
| Vendor onboarding | `/admin/vendors/:id/onboarding` | COMPLETE | 8 sections; advisory checklist; super-admin "Approve vendor now" (VERIFIED by `test_vendor_onboarding` plus a browser check on 2026-11-14). |
| Agreements | `/admin/agreements` | COMPLETE | Draft, then approval by a different finance user (maker-checker enforced in the backend). |
| Benefits | `/admin/benefits` | PARTIAL | Menu shown to all roles, but every GET needs a finance role, so other roles see an empty page. |
| Reports | `/admin/reports` | PARTIAL | View the first 200 rows; CSV export. **Leaks data (SEC-02)**; CSV has no formula-injection guard. |
| Settings | `/admin/settings` | **BROKEN** | Save sends only a few fields; commission %, return window, COD switch, withdrawal switch and others are silently not saved (ADM-01). |
| Audit logs | `/admin/audit` | PARTIAL | Last 500 rows; no filter; super admin can "Delete All" (AUD-01). |

**BACKEND ONLY (the API exists, no admin screen):**
- KYC review and edit;
- commission list, hold and release;
- referrals;
- payments list;
- refund cases; returns decision; returns policy;
- finance policy, vendor balances, ledger, adjustments, settlements, reconcile;
- COD discrepancies;
- commission funding; negative wallets;
- bank-change requests; vendor policy; vendor history;
- support tickets;
- owner-invitation revoke and status.

**MISSING entirely:**
- admin and role management;
- category CRUD;
- banners, CMS, promotions, coupons;
- broadcast notifications;
- shipping configuration;
- customer support tickets;
- sponsor change;
- GREEN→RED demotion;
- vendor close;
- admin product variants, CSV, archive, history;
- duplicate-account detection;
- admin MFA.

### D.2 Admin permission matrix (backend-enforced)

| Action | Roles allowed | Maker-checker in backend? | Location |
|---|---|---|---|
| Read dashboard, users, orders, payments, commissions, reports | all 4 | n/a | admin_routes.py:49–361, 1062 |
| Create, edit or delete HOME GENIES products | all 4 | no | admin_routes.py:136–185 |
| Edit or permanently delete vendor products | refused (409) | n/a | admin_routes.py:155–158, 180 |
| Deactivate vendor product | super_admin, admin | no | admin_routes.py:167 |
| Order status (including cancel of paid orders) | **all 4** | no | admin_routes.py:215 |
| Hard-delete order | **all 4** | no | admin_routes.py:334 |
| One-step refund | super_admin, accounts_admin | **no** | admin_routes.py:272 |
| UPI confirm / manual payment | **all 4** | **no** | shop_routes.py:740, 782 |
| COD collected | admin, super_admin (not the attributed seller) | discrepancy resolver must differ from reporter | shop_routes.py:203; finance_routes.py:399 |
| Withdrawal approve / pay / reject | super_admin, accounts_admin | **yes**: approver ≠ payer | admin_routes.py:518, 576 |
| Wallet credit | super_admin, accounts_admin | no (₹1 crore cap) | admin_routes.py:953 |
| Commission release / hold | super_admin, accounts_admin | no | admin_routes.py:371 |
| KYC edit (PAN, bank) / verify | **all 4** | no | admin_routes.py:435, 459 |
| Reset password / edit user / block | **all 4, any target** | no | admin_routes.py:989, 901, 857 |
| Settings (non-money / money fields) | all 4 / super_admin + accounts_admin | no | admin_routes.py:700–705 |
| Finance policy | super_admin, accounts_admin | no (one person can switch dual approval off) | finance_routes.py:203 |
| Vendor adjustments | super_admin, accounts_admin | **no**; signed amount, no cap | finance_routes.py:243 |
| Settlements approve / pay | super_admin, accounts_admin | only if `require_dual_approval`, **default False** | finance_routes.py:28, 312–328 |
| Agreements approve | super_admin, accounts_admin | **yes** | commercial_terms.py:96 |
| Benefits decide | super_admin, accounts_admin | **yes** | vendor_benefits.py:153 |
| Refund case initiate / confirm | any admin / finance | **no** (initiator may confirm) | returns_routes.py:247–330 |
| Returns decision | all 4 | no | returns_routes.py:710 |
| Bank-change approval | super_admin, accounts_admin | **no** | governance_routes.py:232 |
| Vendor final approve / reject / reinstate / activate | super_admin only | by role only | vendor_routes.py:865; vendor_onboarding.py:652 |
| Vendor suspend / product decision | super_admin, admin | no | vendor_routes.py:857, 898 |
| Delete all audit logs | super_admin | no | admin_routes.py:1029 |

**Conclusion:** maker-checker is genuinely enforced **in the backend** for:
- withdrawals;
- commercial agreements;
- benefit grants;
- COD discrepancy resolution.

It is **absent** for:
- marking orders paid;
- refunds;
- adjustments;
- wallet credits;
- bank changes;
- commission release.

For settlements it exists but is switched off by default.

### D.3 Other admin modules

| Module | Status |
|---|---|
| Categories | Seeded only; no CRUD |
| Banners / CMS / promotions / coupons / shipping configuration / broadcast notifications | MISSING |
| Support | Vendor tickets only; admin replies are backend only |
| Settings | BROKEN (ADM-01) |
| Reports | 8 report types in the backend; 6 exposed in the UI |

---

## E. Super Admin governance

**What works (VERIFIED by code reading and `test_vendor_authority`, 78 tests; `test_governance_security`, 16 tests):**
- Final vendor approval, rejection, reinstatement and activation are super_admin only.
- Owner access repair is super_admin only.
- Converting an existing account into a vendor is retired (410).
- Role overwrite has no endpoint.

**What undermines it:**
- **SEC-01:** a support_admin can take over the super_admin account. Its maker-checker and approval rights then mean nothing.
- **OPS-01:** there is no API to create admins or change roles. Admins exist only via:
  - the env seed (`server.py` `_init_db`), which re-applies the env password at every cold start, so a password changed in the UI is reverted (SEC-17);
  - the demo script.
- With a single super_admin and no accounts_admin, every two-person rule (withdrawal pay, agreement approve) can **never complete** in production unless a second admin is inserted directly into the database.
- **AUD-01:** the audit trail can be erased by super_admin.
- **No admin MFA** (SEC-21).

---

## F. HomeGenie panel — every module

The HomeGenie panel and the customer panel are **the same `/app/*` layout and the same account type**: `role=distributor`. RED means registered; GREEN means activated.

| Screen | Route | Status | Evidence / gap |
|---|---|---|---|
| Dashboard | `/app/dashboard` | COMPLETE (figures misleading in places) | Live from `GET /dashboard` (wallet_routes.py:226). The "pending" figure mixes commission with withdrawal reservations; team commission and the 7-day chart ignore reversals; the badge is bucketed by `created_at`. |
| Wallet | `/app/wallet` | COMPLETE | 300 rows; no statement or export |
| Withdrawals | `/app/withdrawals` | **BROKEN end to end** | KYC is required by default (`core.py:226`), but no screen submits or reviews KYC (HG-02) |
| Referral | `/app/referral` | PARTIAL | Shares `/register?ref=`, which sets a sponsor and does **not** credit sales (HG-01) |
| Rewards / badge / leaderboard | `/app/rewards` | COMPLETE | Names masked |
| Profile | `/app/profile` | PARTIAL | Photo only. Edit profile, change mobile, change password and KYC are BACKEND ONLY. |
| Commission statement | — | MISSING | — |

**Registration and activation:**
- `POST /auth/register-request` creates an active RED distributor immediately. It verifies **neither mobile nor email** (SEC-05).
- The OTP register route `/auth/register` exists but the UI does not use it.
- Activation is **manual**: admin or super_admin picks a paid, non-refunded order with a pre-GST subtotal of at least ₹2,500 (`activation_rules.py:13`). COD orders need proven collection; self-approval is refused (VERIFIED by `test_activation`, `test_activation_rules`).

**Referral ID and sponsor:**
- The referral ID is `distributor_id` `HG######` from a counter.
- The sponsor is set only at signup, from a GREEN member or an admin code. No endpoint changes a sponsor afterwards, so cycles cannot form.
- Commission is skipped when the recipient is the buyer.
- There is no protection against a HomeGenie buying through their own link from a second unverified account.

**How a HomeGenie sells:**
- The order carries `seller_ref`, and is attributed only if the ref belongs to a GREEN distributor who is not the buyer (shop_routes.py:136).
- The frontend captures the ref **only** from `/?ref=` on the Landing page (VERIFIED: `captureSellerRef` is called only in `Landing.js:61`).
- No screen produces that link, and the ref is never cleared (HG-01).

**Commission (VERIFIED in code and by `test_commission_model`, `test_commission_engine` [script], `test_crash_safe_distribution`):**

| Aspect | Implementation |
|---|---|
| Rates | 30% direct, 10% referral, 5% team, on the pre-GST subtotal (`core.py:211-213`, `commission.py:146-150`), stacked; three fixed levels |
| Eligibility | GREEN distributor; a RED referrer ends the chain |
| Plans | Frozen per order (`commission_plans`, `_id` = order id) |
| Statuses | PENDING → RELEASED; PARTIALLY_REVERSED / REVERSED; `manual_hold` |
| Release | Cron `/api/cron/release-points` after `return_window_days` (default 7), counted **from payment, not delivery**, although the notification says "after delivery" (FIN-05) |
| Refund | Proportional clawback, idempotent; a wallet can go negative |

**Wallet and withdrawals:**
- Conditions: GREEN distributor, `points_withdrawal_enabled`, verified KYC (by default); no minimum amount.
- Approve → pay with approver ≠ payer, unique payout reference, idempotent wallet operations (VERIFIED by `test_withdrawal_controls`, 33 tests).
- No bank snapshot is taken at request time, and no idempotency key on the request (FIN-10, PLT-09).

---

## G. Customer panel and user profile

**There is no distinct "customer" role in code.** Every signup is `role=distributor, status=red`. The admin dashboard and reports query `role: "customer"`, which never matches (DOC≠CODE with MASTER_SPEC §1).

| Area | Status | Notes |
|---|---|---|
| Sign-up | PARTIAL | No OTP; Google flag is trusted from the client (SEC-05); password minimum is 6 |
| Login (password, OTP, Google) | COMPLETE | OTP returns 503 unless Twilio is configured; Google depends on Emergent Auth |
| Forgot password | PARTIAL | Request goes to an admin manual queue, or a Google-verified reset; no self-service OTP reset |
| Sessions | IMPLEMENTED | 7-day JWT in localStorage; logout is client-side only |
| Profile | PARTIAL | Photo only in the UI |
| Address book / default address | MISSING | Checkout prefills from the profile |
| Wishlist / saved products | MISSING | — |
| Browse / categories | PARTIAL | No search, filter, sort or pagination (capped at 200) |
| Product detail | PARTIAL / **BROKEN for variant products** | Attributes and variants not shown; `variant_sku` is never sent (CAT-01, VERIFIED) |
| Cart | COMPLETE | Stored in localStorage; the server re-prices |
| Checkout | PARTIAL | Stripe, Razorpay, UPI and COD wired. UPI claim is sent immediately with an empty reference (FIN-08). No server-side pincode or mobile validation. Flat GST (CAT-02). |
| Orders list and detail | COMPLETE / PARTIAL | Vendor tracking shown. "Pay now" rebuilds a new order from the cart. |
| Cancel / return | **BACKEND ONLY** | `/orders/{id}/cancel`, `/orders/{id}/returns` and `/returns` exist; no customer UI |
| Refund history | MISSING | Notifications only |
| Customer support | UI ONLY | Static legal page |

---

## H. Vendor panel — every module

**Gating:**
- `VendorGate` (`App.js:95-99`) shows `PendingApproval` unless the vendor status is `approved` or `active`.
- The backend enforces the same through `require_approved_vendor` (`vendor_routes.py:86-90`).
- This is why an onboarding or ready_for_review vendor (for example production vendor VD000003) sees the same "Your application is in progress" card on every page. That is by design.

**Lifecycle** (`vendor_lifecycle.py:30-63`, `move()` is a compare-and-set plus a history row):
```
apply → [applicant login active] → onboarding --admin--> ready_for_review --super_admin--> approved | rejected | onboarding
onboarding --super_admin--> approved (advisory checklist: submitted_missing / approved_with_missing recorded)
onboarding --admin--> rejected (decline/duplicate);  rejected --super_admin--> onboarding (reopen)
approved --super_admin--> active;  approved/active --admin--> suspended;  suspended --super_admin--> approved
legacy self-onboarding states (invited/draft/submitted/under_review/…) remain in the table and reachable via PUT /vendor/me
```

| Screen | Route | Status | Notes |
|---|---|---|---|
| Login / apply / owner invite / staff invite | `/vendor/login`, `/vendor/apply`, `/vendor/owner-invite`, `/vendor/invite` | COMPLETE / COMPLETE / **PARTIAL** / COMPLETE | Owner-invite email link is relative and unusable (VEN-01) |
| Pending gate | any gated route | PARTIAL | A suspended vendor sees the generic "awaiting approval" text |
| Dashboard | `/vendor/dashboard` | COMPLETE (owner) / BROKEN (staff without `reports.read`) | Live aggregations; tiles are dynamic and read 0 only when nothing has been posted |
| Products (CRUD, archive, listing, CSV, images) | `/vendor/products` | PARTIAL | Archived products can be re-listed (CAT-04); CSV import skips the image-ownership check and wipes fields (VEN-04); variant edit can overwrite live variant stock (CAT-03) |
| Inventory (adjust, journal) | `/vendor/inventory` | COMPLETE | `stock_movements` journal |
| Orders and fulfilment | `/vendor/orders` | COMPLETE with defects | Accept → pack → dispatch (carrier and tracking required) → deliver (a 3-character note is enough, VEN-06). Shows only the vendor's own lines (VERIFIED). **Shows UPI-claimed unpaid orders (FIN-02).** |
| Dispatch / shipping | `/vendor/dispatch`, `/vendor/shipping` | COMPLETE | — |
| Returns | `/vendor/returns` | COMPLETE | Approve, contest, receive, inspect, replacement |
| Analytics / reports / advancement | `/vendor/analytics`, `/vendor/reports`, `/vendor/advancement` | COMPLETE | CSV export |
| Finance / earnings / COD / terms | `/vendor/finance`, `/vendor/earnings`, `/vendor/cod`, `/vendor/terms` | COMPLETE (read-only) | Finance text says "before commissions", but commissions are applied (VEN-08) |
| Support | `/vendor/support` | COMPLETE (owner) | Admin replies are backend only |
| Staff | `/vendor/staff` | COMPLETE | Invite, role, suspend, revoke, resend |
| Security | `/vendor/security` | COMPLETE | Change password |
| Profile / governance | `/vendor/profile` | PARTIAL | Shows an editable legacy form to onboarding applicants (every save returns 409) and to `active` vendors (changes silently dropped) (VEN-05) |

**Who can edit what:**
- After approval, a vendor can edit **contact fields only** (`vendor_routes.py:134-140`).
- Legal identity, PAN/GST and categories: admin only, during onboarding. There is no path to change them after approval.
- Bank: change request, approved by a single finance admin (FIN-04).

---

## I. Vendor staff and permissions

The matrix comes from backend `vendor_staff.RULES` and `PRESETS`. The first matching rule decides; a path with no rule is refused.

| Path (under `/api/vendor`) | Permission | store_mgr | product_mgr | order_mgr | inventory | finance_viewer |
|---|---|---|---|---|---|---|
| GET /me, /notifications | any member | ✔ | ✔ | ✔ | ✔ | ✔ |
| GET products, export, template, catalogue spec | products.read | ✔ | ✔ | – | ✔ | – |
| POST/PUT products, import, archive, listing, upload sign | products.write | ✔ | ✔ | – | – | – |
| GET stock-history / POST stock | inventory.read / .write | ✔ / ✔ | ✔ / – | – | ✔ / ✔ | – |
| GET orders | orders.read | ✔ | – | ✔ | – | – |
| POST fulfilment | orders.fulfil | ✔ | – | ✔ | – | – |
| RTO return-inspection, returns action and inspection | returns.act | ✔ | – | – | – | – |
| GET returns | returns.read | ✔ | – | ✔ | – | – |
| GET dashboard, reports | reports.read | ✔ | – | – | – | ✔ |
| GET finance/* | finance.read | – | – | – | – | ✔ |

**Always refused for staff:** profile edit, documents, bank change, support, staff management, terms acceptance, advancement.

**Isolation:** VERIFIED by `test_vendor_staff` and `test_vendor_authority` (cross-vendor access returns 404).

**Gaps:**
- `orders.read` exposes per-order vendor ledger rows, and `reports.read` exposes payable and settlement figures (VEN-07).
- The menu shows areas the backend refuses (VEN-07).
- Suspended or revoked staff keep a working login and can use `/app/*` (SEC-16).

---

## J. Product management and catalogue

| Aspect | Admin path (`POST /admin/products`) | Vendor path (`POST /vendor/products`) |
|---|---|---|
| Who | any admin role, including support and accounts | approved vendor or permitted staff |
| Validation | **none** (price, MRP, category, options) | MRP and price > 0, price ≤ MRP, GST 0–28, pillar, attributes, package, variants, documents |
| SKU | unique index; not upper-cased; duplicate on edit → 500 | upper-cased, regex-checked, unique variant SKU index |
| Variants | none (free-text `options`) | per-variant SKU, price, stock |
| Price storage | float rupees (paise only from order time onward) | float rupees |
| GST / HSN | stored, **ignored at checkout** | stored, **ignored at checkout** (CAT-02) |
| Shipping data | none | weight, dimensions, handling days |
| Approval | none: live immediately (`approval_status` unset counts as approved) | pending → approved / rejected; a material edit goes back to pending |

**Approval and visibility:**
- The shop shows products where `approval_status ∈ {None, approved}` AND `is_active`.
- The shop does **not** check `archived` or vendor status.
- Vendor suspension deactivates all of the vendor's products. Reinstatement leaves them paused.

**Can approval be bypassed?**
- The generic admin endpoints refuse to edit vendor products (409).
- A vendor **cannot** list an unapproved product.
- A vendor **can** re-list an archived approved product (CAT-04, VERIFIED).
- An admin takedown is not sticky: the vendor can re-list immediately (CAT-05).

**Ownership:**
- `vendor_id` is on the product and snapshotted on each order line. HOME GENIES products have `vendor_id = null`.
- Cross-vendor edits are blocked by `_own_product`.

**Lifecycle:**
```
create → (vendor: pending → approved/rejected) → listed (is_active) → reserved at order → decremented on payment → restocked on cancel/return → archived/paused
```
Defects along this path: CAT-01 to CAT-06, VEN-04.

---

## K. Categories and subcategories

| Item | Implementation |
|---|---|
| Main categories | Exactly four, seeded once into `product_categories` from `CATEGORY_SEED` (server.py:105, 204-208) and used as the validation constant `catalogue.PILLARS`: **Sarees; Fashion Products; Makeup, Beauty & Skincare; Household Essentials** (VERIFIED) |
| Category IDs | `{id, name, created_at}`; unique on `name`. Products store the **name string**. |
| Activation / images / ordering | MISSING |
| Admin category management | MISSING (no endpoint, no UI). Admin products accept any free-text category. |
| Subcategories | **Free text** (max 60 characters), not master data |

**Attributes** (vendor path only; all optional; unknown keys rejected):
- **Sarees:** fabric, weave_style, colour, length_m, care_instructions, origin, included_accessories. There is no blouse-piece field and no weave list.
- **Fashion Products:** product_type, size, colour, material, fit, care_instructions.
- **Makeup, Beauty & Skincare:** product_type, net_quantity, ingredients, directions, warnings, batch_no, expiry_date (not checked to be in the future), manufacturer, country_of_origin.
- **Household Essentials:** material, dimensions, weight_g, usage_instructions, safety_info.
- **Variant attributes:** a global whitelist: size, colour, design, fabric, pack_size, weight, quantity, shade.
- **Search or filter on attributes:** none. The product page does not display attributes.

---

## L. Registration and sign-up architecture

| Path | Creates | Verification | Approval |
|---|---|---|---|
| `/register` → `POST /auth/register-request` | active RED distributor | **none** (no OTP; `google_verified` trusted from the client, VERIFIED at auth_routes.py:128-160) | none |
| `POST /auth/register` (OTP) | distributor | mobile OTP | none. **Not used by the UI.** |
| Google sign-in (Emergent) | logs in by **email match** | Emergent session | — |
| `/vendor/apply` | active vendor-role login + vendor in `onboarding` | **none** (any mobile number) (VEN-02) | selling waits for super_admin |
| Admin "Add vendor" | owner user `pending_approval` + invitation | invitation token | super_admin final review |
| Owner invitation accept | activates the owner | token | — |
| Staff invitation accept | `vendor_staff` + `vendor_members` row | token + matching mobile | owner invites |
| Admin accounts | env seed (super_admin) / demo script | — | **no API** (OPS-01) |

---

## M. Identity and authentication

| Account type | Creation | Login methods | Role / relationship | Approval | Panel access |
|---|---|---|---|---|---|
| Customer | register-request (same as HomeGenie) | password (email, mobile or ID), OTP, Google | `distributor` / `red` | none | `/app/*` |
| HomeGenie | the same account, promoted | same | `distributor` / `green` | admin or super_admin activation | `/app/*` |
| Vendor applicant | `/vendor/apply` | password, OTP, Google | `vendor` (VD######), vendor `onboarding` | super_admin to sell | `/vendor` (pending card) + `/app/*` |
| Vendor owner (admin-started) | admin onboarding + invitation | after activation: password, OTP, Google | `vendor` | blocked until activated (`NOT_ACTIVATED`) | `/vendor`, `/app/*` |
| Vendor staff | owner invitation | password, OTP | `vendor_staff` (VS######) | invitation | `/vendor` (per permission), `/app/*` |
| super_admin | env seed | admin-login; also `/auth/login` and Google | `super_admin` | — | `/admin`, `/app` |
| admin / accounts_admin / support_admin | **no API** | same | role | — | `/admin` |

**Checks:**
- **Duplicate mobile or email:** pre-checks plus unique indexes (`users_mobile_unique` sparse, `users_email_partial_unique`).
- **Role overwrite:** no endpoint changes a role.
- **Pending and blocked accounts:**
  - checked on password, OTP and Google login;
  - admin-login does not check;
  - `get_current_user` refuses blocked, suspended, deleted and not-activated accounts on every call (VERIFIED by `test_forgot_google`, `test_otp_auth` is a live suite and NOT RUN, `test_vendor_authority`).
- **Takeover risks:**
  - SEC-01: admin password reset of any target;
  - SEC-03: admin edits any target's email or mobile;
  - SEC-04: unblock reactivates deleted or not-activated accounts;
  - SEC-05: account pre-hijack via an unverified signup plus Google login by email match;
  - VEN-02: mobile squatting via vendor apply.

**Separation of account types:**
- Customer and HomeGenie are the **same** account (`distributor`, RED or GREEN).
- Vendor, vendor staff and admin are distinct roles.
- `/app/*` has no role gate, so vendors, staff and admins can also use the shop and wallet pages. Withdrawals are still restricted to GREEN distributors in the backend.

---

## N. Orders and fulfilment

**Order `status`** (no central transition table; written in several places):
- `payment_pending` (online) or `confirmed` (COD)
- → `processing` (paid)
- → `shipped` (any vendor dispatches) or `delivered` (all fulfilments delivered, or COD collected, or COD discrepancy resolved)
- `cancelled`: by expiry, customer, admin, or when every vendor rejects
- `refunded`: admin full refund

**`payment_status`:**
- Online: `pending → claimed (UPI) → paid → partially_refunded / refunded`.
- COD: `cod_pending → paid | cod_discrepancy → paid`.
- A `needs_refund` flag marks late payments.

**Per-vendor fulfilment** (`orders.fulfilments[]`):
- new → accepted | rejected
- accepted → packed | cancelled
- packed → dispatched | cancelled
- dispatched → delivered | delivery_failed
- delivery_failed → dispatched | returned_to_origin

Updates are conditional `$elemMatch` writes (VERIFIED by `test_vendor_operations`, `test_order_lifecycle_races`, 36 tests).

**Gaps:**
- FIN-02: unpaid "claimed" orders can be fulfilled.
- FIN-11: COD "collected" forces `delivered` regardless of fulfilment.
- ORD-01: mixed platform and vendor orders are rolled up to `delivered` while platform lines are unshipped.
- ORD-02: admin status changes don't sync fulfilments (suspected).
- ORD-03: a suspended vendor cannot act on existing paid orders, and there is no admin override.
- FIN-07: hard delete.
- Shipping is manual (carrier, tracking number and URL entered by the vendor); there is no courier API.

---

## O. Inventory

**VERIFIED by `test_stock_reservation` (13), `test_stock_expiry_race` (39), `test_stock_recovery` (25):**
- Reservation at order creation with a `reserve:<order>` unique key and per-line `stock_ops` markers.
- Decrement on payment.
- Restock on cancel, expiry and return.
- A `stock_movements` journal.
- A recovery sweep for crashed transactions.
- Expiry restoration is race-safe.

**Gaps:**
- CAT-03: admin product edit and vendor variant edit overwrite live stock.
- FIN-08: UPI claims never expire, so stock stays reserved indefinitely.
- FIN-07: order hard delete does not release stock.
- No low-stock alerts beyond dashboard counts.

---

## P. Returns and refunds

**Phase 3B.7** (commit `60a0acd`; VERIFIED by `test_refund_return_controls`, 37 tests passing):
- A refund case is claimed for ONE reference before money moves; a crashed confirmation resumes only with that reference.
- Return quantities are claimed atomically per order line and released once.
- A cancelled paid order opens one `cancel:<order>` case (repaired by cron).
- A vendor rejection of a paid order opens one `vreject:` case and reverses that vendor's sale.
- Only finance roles may do a one-step refund, confirm or resolve.

Also VERIFIED: `test_returns_refunds` (25), `test_refunds_and_retention` (25).

**Not enforced:**
- initiator ≠ confirmer (FIN-04);
- payment-happened check: a refund case can be "confirmed" with ₹0 on an unpaid COD or claimed order, and the customer is told "Refund processed" (FIN-12);
- UTR uniqueness across orders.

**Other gaps:**
- The vendor is debited the GST share on vendor-specific refunds (FIN-13).
- The vendor's commission is not credited back on customer refunds (suspected policy gap).
- **There is no customer or admin UI for returns and refund cases (OPS-02).**

---

## Q. Commissions and HomeGenie wallet

See section F. The engine is solid and well tested:
- frozen plans;
- `op_key` idempotency;
- resumable distribution;
- intent-based release;
- proportional clawback.

**VERIFIED by:** `test_commission_model` (30), `test_crash_safe_distribution` (12), `test_crash_safe_finance` (16), `test_recovery_and_ledger` (20), `test_role_eligibility_wallets` (17), `test_withdrawal_controls` (33), and the `test_commission_engine` script (PASS).

**Gaps:**
- FIN-05: release is anchored to payment, not delivery.
- FIN-09: release cron reads at most 5000 rows unsorted.
- HG-01: seller attribution.
- HG-02: withdrawals blocked.
- HG-03: dashboard figures misleading.

The spec says "cash wallets and non-cash points are separate". The code has a single points wallet, withdrawable at ₹1 per point (DOC≠CODE).

---

## R. Vendor finance and settlements

**VERIFIED by `test_finance_ledger` (21), `test_commercial_terms` (10), `test_e2e_vendor_integration` (3):**
- The vendor ledger is append-only with unique `source_key`s: SALE, COMMISSION, SALE_REVERSAL, REFUND, ADJUSTMENT, SETTLEMENT_PAID.
- Settlements run requested → approved → paid / rejected / failed, with one open settlement per vendor (partial unique index).
- Agreements require a second approver.

**Defects:**
- **FIN-03 (VERIFIED, `ledger.py:169-185`):** "available for settlement" = payable − settled − open. It does not consider delivery or the return window, so money can be paid out before goods ship.
- Dual approval defaults to off (`finance_routes.py:28`), and one finance admin can switch it off.
- Adjustments: any signed amount, single actor.
- Bank change: a single approver, no proof document, no notice to the old contact, no snapshot on the settlement.
- Commission can be charged retroactively when an agreement is approved after its effective date (suspected).
- **There is no admin UI for settlements, the ledger, adjustments or finance policy (OPS-02).**

---

## S. Notifications and support

| Channel | Provider | Actually sent? | Used for |
|---|---|---|---|
| SMS | Twilio | Yes, if `TWILIO_ENABLED` and credentials are set (production NOT VERIFIED) | login OTP, change-mobile OTP, registration OTP (route unused by the UI) |
| Email | Emergent-managed Resend proxy | Only when `EMERGENT_EMAIL_KEY` is set; otherwise silently skipped | **vendor owner invitation only**. The link is relative (VEN-01). The template uses the old green "AYURVEDA INDIA LLP" branding. |
| Push | — | MISSING | — |
| In-app | `notifications` collection | Stored and displayed only | orders, payments, commissions, releases, KYC, withdrawals, referrals, password change, vendor and admin alerts |

**Support:**
- Vendor tickets exist (backend, plus the vendor UI).
- Admin replies are backend only.
- Customers and HomeGenies have only a static support page.

---

## T. Security and access control

**Role × capability matrix** (backend dependencies; a ✔ under support_admin marks a gap where noted):

| Capability | super_admin | admin | accounts_admin | support_admin | vendor owner | vendor staff | HomeGenie (green) | customer (red) |
|---|---|---|---|---|---|---|---|---|
| Admin reads | ✔ | ✔ | ✔ | ✔ | – | – | – | – |
| User edit, block, reset password (any target) | ✔ | ✔ | ✔ | ✔ **(SEC-01, SEC-03)** | – | – | – | – |
| Mark order paid (UPI / manual) | ✔ | ✔ | ✔ | ✔ **(FIN-01)** | – | – | – | – |
| Refund, withdrawal pay, wallet credit, money settings | ✔ | – | ✔ | – | – | – | – | – |
| Finance writes, settlements | ✔ | – | ✔ | – | – | – | – | – |
| Vendor lifecycle (non-final) | ✔ | ✔ | – | view | – | – | – | – |
| Vendor final approval | ✔ | – | – | – | – | – | – | – |
| Vendor selling routes | – | – | – | – | ✔ (approved or active) | per permission | – | – |
| Shop, orders, returns | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| Withdrawal request | – | – | – | – | – | – | ✔ (KYC) | – |

**Checks:**
- **IDOR:** sampled endpoints are well scoped (orders by `user_id`, `_own_product`, `_own_return`, fulfilments by `vendor_id`, staff by vendor). Exception: `/payments/status/{session_id}` is unauthenticated and returns the `order_id`.
- **Injection:** search uses `re.escape`. No request dict was found flowing into a Mongo filter. NoSQL injection risk is low.
- **Sensitive exposure:**
  - SEC-02 (reports);
  - `/vendor/me` passes internal review fields to staff (VEN-07);
  - KYC (PAN, Aadhaar, bank) is stored in plaintext (SEC-20).
- **Rate limits:**
  - present on login, admin-login, register-request, forgot, OTP login, vendor apply, invite accept, support, change-password, upload-sign;
  - **missing** on `/auth/send-otp` and change-mobile send (SEC-09, SMS cost abuse);
  - keyed on the first `X-Forwarded-For` value, which may be spoofable (SEC-15, suspected).
- **Duplicate-transaction protection:**
  - strong in the ledgers, wallets, settlements and stock;
  - missing on order creation and withdrawal requests;
  - the Razorpay webhook marks an event seen before processing it (FIN-14).
- **Secrets:** no `.env` file is tracked. A pattern scan found only placeholders. The demo script holds local demo defaults only.
- **Headers / CSP:** none (PLT-06).

---

## U. Frontend screen inventory

The full per-screen tables are in sections D (admin), F/G (HomeGenie and customer) and H (vendor). Route summary (`App.js`):

| Area | Routes | Notes |
|---|---|---|
| Public | `/`, `/login`, `/register`, `/login-otp`, `/forgot`, `/legal/:slug`, `/admin-secure-login`, `/vendor/login`, `/vendor/register` (→ `/vendor/apply`), `/vendor/apply`, `/vendor/invite`, `/vendor/owner-invite`; `#session_id` → AuthCallback; `*` → `/` | |
| Customer / HomeGenie | `/app/{dashboard, products, products/:id, cart, checkout, orders, orders/:id, rewards, wallet, withdrawals, referral, notifications, profile}`, `/payment/{success, cancel}` | ProtectedRoute, any logged-in role |
| Admin | `/admin`, `/admin/{users, products, orders, activations, withdrawals, vendors, vendors/new, vendor-applications, vendors/:id/onboarding, agreements, benefits, reports, settings, audit}` | any of the 4 admin roles |
| Vendor | Gated: dashboard, orders, products, inventory, dispatch, returns, analytics, reports, advancement, finance, earnings, terms, shipping, cod, notifications, support. Ungated: staff, security, profile. | vendor or vendor_staff |

- No routes point at missing components.
- `ThemeToggle.js` is orphaned.
- Backend features with **no UI**: listed in OPS-02.

---

## V. Design and responsive audit

**Cream / chocolate / gold theme:**
- Implemented across **all panels** via `index.css` tokens and the Tailwind remap. Old names (`hg-violet`, `hg-pink`, `hg-lavender`) are remapped to chocolate, gold and terracotta.
- `ThemeContext` forces the light theme.
- No raw violet, purple, indigo or pink Tailwind classes remain.
- A browser check of the admin onboarding page on 2026-11-14 confirmed the theme renders.

**Leftovers (no visual effect, but debt):**
- Dead `.dark` CSS with violet hues (`index.css:56-160`).
- 32 inert `dark:` classes in 14 customer and HomeGenie files.
- Old green `#0B4D2E` in the Razorpay modal theme (`Checkout.js:100`) and in the backend email template (`core.py:403-419`, "AYURVEDA INDIA LLP").
- `design_guidelines.json` still specifies the old green palette.
- Faint `white/xx` glass styles on cream (Toaster, route loader).

**Consistency by panel:**
- Vendor and admin panels use the new colour scales most consistently.
- Public and customer pages rely on the remapped legacy names.

**Responsive:**
- Breakpoint usage: `sm:` 350, `lg:` 166, `md:` 16.
- 19 `overflow-x-auto` table wrappers.
- Landing and vendor layouts were browser-checked earlier at desktop width only.
- **Mobile rendering: NOT VERIFIED in this audit.**

The homepage was not touched.

---

## W. Integrations and deployment

| Integration | Implemented | Configured via (env names) | Local | Production |
|---|---|---|---|---|
| Stripe | yes (official SDK fallback for the private `emergentintegrations` package) | STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET | not exercised | NOT VERIFIED |
| Razorpay | yes | RAZORPAY_KEY_ID, _KEY_SECRET, _WEBHOOK_SECRET | not exercised; **no tests** | NOT VERIFIED |
| UPI manual / COD | yes | COD_MAX_AMOUNT_RUPEES | tested (COD suites) | NOT VERIFIED |
| OTP / SMS (Twilio) | yes, fail-closed | TWILIO_*, OTP_* | test adapter only | NOT VERIFIED |
| Email (Emergent Resend) | yes, invitation only | EMERGENT_EMAIL_KEY, EMAIL_FROM_NAME | — | NOT VERIFIED |
| Images | Emergent storage + Cloudinary | EMERGENT_LLM_KEY, INTEGRATION_PROXY_URL, CLOUDINARY_* (undocumented) | — | NOT VERIFIED; Emergent storage outside Emergent is doubtful |
| Shipping | manual tracking only | — | — | n/a |
| Google login | Emergent Auth, hard-coded demobackend URL | — | — | NOT VERIFIED |
| Frontend / backend hosting | Vercel / Vercel Python | REACT_APP_BACKEND_URL; VERCEL | build passes (2026-11-14) | live site responded earlier; behaviour NOT VERIFIED in this audit |
| DB | Motor / MongoDB | MONGO_URL, DB_NAME | isolated test DB | NOT VERIFIED; **index migration pending** |
| Crons | 2 daily | CRON_SECRET / WEBHOOK_CRON_SECRET | — | NOT VERIFIED |
| CORS | exact origins | CORS_ORIGINS | VERIFIED by `test_vercel_cors_dbdown` | NOT VERIFIED |
| Error monitoring | **none** | — | — | gap |

`deploy/vercel-api/` is a stale alternate deployment: one cron, no `stripe` dependency. Deploying it would break card checkout (PLT-05).

---

## X. Test coverage and results

**Run during this audit** (isolated `hg-test-mongo`, one `hg_audit_<suite>_test` database per suite, serial, `pytest -n 0`):

| Group | Suites | Result |
|---|---|---|
| In-process pytest suites (FastAPI in-process client; no network) | 44 | **984 passed, 0 failed, 0 errors, 0 skipped** |
| Script-style: `test_commission_engine.py` | 1 | **PASS** (30/10/5 pre-GST base, release, idempotency, refund clawback) |
| Script-style: `test_cod_and_badges.py` | 1 | **PASS** (4 checks) |
| `test_financial_engine_isolated.py` | 1 | **1 skipped**: it tests `income_config`, a feature removed in commit `96f8719` (obsolete) |
| Live HTTP suites: `test_health_dashboard` (8), `test_regrequest_flow` (22), `test_it11_emailless` (3), `test_upi_adminlogin` (15), `test_otp_auth` (31), `test_production_hardening` (11), `test_cycle9_upi_ref` (12) | 7 (~102 tests) | **NOT RUN**: they need a deployed backend URL plus admin credentials. Running them would mean touching production or creating accounts, both of which the audit rules forbid. |
| Helper scripts `backend_test.py`, `payflow.py`, `probe_lockout.py` | — | NOT RUN (live HTTP) |

**Test inventory:** 58 files under `backend/tests` (about 15.4k lines). No frontend unit tests. No automated browser test suite in the repository; Playwright checks were run ad hoc during earlier phases.

**Flakiness:** in the 2026-11-14 session, `test_vendor_onboarding` once showed 1 failure and 1 error during an unusually slow run (272 s). The next two runs, and this audit's run, passed. This is suspected load-related flakiness; not reproduced.

**How each area was tested:**

| Level | Covered |
|---|---|
| Unit | rules modules (`cod_rules`, `activation_rules`, `money`, `commission` model) |
| Integration / API (in-process, real MongoDB) | auth, activation, orders, stock, payments-to-paid processing, COD, refunds/returns (3B.7), commission and wallet, withdrawals, vendor lifecycle/onboarding/applications/staff/operations/ledger/settlements, governance, indexes, CORS |
| Browser tested (earlier sessions, ad hoc, local demo environment) | admin onboarding page, vendor panel links (42/42), landing |
| Not verified | Stripe/Razorpay against real gateways; Twilio; email delivery; Cloudinary; Google login; mobile layouts; production data and indexes |

**Untested or weakly tested modules:**
- the Razorpay flow;
- the Stripe webhook (live scripts only);
- admin Settings save (would have caught ADM-01);
- admin reports projection (SEC-02);
- target-role guards (SEC-01);
- the customer variant purchase flow (CAT-01);
- the frontend overall.

A test existing does not mean the feature works from the UI. For example, the backend variant-order path is tested, but no UI ever sends a `variant_sku`.

---

## Y. Master functionality matrix

The Risk column is High, Medium or Low.

| Module | Feature | Backend | Frontend | Database | Permissions | Tests | Actual status | Risk |
|---|---|---|---|---|---|---|---|---|
| Auth | Password login / lockout | ✔ | ✔ | users, login_attempts | ✔ | ✔ | Ready (admin lockout DoS: SEC-10) | Medium |
| Auth | Sign-up verification | ✔ (OTP route unused) | no OTP | users | — | partial | **PARTIAL** (SEC-05) | High |
| Auth | Google login | ✔ (Emergent) | ✔ | users | email match only | ✔ | PARTIAL | High |
| Auth | OTP login | ✔ | ✔ | otp_sessions | ✔ | live suite not run | Implemented; production NOT VERIFIED | Medium |
| Auth | Forgot password | admin queue / Google | ✔ | password_reset_requests | ✔ | ✔ | PARTIAL | Low |
| Admin | User management | ✔ | ✔ | users | **no target guard** | partial | **Not safe** (SEC-01, 03, 04) | High |
| Admin | Admin / role management | ✘ | ✘ | — | — | — | MISSING (OPS-01) | High |
| Admin | Settings | ✔ | **drops fields** | business_settings | ✔ | ✘ | **BROKEN** (ADM-01) | High |
| Admin | Reports | ✔ | ✔ | many | **leaks** | ✘ | **Not safe** (SEC-02) | High |
| Admin | Audit log | ✔ | ✔ | audit_logs | erasable | partial | PARTIAL (AUD-01) | Medium |
| HomeGenie | Activation RED→GREEN | ✔ | ✔ | users, activation_history | ✔ | ✔ | **Ready** | Low |
| HomeGenie | Seller attribution | ✔ | landing only | orders.seller_user_id | ✔ | ✔ (API) | **PARTIAL** (HG-01) | High |
| HomeGenie | Commission engine | ✔ | dashboard | commissions, plans, wallets | ✔ | ✔✔ | Ready with limitations (FIN-05) | Medium |
| HomeGenie | KYC | ✔ | ✘ | kyc_records (plaintext) | any admin edits | partial | **BACKEND ONLY** | High |
| HomeGenie | Withdrawals | ✔ | ✔ | withdrawal_requests | ✔ maker-checker | ✔ | **Blocked in practice** (HG-02) | High |
| Customer | Browse / search / filter | list only | list only | products | — | partial | PARTIAL | Medium |
| Customer | Variant purchase | ✔ | ✘ | — | — | API only | **BROKEN** (CAT-01) | High |
| Customer | Checkout / tax | ✔ | ✔ | orders | ✔ | ✔ | PARTIAL (CAT-02 flat GST) | High |
| Customer | Cancel / return | ✔ | ✘ | return_cases, refund_cases | ✔ | ✔ | BACKEND ONLY | Medium |
| Customer | Address book / wishlist | ✘ | ✘ | — | — | — | MISSING | Low |
| Payments | Stripe / Razorpay | ✔ | ✔ | payment_transactions, webhook_events | ✔ | live / none | Implemented; NOT VERIFIED (FIN-06, FIN-14) | High |
| Payments | UPI confirm / manual pay | ✔ | ✔ | orders | **any admin** | live only | **Not safe** (FIN-01) | High |
| Payments | COD collect / discrepancy | ✔ | ✔ (collect) / ✘ (resolve) | orders | ✔ | ✔✔ | Ready with limitations (FIN-11) | Medium |
| Catalogue | Categories | seed only | chips | product_categories | — | ✔ | PARTIAL | Low |
| Catalogue | Vendor products + approval | ✔ | ✔ | products | ✔ | ✔ | Ready with limitations (CAT-04, VEN-04) | Medium |
| Catalogue | Admin products | ✔ | ✔ | products | any admin | partial | PARTIAL (CAT-03, CAT-06) | Medium |
| Inventory | Reservation / journal / recovery | ✔ | vendor ✔ | stock_txns, stock_movements | ✔ | ✔✔ | Ready with limitations (CAT-03, FIN-08) | Medium |
| Orders | Vendor fulfilment | ✔ | ✔ | orders.fulfilments | ✔ | ✔ | **Unsafe for UPI** (FIN-02) | High |
| Orders | Admin order operations | ✔ | ✔ | orders | any admin delete | partial | PARTIAL (FIN-07, ORD-02) | High |
| Returns / refunds | Refund cases (3B.7) | ✔ | ✘ | refund_cases, order_refunds | finance (no checker) | ✔✔ | BACKEND ONLY; engine ready | Medium |
| Vendor | Applications / onboarding / approval | ✔ | ✔ | vendor_applications, vendors | ✔ super_admin | ✔✔ | **Ready with limitations** (VEN-01, VEN-02) | Medium |
| Vendor | Staff and permissions | ✔ | ✔ | vendor_members | ✔ allow-list | ✔ | Ready with limitations (VEN-07) | Low |
| Vendor finance | Ledger / settlements | ✔ | vendor read-only; admin ✘ | vendor_ledger, settlements | finance (dual approval off) | ✔ | **Not ready** (FIN-03, OPS-02) | High |
| Vendor | Bank change | ✔ | vendor ✔ / admin ✘ | vendor_change_requests | single approver | ✔ | Not safe (FIN-04) | High |
| Support | Tickets | vendor ✔ | vendor ✔ / admin ✘ | support_tickets | ✔ | ✔ | PARTIAL | Low |
| Notifications | In-app / SMS / email | ✔ | ✔ | notifications | ✔ | partial | PARTIAL (email = invitation only, broken link) | Medium |
| Platform | Indexes | specs ✔ | — | 46 specs | — | ✔ | **Production migration unconfirmed**; hot ids unindexed (PLT-02, PLT-03) | High |
| Platform | Monitoring / headers | ✘ | ✘ | — | — | — | MISSING (PLT-06) | Medium |

---

## Z. Defect and risk register

Notes on this register:
- **Reproduction** gives the precondition; **Fix** is a suggestion only. Nothing was fixed during this audit.
- "VERIFIED" means I checked the code myself during this audit. Other entries come from line-cited code reading by the audit reviewers. "(suspected)" means the effect is inferred from the code path and not confirmed end to end.
- Dependencies between items are shown in the roadmap (section AB).

### P0 — Critical

| ID | Module | Location | Description / reproduction / impact | Suggested correction |
|---|---|---|---|---|
| SEC-01 | Admin users | admin_routes.py:989-1008 | **VERIFIED.** `admin_reset_password` (any admin role) has no target-role check and returns the new plaintext password. A support_admin can POST `/api/admin/users/{super_admin_id}/reset-password` and log in as super admin. Impact: full privilege escalation; defeats every maker-checker. | Refuse admin-role targets unless the actor is super_admin; never return plaintext (one-time reset link or forced change); audit the reason. |
| SEC-02 | Admin reports | admin_routes.py:1063 | **VERIFIED.** `get_report` returns `find(q, {"_id":0})`, i.e. full documents. `/reports/registrations` exposes `password_hash` and raw `aadhaar_number` of all users to every admin role; other reports return full rows. | Project to the report's `fields`; mask Aadhaar; add a test. |

### P1 — High

| ID | Module | Location | Description | Suggested correction |
|---|---|---|---|---|
| SEC-03 | Admin users | admin_routes.py:901-920, 857-866 | Any admin can edit any user's email, mobile or Aadhaar (no validation, no target guard) and block any account including super_admin. Changing a victim's mobile allows OTP-login takeover. | Target-role guard; validation; notify the old contact. |
| SEC-04 | Admin users | admin_routes.py:857-866 + 575 | Unblock sets `account_status="active"` on deleted, `pending_approval` and `invited` accounts, bypassing invitation-only activation. | Restore the previous status; refuse not-activated and deleted accounts. |
| SEC-05 | Identity | auth_routes.py:117-175 (VERIFIED :128-160), Register.js:30 | register-request creates live accounts with no OTP and trusts the client's `google_verified` flag. Google login links by email match. An attacker pre-registers the victim's email and receives the victim's later Google logins. | OTP at sign-up (the existing `/auth/register`); verify Google server-side; link only verified emails. |
| SEC-06 | KYC | admin_routes.py:435-456 | Any admin can change PAN or bank details on a verified KYC record; it stays "verified"; the audit records field names only. Payout diversion. | Finance roles only; reset to pending; second verifier; masked old and new values in the audit. |
| FIN-01 | Payments | shop_routes.py:740-804 | UPI confirm and manual payment are open to all 4 admin roles: free-text reference, no amount check, no UTR uniqueness, no checker. This creates vendor SALE entries, commissions and activation eligibility from fake payments. | Finance roles only; amount and UTR required; unique UTR index; two-person verify. |
| FIN-02 | Orders / vendor | vendor_routes.py:611-613, 715-726 | **VERIFIED.** Vendors see and can fulfil `claimed` (unverified UPI) orders. The claim is sent before the customer pays. Goods are shipped unpaid. | Vendor view and transitions only for `paid`, `cod_pending`, `partially_refunded`. |
| FIN-03 | Vendor finance | ledger.py:169-185; finance_routes.py:28, 276-300 | **VERIFIED.** Settlement availability ignores delivery and the return window; dual approval is off by default. Payouts can happen before dispatch, leaving negative balances. | Eligible only after delivery plus the return window with no open case; dual approval always on. |
| FIN-04 | Finance controls | finance_routes.py:203, 243; governance_routes.py:232; admin_routes.py:953, 371; returns_routes.py:247-330 | No maker-checker for adjustments (any signed amount), bank-change approval, wallet credit (up to ₹1 crore), commission release, or refund initiate→confirm. One finance admin can switch dual approval off. One insider can move money end to end. | Two-person rule enforced in the backend for each; lock the policy flag. |
| FIN-05 | Commission | commission.py:308-313 | Release window counts from payment, not delivery. Commission becomes withdrawable before the return window ends, so clawbacks produce negative wallets. The notification text claims "after delivery". | Anchor to the delivered timestamp (needs an owner decision). |
| FIN-06 | Payments | shop_routes.py:343, 375, 621 | A second captured payment (two tabs, or Stripe then Razorpay) returns silently. The customer is double-charged, nobody is flagged, and the Stripe `amount_total` is not compared with the order. | Reuse the open session; flag duplicates as `needs_refund`; compare amounts. |
| FIN-07 | Orders | admin_routes.py:334-347 | Any admin can hard-delete unpaid, claimed, COD-pending or fulfilment-in-progress orders. It deletes payment_transactions and **does not release reserved stock**. | Replace with cancel through the stock path; finance or super_admin only; soft delete. |
| CAT-01 | Customer shop | ProductDetail.js, Checkout.js; shop_routes.py:107-111 | **VERIFIED.** No customer screen sends `variant_sku`, and the server requires it for variant products. Every product with variants is unbuyable. | Render variants on the product page; send `variant_sku`. |
| CAT-02 | Tax | shop_routes.py:94, 143 | **VERIFIED.** Every order uses the global `gst_percent` (default 5%), ignoring per-product GST and HSN. Tax is added on top of the selling price. Wrong invoices; compliance exposure. | Tax per line from the product; snapshot HSN; owner decision on tax-inclusive pricing. |
| CAT-03 | Stock | admin_routes.py:148-161, AdminProducts.js:39-47; vendor_routes.py:354-373 | Admin edit (including the "activate" toggle) `$set`s a stale `stock`; vendor variant edit `$set`s stale variant stock. Lost updates cause oversell, with no journal entry. | Never `$set` stock in edits; atomic, journaled adjustment endpoint. |
| HG-01 | HomeGenie selling | Landing.js:61 (VERIFIED), Referral.js, lib/sellerRef | The seller ref is captured only from `/?ref=` on Landing; no screen produces that link; the Referral page shares a sponsor link; the ref is never cleared (wrong attribution on shared devices). Commissions are almost never earned. | Share-product and share-shop links; capture on all public routes; clear after a paid order or logout. |
| HG-02 | Withdrawals | core.py:226; wallet_routes.py:132; admin_routes.py:576 | KYC is required by default, but there is no KYC screen (user or admin). With only one admin creatable, payer ≠ approver blocks every payout. | KYC screens + admin user management (OPS-01). |
| VEN-01 | Vendor onboarding | vendor_invitations.py:38-43 | Owner-invitation email contains a relative link; when the email is "delivered" the token is hidden from the admin. Admin-created vendors cannot activate once email is configured. | Absolute URL from a FRONTEND_ORIGIN setting; always show the token to super_admin. |
| VEN-02 | Vendor apply | vendor_applications.py:102-119; vendor_onboarding.py:373-377 | Public apply creates an **active** vendor login for any mobile number with no OTP. Squats the number (the real owner can no longer register); spam creates user and vendor rows. | OTP-verify before creating the account. |
| ADM-01 | Settings | AdminSettings.js:25-30 | Save sends 3 non-existent fields plus a few real ones. Commission %, return window, COD switch, withdrawal switch and point value are **not saved**, yet a success toast appears. | Send the displayed fields; re-render from the server response; add a test. |
| AUD-01 | Audit | admin_routes.py:1029-1043 | super_admin can delete all audit logs, including "protected" markers. No tamper evidence. | Append-only (remove delete) or a hash-chained archive. |
| OPS-01 | Governance | — (no endpoint) | No API to create, disable or re-role admins. Two-person finance rules cannot be satisfied with one super_admin. | Super-admin-only admin management with audit. |

### P2 — Medium

| ID | Location | Description |
|---|---|---|
| OPS-02 | frontend | Backend-only workflows with no UI. **Admin:** KYC review, refund cases, returns decision and policy, settlements, ledger, adjustments, finance policy, COD discrepancy resolve, bank changes, support replies, commissions, vendor policy, owner-invitation revoke. **Customer:** cancel, return, KYC, profile edit, change password and mobile. |
| CAT-04 | vendor_routes.py:569-576, 905-907; shop_routes.py:43 | **VERIFIED.** Archived products can be re-listed or approved and appear in the shop (the shop ignores `archived`). |
| CAT-05 | admin_routes.py:169 | Admin takedown only sets `is_active=False`; the vendor can re-list immediately. |
| CAT-06 | admin_routes.py:117-145 | Admin products have no price, MRP, stock or category validation; free-text category; zero or negative price possible (suspected total ≤ 0). |
| VEN-04 | vendor_routes.py:507, 541-551 | CSV import skips the Cloudinary ownership check, wipes absent fields on update, and has no DuplicateKeyError guard (500 and partial import). |
| VEN-05 | VendorProfile.js:47, 151; Governance.js:116 | Onboarding applicants see an editable form (every save returns 409); `active` vendors' legal and bank edits are silently dropped; no bank-change panel for `active`. |
| VEN-06 | vendor_routes.py:729-730 | Vendor self-attests "delivered" with a 3-character note, which starts the return-window clock. No proof and no dispute path. |
| VEN-07 | VendorLayout.js; vendor_routes.py:674-683; vendor_dashboard.py:202 | The staff menu shows areas the backend refuses; staff without `reports.read` land on an erroring dashboard; `orders.read` and `reports.read` expose finance figures; `/vendor/me` passes internal review fields to staff. |
| VEN-08 | ledger.py:18, 187 | Vendor finance says balances are "before commissions", but commissions are applied. |
| VEN-09 | vendor_applications.py:195-230, 311 | Application edits are not propagated to the pre-created account; a declined applicant who re-applies gets no account and can't be converted. |
| VEN-10 | ledger.py:70-89; commercial_terms.py | Commission can be charged retroactively when an agreement is approved after its effective date; there is no acceptance requirement (suspected). |
| FIN-08 | stock.py:401-429; Checkout.js:70-72 | UPI claims never expire, so stock stays reserved indefinitely; there is no "reject UPI claim" action. |
| FIN-09 | commission.py:299 | Release cron reads `to_list(5000)` unsorted; due rows can be starved at scale. |
| FIN-10 | wallet_routes.py:144-150 | No bank snapshot on withdrawal or settlement; finance cannot see where to pay inside the app. |
| FIN-11 | shop_routes.py:253-260; finance_routes.py:413 | COD collected or resolved forces `status=delivered` regardless of fulfilment; commission and SALE start. |
| FIN-12 | returns_routes.py:300-327, 443 | A refund case can be "confirmed" for ₹0 on an unpaid (COD-pending or claimed) order; the customer is told "Refund processed". |
| FIN-13 | ledger.py:143; returns_routes.py:127-132, 408-416 | The vendor is debited the GST share on vendor-specific refunds, although the SALE was value only. |
| FIN-14 | shop_routes.py:444-449 | Razorpay webhook records `event_id` before processing; no unique index; a failed processing run is treated as a duplicate on retry. |
| FIN-15 | admin_routes.py:215 | support_admin can cancel paid orders (sale reversals and refund cases). |
| ORD-01 | vendor_routes.py:756-759 | Mixed platform and vendor orders are rolled up to `delivered` while platform lines are unshipped. |
| ORD-02 | admin_routes.py:215-269 | Admin status changes don't update `fulfilments` (suspected divergence). |
| ORD-03 | vendor_routes.py:86-90 | A suspended vendor cannot act on existing paid orders or returns, and there is no admin fulfilment override. |
| ADM-05 | admin_routes.py:63-72 | Dashboard revenue is miscomputed (see D.1). |
| ADM-06 | admin_routes.py (lists) | No pagination: users, orders, withdrawals, commissions and payments cap at 1000; vendors at 500; products at 200. Silent truncation. |
| HG-03 | wallet_routes.py:226 | Dashboard "pending" mixes withdrawals and commission; team commission and chart ignore reversals; badge bucketed by `created_at`. |
| SEC-09 | auth_routes.py:86 | `/auth/send-otp` and change-mobile send have no IP rate limit (SMS pumping). |
| SEC-10 | auth_routes.py:448-458 | Anyone can lock the super_admin username for 15 minutes (admin lockout DoS). |
| SEC-11 | auth_routes.py | `/auth/login` and Google accept admin roles, sidestepping the admin login limits. |
| SEC-12 | auth_routes.py:638; core.py:84 | Logout does not revoke the JWT (7-day life, localStorage); no 401 interceptor. |
| SEC-13 | auth_routes.py (change-mobile) | Changing the mobile needs no password re-check and sends no alert to the old number. |
| SEC-15 | core.py:435 | Rate-limit key is the first `X-Forwarded-For` value (suspected spoofable). |
| SEC-16 | vendor_staff_routes.py | Suspended or revoked staff keep a working login and `/app/*` access. |
| SEC-17 | server.py:257 | super_admin password is reset from env at every cold start; a UI change is reverted. |
| PLT-02 | db_indexes.py | No index on `users.id`, `orders.id`, `products.id`, `payment_transactions.session_id`, `webhook_events.event_id`, `login_attempts.identifier`, `kyc_records.user_id`. Every authenticated request does `users.find_one({"id"})`, so collection scans grow with data. |
| PLT-03 | server.py:194 | Indexes are created only by the migration script; the production run is unconfirmed. If it hasn't run, the uniqueness guarantees (op_key, wallets, rate limits, vendor) are absent. |
| PLT-05 | deploy/vercel-api | Stale alternate deployment (one cron, no stripe). |

### P3 — Low

| ID | Description |
|---|---|
| SEC-18 | Open redirect: Stripe success and cancel URLs come from the client `origin_url` (shop_routes.py:335). |
| SEC-19 | `OTP_PEPPER` defaults to empty (providers.py:20) and is not checked at startup. |
| SEC-20 | KYC PAN, Aadhaar and bank details stored in plaintext. |
| SEC-21 | No admin MFA. |
| SEC-22 | Inconsistent password minimums (6 / 8 / 8 with letters and digits). |
| SEC-23 | `/payments/status/{session_id}` is unauthenticated; `/products?active=false` and `/products/{id}` are public for inactive products. |
| SEC-24 | Admin email written to logs; 4 MB profile-photo data URL stored in and returned with the user document. |
| ADM-07 | CSV report export has no formula-injection guard (admin_routes.py:1071-1083). |
| ADM-08 | Duplicate SKU on admin edit returns a 500 DuplicateKeyError. |
| ADM-09 | Unaudited actions: password-reset dismiss, finance reconcile, vendor document deletion. |
| ADM-10 | Misleading UI: "Permanently DELETE" wording on deactivate; Benefits and wallet-credit buttons shown to roles that get 403; the commissions report names fields that don't exist. |
| CAT-07 | Admin SKUs not upper-cased (case duplicates possible); a product SKU equal to another product's variant SKU is blocked only in app code. |
| CAT-08 | Any https image URL accepted (hotlinking); upload trusts the client Content-Type; `_public_url` built from the Host header (suspected). |
| VEN-11 | `/decision approve` on a rejected onboarding-path vendor skips final review (UI hides it; backend allows). |
| VEN-12 | `active` status only partly supported (finance balances, profile screens). |
| VEN-13 | Reinstated vendors' products stay paused; double-notify race on product decision. |
| VEN-14 | `sweep_dispatch_deadlines` crashes if the vendor document is missing. |
| PLT-06 | No error monitoring, no security headers or CSP, no global exception handler. |
| PLT-07 | Design debt: dead `.dark` violet CSS, 32 `dark:` classes, old green in the Razorpay theme and email template, orphaned ThemeToggle, faint glass styles. |
| PLT-08 | Stale docs: README (1 line), test_result.md, design_guidelines.json (old palette), VENDOR_PANEL_AUDIT_AND_PLAN.md, the status PDF; stale code comments (vendor_lifecycle.py:31, vendor_applications.py docstrings, ledger.py:18). |
| PLT-09 | No idempotency key on `POST /orders` or `POST /withdrawals` (double-click duplicates). |
| PLT-10 | `test_financial_engine_isolated.py` is obsolete (feature removed in 96f8719); script-style tests hard-code `/app/backend/.env`. |

### Documentation vs code discrepancies

| Document | Claim | Code |
|---|---|---|
| MASTER_SPEC §1 | A `customer` role exists | No customer role; all buyers are `distributor` |
| MASTER_SPEC §3.9 | `admin_vendor_invite` converts an account to a vendor | Retired; returns 410 |
| MASTER_SPEC §3.5 | Commission released "after the return window" | Window counted from payment |
| MASTER_SPEC §3.8 | Cash wallet and points are separate | Single points wallet, cash at ₹1 per point |
| MASTER_SPEC §3.1 | Money stored as paise | Products and `payment_transactions.amount` are floats |
| MASTER_SPEC §3.10 | Withdrawal paid by "a different finance user" | No way to create one |
| MASTER_SPEC (general) | — | Predates Phase 3B.7 (refund cases, returns policy, G1/G2) and the vendor applicant flow |
| VENDOR_PANEL_AUDIT_AND_PLAN.md | 5 vendor pages; variants, CSV, returns, ledger, settlements and staff missing | 23 pages; all implemented |

---

## AA. Business readiness scorecard

"Ready" means fit for real operations as built today.

| # | Area | Assessment | Basis |
|---|---|---|---|
| 1 | Customer experience | **Not ready** | Variant products unbuyable (CAT-01), flat GST (CAT-02), no search or filter, no cancel or return UI, unverified sign-up |
| 2 | Admin operations | **Not ready** | Settings broken (ADM-01), many backend-only workflows (OPS-02), any-admin order delete and mark-paid |
| 3 | Super Admin governance | **Not ready** | SEC-01, SEC-02, no admin management (OPS-01), erasable audit (AUD-01) |
| 4 | HomeGenie operations | **Not ready** | Seller attribution (HG-01), withdrawals blocked (HG-02); activation itself is ready |
| 5 | Vendor onboarding | **Ready with limitations** | 51 + 46 + 78 tests pass; invitation email link (VEN-01) and applicant OTP (VEN-02) outstanding |
| 6 | Vendor Panel | **Ready with limitations** | All screens built and tested; FIN-02 must be fixed before UPI is used; CAT-04 |
| 7 | Vendor staff | **Ready with limitations** | Backend allow-list sound; menu and data leakage gaps (VEN-07) |
| 8 | Product catalogue | **Not ready** | CAT-01, CAT-02, no category management, no search |
| 9 | Inventory | **Ready with limitations** | Reservation, journal and recovery tested; CAT-03 stock overwrite; FIN-08 UPI holds |
| 10 | Orders and fulfilment | **Not ready** | FIN-02, FIN-07, FIN-11, ORD-01 |
| 11 | Returns and refunds | **Not ready** (engine ready) | 3B.7 engine tested; no customer or admin UI; FIN-12, FIN-13 |
| 12 | HomeGenie commissions | **Ready with limitations** | Engine well tested; release timing (FIN-05); attribution (HG-01) |
| 13 | Vendor finance | **Not ready** | FIN-03, FIN-04, no admin finance UI |
| 14 | Payments | **Not ready** | FIN-01, FIN-06, FIN-14; gateways NOT VERIFIED in production |
| 15 | Security | **Not ready** | Two P0s plus SEC-03 to SEC-06 |
| 16 | Mobile responsiveness | **Not verified** | Responsive classes present; no mobile check in this audit |
| 17 | Integrations | **Not verified** | No live provider exercised; email link broken; Emergent dependencies |
| 18 | Deployment readiness | **Ready with limitations / not verified** | Build passes and CORS is tested; index migration unconfirmed (PLT-03); no monitoring |

No numeric scores are given; the assessments rest on the evidence cited.

---

## AB. Recommended development roadmap

Batches are ordered by risk. Each is small enough to review on its own. **None has been started.**

**Owner decisions needed before the batches marked †:**
1. Are selling prices GST-inclusive (MRP-style) or exclusive?
2. Commission release anchor: delivery + N days, or payment + N days?
3. Vendor settlement eligibility: delivery + return window?
4. Who may confirm UPI and manual payments, and is a second person required?
5. Should "customer" become a distinct role from RED distributor?
6. Should plain `admin` be allowed final vendor approval? (Currently super_admin only.)

### Batch 0 — Security hotfix (P0) — Priority: immediate
- **Objective:** close privilege escalation and data leakage.
- **Scope:** SEC-01, SEC-02, SEC-03, SEC-04, SEC-06.
- **Backend:**
  - target-role guards on reset, edit and block;
  - no plaintext password in responses;
  - report projection;
  - unblock restores the prior status;
  - KYC edit limited to finance roles and resets verification.
- **Frontend:** reset-password dialog no longer shows a password (shows a one-time link or a "forced change" note).
- **Tests:** new negative tests (support_admin → super_admin target refused; report rows contain only listed fields; unblock of a pending owner refused; KYC edit resets status).
- **Acceptance:** all new and existing tests pass; no admin endpoint returns `password_hash` or `aadhaar_number`.
- **Risks:** low; touches 4 endpoints.
- **Dependencies:** none.

### Batch 1 — Payment and order integrity — Priority: P1 †(4)
- **Scope:** FIN-01, FIN-02, FIN-06, FIN-07, FIN-08, FIN-14, FIN-15.
- **Backend:**
  - finance-only mark-paid with amount and unique UTR (plus a checker if decided);
  - vendor view and fulfilment only on paid or COD-pending orders;
  - duplicate-capture detection;
  - replace order delete with cancel-via-stock;
  - UPI claim expiry and reject;
  - Razorpay webhook processed-after-success with a unique index;
  - restrict paid-order cancel.
- **Frontend:** admin UPI confirm form with amount and UTR; a "reject claim" button.
- **Tests:** an API test per rule; extend `test_order_lifecycle_races` and the COD suites.
- **Acceptance:** an unpaid claimed order is invisible to vendors; the same UTR cannot pay two orders; a deleted order never leaks stock.
- **Risks:** medium (payment paths).
- **Dependencies:** Batch 0.

### Batch 2 — Admin foundations — Priority: P1
- **Scope:** ADM-01 (Settings save), OPS-01 (super-admin-only admin management: create, disable, change role, with audit), AUD-01 (append-only audit), SEC-17 (stop the env re-seed overriding UI changes, or document it).
- **Tests:** settings round-trip for every field; admin-management permission tests.
- **Acceptance:** every field on the settings screen persists; super_admin can create accounts_admin, which unblocks the two-person rules.
- **Dependencies:** Batch 0.

### Batch 3 — Catalogue purchase correctness — Priority: P1 †(1)
- **Scope:** CAT-01 (variant selector on the product page; `variant_sku` sent through cart and checkout), CAT-02 (per-line GST and HSN snapshot), CAT-03 (remove stock from edit bodies; journaled adjust endpoint for admin), CAT-04, CAT-05 (archived and takedown rules), CAT-06 (admin product validation and category picker from the 4 pillars).
- **Tests:** API test plus a Playwright purchase of a variant product; tax calculation tests per pillar.
- **Acceptance:** a variant product can be bought from the UI; invoice GST per line matches the product rate.
- **Dependencies:** none (can run in parallel with Batch 1).

### Batch 4 — Identity verification — Priority: P1
- **Scope:** SEC-05 (OTP sign-up via the existing `/auth/register`, server-side Google verification, link only verified emails), VEN-02 (OTP before vendor applicant account creation), SEC-09 (rate limits on OTP send), SEC-10/11 (admin login separation and lockout keyed by IP + user), SEC-12 (token revocation at logout), SEC-16 (revoked staff login).
- **Tests:** auth suites extended; `test_otp_auth` re-pointed at an in-process client so it can run locally.
- **Risks:** medium (sign-up UX change; depends on Twilio configured in production).
- **Dependencies:** Twilio production check.

### Batch 5 — HomeGenie selling and payouts — Priority: P1 †(2)
- **Scope:** HG-01 (share-product and share-shop links, ref capture on all public routes, clear after a paid order or logout), HG-02 (user KYC form plus admin KYC review screen), FIN-05 (release anchor), FIN-09 (sorted, paged release cron), HG-03 (dashboard figures), FIN-10 (bank snapshot on withdrawal; show payout details to finance).
- **Tests:** attribution end to end; KYC → withdrawal → approve → pay by two admins.
- **Acceptance:** a HomeGenie can share a product, earn on a paid order, and withdraw after KYC.
- **Dependencies:** Batch 2 (a second finance admin).

### Batch 6 — Vendor finance controls — Priority: P1 †(3)
- **Scope:** FIN-03 (settlement eligibility after delivery + return window), FIN-04 (two-person rule for adjustments, bank changes, wallet credits, refunds, commission release; dual approval always on), FIN-13 (GST share on vendor refunds), VEN-10 (no retroactive commission), FIN-12 (no refund case on unpaid orders), FIN-11 (COD collected ≠ delivered).
- **Tests:** extend `test_finance_ledger`, `test_refund_return_controls`.
- **Dependencies:** Batch 2.

### Batch 7 — Admin operations screens — Priority: P2
- **Scope (OPS-02, admin side):** refund cases, returns arbitration and policy, settlements and ledger and adjustments, finance policy, COD discrepancies, bank-change approvals, support replies, commissions, owner-invitation revoke; order detail view; pagination and server-side search (ADM-06); dashboard revenue (ADM-05).
- **Tests:** a Playwright smoke test per screen; existing API tests.
- **Dependencies:** Batches 1 and 6 (so the screens sit on final rules).

### Batch 8 — Customer self-service — Priority: P2
- **Scope:** cancel and return request UI, refund status, profile edit, change password and mobile, address book, product search, filters and sort, attribute display; "Pay now" fix; optional wishlist.
- **Dependencies:** Batch 3.

### Batch 9 — Vendor panel polish — Priority: P2
- **Scope:** VEN-01 (absolute invitation link plus token visible to super_admin), VEN-04 (CSV import), VEN-05 (profile screens per status), VEN-06 (delivery proof and dispute), VEN-07 (permission-aware menu and data trimming), VEN-08, VEN-09, ORD-01/02/03 (fulfilment consistency and suspended-vendor override).
- **Dependencies:** none.

### Batch 10 — Platform hardening and cleanup — Priority: P2/P3
- **Scope:**
  - confirm the production index migration and add hot-id indexes (PLT-02, PLT-03);
  - error monitoring and security headers (PLT-06);
  - remove `deploy/vercel-api` (PLT-05);
  - idempotency keys (PLT-09);
  - P3 security items (SEC-18 to SEC-24);
  - design leftovers (PLT-07);
  - documentation refresh: README, spec update for 3B.7 and the vendor applicant flow, retire stale docs (PLT-08);
  - retire the obsolete test (PLT-10);
  - a mobile responsive pass with screenshots.
- **Dependencies:** none; can run alongside other batches.

---

### Audit integrity statement

- No source file, test, schema, database record or dependency of the project was changed. Nothing was committed, pushed or deployed. The only file created is this report.
- Tests were run only against the isolated local `hg-test-mongo` (127.0.0.1:27018) in throwaway `hg_audit_*_test` databases. A scratch virtualenv outside the repository was used. The private `emergentintegrations` package was not installable, and the code's own fallback was used.
- Production, Atlas, live gateways and live customer data were not accessed. All production statements are NOT VERIFIED.
- No secret values appear in this report.
