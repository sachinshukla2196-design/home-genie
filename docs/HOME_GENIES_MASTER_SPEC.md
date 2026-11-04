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
- **Stacking [OWNER, Phase 3B.1]:** 30/10/5 as established; team is exactly one non-cascading upline. The earlier "do not stack" wording is superseded.

### 3.6 Company residual — PROPOSAL, not approved
`residual = customer revenue ex-GST − agreed vendor proceeds − company-funded eligible commissions − separately identified company costs`.
Distinct from the vendor platform commission (charged via `ledger.post_commission` from the agreed vendor agreement). Not implemented as an accounting report. [OPEN]

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

## 4. Known limits and assumptions
- Legacy paid COD orders without `cod_collection` are *unproven*: they earn no new commission and nothing is backfilled [OWNER]. Operator review uses the read-only `scripts/historical_audit.py` against a restored copy, never production directly.
- COD evidence reference format [ENG]: 3–120 characters, starts alphanumeric, then letters, digits, space and `. _ / # : -`. No courier integration or sample exists to justify wider; references beginning with a symbol or containing `+ @ ( )` or non-ASCII are refused.
- Amount cap [ENG]: ₹1 crore technical bound, overridable by `COD_MAX_AMOUNT_RUPEES`; the product has no order-value limit.
- Claim-then-write windows in COD confirm/resolve: commission and vendor sale are recoverable by `resume_distribution` and `reconcile_ledger`; invoice number, audit entry and customer notification have no recovery path.

## 5. Tests that enforce this document
`test_cod_rules.py`, `test_cod_route_logic.py` (fake-DB, not integration), `test_cod_safeguards.py`, `test_finance_ledger.py`, `test_returns_refunds.py`, `test_crash_safe_distribution.py`, `test_stock_recovery.py` (MongoDB integration).

## 6. Not yet covered by this document
Registration/referral rules, KYC/privacy, deployment, per-endpoint API reference, settlements and withdrawals. They exist in the code; they have not been audited into this specification yet.
