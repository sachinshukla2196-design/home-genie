# HOME GENIES — Master Specification

Status: first version, written from repository evidence (code read at HEAD `61eaf96`) and the owner decisions given in the phase prompts.
It is incomplete by design: sections the repository cannot verify are marked rather than guessed.

Labels used for every rule:
**[OWNER]** owner-approved · **[IMPL]** established in the existing implementation · **[ENG]** engineering default · **[OPEN]** unresolved owner decision.

---

## 1. Purpose, stack, roles

- **Purpose [IMPL]:** a marketplace and referral commerce platform. Customers buy; HomeGenies (distributors) earn commission on sales attributed to their share link; vendors supply products and receive proceeds; administrators operate and reconcile.
- **Stack [IMPL]:** React 19 (craco, Tailwind, shadcn-style components) frontend; FastAPI backend; MongoDB (Motor); deployed to Vercel (see `vercel.json`, `VERCEL` env handling in `server.py`).
- **Roles [IMPL]:** `distributor` (HomeGenie), `vendor`, `admin`, `super_admin`, `accounts_admin` (finance), `support_admin`, customer.
- **Product pillars [OWNER]:** Sarees; Fashion Products; Makeup, Beauty & Skincare; Household Essentials. Not to be changed.

## 2. Authority matrix (COD)

| Action | Allowed | Source |
|---|---|---|
| Confirm COD collection | `admin`, `super_admin` only [OWNER] | `cod_rules.CONFIRM_ROLES` |
| Confirm own attributed sale | never, even if also admin [OWNER] | `cod_rules.refuse_own_sale` |
| Resolve a COD discrepancy | `super_admin`, `accounts_admin`; not the reporter; not the attributed HomeGenie [OWNER] | `finance_routes.resolve_cod_discrepancy` |

Authority is checked before the request body is read or any write happens [OWNER].

## 3. Financial Formula and Ledger Invariants

### 3.1 Order economics
- Inputs [IMPL]: `subtotal` (product price before GST), GST, COD fee, `total`. All stored as integer paise (`*_paise`) alongside legacy floats; conversions in `money.py`.
- Distinctions that must stay separate [OWNER]: *marked paid* ≠ *cash collected* ≠ *vendor proceeds posted* ≠ *commission eligible*.
- `payment_status` values for COD [IMPL]: `cod_pending` → `paid` (full evidence) or `cod_discrepancy` (held) → `paid` after review; later `partially_refunded` / `refunded`.

### 3.2 COD collection (OWNER-approved safeguards, implemented)
1. Inputs: `amount_collected` (mandatory, never defaulted), `evidence_type` ∈ {courier_confirmation, provider_confirmation, manual_exception}, `evidence_reference`, optional note. Validation in `cod_rules.CodCollectIn`.
2. Trigger: admin/super_admin POST `/api/orders/{id}/cod-collected`.
3. Held, not paid, when the type is `manual_exception` or the amount differs from the order total. The order becomes `cod_discrepancy` with reporter, time and evidence recorded; no ledger entry, no commission.
4. Paid when a courier/provider reference accompanies an amount equal to the total: conditional claim `cod_pending → paid`, `cod_collection` record written, vendor sale posted, commission distributed once.
5. Evidence is *recorded, not verified*: `verified_by_system` is always `false`; no courier or provider integration exists [IMPL].
6. Idempotency: conditional update on `payment_status`; keys `sale:<order>:<vendor>` (ledger) and `dist:<order>:<type>` (commission).

### 3.3 Discrepancy resolution (OWNER-approved, implemented)
- Required: `resolution` (`confirm_full` | `accept_short`), `reason`, `collected_amount`, `evidence_type` (courier/provider only — a manual exception cannot prove collection), `evidence_reference`.
- Persisted: reason, amount, evidence type and reference, reviewer id, timestamp (`cod_discrepancy.resolution_evidence`, `cod_collection`).
- `confirm_full`: amount must equal the total; commission distributed once.
- `accept_short`: amount must be above zero and below the total; order closed with `cod_collected_paise`, `cod_short_collected`, `cod_shortfall_paise`; vendor sale posted pro rata; **no commission** [OPEN: policy for short collections].
- Guard (defence in depth): `commission.distribute_sale_commissions` and `resume_distribution` refuse any COD order unless `cod_rules.collection_is_proven(order)`.

### 3.4 Refunds
- Ceiling [ENG, derived from the payment record]: order total; for a COD order accepted short, the collected amount (`cod_rules.refundable_total_paise`). Online and fully collected orders are unchanged. Applied in `shop_routes` (`_reserve_refund`, `reverse_order_financials`, `_reverse_commission`), `ledger.post_refund_shares`, `admin_routes.refund_order`, `returns_routes.refundable_paise`.
- Idempotency [IMPL]: refund event keyed by order and reference; reservation is a conditional update on the current refunded amount; clawbacks keyed `clawback:<event>:<commission>`; vendor refund entries keyed `refund:<event>:<vendor>`.
- Refunds for other tender types (customer credits etc.): [OPEN] — no rule found; behaviour unchanged.

### 3.5 HomeGenie commissions
The module docstring in `commission.py` records the rules as "owner-confirmed 21 Jun 2026" [IMPL]:
- Base: product price before GST. Direct 30% to the sale's attributed HomeGenie; Referral 10% to who invited them; Team 5% to who invited that referrer. 1 Point = ₹1.
- Eligibility [IMPL]: order paid; attributed seller approved (`green`) and not the buyer; each upline recipient approved. Credited PENDING, released after the return window (default 7 days when absent).
- Frozen plan per order (`commission_plans`), keys `dist:<order>:<type>`, crash-safe resume.
- **CONFLICT [Phase 3B.0 finding]:** the engine (`commission._freeze_plan`) pays Direct 30% + Referral 10% + Team 5% together, on every eligible sale, to three fixed levels (seller, seller's sponsor, sponsor's sponsor). Team does not cascade beyond that one level. Referral is recurring, not first-purchase-only. Repository sources (the `commission.py` docstring, settings defaults in `core.py`, `test_commission_engine.py`, `test_crash_safe_distribution.py`) all agree on this stacked model. The later directive ("do not stack automatically", "referral on first eligible purchase only", "one non-cascading upline") appears only in the phase prompts, with no repository record. Both cannot be authoritative; the rate and stacking question is an **OPEN** owner decision (see Phase 3B.0 report). Nothing was changed.
- A COD order earns commission only after proven collection (3.3) [OWNER].
- **Own purchase [OWNER, Phase 3B.1, implemented]:** nobody earns any commission on their own purchase, in any role (direct, referral or team). The skipped amount stays unpaid and is not redirected (`commission._freeze_plan`). Commission eligibility is decided at the order's commission event from the recipients' status then (frozen plan); a later activation never replays it.
- **Stacking [OWNER-APPROVED, Phase 3B.1; IMPLEMENTED]:** 30/10/5 as established, paid together on every eligible sale; team is exactly one non-cascading upline. Referral is recurring: no first-purchase rule is approved, and none is implemented (it would need durable per-referral event state, not a runtime count of past orders). The earlier "do not stack" wording is superseded.
- **Short / unproven COD [OWNER-APPROVED; IMPLEMENTED]:** no commission is created (distribution, resume) or released (points cron, manual release) for COD whose full collection is not proven — short, manual-exception, discrepancy-held or legacy without evidence. The cron check was added in Phase 3B.3.

### 3.6 Commission funding and company residual (Phase 3B.3)
**[IMPLEMENTED — detection only]** Every new commission plan stores a `funding` snapshot (`commission.funding_snapshot`), computed when the plan is frozen:
- `company_lines_paise` = merchandise not supplied by a vendor (full pre-GST line value; **cost of goods is not modelled**, so this is an upper bound).
- `vendor_platform_fee_paise` = for each vendor, the platform commission of the approved agreement in force on the order date (`commission_for`); **no approved agreement = 0**, matching `ledger.post_commission`.
- `platform_revenue_paise` = company lines + vendor platform fees; `commission_paise` = the plan's total; `residual_paise` = the difference; `sufficient` = commission ≤ platform revenue.
- GST and the COD fee are excluded, as from the commission base.
- Nothing is clipped, delayed or held because of it: an insufficiently funded plan is logged and listed by `GET /api/admin/finance/commission-funding` (finance roles only). Plans frozen before this existed are reported as `unassessed`, never recalculated.

Economics (all three recipients eligible, 45% of S): company stock residual = 0.55·S − cost of goods (UNKNOWN); vendor stock residual = (p − 0.45)·S + f, break-even p = 45% − f/S; vendor without an approved agreement = −0.45·S.
**[OPEN OWNER DECISION]** Whether an insufficiently funded order should be held, blocked or allowed (and whether vendors must have an approved agreement before their products can sell). The company-residual formula itself remains a proposal; payment-gateway costs, shipping and cost of goods are OUTSIDE THE CURRENT MODEL.

### 3.6a Who may change the formula (Phase 3B.3)
**[IMPLEMENTED]** `PUT /api/admin/settings`: the money-policy fields (commission percentages, return window, point value, withdrawal switch, COD switch and fee, KYC-for-withdrawal, GST %) can be changed only by `super_admin` / `accounts_admin` (the approved finance authority); other admins may still save the remaining settings, and re-sending unchanged money values is allowed. **[ENGINEERING DEFAULT]** validity bounds: each percentage 0–100, the three commission percentages together ≤ 100, return window 0–365 days, point value > 0, fees and badge thresholds ≥ 0. Changes are audited and apply only to plans frozen afterwards.

### 3.7 Activation (Phase 3B.1, implemented)
**[OWNER]** A qualifying activation purchase has a pre-GST merchandise subtotal of at least ₹2,500 (GST, COD fee and other charges never count). The order must be financially valid: online = paid through the normal lifecycle; COD = full collection proven under 3.2/3.3 (held, short, manual-exception or evidence-less COD never qualifies). Activation is never automatic: an `admin` or `super_admin` reviews and approves RED → GREEN. Activation never creates or replays commission.

**[IMPLEMENTED]** `activation_rules.py` (pure), `activation_routes.py`: `GET /api/admin/activations` lists RED distributors with a qualifying purchase of their own; `POST /api/admin/activations/{user_id}/approve {order_id, note}` re-verifies everything server-side, refuses self-approval, and flips the user with one conditional update (`status != green` and no `activation` field), storing `activation` {order, subtotal, evidence summary, approver, time, note} on the user and an `activation_history` row plus an audit entry. Repeats and concurrent approvals return `already`. Admin screen: `/admin/activations`.

**[LIMITATIONS]** Pillar membership of the lines is not checked (order lines do not snapshot a category; the catalogue is limited to the four pillars by design). A later refund does not de-activate. Historical RED users with qualifying old orders appear in the review list and are never activated automatically. Registration approval still creates `red` accounts.

### 3.8 Wallets, Genie Coins, badges
Cash wallets and non-cash points are separate [OWNER]. Badge logic exists (`monthly_badge`, covered by `test_cod_and_badges.py`). Conversion, withdrawal, tax and accounting rules beyond "1 Point = ₹1 where redemption is permitted" are [OPEN].

### 3.9 Manual money controls (Phase 3B.2 / 3B.2.1)
**[OWNER-APPROVED]**
- Manual commission release and manual wallet credit: `accounts_admin` and `super_admin` only. `admin`, `support_admin` and ordinary users have no authority over either.
- Manual commission release before the normal return window has elapsed is **not allowed**; there is no override or "force release".
- Manual wallet credit: no second approver required. Required: exact paisa-safe amount > 0, mandatory reason, mandatory `request_id` idempotency key, duplicate protection, audit trail, notification only when the credit actually occurs. The ₹1 crore ceiling is a technical sanity bound.
- A refund of the activation order does not deactivate an approved HomeGenie.

**[IMPLEMENTED]**
- `PUT /api/admin/commissions/{id}/status` — `release` calls `commission.release_commission_now`, which applies the cron's conditions to one commission (window elapsed, order paid and not cancelled/needs-refund, COD collection proven, no open return/refund case, distribution complete, amount still owed after clawbacks) and moves money only through the recorded release intent (ledger row, once-only wallet move, applied marker). `hold` sets a `manual_hold` flag on a PENDING/PARTIALLY_REVERSED commission without changing its status (so refunds still claw it back and the cron skips it); a hold is not a bypass. Legacy commissions stored with status `HELD` by the earlier route are still blocked by every condition and are clawed back by refunds.
- `POST /api/admin/wallet/credit` — one ledger row (unique `op_key = admin_credit:<request_id>`) and one wallet move per key; reusing a key with different details is refused (409).
- Meanings of "held" in the system: (1) manual commission hold flag (above); (2) the points cron skipping a commission while a return/refund case is open (derived, not stored); (3) a COD order in `cod_discrepancy` or a short collection with `commission_note = short_collection_held` (no commission exists); (4) a withdrawal request in `HELD` (unrelated wallet state).

**[IMPLEMENTED, no rule]** Activation approval needs a qualifying order at approval time; a later refund leaves the user green. No admin endpoint sets a distributor's status; `vendor_routes.admin_vendor_invite` converts an account to the vendor role (separate from activation; the account then leaves the distributor activation workflow).

### 3.10 Who may earn, and negative wallets (Phase 3B.4)
**[OWNER-APPROVED; IMPLEMENTED]**
- Only an active HomeGenie earns NEW commission: `role == "distributor"` AND `status == "green"` (`commission.is_commission_eligible`), for direct, referral and team. Vendors, vendor staff and every admin role earn nothing new, even when green, linked as a sponsor, or holding a share code. A skipped share is not redirected.
- A non-distributor's share code attributes no seller to new orders (`shop_routes` order creation).
- A distributor converted to a vendor stops earning on new orders; earlier frozen commissions are honoured unchanged.
- Historical commissions already credited to non-distributors are honoured as frozen and listed read-only at `GET /api/admin/finance/non-distributor-commissions` (finance roles), marking whether the plan predates the rule (`eligibility_rule` on plans).
- Sponsor/referral links to non-distributors (including admin referral codes) stay as family-tree data; they create no entitlement.
- Negative available balance: allowed when a refund claws back released points; netted automatically by future earnings; new withdrawals are refused while negative; a reserved withdrawal cannot be marked PAID while the wallet's available balance is negative (`409`, reject it or wait). Listed read-only at `GET /api/admin/finance/negative-wallets`. No write-off, interest or external recovery.

**[IMPLEMENTED — preserves earlier behaviour]** The team position is found by walking the sponsor chain through green accounts exactly as before Phase 3B.4. Consequence: a green non-distributor referrer is skipped but the team upline is still paid; a RED referrer still ends the chain, so the team upline is not paid (unchanged since before this phase). **[OPEN OWNER DECISION]** whether a red referrer should still cost the team upline its share.

**[IMPLEMENTED]** Withdrawal pay/reject: the wallet moves first in one conditional update carrying an operation key (`withdrawal_paid:<id>` / `withdrawal_rejected:<id>`); pay and reject of one withdrawal exclude each other; retries finish without moving money twice; ledger rows are written once per key.
**[OWNER-APPROVED; IMPLEMENTED — Phase 3B.4.1]** HomeGenie withdrawal review (`PUT /api/admin/withdrawals/{id}`):
- Only `super_admin` and `accounts_admin` may approve, reject or pay. `admin`, `support_admin`, vendors, vendor staff and distributors are refused (403). The admin screen shows action controls only to those two roles; the backend is the authority.
- Workflow: REQUESTED (`pending`; legacy `under_review` is treated the same) → APPROVED → PAID, or REQUESTED/APPROVED → REJECTED. A requested withdrawal cannot be paid directly.
- Approval records `approved_by` and `approved_at`; one approver is recorded (a concurrent second approval is refused).
- Segregation of duties: the approver cannot pay the same withdrawal; a different finance user must. No emergency bypass exists.
- Paying requires a `payout_reference` supplied by the finance user (3–64 characters: letters, digits, space and `. _ / # : -`, starting with a letter or digit). It is stored on the withdrawal, in the ledger row description and in the audit log, is immutable once paid, and cannot be reused for another withdrawal (`withdrawal_payout_refs`, keyed by the upper-cased reference; a refused payment releases it).
- Before paying, the backend re-checks: approved, not already paid, approver ≠ payer, reference valid and unused, and the wallet is safe (available balance not negative, reservation still in pending), in one conditional wallet update with the operation key.
- Legacy records: PAID and REJECTED withdrawals are terminal and never rewritten; no approval data is invented. A legacy APPROVED record without an approver must be approved again (recording an approver) before it can be paid.

## 4. Known limits and assumptions
- Legacy paid COD orders without `cod_collection` are *unproven*: they earn no new commission and nothing is backfilled [OWNER]. Operator review uses the read-only `scripts/historical_audit.py` against a restored copy, never production directly.
- COD evidence reference format [ENG]: 3–120 characters, starts alphanumeric, then letters, digits, space and `. _ / # : -`. No courier integration or sample exists to justify wider; references beginning with a symbol or containing `+ @ ( )` or non-ASCII are refused.
- Amount cap [ENG]: ₹1 crore technical bound, overridable by `COD_MAX_AMOUNT_RUPEES`; the product has no order-value limit.
- Claim-then-write windows in COD confirm/resolve: commission and vendor sale are recoverable by `resume_distribution` and `reconcile_ledger`; invoice number, audit entry and customer notification have no recovery path.

## 5. Tests that enforce this document
`test_cod_rules.py`, `test_cod_route_logic.py` (fake-DB, not integration), `test_cod_safeguards.py`, `test_finance_ledger.py`, `test_returns_refunds.py`, `test_crash_safe_distribution.py`, `test_stock_recovery.py` (MongoDB integration).

## 6. Not yet covered by this document
Registration/referral rules, KYC/privacy, deployment, per-endpoint API reference, settlements and withdrawals. They exist in the code; they have not been audited into this specification yet.
