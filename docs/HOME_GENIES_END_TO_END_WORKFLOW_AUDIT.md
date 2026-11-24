# HOME GENIES — End-to-End Workflow Audit

Independent principal-architect review. **Inspection only**: no code, test, config or existing document was changed; no test
suite or server was run. Baseline: `main @ d31cb74` (clean). Every statement is grounded in code read for this audit and cited
as `file:function:line` (backend paths are relative to `backend/`, frontend paths to `frontend/src/`).

Legend: **[V]** verified by reading the code path end to end · **[S]** suspicion / inference that needs a runtime probe or an
owner answer · P0 = must fix before any real money flows · P1 = fix before launch · P2 = fix soon after / significant gap ·
P3 = hygiene.

Approved rules treated as fixed (not re-opened here): commission 30 / 10 / 5 % of the taxable value of attributed sales;
payout only after delivery + return window; maker-checker / two-person rules (S-4, S-8); GST-inclusive shelf prices (S-1).
Findings below are defects *against* those rules or workflow gaps around them.

---

## 0. Ranked findings (workflow view)

| # | Rank | Finding | Evidence |
|---|---|---|---|
| W-1 | **P0** [V] | **Returned-to-origin (RTO) on a prepaid order creates no refund obligation, no sale reversal and no hold.** `returned_to_origin` is not in `RESTOCK_ON`, so `refund_due` is never set and `settle_vendor_rejection` / `post_sale_reversal` never run. The customer cannot cancel (already dispatched) or request a return (not delivered) and there is no customer support channel. In a multi-vendor order the RTO group counts as "finished" (`NOT_SUPPLIED`), the order rolls to delivered and the HomeGenie commission on the undelivered goods is released after the window (violates S-2). | `vendor_routes.py:45` `RESTOCK_ON={"rejected","cancelled"}`; `vendor_update_fulfilment:906-924`; `eligibility.py:42 NOT_SUPPLIED`, `delivered_at:53-76`; `ledger.py:36 SALE_BLOCKING_FULFILMENT`; `returns_routes.customer_cancel:384-386`, `request_return:469-470` |
| W-2 | P1 [V] | **No customer support / ticket system.** Support tickets exist only for vendors. Several customer error paths say "contact support" with nowhere to go (refunded / partly refunded orders, platform-owned line returns, UPI claim expiry, missing delivery date). | `governance_routes.py:292-400` (vendor-only `/vendor/support/tickets`, `/admin/support/tickets`); `returns_routes.customer_cancel:381-382`, `request_return:467`; `stock.expire_upi_claim:448-451`; `docs/KNOWN_GAPS_AND_RISKS.md` "Customer support tickets" |
| W-3 | P1 [V] | **A finance admin alone records a manual payment and marks an order paid** (no maker, no checker) — S-4 names manual payment confirmation as maker-checker. The same is true of UPI confirmation when the claimant is the confirmer (no buyer ≠ confirmer check). | `shop_routes.manual_payment_by_distributor:873-910`, `upi_confirm:918-948` (no `order.user_id != admin.id` check) |
| W-4 | P1 [V] | **Commission percentages (approved 30/10/5) are runtime settings any single finance admin can change** (audited, no second person). | `admin_routes.admin_update_settings:997-1010`, `MONEY_POLICY_SETTINGS:970`; `commission._freeze_plan:149-151` reads them per order |
| W-5 | P1 [V] | **Payment that completes after a crash may never credit commissions** (Stripe, UPI, manual, COD; Razorpay is covered only through its webhook). The order is claimed `paid` first; a crash before `_freeze_plan` leaves no plan, every retry returns early ("already paid"), and no sweep looks for "paid + attributed + no plan". | `shop_routes._process_paid_order:726-761`, `cod_collected:343-366`; `commission.release_due_points:305` (resumes existing plans only); `wallet_reconcile.distribution_audit:83-98` (does not detect it) |
| W-6 | P2 [V] | **Customer "Pay now" on an unpaid order is broken**: it navigates to `/app/checkout`, which needs a non-empty cart and otherwise redirects to products. Re-paying creates a new order (new reservation, attribution already cleared). | `pages/OrderDetail.js:166-168`; `pages/Checkout.js:52`, `:61`, `:103` (`clearSellerRef()` before payment, Batch 11 L13 still open) |
| W-7 | P2 [V] | **Admin "payment exceptions" screen only sees the newest 1,000 orders** (`GET /admin/orders` unpaged, filtered client-side). Older UPI claims / COD-pending orders disappear from the queue. | `pages/admin/AdminOrders.js:58,172-175`; `admin_routes.admin_orders:360-371` (`to_list(1000)`) |
| W-8 | P2 [V] | **Refund case closed "no refund" by one finance admin leaves the linked return case in `refund_pending` for ever**, which holds the order's commission and vendor settlement indefinitely (`has_open_case`). | `returns_routes.refund_case_action:298-303` (resolve), `_return_refunded:233-237` (only on confirm); `financial_ops.has_open_case:29-35` |
| W-9 | P2 [V] | **Delivery (the anchor of every payout clock) is vendor self-attested** with a ≥3-character note; platform-owned goods are "delivered" by any admin role including `support_admin`. (Open owner decision D-04; recorded here as a control gap, not a code defect.) | `vendor_routes.vendor_update_fulfilment:893-894`; `admin_routes.update_order_status:388-414` (`require_admin` incl. support) |
| W-10 | P2 [V] | **Mixed carts (platform-owned + vendor lines):** commission eligibility reads vendor fulfilments only, so platform lines' delivery is never checked; platform lines cannot be returned by the customer. | `eligibility.delivered_at:63-73`; `returns_routes.request_return:465-467` |
| W-11 | P2 [V] | **Vendor settlement can be paid to a vendor approved with missing documents / bank details**, and the settlement records no bank-account snapshot; a single finance admin approves bank-detail changes. | `vendor_onboarding.final_review:653-668` ("approved with missing"); `finance_routes.create_settlement:291-318` (only checks `status in SELLING`); `governance_routes.decide_change:232-258` |
| W-12 | P2 [V] | **KYC (gate for withdrawals) can be verified by `support_admin`**; only the *last* editor is excluded (D-06 open; Batch 11 C-20 unchanged). | `admin_routes.review_kyc:735-772` (`require_admin`) |
| W-13 | P2 [V] | **No customer-facing conversion path from CUSTOMER to HomeGenie** (D-12 open); customer cart and HomeGenie attribution live in shared browser storage. | `admin_routes.activate_registration:1065-1074`; `context/CartContext.js:4,12` (cart not cleared on logout, `context/AuthContext.js:38-39`) |
| W-14 | P3 [V] | Customer return screens have no "ship back" or "withdraw return" action (Batch 11 L18 open) although the APIs exist. | `components/OrderSelfService.js` (calls only `GET /returns`, `POST /orders/{id}/returns`, `POST /orders/{id}/cancel`); `returns_routes.customer_ship_back:581`, `customer_cancel_return:590` |
| W-15 | P3 [V] | Admin finance read-only reports exist in the API but have no screen: commission funding, negative wallets, non-distributor commissions, ledger reconcile, settlement policy, returns policy, commission release/hold. | `finance_routes.py:395,459,472,498,198-214`; `returns_routes.set_policy:82`; `admin_routes.commission_status:605`; no frontend caller found (grep of `pages/admin`, `components`) |
| W-16 | P3 [V] | Admin "commissions" report exports columns that commission documents do not have (`sponsor_distributor_id`, `referred_distributor_id`); audit log view is capped at the latest 500 rows with no paging. | `admin_routes.py:1473`, `admin_audit:1450-1452`; commission doc shape `commission._apply_item:193-200` |

No other P0 was found in the workflows. Financial-engine defects (idempotency, crash recovery, concurrency) are ranked in
`HOME_GENIES_FINANCIAL_ARCHITECTURE_AUDIT.md`.

---

## 1. Customer journey

| # | Step | Route → function | Collections | Notes |
|---|---|---|---|---|
| 1 | Register | `POST /api/auth/register-request/send-otp`, `POST /api/auth/register-request` → `auth_routes:156,170`; account created by `admin_routes.activate_registration:1055` | `registration_requests`, `users`, `wallets`, `referral_relationships` | `account_type` `customer` → `role: customer`, `status: customer`, id prefix `CU`, no sponsor (`auth_routes.py:127,202`; `admin_routes.py:1065-1074`). A wallet is created even for customers. |
| 2 | Login / OTP | `POST /api/auth/login`, `/login-otp/send`, `/login-otp/verify`, Google `/google/session` → `auth_routes:332,645,667,412` | `users`, `otp_sessions`, `login_attempts` | OTP attempt race fixed (Batch 12 C-1, per log). Not re-probed here. |
| 3 | Discovery | `GET /api/catalog/search|facets|suggest|products|products/{id}/related` → `discovery.py:40-143`; legacy `GET /api/products` → `shop_routes.list_products:70` | `products` (text index) | Legacy list is unpaged (`to_list(200)`), both apply `SHOP_VISIBLE` (`shop_routes.py:61`). |
| 4 | Product detail | `GET /api/products/{id}` → `shop_routes.get_product:79` (`P_SHOP` projection) | `products` | `?ref=HG…` captured on any page except `/register` (`lib/sellerRef.js:captureSellerRef`, `App.js:235`, `index.js:19`). |
| 5 | Cart | Frontend only: `context/CartContext.js` (`localStorage["hg_cart"]`) | — | Client prices are display-only; server re-prices (`shop_routes.create_order:167-204`). Quantity not capped client-side (server `le=50`). Cart survives logout (shared-device leak, P3). |
| 6 | Address | `GET/POST/PUT/DELETE /api/addresses…` → `customer_routes:162-211`; snapshot `customer_routes.address_snapshot:155` | `addresses` | Saved address copied into the order (`shop_routes.create_order:150-152`); typed address validated (`AddressIn:100-134`). |
| 7 | Checkout / order | `POST /api/orders` → `shop_routes.create_order:145-279` | `orders`, `stock_txns`, `products.stock_ops`, `counters` | Lines priced from DB, GST split per line (`_taxable_part:51`), one fulfilment per vendor (`:250-258`), stock reserved all-or-nothing (`stock.reserve_for_order:222`), `seller_ref` attributed only to a green distributor ≠ buyer (`:212-218`). Status `payment_pending` (online) or `confirmed` + `cod_pending` (COD). |
| 8a | Pay — Stripe | `POST /api/payments/checkout` → `create_checkout:418`; success page polls `GET /api/payments/status/{sid}` (unauthenticated) `:768`; webhook `POST /api/webhook/stripe` `:786` | `payment_transactions`, `orders` | Both call `_process_paid_order` (see financial audit for missing validation / event record). |
| 8b | Pay — Razorpay | `POST /api/payments/razorpay/order` `:458` → client modal → `POST /api/payments/razorpay/verify` `:486`; webhook `POST /api/webhook/razorpay` → `payment_events.razorpay_webhook:160` | `payment_transactions`, `webhook_events`, `orders` | Verify fetches the payment and checks order id + amount; webhook validates currency + amount and records the event. Dismissing the modal leaves the order unpaid; a retry from the UI creates a **new** order (W-6). |
| 8c | Pay — UPI | `POST /api/payments/upi-claim` `:807` → finance `PUT /api/admin/payments/upi-confirm/{id}` `:918` or `upi-reject` `:985`; expiry `stock.expire_upi_claim:428` (24 h) | `orders`, `payment_references`, `payment_transactions` | Claim never expires by the 15-min rule; expires after 24 h (S-9). Money that arrives after expiry has no recorded refund path (financial audit F-11). |
| 8d | Pay — COD | `POST /api/orders/{id}/cod-collected` → `shop_routes.cod_collected:292` (admin/super_admin) | `orders`, `vendor_ledger`, `commissions` | Mismatch / manual evidence → `cod_discrepancy` → finance review `finance_routes.resolve_cod_discrepancy:404`. |
| 9 | Order view | `GET /api/orders`, `GET /api/orders/{id}` → `shop_routes:376,382` | `orders` | Opportunistically expires overdue unpaid orders. "Pay now" broken (W-6). |
| 10 | Vendor fulfilment | `POST /api/vendor/orders/{id}/fulfilment` → `vendor_routes.vendor_update_fulfilment:871-948` | `orders.fulfilments[]` | `new→accepted→packed→dispatched→delivered`; reject/cancel restock + refund case; RTO has **no** money effect (W-1). |
| 11 | Delivery | Fulfilment `delivered` event (vendor note) → order rolls to `delivered` when all groups finished (`:931-934`) | `orders` | Self-attested (W-9). |
| 12 | Cancel | `POST /api/orders/{id}/cancel` → `returns_routes.customer_cancel:372-430` | `orders`, `refund_cases`, `vendor_ledger`, `stock_txns` | All-`new` groups cancel at once (paid → refund case `cancel:<order>` + sale reversal); otherwise a cancellation *request* to vendor/admin. |
| 13 | Return / replacement | `POST /api/orders/{id}/returns` `:446` → vendor approve/contest/receive/inspect `:633,677` → admin decision `:737` → refund case `_complete_inspection:691` | `return_cases`, `refund_cases`, `orders.return_claimed` | Window from the vendor's delivered event; quantities claimed atomically (`_claim_return_quantities:516`). Platform-owned lines: "contact support" (no support system). |
| 14 | Refund | Refund case `awaiting_review → initiated → confirmed` (`refund_case_action:273`); money engine `shop_routes.reverse_order_financials:598` | `refund_cases`, `order_refunds`, `commissions`, `wallets`, `vendor_ledger` | No gateway refund API: confirmation is manual reconciliation (`verify_provider_refund:266` always false). |
| 15 | Support | **None for customers** | — | W-2. |

**Disconnected transitions (customer)**
- RTO after dispatch on a prepaid order → nothing happens for the customer (W-1, P0).
- `payment_pending` order → "Pay now" → empty checkout (W-6).
- UPI claim expired but money received → finance gets HTTP 409 "refund it", no case is created (financial audit F-11).
- Customer return of a platform-owned line → "contact support" → no channel (W-2, W-10).
- A cancelled order whose UPI claim is still `claimed` stays in the UPI queue (Batch 11 L14; `customer_cancel` does not touch `payment_status`).

---

## 2. HomeGenie journey

| # | Step | Route → function | Collections | Notes |
|---|---|---|---|---|
| 1 | Register | Same as customer with `account_type: homegenie` → `role: distributor`, `status: red`, sponsor link recorded (`admin_routes.activate_registration:1076-1105`) | `users`, `referral_relationships`, `referral_codes` | Recruitment pays nothing (`:1104-1105`). |
| 2 | Activation (RED → GREEN) | `GET/POST /api/admin/activations[/{id}/approve]` → `activation_routes:57,75` | `users.activation`, `activation_history` | Needs an own qualifying paid order; single admin approver; a later refund of that order does not revert GREEN (P3 [S], rule not specified). |
| 3 | KYC | `POST /api/kyc` → `wallet_routes.submit_kyc:113`; review `PUT /api/admin/kyc/{uid}` → `admin_routes.review_kyc:735`; finance edit `admin_kyc_edit:681` | `kyc_records`, `users.kyc_status` | Full PAN / Aadhaar / account in plaintext (R-9). Any admin role verifies (W-12). Version CAS prevents stale verification. |
| 4 | Share link | `pages/ProductDetail.js:38` → `lib/sellerRef.productShareLink`; capture `captureSellerRef` (30-day, last click wins, localStorage) | — | Attribution is client-supplied; the server only checks the code belongs to a green distributor ≠ buyer (`shop_routes.create_order:212-218`). No server-side click record (P3 [S]: any customer can name any HomeGenie). |
| 5 | Attribution | `orders.seller_user_id`, `seller_distributor_id` set at order creation | `orders` | Frozen at order time; eligibility re-checked at plan freeze (`commission._approved:86`). |
| 6 | Purchase → commission | `_process_paid_order:760` / `cod_collected:363` / `resolve_cod_discrepancy:450` / webhook `complete_paid_order:147` → `commission.distribute_sale_commissions:260` → `_freeze_plan:123` → `_apply_item:182` | `commission_plans`, `commissions`, `wallet_transactions`, `wallets` | 30/10/5 % of taxable subtotal (`base_p`, `:133-135`), PENDING, wallet `pending_balance`. Lost on crash for non-Razorpay paths (W-5). |
| 7 | Hold / release | Cron `GET /api/cron/release-points` (daily, `vercel.json`) → `commission.release_due_points:294`; manual `PUT /api/admin/commissions/{id}/status` → `release_commission_now:352` | `commissions.release`, `wallets` | Delivery + max(return window, frozen hold) + no open case (`eligibility.payout_block:79`). Cron scans only the first 5,000 pending rows (financial audit F-9). |
| 8 | Statement | `GET /api/commissions/statement` → `wallet_routes.my_commission_statement:32`; metrics `homegenie_metrics.py` | `commissions`, `orders`, `order_refunds` | Shows held reason per commission. Dashboard shows `settings.return_window_days` only, while the payout rule uses the longer of that and `returns_policy.window_days` (`wallet_routes.dashboard:302` vs `eligibility.py:98`). |
| 9 | Withdrawal | `POST /api/withdrawals` → `wallet_routes.request_withdrawal:157` → finance `PUT /api/admin/withdrawals/{id}` approve → mark_paid (different person) `admin_routes.review_withdrawal:806-940` | `withdrawal_requests`, `withdrawal_payout_refs`, `wallets.applied_ops`, `wallet_transactions` | Approve and pay re-check KYC; pay is atomic with `applied_ops`; request step is not crash-safe (financial audit F-12). Payout destination is not snapshotted on the request. |

**Gaps (HomeGenie):** commission loss after crash (W-5); no click/attribution audit trail (P3 [S]); withdrawal request has no
idempotency key (double submit = two requests, both debit; P3); customer→HomeGenie conversion missing (W-13).

---

## 3. Vendor journey

| # | Step | Route → function | Collections | Notes |
|---|---|---|---|---|
| 1 | Application | `POST /api/vendor-applications/send-otp`, `POST /api/vendor-applications` → `vendor_applications:92,107`; admin `/admin/vendor-applications…` `:164-276` | `vendor_applications`, `users`, `vendors` | Applicant signs in immediately (S-11). |
| 2 | Admin creation / invitation | `POST /api/admin/vendors/create` `vendor_routes:994`; `POST /api/admin/vendors/invite` `:1111`; owner invitation `vendor_invitations:72-123` | `vendors`, `account_invitations` | `require_vendor_admin` (super_admin, admin). |
| 3 | Onboarding | `/api/admin/vendors/{vid}/onboarding/{section}` `vendor_onboarding:520`; documents `:597`; submit `:623`; final review (super admin) `:653` | `vendors.onboarding`, `vendor_documents`, `vendor_status_history` | Super admin may approve with items missing (owner decision); missing list stored (`:660-666`). |
| 4 | KYC / documents | `POST /api/vendor/documents` `governance_routes:110`; review `POST /api/admin/vendor-documents/{id}/review` `:159` | `vendor_documents` | Advisory, not a settlement gate (W-11). |
| 5 | Bank details / change | Profile `PUT /api/vendor/me` `vendor_routes:200`; change `POST /api/vendor/me/bank-change` `governance_routes:189` → finance decision `:232` | `vendor_change_requests`, `vendors` | One finance admin applies the change; no penny-drop verification; settlements do not record the destination (W-11). |
| 6 | Staff | `/api/vendor/staff…` `vendor_staff_routes:59-198`; enforcement `vendor_staff.authorize_staff:185` | `vendor_members` | Default-deny rule table; money read-only for staff (`vendor_staff.py:10,64`). |
| 7 | Product creation | PIM drafts `/api/vendor/pim/drafts…` `pim.py:298-340`; direct `POST /api/vendor/products` `vendor_routes:441` | `product_drafts`, `products` | Revisions keep the approved version live. |
| 8 | Approval | `POST /api/admin/vendor-products/{id}/decision` `vendor_routes:1072`; revisions `pim.py:423` | `products` | Preparer ≠ approver for admin-prepared products (`:1079-1081`). The final `update_one` result is not checked (concurrent decisions both log; P3). |
| 9 | Inventory | `POST /api/vendor/products/{id}/stock` `vendor_routes:524`; reservation `stock.py` | `products.stock`, `stock_movements`, `stock_txns` | Manual adjustments are not idempotent (retry = double adjustment; P3). |
| 10 | Order | Visible only once payment is verified or COD (`VENDOR_VISIBLE_PAYMENT:753`) | `orders` | Notified on payment (`core.notify_order_vendors:501`). |
| 11 | Fulfilment | `vendor_update_fulfilment:871` | `orders.fulfilments` | Per-step staff permission; CAS on current status; RTO gap (W-1). |
| 12 | Return | `/api/vendor/returns…` `returns_routes:599-690`; RTO inspection `vendor_routes.vendor_return_inspection:951` | `return_cases`, `stock_txns` | Vendor cannot reject an eligible claim (contest → admin). RTO inspection restocks only; no refund. |
| 13 | Ledger | `GET /api/vendor/finance/summary|ledger|statement.csv|cod` `finance_routes:53-186` | `vendor_ledger`, `settlements` | Read-only for vendors. |
| 14 | Settlement | Admin `POST /api/admin/finance/settlements` → approve (≠ creator) → mark paid (≠ approver) `finance_routes:291-366` | `settlements`, `vendor_ledger` | Creator = payer allowed (D-02). Settlement is an amount only — not linked to orders or bank details (financial audit F-14). |
| 15 | Commercial terms | `/api/admin/finance/vendors/{id}/agreements`, approve, vendor accept `commercial_routes:12-39` | `vendor_agreements` | Charged from approval even if the vendor never accepted (`commercial_terms.effective_agreement:51-55`, P2 [V]). |
| 16 | Support | `/api/vendor/support/tickets…` `governance_routes:292-400` | `support_tickets` | Exists for vendors only. |

---

## 4. Platform admin journey

| Area | Endpoints (guard) | Screen | Gaps |
|---|---|---|---|
| User governance | `/admin/users…`, block/delete/update (`require_admin`; vendor accounts `VENDOR_ADMIN_ROLES`) `admin_routes:117-1335` | `AdminUsers.js` | — |
| Vendor governance | applications, onboarding, final review (super admin), decisions, change requests | `AdminVendor*.js`, `AdminOperations.js` | bank change single finance approver (W-11) |
| Product moderation | `/admin/vendor-products/{id}/decision`, `/admin/pim/...` | `AdminCatalogue.js`, `AdminProducts.js` | — |
| Order management | `/admin/order-ops/orders|.csv|{id}` (read-only, paged) `admin_order_ops.py`; actions `PUT /admin/orders/{id}/status` (`require_admin`), refund maker `POST /admin/orders/{id}/refund` (finance) | `AdminOrderOps.js`; `/admin/orders/exceptions` → `AdminOrders.js` | exceptions screen limited to newest 1,000 orders (W-7); `support_admin` can change order status, incl. "delivered" on platform goods (W-9) |
| Payment exceptions | UPI confirm/reject, manual payment, duplicates, payment events + retry (`payment_events.py:189,206`) | `AdminOrders.js`, `AdminOperations.js`, `AdminOrderOps.js` | Stripe events are not recorded anywhere (financial audit F-4); manual payment single-person (W-3) |
| Refunds | refund cases `returns_routes:240,273`; refund queue `admin_routes:517` | `AdminOperations.js` | "resolve" without refund single-person + stuck return (W-8) |
| Commission governance | `GET /admin/commissions` (cap 1000), release/hold `PUT /admin/commissions/{id}/status`; funding / non-distributor reports | **no screen** for release/hold or the reports (W-15) | — |
| Settlements | `finance_routes:198-401` | `AdminOperations.js` (vendors, settlements, COD) | settlement policy and reconcile have no screen (W-15) |
| KYC | `admin_routes:638-772` | `AdminKyc.js` | support_admin verifies (W-12) |
| Support | `/admin/support/tickets` (vendor tickets) | `AdminOperations.js` | no customer / HomeGenie tickets (W-2) |
| Reports | `/admin/reports/{report}[/export]` | `AdminReports.js` | wrong commission columns, float sums, `paid`-only sales (W-16) |
| Audit logs | `GET /admin/audit-logs` (latest 500), DELETE refused and itself logged | `AdminAuditLogs.js` | no paging / filter; no tamper evidence (P3) |
| Financial approvals | `/admin/finance/approvals…` | `AdminOperations.js` | checker may approve a credit to their own wallet (Batch 11 L4 open: `financial_approvals.approve:85-115` checks only maker ≠ checker) |

---

## 5. Missing screens / APIs / permissions (consolidated)

| Type | Item | Rank |
|---|---|---|
| Missing API + screen | Customer / HomeGenie support tickets | P1 |
| Missing transition | RTO → refund obligation + sale reversal + commission hold | P0 |
| Missing transition | "Pay now" for an existing unpaid order (resume payment) | P2 |
| Missing transition | Return case closure when its refund case is resolved without refund | P2 |
| Missing screen | Commission release/hold, commission funding, negative wallets, non-distributor commissions, ledger reconcile, finance settlement policy, returns policy | P3 |
| Missing screen | Customer return ship-back / withdraw | P3 |
| Permission | Commission % change without second person | P1 |
| Permission | Manual payment / UPI confirm: no maker-checker, no confirmer ≠ buyer | P1 |
| Permission | COD cash confirmation: single admin; refuses the attributed seller but **not the buyer** (`cod_rules.refuse_own_sale:119-123`) | P2 |
| Permission | KYC verify by support_admin (D-06) | P2 |
| Permission | Returns window (decides payout timing) editable by plain `admin` (D-05, `returns_routes.POLICY_ROLES:35`) | P2 (open decision) |

---

## 6. Doc-vs-code differences (workflow)

| Document | Claim | Code |
|---|---|---|
| `ENGINEERING_LOG_BATCH12_ONWARD.md` | "Everything below is uncommitted" | Committed in `d31cb74`; no Batch 14 section although the commit adds `payment_events.py` and the Orders area. |
| `PRODUCTION_READINESS_CHECKLIST.md` | "Batches 12–13 are uncommitted" | Committed. |
| `KNOWN_GAPS_AND_RISKS.md` | "webhook events linked to orders" is a functional gap | Razorpay events now carry `order_id` / `session_id` (`payment_events.apply:115`); Stripe events are not recorded at all. |
| `KNOWN_GAPS_AND_RISKS.md` R-2 / safe-by-design | Admin "delivered" has no payout effect | True for vendor goods only; for platform-owned orders any admin role (incl. support) starts the clock (`admin_routes.update_order_status:412-414`). |
| `FINANCIAL_STATE_MACHINE.md` | Delivery diagram lists `returned_to_origin`; payout requires "no refund obligation" | RTO creates no obligation, so the rule cannot hold it (W-1). |
| `OWNER_DECISION_REGISTER.md` S-4 | Manual payment confirmation is maker-checker | Single finance admin (W-3). |
| `OWNER_DECISION_REGISTER.md` S-7 / FSM | "Percentages 30/10/5 unchanged" | Mutable runtime settings (W-4). |
| `cron_routes.expire_pending_orders` docstring | 15-minute expiry | Vercel cron runs daily (`vercel.json`); expiry happens only opportunistically on order creation / order views. |
| Batch 11 audit L13, L14, L18, L4, C-12, C-19, C-20 | open items | Still present in code at `d31cb74` (see W-6, W-14, approvals row, W-12; D-03/D-05 open). |

## 7. Not verified in this audit
Runtime behaviour (no server, no tests run); Vercel/Emergent hosting topology; the `emergentintegrations` Stripe package (not in the
repo); real gateway payloads; frontend rendering at 390 px.

---
## Programme 01 changes to the journeys (2026-11-23) — findings above kept as found
- **Customer:** a prepaid vendor group returned to origin now owes the customer that group's value through a refund case (finance
  two-person confirmation). A double-clicked "Place order" returns the same order. Ordering is limited per account (10 / 10 min) and to
  5 open unpaid / unaccepted orders. Abandoned online orders release stock after 15 minutes, or after a 60-minute grace when a gateway
  payment is already on its way.
- **Vendor:** contact details save again for vendors whose state is stored as a code (B-008). Returned-to-origin needs a reason; the
  group's sale is reversed at once (the vendor is not paid for goods the customer never received). One vendor's open refund no longer
  holds another vendor's settlement.
- **Admin / finance:** a refund booking that cannot be made is refused with the reason and the case stays open. Operations queues show
  each record's real status (they all read "Selling role pending" before). Content admins can upload platform images (merchandising,
  admin product studio); support and accounts admins cannot. Merchandising refuses external image links.
- **System:** every payment path finishes through one completion step; interrupted completions, refund obligations, ledger entries
  and releases are repaired by resumable sweeps; money writes stop if their protective indexes are missing.
- Still open: customer support tickets, provider refunds, transactional messages, delivery proof (D-04), payment "Pay now".
