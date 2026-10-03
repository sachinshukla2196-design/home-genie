# Anjali Herbal Life Ayurveda India LLP — Software Status Report
_Generated: 1 June 2026_

A production-grade **Distributor (MLM) + E-Commerce platform**: bilingual (English / हिन्दी),
React + FastAPI + MongoDB, with a 9-level team-sales commission engine, wallet, KYC,
withdrawals, payments (Razorpay), SMS OTP (MSG91), object storage, and a full admin panel.

---

## 1. TECHNOLOGY STACK
| Layer | Technology |
|---|---|
| Frontend | React 19, Tailwind CSS, shadcn/ui, framer-motion, recharts |
| Backend | FastAPI (Python), modular routers |
| Database | MongoDB (Motor async) |
| Auth | JWT Bearer (bcrypt password hashing), role-based access |
| Payments | Razorpay (online) + Admin Manual / UPI confirmation |
| SMS OTP | MSG91 (integrated, currently gated OFF until DLT approval) |
| File storage | Emergent Object Storage (profile photos, product images) |
| Languages | English + Hindi (full i18n) |

---

## 2. WHAT IS BUILT (FEATURE BY FEATURE)

### A. Public Website (Landing)
- Hero section with headline, CTAs, trust badges, and a **3-banner auto-slider** (right side).
- Clickable **"REFER & EARN ₹100 / activation"** floating badge → registration page.
- "Our Wellness Range" — shows live products from the database (Starter Kit).
- Distributor Opportunity section, CTA, footer with **Legal links**.
- Dark / Light theme toggle, language switcher.

### B. Registration & Authentication
- **Registration request flow** (no public self-activation): full name, mobile, email (optional),
  Aadhaar (12-digit), password, **Pincode → auto-fills State & City** (editable), mandatory Sponsor/Referral ID.
- Sponsor is **validated** (must be a real Distributor ID, an admin referral code, or Master ID `MST000001`).
- Duplicate mobile/email blocked. Admin must **approve** → generates unique Distributor ID (ANJxxxxxx).
- **Login** by Distributor ID / mobile / email + password; brute-force lockout; blocked users refused (403).
- **Hidden secure Admin login** (`/admin-secure-login`) with email/username + password + passcode.
- Password reset = **admin-handled request** (user raises request, admin resets — no public OTP reset).

### C. Distributor Area (`/app`)
- **Dashboard**: wallet stats, rank & BV progress bar, income chart, recent orders/transactions, notifications.
- **Products / Product detail / Cart / Checkout** with GST computed server-side.
- **Orders** list + detail + invoice.
- **Wallet**: available / pending / earned / withdrawn balances + full transaction ledger.
- **Referral**: referral link + QR code + share (WhatsApp / Email / SMS).
- **Team**: 8–9 level genealogy/matrix view, per-level counts, active members, income, **rank codes (GD…ZM)**.
- **KYC**: submit PAN / Aadhaar / bank (masked) → admin review.
- **Withdrawals**: request (needs active status + verified KYC + balance) → admin approve / pay / reject.
- **Profile**: self-update (name/address/state/city/pincode), profile photo upload, rank & BV display.

### D. Commission & Earnings Engine (core business logic — forensically verified & locked)
- **₹100 Direct Referral Reward**: paid ONCE to the immediate sponsor, **only on activation** (₹1,500 qualifying order). Idempotent, never duplicated.
- **9-Level Team Sales Commission (70% total)**: D1=20%, D2=12%, D3=10%, D4=8%, D5=6%, D6=5%, D7=4%, D8=3%, D9=2%.
  - Base = product value **excluding GST**.
  - Only active (GREEN) uplines paid; inactive uplines skipped (no redistribution).
  - Atomic & idempotent (no double-pay on webhook/retry/refresh).
- **Refund / Reversal clawback**: refunding an order claws back both referral and team commissions and reverts activation.
- **Rank / BV**: rank computed from personal Business Volume (paid-order subtotals excl GST).

### E. Payments
- **Razorpay online** (cards / UPI / netbanking / wallet): order create + signature-verified confirmation + **HMAC-secured webhook**.
- **Admin manual payment** by Distributor ID (reference mandatory, audited).
- **UPI/QR claim** → admin confirmation with mandatory reference ID.
- All payment paths converge on ONE authoritative, idempotent order-processing function.

### F. Admin Panel (`/admin`)
- **Dashboard** stats; **Users** (approve/reject registrations, block/unblock, delete, edit, reset password, generate referral codes, password-reset requests).
- **Products** CRUD + image upload + permanent delete.
- **Orders** (status, manual payment, UPI confirm, hard delete, customer name).
- **KYC** review & edit; **Withdrawals** review; **Commissions** (release/hold).
- **Settings** (activation amount, GST, commission config, Master ID root + network tree).
- **Reports** (multiple types + CSV export); **Audit logs** (immutable, clearable by super-admin).

### G. Security & Production Hardening (DONE)
- No demo/mock data, no mock OTP, no backdoor reset endpoints.
- JWT secret & admin credentials rotated (strong), fail-fast on missing config.
- CORS restricted to explicit production origins (via `CORS_ALLOWED_ORIGINS`).
- Aadhaar masked everywhere (XXXX-XXXX-1234); raw value never returned.
- Atomic wallet debits; immutable commission ledger.

---

## 3. INTEGRATIONS — STATUS
| Integration | Status |
|---|---|
| Razorpay | ✅ Code live & verified — **currently on TEST keys** (swap to LIVE for real money) |
| MSG91 SMS OTP | ⚙️ Integrated but **DISABLED** (`MSG91_ENABLED=false`, returns 503) — awaiting your DLT **Sender ID + Template ID** |
| Emergent Object Storage | ✅ Live (profile photos, product images) |
| Razorpay Webhook | ✅ Built — needs `RAZORPAY_WEBHOOK_SECRET` from your Razorpay dashboard |

---

## 4. WHAT IS PENDING / REMAINING

### 🔴 P0 — Blocking real users (needs YOUR input)
1. **Enable SMS OTP** — provide approved MSG91 DLT **Sender ID + Template ID**, then flip `MSG91_ENABLED=true`. Until then, OTP login/registration verification is off.

### 🟠 P1 — Go-live configuration (needs YOUR input)
2. **Razorpay LIVE keys** — swap TEST → LIVE key/secret to accept real payments.
3. **Razorpay webhook secret** — add `RAZORPAY_WEBHOOK_SECRET` from the Razorpay dashboard.

### 🟡 P2 — Content & polish
4. **Legal pages** — replace placeholder text on Privacy / Terms / Refund / Shipping / Distributor Terms / Contact with your real legal content.
5. Minor cosmetic polish items (dark-mode badge over product image, checkout summary styling).

### 🟢 P3 — Future roadmap (optional, not started)
6. Rank-based / level income bonuses, business-volume bonuses beyond current engine.
7. Pagination on long admin lists; rate-limiting on OTP send.
8. Native mobile apps, push notifications, AI analytics, loyalty/subscriptions.

---

## 5. OVERALL READINESS
- **Core platform: COMPLETE & verified** — registration, approval, genealogy, commissions, wallet, KYC, withdrawals, payments (test), admin panel, object storage.
- **To accept real customers you need: (1) MSG91 DLT details, (2) Razorpay LIVE keys + webhook secret, (3) real legal text.**
- Everything else is production-hardened and locked.
