# HOME GENIES — Programme 02 readiness (Security Hardening and Identity Protection)

Audit-only readiness review, 2026-11-24, working tree of `main` @ `d31cb74` (Programme 01 uncommitted). Facts below were read from the
code on that date. Nothing here is implemented; this is not an implementation prompt. Decision IDs refer to
`HOME_GENIES_OWNER_DECISION_REGISTER.md`. No retention period, credential, access right or legal policy is invented here.

## Entry gate (must hold before Programme 02 starts)
1. Programme 01 is committed on a reviewed branch (it is uncommitted today — 32 modified, 28 untracked files).
2. Owner decision **P1-01** answered and executed (verified backup, production index migration) **before** Programme 01 is deployed —
   Programme 02 builds on Programme 01 code and must not be deployed ahead of it.
3. Decisions needed per workstream (below) are recorded; workstreams whose decisions are missing start with the parts that need none.

## Protected rules
Programme 02 must not change: commission percentages / depth logic (S-7), attribution, no recruitment earnings, maker-checker (S-4),
refund / settlement authority, customer-vendor data isolation, the approved design. Items marked ⚠ below could touch one of them and
need the owner's explicit answer first.

---

## W1. Admin authentication and two-factor security (backlog B-010)
> **Status 2026-11-24: partly done** — criterion (d) (frontend CSP and frame protection) implemented and verified; (a)-(c) wait for
> owner decision P0-06 (factor, recovery, admin session lifetime). See "W1 outcome" below.
- **Existing:** separate admin sign-in `POST /api/auth/admin-login` (`AdminSecureLogin.js`); bcrypt passwords; per-account lockout and
  per-IP rate limit (`login_attempts`, `rate_limits`, `admin_login_ip` 20 / 10 min); JWT with `exp` 7 days, `jti` revocation on logout and
  password change (`core.py:85`, `revoked_tokens`); admin credential only from environment (`ADMIN_PASSWORD_HASH`); security headers on
  the API (`server.py`); frontend stores the token in `localStorage` (`AuthContext.js:12-32`). No second factor in application code
  (no TOTP / OTP step for admins).
- **Missing:** second factor for every admin role; shorter admin session lifetime and re-authentication for money actions; protection
  against distributed password guessing beyond IP + account keys; frontend Content-Security-Policy and frame protection
  (`frontend/vercel.json` has rewrites only).
- **Dependencies:** P0-06 (factor type, recovery), D-10 (trusted proxy for IP keys), SMS availability (K3) if SMS is chosen.
- **Risks:** locking out the only super admin (needs a documented recovery path); moving tokens out of `localStorage` into cookies is
  cross-site because frontend and API are separate Vercel projects (cookie scope is a hosting question); CSP can break third-party
  scripts (Razorpay checkout, Google fonts) if written too tight.
- **Decisions:** P0-06; D-10; D-11 (resets without SMS).
- **Acceptance criteria:** (a) every admin role must present a second factor before any `/api/admin/*` call succeeds — tests for each of
  the 4 roles, wrong / replayed / expired codes refused, rate-limited; (b) documented and tested recovery path that cannot be used by a
  single person to bypass 2FA; (c) admin tokens expire within the agreed lifetime and money actions require a fresh factor if so
  decided; (d) frontend responses carry CSP and `frame-ancestors`/X-Frame-Options, verified by an automated header check and a browser
  check that payment checkout still works; (e) no regression in the full suite.

### W1 outcome (2026-11-24) — criterion (d) only
- **Done:** `frontend/vercel.json` serves every page with a Content-Security-Policy (`default-src 'self'`; scripts only from the app and
  `https://checkout.razorpay.com`, no `unsafe-inline` / `unsafe-eval`; styles self + Google Fonts; fonts self + gstatic; images and API
  calls https (the API origin differs per environment; D-10); frames only Razorpay; `frame-ancestors 'none'`, `object-src 'none'`,
  `base-uri 'self'`, `form-action 'self'`, `upgrade-insecure-requests`) plus `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`,
  `Permissions-Policy`. The build emits no inline script (`INLINE_RUNTIME_CHUNK=false` in `npm run build`).
- **Verified:** automated header check `src/securityHeaders.test.js` (fails if the policy is weakened); browser under these exact headers
  (test proxy reads `vercel.json`; only `upgrade-insecure-requests` dropped for the plain-http local origin): 38/38 — public, customer,
  checkout and all 18 admin pages with no CSP violation at 1366 and 390 px; Razorpay checkout script allowed; any other script origin
  blocked; another page cannot frame the app (`frame-ancestors 'none'`); W7 checks 112/112 and the 4-role crawl (0 refused requests)
  repeated under the same headers. **Not verified:** the headers on the deployed Vercel host (no deployment).
- **Waiting for P0-06:** second factor for every admin role and its recovery path (a, b); admin session lifetime and fresh-factor rule for
  money actions (c). Distributed password guessing across many IPs is not addressed separately: a per-account lock regardless of IP would
  let anyone lock the real admin out (why SEC-10 keys lockout on IP + username); the second factor is the intended answer (P0-06).
  Tokens in `localStorage` stay until cookie scope is decided with hosting (D-10).
## W2. KYC and identity-document protection (B-007; L7, L8, L12)
> **Status 2026-11-24: designed, not built — blocked by A-01 (key custody).** Implementation and migration design (envelope
> encryption behind a key-provider interface, fail-closed writes, resumable migration with dry run, tests, decisions):
> `HOME_GENIES_W2_KYC_ENCRYPTION_DESIGN.md`. No key-management policy was assumed.
- **Existing:** KYC submission `POST /api/kyc` stores `pan`, `aadhaar`, `bank_account` in clear (`wallet_routes.py:113-122`); responses
  mask them (`_mask`, last 4); vendor bank / PAN masked in vendor views (`vendor_routes._public_vendor`); second-person KYC verification
  (S-8, last editor only); KYC submission open to any role (L8). Identity numbers also appear in `users`, `registration_requests`,
  `vendors`, `vendor_change_requests` (Programme 00 database audit). Account "deletion" is deactivation; data retained.
- **Missing:** encryption at rest for these fields, key management and rotation, a migration that encrypts existing records without
  data loss, role restriction of KYC submission to members, retention / anonymisation jobs, data-subject export / deletion.
- **Dependencies:** **A-01** (key custody), **P0-05** (retention, deletion meaning), D-06 (verifier rules); a verified backup before any
  data migration; W5 (indexes) if lookups move to hashed fields.
- **Risks:** irreversible data loss if a key is lost or a migration half-runs (needs a resumable, verifiable migration and a restore
  drill); duplicate-detection features that compare raw numbers must move to keyed hashes; finance screens that show full bank numbers
  for payouts need an audited reveal.
- **Decisions:** A-01, P0-05, D-06.
- **Acceptance criteria:** (a) no PAN / Aadhaar / bank account number is stored in clear in any collection — verified by a database scan
  on a migrated copy; (b) masked everywhere by default; full value only through an audited, role-restricted reveal; (c) migration is
  idempotent, resumable, verified by counts and round-trip decryption on a copy, with a written restore procedure; (d) KYC submission
  refused for roles the owner excludes; (e) retention / deletion behaviour implemented exactly as decided in P0-05 (none invented).

## W3. Google authentication and identity-provider replacement (B-011; A3, K7)
- **Existing:** browser redirect to `https://auth.emergentagent.com/?redirect=…` (`Login.js:45`, `Register.js:45`, `AuthExtras.js:137`);
  backend trusts `demobackend.emergentagent.com/auth/v1/env/oauth/session-data` to state the e-mail (`auth_routes.py:390`);
  `/api/auth/google/session`; Google recovery path; legacy `email_verified: true` accounts (R-5, L16).
- **Missing:** a first-party identity provider (own Google OAuth client with ID-token verification) or removal of Google sign-in;
  handling of accounts whose e-mail was never proven.
- **Dependencies:** **P0-07** and the resulting OAuth client credentials (owner-provided, never in the repo); redirect URIs per
  environment (staging and production).
- **Risks:** locking out members who only use Google; account takeover if an unverified legacy e-mail is linked automatically.
- **Decisions:** P0-07; R-5 handling (re-verification policy).
- **Acceptance criteria:** (a) no request to any `emergentagent.com` host in the sign-in path (code search + browser network log);
  (b) ID tokens verified locally (issuer, audience, expiry, signature) — tests with forged / expired / wrong-audience tokens; (c) a
  Google identity links only to an account whose e-mail was proven; (d) existing users can still sign in or recover by the documented
  path.

## W4. Reports, exports and sensitive-data masking (B-019; D37, L9, M2)
> **Status 2026-11-24: reports and exports secured** (W4 package; uncommitted). Criteria (a)-(e) met for every report and export;
> the role questions that need the owner are recorded under D-16 (D16-W4-1…5). See "W4 outcome" below and
> `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md`. The text below is the original assessment.
- **Existing:** 8 legacy reports `GET /api/admin/reports/{r}` and `/export` open to **any** admin role (`admin_routes.py:1484-1499`,
  `require_admin`), registrations export includes e-mail and mobile, export not audited, float money columns, 2,000 / 5,000 row caps;
  the newer order export is masked, audited and role-restricted (`admin_order_ops.py`, M3) — the pattern to follow; admin users list
  returns full documents minus hash (L9).
- **Missing:** role restriction per report, masking of personal fields by default, audit entry per export, paise money, date ranges,
  paging instead of silent caps.
- **Dependencies:** D-16 (roles), P0-05 (what may be exported at all).
- **Risks:** finance depends on today's exports — changes must keep needed columns (masked) and be announced.
- **Decisions:** D-16 (which role sees which report).
- **Acceptance criteria:** (a) every export writes an audit entry (who, which report, filters, row count); (b) support_admin cannot
  export personal contact data unless the owner decides otherwise — tested per role; (c) money columns from integer paise; (d) no
  silent truncation: paged or bounded with an explicit "more rows" indicator; (e) existing finance reports still produce the same
  totals on test data.

### W4 outcome (2026-11-24)
- **(a) Every export audited** — legacy report CSV, order CSV, vendor statement, vendor current report, vendor catalogue: one record per
  attempt (success / refused / failed) with user, role, report, export id (also the `X-Export-Id` header), dates, redacted filters,
  rows, format, scope; report views audited too.
- **(b) support_admin cannot export personal contact data** — report CSVs follow `EXPORT_ROLES` (support refused; interim D16-W4-1) and
  the bulk reports mask mobile / e-mail / payment session id for every role, screen and CSV alike. Tested per role.
- **(c) Money from integer paise** — report money columns are printed from `*_paise` (legacy documents through `paise_of`), exact
  two-decimal strings, same column names.
- **(d) No silent truncation** — the report screen declares `total` / `truncated`; exports beyond their limit (reports and orders
  5,000, statement 20,000, catalogue 5,000) are refused with a message to narrow the dates (413); dates validated.
- **(e) Finance reports unchanged** — report totals equal the stored paise totals (tested); finance diagnostics, vendor statement,
  commission statement, order history and dashboard regression-tested.
- **Also:** one formula-injection rule for every exported cell; exports `no-store`, no files or links ever created; Reports screen: Export only for export roles, errors shown as
  errors, date filters; CSV downloads show the server's refusal message.
- **Regression:** `test_w4_export_security` 63 passed; full regression 74 suites / 1,585 passed / 0 failed / 0 skipped; live 96 passed / 6 skipped; frontend quality exit 0; browser 50/50 at 1366 and 390 px. Details: engineering log, Programme 02 / W4.
- **Not done (owner decisions):** D16-W4-2 (support reads finance lists), D16-W4-3 (accounts sees full contact in legacy lists),
  D16-W4-4 (audit-viewer e-mail / IP), D16-W4-5 (report rights for future roles), D16-W4-6 (accounts_admin reading vendor identity-document
  links — existing, tested access; unchanged). VG-01 stays open.
## W5. Database index and data-integrity audit (B-025; DB audit)
> **Status 2026-11-24: index, integrity and repair audit DONE** (W5 package; uncommitted; the indexes exist in the specification and
> the test databases only — production needs the P1-01 migration). Criteria (a) and (b) met; (c) holds (no TTL created, nothing
> deleted). See "W5 outcome" below and `HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md`. The text below is the original assessment.
- **Existing:** `db_indexes.SPECS` (incl. Programme 01 additions), migration-only creation, `money_guard` exact checks for 8 money
  indexes, duplicate report by record id.
- **Missing (Programme 00 database audit):** indexes on `orders.user_id` (standalone), `files.storage_path`, `audit_logs` (none),
  `payment_transactions.order_id`, `commissions.order_id/status`, `refund_cases`/`return_cases` `id`/`order_id`,
  `password_reset_tokens.token_hash`; uniqueness where needed (`kyc_records.user_id`, `cron_runs.run_id`, `counters.id`); TTL on
  `otp_sessions`, `login_attempts`, `password_reset_tokens`. ~~Residual capped repair loops: stock-journal recovery (`run_recovery` 20 per run)
  and the stuck-expiry self-heal~~ — corrected 2026-11-24 by the DEF-03 package (no longer in scope here).
- **Dependencies:** verified backup; duplicate resolution before any new unique index (finance decisions per record); W2 if hashed
  lookup fields are introduced.
- **Risks:** unique index builds fail on existing duplicates (handled by the existing refuse-and-report mechanism); TTL indexes delete
  data — retention for those collections must match P0-05.
- **Decisions:** P0-05 (TTL periods for security collections).
- **Acceptance criteria:** (a) every query on a hot path listed above uses an index (explain-plan tests as in `test_discovery_merch_b13`);
  (b) migration dry run lists all changes and duplicates; apply is repeatable; (c) no document deleted except by an agreed TTL.

### W5 outcome (2026-11-24)
- **(a) Hot paths use an index** — every path listed above plus the ones found by a static analysis of all 1,042 database call sites:
  40 indexes added to `db_indexes.SPECS` (37 query indexes — 8 of them for repair sweeps that run inside requests — and 3 integrity
  constraints); 34 hot queries asserted `IXSCAN` / no `COLLSCAN`
  (`test_w5_index_integrity`). Found on the way: **every member login scanned the whole `users` collection** (the e-mail `$or` branch
  could not use the partial unique index) — fixed with a plain lookup index beside it. `orders.user_id` is served by
  `orders_user_payment_status` (P01); `kyc_records.user_id` is now unique; `otp_sessions` / `login_attempts` / `password_reset_tokens`
  TTLs are NOT created (P0-05, and their time fields are strings, which TTL cannot expire).
- **(b) Dry run lists all changes and duplicates; apply repeatable** — `db_indexes.dry_run()` (creates / refusals with duplicate counts /
  legacy replacements / conflicts), `spec_version()`, `index_migrations` run records with interrupted-run detection; duplicate counting
  corrected for multikey and missing-vs-null keys; `plan()` now agrees with the money guard on renamed indexes; collation and text
  language are part of an index definition.
- **(c) Nothing deleted** — no TTL created or changed; duplicates are reported, never removed; retention is a read-only report.
- **Races fixed (proven by tests first):** double KYC submission (3 records → 1), first use of a sequence (same number issued 3 times →
  unique counter), repeated cron delivery (6 run records → 1).
- **Repair jobs:** `prune_stock_markers` (200 per day, could stop entirely) is now a complete resumable sweep; the sweep runner tracks
  every open failure (was capped at 1,000). All 17 sweeps inventoried; no fixed per-run ceiling remains. Six sweeps run inside
  requests and, with nothing to repair, examined every order / journal row each time (~210,000 documents per checkout at 30,000
  orders, measured) — now 0-2 index keys (selections unchanged).
- **Regression:** `test_w5_index_integrity` 58 passed (11 defect tests failed on the unchanged code first; request-time sweep scans measured); full regression 73 suites / 1,522 passed / 0 failed / 0 skipped; live suites 96 passed / 6 skipped; pyflakes 0 new. Details: engineering log, Programme 02 / W5.
- **Not done (recorded):** production migration (owner, P1-01, now including the W5 indexes); retention periods (P0-05); capped
  dashboard / report figures (W4 / P05); stale `processing` webhook claims (P03). Residual items W5-R1…W5-R6.
## W6. Backend dependency and security upgrades (B-032)
> **Status 2026-11-24: dependency audit and controlled upgrades DONE** (W6 package; uncommitted, not deployed). Criteria (a), (b) and (c)
> met — see "W6 outcome" at the end of this section and `HOME_GENIES_DEPENDENCY_AUDIT_W6.md`. The text below is the original readiness
> assessment.
- **Existing:** FastAPI 0.110.1, Starlette 0.37.2, Pydantic 2.13.4, PyJWT 2.13.0, Motor 3.3.1 / PyMongo 4.6.3, requests 2.34.2, razorpay
  2.0.1, stripe 14.4.1, twilio 9.11.2 (`backend/requirements.txt`); React 19.0.0, react-scripts 5.0.1, CRACO 7.1.0, axios 1.18.0
  (`frontend/package.json`). Unused packages in `requirements.txt` (openai, litellm, google-genai — integration register #19).
  **No `pip-audit` / `npm audit` has been run** in Programme 00 or 01 or this audit (advisories are suspected, not verified).
- **Missing:** an audited vulnerability report, controlled upgrades, removal of unused packages, a repeatable audit step.
- **Dependencies:** none on decisions; must run before W1 / W3 so new security code is written against the upgraded framework.
- **Risks:** Starlette / FastAPI upgrades change behaviour (middleware, TestClient); requires the full suite plus live suites.
- **Decisions:** none.
- **Acceptance criteria:** (a) `pip-audit` and `npm audit` reports recorded before and after; (b) no known high / critical advisory left
  without a written reason; (c) full in-process regression, live suites and frontend build green after the upgrade.

### W6 outcome (2026-11-24)
- **(a) Audits before and after** — `pip-audit` 2.10.1 (PyPI and OSV) and `npm audit`: production backend set 4 vulnerable packages
  (1 critical, 14 high; starlette, PyJWT, pymongo, dnspython) → **0**; Emergent `requirements.txt` 15 → 5; frontend 38 findings
  (22 high) → 26 (13 high, 4 moderate, 9 low). Register and evidence: `HOME_GENIES_DEPENDENCY_AUDIT_W6.md`.
- **(b) No high / critical left without a written reason** — remaining: CRA 5 toolchain (build / dev-server / test only; none in the
  browser bundle; fix = replace CRA, decision W6-01); pillow, python-jose, ecdsa, filelock, oauthlib (Emergent-only, not imported; major
  or no fix; D-10). Residual items W6-R1…W6-R8 in the remaining-work register §8.
- **Upgrades:** fastapi 0.110.1 → 0.133.1, starlette 0.37.2 → 1.3.1, PyJWT 2.13.0 → 2.15.0, pymongo 4.6.3 → 4.18.3, motor 3.3.1 → 3.7.1,
  dnspython 2.8.0 → 2.9.2 (pyproject, deploy copy, requirements.txt); Emergent-only patches certifi, urllib3, aiohttp, multidict, yarl,
  pyasn1, black; axios 1.18.0 → 1.20.0, react-router-dom 7.15.0 → 7.18.2, postcss 8.5.10 → 8.5.23, underscore override 1.13.8, in-range
  transitive patches; zod, @eslint/js, globals removed; top-level eslint 9.23.0 → 8.57.1 (it is loaded by `eslint-plugin-import`, so it is
  aligned with the engine react-scripts runs rather than removed — W8 configuration unchanged, guard and lint output identical).
- **Compatibility:** one shim — `core.py` validates `mongodb+srv` URLs with `pymongo.uri_parser.parse_uri` at import because PyMongo 4.18
  resolves SRV lazily (the existing 503 diagnostic is preserved; test unchanged). `on_event` startup hooks run under Starlette 1.x via
  FastAPI 0.133.1; Starlette's 1 MB multipart limit applies to non-file fields only (uploads keep the app's 5 MB cap).
- **(c) Regression:** full in-process regression 72 suites / 1,464 passed / 0 failed / 0 skipped; live suites 96 passed / 6 skipped (unchanged); frontend `npm run quality` exit 0 (lint 0 errors / 9 warnings, tests 7/7, guards 13/13, build); W8 fixtures still fail the real build; browser 64/64 at 1366 and 390 px; pyflakes 0 new. Details: engineering log, Programme 02 / W6.
- **Not done (recorded):** CRA replacement (W6-01), Emergent clean-up (D-10), package-manager declaration (W6-R3), CI audit step
  (W6-R8). VG-01 (repository browser smoke suite) stays open. No production install or deployment.
## W7. Operations Approvals permissions and 403 correction (B-039; P1-08)
> **Status 2026-11-24: engineering DONE (Programme 02 cycle); P1-08 stays open** — no admin page fires a request its viewer's role is
> refused, for any of the 4 roles; the current "explain" presentation is kept until the owner decides P1-08. See "W7 outcome" below.
- **Existing:** `AdminOperations.js:66` loads `/api/admin/finance/approvals?status=pending` for every admin; the endpoint is finance-only
  (`financial_approvals.FINANCE_ROLES` = super_admin, accounts_admin) → 403 in the console for `admin` / `support_admin` (display only;
  server refuses correctly). Nav and tabs are not role-aware beyond the menu (D44).
- **Missing:** role-aware Operations tabs; generally, actions hidden for roles that cannot perform them.
- **Dependencies:** P1-08 (hide vs explain); D-16 if new roles arrive.
- **Risks:** hiding must not become the control — the server guard stays the authority.
- **Decisions:** P1-08.
- **Acceptance criteria:** (a) no 403 request is made by the Operations page for any of the 4 roles (browser network check at 1366 and
  390 px); (b) server guards unchanged (existing permission tests still pass); (c) approved design unchanged.

### W7 outcome (2026-11-24)
- **Found (browser crawl of 22 admin pages + 8 Operations tabs as each admin role):** refused requests (403) on page load — admin 6,
  accounts_admin 3, support_admin 7, super_admin 0: Operations approvals and duplicate payments (requested before the role check),
  Advancement benefits (screen promised a read-only view the server refuses), payment events, activations, vendor applications and
  team (hidden in the menu but refused when opened by address). Plus buttons the server refuses: COD "Cash collected" (accounts,
  support), merchandising editing (accounts, support), catalogue decisions and "Add for a vendor" (accounts, support).
- **Done (frontend only; no server rule changed):** `lib/roles.js` — one copy of the server's role sets, each naming its backend source
  and kept in step by `test_w7_role_sets_in_sync` (backend); `components/RoleGate.js` — renders a page only for allowed roles, otherwise a
  short note and the page is not mounted (no request); applied to payment events, activations, vendor applications, benefits, team and
  catalogue "Add for a vendor"; Operations approvals / duplicates make no request for non-finance roles (existing "Finance
  administrators only" note kept); COD collect, merchandising editing and catalogue decisions shown only to the roles the server allows.
- **(a)** crawl after the change: **0 refused requests and 0 page errors for all 4 roles**; role-by-role browser checks 112/112 at 1366 and
  390 px. **(b)** server unchanged (backend files identical to the last full regression). **(c)** design unchanged (screenshots reviewed).
- **Open:** P1-08 (keep the explanatory notes, or hide the entries); admin product studio still opens for accounts / support (saving is
  refused by the server); Settings money fields stay editable on screen for non-finance roles (the server refuses a change with a clear
  message).
## W8. Frontend static checks and build protection (B-040, B-035, R-14; N9, N10)
> **Status 2026-11-24: static analysis and build protection IMPLEMENTED AND VERIFIED** (W8 package). Criteria (a) and (b) met; criterion
> (c) — a repository-tracked browser smoke suite — is **not** met (the browser checks ran from scratch scripts) and moves to VG-01 / P05.
> Rules, scripts and evidence: "W8 outcome" at the end of this section. The text below is the original readiness assessment.
- **Existing:** CRACO ESLint config extends only `plugin:react-hooks/recommended` (`frontend/craco.config.js:75-81`); the build therefore
  compiles undefined identifiers (Batch 13 dashboard crash; Programme 01 product-studio step crash, both caught only by browser checks);
  2 frontend unit-test files; browser checks live outside the repository (scratch scripts).
- **Missing:** `no-undef` / `no-unused-vars` (at least undefined-name detection) failing the build; a repository-tracked browser smoke
  suite for the critical screens; CI-style command that runs lint + unit tests + build.
- **Dependencies:** none; should land first so every later Programme 02 change is protected.
- **Risks:** turning rules on may surface existing warnings — fix them without restyling; keep the approved design.
- **Decisions:** none.
- **Acceptance criteria:** (a) a deliberately introduced undefined name fails the build (tested); (b) current code builds clean with the
  new rules; (c) a repository-tracked smoke suite covers at least: login, product studio steps, checkout, admin operations, merchandising
  upload, vendor profile — at 1366 and 390 px.
- **W8 outcome (2026-11-24).**
  - *Root cause:* CRA 5 lints the build with `eslint-config-react-app/base` only (parser + environments, no correctness rules) and expects
    the project to extend `react-app`; the project never did, and `craco.config.js` merged only the react-hooks rules — so `no-undef`,
    `react/jsx-no-undef` and every import check were off. The top-level ESLint 9 package needs a flat config and was never used.
  - *Configuration:* `frontend/.eslintrc.js` (single source; `extends: react-app`, `env.es2020`); `craco.config.js` `eslint.mode = "file"`.
    **Errors** (fail the build): `no-undef`, `react/jsx-no-undef` (no globals), `import/no-unresolved` (incl. the `@/` alias and
    exports-only packages via `scripts/eslint-alias-resolver.js`), `import/named`, `import/default`, `react-hooks/rules-of-hooks`,
    `react/jsx-no-duplicate-props`, `no-dupe-keys`, `no-dupe-class-members`, `no-redeclare`, `no-const-assign`, `no-func-assign`,
    `no-import-assign`, `no-unreachable`, plus react-app's `no-restricted-globals` and `import/first`. **Warnings:** `no-unused-vars`
    (args none, ignore rest siblings), `react-hooks/exhaustive-deps`, `import/no-duplicates`, `import/no-cycle` (depth 4), `react/jsx-key`
    and the rest of react-app.
  - *Scripts:* `npm run lint` (`scripts/lint.js`, same ESLint 8.57.1 engine as the build, all of src/), `npm run test:ci`,
    `npm run build:check` (`scripts/check-build-guard.js`, 13 in-memory guard fixtures), `npm run quality` (lint → tests → guards → build).
    `npm run build` itself fails on any ESLint error (CRA `failOnError` in production).
  - *Evidence:* guards 13/13; real production builds of a scratch copy FAILED on an injected undefined name (`no-undef`), unresolved import
    and invalid named import, and passed without them; `npm run lint` 0 errors / 9 warnings over 172 files; `npm run quality` exit 0;
    frontend tests 7/7; browser check 72/72 + Documents input (2/2) at 1366 / 390 px.
  - *Fixed while enabling the rules:* 6 dead duplicate i18n keys in `i18n/vendorPanel.js` (earlier copies removed; all 1,232 effective
    strings proven identical); 8 unused named imports in 6 files (bundle module set and every other module source proven identical).
  - *No exceptions* (no disabled rules, no ignored files or directories). The 9 remaining warnings are listed in the remaining-work register.

---

## Recommended execution order
| Order | Workstream | Why first / after | Can start without decisions? |
|---|---|---|---|
| 1 | W8 frontend static checks | protects every later change; two runtime crashes already slipped past the build | yes |
| 2 | W6 dependency audit and upgrades — **done 2026-11-24** | new security code must target the upgraded framework | yes |
| 3 | W7 Approvals 403 — **engineering done 2026-11-24 (P1-08 open)** | small, isolated, visible | needs P1-08 (either answer removes the 403) |
| 4 | W5 index and integrity audit — **done 2026-11-24** | performance and integrity base for W2 / W4; includes residual stock-recovery caps | yes, except TTL periods (P0-05) |
| 5 | W4 reports and exports — **done 2026-11-24** | removes the widest personal-data exposure | role split needs D-16; audit + masking can start |
| 6 | W1 admin 2FA and CSP — **CSP / frame protection done 2026-11-24; 2FA waits for P0-06** | CSP and session hardening can start; the factor needs P0-06 | partly |
| 7 | W2 KYC encryption | highest data-migration risk; needs backup drill, A-01, P0-05 | no (design only) |
| 8 | W3 identity provider | needs P0-07 and owner-supplied OAuth credentials | no |

## Programme 02 completion gate
Programme 02 is complete only when every workstream's acceptance criteria are met **or** the unmet part is explicitly recorded as
blocked by a named decision; full in-process regression, live suites, frontend build / lint / unit tests and the browser smoke suite are
green; no protected rule changed; documentation updated; nothing deployed to production without the owner.
