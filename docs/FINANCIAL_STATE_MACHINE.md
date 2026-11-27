# HOME GENIES — Financial state machine (as built, Batch 12)

All amounts are integer paise. Customer money, vendor money (`vendor_ledger`) and HomeGenie commissions (`commissions`,
`wallets`, `wallet_transactions`) are separate collections and code paths.

## Order payment
```
online:  pending ──(gateway capture / webhook, verified amount)──▶ paid
         pending ──upi-claim──▶ claimed ──finance confirm (finance roles)──▶ paid
                                 claimed ──24 h (configurable)──▶ claim_expired (order cancelled, stock released once)
                                 claimed ──finance reject──▶ pending
cod:     cod_pending ──cash confirmed (admin / super_admin: D-03 open)──▶ paid
         cod_pending ──amount ≠ expected or manual evidence──▶ cod_discrepancy ──independent finance review──▶ paid
paid ──refund cases confirmed──▶ partially_refunded ──▶ refunded
```
**Refund obligations at the transition (Programme 03-B).** A cancellation of a paid order writes `refund_due_cancel` in the same
conditional update that cancels it (customer and admin; the claim is pinned to the payment state read) → one `cancel:<order>` refund
case → marker cleared. A payment claimed on an already-cancelled order writes `late_payment_due` (leased) in the same update that marks
it paid → the unchanged rule: expiry-cancelled + stock available → restored (earns); otherwise `needs_refund` → one `late:<order>`
case → marker cleared. Interrupted steps are finished by the obligation sweep / `repair_late_payments`; recording an obligation never
executes a refund.

Expected COD cash = order total − goods a vendor did not supply (C-8). A second gateway capture is flagged as a duplicate
payment (`duplicate_payments[].status: refund_due → refunded`), never applied.

## Delivery (the anchor of every payout clock)
Per vendor fulfilment: `new → accepted → packed → dispatched → delivered` (or `rejected` / `cancelled` / `delivery_failed` →
`returned_to_origin`). Each step needs its staff permission. The order is `delivered` when every vendor group is finished
(delivered, or ended without supplying) and at least one delivered. Admin status changes on vendor goods, COD cash confirmation
and steps on a cancelled order **do not** create a delivery (C-5). Platform-own goods (no vendor fulfilment) use the order record.

## Payout eligibility (`eligibility.payout_block`) — one rule for both money systems
Payable when: not cancelled · payment `paid` / `partially_refunded` · no refund obligation · no duplicate payment awaiting refund ·
delivered (per vendor for settlement, whole order for commission) · the longer of the return window and the commission hold has
passed · no open return / refund case. COD commission additionally needs proven collection (C-10: partly refunded still counts).

## HomeGenie commission
`PENDING ──eligible (cron or finance release)──▶ RELEASED` · refund events claw back proportionally on the goods value (C-11) →
`PARTIALLY_REVERSED` / `REVERSED`. Base = taxable subtotal of supplied goods (C-8). Percentages 30 / 10 / 5 unchanged (S-7).

## Vendor ledger
`SALE_COLLECTED` (+) on payment · `COMMISSION` (−, per approved agreement) · `REFUND` (− share of each refund) · `SALE_REVERSAL`
(− what is still attributed after earlier refunds, C-6) · `ADJUSTMENT` (maker-checker) · `SETTLEMENT_PAID` (−). Entries are
append-only with unique `source_key`; `reconcile_ledger` rebuilds anything missing.

## Settlement
`requested (creator) ──approve (≠ creator)──▶ approved ──mark paid (≠ approver; ≤ eligible money)──▶ paid` or `rejected` /
`failed`. One open settlement per vendor (unique partial index). Creator = payer allowed today (D-02 open).

## Refund case
`awaiting_review ──initiate (maker; recorded in initiators)──▶ initiated ──confirm (finance, not any initiator)──▶ confirmed ──▶ resolved`;
`initiated ──fail──▶ failed ──retry (initiator preserved)──▶ initiated`. The admin "Refund" button is the maker step (C-4).

## Maker-checker (wallet credit, vendor adjustment)
`pending ──approve (finance, ≠ maker; CAS)──▶ approving ──executor (idempotent key)──▶ approved` / `failed`; `pending ──reject──▶
rejected`. An `approving` claim older than 5 minutes can be taken over by another finance admin (never the maker) (C-18).

## Withdrawal
`requested ──approve (finance; KYC verified now)──▶ approved ──mark paid (≠ approver; KYC verified now; reference)──▶ paid`, or
`rejected` (reservation returned) (C-13).
