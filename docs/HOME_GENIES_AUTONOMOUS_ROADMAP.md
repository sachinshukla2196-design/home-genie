# HOME GENIES — Autonomous roadmap (Batch 12 onward)

Baseline: `main` @ `ce4ab93` (Batches 0–11 committed). All Batch 12 work is **uncommitted** in the working tree.
Recoverable checkpoint: `~/home-genie-checkpoints/hg-20261121-1725-pre-batch12.bundle` (verified `git bundle verify`).
Owner decisions: `docs/OWNER_DECISION_REGISTER.md`. Engineering detail: `docs/ENGINEERING_LOG_BATCH12_ONWARD.md`.

Status labels: COMPLETE AND VERIFIED · IMPLEMENTED, TESTING REQUIRED · PARTIALLY IMPLEMENTED · BACKEND MISSING · FRONTEND MISSING ·
UI ONLY · BLOCKED BY OWNER DECISION · NOT STARTED. "Verified" means automated tests on the isolated test database plus a build;
nothing is production-verified.

## Phase 1 — preservation, audit findings, decisions
| Item | Status | Notes |
|---|---|---|
| Checkpoint outside the tree | COMPLETE AND VERIFIED | git bundle, verified |
| Owner decision register | COMPLETE AND VERIFIED | D-01 … D-17 |
| Roadmap / engineering log | IMPLEMENTED, TESTING REQUIRED | kept current per phase |

## Phase 2 — authentication and identity (Batch 11 C-1, C-2, C-3, C-9, C-16, C-17, L6, L9)
| Item | Status | Test |
|---|---|---|
| OTP attempts race-safe; per-identifier daily budget | COMPLETE AND VERIFIED | `test_batch12_remediation` (C-1 ×3) |
| Client IP not forgeable (Vercel / private proxy / rightmost) | COMPLETE AND VERIFIED | unit test; **D-10 hosting confirmation open** |
| Legacy sign-up no longer verifies an unproven e-mail | COMPLETE AND VERIFIED | C-3 test |
| Google recovery needs a proven e-mail | COMPLETE AND VERIFIED | C-9 tests, `test_forgot_google` |
| Blocked admin = invalid-credentials answer | COMPLETE AND VERIFIED | L6 |
| Only `type: access` tokens with exp/sub are sessions | COMPLETE AND VERIFIED | L9 |
| Vendor applicant proves the mobile when SMS works | COMPLETE AND VERIFIED | C-16 (frontend step added) |
| Vendor accounts only via vendor-lifecycle roles; staff stop with owner | COMPLETE AND VERIFIED | C-17 |

## Phase 3 — refunds, delivery, COD, ledger
| Item | Status | Test |
|---|---|---|
| Admin "Refund" is a maker step; second finance admin confirms | COMPLETE AND VERIFIED | C-4, `test_returns_refunds` |
| fail → retry cannot launder the initiator | COMPLETE AND VERIFIED | L1 |
| Delivery = vendor fulfilment (per vendor); admin status, COD confirm and cancelled orders start no payout clock | COMPLETE AND VERIFIED | C-5 ×4 |
| Multi-vendor partial rejection: delivering vendor payable after the window | COMPLETE AND VERIFIED | C-7 ×2 |
| Sale reversal nets earlier refunds | COMPLETE AND VERIFIED | C-6 |
| COD cash + commission exclude unsupplied goods | COMPLETE AND VERIFIED | C-8 |
| Refund split on goods value, not COD fee | COMPLETE AND VERIFIED | C-11 |
| COD partly refunded still releasable | COMPLETE AND VERIFIED | C-10 |
| Withdrawal re-checks KYC at approve and pay | COMPLETE AND VERIFIED | C-13 |
| Interrupted approvals finish exactly once | COMPLETE AND VERIFIED | C-18, `test_manual_money_controls` |
| Statement legacy amounts, real status labels, basis, reasons | COMPLETE AND VERIFIED | C-21; UI build |
| Delivery / COD **authority** | BLOCKED BY OWNER DECISION | D-03, D-04 (safe holds in place) |
| UPI confirm-vs-expiry leftovers (L2, L3); clawback on taxable base (L5) | NOT STARTED | low severity |

## Phase 4 — product information management
| Item | Status | Test |
|---|---|---|
| Category templates (4 pillars, sub-categories, labelled groups, conditional required fields, review flags) | COMPLETE AND VERIFIED | `test_pim_batch12` |
| Drafts: create / versioned save / resume / discard; one open draft per product | COMPLETE AND VERIFIED | ×3 |
| Section-by-section completeness check; strict submit | COMPLETE AND VERIFIED | ×2 |
| Submission: new product → review; change to approved product → pending revision, live version untouched | COMPLETE AND VERIFIED | ×2 |
| Revision review: diff, approve / reject / request changes, price history, stock never from forms | COMPLETE AND VERIFIED | ×2 |
| Admin product on a vendor's behalf; preparer cannot approve | COMPLETE AND VERIFIED | ×2 |
| Shop never shows pending changes, price history, compliance documents | COMPLETE AND VERIFIED | assertion in revision test |
| Product studio UI (vendor + admin), admin Catalogue page | IMPLEMENTED, TESTING REQUIRED | build OK; browser check pending |
| Tax classification confirmation (HSN / GST) | BLOCKED BY OWNER DECISION | D-15 (warning only) |
| Bulk CSV import onto the new fields (VEN-04), merchandising (badges, collections), scheduled publishing | NOT STARTED | |

## Phase 5 — granular staff permissions
| Item | Status | Test |
|---|---|---|
| Vendor: 18 fine-grained permissions with descriptions and risk levels; original coarse permissions imply the fine ones (no migration, no lock-out) | COMPLETE AND VERIFIED | `test_staff_permissions_batch12` |
| Vendor: 12 least-privilege presets (+2 older ones kept for existing members) | COMPLETE AND VERIFIED | preset × endpoint matrix |
| Fulfilment checked per step (accept / pack / dispatch); studio create vs edit vs submit | COMPLETE AND VERIFIED | step tests, `test_pim_batch12` |
| `/vendor/me` returns effective permissions (menu = server) | COMPLETE AND VERIFIED | `test_vendor_staff` |
| Role builder UI (grouped, described, risk badges, preset preview, high-risk warning) | IMPLEMENTED, TESTING REQUIRED | build OK; browser-checked render |
| Hiding individual buttons a staff member cannot use (server refuses them anyway) | NOT STARTED | |
| Platform admin role expansion | BLOCKED BY OWNER DECISION | D-16 |

## Batch 13 (2026-11-23)
| Item | Status | Test / evidence |
|---|---|---|
| 7A Address book (validation, isolation, default, soft delete, checkout snapshot) | COMPLETE AND VERIFIED | `test_customer_batch13`; browser 1366 + 390 |
| 7B Wishlist (idempotent, live state, price change, no fake alerts) | COMPLETE AND VERIFIED | same; browser |
| 8 HomeGenie dashboard metrics (HG-03) | COMPLETE AND VERIFIED | `test_homegenie_metrics_b13`; browser |
| 9 Admin order operations (ADM-06) list / export / detail | COMPLETE AND VERIFIED | `test_admin_order_ops_b13`; browser |
| 9 Merging the old Orders page (payment-exception workflows) into the new list | PARTIALLY IMPLEMENTED | old page links to the new detail |
| 10 Merchandising | COMPLETE AND VERIFIED (API) · browser-checked | `test_discovery_merch_b13` |
| 11 Search, filters, suggestions, facets, related, recently viewed | COMPLETE AND VERIFIED | same (incl. query plans); browser |
| Seven server-dependent suites | COMPLETE AND VERIFIED (honest results) | 96 passed, 6 skipped with reasons (engineering log) |
| Product studio full browser journey (vendor → admin → shop → order) | COMPLETE AND VERIFIED | 19 / 19 steps |
| Delivery proof (VEN-06) | BLOCKED BY OWNER DECISION | D-04 |
| Platform admin roles | BLOCKED BY OWNER DECISION | D-16 |
| Vendor profile screens (VEN-05), CSV import onto new fields (VEN-04), customer support tickets, notification preferences | NOT STARTED | |

## Latest verification (2026-11-21)
Full regression 57 suites / **1,247 passed, 0 failed**; script tests 2/2 PASS; no new lint warnings vs `ce4ab93`; `git diff --check`
clean; frontend production build compiles; browser check (desktop + 390 px, no console errors, no horizontal overflow): vendor
products, product studio, vendor staff, admin catalogue (revision diff), customer home. Live HTTP suites: not run in Batch 12.

## Next executable task
Phase 7: customer address book and wishlist (backend storage with ownership, tests, screens), then Phase 8 HG-03 dashboard figures.
