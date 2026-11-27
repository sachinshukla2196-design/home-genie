# HOME GENIES — Master roadmap (current, authoritative)

Reconciled 2026-11-24 on the working tree of `main` @ `d31cb74` (Programme 00 documents and Programme 01 work are **uncommitted**:
32 modified + 28 untracked files; checkpoint `~/home-genie-checkpoints/hg-20261124-*-pre-reconciliation-worktree.tar.gz`).
This document supersedes the sequencing sections of `HOME_GENIES_AUTONOMOUS_ROADMAP.md` and the batch sequence in
`HOME_GENIES_MASTER_IMPLEMENTATION_BACKLOG.md`; both stay as historical records.

Companion documents (current): `HOME_GENIES_CURRENT_MODULE_COMPLETION_MATRIX.md` (303 rows) · `HOME_GENIES_OWNER_DECISION_REGISTER.md`
(49 open decisions) · `HOME_GENIES_PROGRAMME_02_READINESS.md` · `HOME_GENIES_REMAINING_WORK_REGISTER.md` (184 open capability items,
defects, verification gaps). Historical evidence: all Programme 00 documents, `PROGRAMME_01_TECHNICAL_SPECIFICATIONS.md`,
`ENGINEERING_LOG_BATCH12_ONWARD.md`.

## 1. The programme sequence (unchanged from Programme 00)
| # | Programme | State | Open matrix items | Gate to start |
|---|---|---|---|---|
| 00 | Master architecture and completion audit | complete (documentation) | — | — |
| 01 | Money and data integrity (B-001…B-006, B-008, B-009) | **engineering complete; uncommitted; not deployed**; production index migration pending (P1-01) | 2 owner actions (E15, O21) | — |
| 02 | Security hardening and identity protection | **in progress**: W8, W6, W5, W4 done and W7 engineering done (2026-11-24; uncommitted; P1-08 presentation open); W1 CSP / frame protection done (2FA waits for P0-06), W2 / W3 (decisions) remain; see readiness document | 25 | Programme 01 committed; P1-01 executed before any Programme 01 deployment; decisions per workstream |
| 03 | Payments and finance governance | **in progress** (2026-11-27, by owner directive): DEF-05, B-022, B-023 and the reconciliation report done locally; uncommitted; not deployed. Remaining items need owner decisions or external integrations (see the Programme 03 report §K) | 28 | P02 identity / masking done; P0-01, P0-02, P0-03, P0-04, D-02, D-03, P1-02…P1-05 |
| 04 | Customer service and notifications | not started | 20 | P03 refund execution (for refund messages); P0-08; L-01 |
| 05 | Operations and observability | not started (parts may run in parallel with 03 / 04) | 31 | P0-09 hosting choices; staging environment |
| 06 | Vendor completeness | not started | 33 | D-04, D-15, D-16, D-17, D-19, P1-06 |
| 07 | Tax and invoicing | not started | 7 | tax adviser: D-09, D-15, L-02; P06 HSN data |
| 08 | Marketing Studio (full scope, §4) | design complete, not built | 23 | B-034 fixed; OD-M1, OD-M3, OD-M6, OD-M8 (MVP); P04 consent store for leads |
| — | Owner / legal items gating launch | open | 7 | D-01, D-05, D-06 (O7), D-12, D-14, L-03 (O20), legal text (O1) |
| — | Unscheduled (not in any programme yet) | owner to prioritise | 8 | promotions / coupons, shipping charges / serviceability, recently-viewed sync, server cart, leaderboard tests, badge UI, HomeGenie performance reports |

**Why the sequence is kept.** The evidence still supports the Programme 00 order: identity and personal-data exposure (P02) are the
largest remaining risk classes after money integrity; finance governance (P03) depends on P02's role and masking work and on owner money
decisions; customer messaging (P04) depends on P03 refund execution; P05 can overlap. **No reordering is proposed.** Two items are flagged
for P02 because of evidence found in this audit, without changing the sequence: the remaining capped stock-recovery loops (DEF-03, P02 W5
or P05) and the undefined-name build check (DEF-02, P02 W8), both reliability guards for everything that follows.
**Update 2026-11-24 (W8):** Programme 02 workstream W8 (frontend static checks and build protection) is implemented and verified;
its repository-tracked browser smoke suite (criterion c) is not and is carried as VG-01. Next per the readiness order: W6.
**Update 2026-11-24 (W4):** reports and exports secured (`HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md`): every report and
export inventoried and classified; bulk reports masked; every export audited; one formula-injection rule; money from paise; oversized
exports refused. No access was added; the role questions (incl. accounts_admin reading vendor identity documents) are recorded
under D-16 (D16-W4-1…6). Uncommitted, not deployed.
**Update 2026-11-24 (W5):** database index, integrity and repair audit done (`HOME_GENIES_DATABASE_INDEX_AND_REPAIR_AUDIT_W5.md`):
40 indexes specified after a static analysis of every database call site (member login and the repair sweeps that run inside
checkout / order views no longer scan all users / orders); three races
closed with unique constraints (double KYC submission, first use of a number sequence, repeated cron delivery); stock-marker pruning
complete and resumable; migration dry run, run records and corrected index verification. The production migration (P1-01) now also
creates these indexes; retention stays with P0-05. Uncommitted, not deployed.
**Update 2026-11-24 (W6):** dependency audit and controlled upgrades done (`HOME_GENIES_DEPENDENCY_AUDIT_W6.md`): production API
dependencies have 0 known advisories (were 4 packages, 1 critical / 14 high); the browser bundle has none; 26 npm findings remain in
the Create React App build toolchain (decision W6-01) and 5 Python findings in unused Emergent-only packages (D-10). One compatibility
shim (PyMongo lazy SRV, `core.py`). Upgrades are uncommitted and not deployed. Next per the readiness order: W7 (P1-08) or W5.
**Update 2026-11-24:** DEF-03 was corrected by a separate corrective package before Programme 02 (evidence in the remaining-work register
§8); it no longer needs a place in P02 W5 or P05. Programme 02 should re-run the full regression on its committed baseline (now 75
in-process suites, 1,587 tests after W7).

**Update 2026-11-27 (Programme 03, first package):** started on the owner's Programme 03 directive (the sequence is unchanged; the
three tasks needed no open decision). DEF-05 Stripe completion integrity, B-022 crash-safe idempotent withdrawal requests, B-023
immutable settlement order / bank snapshots, and a read-only financial reconciliation report across eight money domains
(`HOME_GENIES_PROGRAMME_03_ENGINEERING_REPORT.md`). Five new owner decisions (P03-OD-01 … 05). Matrix row statuses unchanged.
Programme 02's open workstreams (W2, W3, W1 second factor) still wait for their decisions; P1-01 remains the hard production gate and
now also creates the withdrawal indexes. In-process regression is now 79 suites.

**Update 2026-11-27 (Programme 03-B):** the two High audit findings are fixed locally — P03-A01 (customer cancellation of a paid
order) and P03-A02 (late payment on a cancelled order) now record the refund obligation in the same database update as the
transition, with repair sweeps and a reconciliation `liabilities` domain (`HOME_GENIES_PROGRAMME_03B_FINANCIAL_LIABILITY_INTEGRITY_REPORT.md`).
One owner decision added (P03B-OD-01, the existing revival rule). Uncommitted; P1-01 remains the production gate.

## 2. Overall progress (from the current matrix, 303 rows)
| Measure | Value |
|---|---|
| Implemented and verified (backend-verified; no repository UI tests) | 139 / 303 = **45.9 %** (after W8 N10, W4 D37 / M2, W1 L5) |
| Implemented in any form (verified + verification incomplete) | 165 / 303 = 54.5 % |
| Engineering-actionable rows (excluding owner-blocked 36, integration-blocked 20, deprecated 8) | 239; verified 139 = **58.2 %** |
| Partially implemented | 18 |
| Backend complete, frontend incomplete | 15 |
| Not implemented | 41 (13 of them Marketing Studio) |
| Owner decisions open | 49 (26 block launch; P1-01 blocks deploying Programme 01; W6-01 added by W6, non-blocking; W5-01 added by W5, conditional) |
These figures count capabilities, not effort; they rely on historical test runs (Programme 01, 2026-11-23: 71 suites, 1,449 passed;
live 96 passed, 6 skipped) — not re-run for this audit.

## 3. Dependencies (critical path)
```
P1-01 verified backup + production index migration  ──►  (only then) deploy Programme 01
Programme 01 committed ──► P02: W8 static checks → W6 upgrades → W7 Approvals → W5 indexes → W4 exports → W1 2FA/CSP (P0-06) → W2 KYC (A-01, P0-05) → W3 IdP (P0-07)
P02 (roles, masking, identity) ──► P03 (gateway P0-01, two-person scope P0-02, rates P0-03, vendor commission P0-04, D-02, D-03, P1-02…P1-05)
P03 refund execution ──► P04 refund messages; P0-08 provider; L-01 grievance mechanism
P0-09 hosting ──► P05 backups / monitoring / alerting / staging (can overlap P03–P04)
D-04 ──► P06 delivery proof; D-15 ──► P06 HSN ──► P07 invoicing (L-02, D-09)
B-034 + OD-M1/M3/M6/M8 ──► P08 MVP; P04 consent store ──► P08 leads; OD-M4 ──► AI captions; OD-M5 + Meta approval ──► WhatsApp API
```

## 4. Marketing Studio — full retained scope (Programme 08)
Not reduced to a share button. Design: `HOME_GENIE_MARKETING_STUDIO_ARCHITECTURE.md`; matrix module P (P1–P20).
- **Sharing and attribution:** server-issued product links (`/s/<code>`) preserving the existing last-click HomeGenie attribution, link
  id and channel (M1); WhatsApp one-to-one sharing from the member's own WhatsApp (M2) and member-side campaign kits without bulk sending
  (M3); Instagram / Facebook (M4) and other channels (M5); link previews (P18); product pages for link recipients (P19, OD-M1).
- **Content:** AI-assisted captions (M6, OD-M4) and curated hashtags (M7); posters and QR creatives with current, date-stamped prices
  (M8, OD-M3); saved and approved templates (M11, OD-M8); compliance guard-rails — no earnings / recruitment / health-cure claims (P20).
- **Campaigns:** festival and seasonal campaigns (M9), personal campaign calendar with in-app reminders only (M10).
- **Measurement:** first-party click and conversion tracking (M12), channel attribution (M13), marketing performance dashboard (M15) — no
  fabricated reach or impressions.
- **Leads:** consent-based customer enquiries and lead tracking under DPDP (M14).
- **Future integrations:** official WhatsApp Business Platform with opted-in templates only (M16, OD-M5) and Meta Graph API publishing
  for members' own accounts (M17).
- **Rules:** no recruitment-based earnings, no unauthorised bulk messaging, no contact scraping, no spam automation, no fabricated
  analytics, no unofficial APIs, approved products at current prices only, correct attribution preserved.
- **Phases:** MVP (M1, M2, M4, M5, M6 template-only, M7, M8, M11, M12, M13, M15, P18) → phase 2 (M3, M9, M10, M14, M6 with AI) → phase 3
  (M16, M17).

## 5. Programme completion gates (apply to every programme)
1. Every in-scope matrix row reaches "Implemented and verified", or is explicitly recorded as blocked by a named decision / integration.
2. Full in-process regression, live-server suites, frontend build / lint / unit tests and the browser smoke suite are green (results
   recorded with counts and skip reasons).
3. No protected rule changed (financial boundaries, 30 / 10 / 5 and inactive depth logic, attribution, no recruitment earnings,
   maker-checker, refund / settlement authority, data isolation, approved design) — roadmap items that touch them are marked ⚠ in the
   decision register and need the owner's explicit answer.
4. Matrix, remaining-work register, decision register and specification documents updated; historical documents kept.
5. Nothing deployed or migrated in production without the owner; no production verification claimed without evidence.

## 6. Items that could alter protected rules (flagged, not changed)
| Item | Rule at risk | Decision |
|---|---|---|
| Locking or changing commission rates (B-012) | 30 / 10 / 5 percentages | P0-03 |
| Two-person scope for money actions (B-013) | maker-checker | P0-02 |
| COD confirmation authority | refund / payment authority | D-03 |
| Delivery confirmation by admins | payout eligibility | D-04 |
| Closing not-supplied refund cases without refund | commission on undelivered goods | P1-03 |
| New platform roles | money authority | D-16 |
| Marketing attribution changes (legacy links, ineligible codes, platform WhatsApp credit, vendor use) | attribution, financial boundaries | OD-M2, OD-M5, OD-M6, OD-M7 |
| Direct-selling compliance review | business model | L-03 |

## 7. Recommended next action
1. Owner: review and commit the Programme 00 / 01 / reconciliation work on a branch (nothing is committed today).
2. Owner: P1-01 — verified backup, then the production index migration — before any deployment of Programme 01.
3. Owner: answer the Programme 02 decisions that unblock the most work: P1-08 (W7), P0-06 (W1), A-01 + P0-05 (W2), P0-07 (W3), D-16 (W4).
4. Engineering: W8, W6, W5 and W4 are done (uncommitted); next W7 once P1-08 is answered, otherwise the parts of W1 that need no decision (CSP, session hardening).
5. Owner: deploy the W6 dependency upgrades together with Programme 01 (same deployment gate, P1-01); answer W6-01 (replace Create React
   App) and D-10 (retire the Emergent environment) to clear the remaining, non-runtime advisories.
