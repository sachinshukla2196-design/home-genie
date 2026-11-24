# HOME GENIES — Frontend ↔ Backend map

Independent inspection of `main` @ `d31cb74` (clean tree), 2026-11-23. Inspection only: nothing was run (no tests, no servers),
no existing file was changed. Companion document: `docs/HOME_GENIES_MODULE_COMPLETION_MATRIX.md`.

## 0. Method and evidence rules

| Item | How it was obtained (verified from code) |
|---|---|
| Frontend routes | every `<Route>` in `frontend/src/App.js` (83 `<Route>` elements incl. index routes and the `*` fallback) |
| Frontend API calls | regex scan of every `.js` under `frontend/src` (excluding `components/ui/` and tests) for `API.get/post/put/delete`, `usePaged` (`components/vendor/kit.js:74`), `downloadCsv` (`kit.js:210`), `useList` (`pages/admin/AdminOperations.js:19`), `useGet` (`components/vendor/Governance.js:14`), `act` (`pages/admin/AdminVendors.js`), plus the template-built calls in `components/catalogue/ProductStudio.js:41,51,79` (`${base}/drafts/...` with `base` = `/vendor/pim` or `/admin/pim`). The axios base URL is `${REACT_APP_BACKEND_URL}/api` (`lib/api.js:9`), so a frontend call `/x` is backend `/api/x`. |
| Backend routes | Python AST parse of every `@router.<method>` / `@app.<method>` in `backend/*.py` with the module's `APIRouter(prefix=...)`. **293 handlers** in 29 router modules + `server.py` (4). All 29 routers are included by `backend/server.py:65-118`; no router module is orphaned. |
| Guards | the `Depends(...)` default of each handler, resolved to its definition (table in §1), plus inline role checks found by grep (`get("role") not in ...`). |
| Vendor staff permission | `vendor_staff.RULES` (`backend/vendor_staff.py`, first matching rule) applied to the concrete path; `None` = staff refused (owner-only). |
| Matching | method + path with path parameters normalised. **Result: 0 frontend calls without a backend route; 46 backend handlers without any frontend caller (§7).** |

"Verified" below means read in the code at `d31cb74`. Anything not provable from the repository is marked **ASSUMPTION**.

## 1. Guard legend (verified definitions)

| Guard (as written in code) | Defined at | Who passes |
|---|---|---|
| public | — | anyone, no token |
| `get_current_user` | `core.py:123` | any valid session (customer, distributor, vendor, vendor_staff, admin roles) |
| `require_admin` | `core.py:186` | `ADMIN_ROLES` = super_admin, admin, accounts_admin, support_admin (`core.py:44`) |
| `require_vendor_admin` | `core.py:197` | super_admin, admin (`VENDOR_ADMIN_ROLES`) |
| `require_super_admin` / `_require_super_admin` | `admin_team.py:31`, `vendor_onboarding.py:647` | super_admin |
| `require_money_admin` | `admin_routes.py:382` | super_admin, accounts_admin (`MONEY_ADMIN_ROLES`) |
| `require_finance` | `finance_routes.py:32` | super_admin, accounts_admin |
| `require_finance_admin` | `financial_approvals.py:29` and a second copy `shop_routes.py:830` | super_admin, accounts_admin |
| `_finance` | `payment_events.py:183` | super_admin, accounts_admin |
| `require_approver` | `activation_routes.py:24` | admin, super_admin |
| `_require_view` | `vendor_applications.py:152`, `vendor_onboarding.py:487` | super_admin, admin, support_admin |
| `require_vendor_user` | `vendor_routes.py:71` | role vendor (owner) or vendor_staff (staff pass only through `authorize_staff` = `vendor_staff.RULES`) |
| `require_approved_vendor` / `_vendor_dep()` | `vendor_routes.py:96`, `pim.py:286` | vendor user whose vendor status is in `SELLING` = approved, active |
| `require_vendor_obligations` | `vendor_routes.py:86` | vendor user whose vendor is approved, active **or suspended** |
| `require_owner_account` | `vendor_staff_routes.py:25` | vendor owner only (staff refused) |
| cron `_authorise` | `cron_routes.py:17` | `Authorization: Bearer <WEBHOOK_CRON_SECRET or CRON_SECRET>` |
| webhook signatures | `payment_events.py` (Razorpay HMAC), `shop_routes.py:787` (Stripe via SDK) | payment provider |

Inline (in-handler) role checks that narrow a broader guard (verified): `homegenie_metrics.py:136,175` (role distributor only);
`wallet_routes.py:158` (withdrawal: distributor + green); `activation_routes.py:85` (target must be distributor);
`admin_order_ops.py:126` (CSV export: super_admin/admin/accounts_admin, support refused) and `:155` (contact details shown to
super_admin/admin/support_admin); `admin_routes.py:425,553` (cancel paid / remove order: super_admin/admin);
`admin_routes.py:1002` (money settings: finance only); `admin_routes.py:1406` (credential reset: super_admin/admin);
`admin_routes.py:74` (`_guard_vendor_account`: vendor accounts only by super_admin/admin); `admin_routes.py:323,336` (vendor
product takedown/lift: super_admin/admin); `returns_routes.py:83` (returns policy: super_admin/admin), `:296,305` (refund
resolve/confirm: finance); `cod_rules.py:115` via `shop_routes.py:304` (COD collected: admin/super_admin); `governance_routes.py:161`
(document review: super_admin/admin/support_admin), `:234` (bank change decision: super_admin/accounts_admin);
`contact_change.py:235` (recovery approve: super_admin); `vendor_routes.py:1039` (approve/reject/reinstate/activate: super_admin);
`shop_routes.py:387` (order read: owner or any admin role); `pim.py:146` (template: vendor, staff or admin roles).

Frontend guards (UX only; the server is authoritative): `ProtectedRoute` (`components/ProtectedRoute.js:19`): any signed-in user;
`admin` flag = the 4 admin roles; `vendor` flag = vendor / vendor_staff. `MemberOnly` (`components/MemberOnly.js:9`) only redirects
role `customer`; every other signed-in role (incl. admins/vendors who open `/app/...`) passes. `VendorGate` (`App.js`) shows
`PendingApproval` unless vendor status is approved/active (or suspended with `obligations`). Vendor menu filtering:
`VendorLayout.js NAV_PERMISSION`. Admin menu filtering: `AdminLayout.js:15-32` (`roles:` only on activations, vendor-applications, team).

## 2. Public / authentication

| Frontend route | Page component | API calls → backend handler | Guard |
|---|---|---|---|
| `/` | `pages/Landing.js` | GET `/api/products` → `shop_routes.py:71` | public |
| `/login` | `pages/Login.js` | POST `/api/auth/login` → `auth_routes.py:333` | public (rate-limited) |
| (any URL with `#session_id=`) | `pages/AuthCallback.js` (intercepted in `App.js AppRoutes`) | POST `/api/auth/google/session` → `auth_routes.py:413` (server calls Emergent `demobackend.emergentagent.com`, `auth_routes.py:390`); POST `/api/auth/forgot/google` → `auth_routes.py:468` | public |
| `/admin-secure-login` | `pages/AdminSecureLogin.js` | POST `/api/auth/admin-login` → `auth_routes.py:526` | public |
| `/register` | `pages/Register.js` | GET `/api/settings/public` → `server.py:41`; POST `/api/auth/register-request/send-otp` → `auth_routes.py:157`; POST `/api/auth/register-request` → `auth_routes.py:171` | public |
| `/login-otp` | `LoginOtp` in `pages/AuthExtras.js` | POST `/api/auth/login-otp/send` `:646`, `/verify` `:668` (`auth_routes.py`) | public |
| `/forgot` | `ForgotPassword` in `pages/AuthExtras.js` | POST `/api/auth/forgot/otp/send` `:708`, `/forgot/otp/reset` `:727`, `/forgot/google/reset` `:496`, `/forgot/send` `:752` (admin-handled request queue) | public |
| `/legal/:slug` | `pages/Legal.js` (static text: terms, privacy, returns, refunds, support) | none | public |
| `/payment/success` | `pages/PaymentSuccess.js` (ProtectedRoute) | GET `/api/payments/status/{session_id}` → `shop_routes.py:769` | **public** (no auth on the backend route) |
| `/payment/cancel` | `pages/PaymentCancel.js` | none | — |
| `/vendor/login` | `VendorLogin` in `pages/vendor/VendorAuth.js` | POST `/api/auth/login` | public |
| `/vendor/register` | `VendorRegister` = `<Navigate to="/vendor/apply">` (`VendorAuth.js:11`) | none — **deprecated route kept as redirect** | — |
| `/vendor/apply` | `pages/vendor/VendorApply.js` | GET `/api/settings/public`; POST `/api/vendor-applications/send-otp` → `vendor_applications.py:93`; POST `/api/vendor-applications` → `:108` | public |
| `/vendor/invite` | `pages/vendor/VendorStaffInvite.js` | GET `/api/vendor/staff/invitation` → `vendor_staff_routes.py:184`; POST `/api/vendor/staff/accept` → `:199` | public (token) |
| `/vendor/owner-invite` | `pages/vendor/VendorOwnerInvite.js` | GET `/api/vendor/invitation/owner` → `vendor_invitations.py:115`; POST `.../accept` → `:124` | public (token) |
| `*` | `<Navigate to="/">` | — | — |
| (every page) | `context/AuthContext.js` | GET `/api/auth/me` → `auth_routes.py:565`; POST `/api/auth/logout` → `:819` | get_current_user |
| (every protected page) | `components/ProtectedRoute.js` → `ContactChangeBanner.js`, `ForcePasswordChange.js` | GET/POST `/api/auth/contact-change[...]` → `contact_change.py:169-203`; POST `/api/auth/forced-change/send-otp` → `governance_routes.py:428`; PUT `/api/auth/change-password` → `:438` | get_current_user |

## 3. Customer ecosystem (`/app/*`, `ProtectedRoute`, any signed-in user)

| Frontend route | Page / components | API calls → handler | Guard |
|---|---|---|---|
| `/app` | redirect → `/app/dashboard` | — | — |
| `/app/dashboard` | `pages/Dashboard.js` (role `customer` → `CustomerHome` at `:47`, else member dashboard) + `MerchSections` + `HomeGeniePerformance` (member view only) | GET `/api/dashboard` → `wallet_routes.py:258`; GET `/api/products` → `shop_routes.py:71`; GET `/api/merch/home` → `merchandising.py:143`; GET `/api/homegenie/metrics` `:133`, `/api/homegenie/orders` `:172` (`homegenie_metrics.py`) | get_current_user / public; homegenie = distributor inline |
| `/app/products` | `pages/Products.js` + `MerchSections` | GET `/api/categories` → `shop_routes.py:88`; `/api/catalog/facets` → `discovery.py:81`; `/api/catalog/suggest` `:106`; `/api/catalog/search` `:41` | public |
| `/app/products/:id` | `pages/ProductDetail.js` + `RelatedProducts` + `WishButton` (share link only for green distributors, `ProductDetail.js:36`) | GET `/api/products/{id}` → `shop_routes.py:80`; `/api/catalog/products/{id}/related` → `discovery.py:124`; `/api/catalog/products` → `:144`; GET `/api/wishlist/ids` → `customer_routes.py:309`; POST `/api/wishlist` `:282`; DELETE `/api/wishlist/{product_id}` `:303` | public / get_current_user |
| `/app/cart` | `pages/Cart.js` (state in `context/CartContext.js`, `localStorage["hg_cart"]`) | **none — no server cart** | — |
| `/app/checkout` | `pages/Checkout.js` | GET `/api/addresses` → `customer_routes.py:163`; GET `/api/settings/public`; POST `/api/orders` → `shop_routes.py:146`; then **one of**: POST `/api/payments/checkout` (Stripe, default "Place order" button) `:419`; POST `/api/payments/razorpay/order` `:459` + `/razorpay/verify` `:487`; POST `/api/payments/upi-claim` `:808` | get_current_user |
| `/app/orders` | `pages/Orders.js` | GET `/api/orders` → `shop_routes.py:377` | get_current_user |
| `/app/orders/:id` | `pages/OrderDetail.js` (printable invoice via `window.print()`, `:47`) + `OrderSelfService` | GET `/api/orders/{id}` → `shop_routes.py:383`; GET `/api/returns` → `returns_routes.py:552`; POST `/api/orders/{id}/cancel` `:372`; POST `/api/orders/{id}/returns` `:446` (UI always sends `photos: []`) | get_current_user (+ owner/admin check `shop_routes.py:387`) |
| `/app/wishlist` | `pages/Wishlist.js` | GET `/api/wishlist` `:261`; DELETE `/api/wishlist/{id}` | get_current_user |
| `/app/addresses` | `pages/Addresses.js` | GET/POST `/api/addresses`, PUT `/api/addresses/{id}`, POST `/{id}/default`, DELETE `/{id}` (`customer_routes.py:163-212`) | get_current_user |
| `/app/notifications` | `pages/Notifications.js` (+ `AppLayout.js:59` bell) | GET `/api/notifications` → `wallet_routes.py:199`; POST `/api/notifications/read-all` `:212` | get_current_user |
| `/app/profile` | `pages/Profile.js` + `AccountSettings` | GET `/api/dashboard`; POST `/api/uploads/profile-photo` → `storage.py:107`; PUT `/api/auth/profile/photo` → `auth_routes.py:578`; PUT `/api/auth/profile` `:599`; PUT `/api/auth/change-password` → `governance_routes.py:438` | get_current_user |

Customer capabilities with a backend route but **no screen**: return ship-back with tracking (`POST /api/returns/{rid}/ship`,
`returns_routes.py:581`), withdraw a return (`POST /api/returns/{rid}/cancel`, `:590`), returns policy (`GET /api/returns/policy`,
`:76`), self-service mobile change (`PUT /api/auth/change-mobile/send|verify`, `auth_routes.py:772,793`), mark one notification read
(`POST /api/notifications/{nid}/read` is used only by the vendor portal). **No customer support-ticket API or screen exists** (the
only `support_tickets` routes are vendor/admin, `governance_routes.py:293-381`).

## 4. HomeGenie member ecosystem (role `distributor`; `/app/*` wrapped in `MemberOnly`)

| Frontend route | Page / components | API calls → handler | Guard |
|---|---|---|---|
| `/app/rewards` | `pages/Rewards.js` + `JourneyCard` | GET `/api/leaderboard` → `wallet_routes.py:233`; GET `/api/dashboard` `:258` | get_current_user |
| `/app/wallet` | `pages/Wallet.js` + `CommissionStatement` | GET `/api/wallet` `:25`; GET `/api/wallet/transactions` `:63`; GET `/api/commissions/statement` `:32` | get_current_user |
| `/app/withdrawals` | `pages/Withdrawals.js` | GET `/api/wallet`; GET `/api/withdrawals` `:152`; POST `/api/withdrawals` `:157` | get_current_user + inline distributor/green (`:158`) |
| `/app/kyc` | `pages/Kyc.js` | GET `/api/kyc` `:95`; POST `/api/kyc` `:113` | get_current_user (**no role check on submit**, matches KNOWN_GAPS R-9/L10) |
| `/app/referral` | `pages/Referral.js` | GET `/api/referral` `:69` | get_current_user |
| `/app/dashboard` (member view) | `HomeGeniePerformance` | `/api/homegenie/metrics`, `/api/homegenie/orders` | distributor inline |
| (any page) | `lib/sellerRef.js` via `SellerRefCapture` in `App.js` | stores `?ref=` code; sent as `seller_ref` in POST `/api/orders` (`shop_routes.py:141,213`) | — |

Backend-only member routes: `GET /api/badge` (`wallet_routes.py:219`).

## 5. Vendor ecosystem (`/vendor/*`, `ProtectedRoute vendor` + `VendorLayout`)

Staff permission = the `vendor_staff.RULES` permission a `vendor_staff` account needs; owner always passes.

| Frontend route | Page (gate) | API calls → handler | Backend guard | Staff permission |
|---|---|---|---|---|
| (layout) | `components/VendorLayout.js` | GET `/api/vendor/me` → `vendor_routes.py:128`; GET `/api/vendor/notifications` → `governance_routes.py:405` | vendor user | any active member |
| `/vendor/dashboard` | `VendorDashboard.js` (VendorGate) | GET `/api/vendor/dashboard` → `vendor_dashboard.py:78` | approved vendor | reports.read |
| `/vendor/analytics` | `VendorAnalytics.js` (VendorGate) | GET `/api/vendor/dashboard` (same endpoint as dashboard) | approved vendor | reports.read |
| `/vendor/notifications` | `VendorNotifications.js` (VendorGate) | GET `/api/vendor/notifications`; POST `/api/notifications/read-all`, `/api/notifications/{id}/read` (`wallet_routes.py:206,212`) | vendor user / get_current_user | any member / n.a. (not under `/api/vendor`) |
| `/vendor/products` | `VendorProducts.js` (VendorGate) + `ImportDialog` | GET `/api/vendor/products` `:359`; GET `/api/vendor/pim/drafts` → `pim.py:299`; GET `/api/vendor/catalogue/spec` `:410` (via `useCatalogueSpec`, `ProductForm.js:202`); POST `/api/vendor/products/{id}/listing` `:705`, `/archive` `:557`; GET `/api/vendor/products/export.csv` `:569`; GET `/import-template.csv` `:575`; POST `/api/vendor/products/import` `:588` | approved vendor | products.read / products.archive / products.submit (import) |
| `/vendor/products/new`, `/vendor/products/:productId/edit`, `/vendor/products/studio/:draftId` | `VendorProductStudio.js` → `components/catalogue/ProductStudio.js` (base `/vendor/pim`) + `ImageInput` | POST `/api/vendor/pim/drafts` `pim.py:306`; GET/PUT `/api/vendor/pim/drafts/{id}` `:313,318`; POST `/{id}/submit` `:326`; GET `/api/pim/template` `:144`; POST `/api/vendor/uploads/sign` → `governance_routes.py:481` | approved vendor | products.create or products.edit / products.submit |
| `/vendor/inventory` | `VendorInventory.js` (VendorGate) + `ImportDialog(stock)` | GET `/api/vendor/products`; POST `/api/vendor/products/{id}/stock` `:525`; GET `/{id}/stock-history` `:695`; POST `/api/vendor/products/import` (mode stock) | approved vendor | inventory.read / inventory.adjust / products.submit (**stock CSV import needs products.submit, not inventory.adjust** — `RULES` line `("POST", r"^/api/vendor/products(/import)?$", "products.submit")`) |
| `/vendor/orders` | `VendorOrders.js` (VendorGate obligations) + `components/vendor/OrderDetail.js` | GET `/api/vendor/orders` `:772`; GET `/{id}` `:809`; POST `/{id}/fulfilment` `:872`; POST `/{id}/return-inspection` `:952` | approved or suspended | orders.read / orders.accept·pack·dispatch (per step, `FULFILMENT_PERMISSION`) / returns.inspect |
| `/vendor/dispatch` | `VendorDispatch.js` (VendorGate obligations) | GET `/api/vendor/orders` (+ `OrderDetail`) | approved or suspended | orders.read |
| `/vendor/shipping` | `VendorShipping.js` = tabs embedding `VendorDispatch` and `VendorReturns` | as those pages | — | — |
| `/vendor/returns` | `VendorReturns.js` (VendorGate obligations) | GET `/api/vendor/returns` `returns_routes.py:599`; GET `/{rid}` `:618`; POST `/{rid}/action` `:633`; POST `/{rid}/inspection` `:677` | approved or suspended | returns.read / returns.respond / returns.inspect |
| `/vendor/reports` | `VendorReports.js` (VendorGate) | GET `/api/vendor/reports/current` → `vendor_reports.py:157`; `current.csv` `:163` | approved vendor | reports.read / reports.export |
| `/vendor/advancement` | `VendorAdvancement.js` (VendorGate) | GET `/api/vendor/reports/advancement` `vendor_reports.py:226`; GET `/api/vendor/advancement/eligibility` → `vendor_benefits.py:212` | approved vendor | **reports.read** (advancement report) / owner-only (eligibility) — menu treats the whole area as owner-only |
| `/vendor/finance` | `VendorFinance.js` (VendorGate) | GET `/api/vendor/finance/summary` → `finance_routes.py:54`; `/ledger` `:65`; `/settlements` `:76`; `/statement.csv` `:95` | approved vendor | finance.read / finance.export |
| `/vendor/earnings` | `VendorEarnings.js` = `<VendorFinance title=…>` | same as `/vendor/finance` | — | — |
| `/vendor/cod` | `VendorCod.js` (VendorGate) | GET `/api/vendor/finance/cod` `:167` | approved vendor | finance.read |
| `/vendor/terms` | `VendorTerms.js` (VendorGate) | GET `/api/vendor/finance/terms` → `commercial_routes.py:34`; POST `/terms/{aid}/accept` `:40` | approved vendor | finance.read / owner-only (accept) |
| `/vendor/support` | `VendorSupport.js` (VendorGate) + `ImageInput` | POST/GET `/api/vendor/support/tickets` → `governance_routes.py:293,313`; GET `/{tid}` `:329`; POST `/{tid}/reply` `:344`; POST `/api/vendor/uploads/sign` | approved vendor | owner-only (no rule) |
| `/vendor/staff` | `VendorStaff.js` (no gate) | GET `/api/vendor/staff` → `vendor_staff_routes.py:60`; POST `/invitations` `:78`; POST `/{mid}/resend` `:102`; PUT `/{mid}` `:116`; POST `/suspend` `:145`, `/reactivate` `:155`; DELETE `/{mid}` `:165` | **vendor owner only** | refused |
| `/vendor/security` | `VendorSecurity.js` (no gate) | PUT `/api/auth/change-password` | get_current_user | n.a. |
| `/vendor/profile` | `VendorProfile.js` (no gate) + `Governance.js` panels | GET `/api/vendor/me/profile-overview` → `vendor_routes.py:166`; PUT `/api/vendor/me` `:201`; GET `/api/vendor/me/history` → `governance_routes.py:37`; `/me/verification` `:46`; `/me/requirements` `:60`; GET/POST/DELETE `/api/vendor/documents` `:105-133`; GET/POST `/api/vendor/me/bank-change` `:190,210` | vendor user / approved vendor (bank-change POST) | owner-only (no rules) |

Pending / onboarding vendors see `components/vendor/PendingApproval.js` (no API calls) for gated routes.

## 6. Platform admin ecosystem (`/admin/*`, `ProtectedRoute admin` + `AdminLayout`)

| Frontend route | Page | API calls → handler (guard) |
|---|---|---|
| `/admin` | `AdminDashboard.js` | GET `/api/admin/dashboard` `admin_routes.py:80` (admin) |
| `/admin/users` | `AdminUsers.js` | GET `/api/admin/users` `:118` (admin; **unpaged, capped at 1000 rows**); PUT `/api/admin/users/{id}` `:1271`; PUT `/{id}/block` `:1191`; DELETE `/{id}` `:1237` (deactivate); POST `/{id}/reset-password` `:1397` (super_admin/admin inline); GET/POST `/api/admin/password-reset-requests[/{id}/dismiss]` `:1438,1443`; GET/POST `/api/admin/registration-requests[/{id}/approve|reject]` `:1046-1144`; GET/POST/DELETE `/api/admin/referral-codes` `:1014-1030`; POST `/api/admin/wallet/credit` `:1347` (finance; creates a maker-checker approval); GET `/api/admin/contact-changes` + `/cancel` + `/recovery-approve` (`contact_change.py:217-232`) |
| `/admin/team` | `AdminTeam.js` | GET/POST `/api/admin/team`, PUT `/{id}/role` (`admin_team.py:45-95`, super_admin); PUT `/api/admin/users/{id}/block` |
| `/admin/kyc` | `AdminKyc.js` | GET `/api/admin/kyc` `:639` (admin); PUT `/api/admin/kyc/{user_id}` `:736` (admin); PUT `/{user_id}/edit` `:681` (finance) |
| `/admin/activations` | `AdminActivations.js` | GET `/api/admin/activations`, POST `/{user_id}/approve` (`activation_routes.py:58,76`, admin/super_admin) |
| `/admin/withdrawals` | `AdminWithdrawals.js` | GET `/api/admin/withdrawals` `:776` (admin); PUT `/{wd_id}` `:807` (finance) |
| `/admin/orders` | `AdminOrderOps` (default export of `AdminOrderOps.js`) | GET `/api/admin/order-ops/orders` `admin_order_ops.py:97`; GET `orders.csv` `:119` (export roles inline) (admin) |
| `/admin/orders/:id` | `AdminOrderDetail` (`AdminOrderOps.js`) | GET `/api/admin/order-ops/orders/{id}` `:149`; PUT `/api/admin/orders/{id}/status` `admin_routes.py:389` (admin; paid-cancel inline super_admin/admin) |
| `/admin/orders/exceptions` | `AdminOrders.js` (old orders page, now the payment-exceptions tab) | GET `/api/admin/orders` `:361` (unpaged, cap 1000); GET `/api/admin/refund-queue` `:518`; PUT `/api/admin/orders/{id}/status`; POST `/api/orders/{id}/cod-collected` `shop_routes.py:293` (admin/super_admin inline); POST `/api/admin/orders/{id}/refund` `:460` (finance; maker step); DELETE `/api/admin/orders/{id}` `:548` (archive; super_admin/admin); PUT `/api/admin/payments/upi-confirm/{id}` `shop_routes.py:919`, `/upi-reject/{id}` `:986`, POST `/api/admin/payments/manual` `:874` (finance) |
| `/admin/orders/events` | `AdminPaymentEvents` (`AdminOrderOps.js:221`) | GET `/api/admin/payment-events` `payment_events.py:190`; POST `/{id}/retry` `:207` (finance) |
| `/admin/order-ops` | redirect → `/admin/orders` (**deprecated alias**) | — |
| `/admin/operations` | `AdminOperations.js` | GET `/api/admin/finance/approvals` + approve/reject (`financial_approvals.py:77-118`, finance); GET `/api/admin/refund-cases` + `/action` (`returns_routes.py:240,273`, admin; confirm/resolve finance inline); GET `/api/admin/returns` + `/decision` (`:723,737`, admin); GET `/api/admin/finance/vendors` `finance_routes.py:219` (admin); GET/POST `/api/admin/finance/settlements` + `/action` (`:387,292,328`; create/action finance); GET `/api/admin/finance/cod-discrepancies` `:523` + POST `/resolve` `:405` (finance); GET `/api/admin/payments/duplicates` + `/refunded` (`shop_routes.py:953,967`, finance); GET `/api/admin/vendor-change-requests` + `/decision` (`governance_routes.py:217,233`); GET `/api/admin/support/tickets` + `/reply` (`:358,381`) |
| `/admin/catalogue` | `AdminCatalogue.js` | GET `/api/admin/pim/revisions` `pim.py:401`; GET `/api/admin/pim/products/{id}/revision` `:409`; POST `/revision/decision` `:424` (vendor_admin); GET `/api/admin/vendor-products` `vendor_routes.py:1060`; POST `/{id}/decision` `:1073` (vendor_admin); GET/POST `/api/admin/pim/drafts` `:350,367`; GET `/api/admin/vendors` |
| `/admin/catalogue/studio/:draftId` | `AdminCatalogueStudio` → `ProductStudio` (base `/admin/pim`) + `ImageInput` | GET/PUT `/api/admin/pim/drafts/{id}` `:380,385`; POST `/submit` `:393` (vendor_admin); GET `/api/pim/template`; **POST `/api/vendor/uploads/sign` — refused for admins (`require_approved_vendor`), see §8** |
| `/admin/products` | `AdminProducts.js` (platform-own products, direct CRUD) | GET/POST `/api/admin/products`, PUT/DELETE `/{id}`, POST `/{id}/stock`, `/{id}/takedown/lift`, DELETE `/{id}/permanent` (`admin_routes.py:220-347`); POST `/api/admin/uploads/product-image` `storage.py:113` |
| `/admin/merchandising` | `AdminMerchandising.js` + `ImageInput` | GET `/api/admin/merch/sections` `merchandising.py:164` (admin); POST/PUT/status/order (`:186-241`, vendor_admin); GET `/preview` `:249`; GET `/api/catalog/products`, `/api/catalog/search`; **POST `/api/vendor/uploads/sign` — refused for admins** |
| `/admin/vendors` | `AdminVendors.js` | GET `/api/admin/vendors` `vendor_routes.py:1012`; GET `/api/admin/vendor-products?status=pending`; POST `/api/admin/vendors/{id}/decision` `:1032` (vendor_admin; super_admin actions inline); POST `/api/admin/vendor-products/{id}/decision` |
| `/admin/vendors/new` | `AdminVendorCreate.js` | POST `/api/admin/vendors/create` `:995` (vendor_admin) |
| `/admin/vendor-applications` | `AdminVendorApplications.js` | GET `/api/admin/vendor-applications[/{aid}]` (`vendor_applications.py:165,207`, `_require_view`); PUT `/{aid}` `:225`, POST `/{aid}/action` `:277` (vendor_admin) |
| `/admin/vendors/:id/onboarding` | `AdminVendorOnboarding.js` | GET `/api/admin/vendors/{id}/onboarding` `vendor_onboarding.py:508`; GET `/api/admin/vendor-onboarding/options` `:501`; PUT `/onboarding/{section}` `:521`; POST `/onboarding/documents` `:598`; POST `/submit-for-approval` `:624` (vendor_admin); POST `/final-review` `:654`, `/owner-access` `:701` (super_admin); POST `/api/admin/vendor-documents/{id}/review` `governance_routes.py:160` |
| `/admin/agreements` | `AdminAgreements.js` | GET `/api/admin/vendors`; GET/POST `/api/admin/finance/vendors/{vid}/agreements` (`commercial_routes.py:18,13`); POST `/api/admin/finance/agreements/{aid}/approve` `:29` (finance) |
| `/admin/benefits` | `AdminBenefits.js` | GET/POST `/api/admin/benefits/programmes`, `/proposals`, POST `/proposals/{id}/decide`, GET `/eligibility` (`vendor_benefits.py:93-194`, all finance) |
| `/admin/reports` | `AdminReports.js` | GET `/api/admin/reports/{report}` `admin_routes.py:1485`; GET `/{report}/export` `:1494` (admin — incl. support_admin; 8 legacy reports, float money fields, no date filter, 2000/5000 row caps, export not audited) |
| `/admin/settings` | `AdminSettings.js` | GET/PUT `/api/admin/settings` `:944,998` (admin; money fields finance inline) |
| `/admin/audit` | `AdminAuditLogs.js` | GET `/api/admin/audit-logs` `:1451` (admin; last 500 rows only, no filters/paging) |

## 7. Backend routes with no frontend caller (46 of 293)

| # | Route | Handler | Classification |
|---|---|---|---|
| 1-3 | GET `/api/`, GET `/api/health`, GET `/health` | `server.py:26,31,36` | infrastructure (expected) |
| 4-6 | POST+GET `/api/cron/release-points`, GET `/api/cron/expire-pending-orders` | `cron_routes.py:39,57,72` | cron (Vercel `backend/vercel.json` schedules the two GETs daily: `0 20 * * *`, `30 20 * * *`) |
| 7-8 | POST `/api/webhook/razorpay`, POST `/api/webhook/stripe` | `payment_events.py:161`, `shop_routes.py:787` | provider webhooks (expected) |
| 9 | GET `/api/files/{path}` | `storage.py:119` | used implicitly as `<img src>` for uploaded profile/product images (not an API call) |
| 10-11 | POST `/api/auth/register`, POST `/api/auth/send-otp` | `auth_routes.py:254,94` | **deprecated legacy sign-up** (UI uses `/register-request`); still live and still reachable publicly |
| 12 | GET `/api/auth/reference-codes` | `auth_routes.py:245` | backend-only (public list of reference codes) |
| 13-14 | PUT `/api/auth/change-mobile/send`, `/verify` | `auth_routes.py:772,793` | **backend-only: no self-service mobile change screen** (tested in `test_otp_auth.py`, `test_security_batch0.py`) |
| 15 | GET `/api/badge` | `wallet_routes.py:219` | backend-only |
| 16 | GET `/api/returns/policy` | `returns_routes.py:76` | backend-only (customer cannot see the window in-app; text only in `Legal.js`) |
| 17-18 | POST `/api/returns/{rid}/ship`, `/cancel` | `returns_routes.py:581,590` | **backend-only: customer cannot enter return tracking or withdraw a return** |
| 19 | PUT `/api/admin/returns/policy` | `returns_routes.py:82` | backend-only: no admin screen for the return window that drives payouts (D-01/D-05) |
| 20 | GET `/api/admin/users/{user_id}` | `admin_routes.py:131` | backend-only (no user detail screen) |
| 21-23 | GET `/api/admin/payments`, `/api/admin/referrals`, `/api/admin/commissions` | `admin_routes.py:585,591,596` | backend-only legacy lists (unpaged, cap 1000) |
| 24 | PUT `/api/admin/commissions/{id}/status` | `admin_routes.py:606` | **backend-only manual commission release/hold** (finance; tested `test_manual_money_controls.py`) |
| 25 | DELETE `/api/admin/audit-logs` | `admin_routes.py:1456` | refusal stub: always 405 and audits the attempt (intended) |
| 26-27 | GET/PUT `/api/admin/finance/policy` | `finance_routes.py:199,204` | backend-only: settlement policy (dual approval, minimum) has no screen |
| 28-29 | GET `/api/admin/finance/vendors/{id}/ledger`, POST `/adjustments` | `finance_routes.py:228,244` | **backend-only: admins cannot view a vendor ledger or raise a vendor adjustment from the UI**, although the approvals queue for adjustments is on screen |
| 30 | POST `/api/admin/finance/reconcile` | `finance_routes.py:396` | backend-only (also run by the expire-pending-orders cron) |
| 31-33 | GET `/api/admin/finance/commission-funding`, `/non-distributor-commissions`, `/negative-wallets` | `finance_routes.py:460,473,499` | backend-only finance reports |
| 34 | PUT `/api/admin/vendor-policy` | `governance_routes.py:74` | backend-only |
| 35-36 | GET `/api/admin/vendors/{id}/history`, `/documents` | `governance_routes.py:87,145` | backend-only (onboarding screen uses its own endpoint) |
| 37 | GET `/api/admin/support/tickets/{tid}` | `governance_routes.py:367` | backend-only: admins reply from the list without a ticket thread view |
| 38-40 | POST/GET `/api/admin/vendors/{id}/owner-invitation`, POST `/revoke` | `vendor_invitations.py:73,103,95` | **duplicate** of `POST /api/admin/vendors/{vid}/owner-access` (`vendor_onboarding.py:701`), different guard (vendor_admin + inline super_admin vs `_require_super_admin`); revoke has no UI |
| 41 | POST `/api/admin/vendors/invite` | `vendor_routes.py:1112` | **deprecated**: always 410 (account conversion retired) |
| 42-43 | POST `/api/vendor/products`, PUT `/api/vendor/products/{id}` | `vendor_routes.py:442,509` | **legacy direct product create/update** (superseded by the product studio; `ProductForm` component no longer rendered) — still live for vendors and staff with `products.submit` |
| 44 | DELETE `/api/vendor/pim/drafts/{id}` | `pim.py:331` | backend-only: no "discard draft" button |
| 45 | GET `/api/vendor/pim/products/{id}/revision` | `pim.py:341` | backend-only |
| 46 | GET `/api/admin/pim/products/{id}/price-history` | `pim.py:466` | backend-only: price history not visible |

## 8. Frontend calls that reach a route whose guard refuses the caller (functionally broken)

| Caller | Call | Why it fails | Evidence |
|---|---|---|---|
| `pages/admin/AdminMerchandising.js:107-108` (banner images) and `AdminCatalogueStudio` (`ProductStudio.js:229,437` images / documents) | POST `/api/vendor/uploads/sign` from `components/vendor/ImageInput.js:52` | the route depends on `require_approved_vendor` → `require_vendor_user` answers **403 "Vendor access only."** for every admin role. The "paste an https link" field in `ImageInput` still works, so admins can only use external https URLs. | `governance_routes.py:481`, `vendor_routes.py:73` |
| Staff with `reports.read` opening `/vendor/advancement` (only if they reach it by URL; the menu hides it) | GET `/api/vendor/advancement/eligibility` | no `RULES` entry → staff refused, while the sibling `/api/vendor/reports/advancement` is allowed by `reports.read` | `vendor_staff.py RULES`, `vendor_benefits.py:212` |
| `pages/Checkout.js:55-73` default "Place order" (method `online`) | POST `/api/orders` **then** POST `/api/payments/checkout` | when Stripe is not configured `_stripe()` answers 503 **after** the order was created, leaving an unpaid order holding reserved stock until the 15-minute expiry sweep (`stock.py:30`). Razorpay path has the same create-then-fail ordering. | `shop_routes.py:410-412,419-456` |

No frontend call targets a non-existent backend path (0 of the 243 distinct method/path pairs found by the scan).

## 9. Duplicated / overlapping screens and routes

| Area | Duplicates | Evidence | Note |
|---|---|---|---|
| Admin orders | `AdminOrderOps` (new, paged, `/api/admin/order-ops/*`) vs `AdminOrders.js` (old, `/api/admin/orders`, unpaged cap 1000) now mounted at `/admin/orders/exceptions`; `/admin/order-ops` alias redirect | `App.js`, `admin_routes.py:361`, `admin_order_ops.py:97` | Batch 14 merged navigation (tabs) but two list endpoints and two pages remain; both call PUT `/api/admin/orders/{id}/status` |
| Product forms | `components/vendor/ProductForm.js` (`ProductForm` export **not rendered anywhere**; only `useCatalogueSpec` is imported by `VendorProducts.js:11`) vs `components/catalogue/ProductStudio.js` | grep of imports | dead component code; backed by the legacy POST/PUT `/api/vendor/products` |
| Product write paths | product studio (`/api/vendor/pim/*`, keeps live version on sale) vs legacy POST/PUT `/api/vendor/products` and CSV import (`/api/vendor/products/import`) which hide an approved product on a material change (`apply_product_update(review=True)`, `vendor_routes.py:486-487`; import `:677-681`) | `vendor_routes.py` | **CSV import does not check `pending_revision`** (the PUT does, `:511`), so an import can rewrite a product that has a pending studio revision |
| Admin products | `AdminProducts.js` (direct CRUD of platform-own products, `/api/admin/products`) vs `AdminCatalogue.js` (PIM review + admin drafts for vendors) | `admin_routes.py:220-347`, `pim.py:350-466` | two catalogue write models |
| Vendor finance | `/vendor/finance` and `/vendor/earnings` render the same component | `VendorEarnings.js` | only `/vendor/earnings` is in the menu |
| Vendor shipping | `/vendor/dispatch`, `/vendor/returns` and `/vendor/shipping` (tabs embedding both) | `VendorShipping.js` | only `/vendor/shipping` in the menu; notification links use `/vendor/returns?open=` |
| Vendor dashboard | `/vendor/dashboard` and `/vendor/analytics` both read GET `/api/vendor/dashboard` | `VendorDashboard.js:63`, `VendorAnalytics.js:35` | |
| Vendor approval | legacy `POST /api/admin/vendors/{id}/decision` (lifecycle `TRANSITIONS`, `vendor_lifecycle.py:30`) vs onboarding `POST /api/admin/vendors/{vid}/final-review` | `vendor_routes.py:1032`, `vendor_onboarding.py:654` | both on screen (AdminVendors / AdminVendorOnboarding) |
| Owner invitation | `/api/admin/vendors/{id}/owner-invitation` vs `/owner-access` | §7 rows 38-40 | |
| Return inspection | `/api/vendor/orders/{id}/return-inspection` (courier return-to-origin) vs `/api/vendor/returns/{rid}/inspection` (customer return) | `vendor_routes.py:952`, `returns_routes.py:677` | different purposes, similar names (not a true duplicate) |
| Card payment | Stripe (`/api/payments/checkout`) and Razorpay (`/api/payments/razorpay/*`) both offered for method `online` | `Checkout.js:236-246` | only Razorpay is reconciled by webhook events (`payment_events.py`); Stripe webhook is not recorded |
| `require_finance_admin` | defined twice with the same roles | `financial_approvals.py:29`, `shop_routes.py:830` | maintenance risk only |
| Deployment | `backend/vercel.json` (two crons) vs `deploy/vercel-api/vercel.json` (only `release-points`; copies backend via `sync-backend.sh`) | both files | second path would never run `expire-pending-orders` |

## 10. Deprecated routes (verified)

`/vendor/register` (redirect), `/admin/order-ops` (redirect), POST `/api/admin/vendors/invite` (410), DELETE `/api/admin/audit-logs`
(405 by design), POST `/api/auth/register` + `/api/auth/send-otp` (legacy sign-up still active, no UI), admin registration-request
queue (`/api/admin/registration-requests*`, still on the Users screen although `server.py:_init_db` auto-activates pending
registrations via `activate_pending_registrations`), legacy direct vendor product create/update, `ProductForm` component,
`deploy/vercel-api` deployment copy.

## 11. Documentation vs code differences found while mapping

| Doc claim | Code at `d31cb74` |
|---|---|
| `ROLE_PERMISSION_MATRIX.md`: "Owner only: … advancement" | GET `/api/vendor/reports/advancement` matches rule `^/api/vendor/reports/.+$` → any staff with `reports.read` (`vendor_staff.py RULES`); only `/api/vendor/advancement/eligibility` is owner-only |
| `ROLE_PERMISSION_MATRIX.md`: import needs `products.submit` (listed under Products) | true, but this also applies to the **stock** CSV import used from the Inventory screen, so an inventory manager (`inventory.adjust`) cannot import stock |
| `KNOWN_GAPS_AND_RISKS.md` "safe by design: a change to an approved product never hides it" | true only for the product studio; legacy PUT and CSV import hide the product (`vendor_routes.py:486-487, 677-681`) |
| `docs/ENGINEERING_LOG_BATCH12_ONWARD.md` Phase 10: merchandising uses "storage images only" | `merchandising.py:77-82` → `validators.safe_image_refs` accepts any `https://` URL |
| `payment_events.py:1` cites `docs/PAYMENT_RECONCILIATION_SPEC.md` | file does not exist in `docs/` |
| No doc mentions Batch 14 (payment reconciliation, VEN-05 profile overview, orders-area merge) | code and commit `d31cb74` contain it (`payment_events.py`, `vendor_routes.py:148-213`, `AdminOrderOps.js:20`) |
| `HOME_GENIES_AUTONOMOUS_ROADMAP.md`: "All Batch 12 work is uncommitted" / "Next executable task: Phase 7" | committed in `d31cb74`; Phase 7 delivered in Batch 13 |
| `MARKETPLACE_MODULE_COMPLETION_MATRIX.md`: VEN-05 "NOT STARTED" | `/api/vendor/me/profile-overview` + contact validation implemented (Batch 14), without a dedicated test |
| `KNOWN_GAPS_AND_RISKS.md` functional gap "webhook events linked to orders" | implemented for Razorpay in Batch 14 (`webhook_events` matched via `payment_transactions.session_id`); not for Stripe |
| `Legal.js` refunds text: "Approved refunds are issued to the original payment method" | no provider refund API is wired (`returns_routes.verify_provider_refund` returns False; refunds are manual with a reference) |
| `OWNER_DECISION_REGISTER.md` D-05: returns policy editable by super_admin, admin | matches `POLICY_ROLES`; the refusal message says "Only a super admin can change the returns policy" (`returns_routes.py:84`) — message disagrees with the rule |

---

## Appendix A — every frontend call, per file (generated from the scan; guard = backend dependency)

Staff permission column: blank = not a `/api/vendor/*` route; "staff refused (owner-only)" = no `RULES` entry.

### `components/AccountSettings.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| PUT `/api/auth/profile` | `auth_routes.py:599` | any signed-in user |  |
| PUT `/api/auth/change-password` | `governance_routes.py:438` | any signed-in user |  |

### `components/AppLayout.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/notifications` | `wallet_routes.py:199` | any signed-in user |  |

### `components/CommissionStatement.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/commissions/statement` | `wallet_routes.py:32` | any signed-in user |  |

### `components/ContactChangeBanner.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/auth/contact-change` | `contact_change.py:169` | any signed-in user |  |
| POST `/api/auth/contact-change/send-otp` | `contact_change.py:177` | any signed-in user |  |
| POST `/api/auth/contact-change/confirm` | `contact_change.py:189` | any signed-in user |  |
| POST `/api/auth/contact-change/reject` | `contact_change.py:203` | any signed-in user |  |

### `components/ForcePasswordChange.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/auth/forced-change/send-otp` | `governance_routes.py:428` | any signed-in user |  |
| PUT `/api/auth/change-password` | `governance_routes.py:438` | any signed-in user |  |

### `components/HomeGeniePerformance.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/homegenie/metrics` | `homegenie_metrics.py:133` | any signed-in user |  |
| GET `/api/homegenie/orders` | `homegenie_metrics.py:172` | any signed-in user |  |

### `components/MerchSections.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/merch/home` | `merchandising.py:143` | public |  |

### `components/OrderSelfService.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/returns` | `returns_routes.py:552` | any signed-in user |  |
| POST `/api/orders/{order_id}/cancel` | `returns_routes.py:372` | any signed-in user |  |
| POST `/api/orders/{order_id}/returns` | `returns_routes.py:446` | any signed-in user |  |

### `components/RelatedProducts.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/catalog/products/{product_id}/related` | `discovery.py:124` | public |  |
| GET `/api/catalog/products` | `discovery.py:144` | public |  |

### `components/VendorLayout.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/me` | `vendor_routes.py:128` | vendor owner or staff | any active member |
| GET `/api/vendor/notifications` | `governance_routes.py:405` | vendor owner or staff | any active member |

### `components/WishButton.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/wishlist/ids` | `customer_routes.py:309` | any signed-in user |  |
| DELETE `/api/wishlist/{product_id}` | `customer_routes.py:303` | any signed-in user |  |
| POST `/api/wishlist` | `customer_routes.py:282` | any signed-in user |  |

### `components/catalogue/ProductStudio.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/pim/template` | `pim.py:144` | any signed-in user |  |
| GET `/api/vendor/pim/drafts/{draft_id}` | `pim.py:313` | approved vendor (owner/staff) | products.read |
| PUT `/api/vendor/pim/drafts/{draft_id}` | `pim.py:318` | approved vendor (owner/staff) | products.create or products.edit |
| POST `/api/vendor/pim/drafts/{draft_id}/submit` | `pim.py:326` | approved vendor (owner/staff) | products.submit |
| GET `/api/admin/pim/drafts/{draft_id}` | `pim.py:380` | admin (any of 4 roles) |  |
| PUT `/api/admin/pim/drafts/{draft_id}` | `pim.py:385` | vendor_admin (super_admin/admin) |  |
| POST `/api/admin/pim/drafts/{draft_id}/submit` | `pim.py:393` | vendor_admin (super_admin/admin) |  |

### `components/vendor/Governance.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/me/history` | `governance_routes.py:37` | vendor owner or staff | staff refused (owner-only) |
| GET `/api/vendor/documents` | `governance_routes.py:105` | vendor owner or staff | staff refused (owner-only) |
| GET `/api/vendor/me/requirements` | `governance_routes.py:60` | vendor owner or staff | staff refused (owner-only) |
| POST `/api/vendor/documents` | `governance_routes.py:111` | vendor owner or staff | staff refused (owner-only) |
| DELETE `/api/vendor/documents/{doc_id}` | `governance_routes.py:133` | vendor owner or staff | staff refused (owner-only) |
| GET `/api/vendor/me/verification` | `governance_routes.py:46` | vendor owner or staff | staff refused (owner-only) |
| GET `/api/vendor/me/bank-change` | `governance_routes.py:210` | vendor owner or staff | staff refused (owner-only) |
| POST `/api/vendor/me/bank-change` | `governance_routes.py:190` | approved vendor (owner/staff) | staff refused (owner-only) |

### `components/vendor/ImageInput.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/vendor/uploads/sign` | `governance_routes.py:481` | approved vendor (owner/staff) | products.create or products.edit |

### `components/vendor/ImportDialog.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/vendor/products/import` | `vendor_routes.py:588` | approved vendor (owner/staff) | products.submit |
| GET `/api/vendor/products/import-template.csv` | `vendor_routes.py:575` | approved vendor (owner/staff) | products.read |

### `components/vendor/OrderDetail.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/vendor/orders/{order_id}/return-inspection` | `vendor_routes.py:952` | approved or suspended vendor (owner/staff) | returns.inspect |
| GET `/api/vendor/orders/{order_id}` | `vendor_routes.py:809` | approved or suspended vendor (owner/staff) | orders.read |
| POST `/api/vendor/orders/{order_id}/fulfilment` | `vendor_routes.py:872` | approved or suspended vendor (owner/staff) | orders.accept or orders.pack or orders.dispatch |

### `components/vendor/ProductForm.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/catalogue/spec` | `vendor_routes.py:410` | vendor owner or staff | products.read |

### `context/AuthContext.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/auth/me` | `auth_routes.py:565` | any signed-in user |  |
| POST `/api/auth/logout` | `auth_routes.py:819` | any signed-in user |  |

### `pages/Addresses.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/addresses` | `customer_routes.py:163` | any signed-in user |  |
| PUT `/api/addresses/{address_id}` | `customer_routes.py:191` | any signed-in user |  |
| POST `/api/addresses` | `customer_routes.py:172` | any signed-in user |  |
| POST `/api/addresses/{address_id}/default` | `customer_routes.py:205` | any signed-in user |  |
| DELETE `/api/addresses/{address_id}` | `customer_routes.py:212` | any signed-in user |  |

### `pages/AdminSecureLogin.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/auth/admin-login` | `auth_routes.py:526` | public |  |

### `pages/AuthCallback.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/auth/forgot/google` | `auth_routes.py:468` | public |  |
| POST `/api/auth/google/session` | `auth_routes.py:413` | public |  |

### `pages/AuthExtras.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/auth/login-otp/send` | `auth_routes.py:646` | public |  |
| POST `/api/auth/login-otp/verify` | `auth_routes.py:668` | public |  |
| POST `/api/auth/forgot/otp/send` | `auth_routes.py:708` | public |  |
| POST `/api/auth/forgot/otp/reset` | `auth_routes.py:727` | public |  |
| POST `/api/auth/forgot/google/reset` | `auth_routes.py:496` | public |  |
| POST `/api/auth/forgot/send` | `auth_routes.py:752` | public |  |

### `pages/Checkout.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/addresses` | `customer_routes.py:163` | any signed-in user |  |
| GET `/api/settings/public` | `server.py:41` | public |  |
| POST `/api/orders` | `shop_routes.py:146` | any signed-in user |  |
| POST `/api/payments/checkout` | `shop_routes.py:419` | any signed-in user |  |
| POST `/api/payments/upi-claim` | `shop_routes.py:808` | any signed-in user |  |
| POST `/api/payments/razorpay/order` | `shop_routes.py:459` | any signed-in user |  |
| POST `/api/payments/razorpay/verify` | `shop_routes.py:487` | any signed-in user |  |

### `pages/Dashboard.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/dashboard` | `wallet_routes.py:258` | any signed-in user |  |
| GET `/api/products` | `shop_routes.py:71` | public |  |

### `pages/Kyc.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/kyc` | `wallet_routes.py:95` | any signed-in user |  |
| POST `/api/kyc` | `wallet_routes.py:113` | any signed-in user |  |

### `pages/Landing.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/products` | `shop_routes.py:71` | public |  |

### `pages/Login.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/auth/login` | `auth_routes.py:333` | public |  |

### `pages/Notifications.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/notifications` | `wallet_routes.py:199` | any signed-in user |  |
| POST `/api/notifications/read-all` | `wallet_routes.py:212` | any signed-in user |  |

### `pages/OrderDetail.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/orders/{order_id}` | `shop_routes.py:383` | any signed-in user |  |

### `pages/Orders.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/orders` | `shop_routes.py:377` | any signed-in user |  |

### `pages/PaymentSuccess.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/payments/status/{session_id}` | `shop_routes.py:769` | public |  |

### `pages/ProductDetail.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/products/{product_id}` | `shop_routes.py:80` | public |  |

### `pages/Products.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/categories` | `shop_routes.py:88` | public |  |
| GET `/api/catalog/facets` | `discovery.py:81` | public |  |
| GET `/api/catalog/suggest` | `discovery.py:106` | public |  |
| GET `/api/catalog/search` | `discovery.py:41` | public |  |

### `pages/Profile.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/dashboard` | `wallet_routes.py:258` | any signed-in user |  |
| POST `/api/uploads/profile-photo` | `storage.py:107` | any signed-in user |  |
| PUT `/api/auth/profile/photo` | `auth_routes.py:578` | any signed-in user |  |

### `pages/Referral.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/referral` | `wallet_routes.py:69` | any signed-in user |  |

### `pages/Register.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/settings/public` | `server.py:41` | public |  |
| POST `/api/auth/register-request/send-otp` | `auth_routes.py:157` | public |  |
| POST `/api/auth/register-request` | `auth_routes.py:171` | public |  |

### `pages/Rewards.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/leaderboard` | `wallet_routes.py:233` | any signed-in user |  |
| GET `/api/dashboard` | `wallet_routes.py:258` | any signed-in user |  |

### `pages/Wallet.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/wallet` | `wallet_routes.py:25` | any signed-in user |  |
| GET `/api/wallet/transactions` | `wallet_routes.py:63` | any signed-in user |  |

### `pages/Wishlist.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/wishlist` | `customer_routes.py:261` | any signed-in user |  |
| DELETE `/api/wishlist/{product_id}` | `customer_routes.py:303` | any signed-in user |  |

### `pages/Withdrawals.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/wallet` | `wallet_routes.py:25` | any signed-in user |  |
| GET `/api/withdrawals` | `wallet_routes.py:152` | any signed-in user |  |
| POST `/api/withdrawals` | `wallet_routes.py:157` | any signed-in user |  |

### `pages/admin/AdminActivations.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/activations` | `activation_routes.py:58` | admin/super_admin |  |
| POST `/api/admin/activations/{user_id}/approve` | `activation_routes.py:76` | admin/super_admin |  |

### `pages/admin/AdminAgreements.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/vendors` | `vendor_routes.py:1012` | admin (any of 4 roles) |  |
| GET `/api/admin/finance/vendors/{vendor_id}/agreements` | `commercial_routes.py:18` | admin (any of 4 roles) |  |
| POST `/api/admin/finance/vendors/{vendor_id}/agreements` | `commercial_routes.py:13` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/finance/agreements/{aid}/approve` | `commercial_routes.py:29` | finance (super_admin/accounts_admin) |  |

### `pages/admin/AdminAuditLogs.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/audit-logs` | `admin_routes.py:1451` | admin (any of 4 roles) |  |

### `pages/admin/AdminBenefits.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/benefits/programmes` | `vendor_benefits.py:111` | finance (super_admin/accounts_admin) |  |
| GET `/api/admin/benefits/proposals` | `vendor_benefits.py:185` | finance (super_admin/accounts_admin) |  |
| GET `/api/admin/benefits/eligibility` | `vendor_benefits.py:194` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/benefits/programmes` | `vendor_benefits.py:93` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/benefits/proposals` | `vendor_benefits.py:116` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/benefits/proposals/{gid}/decide` | `vendor_benefits.py:133` | finance (super_admin/accounts_admin) |  |

### `pages/admin/AdminCatalogue.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/pim/revisions` | `pim.py:401` | admin (any of 4 roles) |  |
| GET `/api/admin/pim/products/{product_id}/revision` | `pim.py:409` | admin (any of 4 roles) |  |
| POST `/api/admin/pim/products/{product_id}/revision/decision` | `pim.py:424` | vendor_admin (super_admin/admin) |  |
| GET `/api/admin/vendor-products` | `vendor_routes.py:1060` | admin (any of 4 roles) |  |
| POST `/api/admin/vendor-products/{product_id}/decision` | `vendor_routes.py:1073` | vendor_admin (super_admin/admin) |  |
| GET `/api/admin/pim/drafts` | `pim.py:350` | admin (any of 4 roles) |  |
| GET `/api/admin/vendors` | `vendor_routes.py:1012` | admin (any of 4 roles) |  |
| POST `/api/admin/pim/drafts` | `pim.py:367` | vendor_admin (super_admin/admin) |  |

### `pages/admin/AdminDashboard.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/dashboard` | `admin_routes.py:80` | admin (any of 4 roles) |  |

### `pages/admin/AdminKyc.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/kyc` | `admin_routes.py:639` | admin (any of 4 roles) |  |
| PUT `/api/admin/kyc/{user_id}` | `admin_routes.py:736` | admin (any of 4 roles) |  |
| PUT `/api/admin/kyc/{user_id}/edit` | `admin_routes.py:681` | finance (super_admin/accounts_admin) |  |

### `pages/admin/AdminMerchandising.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/merch/sections` | `merchandising.py:164` | admin (any of 4 roles) |  |
| POST `/api/admin/merch/sections/order` | `merchandising.py:241` | vendor_admin (super_admin/admin) |  |
| GET `/api/admin/merch/sections/{sid}/preview` | `merchandising.py:249` | admin (any of 4 roles) |  |
| POST `/api/admin/merch/sections/{sid}/status` | `merchandising.py:219` | vendor_admin (super_admin/admin) |  |
| GET `/api/catalog/products` | `discovery.py:144` | public |  |
| GET `/api/catalog/search` | `discovery.py:41` | public |  |
| PUT `/api/admin/merch/sections/{sid}` | `merchandising.py:200` | vendor_admin (super_admin/admin) |  |
| POST `/api/admin/merch/sections` | `merchandising.py:186` | vendor_admin (super_admin/admin) |  |

### `pages/admin/AdminOperations.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/finance/approvals` | `financial_approvals.py:77` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/finance/approvals/{approval_id}/approve` | `financial_approvals.py:85` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/finance/approvals/{approval_id}/reject` | `financial_approvals.py:118` | finance (super_admin/accounts_admin) |  |
| GET `/api/admin/refund-cases` | `returns_routes.py:240` | admin (any of 4 roles) |  |
| POST `/api/admin/refund-cases/{case_id}/action` | `returns_routes.py:273` | admin (any of 4 roles) |  |
| GET `/api/admin/returns` | `returns_routes.py:723` | admin (any of 4 roles) |  |
| POST `/api/admin/returns/{rid}/decision` | `returns_routes.py:737` | admin (any of 4 roles) |  |
| GET `/api/admin/finance/vendors` | `finance_routes.py:219` | admin (any of 4 roles) |  |
| GET `/api/admin/finance/settlements` | `finance_routes.py:387` | admin (any of 4 roles) |  |
| POST `/api/admin/finance/settlements/{sid}/action` | `finance_routes.py:328` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/finance/settlements` | `finance_routes.py:292` | finance (super_admin/accounts_admin) |  |
| GET `/api/admin/finance/cod-discrepancies` | `finance_routes.py:523` | admin (any of 4 roles) |  |
| POST `/api/admin/finance/cod-discrepancies/{order_id}/resolve` | `finance_routes.py:405` | finance (super_admin/accounts_admin) |  |
| GET `/api/admin/payments/duplicates` | `shop_routes.py:953` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/payments/duplicates/{order_id}/refunded` | `shop_routes.py:967` | finance (super_admin/accounts_admin) |  |
| GET `/api/admin/vendor-change-requests` | `governance_routes.py:217` | admin (any of 4 roles) |  |
| POST `/api/admin/vendor-change-requests/{rid}/decision` | `governance_routes.py:233` | admin (any of 4 roles) |  |
| GET `/api/admin/support/tickets` | `governance_routes.py:358` | admin (any of 4 roles) |  |
| POST `/api/admin/support/tickets/{tid}/reply` | `governance_routes.py:381` | admin (any of 4 roles) |  |

### `pages/admin/AdminOrderOps.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/order-ops/orders` | `admin_order_ops.py:97` | admin (any of 4 roles) |  |
| GET `/api/admin/order-ops/orders.csv` | `admin_order_ops.py:119` | admin (any of 4 roles) |  |
| GET `/api/admin/order-ops/orders/{order_id}` | `admin_order_ops.py:149` | admin (any of 4 roles) |  |
| PUT `/api/admin/orders/{order_id}/status` | `admin_routes.py:389` | admin (any of 4 roles) |  |
| GET `/api/admin/payment-events` | `payment_events.py:190` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/payment-events/{event_id}/retry` | `payment_events.py:207` | finance (super_admin/accounts_admin) |  |

### `pages/admin/AdminOrders.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/refund-queue` | `admin_routes.py:518` | admin (any of 4 roles) |  |
| GET `/api/admin/orders` | `admin_routes.py:361` | admin (any of 4 roles) |  |
| PUT `/api/admin/orders/{order_id}/status` | `admin_routes.py:389` | admin (any of 4 roles) |  |
| POST `/api/orders/{order_id}/cod-collected` | `shop_routes.py:293` | any signed-in user |  |
| POST `/api/admin/orders/{order_id}/refund` | `admin_routes.py:460` | finance (super_admin/accounts_admin) |  |
| DELETE `/api/admin/orders/{order_id}` | `admin_routes.py:548` | admin (any of 4 roles) |  |
| PUT `/api/admin/payments/upi-reject/{order_id}` | `shop_routes.py:986` | finance (super_admin/accounts_admin) |  |
| PUT `/api/admin/payments/upi-confirm/{order_id}` | `shop_routes.py:919` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/payments/manual` | `shop_routes.py:874` | finance (super_admin/accounts_admin) |  |

### `pages/admin/AdminProducts.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/products` | `admin_routes.py:220` | admin (any of 4 roles) |  |
| POST `/api/admin/products/{product_id}/stock` | `admin_routes.py:295` | admin (any of 4 roles) |  |
| POST `/api/admin/products/{product_id}/takedown/lift` | `admin_routes.py:335` | admin (any of 4 roles) |  |
| PUT `/api/admin/products/{product_id}` | `admin_routes.py:263` | admin (any of 4 roles) |  |
| POST `/api/admin/products` | `admin_routes.py:244` | admin (any of 4 roles) |  |
| DELETE `/api/admin/products/{product_id}` | `admin_routes.py:317` | admin (any of 4 roles) |  |
| DELETE `/api/admin/products/{product_id}/permanent` | `admin_routes.py:347` | admin (any of 4 roles) |  |
| POST `/api/admin/uploads/product-image` | `storage.py:113` | admin (any of 4 roles) |  |

### `pages/admin/AdminReports.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/reports/{report}` | `admin_routes.py:1485` | admin (any of 4 roles) |  |
| GET `/api/admin/reports/{report}/export` | `admin_routes.py:1494` | admin (any of 4 roles) |  |

### `pages/admin/AdminSettings.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/settings` | `admin_routes.py:944` | admin (any of 4 roles) |  |
| PUT `/api/admin/settings` | `admin_routes.py:998` | admin (any of 4 roles) |  |

### `pages/admin/AdminTeam.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/team` | `admin_team.py:45` | super_admin |  |
| POST `/api/admin/team` | `admin_team.py:61` | super_admin |  |
| PUT `/api/admin/team/{user_id}/role` | `admin_team.py:95` | super_admin |  |
| PUT `/api/admin/users/{user_id}/block` | `admin_routes.py:1191` | admin (any of 4 roles) |  |

### `pages/admin/AdminUsers.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/contact-changes` | `contact_change.py:217` | admin (any of 4 roles) |  |
| POST `/api/admin/contact-changes/{request_id}/cancel` | `contact_change.py:223` | admin (any of 4 roles) |  |
| POST `/api/admin/contact-changes/{request_id}/recovery-approve` | `contact_change.py:232` | admin (any of 4 roles) |  |
| GET `/api/admin/users` | `admin_routes.py:118` | admin (any of 4 roles) |  |
| GET `/api/admin/referral-codes` | `admin_routes.py:1025` | admin (any of 4 roles) |  |
| GET `/api/admin/registration-requests` | `admin_routes.py:1046` | admin (any of 4 roles) |  |
| GET `/api/admin/password-reset-requests` | `admin_routes.py:1438` | admin (any of 4 roles) |  |
| POST `/api/admin/users/{user_id}/reset-password` | `admin_routes.py:1397` | admin (any of 4 roles) |  |
| POST `/api/admin/password-reset-requests/{req_id}/dismiss` | `admin_routes.py:1443` | admin (any of 4 roles) |  |
| POST `/api/admin/registration-requests/{req_id}/approve` | `admin_routes.py:1126` | admin (any of 4 roles) |  |
| POST `/api/admin/registration-requests/{req_id}/reject` | `admin_routes.py:1144` | admin (any of 4 roles) |  |
| PUT `/api/admin/users/{user_id}` | `admin_routes.py:1271` | admin (any of 4 roles) |  |
| POST `/api/admin/wallet/credit` | `admin_routes.py:1347` | finance (super_admin/accounts_admin) |  |
| POST `/api/admin/referral-codes` | `admin_routes.py:1014` | admin (any of 4 roles) |  |
| DELETE `/api/admin/referral-codes/{code}` | `admin_routes.py:1030` | admin (any of 4 roles) |  |
| PUT `/api/admin/users/{user_id}/block` | `admin_routes.py:1191` | admin (any of 4 roles) |  |
| DELETE `/api/admin/users/{user_id}` | `admin_routes.py:1237` | admin (any of 4 roles) |  |

### `pages/admin/AdminVendorApplications.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/vendor-applications` | `vendor_applications.py:165` | super_admin/admin/support_admin |  |
| GET `/api/admin/vendor-applications/{aid}` | `vendor_applications.py:207` | super_admin/admin/support_admin |  |
| POST `/api/admin/vendor-applications/{aid}/action` | `vendor_applications.py:277` | vendor_admin (super_admin/admin) |  |
| PUT `/api/admin/vendor-applications/{aid}` | `vendor_applications.py:225` | vendor_admin (super_admin/admin) |  |

### `pages/admin/AdminVendorCreate.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/admin/vendors/create` | `vendor_routes.py:995` | vendor_admin (super_admin/admin) |  |

### `pages/admin/AdminVendorOnboarding.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/vendors/{vid}/onboarding` | `vendor_onboarding.py:508` | super_admin/admin/support_admin |  |
| GET `/api/admin/vendor-onboarding/options` | `vendor_onboarding.py:501` | super_admin/admin/support_admin |  |
| PUT `/api/admin/vendors/{vid}/onboarding/{section}` | `vendor_onboarding.py:521` | vendor_admin (super_admin/admin) |  |
| POST `/api/admin/vendors/{vid}/submit-for-approval` | `vendor_onboarding.py:624` | vendor_admin (super_admin/admin) |  |
| POST `/api/admin/vendors/{vid}/final-review` | `vendor_onboarding.py:654` | super_admin |  |
| POST `/api/admin/vendors/{vid}/owner-access` | `vendor_onboarding.py:701` | super_admin |  |
| POST `/api/admin/vendors/{vid}/onboarding/documents` | `vendor_onboarding.py:598` | vendor_admin (super_admin/admin) |  |
| POST `/api/admin/vendor-documents/{doc_id}/review` | `governance_routes.py:160` | admin (any of 4 roles) |  |

### `pages/admin/AdminVendors.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/vendors` | `vendor_routes.py:1012` | admin (any of 4 roles) |  |
| GET `/api/admin/vendor-products` | `vendor_routes.py:1060` | admin (any of 4 roles) |  |
| POST `/api/admin/vendors/{vendor_id}/decision` | `vendor_routes.py:1032` | vendor_admin (super_admin/admin) |  |
| POST `/api/admin/vendor-products/{product_id}/decision` | `vendor_routes.py:1073` | vendor_admin (super_admin/admin) |  |

### `pages/admin/AdminWithdrawals.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/admin/withdrawals` | `admin_routes.py:776` | admin (any of 4 roles) |  |
| PUT `/api/admin/withdrawals/{wd_id}` | `admin_routes.py:807` | finance (super_admin/accounts_admin) |  |

### `pages/vendor/VendorAdvancement.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/reports/advancement` | `vendor_reports.py:226` | approved vendor (owner/staff) | reports.read |
| GET `/api/vendor/advancement/eligibility` | `vendor_benefits.py:212` | approved vendor (owner/staff) | staff refused (owner-only) |

### `pages/vendor/VendorAnalytics.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/dashboard` | `vendor_dashboard.py:78` | approved vendor (owner/staff) | reports.read |

### `pages/vendor/VendorApply.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/settings/public` | `server.py:41` | public |  |
| POST `/api/vendor-applications/send-otp` | `vendor_applications.py:93` | public |  |
| POST `/api/vendor-applications` | `vendor_applications.py:108` | public |  |

### `pages/vendor/VendorAuth.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/auth/login` | `auth_routes.py:333` | public |  |

### `pages/vendor/VendorCod.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/finance/cod` | `finance_routes.py:167` | approved vendor (owner/staff) | finance.read |

### `pages/vendor/VendorDashboard.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/dashboard` | `vendor_dashboard.py:78` | approved vendor (owner/staff) | reports.read |

### `pages/vendor/VendorDispatch.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/orders` | `vendor_routes.py:772` | approved or suspended vendor (owner/staff) | orders.read |

### `pages/vendor/VendorFinance.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/finance/summary` | `finance_routes.py:54` | approved vendor (owner/staff) | finance.read |
| GET `/api/vendor/finance/ledger` | `finance_routes.py:65` | approved vendor (owner/staff) | finance.read |
| GET `/api/vendor/finance/settlements` | `finance_routes.py:76` | approved vendor (owner/staff) | finance.read |
| GET `/api/vendor/finance/statement.csv` | `finance_routes.py:95` | approved vendor (owner/staff) | finance.export |

### `pages/vendor/VendorInventory.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/products` | `vendor_routes.py:359` | approved vendor (owner/staff) | products.read |
| POST `/api/vendor/products/{product_id}/stock` | `vendor_routes.py:525` | approved vendor (owner/staff) | inventory.adjust |
| GET `/api/vendor/products/{product_id}/stock-history` | `vendor_routes.py:695` | approved vendor (owner/staff) | inventory.read |

### `pages/vendor/VendorNotifications.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/notifications` | `governance_routes.py:405` | vendor owner or staff | any active member |
| POST `/api/notifications/read-all` | `wallet_routes.py:212` | any signed-in user |  |
| POST `/api/notifications/{nid}/read` | `wallet_routes.py:206` | any signed-in user |  |

### `pages/vendor/VendorOrders.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/orders` | `vendor_routes.py:772` | approved or suspended vendor (owner/staff) | orders.read |

### `pages/vendor/VendorOwnerInvite.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/invitation/owner` | `vendor_invitations.py:115` | public | staff refused (owner-only) |
| POST `/api/vendor/invitation/owner/accept` | `vendor_invitations.py:124` | public | staff refused (owner-only) |

### `pages/vendor/VendorProductStudio.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/vendor/pim/drafts` | `pim.py:306` | approved vendor (owner/staff) | products.create or products.edit |

### `pages/vendor/VendorProducts.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/products` | `vendor_routes.py:359` | approved vendor (owner/staff) | products.read |
| GET `/api/vendor/pim/drafts` | `pim.py:299` | approved vendor (owner/staff) | products.read |
| POST `/api/vendor/products/{product_id}/listing` | `vendor_routes.py:705` | approved vendor (owner/staff) | products.archive |
| POST `/api/vendor/products/{product_id}/archive` | `vendor_routes.py:557` | approved vendor (owner/staff) | products.archive |
| GET `/api/vendor/products/export.csv` | `vendor_routes.py:569` | approved vendor (owner/staff) | products.read |

### `pages/vendor/VendorProfile.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/me/profile-overview` | `vendor_routes.py:166` | vendor owner or staff | staff refused (owner-only) |
| PUT `/api/vendor/me` | `vendor_routes.py:201` | vendor owner or staff | staff refused (owner-only) |

### `pages/vendor/VendorReports.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/reports/current` | `vendor_reports.py:157` | approved vendor (owner/staff) | reports.read |
| GET `/api/vendor/reports/current.csv` | `vendor_reports.py:163` | approved vendor (owner/staff) | reports.export |

### `pages/vendor/VendorReturns.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/returns/{rid}` | `returns_routes.py:618` | approved or suspended vendor (owner/staff) | returns.read |
| POST `/api/vendor/returns/{rid}/action` | `returns_routes.py:633` | approved or suspended vendor (owner/staff) | returns.respond |
| POST `/api/vendor/returns/{rid}/inspection` | `returns_routes.py:677` | approved or suspended vendor (owner/staff) | returns.inspect |
| GET `/api/vendor/returns` | `returns_routes.py:599` | approved or suspended vendor (owner/staff) | returns.read |

### `pages/vendor/VendorSecurity.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| PUT `/api/auth/change-password` | `governance_routes.py:438` | any signed-in user |  |

### `pages/vendor/VendorStaff.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/staff` | `vendor_staff_routes.py:60` | vendor OWNER only | staff refused (owner-only) |
| POST `/api/vendor/staff/invitations` | `vendor_staff_routes.py:78` | vendor OWNER only | staff refused (owner-only) |
| POST `/api/vendor/staff/{mid}/resend` | `vendor_staff_routes.py:102` | vendor OWNER only | staff refused (owner-only) |
| PUT `/api/vendor/staff/{mid}` | `vendor_staff_routes.py:116` | vendor OWNER only | staff refused (owner-only) |
| POST `/api/vendor/staff/{mid}/suspend` | `vendor_staff_routes.py:145` | vendor OWNER only | staff refused (owner-only) |
| POST `/api/vendor/staff/{mid}/reactivate` | `vendor_staff_routes.py:155` | vendor OWNER only | staff refused (owner-only) |
| DELETE `/api/vendor/staff/{mid}` | `vendor_staff_routes.py:165` | vendor OWNER only | staff refused (owner-only) |

### `pages/vendor/VendorStaffInvite.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/staff/invitation` | `vendor_staff_routes.py:184` | public | staff refused (owner-only) |
| POST `/api/vendor/staff/accept` | `vendor_staff_routes.py:199` | public | staff refused (owner-only) |

### `pages/vendor/VendorSupport.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| POST `/api/vendor/support/tickets` | `governance_routes.py:293` | approved vendor (owner/staff) | staff refused (owner-only) |
| GET `/api/vendor/support/tickets/{tid}` | `governance_routes.py:329` | approved vendor (owner/staff) | staff refused (owner-only) |
| POST `/api/vendor/support/tickets/{tid}/reply` | `governance_routes.py:344` | approved vendor (owner/staff) | staff refused (owner-only) |
| GET `/api/vendor/support/tickets` | `governance_routes.py:313` | approved vendor (owner/staff) | staff refused (owner-only) |

### `pages/vendor/VendorTerms.js`
| Call (method path) | Served by | Guard | Staff permission |
|---|---|---|---|
| GET `/api/vendor/finance/terms` | `commercial_routes.py:34` | approved vendor (owner/staff) | finance.read |
| POST `/api/vendor/finance/terms/{aid}/accept` | `commercial_routes.py:40` | approved vendor (owner/staff) | staff refused (owner-only) |

