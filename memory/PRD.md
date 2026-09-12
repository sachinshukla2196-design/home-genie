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

## PHASE 2 (2026-06 — session 9) — ₹1,500 activation + GREEN + ₹100 referral (PATCH)
Delivered per owner's "PHASE 2 FINAL COMMAND". Logic already existed in shop_routes._process_paid_order; only ONE code change needed.
- CHANGE: GREEN activation now also sets user.activation_status="active" (Phase 1 sets it "inactive"). status→green, activation_status→active, activation_date, activation_order_id, activation_amount, wallet.active=true.
- Activation qualifies only when order.is_activation_order AND total >= settings.activation_amount (₹1500) AND user is RED. Backend-verified only — GREEN NEVER happens from a frontend "success" claim.
- Payment paths: Razorpay verify (signature-checked), admin manual (/api/admin/payments/manual), UPI admin-confirm. All funnel through _process_paid_order.
- ₹100 direct referral commission: paid to the sponsor when the referred distributor activates (sponsor must be GREEN). Immutable: commissions doc (type REFERRAL_COMMISSION) + wallet_transaction (credit to available_balance + total_earned). 3-layer idempotency: order.payment_status=="paid" early-return, existing-commission guard, atomic referral_relationships.commission_paid flag (modified_count==1). No duplicate ₹100 on repeat callbacks/admin actions.
- Wallet changes only via add_wallet_transaction (backend). Frontend cannot alter balance.
- VERIFIED E2E via curl: A(GREEN) refers B → B RED/inactive, A=₹0 → B pays ₹1500 → B GREEN/active, A available=₹100 earned=₹100 → REPEAT payment: A STILL ₹100, commissions unchanged → FAILED razorpay verify (bad signature)=400, user stays RED/inactive, no commission → RED cannot withdraw=403. Test data cleaned (0 users).

## SESSION 9 — Master Ref ID, sponsor dropdown, ID-card fix, dashboard counts, reset clarity
Owner-requested batch (all 6 approved & VERIFIED on preview):
1. ID CARD "half image" FIXED (components/IdCard.js): render() now waits for QR+photo image load, passes explicit width/height + style to toPng, and does a warm-up + final capture pass. Verified: exported PNG 1260x789 (ratio 1.597 ≈ card 1.6) = full card, ~964KB.
2. MASTER REFERENCE ID "ANJALI1" (is_master:true, label "Master Reference ID") seeded once in server.py _init_db; permanent, never expires. Onboarding can start immediately.
3. REGISTRATION SPONSOR = DROPDOWN (Register.js): now a Select populated from public GET /api/auth/reference-codes (active admin-created reference codes + master; code+label+is_master only). Master listed first. Admin creates codes via existing POST /api/admin/referral-codes (AdminUsers "Generate"). Register validation requires a selection. FRONTEND API PATH FIX: must call /auth/reference-codes (API base already has /api).
4. RESET BETA DATA: no longer deletes referral_codes (admin config) — preserves them, resets uses→0. Warning text (AdminSettings.js prompt + card) clarified: admin accounts, products, settings AND Reference IDs are always preserved. Verified reset keeps ANJALI1 + generated codes.
5. ADMIN EDIT PROFILE: already built (AdminUsers Edit modal → PUT /api/admin/users/{id}) — confirmed present.
6. DASHBOARD COUNT BUG FIXED (admin_routes dashboard): red_users/green_users now scoped to role in [distributor,customer] so the super_admin (company root, status green) is no longer counted. This was the "2 green vs 1 green" discrepancy.
VERIFIED: master reg 200 / invalid 400, dropdown shows master first, dashboard green excludes admin, reset preserves ref codes, ID card export full. Test data cleaned (0 users, ANJALI1 preserved).
IMPORTANT: production (anjaliherbal.life) still runs OLD code — the Cloudflare 520 the owner saw = backend startup crash on prod; fixed in code (session 9 deploy fix) but REQUIRES REDEPLOY. Admin creds are driven by prod env ADMIN_USERNAME/ADMIN_PASSWORD/ADMIN_PASSCODE (preview: admin/admin123/admin123).

## SESSION 9b — product image upload + reference-code delete
- Order/customer data: reset-data (preview) wiped orders/users/transactions (users=0). PRODUCTION untouched — no agent access; only owner's Reset on prod after redeploy affects it.
- Product image upload: AdminProducts.js Add/Edit dialog now has a file input (reads file → base64 data URL into images[0], 2MB cap) + live preview + optional paste-URL field. Stored in product.images (List[str]); no backend change (ProductBody.images already accepts strings).
- Reference-code delete: new backend DELETE /api/admin/referral-codes/{code} (blocks deleting is_master → 400). AdminUsers.js code chips now show a Trash2 delete button; master ANJALI1 shows ★ and has NO delete button. VERIFIED: delete normal code ok, delete master → 400.

## SESSION 9c — hard delete order
- Backend: DELETE /api/admin/orders/{order_id} — permanently deletes the order + its payment_transactions (super/admin roles). Audited (order_deleted).
- Frontend: AdminOrders.js Orders table now has an Action column with a red "Delete" button (confirm popup) per row, optimistic removal. VERIFIED via curl: order delete 1→0 ok, non-existent → 404.

## SESSION 10 — Final targeted admin patch
CHANGED:
- Registration sponsor: dropdown → MANUAL text input (mandatory). Server-side existence validation preserved (distributor id / admin code / master ANJALI1). Register.js.
- Orders page: added "Date" column (order created_at). Hard-delete already existed (session 9c) — untouched.
- Commissions: added RELEASE / HOLD. Backend PUT /api/admin/commissions/{id}/status (action release|hold); double-release blocked (400); updates real status (RELEASED/HELD), audited (commission_released/held). AdminCommissions.js Release/Hold buttons.
- Reset BETA Data UI card REMOVED from AdminSettings.js (hidden per request; backend endpoint left intact but no UI). No replacement created.
- KYC admin edit: backend PUT /api/admin/kyc/{user_id}/edit (upserts kyc record, PAN/IFSC uppercased, audited kyc_edited_by_admin). AdminKyc.js Edit button + modal (pan, holder, bank account, ifsc, bank name).
- ID card: added registered Mobile + RED/GREEN status badge (logo/name/ID already present). IdCard.js. Export full-image fix from session 9 still applies.
- Landing "Wellness Range": already dynamic from /api/products (removed the slice(0,3) → shows ALL admin products) + added "Purchase Now" button per card → /register. Landing.js.
SKIPPED (already correct): audit logging (real-time + delete events), hard-delete order (already built), referral relationship logic, KYC structure/masking, payment/wallet/commission calc.
VERIFIED via curl: commission release→RELEASED, double release→400, hold→HELD; KYC edit upsert + PAN uppercased. Screenshots: Register sponsor=INPUT, landing shows products + Purchase Now. Test data cleaned.

## SESSION 11 — Master ID (MST000001) + organic matrix tree
- MASTER ID: the permanent master referral code is now MST000001 (was ANJALI1). is_master:true, active. server.py seeds it once and enforces a SINGLE master (update_many sets is_master=false on all other codes; ANJALI1 demoted to a normal code, still usable). Deactivating MST000001 blocks new registrations through it (validated).
- ROOT ATTRIBUTION: on approval, when the sponsor is a referral CODE, the referral_relationship.sponsor_distributor_id and user.sponsor_distributor_id are set to the CODE itself (e.g. MST000001) — so MST000001 is the tree root. Distributor-ID sponsors store that distributor as parent. commission attribution (sponsor_user_id) still points to created_by/super_admin. No commission rules changed.
- Organic tree: reuses existing referral_relationships (no new table). core.build_referral_tree(root_did) builds a nested tree dynamically (unlimited levels) from sponsor_distributor_id → referred_distributor_id.
- APIs added (admin, super_admin-gated): GET /api/admin/master (code, active, direct_referrals, network_members), PUT /api/admin/master/status {active} (audited master_status_changed), GET /api/admin/tree (nested tree rooted at MST000001).
- Frontend: AdminSettings.js "Master Admin / Root" card (super_admin only) — MST000001, ACTIVE/INACTIVE toggle, direct/network counts, copyable code + referral link, and a Network Tree (components/TreeView.js). Distributor downline already viewable on existing Team page (/app/team) — unchanged.
- VERIFIED via curl: MST000001 active; A registers via MST000001 → parent=MST000001; B registers via A → parent=A(ANJ000208); admin tree MST000001→ANJ000208→ANJ000209; master counts direct 1/network 2; deactivate → register via MST000001 = 400. Test data cleaned.

## SESSION 12 — small correction patch
- Admin Order page: backend admin_orders now enriches each order with user_name (lookup by user_id); AdminOrders.js shows the name under the Distributor ID. (Date already present.)
- ID card: REMOVED the RED/GREEN status badge. Kept mobile + existing Anjali Herbal Life brand emblem/logo.
- KYC pending queue: AdminKyc.js now fetches /admin/kyc?status=pending so approved/rejected records leave the active queue (history kept — visible via status=verified/rejected). review_kyc already set status correctly.
- Homepage "Our Wellness Range": already dynamic from /api/products (active only) — SKIPPED (works in current code; production needs redeploy).
- AUDIT recurrence ROOT CAUSE + fix: clear_audit_logs re-inserted a marker stamped with the admin's email (sachin.shukla2196@gmail.com) after every clear — that's why the record "reappeared." Fixed: the post-clear system marker now stores user_email="system", user_id=None (no personal email). So cleared logs stay cleared and that email is not auto-recreated. (No seed/startup/trigger recreates audit data.)
- Hard-delete consistency: verified orders stay deleted (products seed only when empty, demo seeder disabled) — no recreation sources remain.
- VERIFIED: order user_name shows; audit clear leaves only user_email="system" (no sachin); order hard delete persists (0). KYC pending→0 after approve, verified history kept (re-tested with correct var).

## SESSION 13 — only Starter Kit product (remove demo products permanently)
- ROOT CAUSE: PRODUCT_SEED in server.py held 6 demo products; they reseeded when catalogue was empty.
- FIX: PRODUCT_SEED trimmed to ONLY the Starter Kit (ANJ-STARTER). Permanently deleted the 5 demo + 7 TEST products from DB. Landing.js no longer filters out the activation product, so the Starter Kit shows under "Our Wellness Range".
- VERIFIED: products = ['ANJ-STARTER'] and remains so after backend restart; homepage shows only Starter Kit (no Tulsi/Aloe/Ashwagandha/Chyawanprash/Hair Oil/TEST).

## SESSION 14 — critical small patch (₹100 on approval, optional email, ID logo, withdrawal min, matrix)
- ₹100 ON APPROVAL: admin approve now credits ₹100 to the NEW user's own wallet (available + total_earned) immediately, idempotent via wallet_transactions category "signup_bonus" (re-approve returns 400 anyway; no duplicate). User stays RED; ₹1500 RED→GREEN rule unchanged.
- EMAIL OPTIONAL: register-request no longer requires email; only validates format if provided; duplicate-email checks guarded with `if email`. Stored as email or None. Admin can add email later via existing edit.
- ID CARD: replaced Leaf emblem with the ORIGINAL brand logo (/brand-logo.jpg, same asset as site Logo). RED/GREEN already removed; shows logo + name + ID + mobile.
- WITHDRAWAL: removed the minimum-amount check entirely (was ₹500). Any amount within available balance allowed (₹1 works). KYC/green/balance/duplicate checks retained.
- MATRIX: verified working — MST000001→ANJ000213→ANJ000214 persists via referral_relationships. Root cause of prior "not working" was production running old code; current code stores sponsor_id/sponsor_distributor_id correctly on approval.
- VERIFIED: register w/o email→approve→₹100 (idempotent), matrix chain, ₹1 withdrawal=200.

## Backlog
- Cosmetic polish (P2): Checkout summary uses hardcoded 5% GST (use server gst_percent); dark-mode 'Activation' badge over product image; /admin-secure-login field fill.
- Backend hardening (P1): admin "reject UPI claim" path + upi reference validation; admin-login lockout email+IP keying; backport 15-min window to /api/auth/login.
- Dark mode tech-debt: migrate ~20 `.dark .util !important` overrides to Tailwind dark: variants before adding pages.
- Production integrations (ready-to-use via providers.py/APP_ENV abstraction, need keys): MSG91 real OTP (replace mock), Razorpay production payments (replace Stripe test/manual UPI), real email (Resend managed).
- P1: real email/SMS OTP delivery (currently mocked/dev_otp); rate-limit send-otp; pagination on lists; time-based login lockout expiry
- P1: Stripe live/India account (claim/BYOK) for production INR settlement
- P2: 8-level genealogy, level/rank income, business volume, bonuses (schema reserve fields already isolated)
- P3: native apps, push notifications, AI analytics, loyalty, subscriptions

## Phase 3 (Sep 2026) — DONE
- KYC user→admin flow: confirmed already complete (Kyc.js submit → AdminKyc.js verify/reject; drops from pending queue).
- Withdrawal NO minimum: confirmed (amount>0, up to available balance, needs GREEN + verified KYC). No minimum enforced.
- 8-LEVEL TEAM HIERARCHY: `GET /api/team` now does BFS down 8 levels from the user via referral_relationships (dedup via `seen`, halts at level 8). Returns `levels[]` (level, count, active, income, members[]) + totals (total, active, total_income, direct). Backward-compatible `members`=level 1.
- INCOME PER LEVEL: per-member income = sum of `commissions` where sponsor_id=user & referred_user_id=member; summed per level. (Current payout logic only credits direct sponsor, so income concentrates at L1 — accurate to existing rules, no new commission logic added.)
- FRONTEND Team.js: new default "Levels" accordion view (collapsible L1–L8, header shows count/active/income, expandable member rows w/ income+downline). Matrix & List views retained. Summary cards: Total Team, Active, Total Income, Levels Reached (of 8).
- VERIFIED: backend BFS (10-level chain seeded → returns exactly 8, income at L1=₹100); frontend accordion desktop+mobile (no overflow), expand/collapse, summary cards. Temp test data cleaned up.

## Purchase Level Commission (Sep 2026) — DONE
- ADDED: `_distribute_purchase_commission()` in shop_routes.py, called at the END of `_process_paid_order` for EVERY paid order (all payment paths route through it). ₹100 direct referral left completely untouched.
- Depth-based fixed % from buyer: L1=0, L2=15, L3=5, L4=5, L5=5, L6=4, L7=4, L8=3, L9=3 (LEVEL_COMMISSION_PCT).
- Base = order.subtotal (product value EXCLUDING GST). Walks real sponsor chain via referral_relationships (referred_user_id→sponsor_id) up to 9 levels.
- Only GREEN uplines paid; non-green uplines skipped (₹0) and NOT redistributed (positional level preserved).
- Type = PURCHASE_LEVEL_COMMISSION (separate from REFERRAL_COMMISSION). Idempotent via atomic order claim (`purchase_commission_paid` flag) → retries/refresh/webhook never duplicate.
- No new tables/APIs/UI: reuses commissions + wallet_transactions; AdminCommissions renders type generically.
- VERIFIED: A→B→C→D chain (base 1000): L1=0, L2=15%=150, L3=5%=50; non-green upline skipped & not redistributed; 2nd run = no duplicate (exactly 2 rows); base excludes GST.

## Compensation + User-ID Patch (Sep 2026) — DONE
- ₹100 BUG FIX: admin approve (`admin_routes.approve_registration_request`) NO LONGER credits ₹100 to the NEW user (removed `signup_bonus`). ₹100 DIRECT REFERRAL REWARD now credited ONLY to the immediate direct sponsor (`rel.sponsor_id`) as REFERRAL_COMMISSION, idempotent (guard on existing REFERRAL_COMMISSION + relationship `commission_paid=True`), never cascades. shop_routes activation referral block now skips (guard already present) → no double-pay.
- PURCHASE COMMISSION: unchanged calc (depth L1=0,L2=15,L3=5,L4=5,L5=5,L6=4,L7=4,L8=3,L9=3; base=subtotal excl GST). Descriptions/notifications now use RANK NAMES + % + base for wallet display.
- RANK/BV PROGRESS: new `compute_rank()` + RANK_TIERS in wallet_routes; `/dashboard` returns `rank` from personal BV = sum of user's PAID order subtotals (excl GST). Dashboard.js shows a progress bar (Current Rank, Next Rank, BV x/y, %) + rank stat card.
- RANK NAMES (UI): Team accordion shows Executive/Sr. Executive/... (GD/BD/AD/CD/PD/MD/RD/DD/MDD badges); "Level N" removed; tab "Ranks", "Ranks Reached of 8". Backend keeps numeric levels internally.
- FORGOT PASSWORD: already email-based (`/auth/forgot/send`), no mobile OTP in that flow; added no-email helper note (contact admin) on ForgotPassword page. Admin reset (`/admin/users/{id}/reset-password`) covers no-email accounts.
- WITHDRAWAL: unchanged, no minimum.
- VERIFIED: approve → new user ₹0, sponsor ₹100, no signup_bonus, REFERRAL_COMMISSION to sponsor, relationship commission_paid=True, re-approve=400 (idempotent). Rank compute matches spec (BV 12500 → Executive 62.5%). Dashboard bar + Team rank names render (desktop+mobile, no overflow).
- LEGACY NOTE: users approved under OLD code may still hold a `signup_bonus` ₹100 on their own wallet — not auto-deleted (financial data); fix is forward-only.

## Final Surgical Patch #2 (Sep 2026) — DONE
- FORGOT PASSWORD → ADMIN-ONLY REQUEST: removed OTP/email-reset. `/auth/forgot/send` now takes {identifier} (Distributor ID or mobile), creates a `password_reset_requests` doc (idempotent per user), no OTP/email/SMS. `/auth/forgot/reset` removed (404). New admin endpoints: GET `/admin/password-reset-requests`, POST `/admin/password-reset-requests/{id}/dismiss`. Existing admin reset-password now auto-resolves matching pending requests. Frontend ForgotPassword page = single identifier field → "request sent"; AdminUsers shows a "Password Reset Requests" panel with Reset/Dismiss.
- RANK CODES: RANK_TIERS/compute_rank now include codes (GD/BD/AD/CD/PD/MD/RD/DD/MDD/ZM). New `GET /api/rank` returns code/current/next_code/next/current_bv/next_bv/progress/is_max from personal BV (paid-order subtotals excl GST).
- PROFILE: shows "STATUS | CODE — Designation" next to RED/GREEN badge, plus a BV progress bar (Current Rank, Next Rank, BV x/y, %). No page redesign.
- ITEMS ALREADY DONE (unchanged): ₹100 to direct sponsor only (idempotent), depth-based purchase commission (base excl GST, GREEN-only, no redistribution), wallet display w/ rank names, no-minimum withdrawal, Dashboard BV bar, Team rank names.
- VERIFIED: forgot by DID & mobile (idempotent, pending=1), admin list shows it, admin reset auto-resolves (pending=0), unknown id=404, old reset route=404, /api/rank=GD Executive. Backend imports clean; frontend compiled.

## Notes
- Auth is JWT Bearer in localStorage (`anj_token`); CORS `*` with credentials off.
- Payment finalization is webhook-independent (status poll calls Stripe get_checkout_status) for preview reliability.
