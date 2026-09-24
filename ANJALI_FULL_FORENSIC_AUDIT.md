# ANJALI HERBAL LIFE — FULL SOFTWARE FORENSIC AUDIT
_Read-only audit. No code, DB, config, or business rules were modified._
_Verification basis: source code + live MongoDB records + live wallet reconciliation._

---

## 1. Executive Summary

The platform is a **functional Beta build**, not production ready. Core distributor
flows (registration→approval→activation→RED/GREEN, orders, ₹100 direct reward, level
purchase commission, wallet ledger, admin panel) work and reconcile correctly against
the live database.

**The single most important finding:** the requested **70% team-sales model is NOT
implemented.** The live engine pays a **44% total** pool on a different depth curve, and
crucially pays the **immediate sponsor 0%** on purchases. Live DB proof below.

Production blockers exist in **authentication (mock-OTP admin takeover)**, **payments
(test keys, no Razorpay webhook)**, and **data hygiene (test/demo rows in the live DB)**.

**Verdict: B — Beta / test ready. NOT a production candidate yet.**

---

## 2. What Is Actually Working (verified)

- **Registration request → admin approval → Distributor ID (ANJ0000NN)** — system-generated, unique index enforced. ✅
- **Sponsor tree** — unlimited-width, stored in `referral_relationships`; depth walked from the buyer upward. ✅
- **Master ID** — exactly one `MST000001`; all other codes forced `is_master:false` on every startup. ✅
- **RED→GREEN** — only via activation order (`is_activation_order` AND `total ≥ 1500`), conditional `status:red` update. ✅
- **₹100 direct referral reward** — immediate sponsor only, no cascade, idempotent (guard on `commissions{referred_user_id,type:REFERRAL_COMMISSION}`). ✅
- **Level purchase commission** — base = `subtotal` (GST EXCLUDED), idempotent via atomic `purchase_commission_paid` claim, RED uplines skipped without shifting depth. ✅ (percentages are wrong vs target — see §6)
- **Wallet ledger** — immutable `wallet_transactions` + aggregate `$inc`. Reconciles exactly (RANKTOP: ledger ₹200 = wallet ₹200 = 150+50). ✅
- **Admin panel** — dashboard, users, products, orders, KYC, withdrawals, commissions, settings, reports (CSV), audit logs. ✅
- **Order hard-delete** — `delete_order` removes order + payment_transactions; no startup path recreates arbitrary orders, so it does not "come back". ✅
- **Login brute-force lockout** — 5 attempts / 15 min for both user and admin login. ✅

---

## 3. What Is Not Working / Missing

- **70% commission model — not present.** (§6, CRITICAL)
- **Razorpay webhook — does not exist.** Only `/api/webhook/stripe` exists; `RAZORPAY_WEBHOOK_SECRET=""`. A dropped client callback after a real Razorpay payment leaves the order unpaid forever. (§7)
- **`withdrawal_minimum` setting is ignored** by the backend (code enforces no minimum) although `DEFAULT_SETTINGS` and Admin Settings UI expose ₹500. Silent mismatch. (§15)

---

## 4. What Is Partially Working

- **Payments** — Stripe + Razorpay + Manual UPI + Admin-manual all functional, but all on **TEST keys**, and Razorpay has no server webhook safety net. CODE VERIFIED / LIVE-PRODUCTION NOT VERIFIED.
- **OTP flows** — work, but via **mock provider** returning the code in the API response. MOCK / NOT PRODUCTION VERIFIED.
- **₹100 trigger consistency** — paid at **admin approval** in the request flow (no sponsor-GREEN check) vs at **GREEN activation** in the payment flow (requires sponsor GREEN). Two different triggers/eligibility for the same reward. (§12)

---

## 5. Critical Bugs / Blockers

| ID | Severity | Summary |
|----|----------|---------|
| P0-1 | CRITICAL | Mock-OTP **admin account takeover**: admin mobile `9999999999` is also an `OTP_TEST_NUMBER`, so `POST /api/auth/login-otp` with mobile `9999999999` + OTP `123456` returns a valid admin JWT. |
| P0-2 | CRITICAL | Non-admin OTP endpoints return the real OTP (`dev_otp`) in the JSON body while `APP_ENV=beta` → takeover of any account by mobile number. |
| P1-1 | HIGH | 70% commission model not implemented (44% live, immediate sponsor 0%). |
| P1-2 | HIGH | No Razorpay webhook; real payments can be silently lost. |

---

## 6. Financial / Commission Risks — CORE FINDING (live-proven)

**Target (requested):** depth from buyer's immediate sponsor upward, base = value excl GST
`D1=20, D2=12, D3=10, D4=8, D5=6, D6=5, D7=4, D8=3, D9=2` → **70%**.

**Actual (code `shop_routes.py:340`):**
`LEVEL_COMMISSION_PCT = {1:0, 2:15, 3:5, 4:5, 5:5, 6:4, 7:4, 8:3, 9:3}` → **44%**, and **L1 (immediate sponsor) = 0%**.

**Live DB proof** — order `ORDDEMO10`, buyer **DEMO10**, subtotal ₹1000, GST ₹180, total ₹1180:
- Immediate sponsor DEMO09 (L1): **₹0**  ← target wants **₹200 (20%)**
- DEMO08 (L2): ₹150 (15%)  ← target D2 = ₹120
- DEMO07 (L3): ₹50 (5%)   ← target D3 = ₹100
- DEMO06 (L4): ₹50 … DEMO01 (L9): ₹30
- **Total paid = ₹440 (44%)** vs target **₹700 (70%)**.

Correct parts (keep on rewrite): base is `subtotal` (**GST correctly excluded**), idempotent, RED-upline skip does not shift depth.

**Risk:** the compensation plan being paid does not match the intended plan. Immediate
sponsors earn nothing on team purchases today. This is a business-defining defect.

---

## 7. Payment Risks

- All keys are **test** (`rzp_test_…`, `sk_test_emergent`). CODE VERIFIED / NOT LIVE.
- **No Razorpay webhook** endpoint; `RAZORPAY_WEBHOOK_SECRET` blank → no server-side safety net; success depends entirely on the browser calling `/payments/razorpay/verify`.
- Razorpay `verify` checks **signature only** (no explicit `payment.captured`/amount cross-check against the gateway — signature does bind the order_id, so amount tampering is mitigated).
- Stripe amount is server-side (good). Stripe webhook signature-validated (good).
- Manual UPI / admin-manual both mark orders paid on admin action (expected, audited).

---

## 8. Security Risks

| Severity | Finding | Evidence |
|----------|---------|----------|
| CRITICAL | Mock-OTP admin/user takeover | `providers.py` `dev_otp`, `TEST_OTP=123456`, admin mobile `9999999999` ∈ `OTP_TEST_NUMBERS`; `auth_routes.py /login-otp/*` |
| HIGH | Weak/default admin creds & shared passcode | `.env` `ADMIN_PASSWORD=admin123`, `ADMIN_PASSCODE=admin123`; `core.py`/`auth_routes.py` fallback `"admin123"` |
| HIGH | JWT secret hardcoded fallback | `core.py:29` `JWT_SECRET=os.environ.get(..., "anjali-dev-secret-change-me")` — should fail fast if unset |
| MEDIUM | JWT stored in `localStorage` | `AuthContext.js`, `lib/api.js` → XSS token theft; 7-day token, no revocation, logout is server no-op |
| MEDIUM | CORS `allow_origins=["*"]` | `server.py:58` |
| MEDIUM | PII stored in plaintext | Aadhaar (`users.aadhaar_number`), PAN, bank acct/IFSC in `kyc_records` (masked only on API read) |
| LOW | `/api/admin/maintenance/reset-data` mass-delete | gated to super_admin + `confirm:"RESET"` (acceptable but high-blast-radius) |

---

## 9. Database Risks

- **Product reseed:** `server.py _init_db()` seeds the starter kit only when `products` is **empty** → if an admin deletes the last product, it reappears on restart. (P2)
- **Category reseed:** any of the 4 seed categories missing is re-created **every startup**. (P2)
- **Test/demo rows live in the DB right now:** users `DEMO01–DEMO10`, `RANKTOP/RANKM0x`, `rahul@t.com`, `priya@t.com`; orders `ORDDEMO10`, `ORDRANK*`, `DASHDEMO_*` commissions. The demo *seeder* is disabled, but these existing rows were never cleaned. (P2/P3 data hygiene)
- Data **persists** across refresh / relogin / restart (local MongoDB). Admin is re-synced from `.env` on every startup (password reset to env value if mismatched).

---

## 10. Authentication Risks
See §5 (P0-1/P0-2) and §8. Password hashing = bcrypt (good). Forgot-password is
**admin-request only, no OTP** (good, matches spec). Registration `/register` and
`/change-mobile` still gated behind **mock** OTP.

## 11. Admin Risks
Admin routes correctly `require_admin`; several super-admin-only (master, tree, reset,
audit-clear). Shared plaintext passcode = password is the main weakness.

## 12. Distributor / MLM Risks
- Immediate sponsor earns 0% on purchases (§6).
- **₹100 reward trigger inconsistency:** `admin_routes.approve_registration_request` pays the sponsor ₹100 **at approval** with **no sponsor-GREEN check**; `shop_routes._process_paid_order` pays it **at GREEN activation** and **only if sponsor is GREEN**. Same reward, two triggers, two eligibility rules — reconcile the intended rule.

## 13. Wallet & Withdrawal Risks
- Ledger reconciles exactly (verified). ✅
- **Non-atomic debit:** `request_withdrawal` reads `available_balance` then `$inc -amount` without a conditional guard → concurrent requests can drive balance negative (race). (P3)
- `withdrawal_minimum` setting ignored by backend but shown in Admin UI (mismatch).
- KYC-verified required before withdrawal. ✅

## 14. KYC / Data Privacy Risks
Aadhaar/PAN/bank stored plaintext; masked only on API responses. Consider encryption at
rest + strict access logging before production. Rejected/verified records are retained.

## 15. Frontend ↔ Backend Mismatches
- No UI currently displays "70%" or "44%", so there is **no visible numeric contradiction** — but the paid plan silently differs from the requested plan.
- `withdrawal_minimum` (₹500) shown in Admin Settings but **not enforced** by the API.
- Team page shows Level 1 income as the ₹100 reward only (immediate downline purchase = 0%), which is *consistent* with the current (wrong-target) backend.

## 16. Mock / Demo / Test Code Found
- `providers.py`: mock OTP, `TEST_OTP="123456"`, `dev_otp` echoed in beta.
- `.env`: `APP_ENV=beta`, `OTP_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `WHATSAPP_PROVIDER=mock`, test payment keys, `ADMIN_PASSWORD/PASSCODE=admin123`, `DEMO_PASSWORD`.
- `demo_seed.py` present (currently disabled) + demo rows already in DB.
- Checkout shows "Test card: 4242 4242 4242 4242".

## 17. Production Blockers
1. P0-1 Mock-OTP admin takeover.
2. P0-2 `dev_otp` exposure / mock OTP on register & change-mobile.
3. P1 Real payment keys + Razorpay webhook.
4. P1 Decide & implement the correct commission plan (70% vs current 44%).
5. P2 Remove test/demo data; stop category/product auto-reseed side-effects.
6. P2 Move JWT out of localStorage / fail-fast JWT secret; lock down CORS.
7. P2 Rotate/strengthen admin password + passcode.

## 18. Legal / Compliance Review Items (for a qualified professional — NOT legal advice)
Under the Consumer Protection (Direct Selling) Rules, 2021, ask a lawyer/compliance expert to review:
- Compensation-plan disclosure (is the depth/percentage plan documented for distributors?).
- Whether remuneration is tied to product sales vs recruitment (recruitment-incentive prohibition).
- Mandatory buy-back / return / refund / cancellation policy and grievance-officer mechanism.
- Invoice + seller-record retention; income-claim / earnings-representation compliance.
- Data-privacy handling for Aadhaar/PAN/bank details (storage, consent, retention).

---

## 19. Recommended To-Do List

**P0-1 — Mock-OTP admin takeover**
- Module: `auth_routes.py /login-otp/*`, `providers.py`, `.env`
- Problem/Evidence: admin mobile `9999999999` ∈ `OTP_TEST_NUMBERS`, `TEST_OTP=123456`; `login-otp/verify` returns admin JWT.
- Actual: anyone can log in as admin. Expected: no mock-OTP path can authenticate admins.
- Fix: remove admin mobile from test numbers, disable `login-otp/*` (or gate behind real SMS), never treat privileged accounts as test numbers.
- Test: backend — attempt `login-otp` for admin mobile → must fail.

**P0-2 — `dev_otp` exposure & mock OTP on register/change-mobile**
- Fix: never return `dev_otp`; require a real OTP provider before enabling `/register` & `/change-mobile`, or disable per business decision. Test: register/change flows.

**P1-1 — Correct the commission plan** _(do NOT build during this audit; decision required)_
- Confirm target: `D1=20,D2=12,D3=10,D4=8,D5=6,D6=5,D7=4,D8=3,D9=2` with **D1 = immediate sponsor**.
- Fix: replace `LEVEL_COMMISSION_PCT` and the level→depth offset in `_distribute_purchase_commission`; keep base=`subtotal`, idempotency, RED-skip.
- Test: forensic re-run of Tests A–I from the brief on isolated data.

**P1-2 — Razorpay webhook**
- Fix: add `POST /api/webhook/razorpay` with HMAC validation using `RAZORPAY_WEBHOOK_SECRET`; mark order paid idempotently via existing `_process_paid_order`. Test: signed webhook replay → single paid transition.

**P2 — Data hygiene & reseed**
- Remove `DEMO*`, `RANK*`, `*@t.com`, `DASHDEMO_*`, `ORDDEMO*/ORDRANK*` rows; decide whether category/product reseed should be one-time only.

**P2 — Auth hardening**
- JWT: remove hardcoded fallback (fail fast); consider httpOnly cookie; lock CORS to real origins; rotate admin password/passcode.

**P3 — Atomic withdrawal debit**
- Use a conditional update `{available_balance: {$gte: amount}}` and check `modified_count`.

**P3 — `withdrawal_minimum` consistency**
- Either enforce it in `request_withdrawal` or remove it from settings/UI.

---

## 20. Final Verification Matrix

| Module | Working | Partial | Broken | Not Tested | Priority |
|---|---|---|---|---|---|
| Registration (request→approve) | ✅ | | | | — |
| Login (email/mobile/ID + pw) | ✅ | | | | — |
| Password Recovery (admin-only) | ✅ | | | | — |
| Distributor ID (ANJ, unique) | ✅ | | | | — |
| Sponsor Tree (unlimited width) | ✅ | | | | — |
| Master ID (single MST000001) | ✅ | | | | — |
| RED/GREEN activation | ✅ | | | | — |
| Products | ✅ | | | | P2 (reseed) |
| Cart | ✅ | | | | — |
| Checkout | ✅ | | | | — |
| GST exclusion in commission base | ✅ | | | | — |
| Payments (Stripe/Razorpay/UPI) | | ⚠️ test only | | | P1 |
| Orders (lifecycle + delete) | ✅ | | | | — |
| ₹100 Direct Referral | ✅ | ⚠️ trigger inconsistency | | | P2 |
| 70% Team Commission | | | ❌ not implemented (44%) | | P1 |
| Commission Ledger | ✅ | | | | — |
| Wallet | ✅ | | | | — |
| Withdrawals | ✅ | ⚠️ non-atomic, min ignored | | | P3 |
| KYC | ✅ | ⚠️ plaintext PII | | | P2 |
| BV / Rank | ✅ (personal-purchase BV) | | | | — |
| Admin panel | ✅ | | | | — |
| Audit Logs | ✅ | | | | — |
| Security | | | ❌ mock-OTP takeover | | P0 |
| Database Persistence | ✅ | ⚠️ test rows present | | | P2 |
| Payment Webhooks | | ⚠️ Stripe only | ❌ no Razorpay | | P1 |
| Refunds | | | ❌ status only, no wallet/stock reversal | | P2 |
| Reports (CSV) | ✅ | | | | — |

**BV note:** `_personal_bv` = sum of the distributor's OWN paid-order subtotals (personal
purchase only; team purchases do NOT add BV). Ranks are display/threshold only and carry
no commission percentage — confirm this matches intended business rules.

_End of report._
