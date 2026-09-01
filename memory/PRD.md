# PRD — Anjali Herbal Life Ayurveda India LLP — Distributor & E-Commerce Platform

## Original Problem Statement
Phase 1 MVP of a production-oriented Distributor & E-Commerce Management Platform for Anjali Herbal Life Ayurveda India LLP. Premium bilingual (English/हिन्दी) enterprise UI. RED/GREEN distributor status, ₹1,500 activation purchase, ₹100 referral commission, immutable wallet ledger, KYC, withdrawals, admin panel, reports, notifications, audit logs. Architecture ready for Phase 2/3.

## Stack (as built)
- Frontend: React 19 + Tailwind + shadcn/ui + framer-motion + recharts (CRA/craco, `@/` alias)
- Backend: FastAPI + MongoDB (motor), JWT Bearer auth (bcrypt), modular routers
- Payments: Stripe via emergentintegrations (currency INR), server-side verified. Stripe claimable sandbox not available for India → shared test key `sk_test_emergent` used.
- i18n: custom EN/HI dictionary, persisted, Noto Sans Devanagari for Hindi

## User Choices
FastAPI+Mongo+React · Stripe · Email+Password with email OTP (OTP delivery MOCKED, returned as dev_otp) · dummy logo (user to upload) · full end-to-end Phase 1

## Personas
- Visitor → Distributor (RED then GREEN) → Sponsor · Super Admin (sachin.shukla2196@gmail.com)

## Implemented (2026-06)
- Auth: register with OTP, unique ANJxxxxxx distributor id, login, RBAC (super_admin/admin/distributor/customer), brute-force lockout, audit logs
- Products catalogue (seeded incl. ANJ-STARTER ₹1,500 activation product), cart, checkout, Stripe payment, order + invoice, order statuses
- GREEN activation on verified qualifying payment (atomic, idempotent); activation_records
- Referral: relationship stored at register, self/invalid-sponsor prevention, referral link + QR + share (WhatsApp/Email/SMS)
- Referral commission ₹100 to GREEN sponsor when referred user activates — immutable ledger, idempotent (no duplicates)
- Wallet: available/pending/earned/withdrawn + transactions ledger
- Withdrawals: request (GREEN + verified KYC + min amount + balance) → admin approve/mark_paid/reject (refund)
- KYC: submit (masked PAN/Aadhaar/bank) → admin verify/reject
- Distributor dashboard (stat cards, RED activation banner, income chart, quick actions, recent orders/txns), notifications
- Admin panel: dashboard stats, users, products CRUD, orders + status, KYC review, withdrawals review, commissions, settings (activation amount/commission/GST/etc configurable), reports (9 types) + CSV export, audit logs
- Responsive: desktop collapsible sidebar, mobile bottom nav + more drawer
- VERIFIED: backend 28/28 pytest; critical business flow (RED→GREEN→₹100 commission, idempotent, invoice) verified via production activation path

## Implemented (2026-06 — fork continuation)
- Manual PhonePe/UPI QR checkout: POST /api/payments/upi-claim (order -> 'claimed') + admin PUT /api/admin/payments/upi-confirm/{id} (idempotent -> paid+invoice, reuses verified GREEN activation/commission path). Checkout.js QR panel + AdminOrders "Confirm UPI". VERIFIED E2E (iteration_7/8).
- Secured/isolated Admin login: hidden route /admin-secure-login + POST /api/auth/admin-login (email+password+ADMIN_PASSCODE via hmac.compare_digest, admin-roles gate, 15-min brute-force lockout). Passcode: Anjali@Secure#2026 (backend .env). Public demo login buttons REMOVED from /login. VERIFIED.
- Dark/Light theme: ThemeContext + ThemeToggle in distributor & admin headers, persisted (localStorage anj_theme), Tailwind class dark mode + token overrides in index.css. WCAG AA verified (all CTAs/badges/banners ≥4.5:1).

## Implemented (2026-06 — session 2)
- Admin login hardened: username `admin.rahulnirwana` (or email) + password + passcode `anj000088sk` (backend .env ADMIN_PASSCODE, ADMIN_USERNAME). Password/passcode fields have show/hide eye toggle. Endpoint /api/auth/admin-login accepts username OR email. VERIFIED (iteration_9, 100%).
- Manual UPI **Reference ID now MANDATORY**, entered by admin in a confirm modal on /admin/orders; stored as order.payment_reference; shown in new "Reference ID" column; admin Orders page shows UPI stat cards (awaiting-confirm count + collected total). VERIFIED.
- Checkout GST now server-driven from /api/settings/public gst_percent (was hardcoded 5%). VERIFIED at 5% and 12%.
- Dark/Light theme toggle added to public Landing/home header (persisted via localStorage anj_theme). Landing interactivity boosted (hero gradient orbs, floating badge, card hover lift, global button active-scale). VERIFIED.

## Fix (session 7) — BETA request/approval registration + demo cleanup
- NO-OTP registration: POST /api/auth/register-request (name, mobile, password, email optional, sponsor/address optional) -> PENDING registration_requests; user sees "wait for Admin approval". Register.js is now a single-step form + pending screen.
- Admin approval on /admin/users (Registration Requests card): GET/approve/reject. Approve -> next_distributor_id() (ANJxxxxxx, unique), user status RED + account_status active + wallet created; audited.
- Login widened: /api/auth/login accepts Distributor ID / mobile / email + password. Login.js input now type=text.
- CRITICAL fixes (found by testing agent, iteration_10/11): users.email unique index rebuilt with partialFilterExpression {email:{$type:string}} + drop old email_1 (multiple email-less users now allowed); approve insert try/except -> 400 friendly. Verified 24/24 backend + 7/7 browser (iteration_11).
- reset-data now also clears registration_requests. SEED_DEMO=false.

## Deployment Readiness (2026-06 — session 2)
- Passed deployment_agent scan with ZERO blockers. Fixed 3 issues found:
  1. providers.py OTP cleanup: destructive `delete_many` → non-destructive `update_many` (marks prior pending OTPs used:True). Verified send-otp + register still work.
  2. shop_routes.py create_order: N+1 removed — products batch-fetched via `find({"id":{"$in":ids}})`. Verified order total correct.
  3. wallet_routes.py /api/team: N+1 removed — users batch-fetched via `$in` + downline counts via single `$group` aggregation (~1001 queries → 3). Verified total/active/downline_count.
- NOTE: The "Frontend Preview Only / Wake up servers" banner + 404s are Emergent PREVIEW dormancy behavior only; they do NOT occur on production. Preview backend verified healthy (/health 200, all APIs 200/401 as expected).
- Referral/sponsor ID is now MANDATORY at registration (send-otp + register validate it; frontend field required with helper text EN/HI).

## Implemented (2026-06 — session 3)
- Razorpay online payment (test key rzp_test_TU3scdWQy95DIu) wired READY-TO-USE: POST /api/payments/razorpay/order + /verify (signature check via razorpay lib), Checkout "Pay Online" button opens Razorpay checkout. NEEDS RAZORPAY_KEY_SECRET in backend/.env to activate (returns 503 until set). VERIFIED endpoints respond correctly.
- Easy admin creds per owner: username `admin` / password `admin123` / passcode `admin123`. Lockouts cleared.
- Aadhaar number MANDATORY (12 digits) at registration (backend + frontend field). VERIFIED.
- Active-Referrer Rule: sponsor must be GREEN distributor, an admin, or an admin-generated code. RED sponsor rejected. VERIFIED.
- Admin referral-code generator: POST/GET /api/admin/referral-codes + "Generate Code" UI on /admin/users. Code resolves sponsor to company root (ANJ000000). VERIFIED (ANJ000171 registered under a code).
- ID card: removed RED/GREEN status badge; added company address (255, Saini Bhawan, Bengali Colony, Ramadevi, Kanpur; ☎ 9569381755, 9936694255).
- NOTE: signups via admin-generated codes credit the ₹100 referral commission to the company root (super_admin, GREEN) on activation — expected default.

## Implemented (2026-06 — session 4)
- Registration State & City are now DROPDOWNS (frontend/src/data/indiaLocations.js: all states/UTs + major cities; city depends on selected state; "Other" appended). Pincode stays text.
- Forgot-password is EMAIL-based now (was mobile OTP): POST /api/auth/forgot/send {email} + /forgot/reset {email, otp, password}. In beta the code is shown on-screen (dev_otp) because the email integration currently returns 422 — REAL email delivery needs a working provider (Resend) wired in production.
- Admin can reset/generate a user's password: POST /api/admin/users/{id}/reset-password (optional {password}; else auto-generates like Anj#####). UI: "Reset Password" button per row on /admin/users, shows the new password with copy. VERIFIED (auto + custom login works).

## Implemented (2026-06 — session 5)
- Real email (Resend managed) CONFIRMED WORKING: send returns 202 for real inboxes (Gmail verified); forgot-password code + OTPs delivered by email. Fake/undeliverable test domains (@example.com) return 422 by design (proxy deliverability protection). Env: EMERGENT_EMAIL_KEY, EMAIL_FROM_NAME already set.
- Razorpay: Key ID (rzp_test_TU3scdWQy95DIu) in env; code ready. STILL NEEDS RAZORPAY_KEY_SECRET to activate (returns 503 until set). Checkout shows "Pay Online (Card/UPI/Netbanking)" + "Pay via PhonePe/UPI (QR)".
- DEPLOY NOTE: keep APP_ENV=beta in production for now so registration/login OTP still shows on-screen (OTP_PROVIDER=mock is blocked when APP_ENV=production). Switch to production only after MSG91 SMS is wired.

## Fix (session 6) — Paid workflow + product delete + fresh start
- Manual payment by Distributor ID: POST /api/admin/payments/manual {distributor_id, reference, note}. Finds existing user (404 if none, never creates a user/duplicate), attaches to their latest unpaid order or creates an activation order, records an ADMIN/MANUAL payment_transaction (provider=admin_manual), runs idempotent _process_paid_order (paid + invoice + GREEN activation + commission), audit-logged (admin id, distributor id, prev/new status, reference). Reference mandatory. Super/admin only.
- AdminOrders UI: "Record Manual Payment" card (Distributor ID + Reference + Note) + All/Paid tabs; Paid list shows distributor_id, method, reference, invoice. Persists in DB (refresh-safe).
- Product permanent delete: DELETE /api/admin/products/{id}/permanent + trash button in AdminProducts (soft deactivate still available via Power toggle).
- Fresh start: POST /api/admin/maintenance/reset-data {confirm:"RESET"} (super_admin only) wipes users(non-admin)/orders/payments/commissions/wallets/referrals/activations/withdrawals/kyc/notifications/otp/referral_codes/login_attempts; keeps admins, products, settings. Demo seed gated behind SEED_DEMO=false so wipe stays fresh across restarts. RAN on preview (verified: only admin user remains, 0 orders).

## Fix (session 6) — admin login broken on production
- Root cause: production had no ADMIN_PASSCODE env set -> `bool("")` made passcode_ok always False -> every admin login returned "Invalid admin credentials or passcode".
- Fix: auth_routes.py `ADMIN_PASSCODE = os.environ.get("ADMIN_PASSCODE") or "admin123"`; server.py admin_password/username default to "admin123"/"admin". So the easy creds work even when production env vars are missing. Verified via env-unset simulation.
- ACTION: user must REDEPLOY for production to pick this up. After redeploy, admin login = admin / admin123 / admin123.

## Razorpay — LIVE (test mode) as of session 5
- RAZORPAY_KEY_ID="rzp_test_TU6SLmQAw29WNT", RAZORPAY_KEY_SECRET set. Verified: order.create returns real rzp order (order_TU6...), Checkout popup opens (Cards/Netbanking/Wallet/PayLater/UPI), signature verify → _process_paid_order activation.
- Owner will swap to LIVE keys after Razorpay approves the site.

## Implemented (2026-06 — session 8, fork)
- Admin User Management fully wired: AdminUsers.js now renders **Block / Unblock / Delete** buttons per user row (confirm popup on all, "Blocked" badge, optimistic UI). Backend endpoints PUT /api/admin/users/{id}/block {blocked} and DELETE /api/admin/users/{id} (removes user+wallet, admin accounts protected).
- Login refuses blocked users (403) — verified.
- Referral commission model (BETA): SPONSOR receives ₹100 on admin approval of a registration request (credited directly to sponsor wallet if sponsor_id resolves to a distributor_id); new user created RED + active. Manual payment / paid activation flips RED→GREEN. No double-payment (request flow creates no referral_relationship, so _process_paid_order's commission path is skipped). VERIFIED E2E via curl: approval → sponsor available_balance +100; block→403; delete→ok.

## CRITICAL FIX (2026-06 — session 8, fork) — "deleted data reappears"
- ROOT CAUSE 1 (products): server.py product seed ran on EVERY startup and re-inserted any seed SKU that was missing → deleted products came back on every pod restart. FIX: seed products ONLY when `db.products.count_documents({}) == 0` (first-time / empty catalogue only). Deleted products now stay deleted.
- ROOT CAUSE 2 (demo users/orders): demo_seed re-created the whole demo network on restart when SEED_DEMO=true (production still had it on). FIX: demo seeder PERMANENTLY DISABLED in code (removed the seed_demo call + import from server.py) — cannot run regardless of env var.
- VERIFIED on preview: deleted a product → restarted backend → product stayed deleted (5→4→4); 0 non-admin users after restart.
- ACTION FOR OWNER: must REDEPLOY for production (anjaliherbal.life) to pick up this fix; production runs old code until redeploy.

## PHASE 1 (2026-06 — session 9) — Data cleanup + registration + admin approval (PATCH)
Delivered exactly per owner's "PHASE 1 FINAL COMMAND" (no rebuild, no OTP, no demo data):
- MANDATORY cleanup run: reset-data wiped all non-admin data (0 users). Demo seeder already permanently disabled (session 8).
- Reset BETA Data control: AdminSettings.js "Data Management — Reset BETA Data" card (super_admin only), typed-RESET confirm → POST /api/admin/maintenance/reset-data. Preserves admins, products, settings.
- Audit log delete: DELETE /api/admin/audit-logs (SUPER ADMIN only) — clears logs then writes ONE immutable `audit_logs_cleared` system event (protected:true). UI button on AdminAuditLogs.js (super_admin only), with confirm. VERIFIED: deleted 684 → 1 event remains.
- Registration fields updated: MANDATORY now = Full Name, Mobile, Email, Aadhaar(12d), Password, State, City, Pincode. Sponsor/Referral ID is OPTIONAL. Backend + Register.js. NO OTP, no mock OTP. Duplicate mobile/email blocked (users + pending requests).
- Approval workflow: approve → next_distributor_id() ANJxxxxxx, RED, account_status active, activation_status "inactive"; referral relationship saved to referral_relationships (commission_paid:false). Reject stores rejection_reason (optional). **Phase 1 pays NO commission** (₹100 moved to Phase 2 on GREEN activation) — verified 0 commissions on approval.
- Profile: distributor self-update PUT /api/auth/profile (full_name/address/state/city/pincode; identity fields immutable). Admin complete/correct via PUT /api/admin/users/{id} + Edit modal in AdminUsers.js.
- Security: Aadhaar MASKED everywhere in API responses (XXXX-XXXX-1234); raw aadhaar_number never returned (clean_user + admin list/detail/update). mask_aadhaar() in core.py.
- VERIFIED via curl: all validation (missing email/state/city/pincode/aadhaar → 400), sponsor-optional 200, dup mobile/email 400, approve→RED/inactive/masked, login 200 / bad 401, admin edit, reject+reason, self profile update, audit delete. Frontend smoke screenshots OK.
- NOTE: ₹100-on-approval logic from session 8 was REMOVED to match the refined Phase 2 spec (commission on GREEN activation only).

## PHASE 1 CORRECTION (2026-06 — session 9) — Sponsor mandatory + validated
- Owner reversed the "sponsor optional" decision: referral MUST be captured from day one to build genealogy/commissions.
- Sponsor/Referral ID is now MANDATORY again (Register.js required + "*"; backend register-request).
- Backend VALIDATES the sponsor exists: accepts a real Distributor ID, an active admin referral code, or the company root ANJ000000 (does NOT require GREEN in Phase 1). Invalid/typo sponsor → 400 (prevents orphaned tree).
- Approval resolves referral CODES to the company root/super_admin (not just plain Distributor IDs) before saving the referral_relationship.
- VERIFIED: missing→400, invalid ANJ999999→400, ANJ000000→200, distributor-ID sponsor→200; chain ANJ000000→ANJ000199→ANJ000200 saved correctly.

## DEPLOYMENT FIX (2026-06 — session 9) — Atlas "no primary" crashed startup
- Symptom: production deploy timed out. Backend died on startup with pymongo ServerSelectionTimeoutError ("No primary available for writes", ReplicaSetNoPrimary) while running create_index inside @app.on_event("startup"). Crash → nginx /health connection-refused → pod never ready.
- ROOT CAUSE: blocking MongoDB init (indexes + seeds) ran synchronously in the FastAPI startup event; a transient Atlas primary election threw and killed the process before /health could respond.
- FIX (code only, no docker):
  - core.py: AsyncIOMotorClient(serverSelectionTimeoutMS=8000, connectTimeoutMS=8000, retryWrites=True) — bounded, never hangs.
  - server.py: startup() now schedules _run_db_init_with_retry() as a non-blocking asyncio background task (up to 60×5s retries); each index/seed step wrapped in _safe() so one failure can't abort the rest. /health & /api/health have NO DB dependency → pod ready immediately; DB init self-heals once Atlas primary is available.
- VERIFIED on preview: /health 200, "Application startup complete" logs BEFORE "DB initialisation complete", admin login + products work. deployment_agent: all critical checks pass (compilation, env, urls, cors, supervisor).
- NOTE: agent also flagged admin reset-data / delete-user / delete-audit-logs as "destructive" and some to_list() queries as unoptimized — these are intentional user-requested features (super_admin+confirm gated) and non-blocking perf items, NOT deploy blockers; left as-is.

## Backlog
- Cosmetic polish (P2): Checkout summary uses hardcoded 5% GST (use server gst_percent); dark-mode 'Activation' badge over product image; /admin-secure-login field fill.
- Backend hardening (P1): admin "reject UPI claim" path + upi reference validation; admin-login lockout email+IP keying; backport 15-min window to /api/auth/login.
- Dark mode tech-debt: migrate ~20 `.dark .util !important` overrides to Tailwind dark: variants before adding pages.
- Production integrations (ready-to-use via providers.py/APP_ENV abstraction, need keys): MSG91 real OTP (replace mock), Razorpay production payments (replace Stripe test/manual UPI), real email (Resend managed).
- P1: real email/SMS OTP delivery (currently mocked/dev_otp); rate-limit send-otp; pagination on lists; time-based login lockout expiry
- P1: Stripe live/India account (claim/BYOK) for production INR settlement
- P2: 8-level genealogy, level/rank income, business volume, bonuses (schema reserve fields already isolated)
- P3: native apps, push notifications, AI analytics, loyalty, subscriptions

## Notes
- Auth is JWT Bearer in localStorage (`anj_token`); CORS `*` with credentials off.
- Payment finalization is webhook-independent (status poll calls Stripe get_checkout_status) for preview reliability.
