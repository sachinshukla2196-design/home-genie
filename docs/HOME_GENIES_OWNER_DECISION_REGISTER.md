# HOME GENIES — Consolidated owner decision register (pre-Programme 02)

Consolidated 2026-11-24 from `OWNER_DECISION_REGISTER.md` (D-series, settled S-series; kept unchanged as the historical record),
`HOME_GENIES_MASTER_IMPLEMENTATION_BACKLOG.md` (decisions Programme 00 named without an ID — given **P0-xx** IDs here),
Programme 01 (**P1-01 … P1-08**), one decision found in this reconciliation (**A-01**), `HOME_GENIE_MARKETING_STUDIO_ARCHITECTURE.md` (**OD-M1 … OD-M8**) and the legal assumptions of the
Programme 00 matrix (O18–O20, here **L-01 … L-03**).

**Nothing in this register is approved** unless it is in the "Settled" table with a date. Recommendations are engineering advice,
not decisions. "Interim" describes what the code does today (verified in the working tree on 2026-11-24).

**Blocks** column: **Dev** = local development cannot proceed on that item · **Deploy** = must be answered before the affected code
goes to production · **Launch** = must be answered before public launch · "—" = does not block (a safe default is in place).

## Settled (reference only — evidence: OWNER_DECISION_REGISTER.md)
S-1 GST-inclusive prices (2026-11-20) · S-2 commission payable after delivery + return window · S-3 vendor settlement after delivery +
return window · S-4 payment confirmation finance-only, maker-checker · S-5 distinct CUSTOMER role · S-6 final vendor approval super
admin only · S-7 depth commission inactive, 30 / 10 / 5 unchanged · S-8 KYC second-person verification · S-9 UPI claim expiry 24 h ·
S-10 support_admin never resets member / vendor credentials · S-11 vendor applicants sign in at once, selling waits for approval ·
D-07 refund authority settled by S-4 (implemented Batch 12).

## Protected rules (immutable — no decision below may change them without an explicit owner instruction)
Financial boundaries between customer, vendor, HomeGenie and platform money · commission percentages 30 / 10 / 5 and depth logic
inactive (S-7) · HomeGenie attribution (last valid green seller link, never the buyer) · no recruitment-based earnings · maker-checker
controls · refund and settlement authority (S-4) · vendor / customer data isolation · approved design system.
Decisions that **touch** these rules are marked ⚠ — they must be answered by the owner, never by engineering.

## Unresolved decisions

### Before deploying Programme 01
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| P1-01 | Will the owner take a verified production backup and then run `scripts/vendor_foundation_migrate.py` (dry run, then `--apply`) on production, deciding any duplicate money records it lists? | Programme 01 refuses every money write until the protective unique indexes exist | E15, all payment / refund / ledger / wallet / stock writes | Deploying Programme 01 blocks all payments and orders (by design) | Code fails closed; nothing deployed | **Deploy** |
| W5-01 | (Found in Programme 02 / W5, 2026-11-24; **conditional** — only if the production dry run reports duplicates) For `kyc_records` (more than one KYC record per member), `counters` (two counters for one sequence) and `cron_runs`: which record is authoritative, and — if duplicate invoice / refund / settlement / ticket numbers were already issued — whether customers, vendors or the tax adviser must be told? | The three W5 unique constraints are refused while duplicates exist (the races they close stay open) | B6, N5, E15; invoicing (P07) | Constraint not created; legacy KYC index kept; races remain possible | Refuse-and-report (nothing deleted or merged); `scripts/db_maintenance_report.py` lists the records | P1-01 (partly) |

### Money, payments and finance governance (Programme 03)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| D-01 | How many days may a customer return goods, and must commission / settlement wait exactly that long? | Sets when vendors and HomeGenies are paid | G2, G6, G7, O2 | Payout timing stays at 7 days | 7 days for both, configurable, audited | Launch |
| D-02 | May the creator of a settlement also mark it paid (today allowed), or must creator ≠ approver ≠ payer? | Separation of duties on vendor money ⚠ | D23, G7 | Two-person rule (creator/payer + approver) stays | create ≠ approve ≠ … approve ≠ pay; create = pay allowed | — |
| D-03 | Who may confirm COD cash collection (today admin / super_admin, single person); finance-only or two-step? | COD confirmation triggers vendor sales and commission ⚠ | A17, G11, O4 | Operations staff keep confirming money | Collection records payment only; no payout clock; short collections reviewed by finance | Launch |
| D-05 | Who may change the return window that controls payouts (today admin + super_admin)? | Changing it changes when money is payable ⚠ | D39, O6 | Admin can shorten payout holds | Validated (0–90) and audited | Launch |
| D-08 | Confirm: a delivered vendor and the HomeGenie are paid although another vendor on the same order rejected / returned its part | Multi-vendor fairness ⚠ | G6, G17 | Current per-vendor rule stays (implemented) | Per-vendor settlement; commission after the unsupplied part is refunded | — |
| D-09 | Is the COD fee refunded when all goods are returned? Tax adviser: do vendors receive the GST-inclusive line value? | Refund amounts and vendor shares | G3, G5, O8 | Finance chooses the refund amount case by case | COD fee never in vendor / commission shares | Launch |
| P0-01 | Which card / online gateways at launch: Razorpay only, Razorpay + Stripe, or Stripe only? | Default "Place order" uses Stripe, unconfigured, unreconciled | A14, A15, F5, K1, K2 | Stripe 503 leaves pending orders (expire in 15 min) | UPI / COD work; completion shared (B-003) | Launch |
| P0-02 | Which money actions must need two people: manual payment, UPI confirm, COD confirm, vendor bank change, commission release, closing a refund case without refund? | Single-person money actions remain ⚠ | D12, D17, C8, D14, D21 | Those stay single-person | S-4 roles enforced per action | Launch |
| P0-03 | Commission rates (30/10/5) are editable at runtime by one finance admin — must they be locked (code / super admin + second person)? | Conflicts with S-4 / S-7 ⚠ | D38, G1 | One person can change rates for new orders | Frozen per order (plan) once paid; settings audited | Launch |
| P0-04 | Vendor platform commission when no accepted agreement exists, backdated agreements, and return on refunds | Vendor charges without consent ⚠ | D35, G5 | Commission charged per the agreement in force on the order date; none without agreement | No agreement → no commission entry | Launch |
| P1-02 | For vendor groups returned to origin before Programme 01 (no refund case, sale not reversed): open a refund case for each, or review each? | Customers may be owed money | G17, I5 | They stay listed, untouched | Reported by `scripts/programme01_reconcile.py` | Launch |
| P1-03 | May finance close a returned-to-origin / vendor-rejection refund case without a refund (no commission clawback on undelivered goods)? | Commission could be paid on goods never received ⚠ | D21, G17 | Owner-approved G3 behaviour stays | Finance-only, closing note required | Launch |
| P1-04 | Should a COD order that no seller accepts expire automatically and return its stock? After how long? | Stock locking vs customer experience | A17, F2, E18 | No COD order ever expires | Open-order cap 5 + rate limits | — |
| P1-05 | Confirm the order-protection limits: 10 orders / 10 min per account, 60 / 10 min per IP, 5 open unpaid orders, 60 s duplicate window, 60 min payment grace | Abuse protection vs legitimate shoppers | E18, F2 | Defaults stay | Environment-tunable defaults | Launch |

### Security, identity and privacy (Programme 02)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| P0-05 | Retention and deletion policy for PAN / Aadhaar / bank numbers and personal data (what is kept, how long, what "delete my account" means) | Privacy page promises deletion; data is plaintext | B6, D10, L7, L12, A31 | Encryption can be built; deletion / retention cannot | Masked in responses; stored plaintext | **Launch** (Dev for retention jobs) |
| P0-06 | Admin second factor: authenticator app (TOTP), SMS OTP, or both; recovery procedure (W1 2026-11-24: also the admin session lifetime and whether money actions need a fresh factor; the CSP part of W1 is done and needs no decision) | Admin accounts are password-only | D1, L3 | Admin stays password-only | Lockout, rate limits, 7-day tokens | **Launch** (Dev for 2FA) |
| P0-07 | Identity provider to replace the Emergent demo broker for Google sign-in (first-party Google OAuth client, or remove Google sign-in) | A third-party demo host decides who a user is | A3, A4, K7 | Google sign-in keeps trusting the demo host | Works while the broker is reachable | **Launch** (Dev needs OAuth client credentials) |
| D-06 | May support_admin verify KYC; must the verifier differ from every editor since the last verification? | KYC integrity | D10, O7 | Only the last editor is blocked | Second-person rule (S-8) partially | Launch |
| D-10 | Confirm the API is reachable only through Vercel (no other public entry) | Rate limits / audit IPs trust X-Forwarded-For | E3, L6, O9 | IP-based limits may be bypassable elsewhere | Trusted only on Vercel / private peer | Launch |
| D-11 | Allow admin password resets of member / vendor accounts while SMS is unavailable? | The admin learns the temporary password | D4, O10 | Resets allowed | Forced change at next login | Launch |
| D-16 | New platform roles (Finance, Catalogue, Vendor Ops, Customer Ops, Reports Viewer, custom) and each one's money authority (W4 field / role sub-questions: table "D-16 — W4" below) | Permission model ⚠ | D9, L10, O14 | Four fixed roles | Support role still has some write powers (L10) | — |
| P1-07 | Admin roles for platform uploads: super_admin + admin only (support / accounts refused) | Who changes shop imagery | D30, D31, L11 | Current restriction stays | Enforced | — |
| P1-08 | Operations page for non-finance admins: hide the Approvals tab, or show a "finance only" note? | ~~403 error on every visit by an admin~~ — W7 (2026-11-24) removed every refused request; only the presentation is open | D44 | The "explain" form stays: a short role note, no request (Approvals, Duplicate payments; and by the same rule Benefits, Payment events, Activations, Vendor applications, Team) | Notes in place; switching to "hide" is a menu / tab change only (`lib/roles.js`) | — |
| A-01 | (Found in the 2026-11-24 reconciliation) Where is the encryption key for identity documents held and who may rotate it (hosting secret store, managed KMS, other)? | Field encryption is only as strong as key custody | B6, D10, L7 | Encryption cannot be designed safely | Plaintext storage, masked responses | **Launch** (Dev for workstream 2) |
| W6-01 | (Found in Programme 02 / W6, 2026-11-24) Approve replacing Create React App (react-scripts 5, unmaintained) with a maintained build toolchain (e.g. Vite) as a separate work package — or accept the build-time advisories as documented? | The 13 high / 4 moderate / 9 low npm findings left after W6 are all in the CRA build, dev-server and test toolchain; npm's only fix is leaving CRA (none of them ships in the browser bundle) | N9, N10 (W8 lint / guards are wired through CRA / CRACO), frontend build and tests | Findings stay; exposure limited to developer / CI machines running `npm start` / `npm run build` | Documented in `HOME_GENIES_DEPENDENCY_AUDIT_W6.md` §6; pins and overrides applied where in-range | — |
| L-03 ⚠ | Legal review: do the Consumer Protection (Direct Selling) Rules 2021 apply to the 30 / 10 / 5 sponsor-based commission? (ASSUMPTION) | Compliance of the business model | G1, O20, P20 | Model unreviewed | Commission on sales only, no recruitment earnings | **Launch** |

### Customer service and notifications (Programme 04)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| L-01 | Grievance officer, complaint acknowledgement and tracking under the Consumer Protection (E-Commerce) Rules 2020 (ASSUMPTION — legal confirmation) | Customer complaint channel is missing | A27, J6, O18 | No in-app complaints | Static support page | **Launch** |
| P0-08 | E-mail / SMS provider and sender identity for transactional messages (SMS DLT templates) | Customers get no off-app confirmations | J3, K3, K4 | In-app only | OTP SMS only | Launch |

### Operations and observability (Programme 05)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| P0-09 | Hosting choices for backups / restore drills, error monitoring and uptime / cron alerting | No backup or monitoring evidence in the repo | N6, N7, K11 | No disaster recovery evidence | Startup logs; cron run records | **Launch** |
| D-12 | Convert existing RED members to customers? | Role data | O11 | Report only | `scripts/customer_role_report.py` | — |
| D-13 | Live HTTP suites updated to approved rules (Batch 12 instruction) | Test contracts | N8 | — | **INTERIM** — done in Batch 13 (96 passed, 6 skipped) | — |
| D-14 | Accept the Batch 11 launch-gap classifications | Launch sign-off | O12 | No launch sign-off | — | **Launch** |

### Vendor completeness (Programme 06)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| D-04 | Who may confirm a delivery on a vendor's behalf, and with what proof (courier POD, OTP, photo)? | Delivery starts payout clocks ⚠ | C18, I3, I8, D16, O5 | Delivery proof module cannot be designed | Vendor fulfilment only starts payouts; admin "delivered" has no payout effect | Launch |
| D-17 | May vendor staff see settlement bank details / export statements? | Vendor money-adjacent access | C22, O15 | Grantable to custom roles today | Bank details masked | — |
| D-19 | Vendor merchandising requests (queue) or admin-only? | Scope | C36, O17 | Admin-only | Admin-only | — |
| P1-06 | Merchandising images: validated uploads only (current) or an allow-list of external hosts? | Image integrity on the shop home | D32 | Current rule stays | Validated uploads / bundled assets only | — |

### Tax and invoicing (Programme 07)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim (in code) | Blocks |
|---|---|---|---|---|---|---|
| D-15 | Who confirms a product's HSN and GST rate (vendor, catalogue admin, finance)? | Invoice tax split and commission base | G16, O13 | HSN optional-but-flagged | Studio warning | Launch |
| D-18 | Separate billing address on invoices? | B2B GST invoices | A12, O16 | Delivery address only | Single snapshot | — |
| L-02 | GST tax invoice per seller, e-commerce operator TCS, e-invoicing (ASSUMPTION — tax adviser) | Statutory invoicing | A24, K12, O19 | Browser-printed order page only | Invoice numbering | **Launch** |

### Marketing Studio (Programme 08)
| ID | Exact question | Why it matters | Affected modules | If not decided | Safe interim | Blocks |
|---|---|---|---|---|---|---|
| OD-M1 | Make product / shop pages viewable without login for link recipients? | Conversion of shared links | P19, P1 | Recipients must log in first (ref survives) | ProtectedRoute | Dev (P08 MVP) |
| OD-M2 | Sunset legacy `?ref=HG…` links after a transition? | Attribution continuity ⚠ (attribution rule) | P1, B3 | Legacy links keep working | — | — |
| OD-M3 | Show prices on posters (date-stamped) or "see price at link" only? | Pricing accuracy | P8 | Posters cannot show price | — | Dev (posters) |
| OD-M4 | AI caption provider and budget, or no AI? | Cost, privacy, claims risk | P6 | Templates only | — | Dev (P08 phase 2) |
| OD-M5 | For platform WhatsApp marketing (phase 3), who is credited — platform or the member whose link was used? | Attribution ⚠ | P16 | Phase 3 cannot start | — | Dev (phase 3) |
| OD-M6 | Keep pure last-click (an ineligible newer code overwrites an eligible older one) or ignore ineligible codes? | Attribution ⚠ | P1, B3 | Current rule stays | Last click wins | — |
| OD-M7 | May vendors use the studio for their own products (traffic only, no commission)? | Scope; financial boundary ⚠ | P1–P15 | Members only | — | — |
| OD-M8 | Who approves templates and the claims policy text (two-person admin + super admin proposed)? | Compliance of marketing copy | P11, P20 | Templates cannot go live | — | Dev (templates) |

### D-16 — W4 field- and role-level decisions (Programme 02 / W4, 2026-11-24; D-16 stays OPEN)
D-16 is not approved. W4 granted no access; it narrowed one over-broad access (support_admin report downloads) to the export rule that already exists in
the code (marked "in force (interim)"). Each row is a sub-question of D-16, not a separate decision. Detail: `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md` §5 (sub-questions D16-W4-1…6).

| # | Exact question | Affected report / endpoint | Affected fields | Current authorised roles | Proposed safe behaviour | State | If not decided | Blocks |
|---|---|---|---|---|---|---|---|---|
| D16-W4-1 | May support_admin download report files (CSV)? | legacy reports ×8 (`/api/admin/reports/{r}/export`); orders CSV | all report columns (contact already masked) | export: super_admin, admin, accounts_admin | support views reports (masked) but does not export | **in force (interim)** — the existing `EXPORT_ROLES` rule now also covers report CSVs | support cannot download report files | nothing (local / deployment / launch) |
| D16-W4-2 | May support_admin read finance lists? | `/api/admin/payments`, `/commissions`, `/referrals`, `/admin/finance/vendors/{id}/ledger`, `/admin/finance/settlements` | payment session ids, amounts, commission and settlement records | all four admin roles | finance roles only, or the same lists with session ids masked for support | not changed | support keeps finance read access | public launch (data minimisation) |
| D16-W4-3 | Should accounts_admin see full customer contact and address in the legacy lists, when the order-operations detail masks it for that role? | `/api/admin/users`, `/users/{id}`, `/orders`, `/refund-queue`, `/registration-requests` | mobile, e-mail, delivery address | all four admin roles (full) | apply `CONTACT_ROLES` everywhere (full for super_admin, admin, support_admin; masked for accounts_admin) | not changed | inconsistent personal-data exposure | public launch (DPDP) |
| D16-W4-4 | Who may read the audit log, and should actor e-mail / IP be masked for non-super roles? | `/api/admin/audit-logs` | actor e-mail, IP (values inside records are already masked) | all four admin roles | super_admin full; other roles e-mail / IP masked | not changed | every admin sees actors' e-mail and IP | public launch |
| D16-W4-5 | When new roles are created (Reports Viewer, Finance, Customer Ops …), which reports may each view and export, masked or not? | all reports and exports | all | four fixed roles | no rights until defined | — | only the four roles exist | nothing now |
| D16-W4-6 | Should accounts_admin read vendor identity-document links (PAN, identity, bank proof)? It may not review documents or open the onboarding view, but the documents listing answers it (existing, tested behaviour) | `GET /api/admin/vendors/{id}/documents` | document links | read: all four admin roles; review: super_admin, admin, support_admin | limit the listing to the document reviewers | not changed | accounts_admin can open identity documents | public launch (identity data) |

## Counts
Open / interim decisions listed: **49** (counted from the tables) — D-series **18** (D-01 … D-19 except settled D-07; D-13 is interim
and already actioned), P0-01 … P0-09 (**9**), P1-01 … P1-08 (**8**), OD-M1 … OD-M8 (**8**), L-01 … L-03 (**3**), A-01 (**1**, found in this
reconciliation), W6-01 (**1**, found in Programme 02 / W6, 2026-11-24; does not block launch), W5-01 (**1**, found in Programme 02 /
W5, 2026-11-24; conditional on the production dry run).
- **W6 note (2026-11-24):** whether the Emergent platform environment (`backend/requirements.txt`, private `emergentintegrations`) can be
  retired follows from **D-10** (API reachable only through Vercel); it is not a separate decision. Five unused vulnerable Python packages
  (pillow, python-jose, ecdsa, filelock, oauthlib) remain there until D-10 is answered (remaining-work register W6-R2, W6-R5).
- **26 block public launch**: D-01, D-03, D-04, D-05, D-06, D-09, D-10, D-11, D-14, D-15, P0-01 … P0-09, P1-02, P1-03, P1-05, L-01,
  L-02, L-03, A-01.
- **1 blocks production deployment of Programme 01**: P1-01.
- **Programme 02 cannot finish these parts without an answer**: P0-05 (retention / deletion), P0-06 (admin second factor),
  P0-07 (identity provider), A-01 (key custody); D-06 and D-16 shape the KYC and role scope; P1-08 shapes the Approvals fix.
- **Marketing Studio MVP needs** OD-M1, OD-M3, OD-M6, OD-M8 (phase 2: OD-M4; phase 3: OD-M5).
