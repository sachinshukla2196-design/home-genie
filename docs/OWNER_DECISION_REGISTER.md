# HOME GENIES — Owner Decision Register

The authoritative list of business, financial, legal and governance questions that only the owner can settle. Engineering
does not decide these. For each: the question, why it matters, the options, a recommendation, the risks, what is blocked and
what continues. Sources: Batch 11 audit (section J, decisions 1–14) and decisions found since.

Status legend: **OPEN** (no answer) · **INTERIM** (a safe technical default is in place until answered) · **SETTLED** (answered;
recorded with date).

## Settled (for reference)

| # | Decision | Date |
|---|---|---|
| S-1 | Customer prices are GST-inclusive | 2026-11-20 |
| S-2 | HomeGenie commission payable only after delivery + return window; cancelled / returned / refunded / ineligible excluded | 2026-11-20 |
| S-3 | Vendor settlement eligibility after delivery + return window; unresolved returns / refunds / disputes / payment issues hold | 2026-11-20 |
| S-4 | UPI / manual payment confirmation is finance-only; maker-checker; the same person may not create and approve a controlled financial action | 2026-11-20 |
| S-5 | Distinct CUSTOMER role; existing RED users unchanged; no automatic conversion | 2026-11-20 |
| S-6 | Final vendor approval: super admin only | 2026-11-20 |
| S-7 | Depth-based commission inactive; percentages unchanged (30 / 10 / 5) | 2026-11-20 |
| S-8 | KYC changes need an independent second-person verification | 2026-11-20 |
| S-9 | UPI claim expiry 24 h (configurable), atomic stock release | 2026-11-20 |
| S-10 | support_admin never resets member / vendor credentials; admin and super admin may | 2026-11-20 |
| S-11 | Vendor applicants sign in immediately; selling waits for approval (commit f47e3dd) | earlier |

## Open decisions

### D-01 Return window and commission hold duration — **INTERIM**
- **Question:** How many days after delivery may a customer return goods, and must commission / settlement wait exactly that long?
- **Why:** It sets when HomeGenies and vendors are paid and how long customers are protected.
- **Options:** (a) 7 days for both (current setting); (b) a different single number; (c) different windows per category.
- **Recommendation:** (a) 7 days for launch, revisit per category after 3 months of return data.
- **Risks:** Too short exposes the platform to paying out on goods later returned; too long delays vendor cash flow.
- **Affected:** `returns_policy.window_days`, `return_window_days`, eligibility, settlements, commission release.
- **Blocked:** Final launch sign-off only. **Continues:** everything; both values are configurable.

### D-02 May the creator of a settlement also mark it paid? — **INTERIM**
- **Question:** Decision S-4 forbids create = approve. Today the code also forbids approve = pay, but allows create = pay.
- **Options:** (a) keep (two people: creator/payer and approver); (b) three distinct people (creator ≠ approver ≠ payer).
- **Recommendation:** (b) once two finance admins plus the super admin exist; (a) until then.
- **Risks:** (a) one person prepares and releases the money with a single approval between; (b) needs three finance people.
- **Affected:** `finance_routes.settlement_action`. **Blocked:** nothing. **Continues:** all work; current behaviour is (a).

### D-03 COD cash confirmation authority — **INTERIM**
- **Question:** Who may confirm that COD cash was collected (today: `admin` and `super_admin`; `accounts_admin` is refused), and does it need a second person?
- **Why:** COD confirmation records customer money and triggers vendor sales and HomeGenie commission.
- **Options:** (a) keep; (b) finance only (super_admin, accounts_admin) to match S-4; (c) operations records, finance confirms (two-step).
- **Recommendation:** (c), consistent with S-4.
- **Interim safeguards in place (Batch 12):** confirming cash no longer marks vendor goods delivered or starts any payout clock; the expected cash excludes goods a vendor never supplied; short collections go to an independent finance review.
- **Affected:** `cod_rules.CONFIRM_ROLES`, `shop_routes.cod_collected`. **Blocked:** changing the role set. **Continues:** all else.

### D-04 Who may confirm a delivery on a vendor's behalf, and with what proof? — **INTERIM**
- **Question:** Today any admin role (including support) can set an order "delivered". Should anyone other than the vendor's fulfilment record a delivery, and what evidence (courier POD, OTP, photo) is required?
- **Interim (Batch 12):** an admin status change is recorded (`status_set_by_admin`) but starts no payout clock; delivery for payouts comes only from the vendor fulfilment (per vendor). Platform-own goods (no vendor) still use the admin record.
- **Options:** (a) vendor fulfilment only; (b) admin/ops may confirm with mandatory evidence; (c) courier integration only.
- **Recommendation:** (b) with evidence upload (VEN-06), restricted to admin + super_admin.
- **Blocked:** delivery-proof module (VEN-06) design. **Continues:** everything else.

### D-05 Who may change the return window? — **OPEN**
- **Question:** `returns_policy.window_days` is editable by `admin` and `super_admin`. It now decides when money is payable (S-2, S-3). Should changing it be finance + super admin only, maker-checker, or separate from a finance-owned payout hold?
- **Recommendation:** super admin only, audited, with a separate finance-owned minimum payout hold that cannot be lower than the return window.
- **Blocked:** the settings-authorisation change. **Continues:** everything.

### D-06 KYC verifier rules — **OPEN**
- **Question:** May `support_admin` verify KYC? Must the verifier be different from every editor of the current version (today only the last editor is blocked)?
- **Recommendation:** finance or admin only; the verifier must differ from every editor since the last verification.

### D-07 Refund authority — **SETTLED BY S-4 (implemented Batch 12)**
- The admin "Refund" action now records the refund for confirmation; a different finance admin confirms it. No single-person refund path remains. Owner may still decide whether the one-step button should be removed from the UI entirely.

### D-08 Multi-vendor orders with a rejected vendor — **INTERIM (consistent with S-2 / S-3)**
- **Question:** Confirm that a vendor whose part was delivered (and the HomeGenie on the order) are paid even though another vendor on the same order rejected its part.
- **Implemented (Batch 12):** vendor settlement is per vendor; the order's commission becomes eligible when every vendor group is finished (delivered, or ended without supplying) and the refund for the unsupplied part is settled. COD cash and commission exclude unsupplied goods.

### D-09 COD fee on refunds; tax adviser on GST-inclusive vendor value — **OPEN**
- Is the COD handling fee refunded when all goods are returned? (Today: the refund amount is chosen by finance; the fee is never part of vendor or commission shares.)
- Tax adviser confirmation that vendors receive the GST-inclusive line value.

### D-10 Hosting and trusted proxy — **INTERIM**
- **Interim (Batch 12):** the client IP is taken from `X-Forwarded-For` only on Vercel (`VERCEL` set by the platform) or when the direct peer is a private address, and then the rightmost entry; `TRUSTED_PROXY_HOPS` configures longer chains.
- **Owner confirmation needed:** the API is served only through Vercel (no other public entry point).

### D-11 Admin password reset when SMS is unavailable — **OPEN**
- Without SMS the admin who resets a member's password knows the temporary password and the forced change needs no OTP. Accept, or refuse resets until SMS works?
- **Recommendation:** refuse admin resets of member / vendor accounts while SMS is unavailable; use Google recovery or SMS OTP recovery.

### D-12 Existing RED members → customers — **OPEN**
- Report only (`scripts/customer_role_report.py`); no automatic conversion.

### D-13 Updating the 7 live HTTP suites — **INTERIM (Batch 12 instruction authorises updating tests that contradict approved rules)**
- They encode pre-SEC-05 / SEC-11 contracts and need fixtures; updating them to approved rules is engineering work. Documented per change.

### D-14 Launch-gap classifications (Batch 11 section H) — **OPEN** (acceptance)

### D-15 Product tax classification authority — **NEW, OPEN**
- **Question:** Who confirms a product's HSN code and GST rate — the vendor (self-declared), a catalogue admin, or finance?
- **Why:** The GST rate splits the customer price into taxable value and GST on the invoice and sets the commission base.
- **Recommendation:** vendor declares; catalogue admin confirms at product approval; finance can override with audit.
- **Blocked:** making HSN / GST mandatory at approval. **Continues:** product information management with the field optional-but-flagged.

### D-16 Platform admin role expansion — **NEW, OPEN**
- **Question:** The programme proposes new platform roles (Finance Admin, Catalogue Admin, Vendor Operations Admin, Customer Operations Admin, Reports Viewer, custom roles). Which financial authorities (payment confirmation, refunds, settlements, wallet credits) may each hold?
- **Recommendation:** Finance Admin = same money authority as accounts_admin; all others no money authority.
- **Blocked:** granting money permissions to new roles. **Continues:** building the permission engine with those permissions off.

### D-17 Vendor staff with money-adjacent permissions — **NEW, OPEN**
- May vendor staff (e.g. Finance Viewer) see settlement bank details or export statements? Recommendation: view statements yes, bank details masked, export owner-only.

## Batch 13 verification of open decisions (2026-11-23) — nothing below is approved; recommendations unchanged unless stated

| # | What the code does today (verified) | What stays constrained until decided | Consequence of each option |
|---|---|---|---|
| D-01 | `returns_policy.window_days` 7 (validated 0–90, audited `returns_policy_changed`); commission hold `return_window_days` 7; payouts use the longer | nothing blocked; both configurable | shorter = faster payouts, more clawbacks after release; longer = slower vendor / member cash flow |
| D-03 | COD cash confirmation: `admin`, `super_admin` (`cod_rules.CONFIRM_ROLES`), single person; it records payment only — delivery and payout clocks come from vendor fulfilments (Batch 12) | role set unchanged | (a) keep: operations staff confirm money; (b) finance-only: matches S-4, finance must handle every COD; (c) two-step: strongest, two people per COD order |
| D-04 | delivery for payouts = vendor fulfilment `delivered` with a note; admin "delivered" is recorded (`status_set_by_admin`, reason required in the new detail screen) and has **no** payout effect; the new order detail shows each vendor's evidence note | no admin delivery confirmation path; no evidence upload | (a) vendor-only: simplest, relies on vendor honesty; (b) admin with evidence: needs an upload + review flow (VEN-06); (c) courier integration: most reliable, needs a provider contract |
| D-05 | `PUT /api/admin/returns/policy`: `super_admin`, `admin`; validated and audited | unchanged | admin keeps it: operations can shorten payout holds; super-admin only: slower changes, tighter money control |
| D-10 | the repo deploys backend and frontend as two Vercel projects (`backend/vercel.json`, `deploy/ENVIRONMENT.md`); `client_ip` trusts `X-Forwarded-For` only on Vercel or behind a private peer. **Not verifiable from the repo**: whether the API is also reachable elsewhere (e.g. an older Emergent environment referenced by `requirements.txt`) | — | if another public entry exists that is not behind a trusted proxy, rate limits there key on the socket peer (correct) — but if that host injects its own `VERCEL` variable or a private proxy that appends client XFF, limits could be bypassed |
| D-15 | GST rate and HSN are vendor-declared; studio shows a reviewer warning when HSN is missing; no rate invented | HSN not mandatory at approval | vendor-declared only: fastest, risk of wrong invoices; catalogue-admin confirmation (recommended): one review step; finance override: adds an audited correction path |
| D-16 | platform roles: super_admin, admin, accounts_admin, support_admin only; vendor permission engine (Batch 12) is the pattern for platform roles | no new platform roles, no new money authority | each new role needs an explicit money authority answer before it is created |

### New decisions found in Batch 13
- **D-18 Separate billing address on invoices** — OPEN (low). The invoice model has one address per order (the delivery snapshot). A
  separate billing address needs an invoice change and may matter for B2B GST invoices. Recommendation: not before launch unless
  business customers need GST invoices in their own name.
- **D-19 Vendor merchandising requests** — OPEN (low). Vendors cannot request placements today; only admins curate. Recommendation:
  keep admin-only for launch; add a request queue later if vendors ask.

## Programme 01 (2026-11-23) — decisions needed; nothing below is approved
Implemented behaviour is the safest interim in each case and is described in `PROGRAMME_01_TECHNICAL_SPECIFICATIONS.md`.

| ID | Question | Interim behaviour now in code | Options / trade-offs |
|---|---|---|---|
| P1-01 | **Production index migration** (B-004): confirm a verified backup, then run `scripts/vendor_foundation_migrate.py` (dry run, then `--apply`) on production | Programme 01 code refuses every money write (503 `FIN_INDEX_NOT_READY`) until the protective indexes exist | Must happen before this code is deployed; any money duplicates the dry run lists need a finance decision per record |
| P1-02 | **Historical returned-to-origin orders** (B-001): what is owed for vendor groups returned before Programme 01 (no refund case, vendor sale not reversed)? | Listed by `scripts/programme01_reconcile.py` (`historical_rto_without_case`); never changed automatically | (a) open a refund case for each (customer refunded, vendor sale reversed); (b) finance reviews each (some may have been refunded outside the system) |
| P1-03 | **Closing a not-supplied refund case "without refund"** (RTO / vendor rejection): the finance `resolve` action closes it with no clawback of the HomeGenie commission on those goods | Unchanged (owner-approved G3: finance may close a case with a note) | (a) keep; (b) forbid `resolve` without refund for these kinds; (c) allow it but claw the commission back anyway |
| P1-04 | **Unaccepted COD orders** (B-006): should a COD order no seller has accepted expire automatically and return its stock? | Never expired; protected instead by the per-account open-order cap (5) and order rate limits | (a) keep; (b) expire after N days unaccepted (customer notified); (c) require seller acceptance within the dispatch deadline |
| P1-05 | **Order-protection limits** (B-006): 10 orders / 10 min per account, 60 / 10 min per IP, 5 open unpaid / unaccepted orders, 60 s duplicate window, 60 min grace for a payment in progress | Environment settings with these defaults (`deploy/ENVIRONMENT.md`) | Lower = stronger protection, more legitimate refusals; higher = the reverse |
| P1-06 | **Merchandising images** (B-009): only validated uploads (our storage / platform Cloudinary folder) or bundled assets; external links refused | Enforced on create / edit; existing sections untouched until edited | Matches the earlier "storage only" rule; the alternative is an allow-list of image hosts |
| P1-07 | **Admin roles for platform uploads** (B-009): `super_admin` and `admin` (same as merchandising / admin studio); support and accounts refused, including the older product-image upload | In code | Ties to D-16 (role expansion) |
| P1-08 | **Operations page for non-finance admins**: the page loads the finance approvals queue, which answers 403 to `admin` (pre-existing) | Unchanged (display only) | Hide the Approvals tab for non-finance roles, or show a "finance only" note |


---
**Reconciliation 2026-11-24 (pointer; history above unchanged).** Current, authoritative documents: `HOME_GENIES_MASTER_ROADMAP_CURRENT.md`,
`HOME_GENIES_CURRENT_MODULE_COMPLETION_MATRIX.md`, `HOME_GENIES_OWNER_DECISION_REGISTER.md`, `HOME_GENIES_PROGRAMME_02_READINESS.md`,
`HOME_GENIES_REMAINING_WORK_REGISTER.md`.
