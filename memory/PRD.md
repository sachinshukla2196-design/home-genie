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
