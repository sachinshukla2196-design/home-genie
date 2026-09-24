# PRODUCTION CONVERSION REPORT — Anjali Herbal Life Ayurveda India LLP
_All changes tested. 11/11 backend prod-hardening tests + 13/13 frontend smoke PASS; 7/7 commission/wallet forensic tests PASS._

## 1. Changes made
- Implemented the **70% depth-based TEAM SALES commission** (D1=20…D9=2), Depth 1 = immediate sponsor, base = value excl GST, product orders only.
- Fixed **₹100 direct referral** to fire once at GREEN activation (immediate sponsor only), removed the approval-time payout.
- Replaced **mock OTP** with **real MSG91 SMS OTP** (secure, hashed, single-use, fail-safe 503 when unconfigured); no OTP in responses/logs; admins blocked from OTP login.
- Rotated **JWT_SECRET / ADMIN_PASSWORD / ADMIN_PASSCODE**; removed all hardcoded secret fallbacks; JWT & CORS fail-fast.
- **CORS** now explicit env origin (no `*`), credentials on.
- **Razorpay**: hardened verify (signature + gateway fetch status + amount + order match) and added HMAC **webhook** `/api/webhook/razorpay` (idempotent via `webhook_events`).
- **Refund clawback** (`reverse_order_financials`): refund reverses product + referral commissions (audited, idempotent), reverts activation GREEN→RED.
- **Withdrawals**: atomic conditional debit; idempotent admin review (status-claim); no minimum.
- Removed the **reset-data backdoor**, `demo_seed.py`, "Reset BETA Data", "Withdrawal Minimum" field, "Test card 4242", and all dev/test OTP UI.
- Purged all demo/test data; catalogue reseed made one-time (`catalogue_bootstrap`).

## 2. Files modified
Backend: `.env`, `core.py`, `server.py`, `providers.py`, `auth_routes.py`, `shop_routes.py`, `wallet_routes.py`, `admin_routes.py`; deleted `demo_seed.py`.
Frontend: `pages/Checkout.js`, `pages/AuthExtras.js`, `pages/admin/AdminSettings.js`.

## 3. Database changes
- Deleted: DEMO01-10, RANKTOP, RANKM01/02/03/05, rahul/priya@t.com test rows earlier confirmed + all QA `TEST_*`/`ANJ000221-238` rows and their orders/commissions/wallets/referrals/txns/KYC/withdrawals/requests.
- Surviving users: admin (ANJ000000), ANJ000215 (GREEN), ANJ000216/219/220 (RED). Product: ANJ-STARTER only. Master: MST000001.
- New collection: `webhook_events` (Razorpay idempotency). New settings marker: `catalogue_bootstrap`.

## 4. Environment variables required (production)
`MONGO_URL, DB_NAME, CORS_ORIGINS, JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_USERNAME, ADMIN_PASSCODE, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, MSG91_AUTH_KEY, MSG91_SENDER_ID, MSG91_TEMPLATE_ID, MSG91_BASE_URL, OTP_PEPPER, APP_ENV=production, OTP_PROVIDER=msg91`.
App fails fast if `JWT_SECRET`/`CORS_ORIGINS` missing; OTP/webhook fail safe (503) if their creds missing.

## 5–14 (summary)
Demo/test data removed ✔ · Mock OTP removed ✔ · MSG91 OTP implemented ✔ · Razorpay verify+webhook ✔ · 70% commission ✔ · ₹100 at activation ✔ · Wallet CLAWBACK branch + reconciliation ✔ · Atomic + idempotent withdrawals ✔ · Secrets rotated/fail-fast, CORS locked, backdoor removed ✔ · Refund reversal ✔.

## 15–16. Tests executed & results
- Forensic (isolated temp data, real engine): 9-depth=₹700, idempotency, GST base=₹1000, RED-upline (d1=0/d2=12%), wallet reconcile, refund clawback (9 reversed + idempotent) — **ALL PASS**.
- ₹100-at-activation: sponsor +₹100, new user ₹0, idempotent, GREEN transition — **PASS**.
- testing_agent iteration_12: 11/11 backend + 13/13 frontend smoke — **100%**.
- API spot-checks: new admin creds OK, `admin123` rejected, admin OTP-login 403, reset-data 404, webhook 503 (unconfigured).

## 17. Remaining issues (non-blocking)
- Login brute-force lockout keyed on the submitted identifier form (email vs DID vs mobile) — pre-existing from Beta; can be bypassed by rotating identifier form. Recommend normalizing to canonical user id after lookup. (Out of this task's explicit scope; flagged.)

## 18. Production deployment requirements
Deploy the updated code; set the production secrets below in the Secrets panel before/at go-live.

## 19. Manual configuration still required — CONFIGURATION REQUIRED (USER ACTION)
1. **MSG91**: set `MSG91_AUTH_KEY`, `MSG91_SENDER_ID`, `MSG91_TEMPLATE_ID` (DLT-approved template with an `OTP` variable). Until set, OTP flows return 503 (by design). Primary registration is admin-approval and does NOT need OTP.
2. **RAZORPAY_WEBHOOK_SECRET**: create a webhook in the Razorpay dashboard pointing to `/api/webhook/razorpay` and paste its secret. Until set, the webhook returns 503 (client-side verify still works).
3. **Razorpay LIVE keys**: swap the test `RAZORPAY_KEY_ID/SECRET` for live keys when Razorpay approves the account.
4. **CORS_ORIGINS**: set to the real production domain (currently the preview URL).
5. Save the rotated admin credentials (shared in chat) and JWT secret securely.

## 20. Final production readiness status
**PRODUCTION CANDIDATE** — all code-side production blockers from the audit are resolved and tested. Go-live is gated ONLY on the 5 external configuration items in §19 (MSG91, Razorpay webhook secret, Razorpay live keys, real CORS domain). No mock OTP, no test data, no hardcoded secrets, no backdoor, no commission/wallet/idempotency defects remain in code.
