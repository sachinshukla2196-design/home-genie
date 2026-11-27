# HOME GENIES — Remaining work register (pre-Programme 02; updated through Programme 03 first package, 2026-11-27)

Reconciled 2026-11-24 against the working tree of `main` @ `d31cb74` (Programme 01 uncommitted). One place for everything still
outstanding: capabilities (generated from `HOME_GENIES_CURRENT_MODULE_COMPLETION_MATRIX.md` so the two cannot disagree), defects,
verification gaps, integrations, duplicated implementation, documentation contradictions and the status of every backlog item.
Decision IDs: `HOME_GENIES_OWNER_DECISION_REGISTER.md`. Sequence and gates: `HOME_GENIES_MASTER_ROADMAP_CURRENT.md`.

## 1. Defects (code behaves wrongly today)
| ID | Defect | Evidence (2026-11-24, read-only) | Priority | Programme |
|---|---|---|---|---|
| DEF-01 | ~~Operations page requests the finance approvals queue for non-finance admins → 403 on every visit~~ **CORRECTED 2026-11-24 (W7)** — no admin page fires a refused request for any role; see §8 | `AdminOperations.js:66` vs `financial_approvals.FINANCE_ROLES`; seen in the Programme 01 browser check | P2 | P02 (W7) |
| DEF-02 | ~~Frontend build does not fail on undefined identifiers; two runtime crashes reached the browser (Batch 13 dashboard, Programme 01 studio step — fixed)~~ **CORRECTED 2026-11-24 (W8)** — see §8 | `frontend/craco.config.js:75-81` (hooks rules only) | P2 | P02 (W8) |
| DEF-03 | ~~Stock-journal crash recovery handles at most 20 interrupted transactions per run; stuck-expiry self-heal also capped (`limit`)~~ **CORRECTED 2026-11-24** — see §8 | `stock.py:641` `run_recovery(limit=20)` via the expiry sweep; `stock.py:516-523` (as found) | P2 | done (DEF-03 package) |
| DEF-04 | Open refund cases can promise more than is still refundable (now refused at confirmation and reported as `over_promised`) | B-021; `test_programme01_cross_module` scenario 6 | P2 | P03 |
| DEF-05 | ~~Stripe completion path: no amount / currency check, events not recorded in `webhook_events`, unauthenticated status poll triggers processing~~ **CORRECTED 2026-11-27 (Programme 03)** — see §8 | `shop_routes.py` `/payments/status`, `/webhook/stripe` | P1 | P03 |
| DEF-06 | Default "Place order" uses Stripe; unconfigured → 503 after the order is created (stock held until the 15-min expiry) | `Checkout.js`, `shop_routes.py` `_stripe` | P1 | P03 (P0-01) |
| DEF-07 | Customer "Pay now" on a pending order opens an empty checkout | Programme 00 workflow audit (B-029) — not re-verified in the browser | P2 | P04 |
| DEF-08 | ~~Legacy reports export personal contact data to every admin role, unaudited; float money; silent row caps~~ **CORRECTED 2026-11-24 (W4)** — masked, audited, export roles, paise money, refused instead of cut; see §8 | `admin_routes.py` reports | — | — |
| DEF-09 | Referral page labels a sponsor-registration link "Shop with me" | `Referral.js` (MS §1) | P2 | P08 (B-034) |
| DEF-10 | Admin server upload on a plain-http local server returns `http://` URLs that the image validator refuses (local only) | Programme 01 browser check (B-041) | P3 | P05 |
| DEF-11 | Privacy page promises deletion; code only deactivates. Refund policy promises refunds to the original method; no provider refund exists | `Legal.js`, `admin_routes.py:1237`, `returns_routes.verify_provider_refund` | P1 | P02 (P0-05) / P03 / legal |

## 2. Verification gaps (implemented but not proven)
| ID | Gap | Today's evidence | Needed | Programme |
|---|---|---|---|---|
| VG-01 | No repository UI tests; browser checks run from scratch scripts outside the repo (still true after W8; W8 added static guards, not browser tests) | 2 frontend unit-test files; P01 browser check (72 checks) not in the repo | repository-tracked smoke suite | P02 (W8) / P05 |
| VG-02 | Razorpay client order + verify routes have no tests; live gateway never exercised | no test references `/payments/razorpay/order|verify` | staging run with test keys (R-15) | P03 / P05 |
| VG-03 | Stripe webhook ~~untested~~ tested against a fake Stripe (`test_p03_stripe_integrity`, 2026-11-27); never exercised against Stripe itself; card tests skipped on test servers | 2 live skips | sandbox run with test keys after P0-01 | P03 |
| VG-04 | Vendor profile overview endpoint untested | no test references `profile-overview` | API test | P06 |
| VG-05 | Admin uploads verified only with an in-memory object store | `test_programme01_admin_media` stand-in | staging check with real Cloudinary / Emergent storage | P05 |
| VG-06 | `scripts/programme01_reconcile.py` smoke-run on an empty database only | P01 log | run against a production copy before go-live | P05 |
| VG-07 | Production index state and production behaviour never verified | all programmes | P1-01, staging, monitoring | Owner + P05 |
| VG-08 | ~~Dependency advisories suspected but never audited (`pip-audit` / `npm audit` not run)~~ **CLOSED 2026-11-24 (W6)** — audited and upgraded; see §8 | B-032; `HOME_GENIES_DEPENDENCY_AUDIT_W6.md` | residual items W6-R1…W6-R8 (§8) | — |
| VG-09 | Programme 01 test results are historical (2026-11-23); not re-run for this audit by instruction | engineering log | re-run at the start of Programme 02 | P02 entry |
| VG-10 | HTTP cron routes (`/api/cron/release-points`) not exercised by tests; cron runs not surfaced | G2, N3 | endpoint test + monitoring screen | P05 |
| VG-11 | Profile update / photo upload untested; leaderboard, referral codes, admin dashboard covered only by live suites | A28, B10, D6, D2 | in-process tests | P05 |

## 3. Integrations still required (see `HOME_GENIES_INTEGRATION_REGISTER.md`)
| Integration | State | Blocks | Programme |
|---|---|---|---|
| Razorpay live / staging keys | code integrated; never exercised against the gateway | online payment launch | P03 |
| Stripe | integrated, unconfigured, unreconciled | depends on P0-01 | P03 |
| Provider refunds | stub (`verify_provider_refund` returns False) | refund to original method (legal text) | P03 |
| Bank payouts | manual references only | automated settlement / withdrawal payment | P03 |
| Twilio SMS (DLT) | integrated; test adapter in tests | OTP flows, transactional SMS | P04 |
| Transactional e-mail | one caller (owner invitations) | order / refund messages | P04 |
| Emergent object storage / Cloudinary | integrated; Cloudinary env not documented before P01 | uploads in production | P05 verification |
| First-party Google OAuth | not integrated (Emergent demo broker) | P0-07 | P02 (W3) |
| Error monitoring / alerting / uptime | none | operations | P05 |
| Backups / restore tooling | none in repo | disaster recovery | P05 (P0-09) |
| Courier / logistics | none | delivery proof, tracking | P06 (D-04) |
| GST e-invoicing / TCS | none | statutory invoicing | P07 (L-02) |
| WhatsApp Business Platform, Meta Graph API | none | Marketing Studio phase 3 | P08 |
| LLM for captions | none (unused packages present) | OD-M4 | P08 phase 2 |

## 4. Duplicated or superseded implementation
| Item | Evidence | Action | Programme |
|---|---|---|---|
| Legacy vendor product create / update routes beside the product studio | C14, H7 (`vendor_routes.py` POST/PUT `/vendor/products`) | retire or align with PIM | P06 |
| Duplicate vendor screens / routes (`/vendor/finance`≡`/earnings`, `/dispatch`+`/returns`≡`/shipping`, owner-invitation vs owner-access, decision vs final-review) | C34 | consolidate | P06 |
| Old unpaged admin order list and page | D18 | merge into order operations | P05 |
| Legacy registration-request queue (startup auto-activates) | D5 | retire | P05 |
| Legacy public sign-up endpoint | L15 | retire | P02 |
| Stale backend copy `deploy/vercel-api/` (git-ignored) | N2 | delete locally / never deploy from it | P05 |
| Two admin product-image upload routes (`/admin/uploads/product-image`, `/admin/uploads/image?kind=product`) | Programme 01 (B-009) kept the old route for `AdminProducts.js` | converge on one route | P05 |
| `payment_events.complete_paid_order` thin wrapper over `order_completion.complete_paid_order` | Programme 01 (B-003) | keep or inline (naming duplication only) | P05 |
| Two storage back-ends for images (Cloudinary for direct uploads, Emergent storage for server uploads) | H11 | choose one per environment (decision with P0-09) | P05 |
| Old and new completion matrices / decision registers / roadmaps | `MARKETPLACE_MODULE_COMPLETION_MATRIX.md`, `HOME_GENIES_MODULE_COMPLETION_MATRIX.md`, `OWNER_DECISION_REGISTER.md`, `HOME_GENIES_AUTONOMOUS_ROADMAP.md` | historical; superseded by the `*_CURRENT_*` / consolidated documents (pointers added) | — |

## 5. Documentation contradictions found in this reconciliation
| Document | Claim | Reality (2026-11-24) |
|---|---|---|
| Programme 01 final report / engineering log | "every repair and release job processes the full dataset" | money jobs yes; stock-journal recovery and stuck-expiry self-heal remained capped (DEF-03) — corrected 2026-11-24 (§8) |
| `HOME_GENIES_MODULE_COMPLETION_MATRIX.md` Programme 01 appendix | Operations queue status display "1" (verified) | browser check only, no repository test → "Implemented, verification incomplete" (D45) |
| same appendix | admin image upload "1" | verified with an in-memory store only → "Implemented, verification incomplete" (D30) |
| `HOME_GENIES_MASTER_IMPLEMENTATION_BACKLOG.md` | Marketing Studio summarised as an MVP of links / share buttons / templates / posters / tracking | full 17-module scope (M1–M17) plus link previews, public product pages and compliance guard-rails is retained (matrix module P) |
| Programme 00 matrix | 266 rows, no Marketing Studio rows | module P added (20 rows) |
| `OWNER_DECISION_REGISTER.md` | decisions named in the Programme 00 backlog (gateway, two-person scope, retention, 2FA, IdP, …) had no IDs | given P0-01 … P0-09 in the consolidated register |
| `PROGRAMME_01_TECHNICAL_SPECIFICATIONS.md` §5 | lists converted jobs | accurate; does not mention the remaining stock-recovery caps (DEF-03) |

## 6. Backlog cross-reference (Programme 00 B-items and Programme 01 additions)
| Item | Status 2026-11-24 | Programme |
|---|---|---|
| B-001, B-002, B-003, B-005, B-006, B-008, B-009 | done in Programme 01 (verified in code; tests reported green) | — |
| B-004 | done in code; production migration pending (P1-01) | owner |
| B-007 KYC plaintext | open | P02 W2 |
| B-010 admin password-only / CSP | **CSP part done (W1, 2026-11-24)**; second factor waits for P0-06 | P02 W1 |
| B-011 Google via demo host | open | P02 W3 |
| B-012 runtime-editable commission rates ⚠ | open (P0-03) | P03 |
| B-013 single-person money actions ⚠ | open (P0-02) | P03 |
| B-014 customer support tickets | open | P04 |
| B-015 Stripe gaps / default gateway | integrity gaps **done (DEF-05, 2026-11-27)**; default gateway still open (P0-01, DEF-06) | P03 |
| B-016 CSV import on PIM | open | P06 |
| B-017 backups / monitoring / alerting | open (P0-09) | P05 |
| B-018 GST invoice / TCS | open (L-02, D-15) | P07 |
| B-019 legacy report exports | **done (W4, 2026-11-24)**; role questions in D-16 (D16-W4-1…5) | — |
| B-020 unrecorded money owed (late UPI, double payment, rejected events) | open | P03 |
| B-021 over-promising refund cases | open (DEF-04) | P03 |
| B-022 withdrawal request not crash-safe | **done (P03, 2026-11-27)**; uncommitted | — |
| B-023 settlements without order / bank snapshot | **done (P03, 2026-11-27)**; uncommitted | — |
| B-024 vendor platform commission policy ⚠ | open (P0-04) | P03 |
| B-025 missing indexes / TTLs | **indexes done (W5, 2026-11-24; production migration pending, P1-01)**; TTLs await P0-05; residual W5-R1…W5-R6 (§8) | — |
| B-026 admin role breadth | open (D-04, D-06, D-16) | P02 |
| B-027 delivery proof | open (D-04) | P06 |
| B-028 transactional messages, preferences | open | P04 |
| B-029 returns UI, "Pay now" | open | P04 |
| B-030 admin finance screens, audit-log viewer, user paging | open | P05 |
| B-031 payment-exceptions 1,000-order window | open | P05 |
| B-032 dependency currency | **done (W6, 2026-11-24)**; residual W6-R1…W6-R8 (§8) | — |
| B-033 environment hygiene (partly documented in P01) | partly done | P05 |
| B-034 "Shop with me" copy | open (DEF-09) | P08 |
| B-035 UI tests / R-14 | open | P02 W8 / P05 |
| B-036 profile photo http / data URIs | open | P02 |
| B-037 lockout abuse, enumeration (L7, L8) | open | P02 |
| B-038 VEN-05 tests, missing spec, Batch 14 docs | partly done (Batch 14 recorded in the engineering log; overview test missing; `PAYMENT_RECONCILIATION_SPEC.md` still missing) | P06 / P05 |
| B-039 Approvals 403 | **done (W7, 2026-11-24)**; presentation choice P1-08 open | — |
| B-040 undefined-name build check | **done (W8, 2026-11-24)** | — |
| B-041 local http upload URLs | open (DEF-10) | P05 |
| B-042 incremental ledger reconcile marker | open | P05 |
| P3 list (mixed-GST clawback R-8, UPI races R-7, applied_ops growth, commissions report columns, L4 self-credit approval, cart not cleared on logout, demo script contract, advancement access, stock-import permission) | open | P03 / P05 / P06 |

## 8. Corrections log
| Date | Item | Evidence | Remaining |
|---|---|---|---|
| 2026-11-24 | **DEF-03 corrected** — stock-journal crash recovery (`recover_stock_txns`, `process_restock_intents`) and the stuck-expiry self-heal (`heal_stuck_expiries`) are resumable keyset sweeps with checkpoints, per-record isolation, failure records (`job_failures`) and retry, run records (`job_runs`), dry run and re-check before acting; abandoned committed reservations now get a compensating journal row (`PROGRAMME_01_TECHNICAL_SPECIFICATIONS.md` §9) | `test_def03_stock_recovery` 15/15 (×4 runs); full in-process regression 72 suites, 1,464 passed, 0 failed, 0 skipped; live suites 96 passed, 6 skipped (same reasons as before); pyflakes no new findings | Historical journals of reservations rolled back before 2026-11-24 are not rewritten (net counter correct; journal shows only the −1). `prune_stock_markers` (housekeeping, query shrinks as it works) keeps its 200-per-run limit. |
| 2026-11-24 | **DEF-02 / B-040 corrected (Programme 02 W8)** — the build and `npm run lint` use `frontend/.eslintrc.js` (react-app + undefined-name, import-integrity, duplicate, hook and unreachable rules as errors); `npm run build:check` proves each defect class is still caught | 13/13 guards; production build fails on injected undefined name / unresolved import / invalid named import (scratch copy) and passes without; lint 0 errors / 9 warnings (172 files); `npm run quality` green; frontend tests 7/7; browser 74/74 | 9 lint warnings (below); repository-tracked browser smoke suite (VG-01) |
| 2026-11-24 | **VG-08 / B-032 closed (Programme 02 W6)** — `pip-audit` (PyPI + OSV) and `npm audit` run before and after; production backend set 4 vulnerable packages (1 critical, 14 high) → 0; Emergent `requirements.txt` 15 → 5 (all unused by the application); frontend 38 findings (22 high) → 26 (13 high, build / test toolchain only, none in the browser bundle). One compatibility shim (`core.py`, PyMongo lazy SRV) | `HOME_GENIES_DEPENDENCY_AUDIT_W6.md`; engineering log Programme 02 / W6 | W6-R1…W6-R8 below |
| 2026-11-24 | **B-025 indexes and repair controls (Programme 02 W5)** — 40 indexes specified (37 query, 3 integrity) after a static analysis of 1,042 database call sites; member login and the request-time repair sweeps no longer scan `users` / `orders` / `stock_txns`; races fixed: double KYC submission, first use of a sequence (duplicate invoice / refund / settlement numbers), repeated cron delivery; `prune_stock_markers` complete and resumable; migration dry run with duplicate counts, run records, interrupted-run detection; index verification corrected (renamed index, collation, text language, multikey / null duplicates) | `HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md`; `test_w5_index_integrity` (58); engineering log Programme 02 / W5 | W5-R1…W5-R6 below |
| 2026-11-24 | **DEF-08 / B-019 corrected (Programme 02 W4)** — every report and export inventoried (30 endpoints); bulk reports mask mobile / e-mail / payment session id for every role (screen and CSV); report CSV export follows the export roles (support refused, interim D16-W4-1); one formula-injection rule for every cell; every export attempt audited; money from paise; dates validated; oversized exports refused; Reports screen errors and roles fixed | `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md`; `test_w4_export_security` (63) | W4-R1…W4-R6 below |
| 2026-11-24 | **DEF-01 / B-039 corrected (Programme 02 W7)** — browser crawl of every admin page and Operations tab as each admin role: 16 refused requests → 0; actions the server refuses no longer offered (COD collect, merchandising editing, catalogue decisions, add-for-vendor); one frontend copy of the server's role sets kept in step by a backend test | `lib/roles.js`, `components/RoleGate.js`; `test_w7_role_sets_in_sync`, `RoleGate.test.js`; browser 112/112 | P1-08 presentation; admin studio / Settings money-field gaps (D44) |
| 2026-11-24 | **R-10 / L5 corrected (Programme 02 W1, criterion d)** — frontend served with a strict Content-Security-Policy and frame protection (`frontend/vercel.json`), build without inline script; header test + browser check under the same headers (38/38) | `src/securityHeaders.test.js`; engineering log | headers on the deployed host unverified; 2FA (P0-06) |
| 2026-11-27 | **DEF-05 corrected (Programme 03)** — Stripe webhook and status poll pay an order only on Stripe's own server-side record (paid, INR, exact paise total, the attempt's order); one `webhook_events` record per delivery / session with claim, outcomes and finance retry (re-reads Stripe); applied only through the shared state machine | `test_p03_stripe_integrity` (26; 23 fail on the old code) | gateway choice / default button (P0-01, DEF-06); rejected captures create no refund obligation (P03-OD-04); poll public (P03-OD-03); `origin_url` allow-list (P03-A12) |
| 2026-11-27 | **B-022 done (Programme 03)** — withdrawal request intent-first, keyed hold excluded by a void marker, HELD row by op key, notice / audit once, optional idempotency key, repair sweep in the daily maintenance; pay / reject path fails closed before money moves and a settled-but-open request is reported (P03-A04) | `test_p03_withdrawal_requests` (40; 31 of the first 38 fail on the old code); browser: lost response + retry ⇒ one request | key optional (P03-A13); P03-OD-02; new indexes need P1-01 |
| 2026-11-27 | **B-023 done (Programme 03)** — immutable settlement snapshot (order basis, masked payee bank details, digest); pay refused on altered snapshot or bank change | `test_p03_settlement_snapshot` (11; all fail on the old code) | P03-OD-01, P03-OD-05; open legacy settlements (P03-A14) |
| 2026-11-27 | **Financial reconciliation framework (Programme 03)** — read-only report over payments, wallets, withdrawals, settlements, vendor ledger, refunds, commissions, stock (API, script) | `test_p03_reconciliation` (17; read-only proven by full-database fingerprint) | — |

**Programme 03 audit items (2026-11-27; detail `HOME_GENIES_PROGRAMME_03_ENGINEERING_REPORT.md` §6):**
| ID | Item | Severity | Programme · decision |
|---|---|---|---|
| P03-A01 | Customer cancel of a paid order writes no refund marker with the claim; a crash before the case leaves an unrecorded refund (now reported by reconciliation) | High | P03 next package |
| P03-A02 | Late payment on a cancelled order: a crash before late handling leaves paid + cancelled with no refund record (now reported) | High | P03 next package (B-020) |
| P03-A03 | COD discrepancy resolve / cash collection not excluded for cancelled orders | Medium (to confirm) | P03 next package |
| P03-A05 | Return-window policy changeable by `admin` | Medium | D-05 |
| P03-A06 | Any admin role can verify KYC / bank details | to confirm | D-06 / P0-02 |
| P03-A07 | Failed financial approval cannot be retried after partial execution | Low | P03 |
| P03-A08 | Vendor commission percent → basis points via float `round()` | Low | P03 with B-024 |
| P03-A09 | Manual payment may target an expired order; no post-check | Low | P03 |
| P03-A10 | Ledger not-supplied set omits `returned_to_origin` | Low | P03 before B-024 |
| P03-A11 | Maintenance time budget overrun per batch | to confirm | P05 |
| P03-A12 / A13 / A14 | Stripe `origin_url` allow-list; optional withdrawal key; open legacy settlements without snapshot | Low | P03 |

**Remaining frontend lint warnings after W8 (9; none fail the build; not fixed because each would change behaviour, semantics or vendored code):**
| File:line | Rule | Classification |
|---|---|---|
| `components/vendor/Governance.js:113` | react/jsx-pascal-case (`History_`) | naming only; renaming a component is a refactor — P3 |
| `components/vendor/VendorUI.js:94` | jsx-a11y/role-supports-aria-props (`aria-pressed` on role radio) | accessibility semantics — needs a UI decision — P3 |
| `pages/admin/AdminVendorApplications.js:83` | jsx-a11y/role-supports-aria-props (`aria-pressed` on role tab) | same — P3 |
| `pages/admin/AdminSettings.js:18` | no-unused-vars (`isSuper`) | unused computed value; may signal an unfinished role check — review, P3 |
| `pages/admin/AdminUsers.js:54` | no-unused-vars (`loadPwReqs`) | unused loader; may signal a missing refresh — review, P3 |
| `components/ui/alert.jsx:32` | jsx-a11y/heading-has-content | vendored shadcn component — P3 |
| `components/ui/pagination.jsx:38` | jsx-a11y/anchor-has-content | vendored shadcn component — P3 |
| `hooks/use-toast.js:8` | no-unused-vars (`actionTypes`) | vendored shadcn hook — P3 |
| `hooks/use-toast.js:41` | default-case | vendored shadcn hook — P3 |

**Residual items after W6 (each has a written reason in `HOME_GENIES_DEPENDENCY_AUDIT_W6.md` §6 / §10):**
| ID | Item | Severity / risk | Programme · decision |
|---|---|---|---|
| W6-R1 | CRA 5 build / dev-server / test toolchain advisories (svgo, nth-check, serialize-javascript, webpack-dev-server, workbox, uuid, postcss 7, jest 27 / jsdom 16 …): only fix is leaving Create React App | 13 high, 4 moderate, 9 low; build machine only, not in the browser bundle | framework replacement needs owner approval (F-1); candidate for P05 |
| W6-R2 | Emergent-only Python packages with no in-range fix: pillow 12.3.0 (13.0.0 major), python-jose 3.5.0 and ecdsa 0.19.2 (no fix), filelock 3.32.2 (4.x), oauthlib 3.3.1 (4.x); none imported by the application | 6 critical, 28 high in unused code | remove or upgrade with the Emergent clean-up — D-10 (F-3) |
| W6-R3 | `frontend/package.json` declares `packageManager: yarn@1.22.22` and 42 yarn `resolutions`, but npm installs (only `package-lock.json` exists); under yarn the stale entries would force vulnerable / CRA-incompatible versions | P2 (latent) | P05 / B-033 (F-4) |
| W6-R4 | `frontend/.npmrc` `legacy-peer-deps=true` hides peer checks; after W6 the only peer conflict is `react-day-picker@8` (React ≤ 18, date-fns ≤ 3; used only by the unused `components/ui/calendar.jsx`) | P3 | P05 |
| W6-R5 | `emergentintegrations==0.2.0` (private) could not be checked against the upgraded pins | unknown; Emergent only | D-10 |
| W6-R6 | Motor is deprecated upstream (PyMongo native async replaces it) | P3 | future (F-2) |
| W6-R7 | Starlette 1.x TestClient deprecation warning (`httpx` → `httpx2`), tests only | P3 | future (F-5) |
| W6-R8 | No dependency audit step in CI; upgraded pins not yet deployed or production-verified | P2 | P05 (F-6); owner deploy with Programme 01 |

**Residual items after W5 (`HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md` §6.2, §7, §9, §12):**
| ID | Item | Severity / risk | Programme · decision |
|---|---|---|---|
| W5-R1 | The 40 W5 indexes (incl. 3 new unique constraints) exist only in the specification and the test databases; production needs the migration, preceded by its dry run on a production copy | P1 (performance, races stay open until then) | Owner: P1-01 |
| W5-R2 | Retention: no TTL beyond the 3 operational ones; candidates store ISO-string times, so any approved period needs a BSON date field or an audited delete job | P2 | P0-05 |
| W5-R3 | Silently capped figures: admin dashboard total revenue (5,000 paid orders), monthly badge sales (5,000 orders), member commission figures (2,000), vendor statement (20,000 rows), read-only audits (10,000-100,000) | P2 | W4 / P05 / P03 |
| W5-R4 | A gateway event left `processing` after the gateway stops retrying is visible only through the finance inbox filter | P2 | P03 |
| W5-R5 | Sweeps have no run lease; safe only because every handler is claim-based (rule recorded) | P3 | — (only if a non-idempotent handler is added) |
| W5-R6 | Any duplicates the production dry run finds in `kyc_records` / `counters` / `cron_runs` need a per-record decision (incl. whether duplicate invoice / refund / settlement numbers were issued) | conditional | Owner: W5-01 |

**Residual items after W4 (`HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md` §5, §13):**
| ID | Item | Severity / risk | Programme · decision |
|---|---|---|---|
| W4-R1 | accounts_admin sees full customer contact / address in the legacy members, orders, refund-queue and registration lists (the order-ops detail masks it) | P1 (DPDP) | D-16 · D16-W4-3 |
| W4-R2 | support_admin reads finance lists (payments incl. session ids, commissions, vendor ledger, settlements) | P2 | D-16 · D16-W4-2 |
| W4-R3 | Audit viewer shows actor e-mail / IP to every admin role; last 500 records, no filters or paging | P2 | D-16 · D16-W4-4; P05 |
| W4-R4 | Legacy admin list endpoints (users, orders, payments, commissions, referrals, KYC, withdrawals) return up to 1,000 rows without paging | P2 | P05 (D3) |
| W4-R5 | KYC / identity values stored in plaintext (masked on every way out) | P0 | W2 (A-01, P0-05) |
| W4-R6 | accounts_admin can read vendor identity-document links (existing, tested) although it may not review them | P1 | D-16 · D16-W4-6 |

**Residual items after W7 and W1 (CSP) — 2026-11-24:**
| ID | Item | Severity / risk | Programme · decision |
|---|---|---|---|
| W7-R1 | Admin product studio opens for accounts / support admins (the server refuses saving) | P3 | P02 / P06 |
| W7-R2 | Settings money fields are editable on screen for non-finance roles (the server refuses a change, with a clear message) | P3 | P02 |
| W1-R1 | Admin second factor, its recovery path, admin session lifetime and fresh-factor rule for money actions | P0 (launch) | P0-06 |
| W1-R2 | Security headers not yet observed on the deployed frontend host | P2 | owner deployment |
| W1-R3 | Session token in `localStorage` (cookie scope depends on hosting) | P2 | D-10 |

## 7. Open capabilities by programme (generated from the current matrix)
Every row of the current matrix that is not "Implemented and verified" with nothing left to do. Rows marked done in the matrix but
carrying a programme are included (they have remaining work).

### Owner action before deploying Programme 01 — 2 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| E15 | Money-write protection: refuse money writes while protective unique indexes are missing or different (fail closed, 503) | Implemented and verified | production migration not run (P1-01) · P0 owner action |
| O21 | P1-01 production index migration after a verified backup (owner action) | Blocked by owner decision | decision required · before any P01 deployment |

### P02 — 25 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| A3 | Google sign-in | Blocked by external integration | Works only while the Emergent auth broker is reachable; no first-party Google OAuth · P2 |
| A31 | Account deletion / data export by the customer | Not implemented | see L12 · P2 |
| B6 | KYC submission (PAN, Aadhaar, bank) | Implemented and verified | plaintext storage and role gap tracked in L9/L10 |
| D3 | Users: list, edit, block, deactivate | Implemented and verified | list unpaged and capped at 1000 (`admin_routes.py:122`); support_admin can deactivate customers/members · P2 |
| D16 | Admin order status change | Implemented and verified | R-2 / D-04 · P2 |
| D37 | Reports & exports (8 legacy reports) | Partially implemented | float (non-paise) money columns, no date range, 2000/5000 row caps, export not audited, e-mail+mobile exported to support role · P1 |
| D44 | Role-aware admin UI (hide actions a role cannot perform) | Partially implemented | Operations page requests finance approvals for non-finance admins → 403 (B-039 / P1-08); nav-level only · P2 |
| E1 | JWT sessions (`type: access`, exp/sub), logout revocation via `jti`, password-change invalidation | Implemented and verified | tokens issued before `jti` not revocable (R-6, time-bounded) |
| K7 | Google OAuth through Emergent session broker | Blocked by external integration | · P2 |
| L5 | Frontend Content-Security-Policy | Not implemented | R-10 · P2 |
| L6 | Trusted proxy for client IP | Blocked by owner decision | D-10 hosting confirmation · P2 |
| L7 | Encryption at rest of PAN / Aadhaar / bank details | Not implemented | · P0 |
| L8 | KYC submission limited to members | Partially implemented | · P2 |
| L9 | PII exposure to support role (legacy reports export e-mail/mobile; users list returns full user documents minus hash) | Partially implemented | masking + export audit missing · P1 |
| L10 | Support-role write powers (order status, customer deactivation, settings non-money fields, referral codes) | Blocked by owner decision | D-16 / D-04 · P2 |
| L12 | Data-subject rights (export, deletion, anonymisation) and retention policy | Not implemented | · P2 (legal input needed) |
| L14 | Unauthenticated payment status lookup returns `order_id` by session id | Partially implemented | · P3 |
| L15 | Legacy sign-up endpoint still public (`/api/auth/register`, stores `email_verified: False`) | Deprecated or duplicated | retire · P3 |
| L16 | Unverified legacy `email_verified: true` accounts (R-5) | Blocked by owner decision | owner may run re-verification · P2 |
| M2 | Admin legacy reports + CSV | Partially implemented | D37 · P1 |
| N10 | Frontend lint catches undefined identifiers | Partially implemented | a Programme 01 change crashed a studio step and only the browser check caught it (B-040) · P2 |
| O9 | D-10 hosting / trusted proxy | Blocked by owner decision | P2 |
| O10 | D-11 admin reset without SMS | Blocked by owner decision | P2 |
| O27 | P1-07 admin roles for platform uploads | Blocked by owner decision | decision required · P02 |
| O28 | P1-08 Operations Approvals tab for non-finance admins | Blocked by owner decision | decision required · P02 |

### P03 — 28 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| A10 | Checkout & order creation (GST-inclusive per-line snapshot, address snapshot, seller attribution, stock reservation) | Implemented and verified | Stripe 503 still leaves a pending order; since Programme 01 it expires after 15 min and counts toward the 5-order open cap (B-006) · residual P1 |
| A14 | Pay online — Razorpay client checkout + signature verify | Implemented, verification incomplete | client verify path untested; completion is now the shared step (B-003); live gateway never exercised (R-15) · P1 |
| A15 | Pay online — Stripe Checkout (default "Place order" button for method `online`) | Blocked by external integration | still unconfigured by default; no amount/currency check; webhook not recorded in webhook_events; completion now shared + retried (B-003) · P1 |
| D14 | Commission administration (list, manual release/hold) | Backend complete, frontend incomplete | no screen · P2 |
| D21 | Refund cases (initiate, confirm by second finance admin, fail/retry, resolve) | Implemented and verified | booking must succeed exactly before confirmation (B-002); over-promising open cases still possible (B-021) · P2 |
| D25 | Duplicate payments | Implemented, verification incomplete | only a screen-contract test · P2 |
| D27 | Vendor ledger view & adjustments | Backend complete, frontend incomplete | no screen to raise an adjustment although approvals are on screen · P2 |
| D28 | Settlement finance policy (dual approval, minimum) | Backend complete, frontend incomplete | no screen · P3 |
| F5 | Stripe path | Blocked by external integration | see A15 · P1 |
| G4 | Clawback on per-line taxable value for mixed-GST orders | Partially implemented | money accuracy on mixed-GST refunds · P0 (low magnitude) |
| G8 | Refund execution through the payment provider | Blocked by external integration | money is returned outside the system; only a reference is recorded · P1 |
| G9 | Payout execution (vendor settlements, member withdrawals) to bank | Blocked by external integration | no payout API · P2 |
| G13 | UPI confirm vs expiry race leftovers (L2), concurrent confirms with different UTRs both 200 (L3) | Partially implemented | · P0 (low magnitude) |
| G14 | Finance reports (commission funding, non-distributor commissions, negative wallets) | Backend complete, frontend incomplete | no screen · P2 |
| G17 | Returned-to-origin financial handling (liability, sale reversal, refund case, commission hold/clawback, restock after inspection) | Implemented and verified | historical RTO orders (P1-02); closing such a case without refund (P1-03) · P1 owner |
| G18 | Refund confirmation integrity (exact booking, rejected/zero never confirms, retry with same reference) | Implemented and verified | over-promising open cases (B-021) · P2 |
| K1 | Razorpay (checkout, verify, webhook) | Blocked by external integration | needs staging run with test keys (R-15) · P1 |
| K2 | Stripe (via Emergent `emergentintegrations==0.2.0` in `requirements.txt:23`, else `stripe==14.4.1` SDK in `pyproject.toml`) | Blocked by external integration | decide one card gateway; Stripe unreconciled · P1 |
| K8 | Provider refunds | Blocked by external integration | G8 · P1 |
| K9 | Bank payouts | Not implemented | G9 · P2 |
| M8 | Finance reports | Backend complete, frontend incomplete | G14 |
| O3 | D-02 settlement creator may also pay | Blocked by owner decision | P2 |
| O4 | D-03 COD cash confirmation authority | Blocked by owner decision | P1 |
| O8 | D-09 COD fee on refunds; GST-inclusive vendor value (tax adviser) | Blocked by owner decision | P1 |
| O22 | P1-02 historical returned-to-origin orders without a refund case | Blocked by owner decision | decision required · P03 |
| O23 | P1-03 closing a not-supplied refund case without refund | Blocked by owner decision | decision required · P03 |
| O24 | P1-04 automatic expiry of unaccepted COD orders | Blocked by owner decision | decision required · P03 |
| O25 | P1-05 order-protection limits | Blocked by owner decision | decision required · P03 |

### P04 — 20 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| A21 | Return ship-back with tracking; withdraw a return | Backend complete, frontend incomplete | customer cannot record return tracking or withdraw; vendor can still `receive` from `approved` · P2 |
| A22 | Return photos | Backend complete, frontend incomplete | no photo evidence for damaged-goods returns · P2 |
| A23 | Refund status on order | Implemented, verification incomplete | customer sees amount only, not the refund case stage/reference · P3 |
| A25 | In-app notifications | Implemented, verification incomplete | no per-item read, no paging (100 cap) · P3 |
| A26 | Notification preferences | Not implemented | not implemented · P3 |
| A27 | Customer support tickets / complaints | Not implemented | no way to raise or track a customer complaint in-app · P1 (see O18) |
| A29 | Self-service mobile number change | Backend complete, frontend incomplete | no screen · P3 |
| D26 | Vendor support inbox | Implemented, verification incomplete | no thread view; no assignment/SLA · P3 |
| E5 | Notification writer | Implemented, verification incomplete | in-app only (J3) |
| E6 | E-mail sender | Blocked by external integration | only used for vendor owner invitations (`vendor_invitations.py:50`) · P2 |
| I6 | Customer return shipment | Backend complete, frontend incomplete | A21 · P2 |
| J1 | In-app notifications (customers/members) | Implemented, verification incomplete | A25 · P3 |
| J3 | Transactional e-mail / SMS for orders, payments, shipping, refunds | Not implemented | customers get no off-app confirmation · P2 |
| J4 | OTP SMS | Blocked by external integration | K3 |
| J5 | Notification preferences / opt-outs | Not implemented | · P3 |
| J6 | Customer support tickets | Not implemented | A27 · P1 |
| J8 | Push / WhatsApp | Not implemented | · P3 |
| K3 | Twilio SMS | Blocked by external integration | · P1 (OTP-dependent flows degrade without it) |
| K4 | E-mail (Emergent integrations API) | Blocked by external integration | · P2 |
| O18 | Consumer grievance mechanism for an e-commerce marketplace (ASSUMPTION: Indian Consumer Protection (E-Commerce) Rules 2020 require a grievance officer and complaint acknowledgement/tracking) | Not implemented | P1 |

### P05 — 31 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| A28 | Profile, profile photo, password change | Implemented, verification incomplete | profile update and photo upload untested · P3 |
| D2 | Admin dashboard | Implemented, verification incomplete | in-process tests absent · P3 |
| D5 | Registration-request queue | Deprecated or duplicated | legacy queue still shown · P3 |
| D6 | Referral codes | Implemented, verification incomplete | untested · P3 |
| D18 | Old unpaged admin order list (`GET /api/admin/orders`) + separate old page | Deprecated or duplicated | merge into order ops · P3 |
| D30 | Admin image/document upload in studio & merchandising | Implemented, verification incomplete | never exercised against real Cloudinary / Emergent storage; plain-http local server cannot save uploaded banner (B-041) · P2 |
| D39 | Returns-policy administration | Backend complete, frontend incomplete | no screen; D-05 governs authority · P2 |
| D40 | Vendor policy | Backend complete, frontend incomplete | no screen · P3 |
| D41 | Audit log viewer | Partially implemented | no filter/paging: older records unreachable from UI · P2 |
| D43 | User detail screen | Backend complete, frontend incomplete | · P3 |
| D45 | Operations queues show each record's real status (refunds, returns, settlements, tickets) | Implemented, verification incomplete | add automated UI coverage (N9) · P3 |
| E7 | File storage + `/api/files` | Blocked by external integration | external dependency (K5) · P2 |
| E16 | Resumable keyset sweep runner (checkpoint, isolation, dry run, time budget) | Implemented and verified | stock-journal recovery not yet on it (F2) · P2 |
| F2 | Stock reservation / release / expiry (15 min) / crash recovery | Implemented and verified | prepaid expiry is a full sweep with payment-in-progress grace (B-006); stock-journal crash recovery still capped (run_recovery limit 20 per run; stuck-expiry self-heal limit) · P2 |
| F12 | Owner reconciliation tool (report-only by default) | Implemented, verification incomplete | run against a production COPY before go-live (P05) · P2 |
| G2 | Commission release after delivery + return window (J1) | Implemented and verified | release is a resumable sweep, no 5,000 cap (B-005); HTTP cron route still untested · P3 |
| K5 | Object storage (Emergent) | Blocked by external integration | profile photos / admin product images depend on it · P2 |
| K11 | Error monitoring / alerting (e.g. Sentry) | Not implemented | · P2 |
| M1 | Admin dashboard KPIs | Implemented, verification incomplete | · P3 |
| M11 | Audit trail reporting | Partially implemented | D41 · P2 |
| N1 | Backend deployment (Vercel, root `backend`, 60 s limit) | Implemented, verification incomplete | not production-verified (all docs agree) · P1 |
| N2 | Second deployment path `deploy/vercel-api` (copies backend; schedules only release-points) | Deprecated or duplicated | would skip J2 if used; untracked stale copy present locally · P2 |
| N3 | Scheduled jobs J1/J2 (daily; Vercel Hobby) | Implemented, verification incomplete | 40 s budget, resumable sweeps, runs stored in cron_runs (B-005); daily cadence; no monitoring UI · P2 |
| N6 | Monitoring, alerting, log aggregation | Not implemented | R-10 · P2 |
| N7 | Backups / disaster recovery | Not implemented | evidence required · P1 |
| N8 | Staging environment & live HTTP suites | Partially implemented | R-11 staging run pending · P2 |
| N9 | Frontend automated tests | Partially implemented | no UI regression net · P2 |
| N12 | Script `customer_role_report.py` (D-12, read-only) | Implemented, verification incomplete | untested; output prints masked mobiles · P3 |
| N13 | Script `demo_environment.py` (seed/cleanup demo data via real routes, local test DB only) | Implemented, verification incomplete | every route it calls still exists (verified against the route table, incl. legacy POST `/api/vendor/products`); KNOWN_GAPS R-12 "old contracts" refers to payloads — not verifiable without running · P3 |
| N14 | Other scripts: `hash_admin_password.py` (none), `migrate_money_paise.py` (`test_money_exact`), `vendor_foundation_migrate.py` (`test_vendor_foundation`), `historical_audit.py` (`test_historical_audit`), `seed_test_backend.py` (none) | Implemented, verification incomplete | two scripts untested · P3 |
| N15 | System-integrity diagnostics endpoint (money protection, completion backlog, job checkpoints) | Backend complete, frontend incomplete | no admin screen (P05) · P2 |

### P06 — 33 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| C6 | Business profile edit + per-status profile overview (VEN-05) | Implemented, verification incomplete | contact/state validation fixed and tested (B-008); GET /vendor/me/profile-overview still has no test · P2 |
| C10 | Product studio: drafts, template fields, variants, versioned autosave, submit | Implemented and verified | "discard draft" (DELETE) has no button · P3 |
| C13 | Product CSV import onto the PIM fields (VEN-04) | Partially implemented | Columns lack `hsn_code`, `highlights`, `model_number`, `image_alt`, template attributes, variants; an update **does not check `pending_revision`** (PUT does, `:511`) and hides a live approved product (`:677-681`) · P1 |
| C14 | Legacy direct create/update of products | Deprecated or duplicated | superseded by C10 but still callable · P2 (retire or align with PIM) |
| C15 | Inventory: adjustments with reasons, history, stock CSV import | Implemented and verified | stock import needs `products.submit` instead of `inventory.adjust` (inventory-manager preset cannot import) · P3 |
| C18 | Delivery proof (VEN-06) | Blocked by owner decision | D-04 · P1 |
| C26 | Advancement & benefit eligibility | Implemented and verified | staff access inconsistency · P3 |
| C27 | Dashboard / analytics | Implemented, verification incomplete | earlier docs: figure review "NOT STARTED"; two screens on one endpoint · P3 |
| C31 | Button-level hiding for staff | Partially implemented | not started per roadmap · P3 |
| C34 | Duplicate vendor routes/screens (`/vendor/finance`≡`/earnings`, `/dispatch`+`/returns`≡`/shipping`, owner-invitation vs owner-access, decision vs final-review) | Deprecated or duplicated | consolidate · P3 |
| C35 | Image / document upload (Cloudinary signed) | Blocked by external integration | depends on Cloudinary configuration · P2 |
| C36 | Vendor merchandising requests | Blocked by owner decision | D-19 · P3 |
| D9 | Platform role expansion (Finance/Catalogue/Ops/Reports roles, custom) | Blocked by owner decision | D-16 · P2 |
| D29 | Catalogue moderation: revisions with diff, new products, admin drafts for a vendor | Implemented and verified | price history not shown (`pim.py:466` unused) · P3 |
| D31 | Platform-own products (direct CRUD, stock, takedown, permanent delete) | Implemented, verification incomplete | separate write model from PIM (map §9); image upload now content roles only (B-009) · P3 |
| D42 | Category / attribute template management | Not implemented | code change needed per template (R-13) · P3 |
| H3 | Price history | Backend complete, frontend incomplete | not shown in UI · P3 |
| H6 | Bulk CSV import/export | Partially implemented | VEN-04 · P1 |
| H7 | Legacy product form & direct write routes | Deprecated or duplicated | · P2 |
| H9 | Scheduled publishing of products | Not implemented | roadmap "NOT STARTED" · P3 |
| H10 | Product ratings & reviews | Not implemented | · P3 |
| H11 | Product images & documents hosting | Blocked by external integration | two storage back-ends; admin studio cannot use either for upload (D30) · P2 |
| I2 | Courier integration (labels, pickup, live tracking, COD remittance) | Not implemented | · P2 |
| I3 | Proof of delivery (VEN-06) | Blocked by owner decision | D-04 · P1 |
| I8 | Admin-recorded delivery (no payout effect) | Blocked by owner decision | D-04 / R-2 · P2 |
| K6 | Cloudinary signed uploads | Blocked by external integration | · P2 |
| K10 | Courier | Not implemented | I2 · P2 |
| M4 | Vendor dashboard / analytics | Implemented, verification incomplete | C27 |
| O5 | D-04 delivery confirmation and proof | Blocked by owner decision | P1 |
| O14 | D-16 platform roles | Blocked by owner decision | P2 |
| O15 | D-17 staff money-adjacent access | Blocked by owner decision | P2 |
| O17 | D-19 vendor merchandising requests | Blocked by owner decision | P3 |
| O26 | P1-06 merchandising image rule | Blocked by owner decision | decision required · P06 |

### P07 — 7 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| A12 | Separate billing address on invoices | Blocked by owner decision | D-18 · P3 |
| A24 | Invoice | Partially implemented | browser print only; no PDF, no per-seller GST tax invoice / seller GSTIN, D-18 billing address · P1 (see O19) |
| G16 | Tax classification authority (HSN/GST) | Blocked by owner decision | D-15 · P1 |
| K12 | GST e-invoicing / TCS reporting | Not implemented | O19 · P1 |
| O13 | D-15 HSN/GST authority | Blocked by owner decision | P1 |
| O16 | D-18 billing address | Blocked by owner decision | P3 |
| O19 | GST-compliant tax invoices per seller, e-commerce operator TCS (ASSUMPTION: required under Indian GST for marketplace operators) | Not implemented | P1 |

### P08 — 23 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| B9 | Referral page | Implemented, verification incomplete | only a live-server suite touches it; 'Shop with me' copy on a sponsor link (B-034) · P2 |
| M9 | HomeGenie performance reports | Not implemented | B12 · P3 |
| M10 | Product / funnel analytics (views, conversion) | Not implemented | · P3 |
| P1 | M1 Product sharing & attribution links (server-issued short links /s/<code>, link id + channel, signed) | Partially implemented | server links, link ids, channel, Open Graph landing; preserve last-click rule (OD-M6) · P08 |
| P2 | M2 WhatsApp product sharing (member's own WhatsApp, wa.me, one-to-one) | Not implemented | product-level WhatsApp share with approved caption · P08 |
| P3 | M3 WhatsApp campaign tools (member-side, no bulk send) | Not implemented | campaign kits; never automated sending · P08 phase 2 |
| P4 | M4 Instagram & Facebook sharing | Not implemented | share sheet incl. Facebook sharer; IG via Web Share with poster · P08 |
| P5 | M5 Other social channels (X, Telegram, SMS, e-mail, Pinterest, LinkedIn) | Not implemented | share targets · P08 |
| P6 | M6 AI-assisted captions / descriptions | Blocked by owner decision | OD-M4 provider and budget; MVP uses approved templates only · P08 phase 2 |
| P7 | M7 Hashtag suggestions (curated sets) | Not implemented | curated hashtag sets · P08 |
| P8 | M8 Promotional creatives / posters with QR (client-side; price stamped) | Not implemented | poster generator; price display needs OD-M3 · P08 |
| P9 | M9 Festival / seasonal campaigns | Not implemented | campaign packs · P08 phase 2 |
| P10 | M10 Personal campaign calendar (in-app reminders only) | Not implemented | calendar · P08 phase 2 |
| P11 | M11 Saved templates (platform-approved and personal) | Not implemented | template store + two-person approval · P08 |
| P12 | M12 Click & conversion tracking (first-party only, no fabricated reach) | Partially implemented | link click recording and click→order conversion · P08 |
| P13 | M13 Marketing-source (channel) attribution | Not implemented | orders.marketing snapshot, share_link_code · P08 |
| P14 | M14 Customer enquiries & consent-based lead tracking (DPDP) | Not implemented | consent capture, retention rule, privacy notice update · P08 phase 2 |
| P15 | M15 Marketing performance dashboard | Partially implemented | channel / campaign views · P08 |
| P16 | M16 Future: official WhatsApp Business Platform (Cloud API), opted-in templates only | Blocked by external integration | OD-M5 credit rule; opt-in store · P08 phase 3 |
| P17 | M17 Future: Meta Graph API publishing for members' own accounts | Blocked by external integration | only if demand proven · P08 phase 3 |
| P18 | Link previews (Open Graph tags / landing) for shared products | Not implemented | server-rendered or prerendered preview landing · P08 |
| P19 | Product pages viewable without login for link recipients | Blocked by owner decision | OD-M1 · P08 |
| P20 | Marketing compliance guard-rails (banned earnings / recruitment / health-claim phrases; claims policy) | Not implemented | policy text OD-M8 + legal input · P08 |

### Owner / legal (gates launch) — 7 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| O1 | Legal pages (terms, privacy, returns, refunds, support) | Partially implemented | P1 (legal review + align text) |
| O2 | D-01 return window / commission hold (7 days) | Blocked by owner decision | P1 |
| O6 | D-05 who changes the return window | Blocked by owner decision | P2 |
| O7 | D-06 KYC verifier rules | Blocked by owner decision | P2 |
| O11 | D-12 RED members → customers | Blocked by owner decision | P3 |
| O12 | D-14 launch-gap acceptance | Blocked by owner decision | P1 |
| O20 | Direct-selling / multi-level commission compliance review of the HomeGenie model (ASSUMPTION: Consumer Protection (Direct Selling) Rules 2021 may apply to sponsor-based 30/10/5 commissions) | Not implemented | P1 (not in the decision register) |

### Unscheduled (not in P02–P08; owner to prioritise) — 8 items

| ID | Capability | Current status | Remaining work · priority |
|---|---|---|---|
| A7 | Related products; recently viewed | Implemented and verified | recently-viewed is client-only (not cross-device) · P3 |
| A9 | Cart | Implemented, verification incomplete | no server cart: lost across devices, no stock/price check before checkout · P3 |
| B10 | Leaderboard / rewards journey | Implemented, verification incomplete | untested · P3 |
| B11 | Monthly badge | Backend complete, frontend incomplete | endpoint unused by UI · P3 |
| B12 | HomeGenie performance reports | Not implemented | not started (earlier matrix agrees) · P3 |
| F10 | Promotions, coupons, discounts | Not implemented | KNOWN_GAPS "promotional pricing" · P3 |
| F11 | Shipping charges / PIN serviceability | Not implemented | · P2 |
| I9 | Shipping charges / serviceability | Not implemented | F11 · P2 |
