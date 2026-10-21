# HOME GENIES — Product Requirements & Status

_Forked from the Anjali Herbal Life codebase. That project is separate and must never be opened
or modified from this workspace._

## 1. Product
- **Brand:** HOME GENIES · **Tagline:** _Establish Yourself._
- A women-focused home-business and social-commerce platform: HomeGenies buy useful products,
  share product links, sell without compulsory inventory, and track eligible sales and points.
- **Honesty rule:** recruitment alone NEVER earns commission. No fabricated products, balances,
  testimonials or earnings promises.
- **Four fixed pillars:** Sarees · Fashion Products · Makeup, Beauty & Skincare · Household Essentials.
- **Design:** royal purple `#2E1065`/`#6D28D9`, gold `#C9A227`, magenta `#C026A3`, ivory;
  Fraunces + Inter; mobile-first. Logo: girl peeping from an ornate genie lamp.
- **Languages:** English + Hindi, 288 parallel keys.

## 2. Architecture
React 19 (craco) + Tailwind + shadcn/ui · FastAPI + Motor/MongoDB (`homegenies`, localhost).
Backend: `server, core, auth_routes, shop_routes, wallet_routes, admin_routes, commission,
badges, cron_routes, providers, storage`.

## 3. Money rules — LIVE (owner-approved)
| Rule | Value |
|---|---|
| Base | product price **before GST** |
| Direct / Referral / Team | **30% / 10% / 5%** |
| Referral recipient | the person who invited the seller (permanent) |
| Credit | **PENDING**, released after `return_window_days` (7) |
| Point value | 1 point = Rs 1 · withdrawal to bank enabled, identity verification required, no minimum |
| COD | enabled, handling fee `cod_fee` (default Rs 49) |
| COD commission | credited **only** when cash collection is confirmed — by the HomeGenie herself **or** an admin; the confirmer is recorded on the order |
| Badges | monthly sales value → Bronze 10k · Silver 25k · Gold 50k · Diamond 100k (recognition only, no rate change) |

Attribution: `?ref=<HomeGenieID>` stored 30 days; seller ≠ buyer; seller and each upline must be
approved. Idempotent via atomic order claim; refunds claw back proportionally.
Cron: `points-release` daily 01:30 IST → `POST /api/cron/release-points` (bearer secret).
All rates, the COD fee and badge thresholds are editable in Admin → Settings.

## 4. Isolation from the original (complete)
Own DB, own admin (`HGADMIN001` / sansardeveloperssachin@gmail.com), rotated secrets, provider
keys blanked, CORS trimmed, storage namespace `home-genies`, Anjali dumps deleted from the tree.
All Anjali MLM logic removed, not renamed.

## 5. Backlog
**P1** — Razorpay merchant + webhook secret · Twilio sender + India DLT · email sender ·
real product catalogue (owner data pending) · seller/customer dual role + per-seller scoping ·
shipping & returns workflow · supplier / hybrid fulfilment.
**P2** — catalogue search · per-variant stock & price · session hardening (localStorage →
httpOnly) · admin pagination · git-history purge · distinct HOME GENIES hostname ·
change the admin password/passcode shared in chat.

## 6. Verification (21 Jun 2026)
`tests/test_commission_engine.py` — 30/10/5 on pre-GST base, pending→available release,
idempotency, refund clawback. `tests/test_cod_and_badges.py` — COD pays nothing on placement,
credits only on confirmed collection by HomeGenie or admin, idempotent, confirmer recorded,
badge tiers correct. UI verified at 390px and 1920px: checkout payment-method selector with COD
fee, COD tags and collect actions, dashboard badge + commission panels, admin COD/badge settings,
withdrawals (both sides), variant → cart flow. Catalogue intentionally empty.
