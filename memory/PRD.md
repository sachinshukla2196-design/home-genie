# HOME GENIES — Product Requirements & Status

_Forked from the Anjali Herbal Life codebase. The original project is separate and must never be
opened or modified from this workspace._

## 1. Product
- **Brand:** HOME GENIES · **Tagline:** _Establish Yourself._
- **Purpose:** a women-focused home-business and social-commerce platform. HomeGenies buy useful
  products, share product links with customers, sell without compulsory inventory, and track
  eligible sales and HomeGenie Points.
- **Honesty rule (non-negotiable):** recruitment alone NEVER generates commission. No fabricated
  products, balances, testimonials or earnings promises anywhere in the product.
- **Four fixed pillars:** Sarees · Fashion Products · Makeup, Beauty & Skincare · Household Essentials.
- **Design:** deep royal purple `#2E1065` / `#6D28D9`, metallic gold `#C9A227`, magenta `#C026A3`,
  ivory surfaces; Fraunces display + Inter body; mobile-first.
- **Languages:** English + Hindi (250 keys each, kept strictly parallel).

## 2. Architecture
React 19 (CRA/craco) + Tailwind + shadcn/ui · FastAPI + Motor/MongoDB · preview pod with supervisor.

## 3. Isolation status (vs the Anjali original)
| Area | State |
|---|---|
| Database | `DB_NAME=homegenies`, localhost only — **needs a backend restart to take effect** |
| Payout cron | Removed from `.emergent/crons.yml` and **confirmed de-registered** in the pod |
| Secrets | JWT / OTP pepper / cron secret rotated; Razorpay, Stripe, Twilio, email keys blanked |
| CORS | Anjali domains removed; preview origin only |
| Admin identity | seeded id is `HGADMIN001`; **`ADMIN_EMAIL` + password rotation still pending owner input** |
| Storage | namespace `home-genies` |
| Anjali DB dumps | `/app/backups` deleted from the tree (git history purge NOT executed — separate decision) |
| Branding | fully replaced across frontend + backend |

## 4. Removed Anjali business logic (21 Jun 2026)
Commission matrix (30/70 pool, GD..MDD), personal-repurchase 5%, team-purchase 2.5%, monthly fixed
income, club/royalty income, rank/BV, RED→GREEN activation, genealogy tree, master code `MST000001`,
the ₹100 registration referral reward, `ANJ` id prefix, mandatory sponsor, Aadhaar-at-signup,
the Anjali starter kit seed and the PhonePe merchant QR. Files deleted: `club_income.py`,
`income_rules.py`, `income_config.py`, `cron_routes.py`, `Team.js`, `Kyc.js`, `Withdrawals.js`,
`IdCard.js`, `TreeView.js`, `AdminKyc/AdminWithdrawals/AdminCommissions/AdminMonthlyIncome/AdminIncomeRules`.

## 5. Preserved
Auth + RBAC, Google sign-in, registration→admin approval, catalogue + cart + orders with
server-side pricing, Razorpay/webhook verification with idempotency, refund + clawback,
immutable wallet ledger, notifications, audit log, CSV reports, object-storage uploads, i18n.

## 6. Pending / backlog
**P0 — blocking**
1. Owner's HOME GENIES admin email + a safe channel for new admin password/passcode.
2. Authorised backend restart so `DB_NAME=homegenies` takes effect (fresh, empty DB).
3. A distinct HOME GENIES hostname (fork currently shares the original's preview host).

**P1**
4. HOME GENIES commission engine (30% direct / 10% permanent referral / 5% team) — **not built**;
   every surface currently says "Pending configuration".
5. HomeGenie Points ledger (1 pt = ₹1), redemption + withdrawal rules (compliance review needed).
6. Provider accounts: Razorpay merchant + webhook secret, Twilio sender + India DLT, email sender.
7. Seller/HomeGenie role separation on one login + per-seller data scoping.
8. COD, shipping and returns workflow; supplier / hybrid-fulfilment model.

**P2**
9. Product variants (size/shade) + catalogue search; badges & monthly activity tracking.
10. Session hardening (localStorage → httpOnly), pagination on admin lists.
11. Git-history purge of the old DB dumps (plan prepared, NOT executed).

## 7. Verification (21 Jun 2026)
Backend compiles; all live endpoints 200; every removed MLM endpoint returns 404; webpack compiles
clean; testing agent (iteration_16) passed homepage, EN/HI, 5 legal pages, login, all 7 admin routes,
dashboard and removed-route redirects. Its 7 findings (referral wrongly required, mobile header
overflow, dead rank UI, duplicate labels, logo alignment, MLM column headers, points shown as rupees)
were all fixed and re-verified. Authenticated UI was exercised with the admin account; the legacy
HomeGenie test login is stale (401).
