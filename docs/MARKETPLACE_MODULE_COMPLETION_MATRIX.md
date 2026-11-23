# HOME GENIES — Marketplace module completion matrix

Labels as in the roadmap. "Verified" = automated tests on the isolated test database + production build + browser check where
noted. Nothing here is production-verified.

## Customer
| Module | Status | Notes |
|---|---|---|
| Registration (customer account type) | COMPLETE AND VERIFIED | Batch 5/8; OTP when SMS works |
| Customer home, no HomeGenie screens | COMPLETE AND VERIFIED | Batch 12 (`MemberOnly`, customer home); browser-checked |
| Product browse, detail, variants, search, filters, suggestions, related, recently viewed | COMPLETE AND VERIFIED | Batch 13 server-side discovery |
| Cart, checkout (GST-inclusive), payment (online / UPI / COD) | COMPLETE AND VERIFIED | |
| Orders, tracking, cancel, return / replacement, refund status | COMPLETE AND VERIFIED | Batch 8 self-service |
| Invoice breakdown | COMPLETE AND VERIFIED | |
| Address book | COMPLETE AND VERIFIED | Batch 13 |
| Wishlist | COMPLETE AND VERIFIED | Batch 13 |
| Notifications | PARTIALLY IMPLEMENTED | in-app list exists |
| Customer support tickets | PARTIALLY IMPLEMENTED | legal/support page; ticket UI for customers not built |

## HomeGenie
| Module | Status | Notes |
|---|---|---|
| KYC | COMPLETE AND VERIFIED | |
| Share links + attribution | COMPLETE AND VERIFIED | |
| Commission statement (basis, real state, hold / reversal reasons) | COMPLETE AND VERIFIED | Batch 12 |
| Commission release / reversal | COMPLETE AND VERIFIED | delivery-anchored (Batch 12) |
| Withdrawals | COMPLETE AND VERIFIED | KYC re-checked at approve / pay |
| Dashboard figures (HG-03) | COMPLETE AND VERIFIED | Batch 13 metrics with definitions |
| Performance reports | NOT STARTED | |

## Vendor
| Module | Status | Notes |
|---|---|---|
| Application (mobile OTP), onboarding, approval (super admin), owner invitation | COMPLETE AND VERIFIED | |
| Product studio: drafts, templates, variants, images, review, revisions | COMPLETE AND VERIFIED | Batch 12 Phase 4; full browser journey vendor → admin → shop in Batch 13 (19/19) |
| Inventory (journaled adjustments, history) | COMPLETE AND VERIFIED | |
| Staff: fine permissions, 12 presets, role builder | COMPLETE AND VERIFIED (API) · IMPLEMENTED, TESTING REQUIRED (UI) | Batch 12 Phase 5 |
| Orders + per-step fulfilment | COMPLETE AND VERIFIED | |
| Returns (respond, inspect, restock) | COMPLETE AND VERIFIED | |
| Ledger, settlements, statement | COMPLETE AND VERIFIED | eligibility per vendor |
| Delivery proof (VEN-06) | BLOCKED BY OWNER DECISION | D-04 |
| Vendor profile screens per status (VEN-05), CSV import on new fields (VEN-04) | NOT STARTED | |
| Vendor dashboard figure review | NOT STARTED | Phase 6 |

## Administration
| Module | Status | Notes |
|---|---|---|
| Users, KYC, Admin Team | COMPLETE AND VERIFIED | |
| Operations (approvals, refunds, returns, settlements, COD, duplicates, bank changes, support) | COMPLETE AND VERIFIED | |
| Catalogue moderation (new products, revisions with diff, products for a vendor) | COMPLETE AND VERIFIED (API) · browser-checked | Batch 12 |
| Order lookup, detail, export (ADM-06) | COMPLETE AND VERIFIED | Batch 13; old Orders page kept for payment-exception actions |
| Merchandising (banners, collections, bestsellers, schedule) | COMPLETE AND VERIFIED | Batch 13 |
| Reports with sensitive-data restrictions | PARTIALLY IMPLEMENTED | existing reports; review pending |
| Category / attribute management screens | NOT STARTED | templates live in code |
| Platform role expansion | BLOCKED BY OWNER DECISION | D-16 |
| Settings authorisation for money-affecting values | BLOCKED BY OWNER DECISION | D-05 |
