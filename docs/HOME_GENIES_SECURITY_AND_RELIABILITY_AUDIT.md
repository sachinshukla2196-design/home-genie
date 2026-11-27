# HOME GENIES — Security and reliability audit (independent inspection)

Scope: backend (`backend/`, FastAPI + Motor) and frontend (`frontend/`, CRA/React 19) at git `main @ d31cb74`, clean tree.
Method: **static reading only** — no tests, servers, network installs or database connections were run, and no secret values were
read or printed (the only env file present, `frontend/.env.development.local`, is git-ignored and holds `REACT_APP_BACKEND_URL`,
`BROWSER`). **[V]** = verified in code with a citation; **[S]** = suspicion / needs runtime or vendor confirmation.

Companion documents: `docs/HOME_GENIES_DATABASE_ARCHITECTURE.md` (collections, indexes, retention, PII at rest) and
`docs/HOME_GENIES_PERMISSION_MATRIX.md` (every sensitive action × role).

---

## A. Verdict and ranked findings

**No P0 (anonymous, directly exploitable, high-impact) vulnerability was found.** Payment webhooks are authenticated, OTP
verification is race-safe, admin routes are all guarded, and no IDOR was found on customer, vendor or staff data. The main risks are
(1) business-logic abuse available to any registered account, (2) weak protection of the administrator accounts that hold money
authority, (3) plaintext identity/bank data, and (4) operational prerequisites (migration-created unique indexes, backups, monitoring)
that are not enforced by the code.

| ID | Sev | Finding | Evidence |
|---|---|---|---|
| **P1-1** | P1 | **Unlimited order creation; COD orders lock stock forever.** `POST /api/orders` has no rate limit, no cap on open orders, and an unbounded `items` list (qty ≤ 50 per line). Stock is reserved at creation for every order; only *online* unpaid orders expire (15 min) — COD orders never expire and immediately notify vendors. One account can reserve the entire stock of any product and flood vendors. | `shop_routes.create_order` l.146-279 (no `rate_limit`; `reserve_for_order` l.264; `notify_order_vendors` l.275); `CreateOrder.items: List[OrderItemIn]` l.138; `stock.expire_pending_online_orders` l.474-476 filters `payment_method: "online"`; `deploy/ENVIRONMENT.md` "COD orders are never expired" |
| **P1-2** | P1 | **Admin accounts (money authority) are password-only.** No MFA/OTP at admin login; lockout is per *(IP, username)* so guessing from many IPs is unbounded; session is a 7-day HS256 bearer token kept in `localStorage`; the frontend ships **no CSP / X-Frame-Options** (security headers exist only on API responses), so any XSS or malicious dependency steals a 7-day admin token. New admins start with a 12-char temp password; the seeded super admin's strength is only warned about. | `auth_routes.admin_login` l.526-561 (`ident = admin:<ip>:<user>` l.534); `core.create_token` l.77-87 (`exp` 7 days); `frontend/src/lib/api.js:34`, `ForcePasswordChange.js:36` (`localStorage "anj_token"`); `frontend/vercel.json` (no `headers`); `server.SECURITY_HEADERS` l.167; `admin_team.NewAdminIn.temporary_password min_length=12` l.56; `server._init_db` l.297-298 |
| **P1-3** | P1 | **Full Aadhaar, PAN and bank account numbers stored in plaintext** in `users`, `registration_requests`, `kyc_records`, `vendors`, `vendor_change_requests`; no app-level encryption anywhere; no retention/anonymisation. [S] Storing full Aadhaar numbers without an Aadhaar Data Vault / encryption is likely non-compliant with UIDAI Aadhaar (Data Security) Regulations 2016 and the DPDP Act 2023 — legal confirmation needed. | `wallet_routes.submit_kyc` l.113-137; `auth_routes.register_request` l.230, `register` l.294; `admin_routes.admin_update_user` l.1288; `governance_routes.request_bank_change` l.194; `grep encrypt|fernet|cryptography` → none; `admin_routes.delete_user` l.1239 "Personal-data anonymisation is not performed" (KNOWN_GAPS R-9 acknowledges) |
| **P1-4** | P1 | **Money idempotency depends on unique indexes the app never creates.** Startup only logs missing indexes; ledger, wallet-op, refund-case, webhook, stock-txn, settlement and wallet uniqueness exist only if `scripts/vendor_foundation_migrate.py --apply` was run. Without them, concurrent duplicates are inserted silently (code relies on `DuplicateKeyError`). | `server._init_db` l.261-263 → `db_indexes.check_missing` l.183; `ledger.post_entry` l.53-57; `financial_ops.ensure_ledger` l.40-45; `payment_events.claim` l.77-82; `finance_routes.create_settlement` l.317 |
| **P1-5** | P1 | **Authentication trust delegated to a third-party "demo" endpoint.** Google sign-in *and* Google password recovery accept whatever e-mail `https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data` returns for a client-supplied `session_id`; `/forgot/google` then issues a password-reset token. Availability or integrity problems at that service become account takeover for every account with a verified / Google-linked e-mail. Object storage and e-mail also depend on Emergent endpoints. | `auth_routes.EMERGENT_SESSION_DATA_URL` l.390, `_google_identity` l.397-409, `google_session` l.413, `forgot_google` l.468-492; `storage.STORAGE_BASE` l.14; `core.EMAIL_BASE_URL` l.397 |
| **P1-6** | P1 | **No backup/restore tooling, no error monitoring, no alerting** on money paths or cron failures. Checklist items remain unchecked. | `grep sentry|prometheus|datadog|opentelemetry` → none; no `mongodump` script; `docs/PRODUCTION_READINESS_CHECKLIST.md` "Production" section; `cron_routes._run_release` l.32-35 only logs |
| **P2-1** | P2 | **Stripe status poll treats `status == "complete"` as paid** even when `payment_status` is not `paid` (delayed-notification methods), and the Stripe paths never compare amount/currency with the order (the Razorpay path does). | `shop_routes.payment_status` l.769-783 (`if status.payment_status == "paid" or status.status == "complete"`); `stripe_webhook` l.787-803; contrast `payment_events.apply` l.129-133 |
| **P2-2** | P2 [S] | **Stripe webhook signature verification on Emergent hosting is unverifiable.** When `emergentintegrations` is importable, `StripeCheckout` is built without a webhook secret (`_stripe` l.410-415); whether its `handle_webhook` verifies `Stripe-Signature` cannot be checked from this repo. If it does not, a forged event can call `_process_paid_order` for **any** `payment_transactions.session_id` (it does not check `provider == "stripe"`), including Razorpay attempts. The non-Emergent path (`stripe_checkout.handle_webhook` l.96-100) does verify. | `shop_routes` l.11-16, 410-415, 787-803, `_process_paid_order` l.696-700 |
| **P2-3** | P2 | **support_admin / accounts_admin are far broader than documented**: create/edit/delete platform products and prices, adjust stock; verify member KYC alone; initiate refunds; decide returns; mark platform orders delivered (starts commission release clock); deactivate members; read/export all PII. | Doc 2 §8; `admin_routes` l.244, 263, 295, 389, 736; `returns_routes` l.273, 737 |
| **P2-4** | P2 | **PII exposure inconsistent and partly unaudited.** `orders.csv` is restricted and masked (and audited), but `GET /api/admin/reports/registrations/export` gives any admin role full e-mail + mobile of all members (5,000 rows) without an audit entry; `accounts_admin` masking in order-ops is bypassed by `/admin/orders`, `/admin/users`, `/admin/refund-queue`. | `admin_routes.REPORTS` l.1464-1475, `export_report` l.1494 (no `log_audit`); `admin_order_ops.export_orders` l.126-145 vs `admin_routes.admin_users` l.118, `admin_orders` l.361, `refund_queue` l.518-540 |
| **P2-5** | P2 | **Single-person money decisions**: COD cash confirmation, UPI/manual payment confirmation, vendor bank-change approval (applied straight to the vendor record, no confirmation by the vendor's trusted contact — a single finance user can redirect future settlements), commission release-now, refund case closed as `no_refund`, final vendor approval. Two-person rules are also circumventable by the super admin creating a helper admin when SMS is off. | `cod_rules.CONFIRM_ROLES` l.26; `shop_routes.upi_confirm` l.919, `manual_payment_by_distributor` l.874; `governance_routes.decide_change` l.233-252; `admin_routes.commission_status` l.606; `returns_routes` l.295-299; `governance_routes.forced_change_needs_otp` l.420 |
| **P2-6** | P2 | **Account takeover by insiders when SMS is not configured**: admin password reset (admin knows the temp password and no OTP is required to finish the forced change); vendor-owner invitation token is returned to the admin when e-mail is not configured; registration without SMS accepts unproven mobiles. | `governance_routes.forced_change_needs_otp` l.420-424; `vendor_invitations.issue` l.53; `auth_routes.register_request` l.214-220; `vendor_applications.apply_to_sell` l.115-122 |
| **P2-7** | P2 | **Profile photo endpoint bypasses the upload controls**: accepts any `http://…` URL or any `data:image/*` (incl. SVG) up to 4 MB stored *inside the user document*, which `get_current_user` loads on every request and admin lists load ×1000. The multipart upload reads the whole file before the 5 MB check. (Batch 11 L11, still open.) | `auth_routes.update_photo` l.578-587; `core.get_current_user` l.134; `admin_routes.admin_users` l.122; `storage._upload_image` l.77-79 |
| **P2-8** | P2 | **Missing indexes on hot paths and unbounded admin lists** → latency / memory exhaustion as data grows: `orders.user_id`, `files.storage_path` (every public image), `audit_logs` (none), `users.role`, `payment_transactions.order_id`, `commissions.order_id/status`; admin lists load 500–5,000 documents unpaginated; dashboard revenue sums floats of at most 5,000 orders (wrong totals beyond that, refunds ignored). | Doc 1 §2.1; `admin_routes.admin_dashboard` l.97-101, `admin_users` l.122, `admin_orders` l.365, `admin_payments`, `admin_commissions`, `admin_kyc` l.643, `admin_withdrawals`; `vendor_routes.admin_vendors` (N+1 `count_documents`) |
| **P2-9** | P2 | **Daily cron on a 60 s function** processes ≤5,000 commissions with several unindexed queries each; overruns or truncation are silent. `expire-pending-orders` (refund-case creation, ledger reconcile) also runs only daily. | `backend/vercel.json`; `commission.release_due_points` l.304-313; `cron_routes` l.57-84 |
| **P2-10** | P2 | **Outdated web framework pins** (no network check performed): `fastapi==0.110.1` / `starlette==0.37.2` (2024). [S] Starlette < 0.40.0 is affected by CVE-2024-47874 (multipart form DoS) and < 0.47.2 by CVE-2025-54121 (large-upload event-loop block); confirm with `pip-audit`. `uvicorn==0.25.0` old. | `backend/pyproject.toml`, `backend/requirements.txt` |
| **P2-11** | P2 | **Member lockout DoS and account enumeration** (Batch 11 L7, L8 still open): 5 bad passwords lock any identifier for 15 min; `/auth/send-otp` and `/auth/register-request/send-otp` answer "already registered" for e-mail/mobile. | `auth_routes.login` l.338-346, `send_otp` l.101-104, `register_request_send_otp` l.164 |
| **P3-1** | P3 | Public, unauthenticated `/api/files/{path}` with `Cache-Control: public, immutable` (profile photos are public by unguessable URL). | `storage.serve_file` l.118-129 |
| **P3-2** | P3 | `/api/payments/status/{session_id}` is unauthenticated and calls the Stripe API on every request for unpaid sessions (amplification; leaks order id/status for a known session id). | `shop_routes.payment_status` l.768-783 |
| **P3-3** | P3 | Stripe `success_url`/`cancel_url` built from client-supplied `origin_url` (open redirect through Stripe). | `shop_routes.create_checkout` l.428-429 |
| **P3-4** | P3 | Razorpay de-duplication uses the unsigned `X-Razorpay-Event-Id` header in preference to the signed body id; a replayed genuine body with a new header id is re-processed (effects stay idempotent via the order CAS). | `payment_events.normalise` l.60, `razorpay_webhook` l.169 |
| **P3-5** | P3 | `OTP_PEPPER` defaults to empty; with a 6-digit space the stored HMAC gives little protection if the DB leaks during a code's 5-minute life. | `providers.py` l.20, 58-59 |
| **P3-6** | P3 | Inconsistent password policy: 6 chars (register-request), 8 (resets, change), 10 (admin temp reset), 12 (new admin temp), 14 (admin self-change). bcrypt silently uses only the first 72 bytes. | `auth_routes` l.189, 500, 697; `admin_routes` l.1417; `admin_team` l.56; `governance_routes` l.451 |
| **P3-7** | P3 | Admin seed can promote an existing **member** account whose (unverified) e-mail equals a newly configured `ADMIN_EMAIL` to `super_admin` with the env password (data-integrity issue, not a takeover: the attacker does not learn the password). | `server._init_db` l.316-343 |
| **P3-8** | P3 | 503 responses list missing env variable **names** to anonymous callers. | `server._ensure_initialised` l.147-148 |
| **P3-9** | P3 | Stripe errors written with `print()` (unstructured; may include provider messages); `payment_events` stores exception text (≤200 chars) visible to finance admins. | `shop_routes` l.781, 794; `payment_events` l.177 |
| **P3-10** | P3 | Public catalogue suggest runs an unanchored case-insensitive regex per keystroke (cannot use an index), no rate limit. | `discovery.suggest` l.105-120 |
| **P3-11** | P3 | Stale, git-ignored deployment copy `deploy/vercel-api/backend/` differs from `backend/` in 11/12 files and schedules only one cron; deploying it would ship old code. | `cmp` of the two trees; `deploy/vercel-api/vercel.json` |
| **P3-12** | P3 | Wallet credits: neither maker nor checker is prevented from being the beneficiary (Batch 11 L4 open). | `admin_routes.apply_wallet_credit` l.1362; `financial_approvals.approve` l.89 |

---

## B. Authentication and OTP

**[V] Working as intended**
* OTP generation: `secrets.randbelow(10**6)`, HMAC-SHA256 hash stored, 5-minute TTL, 60 s resend cooldown, previous codes invalidated
  (`providers.otp_create` l.131-161). Delivery only via Twilio; no OTP in responses or logs; a test adapter works only with
  `SMS_TEST_ADAPTER=true` **and** a `*_test` database name (l.32-38).
* OTP verification (Batch 11 C-1 fixed): each attempt is reserved atomically (`attempts < max` and `used: false` in one
  `find_one_and_update`, l.185-191), consumed with a second CAS (l.194-196), constant-time compare (l.192), and every attempt counts
  against a per-identifier+purpose daily budget of 20 (`otp_attempts_identifier`, core.py:451; l.184). Max success probability per
  number per day ≈ 20/10⁶.
* Login flows refuse admins on member/OTP/Google logins (SEC-11: auth_routes l.380, 432, `_eligible_for_login_otp` l.640); blocked,
  deleted, suspended and not-activated accounts get no token.
* Google pre-hijack fixes (C-3, C-9): Google sign-in links only accounts whose e-mail was proven (`google_session` l.434-438); legacy
  `/register` now stores `email_verified: False` (l.290); `/forgot/google` requires a proven e-mail (l.482).
* Change mobile needs OTPs to both the current and the new number (l.772-815); admin-proposed contact changes need the holder's OTP or a
  super-admin recovery by someone other than the proposer (contact_change.py).
* Reset tokens and invitation tokens: 256-bit, stored as sha256, single-use by CAS, short expiry (auth_routes l.485-511;
  vendor_invitations l.25-28, 128-131; vendor_staff.new_invite_token l.175).

**Gaps:** P1-2 (admin MFA), P1-5 (third-party identity), P2-6 (no-SMS fallbacks), P2-11 (lockout DoS, enumeration), P3-6 (policy).
Legacy accounts may still carry an unproven `email_verified: true` (KNOWN_GAPS R-5) — not rewritten.

## C. Sessions / JWT

* [V] `create_token` (core.py:77): HS256, `sub`, `type: access`, `iat`, `iat_ms`, `jti`, `exp = +7 days`. `_decode` (l.90) requires
  `exp`+`sub` and `type == access`, algorithm pinned to HS256 (no `alg=none`).
* [V] `get_current_user` (l.123-150) re-reads the user, rejects revoked `jti` (`revoked_tokens`, TTL-cleaned), tokens issued before
  `password_changed_at` (ms precision), blocked/suspended/deleted/not-activated users, and gates `must_change_password`.
* [V] Logout revokes the current token (`revoke_token_from_request` l.513); password change revokes all others.
* `JWT_SECRET` missing or `change-me` ⇒ every request 503 (core.py:39-41, server.py:147). The same secret also signs short-lived
  `google_signup` tokens, kept apart by `type` (auth_routes l.133-149).
* Gaps: no refresh/rotation, no idle timeout, no admin-specific shorter lifetime, token in `localStorage` (P1-2). Tokens issued before
  `jti` existed cannot be revoked by logout (KNOWN_GAPS R-6, expires within 7 days).

## D. Rate limiting and client IP

* [V] `core.rate_limit` (l.482-498): MongoDB fixed window, unique `(key, w)`, TTL cleanup, `Retry-After`. Limits table l.446-452.
* [V] `core.client_ip` (l.466-479, Batch 11 C-2 fixed): uses `X-Forwarded-For` only on Vercel (`VERCEL` env) or when the socket peer
  is private/loopback, and then takes the **rightmost** entry (`TRUSTED_PROXY_HOPS`). Correct for Vercel. [S] Behind any other public
  proxy the proxy's IP becomes everyone's IP, so per-IP limits become global (KNOWN_GAPS R-1 / D-10).
* `RATE_LIMIT_SCALE` (l.445) can multiply every limit from the environment; not documented in `deploy/ENVIRONMENT.md`.
* Unlimited endpoints of note: `POST /api/orders` (P1-1), `/api/catalog/*`, `/api/payments/status/*`, `/api/files/*`,
  `/api/auth/register` (legacy, OTP-gated), `/api/auth/reference-codes`.

## E. API authorisation

* [V] Every `/api/admin/*` route has an admin dependency (route inventory of 293 decorated handlers; none under
  `/api/admin` lacks `require_admin` or a stricter guard). Public routes are the intended ones (auth, catalogue, settings, webhooks
  with signature, cron with secret, invitation token look-ups, files).
* [V] Vendor and staff scoping is server-side (`vendor_routes.require_vendor_user` l.66, `vendor_staff.authorize_staff` l.185, explicit
  path rules, default deny). Owner blocked ⇒ staff blocked (C-17 fixed).
* [V] Customer data access is owner-checked (orders l.388, returns, addresses, KYC, wallet, notifications). No IDOR found.
* Gaps are about **breadth of admin roles**, not missing checks — see P2-3, P2-5 and Doc 2.

## F. Webhooks and payments

| Channel | Authentication | Validation | Idempotency | Verdict |
|---|---|---|---|---|
| Razorpay webhook `POST /api/webhook/razorpay` | HMAC-SHA256 of raw body with `RAZORPAY_WEBHOOK_SECRET`, `hmac.compare_digest`; missing secret ⇒ 503 (payment_events l.48-52, 160-167) | matched only by **our** gateway order id; currency INR; amount == order `total_paise`; final status required (l.104-144) | unique `event_id` claim with stale-claim takeover (l.74-91); order CAS in `_process_paid_order` | Sound (P3-4 minor) |
| Razorpay client verify `POST /api/payments/razorpay/verify` | SDK signature check + server fetch of the payment (shop_routes l.487-522) | order id and amount compared; `authorized` is not treated as paid | order CAS | Sound; does not check that the caller owns the transaction (harmless — it can only confirm a genuine payment) |
| Stripe webhook `POST /api/webhook/stripe` | Official SDK path: `stripe.Webhook.construct_event` with `STRIPE_WEBHOOK_SECRET` (stripe_checkout l.96-100). Emergent path: **unverifiable** (P2-2) | none (no amount/currency/provider check) | order CAS | P2 |
| Stripe status poll `GET /api/payments/status/{sid}` | none (public) | `complete` treated as paid (P2-1) | order CAS | P2 |
| UPI / manual confirmation | finance roles | exact amount, UTR unique (`payment_references._id`) | yes | 1P (P2-5) |
| Cron | `Authorization: Bearer` == `CRON_SECRET`/`WEBHOOK_CRON_SECRET`, constant-time; empty secret ⇒ 401 (cron_routes l.17-23) | — | `cron_runs.run_id` (not unique) + idempotent jobs | Sound |

## G. Sensitive data, encryption and uploads

* Encryption at rest: none at application level (P1-3). [S] Atlas/disk encryption not visible in repo.
* Masking in responses is consistent for Aadhaar/PAN/bank (`core.clean_user`, `admin_kyc`, `_public_vendor`, `wallet_routes.get_kyc`);
  audit records store masked values for KYC edits and contact changes.
* Uploads (`storage._upload_image` l.73-103): MIME allow-list **and** magic-byte sniffing (CAT-08), 5 MB cap (after full read), stored
  under a server-chosen UUID path, re-served with the sniffed type. Signed Cloudinary uploads (`governance_routes.sign_upload`
  l.481-503): server fixes folder, public id, formats, `overwrite=false`, documents as `type=authenticated`; image ownership enforced
  for Cloudinary URLs (`validate_image_ownership` l.503-514).
* `validators.safe_image_refs` (l.5-17) blocks `javascript:`, `data:`, `http:`, protocol-relative, traversal, quotes/brackets — but
  **is not used by `PUT /api/auth/profile/photo`** (P2-7). Vendor document URLs may be any https link (not necessarily Cloudinary).
* CSV exports use formula-injection escaping (`finance_routes._csv_safe`, `catalogue.csv_safe`).

## H. CORS, CSP and security headers

* [V] CORS (server.py:118-121, 211-217): explicit origin list from `CORS_ORIGINS`/`CORS_ALLOWED_ORIGINS`, `*` refused (503 until set),
  credentials allowed, all methods/headers. Bearer-token auth (not cookies) ⇒ CSRF not applicable. The 500 handler re-adds CORS
  headers only for allowed origins (l.200-204).
* [V] API security headers (l.167-189): `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`, `COOP`; HSTS when
  the request is https or `X-Forwarded-Proto: https`.
* [V] **Frontend has no security headers at all**: `frontend/vercel.json` defines only build and rewrites; `public/index.html` loads
  Google Fonts; `Checkout.js:93` injects `https://checkout.razorpay.com/v1/checkout.js` at run time. No CSP, no frame protection for
  the admin UI (clickjacking), no HSTS beyond the host default (P1-2; KNOWN_GAPS R-10).
* No `dangerouslySetInnerHTML` in `frontend/src` [V].

## I. Audit logging

* [V] `core.log_audit` (l.378-393) records actor id/e-mail, action, entity, old/new value, trusted client IP; called on logins,
  money actions, lifecycle changes, KYC, contact changes, team changes, refund/settlement/withdrawal transitions.
* [V] Deleting audit logs is refused and itself audited (`admin_routes.clear_audit_logs` l.1456-1460).
* Gaps: no index (Doc 1), no integrity protection (hash chain / WORM), readable by every admin role, admin UI shows only the last 500
  rows, several sensitive reads are not audited (reports export, user/KYC listings), audit write is in-request best effort.

## J. Error handling, monitoring, reliability

* [V] Unhandled exceptions ⇒ JSON 500 with `error_id`, traceback only in server log (server.py:191-206). HTTPException messages are
  user-oriented. Missing config ⇒ 503 naming variables (P3-8).
* [V] DB unreachable on Vercel ⇒ 503 after a 5 s ping, retried on the next request (l.149-163); non-Vercel startup retries init 60×5 s.
* **No monitoring/alerting/metrics/tracing** (P1-6). Logging is `logging.basicConfig` to stdout plus a few `print()` calls.
* No multi-document transactions; crash safety is achieved through intents + idempotent steps + reconcile sweeps (`financial_ops`,
  `stock`, `ledger.reconcile_ledger`, `finance_routes.reconcile_settlements`, `returns_routes.reconcile_returns`). Sound design, but it
  depends on P1-4 (indexes) and on the daily cron completing (P2-9). Wallet aggregate vs ledger reconciliation is offline-only
  (`wallet_reconcile.py`).
* Withdrawal request moves the wallet before writing its ledger row and request (wallet_routes l.174-191): a crash in between leaves
  money held with no request record [V], repairable only by manual reconciliation.

## K. Database access patterns (injection)

* [V] User text that reaches regexes is escaped (`pagination.text_filter` l.20-23, `admin_routes._sku_taken` l.215, admin product search
  l.226). Attribute filters are whitelisted (`discovery._attr_filters` l.25-36). Request bodies are Pydantic models with typed fields,
  so JSON operator objects cannot be injected into string filters; `Body(Any)` inputs (COD) are parsed by Pydantic models in
  `cod_rules`. Dynamic collection names come from server constants only (`admin_routes.REPORTS`, `governance_routes._check_related`).
* Performance-related patterns: date filters via `$regex "^YYYY-MM-DD"` on ISO strings (admin dashboard, leaderboard); unanchored
  regex in public suggest (P3-10).

## L. Dependencies (no network check performed)

| Area | Observation |
|---|---|
| Backend runtime (`pyproject.toml`, used by Vercel) | fastapi 0.110.1, starlette 0.37.2 (P2-10), pydantic 2.13.4, motor 3.3.1, pymongo 4.6.3, PyJWT 2.13.0, bcrypt 4.1.3, httpx 0.28.1, requests 2.34.2, razorpay 2.0.1, stripe 14.4.1, python-multipart 0.0.32 |
| Backend Emergent list (`requirements.txt`) | Includes many packages **not imported by the app** [V by grep]: python-jose 3.5.0 + ecdsa 0.19.2 ([S] ecdsa CVE-2024-23342, no upstream fix), passlib 1.7.4 (unmaintained), boto3, google-genai / google-generativeai, openai, litellm **installed from a custom URL wheel** (`customer-assets.emergentagent.com`), pandas, numpy, uvicorn 0.25.0, plus the private `emergentintegrations` — supply-chain and patching surface on that host |
| `deploy/vercel-api/requirements.txt` | omits `stripe`, while `shop_routes` falls back to `stripe_checkout` which imports `stripe` ⇒ import failure if that project were deployed (P3-11) |
| Frontend (`package.json`) | `react-scripts 5.0.1` (Create React App, deprecated/unmaintained; long `resolutions` list pins patched transitive deps — keep `npm audit` in CI); React 19.0.0 client only (not affected by RSC server advisories); axios 1.18.0; `html-to-image`, `qrcode` with caret ranges |

## M. Backups, environment separation, deployment

* Backups: none in repo (P1-6); rollback caveat on `money_version 3` orders (Batch 11 F).
* Environments [V]: `deploy/ENVIRONMENT.md` lets **Preview frontends point at the production API** ("otherwise the same production
  API"); no staging config exists in the repo. Test-only behaviour (SMS adapter, seed scripts) is guarded by the database name suffix
  `_test`, not by an explicit environment variable.
* `deploy/ENVIRONMENT.md` does not document variables the code reads: `CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET/UPLOAD_PRESET`,
  `TRUSTED_PROXY_HOPS`, `RATE_LIMIT_SCALE`, `SMS_TEST_ADAPTER`, `FRONTEND_PUBLIC_URL`, `VENDOR_TERMS_VERSION`,
  `COD_MAX_AMOUNT_RUPEES`, `STOCK_RECOVERY_MIN_AGE_SECONDS`; it says `vercel.json` sets "the daily cron" (there are two) and describes
  `CRON_SECRET` only for points release (it also gates `expire-pending-orders`).
* Index migration must run before traffic (P1-4); startup does not enforce it.

---

## N. Comparison with existing documents

| Document | Statement | Code reality |
|---|---|---|
| KNOWN_GAPS R-1..R-15 | R-1, R-2, R-3, R-4, R-5, R-6, R-9, R-10 | still accurate |
| KNOWN_GAPS | — | **Not listed:** P1-1 (order/COD stock lock), P1-2 admin MFA + localStorage token, P1-4 migration-dependent idempotency, P1-5 third-party identity, P2-1/P2-2 Stripe, P2-3/P2-4 admin breadth and PII export, P2-7 profile photo, P2-8 indexes/unbounded lists, P2-9 cron limits, P2-10 framework pins, P2-11 lockout/enumeration |
| PRODUCTION_READINESS_CHECKLIST | "Batches 12–13 are uncommitted" | Committed in `d31cb74` (with Batch 14). Production items (monitoring, CSP, backup drill) still open |
| ROLE_PERMISSION_MATRIX | support_admin "read + support"; admin "no money" | Broader in code — see Doc 2 §8 |
| BATCH11 audit | C-1, C-2, C-3, C-4, C-9, C-13, C-16 (when SMS on), C-17, C-18, L1, L6, L9 | **Fixed** in code (providers.otp_verify; core.client_ip; auth_routes.register l.290; admin_routes.refund_order; forgot_google l.482; review_withdrawal l.832; vendor_applications l.115-122; _guard_vendor_account; financial_approvals stale takeover; refund initiators; admin_login `not _inactive`; core._decode) |
| BATCH11 audit | C-5 | **Partly fixed**: vendor goods no longer payable on admin "delivered"; platform goods still are, by any admin role incl. support |
| BATCH11 audit | C-12, C-19, C-20, L4, L7, L8, L10, L11 | **Still open** |
| BATCH11 audit | C-6, C-7, C-8, C-10, C-11 (ledger maths) | not re-verified in this inspection |
| `payment_events.py` docstring | "Spec: docs/PAYMENT_RECONCILIATION_SPEC.md" | That file does **not exist** in `docs/` |
| `returns_routes.set_policy` message | "Only a super admin can change the returns policy" | `POLICY_ROLES` also admits `admin` |

## O. Recommended order of remediation (no code was changed)

1. P1-1: rate-limit `POST /api/orders` per user and IP, cap open COD orders/units per account, expire or require confirmation for
   stale COD orders, cap `items` length.
2. P1-2: TOTP/OTP for admin roles, shorter admin token lifetime, move tokens out of `localStorage` or add a strict CSP +
   `frame-ancestors 'none'` on the frontend host; account-level (not only IP-level) admin lockout/alerting.
3. P1-4 / P1-6: make the index migration a deploy gate (fail health check while unique money indexes are missing); add backups +
   restore drill; add error monitoring and cron-failure alerts.
4. P1-3: encrypt Aadhaar/PAN/bank fields (or stop storing full Aadhaar), define retention and anonymisation.
5. P1-5: verify Google ID tokens directly (Google OAuth) instead of a third-party demo endpoint.
6. P2 items: Stripe `payment_status == "paid"` only + amount/currency/provider checks; narrow support/accounts powers to the
   documented matrix; audit and restrict exports; second-person approval for bank changes and COD confirmation; missing indexes and
   pagination; framework upgrades; fix the profile-photo endpoint.

---
## Programme 01 status (2026-11-23) — findings above kept as found
| Item | Status |
|---|---|
| Stock lock via order creation; COD never expires (B-006, P1) | **Mitigated**: per-account and per-IP order rate limits, open-order cap, duplicate-submission claim; prepaid expiry covers every order with a grace for payments in progress. Unaccepted COD still never expires (owner decision P1-04). |
| Idempotency indexes not created by the app (B-004) | **Fail-closed guard** in code; production migration pending (P1-01). |
| Admin uploads 403 / any admin role could upload product images (B-009) | **Resolved**: content roles only, sniffed type, size limit, server-chosen paths, audited; merchandising accepts validated uploads only. |
| Reliability of repair jobs (B-005) | **Resolved**: keyset sweeps, checkpoints, isolation, time budget, recorded runs. |
| Admin password-only, plaintext KYC, Google via demo host, backups / monitoring, dependency currency | Unchanged — Programmes 02 and 05. |
| New observation | The frontend build does not flag undefined names: a Programme 01 change referenced a variable out of scope and only the browser check caught it (fixed). Supports R-14 / B-035 (automated UI tests, undefined-name checking). |
| New observation | The Operations page requests the finance approvals queue for non-finance admins (403 in the console; display only) — P1-08. |

## Programme 02 / W4 status (2026-11-24) — findings above kept as found
Full audit: `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md`.
- **P2-4 (PII exposure in reports / exports) — corrected for reports and exports.** Registrations report: mobile and e-mail masked in
  the screen and the CSV for every role; payments report: gateway session id masked; report CSV export follows the platform export rule
  (support_admin refused — interim, D-16 D16-W4-1); every report view and every export attempt is audited (`report_viewed`,
  `export_success` / `export_refused` / `export_failed`: user, role, report, export id, dates, redacted filters, rows, format).
  **Still open (owner decision D-16):** full contact in the legacy members / orders / refund-queue / registration lists for
  accounts_admin (D16-W4-3); support_admin read access to finance lists (D16-W4-2); actor e-mail / IP in the audit viewer (D16-W4-4).
- **G (sensitive data / uploads):** vendor identity-document links are listed to every admin role through
  `GET /api/admin/vendors/{id}/documents` — accounts_admin reads them although it may not review them or open onboarding. This is
  existing, tested behaviour, so it is **unchanged** and recorded as owner decision D-16 (D16-W4-6). Identity documents stay Cloudinary
  `authenticated` uploads and never appear in an export.
- **G (CSV formula escaping):** the two copies of the sanitiser are one rule (`exports.csv_cell`) applied to every cell of every
  export; leading spaces, line breaks and full-width formula characters are now covered; numbers and numeric text untouched.
- **I (audit logging):** "reports export … not audited" — corrected (all five exports and report views). Audit records remain
  insert-only (DELETE refused and audited; no edit route). Retention not set (P0-05).
- Exports never write files or links (in-memory, streamed in the authorised response, `Cache-Control: no-store`); larger-than-allowed
  exports are refused (413) instead of silently truncated; date ranges validated.

## Programme 02 / W7 and W1 status (2026-11-24) — findings above kept as found
- **H (frontend headers) — corrected:** `frontend/vercel.json` now sends a strict Content-Security-Policy (scripts only from the app and
  Razorpay checkout; no inline / eval), `frame-ancestors 'none'` + `X-Frame-Options: DENY` (clickjacking of the admin UI), `nosniff`,
  `Referrer-Policy`, `Permissions-Policy`; the build has no inline script. Verified by `src/securityHeaders.test.js` and a browser check
  under the same headers (38/38). HSTS on the frontend host stays the host default. Deployed host not yet observed.
- **P1-2 (admin MFA, localStorage token) — still open:** waits for P0-06 (factor, recovery, session lifetime) and D-10 (cookie scope).
- **UI vs backend (permission matrix §7):** no admin page now fires a request its viewer's role is refused (4 roles, 22 pages, 8 tabs); actions
  the server refuses are no longer offered (COD collect, merchandising editing, catalogue decisions). Server rules unchanged.

## Programme 03 status (2026-11-27) — findings above kept as found
Evidence: `HOME_GENIES_PROGRAMME_03_ENGINEERING_REPORT.md`. Local / isolated database only; uncommitted; not deployed.
- **F / P2-1 (Stripe status poll treated `complete` as paid) — corrected:** the poll checks only Stripe attempts that are not yet paid,
  and completes an order only when Stripe's own record (read server-to-server) says `payment_status == "paid"`, currency INR, amount ==
  the order's `total_paise`, and the session belongs to the attempt's order. The route stays public (the browser returns from Stripe
  without a session of ours) but can no longer cause anything Stripe has not confirmed; nothing is recorded until Stripe says paid.
  Whether to require a signed-in owner anyway is recorded as P03-OD-03.
- **F / P2-2 (Stripe webhook unverifiable on the Emergent path; no validation) — mitigated:** whatever the signature path, the
  webhook body's figures are never used; the same server-to-server check decides. Every delivery is recorded once in `webhook_events`
  (provider `stripe`, no gateway payload, no customer data) and shows in the finance payment-events inbox with retry.
- **Reliability (B-022):** a crash at any step of a withdrawal request is finished by a retry with the same key or by the repair sweep
  in the daily maintenance; no double reservation and no stranded reservation (tested at five crash points and under races).
- **Sensitive data (B-023):** settlement snapshots never copy the full account number (masked, last four); bank details in settlement
  lists are shown to finance roles only; no new key material (A-01 unresolved). Logs added in this programme name event ids, statuses
  and exception types only.
- **Logging:** the Stripe status poll's `print()` replaced by a structured log line without the exception text.
