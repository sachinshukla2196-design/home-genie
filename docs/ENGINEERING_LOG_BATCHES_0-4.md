# HOME GENIES — Engineering log: Batches 0–4

Baseline: `main` @ `5b7adc2ec060c4945ff813dbb8d328e5de9c812c`. All work below is **uncommitted** in the working tree.
Verification used only the isolated local test MongoDB (`hg-test-mongo`, 127.0.0.1:27018, throwaway `*_test` databases).
Nothing here has been verified in production. Defect IDs refer to `docs/HOME_GENIES_FULL_APPLICATION_MASTER_AUDIT.md`.

---

## Batch 0 — Critical security (SEC-01, SEC-02, SEC-03, SEC-04, SEC-06)

| Item | Problem | Solution | Alternatives considered |
|---|---|---|---|
| SEC-01 reset | Any admin could reset any account (including super admin) and saw the new password | Target-role guard (`admin_routes._guard_target`); the admin enters a **temporary** password + reason, it is never returned; `must_change_password` gate in `core.get_current_user`; when SMS is available, finishing the forced change also needs a code sent to the account's own mobile (`/auth/forced-change/send-otp`), so the admin can never complete the takeover | One-time reset link by SMS/email only — impossible while SMS/email are not confirmed in production; kept as the forced-change design with an SMS step when available |
| Reset → self-service takeover chain | A session opened with a temp password could change the mobile with an OTP to the new number only | `PUT /auth/change-mobile/send|verify` now needs codes from **both** the current (trusted) and the new mobile | Blocking mobile change for N hours after a reset — rejected (arbitrary, still bypassable) |
| Self-service recovery | Forgot-password only went to an admin queue | `POST /auth/forgot/otp/send` + `/auth/forgot/otp/reset` (code to the registered mobile, generic answers, not for admins / blocked / unactivated / deleted) | — |
| SEC-02 | Reports returned whole user documents (password hash, Aadhaar) | Explicit projections on report + CSV, CSV formula neutralisation, registration-requests Aadhaar masked | Response models per report — larger change, same effect |
| SEC-03 / H2 | Admin contact edits could point OTP/Google login at an attacker | `contact_change.py`: admin edits only **propose** a change; the live contact stays until the holder confirms with an OTP to the **current** mobile, or a different super admin approves a reviewed recovery with evidence | Requiring `mobile_verified` for login — rejected, would lock out every account created without OTP |
| SEC-04 / H1 / M4 | Unblock forced "active"; legacy deleted accounts could be revived | `pre_block_status` stored and restored; any deletion marker (`deleted_at`/`deleted_by`) refuses block/unblock at read **and** write time; legacy vendor owners restored to active only with activation evidence (`activated_at`, `invite_accepted_at`, `owner_activation=active`) | — |
| SEC-06 / M2 | Any admin edited verified KYC bank details; stale verify could overwrite an edit | KYC edit finance-only, resets to pending, masked audit; KYC records carry a `version`; verify is an atomic update on the version and status that were read | Maker-checker on KYC — **not implemented**: needs a second finance admin (now possible via OPS-01; owner to decide) |

## Batch 1 — Payment and order integrity

| Item | Solution |
|---|---|
| FIN-01 | UPI confirm and manual payment require `amount` equal to the order total (paise-exact) and a reference that can confirm **one** order only (`payment_references`, reference is the `_id`, normalised). **Roles unchanged** — decision gate 4 |
| FIN-02 | Vendors list/open/fulfil only verified orders (`VENDOR_VISIBLE_PAYMENT`); forward fulfilment steps also need `FULFILLABLE_PAYMENT`, checked at read and write time. Dashboard money aggregates keep the broader filter (`_orders_money_base`) so "awaiting confirmation" still shows as a total |
| FIN-06 | `_process_paid_order` records `paid_session_id`; any other captured payment for a paid/unpayable order is **not applied** and is recorded once in `orders.duplicate_payments` (`refund_due`) |
| FIN-07 | Order hard delete replaced by "remove": super_admin/admin only, only never-paid unclaimed online orders with no fulfilment; cancels through the stock path (restock intents) and archives; nothing is erased |
| FIN-08 | `PUT /admin/payments/upi-reject/{id}`: claim withdrawn (kept in `rejected_upi_claims`), order back to unpaid online so normal expiry releases stock. **Automatic claim expiry not implemented** (window is a policy decision) |
| FIN-14 | Razorpay events are claimed (`processing`), marked `processed` only after success, `failed` on exception (retry processes again), stale claims taken over; unique index spec `webhook_events_event_unique` |
| FIN-15 | Cancelling a paid / COD-due / claimed order: super_admin or admin only |

## Batch 2 — Admin foundations

| Item | Solution |
|---|---|
| ADM-01 | Settings screen now sends exactly the fields it shows and re-renders from the server response |
| AUD-01 | `DELETE /admin/audit-logs` always refuses (405) and records the attempt; UI control removed |
| SEC-17 | `env_credential_marker` (bcrypt of the environment credential) — the environment overrides the super admin password only when the environment value changes; marker never leaves the server |
| OPS-01 | `admin_team.py` (super admin only): list, create admin/accounts_admin/support_admin (temporary password + forced change + own-mobile OTP when SMS works), change role among those three; disable/enable via the guarded block endpoint. Never creates or changes a super_admin. Screen: `/admin/team` |

## Batch 3 — Catalogue and inventory

| Item | Solution |
|---|---|
| CAT-01 | Product page shows real variants (own SKU/price/stock, out-of-stock disabled); cart and checkout send `variant_sku` |
| CAT-02 | **Data only**: order lines snapshot `product_gst_percent` and `hsn_code`; admin products accept `hsn_code`. Totals still use the platform GST setting — decision gate 1 |
| CAT-03 | Admin edit never writes stock; `POST /admin/products/{id}/stock` (atomic, never below zero, journaled). Vendor variant edit is conditional on the stock values it read and rebuilds from a fresh read |
| CAT-04 | Shop list/detail/order creation exclude archived; vendors cannot list archived; approval does not list archived/taken-down |
| CAT-05 | Admin takedown of a vendor product is sticky (`admin_takedown`); lift: `POST /admin/products/{id}/takedown/lift` |
| CAT-06 / CAT-07 | Admin product validation (prices, GST 0–28, pillar categories, HSN format, image refs, options); SKUs upper-cased, unique case-insensitively across product and variant SKUs; `GET /admin/products` (paginated, searchable) |
| CAT-08 | Uploaded images are typed from their bytes (JPEG/PNG/WebP only) |
| SEC-23 | `/products?active=false` no longer exposes unlisted products; inactive/archived product detail is 404 |

## Batch 4 — Identity and authentication

| Item | Solution |
|---|---|
| SEC-05 | Google sign-up needs a server-signed 20-minute `google_signup_token` bound to the email (issued only after the server checked Google); sign-up requires a mobile code whenever SMS is available (`/auth/register-request/send-otp`, `sms_otp_available` in public settings); Google login links only to accounts whose email is already confirmed |
| SEC-09 | Per-IP limits on registration OTP and sign-up OTP; per-user limits on mobile-change and forced-change codes |
| SEC-10 | Admin lockout keyed by (client IP, username) |
| SEC-11 | Member password login and Google login refuse admin roles |
| SEC-12 | Tokens carry `jti`; logout stores it in `revoked_tokens` (TTL index) |
| SEC-13 | Covered by the Batch 0 change-mobile rule |
| SEC-16 | Suspending or revoking a staff membership suspends the staff login (every session refused); reactivation restores it. All sign-in paths refuse suspended/deleted accounts |

## Batch 5 — HomeGenie selling (partial)

| Item | Status | Solution |
|---|---|---|
| HG-01 attribution | Implemented; frontend not browser-verified | Share code captured at app start and on every navigation (survives login redirects); only `HG` + digits accepted; `/register?ref=` is a sponsor code and is never a seller code; cleared after the attributed order and on logout; "Share this product" button for GREEN HomeGenies (`/app/products/<id>?ref=<ID>`). Server rules (active GREEN seller, not the buyer) unchanged and tested |
| HG-02 KYC screens | Implemented; API contract tested | Member screen `/app/kyc` (submit, masked status, resubmission); admin screen `/admin/kyc` (pending/verified/rejected tabs, verify/reject with `expected_version`, finance-only correction) |
| HG-03 dashboard figures | Not started | — |
| Commission ledger/statement for members | Not started | — |
| Commission release timing | Blocked | Decision gate 2 |

---

## API contract changes (callers must be updated together)

| Endpoint | Change |
|---|---|
| `POST /api/admin/users/{id}/reset-password` | body `{temporary_password, reason}`; no password in response |
| `PUT /api/admin/users/{id}` | email/mobile changes return `contact_change` (pending) instead of applying |
| `PUT /api/auth/change-password` | optional `otp` (required for a forced change when SMS works) |
| `PUT /api/auth/change-mobile/verify` | new `current_otp` required |
| `PUT /api/admin/payments/upi-confirm/{id}`, `POST /api/admin/payments/manual` | `amount` required |
| `DELETE /api/admin/orders/{id}` | archives instead of deleting; stricter eligibility |
| `DELETE /api/admin/audit-logs` | always 405 |
| `PUT /api/admin/kyc/{id}` | optional `expected_version`; 409 on stale review |
| `PUT /api/admin/kyc/{id}/edit` | finance roles only |
| `POST /api/auth/login`, `POST /api/auth/google/session` | refuse admin roles; Google refuses unconfirmed-email accounts (409) |
| `POST /api/auth/register-request` | `google_signup_token` required with `google_verified`; `otp` required when SMS works |
| `GET /api/products` | `active` parameter removed (always shop-visible only) |

New endpoints: `/api/auth/forgot/otp/*`, `/api/auth/forced-change/send-otp`, `/api/auth/register-request/send-otp`,
`/api/auth/contact-change*`, `/api/admin/contact-changes*`, `/api/admin/team*`, `/api/admin/payments/upi-reject/{id}`,
`GET /api/admin/products`, `POST /api/admin/products/{id}/stock`, `POST /api/admin/products/{id}/takedown/lift`.

## Data changes (all additive and backward compatible)

New collections: `contact_change_requests`, `payment_references`, `revoked_tokens`.
New fields: users `must_change_password`, `pre_block_status`, `pending_contact_change`, `env_credential_marker`;
kyc_records `version`, `last_edited_by`; orders `paid_session_id`, `duplicate_payments`, `rejected_upi_claims`, `archived`;
products `admin_takedown`, `hsn_code`; order lines `product_gst_percent`, `hsn_code`; webhook_events `status`, `claimed_at`.
Old records without these fields are handled explicitly (tests cover legacy shapes). No data migration is required.

New index specs (`db_indexes.SPECS`): `webhook_events_event_unique` (partial unique), `revoked_tokens_expires` (TTL).
They are created only by the existing migration step (`python scripts/vendor_foundation_migrate.py --apply`), which still has
to be run against production by the operator. Rollback: drop the two indexes; all code paths work without them (the webhook
claim falls back to a find-then-insert, revoked tokens would simply never expire from the collection).

## Owner decisions still open (no code guesses were made)

1. GST-inclusive or exclusive prices (blocks per-product tax in totals and invoices).
2. Commission release event (payment + N days today; delivery + return window?).
3. Vendor settlement release event and return-window policy.
4. Which roles confirm UPI/manual payments, and whether a second person must approve.
5. Distinct customer role vs the existing RED distributor identity.
6. Whether final vendor approval stays super-admin only.
7. Any depth-based compensation (not activated).
Also: KYC maker-checker (now technically possible), automatic UPI-claim expiry window, and who may reset or edit
non-admin accounts (currently any admin role, with the safeguards above).
