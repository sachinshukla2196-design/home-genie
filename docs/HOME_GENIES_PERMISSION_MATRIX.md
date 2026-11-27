# HOME GENIES — Consolidated permission matrix (independent inspection)

Scope: backend guards at git `main @ d31cb74`, compared with the React admin/vendor UI and with `docs/ROLE_PERMISSION_MATRIX.md`.
Static reading only. **[V]** = verified in code (file:function:line), **[S]** = suspicion / not verifiable from the repo.

## 0. How authorisation works

| Mechanism | Code | Behaviour |
|---|---|---|
| Session | `core.get_current_user` (core.py:123) | Bearer JWT (HS256, 7 days, `type: access`, `jti`); user re-read from DB on every request, so **role/blocked changes apply on the next request**; refuses revoked `jti`, tokens older than `password_changed_at`, blocked/suspended/deleted, not-activated accounts; `must_change_password` restricts to 4 paths (core.py:174) |
| Admin gate | `core.require_admin` (core.py:186) | role ∈ {super_admin, admin, accounts_admin, support_admin} |
| Vendor-admin gate | `core.require_vendor_admin` (core.py:197) | super_admin, admin |
| Finance gates | `admin_routes.require_money_admin` (l.382), `finance_routes.require_finance` (l.32), `shop_routes.require_finance_admin` (l.830), `financial_approvals.require_finance_admin` (l.29), `payment_events._finance` (l.183), `returns_routes.FINANCE_ROLES` (l.36) | super_admin, accounts_admin (6 separate copies of the same set) |
| Super-admin gates | `admin_team.require_super_admin` (l.31), `vendor_onboarding._require_super_admin` (l.647), in-handler checks | super_admin only |
| Vendor gates | `vendor_routes.require_vendor_user` (l.66) → `require_approved_vendor` (status ∈ approved/active) / `require_vendor_obligations` (also suspended); `vendor_staff_routes.require_owner_account` (l.25) | owner always; staff via `vendor_staff.authorize_staff` (l.185) path rules |
| HomeGenie status | `users.status` red/green | green needed to withdraw (`wallet_routes.request_withdrawal` l.158), to be an attributed seller (`shop_routes.create_order` seller lookup), to be a sponsor (`auth_routes._find_referrer` l.88) |

Legend: ✓ allowed · ✗ refused by the backend · (own) only own records · **2P** two-person rule enforced in backend · 1P single person.

Roles: **C** customer (`customer`) · **HG** HomeGenie (`distributor`, red/green) · **VO** vendor owner (`vendor`) · **VS** vendor staff
(`vendor_staff`, per permission) · **Sup** support_admin · **Acc** accounts_admin · **Adm** admin · **SA** super_admin.

---

## 1. Money actions

| Action | Endpoint | Backend guard (file:line) | C | HG | VO | VS | Sup | Acc | Adm | SA | Two-person rule | UI gating |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Record refund (formerly one-step) | `POST /api/admin/orders/{id}/refund` | `require_money_admin` admin_routes.py:460 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | Opens/initiates a refund case only; no money moves (l.466-470) | Refund button finance-only (AdminOrders.js:43) |
| Refund case: initiate / retry | `POST /api/admin/refund-cases/{id}/action` `initiate`/`retry` | `require_admin` returns_routes.py:273; no role check for initiate (l.283-291) | ✗ | ✗ | ✗ | ✗ | **✓** | ✓ | ✓ | ✓ | First initiator kept; all initiators recorded (l.290, 350) | "Initiate" shown to all admins (AdminOperations.js:85) |
| Refund case: confirm (money moves, clawback) | same, `confirm` | in-handler: finance role **and** not in `initiators` (l.300-305) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** (initiator ≠ confirmer) | finance-only button |
| Refund case: fail | same, `fail` | any admin (l.292) | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | — | shown to all |
| Refund case: resolve/close (incl. close with **no refund** from `awaiting_review`) | same, `resolve` | finance (l.295-297) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **1P** — a single finance admin can close a refund obligation as `no_refund` | finance-only |
| Customer cancel (paid ⇒ refund case) | `POST /api/orders/{id}/cancel` | owner (returns_routes.py:376) | (own) | (own) | (own) | (own) | — | — | — | — | — | — |
| Vendor decline paid order ⇒ refund case | `POST /api/vendor/orders/{id}/fulfilment` (rejected) | `require_vendor_obligations` + `orders.accept` | ✗ | ✗ | ✓ | `orders.accept` | ✗ | ✗ | ✗ | ✗ | — | — |
| Mark duplicate capture refunded | `POST /api/admin/payments/duplicates/{id}/refunded` | `require_finance_admin` shop_routes.py:967 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **1P** | finance tab |
| Confirm UPI payment | `PUT /api/admin/payments/upi-confirm/{id}` | `require_finance_admin` shop_routes.py:919 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **1P**; UTR unique (`payment_references._id`), exact amount | finance-only |
| Reject UPI claim | `PUT /api/admin/payments/upi-reject/{id}` | same, l.986 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | 1P | finance-only |
| Manual payment by HomeGenie ID | `POST /api/admin/payments/manual` | same, l.874 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **1P** | finance-only |
| Payment events list / retry | `GET /api/admin/payment-events`, `POST …/{id}/retry` | `_finance` payment_events.py:183 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | 1P; only `failed`/stuck `processing` events (l.213) | — |
| COD cash confirmation | `POST /api/orders/{id}/cod-collected` | `cod_rules.require_confirmer_role` (CONFIRM_ROLES l.26) + `refuse_own_sale` | ✗ | ✗ | ✗ | ✗ | ✗ | **✗** | ✓ | ✓ | **1P**; attributed HomeGenie refused; non-total amount or manual exception ⇒ held as discrepancy | **Button shown to every admin role** (AdminOrders.js:245) → 403 for Acc/Sup |
| COD discrepancy resolve | `POST /api/admin/finance/cod-discrepancies/{id}/resolve` | `require_finance` finance_routes.py:405 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** reporter ≠ resolver (l.421) | finance-only |
| Settlement policy activate | `PUT /api/admin/finance/policy` | `require_finance` l.204 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | 1P | — |
| Settlement create | `POST /api/admin/finance/settlements` | `require_finance` l.292 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | one open per vendor (unique partial index) | finance-only |
| Settlement approve | `POST …/settlements/{id}/action` approve | `require_finance` + creator ≠ approver (l.338) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** | finance-only |
| Settlement mark paid | same, mark_paid | approver ≠ payer (l.344); **creator may pay** | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** (creator+approver, or approver+payer); creator = payer allowed (D-02 open) | finance-only |
| Settlement reject / fail | same | `require_finance`, reason ≥5 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | 1P | — |
| Manual wallet credit — request | `POST /api/admin/wallet/credit` | `require_money_admin` admin_routes.py:1347 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | maker | — |
| Vendor ledger adjustment — request | `POST /api/admin/finance/vendors/{id}/adjustments` | `require_finance` finance_routes.py:244 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | maker | — |
| Approve credit / adjustment | `POST /api/admin/finance/approvals/{id}/approve` | `require_finance_admin` + maker ≠ checker (financial_approvals.py:89) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P**. Not checked: checker or maker being the **beneficiary** (any `distributor_id`, incl. admin accounts' own HGADM… ids, admin_routes.apply_wallet_credit l.1362) — Batch 11 L4 still open | finance-only tab |
| Reject credit / adjustment | `…/reject` | finance (l.117) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | maker may reject own request (acts as cancel) | — |
| Commission release-now / hold | `PUT /api/admin/commissions/{id}/status` | `require_money_admin` admin_routes.py:606 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **1P** (release still needs every eligibility condition) | — |
| Withdrawal request | `POST /api/withdrawals` | `distributor` + `green` + KYC verified (wallet_routes.py:158-166) | ✗ | green ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | — | Batch 11 C-14 reported customer UI showing withdraw |
| Withdrawal approve | `PUT /api/admin/withdrawals/{id}` approve | `require_money_admin` l.807 + KYC re-check (l.832) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | approver recorded | finance-only (AdminWithdrawals.js:25) |
| Withdrawal mark paid | same, mark_paid | approver ≠ payer (l.874), unique payout UTR | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** | finance-only |
| Withdrawal reject | same, reject | money admin | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | 1P | finance-only |
| Vendor commercial agreement create / approve | `POST /api/admin/finance/vendors/{id}/agreements`, `…/agreements/{aid}/approve` | `require_finance`; creator ≠ approver (commercial_terms.py:94) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** | finance |
| Vendor benefit proposal decide | `POST /api/admin/benefits/proposals/{id}/decide` | `require_finance`; proposer ≠ decider (vendor_benefits.py:156) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **2P** | finance |
| Money business settings (commission %, return window days, point value, COD on/fee, KYC-for-withdrawal, GST) | `PUT /api/admin/settings` | `require_admin` + in-handler money fields → money admin (admin_routes.py:1002) | ✗ | ✗ | ✗ | ✗ | non-money only | ✓ | non-money only | ✓ | 1P | Save button shown to all (AdminSettings.js); `isSuper` defined but not used for gating |
| Returns policy window (drives payout eligibility) | `PUT /api/admin/returns/policy` | `POLICY_ROLES` = {super_admin, **admin**} (returns_routes.py:35, 83) — error text says "Only a super admin" | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | **✓** | ✓ | 1P | — (KNOWN_GAPS R-4 / Batch 11 C-12 still open) |
| HomeGenie activation (red → green, earning eligibility) | `POST /api/admin/activations/{id}/approve` | `require_approver` (admin, super) activation_routes.py:21 | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | 1P | nav roles match |

## 2. Identity, KYC and contact actions

| Action | Endpoint | Backend guard | C | HG | VO | VS | Sup | Acc | Adm | SA | Two-person | UI |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Submit member KYC (PAN, Aadhaar, bank) | `POST /api/kyc` | `get_current_user` only (wallet_routes.py:113) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | Batch 11 L10: any role |
| Edit member KYC (PAN/bank) | `PUT /api/admin/kyc/{uid}/edit` | `require_money_admin` admin_routes.py:681 | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | editor recorded, status reset to pending | edit finance-only (AdminKyc.js:19) |
| Verify / reject member KYC | `PUT /api/admin/kyc/{uid}` | `require_admin` (l.736); only blocks the **last editor** (l.747) | ✗ | ✗ | ✗ | ✗ | **✓** | ✓ | ✓ | ✓ | 2P only when an admin edited; a member-submitted record is verified by **one** person of **any** admin role | Verify/Reject shown to all (AdminKyc.js:88) |
| Vendor document review (KYC docs) | `POST /api/admin/vendor-documents/{id}/review` | `DOC_REVIEW_ROLES` super/admin/support (governance_routes.py:156) | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | ✓ | 1P | REVIEW_DOC_ROLES matches |
| Vendor adds / removes documents | `POST/DELETE /api/vendor/documents` | `require_vendor_user`, owner only (no staff rule) | ✗ | ✗ | ✓ | ✗ | — | — | — | — | — | — |
| Vendor bank change — request | `POST /api/vendor/me/bank-change` | `require_approved_vendor`; staff have no rule ⇒ refused | ✗ | ✗ | ✓ | ✗ | — | — | — | — | one pending at a time | — |
| Vendor bank change — decide | `POST /api/admin/vendor-change-requests/{id}/decision` | `require_admin` + super/accounts in handler (governance_routes.py:234) | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✗ | ✓ | **1P**; no confirmation from the vendor's trusted contact; applied straight to `vendors` (l.249) | finance-only buttons |
| Member profile edit incl. **Aadhaar** | `PUT /api/admin/users/{id}` | `require_admin` + `_guard_target` (admin targets: SA only) (l.1271) | ✗ | ✗ | ✗ | ✗ | ✓ (members, vendors) | ✓ | ✓ | ✓ | 1P; `_guard_vendor_account` **not** applied here | — |
| Contact change (mobile/e-mail) — propose | same endpoint (mobile/email fields) → `contact_change.propose_contact_change` | as above | — | — | — | — | ✓ | ✓ | ✓ | ✓ | live contact unchanged until confirmed | — |
| Contact change — holder confirm | `POST /api/auth/contact-change/confirm` | OTP to **current** mobile (contact_change.py:188) | (own) | (own) | (own) | (own) | — | — | — | — | holder + proposer = **2P** | — |
| Contact change — recovery approve | `POST /api/admin/contact-changes/{id}/recovery-approve` | SA only and ≠ proposer (l.231-240) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | **2P** (proposer + SA). [S] SA can create a helper admin to propose (Batch 11 E) | SA-only button |
| Contact change — cancel | `POST /api/admin/contact-changes/{id}/cancel` | any admin | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | — | — |
| Self mobile change | `PUT /api/auth/change-mobile/send|verify` | OTP to current **and** new mobile (auth_routes.py:772-815) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | possession of both | — |
| Admin password reset of another account | `POST /api/admin/users/{id}/reset-password` | `require_admin` + SA/Adm only (l.1408) + `_guard_target` (SA protected; admin targets SA only; no self) | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | forced change at next login; OTP to trusted mobile **only when SMS is configured** (governance_routes.forced_change_needs_otp l.420) — otherwise the resetting admin can take over the account | canReset matches (AdminUsers.js:31) |
| Self-service reset | `POST /api/auth/forgot/otp/*`, `/forgot/google*` | OTP to registered mobile / verified Google e-mail; admins excluded | ✓ | ✓ | ✓ | ✓ | ✗ | ✗ | ✗ | ✗ | — | — |
| Reset-request queue view / dismiss | `GET /api/admin/password-reset-requests`, `POST …/dismiss` | `require_admin` | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | — | — |
| Change own password | `PUT /api/auth/change-password` | session + current password (+OTP if forced) (governance_routes.py:438) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | admin passwords need 14+ chars mixed | — |
| Block / unblock account | `PUT /api/admin/users/{id}/block` | `require_admin` + `_guard_target` + `_guard_vendor_account` (l.1191) | ✗ | ✗ | ✗ | ✗ | members only | members only | members + vendors | all except SA | 1P | — |
| Deactivate ("delete") account | `DELETE /api/admin/users/{id}` | `require_admin`; admins never; vendors only Adm/SA (l.1237) | ✗ | ✗ | ✗ | ✗ | **members ✓** | **members ✓** | ✓ | ✓ | 1P, no anonymisation | — |
| Approve / reject registration request | `POST /api/admin/registration-requests/{id}/approve|reject` | `require_admin` | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 1P | — |
| Referral codes create / delete | `POST/DELETE /api/admin/referral-codes` | `require_admin` | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | ✓ | ✓ | 1P | — |

## 3. Admin team

| Action | Endpoint | Guard | Sup | Acc | Adm | SA | Notes |
|---|---|---|---|---|---|---|---|
| List / create admin | `GET/POST /api/admin/team` | `require_super_admin` admin_team.py:31 | ✗ | ✗ | ✗ | ✓ | creates admin/accounts_admin/support_admin only; never super_admin; temporary password + forced change |
| Change admin role | `PUT /api/admin/team/{id}/role` | same; not self; only among TEAM_ROLES (l.94-110) | ✗ | ✗ | ✗ | ✓ | takes effect next request (role read from DB); no session revocation needed |
| Disable admin | `PUT /api/admin/users/{id}/block` | `_guard_target`: admin targets ⇒ SA only | ✗ | ✗ | ✗ | ✓ | SA itself cannot be blocked/reset |
| Super-admin credential | environment only (`server._init_db` l.284-345) | — | — | — | — | env | rotation via `ADMIN_PASSWORD_HASH` |

**Two-person rules weakened by the super admin [V+S]:** SA can create a second finance admin (admin_team.create_admin) with a password
SA chose; when SMS is not configured the forced change needs no OTP (governance_routes.py:420-424), so one person can act as both maker
and checker (wallet credits, adjustments, settlements, refunds, withdrawals). Mitigation is procedural only.

## 4. Vendor lifecycle and catalogue

| Action | Endpoint | Guard | Sup | Acc | Adm | SA | VO | VS | Two-person |
|---|---|---|---|---|---|---|---|---|---|
| Create vendor (admin-run onboarding) | `POST /api/admin/vendors/create` | `require_vendor_admin` vendor_routes.py:995 | ✗ | ✗ | ✓ | ✓ | — | — | — |
| View applications / onboarding | `GET /api/admin/vendor-applications*`, `/admin/vendors/{id}/onboarding` | `VIEW_ROLES` super/admin/support | ✓ | ✗ | ✓ | ✓ | — | — | — |
| Edit application / onboarding sections / documents | `PUT …/vendor-applications/{id}`, `PUT /admin/vendors/{id}/onboarding/{section}` | `require_vendor_admin` | ✗ | ✗ | ✓ | ✓ | — | — | — |
| Submit for final approval | `POST /api/admin/vendors/{id}/submit-for-approval` | `require_vendor_admin` (vendor_onboarding.py:624) | ✗ | ✗ | ✓ | ✓ | — | — | — |
| **Final approve / reject / request changes / reopen** | `POST /api/admin/vendors/{id}/final-review` | `_require_super_admin` (l.647) + `vendor_lifecycle.TRANSITIONS` | ✗ | ✗ | ✗ | ✓ | — | — | **1P**: SA may approve straight from `onboarding` (owner decision, transitions l.33) — no preparer ≠ approver rule; checklist advisory |
| Owner invitation issue / revoke | `POST /api/admin/vendors/{id}/owner-invitation(/revoke)`, `/owner-access` | vendor admin / SA | ✗ | ✗ | ✓ | ✓ | — | — | Token is **returned to the admin** when e-mail is not configured (vendor_invitations.issue l.53); the admin can then set the owner's password [S: takeover by admin] |
| Legacy decisions: start_review, request_documents, request_changes, suspend | `POST /api/admin/vendors/{id}/decision` | `require_vendor_admin` (l.1032) | ✗ | ✗ | ✓ | ✓ | — | — | 1P |
| Legacy decisions: approve, reject, reinstate, activate | same | `SUPER_ADMIN_ACTIONS` (vendor_lifecycle.py:63) | ✗ | ✗ | ✗ | ✓ | — | — | 1P |
| Vendor product decision (new product) | `POST /api/admin/vendor-products/{id}/decision` | `require_vendor_admin`; preparer ≠ approver (l.1079) | ✗ | ✗ | ✓ | ✓ | — | — | 2P only for admin-prepared products |
| PIM revision decision (change to live product, incl. price) | `POST /api/admin/pim/products/{id}/revision/decision` | `require_vendor_admin`; submitter ≠ approver (pim.py:434) | ✗ | ✗ | ✓ | ✓ | — | — | 2P only for admin-submitted revisions |
| Admin drafts on a vendor's behalf | `/api/admin/pim/drafts*` (write) | `require_vendor_admin` | ✗ | ✗ | ✓ | ✓ | — | — | — |
| Take down vendor product / lift takedown | `DELETE /api/admin/products/{id}`, `POST …/takedown/lift` | in-handler `VENDOR_ADMIN_ROLES` (admin_routes.py:323, 337) | ✗ | ✗ | ✓ | ✓ | — | — | — |
| **Create / edit / delete / stock-adjust platform products** | `POST/PUT/DELETE /api/admin/products*`, `POST /api/admin/uploads/product-image` | **`require_admin` only** (admin_routes.py:244, 263, 295, 317, 347; storage.py:113) | **✓** | **✓** | ✓ | ✓ | — | — | 1P, no review step for platform products/prices |
| Vendor submits product / change for review | `POST/PUT /api/vendor/products*`, `/vendor/pim/drafts/{id}/submit` | `require_approved_vendor` + `products.submit` | — | — | — | — | ✓ | `products.submit` | — |
| Vendor stock adjust | `POST /api/vendor/products/{id}/stock` | `inventory.adjust` | — | — | — | — | ✓ | `inventory.adjust` | — |
| Merchandising create/update/status/reorder | `/api/admin/merch/sections*` (write) | `require_vendor_admin` (merchandising.py:185-247) | ✗ | ✗ | ✓ | ✓ | — | — | — · UI shows edit controls to all admins (AdminMerchandising.js) → 403 |
| Vendor policy (required documents) | `PUT /api/admin/vendor-policy` | `require_vendor_admin` | ✗ | ✗ | ✓ | ✓ | — | — | — |
| Support tickets (admin side) | `/api/admin/support/tickets*` | `require_admin` | ✓ | ✓ | ✓ | ✓ | — | — | — |

## 5. Orders, delivery, returns, exports

| Action | Endpoint | Guard | C/HG | VO | VS | Sup | Acc | Adm | SA | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| Place order | `POST /api/orders` | `get_current_user` (shop_routes.py:146) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **no rate limit, no open-COD cap** (Doc 3 P1) |
| Admin order status change (shipped/delivered/cancelled…) | `PUT /api/admin/orders/{id}/status` | `require_admin`; paid/COD-pending cancel only Adm/SA (l.425) | — | — | — | **✓** | ✓ | ✓ | ✓ | Platform goods: `delivered` writes `delivered_at` ⇒ starts commission release clock (l.413-414). Vendor goods: recorded as `status_set_by_admin`, no payout effect |
| Vendor fulfilment delivered | `POST /api/vendor/orders/{id}/fulfilment` | `require_vendor_obligations` + `orders.dispatch` (`FULFILMENT_PERMISSION`) | — | ✓ | `orders.dispatch` | — | — | — | — | self-attested; evidence note ≥3 chars (vendor_routes.py:894) |
| COD confirmation also sets delivered (platform-only orders) | see §1 | — | — | — | — | ✗ | ✗ | ✓ | ✓ | `shop_routes._cod_delivery_fields` l.282 |
| Remove (archive) abandoned order | `DELETE /api/admin/orders/{id}` | Adm/SA in handler (l.553) | — | — | — | ✗ | ✗ | ✓ | ✓ | only never-paid online orders |
| Admin return decision | `POST /api/admin/returns/{id}/decision` | `require_admin` (returns_routes.py:737) | — | — | — | **✓** | ✓ | ✓ | ✓ | 1P; UI shows to all |
| Vendor return action / inspection | `/api/vendor/returns/{id}/action|inspection` | `returns.respond` / `returns.inspect` | — | ✓ | per perm | — | — | — | — | — |
| Order export CSV (masked mobile, no address) | `GET /api/admin/order-ops/orders.csv` | `EXPORT_ROLES` super/admin/accounts (admin_order_ops.py:22, 126); audited | — | — | — | ✗ | ✓ | ✓ | ✓ | UI canExport matches; W4: every attempt audited (`export_*`, search text redacted), > 5,000 rows refused (413) |
| Order detail with full contact | `GET /api/admin/order-ops/orders/{id}` | `require_admin`; full mobile/e-mail only for super/admin/support (CONTACT_ROLES) | — | — | — | full | **masked** | full | full | but `GET /api/admin/orders`, `/admin/users`, `/admin/users/{id}`, `/admin/refund-queue` give Acc the same data **unmasked** |
| Reports + CSV export (registrations, sales, orders, payments, referrals, commissions, wallet, withdrawals) | `GET /api/admin/reports/{r}(/export)` | view: `require_admin`; **W4: export `EXPORT_ROLES`** (admin_routes.py `export_report`) | — | — | — | view ✓ / export **✗** | ✓ | ✓ | ✓ | W4 (2026-11-24): mobile / e-mail / payment session id masked in screen and CSV for every role; view and export audited; dates; > 5,000 rows refused (413); support export refusal is interim pending D-16 (D16-W4-1) |
| Audit log read | `GET /api/admin/audit-logs` | `require_admin` | — | — | — | ✓ | ✓ | ✓ | ✓ | last 500 only |
| Audit log delete | `DELETE /api/admin/audit-logs` | refused for everyone (405) and itself audited | — | — | — | ✗ | ✗ | ✗ | ✗ | — |
| Vendor statement / report CSV | `/api/vendor/finance/statement.csv`, `/api/vendor/reports/*.csv` | `finance.export` / `reports.export` | — | ✓ | per perm | — | — | — | — | —; W4: owner and staff exports audited (`export_*`, scope `vendor:<id>`), statement > 20,000 rows refused, start-after-end refused |
| Vendor documents listing (identity / bank-proof links) | `GET /api/admin/vendors/{id}/documents` | `require_admin` (governance_routes.py) | — | — | — | ✓ | ✓ (read; cannot review — tested) | ✓ | ✓ | W4: unchanged — accounts_admin reads but may not review or open onboarding; owner decision D16-W4-6 |

## 6. Vendor staff presets (backend/vendor_staff.py)

Rules (`RULES` l.102-132) are matched in order with `re.match`; no rule ⇒ staff refused (`required_permission` l.150). Owner-only
areas (profile, bank change, documents, staff, support, advancement, uploads for documents) have **no rule** and are refused.
`LEGACY_IMPLIES` (l.49): `products.write` ⇒ create/edit/submit/archive; `inventory.write` ⇒ adjust; `orders.fulfil` ⇒ accept/pack/
dispatch; `returns.act` ⇒ respond/inspect. Staff stop working when the membership is not `active` or the owner account is blocked/
deleted/suspended (`authorize_staff` l.187-196).

| Preset (PRESETS l.65) | Effective permissions |
|---|---|
| store_manager | products.read, products.create/edit/submit/archive (via products.write), inventory.read, inventory.adjust (via inventory.write), orders.read, orders.accept/pack/dispatch (via orders.fulfil), returns.read, returns.respond/inspect (via returns.act), reports.read |
| catalogue_manager | products.read/create/edit/submit/archive, inventory.read |
| product_editor | products.read/create/edit |
| inventory_manager | inventory.read, inventory.adjust, products.read |
| warehouse_staff | orders.read, orders.pack, inventory.read |
| order_manager | orders.read, orders.accept/pack/dispatch, returns.read |
| packing_staff | orders.read, orders.pack |
| dispatch_staff | orders.read, orders.dispatch (**includes marking delivered**) |
| returns_manager | returns.read/respond/inspect, orders.read |
| support_staff | orders.read, returns.read |
| finance_viewer | finance.read, reports.read |
| reports_viewer | reports.read |
| product_manager (legacy) | products.read + products.write (⇒ create/edit/submit/archive), inventory.read |
| inventory_staff (legacy) | inventory.read, inventory.write (⇒ adjust), products.read |
| custom | any non-empty subset of PERMISSIONS or legacy names (validate_role l.165) |

Verified against `docs/ROLE_PERMISSION_MATRIX.md` preset table: **identical**. Note the doc's table omits the two legacy presets'
rows (described in prose) and does not flag that `product_manager` (legacy) can submit and archive through `products.write`.

---

**W4 (2026-11-24) — reports and exports.** Full inventory, field classification and the D-16 decision table: `HOME_GENIES_REPORTS_AND_EXPORTS_SECURITY_AUDIT_W4.md`. No role gained access. Narrowed to an existing rule: report CSV export (support refused, as for the order export; interim D16-W4-1). The vendor documents listing stays readable by accounts_admin (existing, tested) — D16-W4-6. The Reports screen now shows Export only to the export roles (matches the backend).

## 7. UI vs backend disagreements [V]

| # | Screen / control | UI shows to | Backend allows | Effect |
|---|---|---|---|---|
| U-1 | COD "Collect" button (`AdminOrders.js:245`) | every admin role | admin, super_admin | Acc/Sup get 403; **W7: shown to admin / super_admin only** |
| U-2 | KYC Verify / Reject (`AdminKyc.js:88-89`) | every admin role | every admin role | Consistent with each other, but contradicts ROLE_PERMISSION_MATRIX ("support: read + support") |
| U-3 | Settings Save (`AdminSettings.js:89`) | every admin role | money fields: super/accounts; others: any admin | partial 403 for Adm/Sup |
| U-4 | Order status selector (`AdminOrders.js` status Select) | every admin role | any admin; paid cancel only Adm/SA | Sup/Acc can mark platform orders delivered (money clock) |
| U-5 | Refund case "Initiate"/"Failed" (`AdminOperations.js:85-87`) | every admin role | every admin role | support_admin initiates refunds — not in the role matrix |
| U-6 | Returns Approve/Reject (`AdminOperations.js:101-102`) | every admin role | every admin role | not in the role matrix |
| U-7 | Merchandising editor (`AdminMerchandising.js`) | every admin role | super/admin | 403 for Acc/Sup; **W7: editing shown to super / admin only; others view with a note** |
| U-8 | Catalogue review (`AdminCatalogue.js`) | every admin role | super/admin for decisions | 403 for Acc/Sup; **W7: decisions and add-for-vendor shown to super / admin only** |
| U-9 | Admin products create/edit/stock (`AdminProducts.js`) | every admin role | every admin role | Acc/Sup can change platform prices and stock — not in the role matrix |
| U-10 | Activations, Vendor applications, Team nav (`AdminLayout.js:19, 26, 32`) | role-filtered | same roles | consistent |
| U-11 | Withdrawals, finance ops, order export (`AdminWithdrawals.js:25`, `AdminOperations.js:190`, `AdminOrderOps.js:50`) | role-filtered | same roles | consistent |

The UI is not a security boundary (comments in AdminLayout.js:39 say so); all disagreements above fail closed except U-2, U-4, U-5,
U-6, U-9, where the **backend itself** is broader than the documented policy.

---

## 8. Differences from `docs/ROLE_PERMISSION_MATRIX.md`

| Doc statement | Code reality | Evidence |
|---|---|---|
| support_admin: "read + support" | support_admin can also: verify/reject member KYC; initiate/retry/fail refund cases; decide contested returns; create/edit/delete platform products, change their prices, adjust stock, upload product images; set order status incl. `delivered` for platform goods (starts commission clock) and cancel unpaid orders; block/deactivate members and customers; edit member profiles incl. Aadhaar and propose contact changes; approve/reject registration requests; create/delete referral codes; edit non-money settings; review vendor documents; read all audit logs; export reports with full mobile/e-mail | §1-§5 above |
| admin: "no money authority" | admin confirms COD cash (single person), changes the returns window that controls payout timing, cancels paid orders (opens refund cases, reverses vendor sales), approves HomeGenie activation | cod_rules.py:26; returns_routes.py:35; admin_routes.py:543; activation_routes.py:18 |
| accounts_admin: confirm refunds etc. | also initiates refunds (case + one-step record), verifies KYC alone, creates/edits platform products and prices, deactivates members; masked contacts only in the new order screen | §1, §2, §5 |
| Two-person rules list | Missing from the doc: COD confirm (1P), UPI/manual payment confirm (1P), bank-change approval (1P), commission release-now (1P), refund-case close as no_refund (1P), member-submitted KYC verification (1P), vendor final approval (1P), agreement create≠approve (2P, present in code), benefit proposer≠decider (2P, present in code), COD reporter≠resolver (2P, present in code) | §1 |
| "KYC (editor ≠ verifier)" | true, but only the **last** editor is blocked; a member-submitted record has no second person | admin_routes.py:747 |
| Vendor staff section | matches code | §6 |

## 9. Differences from other docs (permission-related)

* `docs/KNOWN_GAPS_AND_RISKS.md` R-2, R-3, R-4 still describe the code accurately. It does not list support_admin's product/price,
  KYC, refund-initiation and return-decision powers, nor the reports-export/PII inconsistency.
* `docs/HOME_GENIES_BATCH11_PRE_RELEASE_AUDIT.md`: C-4 (one-step refund) **fixed** (refund_order now only initiates a case);
  C-5a **partly fixed** (vendor goods only; platform goods still payable on any admin's `delivered`); C-12 **open**; C-17 **fixed**
  (`_guard_vendor_account`, `authorize_staff` owner check); C-19 **open** (D-03); C-20 **open**; L1 **fixed** (initiators list);
  L4 **open** (no beneficiary check); L10 **open**.
* `returns_routes.set_policy` error text "Only a super admin can change the returns policy" contradicts `POLICY_ROLES` which includes
  `admin` (returns_routes.py:35 vs 84).

## 10. Programme 03 changes (2026-11-27) — no permission was broadened
Uncommitted; not deployed. Evidence: `HOME_GENIES_PROGRAMME_03_ENGINEERING_REPORT.md`.

| Action | Endpoint | Guard | Change |
|---|---|---|---|
| Withdrawal request | `POST /api/withdrawals` | unchanged (distributor + green + KYC) | optional `request_key` (8-80 of `[A-Za-z0-9_-]`, unique per member): a retry returns the same request; same key + different amount ⇒ 409. A request that never reserved money (`not_reserved`) is hidden from the member's own list. |
| Withdrawal review | `PUT /api/admin/withdrawals/{id}` | unchanged | a request still `reserving` cannot be approved / rejected / paid (it is not in a requested state). |
| Financial reconciliation report | `GET /api/admin/finance/reconciliation[?domain=]` | **new**, `require_finance` (super_admin, accounts_admin) | read-only; ids / counts only. support_admin, admin, members, vendors ⇒ 403. |
| Settlement detail (with snapshot) | `GET /api/admin/finance/settlements/{id}` | **new**, `require_finance` | read-only; masked bank details only. |
| Settlement list | `GET /api/admin/finance/settlements` | unchanged (`require_admin`) | adds `snapshot_summary`; its payee bank part (holder, IFSC, masked account) is returned to finance roles only. |
| Settlement mark paid | `POST …/settlements/{id}/action` mark_paid | unchanged roles; creator ≠ approver ≠ payer rules unchanged | additionally refused (409) when the snapshot does not verify or the vendor's bank details changed since the request (P03-OD-01). |
| Vendor own settlements | `GET /api/vendor/finance/settlements` | unchanged | the snapshot is not returned to vendors. |
| Stripe status poll | `GET /api/payments/status/{sid}` | unchanged (public) | can only complete a payment Stripe itself confirms (amount, currency, order); only Stripe attempts are checked (P03-OD-03). |
| Payment events list / retry | `GET /api/admin/payment-events`, `POST …/{id}/retry` | unchanged (`_finance`) | now also holds Stripe events (provider `stripe`); a Stripe retry re-reads Stripe. |
