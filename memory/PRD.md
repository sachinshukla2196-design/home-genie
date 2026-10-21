# HOME GENIES — Product Requirements & Status

_Forked from the Anjali Herbal Life codebase. That original project is separate and must never be
opened or modified from this workspace._

## 1. Product
- **Brand:** HOME GENIES · **Tagline:** _Establish Yourself._
- **Purpose:** a women-focused home-business and social-commerce platform. HomeGenies buy useful
  products, share product links with customers, sell without compulsory inventory, and track
  eligible sales and HomeGenie Points.
- **Honesty rule (non-negotiable):** recruitment alone NEVER earns commission. No fabricated
  products, balances, testimonials or earnings promises.
- **Four fixed pillars:** Sarees · Fashion Products · Makeup, Beauty & Skincare · Household Essentials.
- **Design:** royal purple `#2E1065`/`#6D28D9`, gold `#C9A227`, magenta `#C026A3`, ivory surfaces;
  Fraunces display + Inter; mobile-first. Logo: girl peeping from an ornate genie lamp
  (`/brand/logo-full.jpg`, `/brand/logo-icon.jpg`).
- **Languages:** English + Hindi, 271 parallel keys.

## 2. Architecture
React 19 (CRA/craco) + Tailwind + shadcn/ui · FastAPI + Motor/MongoDB · supervisor preview pod.
Backend modules: `server, core, auth_routes, shop_routes, wallet_routes, admin_routes,
commission, cron_routes, providers, storage`.

## 3. Commission engine — LIVE (owner-approved 21 Jun 2026)
| Rule | Value |
|---|---|
| Base | product price **before GST** (`order.subtotal`) |
| Direct | **30%** to the HomeGenie whose share link produced the sale |
| Permanent referral | **10%** to the person who invited that HomeGenie |
| Team sales | **5%** to the person who invited that referrer |
| Credit | as **PENDING**, released to AVAILABLE after `return_window_days` (7) |
| Point value | 1 point = Rs 1 |
| Withdrawal | enabled, requires a verified identity/bank record, no minimum |

Eligibility: order paid · sale attributed via `?ref=<HomeGenieID>` (stored 30 days) · seller ≠ buyer
· seller approved (green) · each upline recipient approved. Idempotent via an atomic order claim;
refunds claw back proportionally (pending cancelled, released debited).
Release cron: `points-release`, 01:30 IST daily → `POST /api/cron/release-points` (bearer secret).
Rates editable in Admin → Settings → Commission & Points.

## 4. Isolation from the original (complete)
Own DB `homegenies` (localhost) · own admin identity `HGADMIN001` /
`sansardeveloperssachin@gmail.com` · rotated JWT/OTP/cron secrets · provider keys blanked ·
CORS trimmed · storage namespace `home-genies` · Anjali dumps deleted from the tree
(git-history purge still a separate, unexecuted decision).

## 5. Removed Anjali logic (not renamed)
Commission matrix (30/70 pool, GD..MDD), personal repurchase, team purchase, monthly fixed income,
club/royalty income, rank/BV, RED→GREEN activation, genealogy tree, master code MST000001,
the ₹100 registration reward, ANJ prefix, mandatory sponsor, Aadhaar-at-signup, starter-kit seed,
PhonePe merchant QR, legacy Stripe keys.

## 6. Backlog
**P1** — Razorpay merchant + webhook secret · Twilio sender + India DLT · email sender ·
seller/customer dual role on one login + per-seller data scoping · COD, shipping, returns workflow ·
supplier / hybrid fulfilment · badges & monthly activity tracking.
**P2** — catalogue search · per-variant stock and price · session hardening (localStorage →
httpOnly) · admin list pagination · git-history purge · distinct HOME GENIES hostname.

## 7. Verification (21 Jun 2026)
`tests/test_commission_engine.py` passes: 30/10/5 on a pre-GST base, pending→available release,
idempotency, refund clawback. Cron endpoint returns 401 unauthorised / 200 + duplicate-safe when
authorised, and is registered in the pod. Admin login with the new credentials works; Settings,
Withdrawals (admin + HomeGenie), dashboard commission panel and the variant → cart flow verified
at 390px and 1920px with no overflow. Catalogue intentionally empty (4 pillar categories only).
