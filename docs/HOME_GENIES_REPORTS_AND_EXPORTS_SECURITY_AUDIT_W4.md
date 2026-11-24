# HOME GENIES — Reports, exports and sensitive-data protection audit (Programme 02 / W4)

Date 2026-11-24. Working tree of `main` @ `d31cb74` (Programme 00 / 01 / DEF-03 / W8 / W6 / W5 work uncommitted); checkpoint
`~/home-genie-checkpoints/hg-20261124-1516-pre-w4-worktree.tar.gz`. Nothing staged, committed, pushed or deployed. No production data
read. Method: every route read from code (AST of all 296 routes; 58 report-type GET routes inspected), every export function read,
defects reproduced against the pre-W4 code before they were changed (§10). Readiness reference: `HOME_GENIES_PROGRAMME_02_READINESS.md` W4.
**D-16 is not decided; no role was given any new access.** One over-broad access (support_admin downloading report files) was narrowed to
the existing export rule (§4.2) and is recorded as interim D-16 item D16-W4-1; every other role question is left as it is and recorded.

## 1. Summary
| Area | Found | Done in W4 |
|---|---|---|
| Legacy admin reports (8) + CSV | CSV open to **every** admin role incl. support (the platform's own export rule `EXPORT_ROLES` excludes support); registrations listed and exported **full mobile and e-mail**; payments listed the gateway **session id** (the look-up key of the unauthenticated payment-status endpoint); **no audit** of view or export; no date filter; silent 2,000 / 5,000-row cut-off | export follows `EXPORT_ROLES` (interim, D-16); mobile / e-mail / session id masked in screen **and** CSV for every role; view and export audited; validated date range; `total` + `truncated` declared; exports over 5,000 rows refused (413) instead of cut |
| Vendor identity documents | `GET /api/admin/vendors/{id}/documents` answers every admin role, so `accounts_admin` can open PAN / identity / bank-proof links although it may not review them and may not open the onboarding view | **not changed**: an existing test states accounts_admin may still read the listing (`test_vendor_authority`, "still readable"), so this is an authorised access; recorded as D16-W4-6 (a restriction was tried, broke that test in the full regression, and was reverted) |
| Formula injection | two copies of one sanitiser; leading spaces, line breaks and full-width `＝＋－＠` not handled; product category and image cells written raw | one rule (`exports.csv_cell`) for every cell of every export; numbers and numeric text (e.g. `-120.00`) never altered |
| Export audit | only the admin order export was audited (filters stored verbatim, incl. a searched mobile number); vendor statement / report / catalogue exports left no record | every export attempt (success, refused, failed) audited with user, role, report, export id (also in the `X-Export-Id` response header), range, redacted filters, row count, format, scope; no exported value, token, password, OTP, PAN, Aadhaar or account number |
| Size / dates | vendor statement cut at 20,000 rows silently, accepted a start date after the end date; product export cut at 5,000 | refused with a clear message instead (413); start-after-end rejected (400) |
| Files / downloads | no export writes a file or creates a link (all in-memory, streamed in the authorised response); identity documents are Cloudinary `authenticated` uploads; `/api/files` serves only content-sniffed images | exports now `Cache-Control: no-store`; nothing else needed — no temporary files, no download URLs, nothing to expire or clean up |
| Frontend | Reports screen showed Export to every admin role, swallowed export failures, showed "No data" when loading failed; vendor / admin CSV downloads showed a generic error instead of the server's message | Export shown to export roles only; errors shown as errors; date filters; row count / truncation / masked-field note; the server's message (403 / 413 / 400) reaches the toast; nothing downloaded on failure |

## 2. Report and export inventory (every one found in code; none invented)
Roles: **SA** super_admin · **Adm** admin · **Acc** accounts_admin · **Sup** support_admin · **VO** vendor owner · **VS** vendor staff
(per permission) · **HG** HomeGenie member · **C** customer. "Masked" means masked in the response itself (not hidden in the UI).
`finance_admin` does not exist in the code; finance authority is the `super_admin` + `accounts_admin` pair (`FINANCE_ROLES`).

### A / B. Administration and finance
| ID | Capability | Endpoint | Screen / action | Roles (backend) | Fields (personal / financial) | Format | Filter / paging | Masking | Audit | Tests | Remaining |
|---|---|---|---|---|---|---|---|---|---|---|---|
| R-A1 | Dashboard figures | `GET /api/admin/dashboard` | AdminDashboard | all admin | counts, revenue totals | JSON | — | n/a | — | admin screens | total revenue sums ≤ 5,000 paid orders (W5-R3) |
| R-A2 | Legacy reports ×8 (registrations, sales, orders, payments, referrals, commissions, wallet, withdrawals) | `GET /api/admin/reports/{r}` | AdminReports (6 tabs) | all admin | registrations: name, **mobile, e-mail**, state, city; payments: **session id**, amounts; wallet: user ids, amounts | JSON | **W4:** dates, `total`, `truncated` (2,000 newest) | **W4:** mobile, e-mail, session id masked | **W4:** `report_viewed` | security_batch0, **W4** | amounts are floats (legacy) |
| R-A3 | Legacy report CSV | `GET /api/admin/reports/{r}/export` | AdminReports Export | **W4:** SA, Adm, Acc (was all admin) | as R-A2 | CSV | **W4:** dates; > 5,000 → 413 | **W4:** as R-A2 | **W4:** export_* | security_batch0, **W4** | D-16 (support export) |
| R-A4 | Order list | `GET /api/admin/order-ops/orders` | AdminOrderOps | all admin | customer name, **masked** mobile | JSON | 10 filters, IST range ≤ 366 d, paged | mobile masked | — | admin_order_ops_b13, **W4** | — |
| R-A5 | Order CSV | `GET /api/admin/order-ops/orders.csv` | AdminOrderOps Export CSV | SA, Adm, Acc | masked mobile, account id; no address | CSV | filters; **W4:** > 5,000 → 413 (was cut) | mobile masked | `orders_exported` + **W4** export_* (filters redacted) | b13, **W4** | — |
| R-A6 | Order detail | `GET /api/admin/order-ops/orders/{id}` | order detail | all admin | full contact for SA/Adm/Sup, masked for Acc; delivery address | JSON | one record | role-based | — | b13 | — |
| R-A7 | Legacy order list | `GET /api/admin/orders` | AdminOrders | all admin | **full delivery address + mobile** | JSON | status; 1,000 newest | none | — | admin screens | D-16 (D16-W4-3) |
| R-A8 | Members list / detail | `GET /api/admin/users`, `/users/{id}` | AdminUsers | all admin | **full mobile, e-mail, address**; Aadhaar masked | JSON | status; 1,000 newest | Aadhaar | — | identity_batch4 | D-16 (D16-W4-3) |
| R-A9 | Refund queue | `GET /api/admin/refund-queue` | AdminOperations | all admin | **full mobile** | JSON | paged | none | — | refunds suites | D-16 (D16-W4-3) |
| R-A10 | Payments / referrals / commissions lists | `GET /api/admin/payments`, `/referrals`, `/commissions` | legacy tabs | all admin | payment docs (**session id**), commission amounts | JSON | 1,000 newest | none | — | admin screens | D-16 (D16-W4-2) |
| R-A11 | KYC review list | `GET /api/admin/kyc` | AdminKyc | all admin | PAN, Aadhaar, account, IFSC | JSON | status; 1,000 | **all four masked** | review actions audited | homegenie_batch5, **W4** | plaintext at rest (W2) |
| R-A12 | Withdrawals list | `GET /api/admin/withdrawals` | AdminWithdrawals | all admin | member id, amounts (no bank data) | JSON | status; 1,000 | n/a | actions audited | withdrawal_controls | — |
| R-A13 | Registration requests | `GET /api/admin/registration-requests` | AdminUsers | all admin | name, mobile, e-mail, address; Aadhaar masked; no hash | JSON | 500 | Aadhaar | — | security_batch0 | D-16 (D16-W4-3) |
| R-A14 | Vendor documents | `GET /api/admin/vendors/{id}/documents` | (no screen) | all admin (accounts reads, cannot review) | document links (PAN, identity, bank proof) | JSON | 50 | — | — | vendor_authority, **W4** | D-16 (D16-W4-6) |
| R-A15 | Vendor onboarding view | `GET /api/admin/vendors/{id}/onboarding` | AdminVendorOnboarding | SA, Adm, Sup | PAN, bank (account masked), documents | JSON | one | account | — | vendor_onboarding | — |
| R-A16 | Vendor bank change requests | `GET /api/admin/vendor-change-requests` | Governance | all admin | account masked, IFSC | JSON | 100 | account | decisions audited | governance | — |
| R-A17 | Vendors list | `GET /api/admin/vendors` | AdminVendors | all admin | contact; bank & PAN masked (`_public_vendor`) | JSON | — | bank, PAN | — | vendor suites | — |
| R-A18 | Audit log viewer | `GET /api/admin/audit-logs` | AdminAuditLogs | all admin | actor e-mail, IP, masked old / new values | JSON | 500 newest | values masked at write | DELETE refused + audited | security_batch0, **W4** | D-16 (D16-W4-4) |
| R-B1 | Vendor ledger (admin) | `GET /api/admin/finance/vendors/{id}/ledger` | AdminFinance | all admin | amounts | JSON | paged | n/a | — | finance suites | D-16 (D16-W4-2) |
| R-B2 | Settlements | `GET /api/admin/finance/settlements` | AdminFinance | all admin | amounts, references | JSON | paged | n/a | actions audited | finance suites | D-16 (D16-W4-2) |
| R-B3 | Finance diagnostics | `/api/admin/finance/system-integrity`, `/commission-funding`, `/non-distributor-commissions`, `/negative-wallets` | Finance | SA, Acc | ids, amounts | JSON | — | n/a | — | P01, **W4** | — |
| R-B4 | Payment events inbox | `GET /api/admin/payment-events` | Finance | SA, Acc | gateway refs, amounts | JSON | paged | n/a | retry audited | payment_events_b14 | — |
| R-B5 | Duplicate captures | `GET /api/admin/payments/duplicates` | Finance | SA, Acc | refs, amounts | JSON | — | n/a | actions audited | b14 | — |

### C. Vendor panel (owner always; staff by permission — `vendor_staff.ROUTE_RULES`)
| ID | Capability | Endpoint | Staff permission | Fields | Format | Isolation | Audit | Remaining |
|---|---|---|---|---|---|---|---|---|
| R-C1 | Dashboard, current report, advancement | `/api/vendor/dashboard`, `/reports/current`, `/reports/advancement` | `reports.read` | own sales, products, settlements; buyer ids never leave the server | JSON | query keyed by the account's vendor | — | — |
| R-C2 | Current report CSV | `/api/vendor/reports/current.csv` | `reports.export` | as R-C1 | CSV | same | **W4** export_* | — |
| R-C3 | Ledger, settlements, COD, statement view | `/api/vendor/finance/{summary,ledger,settlements,cod}` | `finance.read` | own amounts; bank masked | JSON | same | — | D-17 (staff & bank) |
| R-C4 | Statement CSV | `/api/vendor/finance/statement.csv` | `finance.export` | own ledger entries | CSV | same; a foreign `vendor_id` parameter is ignored (tested) | **W4** export_* | — |
| R-C5 | Catalogue CSV / import template | `/api/vendor/products/export.csv`, `/import-template.csv` | `products.read` | own products | CSV | same | **W4** export_* (template: no data, not audited) | — |
| R-C6 | Orders, returns, stock history | `/api/vendor/orders(/id)`, `/returns`, `/products/{id}/stock-history` | per perm | ship-to name, mobile, address (needed to deliver) | JSON | own lines only | — | — |
| R-C7 | Analytics CSV | (built in the browser from `/api/vendor/dashboard` trend) | `reports.read` | dates, counts, paise | CSV (client) | — | — | numbers only (no injection surface) |

### D. HomeGenie panel
| ID | Capability | Endpoint | Fields | Notes |
|---|---|---|---|---|
| R-D1 | Metrics, attributed orders | `/api/homegenie/metrics`, `/api/homegenie/orders` (distributor only) | order number, state, amounts; **customer first name only** | tested: no mobile / address |
| R-D2 | Wallet, transactions, commission statement, withdrawals, dashboard, referral, leaderboard | `/api/wallet`, `/wallet/transactions`, `/commissions/statement`, `/withdrawals`, `/dashboard`, `/referral`, `/leaderboard` | own records only (`user_id` of the session) | no export |

### E. Customer panel
| ID | Capability | Endpoint | Notes |
|---|---|---|---|
| R-E1 | Order history / detail | `/api/orders`, `/api/orders/{id}` | own only (tested: another customer's order 404) |
| R-E2 | Returns | `/api/returns` | own only |
| R-E3 | Invoices / statements | — | **none exist** (an invoice number is assigned on payment; there is no downloadable invoice or statement) |

## 3. Sensitive-data classification (field register)
| Cat. | Field (where stored) | Needed in reports? | Masked where it leaves | Roles that see it (today) | Export | Extra audit |
|---|---|---|---|---|---|---|
| 1 | Aadhaar (`users.aadhaar_number`, `registration_requests`, `kyc_records.aadhaar`) | no | `XXXX-XXXX-1234` everywhere | masked to all admin | never | edits audited masked |
| 1 | PAN (`kyc_records.pan`, vendor onboarding / `vendors.pan`) | no | `XXXXX1234X` / last 4 | masked to all admin; onboarding view SA/Adm/Sup | never | edits audited masked |
| 1 | Identity / PAN / bank-proof documents (`vendor_documents.url`) | review only | link (Cloudinary authenticated) | listing: all admin; review: SA, Adm, Sup; onboarding view: SA, Adm, Sup (D16-W4-6) | never (tested: no export carries a link) | review audited |
| 2 | Bank account (`kyc_records`, `vendors`, onboarding, change requests) | no | last 4 | masked to all | never | change requests audited (IFSC only) |
| 2 | IFSC | no | bank code + `*` in KYC list; full in vendor change requests (branch code, public) | all admin | never | — |
| 2 | Payment session id (`payment_transactions.session_id`) | no | **W4:** last 6 in reports; full in legacy payments list (D16-W4-2) | all admin | **W4:** masked | — |
| 2 | Payout / UTR references, settlement references | finance | full | finance; vendors see own | vendor own | actions audited |
| 3 | Mobile (`users`, order `address`) | rarely | **W4:** masked in bulk reports + CSV; order-ops list / export masked; full in record details | see §4 | masked | searched values redacted in export audit |
| 3 | E-mail | rarely | **W4:** masked in bulk reports + CSV | as above | masked | — |
| 3 | Delivery address | delivery only | never exported; shown in order detail / vendor ship-to | admin detail, vendor own orders | never | — |
| 3 | Names (customer, vendor contact, staff) | yes | full (HG sees customer first name only) | role-scoped | yes | — |
| 3 | Actor e-mail / IP in audit records | accountability | full | all admin (D16-W4-4) | no export | — |
| 4 | Order ids / numbers, product data, totals, stock, statuses, commission and settlement summaries | yes | none | role-scoped | yes | export audited |

## 4. Role and permission findings
### 4.1 What the backend enforces (verified; UI matches unless noted)
- Admin gate `require_admin` = super_admin, admin, accounts_admin, support_admin. Finance gates = super_admin + accounts_admin.
  Export rule `admin_order_ops.EXPORT_ROLES` = super_admin, admin, accounts_admin (support refused) — Batch 13, tested.
  Contact rule `CONTACT_ROLES` = super_admin, admin, support_admin (accounts masked) — Batch 13 order detail only.
  Document rules `DOC_REVIEW_ROLES` / onboarding `VIEW_ROLES` = super_admin, admin, support_admin.
- Vendor exports: owner always; staff need `reports.export` / `finance.export` / `products.read` (`vendor_staff.ROUTE_RULES`), and every
  query is keyed by the account's own vendor (a foreign vendor id is ignored — tested).
- HG / customer endpoints use the session's own `user_id` only (tested).
- Audit records: insert-only; `DELETE /api/admin/audit-logs` refused (405) and audited; no route edits them (tested).

### 4.2 Changed by W4 (narrowed to an existing rule — no access added)
| Endpoint | Before | After | Rule applied | Interim until |
|---|---|---|---|---|
| `GET /api/admin/reports/{r}/export` | all 4 admin roles | SA, Adm, Acc | `EXPORT_ROLES` (the only export policy in the code) | D-16 / D16-W4-1 |
Not changed (tried and reverted): limiting `GET /api/admin/vendors/{id}/documents` to the document reviewers — an existing test makes
accounts_admin's read access explicit, so it is an authorised access and became decision D16-W4-6. Support keeps **viewing** every report (masked). Two existing tests exported reports as support_admin; their export calls now use
the super admin with every assertion kept, plus an assertion that support is refused (§10).

### 4.3 Inconsistencies left for D-16 (not changed)
Accounts_admin sees full customer contact / address in `GET /api/admin/users`, `/users/{id}`, `/orders`, `/refund-queue`,
`/registration-requests`, while the newer order-ops detail masks it for the same role; support_admin views finance lists
(`/admin/payments`, `/commissions`, finance ledger / settlements) and the audit log with actor e-mail / IP.

## 5. D-16 — W4 decision table (open; proposed safe behaviour in force where noted)
| # | Exact question | Report / fields | Current roles | Proposed safe behaviour | In force now? | If not decided | Blocks |
|---|---|---|---|---|---|---|---|
| D16-W4-1 | May support_admin export reports (CSV)? | legacy reports ×8; orders CSV | export: SA, Adm, Acc | keep support at view-only (masked) | **yes (W4 interim)** | support cannot download report files | — (local / deploy: no; launch: no) |
| D16-W4-2 | May support_admin see finance lists (payments with session ids, commissions, vendor ledger, settlements)? | R-A10, R-B1, R-B2 | all admin | finance roles only, or mask session ids for support | no — unchanged | support keeps finance read access | public launch (data minimisation) |
| D16-W4-3 | Should accounts_admin see full customer contact / address in member, order, refund-queue and registration lists (the order-ops detail masks it)? | R-A7, R-A8, R-A9, R-A13: mobile, e-mail, address | all admin | apply `CONTACT_ROLES` (mask for accounts) in all lists | no — unchanged | inconsistent exposure of personal data | public launch (DPDP) |
| D16-W4-4 | Who may read the audit log, and should actor e-mail / IP be masked for non-super roles? | R-A18 | all admin | super_admin full; others masked e-mail / IP | no — unchanged | all admins see actors' e-mail and IP | public launch |
| D16-W4-5 | Should new roles (Reports Viewer, Finance, Customer Ops …) get report / export rights, and which? | all reports | four fixed roles | none until defined | — | four roles only | — |
| D16-W4-6 | Should accounts_admin read vendor identity-document links (PAN, identity, bank proof)? It may not review them and may not open the onboarding view, but the documents listing answers it (existing, tested) | `GET /api/admin/vendors/{id}/documents` | document links | all four admin roles read; SA, Adm, Sup review | limit the listing to the document reviewers | no — unchanged | accounts_admin can open identity documents | public launch (identity data) |
| D-17 (existing) | May vendor staff export statements / see settlement bank details? | R-C3, R-C4 | per custom staff permission | bank masked; export by explicit permission only | yes (existing) | unchanged | — |

## 6. Backend changes
- New `backend/exports.py`: `csv_cell`, `csv_text`, `csv_response` (attachment, `Cache-Control: no-store`, `Pragma: no-cache`,
  `X-Export-Id`), `date_bounds`, `check_size` (413 + audited refusal), `audit_export`, `redact`, `mask_mobile`, `mask_email`, `mask_reference`.
- `admin_routes.py` legacy reports: masking (`REPORT_MASKS`), dates, `total` / `truncated` / `masked`, `report_viewed` audit; export
  role rule, size refusal, failure path (500, audited, nothing sent), export audit.
- `admin_order_ops.py`: size refusal, every cell sanitised, failure path, `audit_export` (search text redacted), legacy record kept
  (its free-text search now stored as "(search)").
- `finance_routes.py` vendor statement: `date_bounds` (start ≤ end), size refusal (20,000), every cell sanitised, audit; old sanitiser
  delegates to `csv_cell`.
- `vendor_reports.py` current CSV: every cell sanitised, audit, no-store. `vendor_routes.py` catalogue CSV: size refusal, audit, no-store;
  template no-store. `catalogue.py`: every cell sanitised; `csv_safe` delegates. `governance_routes.py`: comment only (documents listing unchanged, D16-W4-6).

## 7. Masking implementation
Bulk listings mask for every role (`email` → `p•••@domain`, `mobile` → `••••••1234`, `session_id` → last 6), in JSON and CSV alike
(one function, `_mask_report_row`, feeds both). Record-level details keep their existing role rules. Existing masks unchanged: Aadhaar
`XXXX-XXXX-1234`, PAN `XXXXX1234X`, account `XXXX9012`, IFSC `HDFC*******`, vendor bank / PAN last 4.

## 8. CSV / spreadsheet injection
One rule for every cell of every export (`exports.csv_cell`): a text cell whose first character — or first character after leading
spaces — is `=`, `+`, `-`, `@`, tab, CR, LF or the full-width `＝＋－＠` is prefixed with `'`. Not altered: numbers and booleans, and
text that is only a number (`-120.00`, `+919876543210`), so money columns and negative amounts stay exact. Idempotent (an already
quoted value is left alone). Tested with 7 payloads and 8 legitimate values, and end-to-end in all five exports. No spreadsheet
(xlsx) export exists.

## 9. Export audit logging
`audit_logs` record per attempt: `action` `export_success` | `export_refused` | `export_failed`; `entity` `export`; `entity_id` the
report; `user_id`, `user_email`, `ip`, `created_at` (existing fields); `new_value` = export id (= `X-Export-Id` header), report, format,
role, rows, date range, filters (free text redacted: e-mails → `[email]`, digit runs → `•••…NN`), reason (refused / failed), scope
(`vendor:<id>`). Report views: `report_viewed` (role, rows, total, range). Never written: exported values, tokens, passwords, OTPs,
PAN, Aadhaar, account numbers, exception messages (only the exception type). Download completion in the browser cannot be observed by
the server; the export is the download (same response). Retention: none set (P0-05).

## 10. Files and downloads
No export writes a file, a database record or a temporary file; none returns a link; the CSV is built in memory and streamed in the
response to the authorised request (tested: `files` count and temp directory unchanged). There is therefore nothing public, predictable,
expiring or to clean up; an export id cannot retrieve anything (tested). Exports are `no-store`. Failed generation returns an error,
sends no CSV and is audited. Identity documents: vendor uploads are Cloudinary `type: authenticated` (not publicly readable without the
signed link); the link list is readable by every admin role (unchanged; D16-W4-6) and never appears in an export. `/api/files/{path}` serves only sniffed images (products, banners,
profile photos) — unchanged. No storage provider added.

## 11. Verification
**Defects reproduced on the pre-W4 code** (`HEAD` + pre-W4 checkpoint, throwaway DB): support_admin exported the payment report (200);
accounts_admin listed identity-document links (200); full mobile and e-mail in the registrations CSV; payment session id in the report;
a leading-space formula left active; a product-category formula written raw; the vendor statement accepted a start after the end
(200); report and statement exports left no audit record; exports cacheable. Eight fixed; the documents listing for accounts_admin is an
authorised, tested access and is recorded as D16-W4-6 instead.

- **New suite** `test_w4_export_security`: **63 passed** (access control 1-8, masking 9-15, export integrity 16-25, regression 26-30,
  money from paise and report totals 31-32).
- **Existing suites run alongside:** test_admin_order_ops_b13 5, test_vendor_reports 15, test_vendor_staff 11, test_governance_security 16,
  test_vendor_onboarding 46, test_admin_screens_backend 3, test_security_batch0 63 (2 export calls moved to the super admin, +1 support
  refusal assertion), test_staff_permissions_batch12 20, test_identity_batch4 9, test_catalogue_batch3 24, test_vendor_foundation 16,
  test_e2e_vendor_integration 3, test_homegenie_metrics_b13 7, test_vendor_authority 78 — all passed.
- **Full in-process regression** (final code; file hashes unchanged during the run): **74 suites, 1,585 passed, 0 failed, 0 skipped,
  0 errors, 0 not run** (1,522 before W4 + 63 new). An earlier full run (1,584 passed, 1 failed) caught the documents-listing
  restriction breaking `test_vendor_authority`; that change was reverted (D16-W4-6) and the full run repeated.
- **Live-server suites:** **96 passed, 6 skipped** (unchanged).
- **Backend lint:** pyflakes 0 new findings against the baseline.
- **Frontend:** `npm run quality` exit 0 — lint 0 errors / 9 existing warnings, unit tests 7/7, build guards 13/13, production build.
- **Browser** (throwaway API + `hg_w4_ui_test`, 1366 and 390 px): **50/50** — Export shown only to export roles (super / accounts yes,
  support no); contact masked on screen and in the downloaded CSV; sales money exact from paise; an invalid range shows an error, not
  "No data"; a refused order export shows the server's message and downloads nothing; vendor statement download (own rows, formula
  neutralised); no page errors, no sideways scroll; approved design unchanged (screenshots reviewed).

## 12. Files changed (W4)
Backend: `exports.py` (new), `admin_routes.py`, `admin_order_ops.py`, `finance_routes.py`, `vendor_reports.py`, `vendor_routes.py`,
`governance_routes.py` (comment only), `catalogue.py`; tests: `tests/test_w4_export_security.py` (new, 61), `tests/test_security_batch0.py` (two export
calls moved from support_admin to super_admin + a support-refused assertion; nothing removed). Frontend: `src/pages/admin/AdminReports.js`,
`src/components/vendor/kit.js`. Docs: this report, permission matrix, security audit, readiness, matrix, decision register,
remaining-work register, roadmap, engineering log.

## 13. Remaining risks
D16-W4-2…6 (§5); legacy list endpoints return up to 1,000 / 2,000 rows without paging (D3 / W5-R3); legacy report amounts are floats;
dashboard revenue cap (W5-R3); KYC / identity data stored in plaintext (W2, A-01); no retention for audit logs or reports (P0-05).
