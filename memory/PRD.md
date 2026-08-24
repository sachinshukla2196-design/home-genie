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
