# HOME GENIES — External Integration Register

Inspection-only register of every external service the code talks to (or is expected to talk to), as of `main @ d31cb74`.
Nothing was run: no tests, no servers, no external calls. Environment variables are listed by **name only**. Whether a
variable is set in production **cannot be known from the repository**; that is written as "unknown in repo".

Classification (exactly one per row):
**IT** Integrated and tested · **IU** Integrated but unverified · **CM** Code exists but credentials/configuration missing ·
**NI** Not integrated · **NR** Not required for current stage · **BD** Requires a business decision.

"Tested" means a test in `backend/tests` drives the integration code path. Unless stated, no test calls the real external
service: tests stub, sign locally, or use a test adapter. Live behaviour with real credentials is unverified for **every**
integration.

---

## 1. Summary table

| # | Integration | Code | Env vars (names) | Tests | Class |
|---|---|---|---|---|---|
| 1a | Razorpay — create order / verify payment | `backend/shop_routes.py` `_razorpay_client`, `POST /api/payments/razorpay/order`, `POST /api/payments/razorpay/verify`; `frontend/src/pages/Checkout.js` `razorpayPay` (loads `checkout.razorpay.com/v1/checkout.js`) | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` | None of `tests/*.py` calls `/payments/razorpay/order` or `/verify` | **IU** |
| 1b | Razorpay — webhook | `backend/payment_events.py` `POST /api/webhook/razorpay` (HMAC, `webhook_events` claim, admin inspect/retry) | `RAZORPAY_WEBHOOK_SECRET` | `test_payment_events_b14.py`, `test_payment_integrity_batch1.py` (locally HMAC-signed payloads, duplicates, bad signatures) | **IT** |
| 2 | Stripe Checkout | `shop_routes.py` `_stripe`, `POST /api/payments/checkout`, `GET /api/payments/status/{id}`, `POST /api/webhook/stripe`; `backend/stripe_checkout.py` (official SDK fallback); `Checkout.js` "Place order & pay" | `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET` | Only a pre-gateway guard (`test_stock_reservation.py` expired order → 400). Webhook and status never tested; `tests/payflow.py`/`backend_test.py` are manual scripts against a live URL | **IU** |
| 3 | SMS OTP + notices (Twilio) | `backend/providers.py` (`_send_sms_otp`, `send_account_id_sms`, `send_security_notice_sms`, `otp_create/verify`) | `TWILIO_ENABLED`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `OTP_PEPPER`, `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN`; test only: `SMS_TEST_ADAPTER` (+ `DB_NAME` ending `_test`) | OTP logic heavily tested through the SMS test adapter (`test_sms_outbox`, 7 files). Real Twilio HTTP call never exercised (tests set `TWILIO_ENABLED=False`) | **IU** |
| 4 | Email (Emergent-managed Resend) | `backend/core.py` `send_email` → `https://integrations.emergentagent.com/api/v1/email/send` (hard-coded); only caller `vendor_invitations.py` | `EMERGENT_EMAIL_KEY`, `EMAIL_FROM_NAME` | None | **IU** |
| 5a | Image storage — Emergent Object Storage | `backend/storage.py` (`/api/uploads/profile-photo`, `/api/admin/uploads/product-image`, `GET /api/files/{path}`) | `EMERGENT_LLM_KEY`, `INTEGRATION_PROXY_URL` | None | **IU** |
| 5b | Image/document storage — Cloudinary signed direct upload (vendors) | `backend/governance_routes.py` `POST /api/vendor/uploads/sign`, `cloudinary_signature`; `frontend/src/components/vendor/ImageInput.js` | `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `CLOUDINARY_UPLOAD_PRESET` | `test_governance_security.py` (503 when unset, signature correctness, secret never returned). The upload to Cloudinary itself is browser-side and untested. **Not listed in `deploy/ENVIRONMENT.md`** | **CM** |
| 6 | Google sign-in (Emergent-managed auth) | Frontend redirect to `https://auth.emergentagent.com/?redirect=…` (`Login.js`, `Register.js`, `AuthExtras.js`) → `AuthCallback.js` → `POST /api/auth/google/session`, `/api/auth/forgot/google`; backend `auth_routes._google_identity` calls hard-coded `https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data` | None (no key; trust is in the Emergent session id) | `test_forgot_google.py`, `test_identity_batch4.py`, `test_security_batch0.py`, `test_vendor_onboarding.py` — all **stub** `_google_identity` | **IU** |
| 7 | Manual UPI (admin-confirmed) | `shop_routes.py` `/payments/upi-claim`, `/admin/payments/upi-confirm|reject`, `/admin/payments/manual` | none (UPI details from settings) | `test_cycle9_upi_ref.py`, `test_upi_adminlogin.py`, others | **IT** (no external service) |
| 8 | GST invoice — numbering + printable invoice | `next_sequence("invoice","INV",6)` in `shop_routes.py`, `stock.py`, `finance_routes.py`; GST-inclusive line breakdown in `create_order`; `frontend/src/pages/OrderDetail.js` "Invoice" → `window.print()` | none | `invoice_number` asserted in 8 test files; GST math in `test_owner_decisions.py`, `test_money_exact.py` | **IT** (internal only) |
| 9 | GST e-invoicing (IRP/IRN), GSTIN on invoice, PDF invoice | none | — | — | **BD** |
| 10 | PIN-code lookup | `frontend/src/pages/Register.js` browser `fetch("https://api.postalpincode.in/pincode/<code>")`, falls back to manual state/city | none | No backend/frontend test | **IU** |
| 11 | Scheduled jobs (Vercel Cron) | `backend/vercel.json` crons → `cron_routes.py` `/api/cron/release-points`, `/api/cron/expire-pending-orders` | `CRON_SECRET` (Vercel) / `WEBHOOK_CRON_SECRET` (Emergent) | Cron endpoints covered by many tests (bearer secret) | **IT** |
| 12 | Push notifications (web push / FCM / OneSignal) | none — only in-app `notifications` collection (`core.create_notification`) | — | — | **NR** |
| 13 | Analytics (GA4, PostHog, Mixpanel…) | none | — | — | **BD** |
| 14 | Error monitoring (Sentry etc.) | none (`KNOWN_GAPS_AND_RISKS.md` R-10; Batch 11 audit: "required before public launch") | — | — | **NI** |
| 15 | WhatsApp | Only a `https://wa.me/?text=` click-to-chat link on `pages/Referral.js` (no API, no credentials). No WhatsApp Business Platform code | — | none | **NI** (API) |
| 16 | Social media (Facebook/Instagram/X…) | none. `ProductDetail.js` uses the browser Web Share API / clipboard only | — | — | **NI** |
| 17 | Maps / geocoding | none | — | — | **NR** |
| 18 | Couriers / logistics | none. Carrier, tracking number and URL are typed in by vendors; `cod_rules.py` records COD evidence as `verified_by_system: False` because "no courier or provider integration exists" | — | — | **BD** (owner decision D-03/D-04 on delivery and COD evidence) |
| 19 | AI / LLM | none in code. `requirements.txt` carries `openai`, `litellm`, `google-genai` (Emergent image defaults) but nothing imports them; `EMERGENT_LLM_KEY` is used only as the storage key | — | — | **NR** |
| 20 | Web fonts (Google Fonts) | `frontend/public/index.html`, `frontend/src/index.css` | none | — | **IU** (static CDN dependency, nothing to configure; listed for privacy/CSP completeness) |

---

## 2. Detail per integration

### 2.1 Razorpay (primary online payment in the UI)
- **Flow:** `create_order` (status `payment_pending`) → `POST /payments/razorpay/order` creates the gateway order for the
  server-side amount, records `payment_transactions{provider:"razorpay", session_id:<rzp order id>}` and
  `orders.razorpay_order_id` → browser checkout.js → `POST /payments/razorpay/verify` (signature verification, then
  `client.payment.fetch` to confirm the payment belongs to the order) → `_process_paid_order`. The webhook
  (`payment_events.py`) is the backstop: HMAC on raw body, unique `webhook_events` claim per event id, maps by gateway
  order id only (never amount/email), late/cancelled orders flagged for refund, admin list + retry.
- **Unset behaviour:** `_razorpay_client` → 503 "Online payment is not configured yet"; webhook → 503.
- **External dependencies:** Python `razorpay==2.0.1` (in `requirements.txt`, `pyproject.toml`, `deploy/vercel-api/requirements.txt`);
  browser script `https://checkout.razorpay.com/v1/checkout.js` (must be allowed by any future CSP).
- **Configuration requirements:** Razorpay account with KYC/activation (business decision + paperwork), live keys,
  webhook registered at `https://<api>/api/webhook/razorpay` with the same secret, events `payment.captured`,
  `order.paid`, refund events as `payment_events.normalise` expects. Production values: unknown in repo.
- **Gap:** order/verify against a real gateway has no automated test; needs a Razorpay test-mode run before launch.

### 2.2 Stripe Checkout (second "Place order & pay" path)
- **Library selection** (`shop_routes.py` lines 11–16): tries Emergent's private `emergentintegrations` package; on
  `ImportError` falls back to `backend/stripe_checkout.py` on the official `stripe` SDK. `emergentintegrations==0.2.0`
  is in `requirements.txt` but is **not installable outside Emergent's image**; the master audit records that the test
  environment used the fallback. `stripe==14.4.1` is in `requirements.txt` and `pyproject.toml`.
- **Placeholder key:** `STRIPE_API_KEY` defaults to `sk_test_emergent`; the fallback treats that and empty as "not
  configured" → 503. On the Emergent path there is no such guard (the Emergent proxy accepts the placeholder).
- **Webhook:** fallback rejects every webhook without `STRIPE_WEBHOOK_SECRET`; payment still confirmed when the customer
  returns via `/payments/status/{session_id}`. `payment_status` swallows errors with `print` (no monitoring).
- **Untested:** no test reaches `create_checkout_session`, `get_checkout_status` or `/webhook/stripe`.
- **Deployment defect (stale folder):** `deploy/vercel-api/requirements.txt` **does not list `stripe`**. If that legacy
  deploy folder were used, `from stripe_checkout import …` raises inside the `except ImportError` block and the whole
  API fails to import. Its `vercel.json` also lacks the `expire-pending-orders` cron. `ENVIRONMENT.md` documents the
  `backend/` root (pyproject) as the real deployment, so this is a latent trap rather than a live fault.
- **Business decision:** two card gateways (Razorpay + Stripe) are offered side by side. Stripe has restricted onboarding
  of new India-registered businesses (invite-only since 2024 — confirm current status with Stripe); the owner should decide whether Stripe stays (BD noted; row classified IU because the code is live).

### 2.3 SMS / OTP (Twilio)
- Twilio Messages REST API called directly with `httpx` (the `twilio` package in `requirements.txt` is unused).
- Fails safe: no provider → 503 `OTP_SERVICE_UNAVAILABLE`; codes are HMAC-peppered, attempt-reserved atomically,
  never returned or logged. Test adapter only on a `*_test` DB.
- **Configuration requirements (India):** DLT registration (TRAI) of the entity, header/sender ID and every SMS
  template (OTP, member-ID, security-notice texts in `providers.py`) — without DLT, Indian carriers drop the messages.
  `OTP_PEPPER` must be set (empty pepper still works but weakens hashing). Production values: unknown in repo.
- `governance_routes.my_verification` reports `provider_available` from `TWILIO_ENABLED` alone (not full config).

### 2.4 Email
- `core.send_email` posts to a **hard-coded Emergent endpoint**; returns `False` silently when `EMERGENT_EMAIL_KEY` is
  unset or the call fails. Only used for vendor invitations (`vendor_invitations.py`, which also needs
  `FRONTEND_PUBLIC_URL` or falls back to the first `CORS_ORIGINS` entry). No transactional order emails exist.
- Hosting on Vercel still depends on Emergent's email service being reachable and the key valid. No SPF/DKIM/domain
  configuration is visible in repo. Class IU (code live, never tested). Business decision pending: keep Emergent-managed
  email or move to a direct provider account.

### 2.5 File / image storage — two systems
- **Emergent Object Storage** (`storage.py`): profile photos and admin product images. `init` with `EMERGENT_LLM_KEY`,
  objects proxied back through `GET /api/files/{path}` (the API serves every image byte — Vercel bandwidth/60 s limit
  apply). Unset key → upload 502. No tests.
- **Cloudinary** (`governance_routes.py` `/vendor/uploads/sign`): server-signed direct browser upload, server fixes
  folder/public_id/formats, documents uploaded as `type=authenticated`. Without the four `CLOUDINARY_*` variables the
  endpoint returns 503 and the vendor UI falls back to pasting an https URL. **These variables are missing from
  `deploy/ENVIRONMENT.md`** → classified CM.
- Note for reading authenticated documents back: delivery of `type=authenticated` assets needs signed delivery URLs;
  confirm the admin review screens can open them before relying on this path.
- Business decision: two storage back-ends; consolidate on one (Cloudinary is self-owned; Emergent storage ties
  production to Emergent).

### 2.6 Google sign-in
- Emergent-managed OAuth: the browser goes to `auth.emergentagent.com`, returns with `session_id`; the backend exchanges
  it at `demobackend.emergentagent.com` (hard-coded, host name says "demo"). The server issues a short-lived
  `google_signup_token` so the client cannot self-assert `google_verified` (SEC-05). Tests stub the exchange.
- No Google Cloud OAuth client of HOME GENIES' own exists. Production reliance on an Emergent demo host is a risk;
  a self-owned Google OAuth client (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`, verified consent screen) would be the
  replacement — that is a business decision.

### 2.7 GST invoicing
- Internal: GST-inclusive pricing (Decision 1), per-line `gst_rate`, `taxable_paise`, `gst_paise`, `hsn_code`;
  invoice number assigned on payment / COD confirmation; printable HTML invoice via `window.print()`.
- Not present: seller GSTIN / legal entity block on the invoice per supplier (marketplace with vendors → each vendor is
  the supplier for its lines), credit notes for refunds, PDF archive, IRP e-invoice (mandatory above the turnover
  threshold), TCS under GST section 52 for e-commerce operators. All **BD** (tax advisor + owner).

### 2.8 PIN-code lookup
- Browser-to-third-party call from `Register.js` only (not from saved addresses or checkout). Free public service, no
  SLA, no key; failure degrades to manual entry. A future CSP must allow `api.postalpincode.in` in `connect-src`.
  No serviceability check exists — PIN code is not used for delivery eligibility.

### 2.9 Not integrated
- **Push:** in-app notifications only — NR.
- **Analytics:** no tracker of any kind; adding one needs a privacy notice/consent decision under DPDP — BD. (The
  Marketing Studio design keeps its own first-party click counts and does not need a third-party tracker.)
- **Error monitoring:** NI; flagged pre-launch blocker by the Batch 11 audit. Would need e.g. `SENTRY_DSN` (backend) and
  a public DSN in a `REACT_APP_*` variable.
- **WhatsApp / social:** NI beyond `wa.me` and the Web Share API (see the Marketing Studio architecture document).
- **Maps:** NR. **Couriers:** BD (delivery proof and COD evidence decisions D-03/D-04).

---

## 3. Exact missing configuration and dependencies

1. `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`, `CLOUDINARY_UPLOAD_PRESET` — used by code,
   absent from `deploy/ENVIRONMENT.md`.
2. `FRONTEND_PUBLIC_URL` — read by `vendor_invitations.py`, absent from `deploy/ENVIRONMENT.md`.
3. `SMS_TEST_ADAPTER`, `COD_MAX_AMOUNT_RUPEES`, `RATE_LIMIT_SCALE`, `TRUSTED_PROXY_HOPS`, `VENDOR_TERMS_VERSION`,
   `STOCK_RECOVERY_MIN_AGE_SECONDS` — read by code, undocumented (`SMS_TEST_ADAPTER` must never be set in production).
4. `deploy/vercel-api/requirements.txt` lacks `stripe`; its `vercel.json` lacks the `expire-pending-orders` cron.
   Either delete the legacy folder or bring it in line (owner/dev decision).
5. `emergentintegrations` (requirements.txt) is private; outside Emergent the code relies on the `stripe` fallback.
   Unused heavy packages in `requirements.txt` (`twilio`, `openai`, `litellm`, `google-genai`, `boto3`, `pandas`…) — not
   harmful on Vercel (pyproject is used) but misleading.
6. External accounts whose existence/production values are **unknown in repo**: Razorpay (live keys + webhook
   registration), Stripe (key + webhook endpoint), Twilio (+ India DLT registration), Emergent email key and sender
   domain, Emergent storage key, Cloudinary account.
7. Hard-coded external hosts (no env override): `integrations.emergentagent.com` (email), `demobackend.emergentagent.com`
   (Google identity), `auth.emergentagent.com` (frontend), `api.postalpincode.in`, `checkout.razorpay.com`.
8. Not configured anywhere: error monitoring, analytics, CSP header listing the hosts above.

## 4. Sources
- Repository files cited inline. Batch 11 audit: `docs/HOME_GENIES_BATCH11_PRE_RELEASE_AUDIT.md`;
  known gaps: `docs/KNOWN_GAPS_AND_RISKS.md`; owner decisions: `docs/OWNER_DECISION_REGISTER.md`.
