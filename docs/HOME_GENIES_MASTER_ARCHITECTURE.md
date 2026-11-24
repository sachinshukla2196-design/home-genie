# HOME GENIES — Master architecture (Programme 00 baseline)

Baseline: `main` @ `d31cb74` (= `origin/main`), clean working tree, 2026-11-23. Inspection only; no code, schema, configuration or
production system was changed. Companion documents (all Programme 00):

| Document | Scope |
|---|---|
| `HOME_GENIES_MODULE_COMPLETION_MATRIX.md` | modules A–O, sub-capabilities, status 1–9, priority |
| `HOME_GENIES_FRONTEND_BACKEND_MAP.md` | every screen → API → guard |
| `HOME_GENIES_DATABASE_ARCHITECTURE.md` | collections, references, indexes, migrations, sensitive data |
| `HOME_GENIES_PERMISSION_MATRIX.md` | roles × sensitive actions with the enforcing guard |
| `HOME_GENIES_INTEGRATION_REGISTER.md` | every external dependency and its configuration |
| `HOME_GENIES_END_TO_END_WORKFLOW_AUDIT.md` | customer, HomeGenie, vendor, admin journeys traced in code |
| `HOME_GENIES_FINANCIAL_ARCHITECTURE_AUDIT.md` | money flows, idempotency, reconciliation |
| `HOME_GENIES_SECURITY_AND_RELIABILITY_AUDIT.md` | vulnerabilities and operational reliability |
| `HOME_GENIE_MARKETING_STUDIO_ARCHITECTURE.md` | the new Marketing & Social Commerce module (design only) |
| `HOME_GENIES_MASTER_IMPLEMENTATION_BACKLOG.md` | every gap ranked P0–P3 with dependencies and the batch sequence |

## 1. System overview

```
 Browser (React 19 SPA, CRACO build)                         Vercel project "frontend"  (REACT_APP_BACKEND_URL baked at build)
   ├─ Public: landing, login / OTP / Google, register, vendor apply / invitations, legal
   ├─ /app/*     customer + HomeGenie member (MemberOnly guard hides HomeGenie screens from customers)
   ├─ /vendor/*  vendor owner + staff (VendorGate, permission-aware menu)
   └─ /admin/*   platform admins (AdminLayout)
          │  HTTPS JSON, Bearer JWT (localStorage "anj_token")
          ▼
 FastAPI app (backend/server.py, 29 routers, 293 routes)       Vercel project "backend" (Python function server.py, 60 s limit)
   ├─ core.py: JWT, current-user gates, rate limits, client IP, audit log, notifications, settings, sequences
   ├─ domain modules (see §3)
   └─ Vercel cron (backend/vercel.json): 20:00 UTC /api/cron/release-points, 20:30 UTC /api/cron/expire-pending-orders
          │  Motor (async)                                   External: Razorpay, Stripe, Twilio SMS, Emergent email /
          ▼                                                   storage / Google identity, Cloudinary, postalpincode (browser)
 MongoDB (Atlas in production; collections listed in DATABASE_ARCHITECTURE; indexes applied by scripts/vendor_foundation_migrate.py)
```

Stack (verified in `frontend/package.json`, `backend/requirements.txt`): React 19.0.0, react-router-dom 7.15, Tailwind 3.4, CRACO 7.1,
axios 1.18 · FastAPI 0.110.1, Motor 3.3.1 / PyMongo 4.6.3, Pydantic 2.13, PyJWT 2.13, bcrypt 4.1, razorpay 2.0.1, stripe 14.4.1,
twilio 9.11, httpx 0.28. Size: backend ≈ 16,000 lines in 44 modules; frontend ≈ 16,800 lines, 70 pages, 83 routes; 72 test files.

## 2. Ecosystems and their entry points
| Ecosystem | Role values | Frontend | Main backend modules |
|---|---|---|---|
| Customer | `customer` (CU ids) | `/app/*` without HomeGenie screens | shop_routes, customer_routes, discovery, returns_routes, merchandising (read) |
| HomeGenie member | `distributor` (red / green) | `/app/*` incl. wallet, KYC, referral, rewards | wallet_routes, commission, homegenie_metrics, activation_routes |
| Vendor | `vendor` owner, `vendor_staff` (vendor_members) | `/vendor/*` | vendor_routes, pim, stock, vendor_staff(_routes), finance_routes (vendor), governance_routes, vendor_onboarding / applications / invitations, vendor_dashboard / reports / benefits, commercial_terms |
| Platform admin | `super_admin`, `admin`, `accounts_admin`, `support_admin` | `/admin/*` | admin_routes, admin_team, admin_order_ops, financial_approvals, finance_routes, returns_routes, pim (review), merchandising, payment_events, contact_change |

## 3. Backend module map (responsibility · size in lines)
| Area | Modules |
|---|---|
| Platform core | `core` 526 (auth gates, rate limits, audit, notifications), `server` 353 (startup, CORS, headers, error handler), `db_indexes` 233, `pagination`, `validators`, `money` |
| Identity | `auth_routes` 823 (register / login / OTP / Google / recovery / admin login), `providers` 197 (SMS / OTP), `contact_change` 245, `admin_team` 111, `governance_routes` 513 |
| Commerce | `shop_routes` 1006 (catalogue read, orders, payments, UPI, COD confirm, refunds engine), `stock` 605 (reservation journal, expiry, recovery), `customer_routes` 313, `discovery` 149, `merchandising` 252 |
| Payments | `payment_events` 225 (Razorpay webhook reconciliation), Stripe in `shop_routes`, `cod_rules` 231 |
| Money | `commission` 394, `eligibility` 77, `financial_ops` 108, `financial_approvals` 132, `ledger` 225, `finance_routes` 529, `wallet_routes` 309, `wallet_reconcile` 131, `commercial_terms` 126, `historical_audit` 229, `money_migration` 116 |
| Returns & refunds | `returns_routes` 752 |
| Catalogue | `pim` 474, `catalogue` 216, `catalogue_templates` 147, product parts of `vendor_routes` and `admin_routes` |
| Vendor | `vendor_routes` 1118, `vendor_onboarding` 705, `vendor_applications` 349, `vendor_invitations` 138, `vendor_lifecycle` 127, `vendor_staff` 203, `vendor_staff_routes` 227, `vendor_dashboard` 215, `vendor_reports` 289, `vendor_benefits` 221 |
| Admin | `admin_routes` 1507, `admin_order_ops` 201, `activation_routes` 109 |
| HomeGenie analytics | `homegenie_metrics` 198 |
| Storage | `storage` 129 (Emergent object storage, Cloudinary signing) |
| Jobs | `cron_routes` (release-points; expire-pending-orders = expiry + recovery + case repair + returns / ledger / settlement reconcile + dispatch alerts) |

## 4. Cross-cutting mechanisms (verified)
- **Money** is integer paise everywhere it is computed; float fields remain for display and history.
- **Idempotency**: unique keys (ledger `source_key`, wallet `op_key`, refund `order_refunds._id`, `financial_approvals._id`,
  `webhook_events.event_id`, `commission_plans._id`, stock journal) **only exist after the index migration runs** — startup only
  logs missing indexes (P0 until the production migration is confirmed, see backlog B-004).
- **State changes** use compare-and-set updates (orders, settlements, approvals, refund cases, drafts, webhook claims).
- **Two-person rules**: wallet credits, vendor adjustments, refund confirmation, settlement approve / pay, withdrawals approve / pay,
  KYC edit vs verify, admin-prepared products. Several money actions remain single-person (see permission matrix).
- **Payout eligibility**: `eligibility.payout_block` (delivery from vendor fulfilments + return window + no open case / refund /
  payment issue), shared by commission release and vendor settlement.
- **Audit**: `core.log_audit` → `audit_logs` (no index, no retention; not written on every money path — see financial audit).
- **Jobs**: two daily crons; expiry / recovery sweeps also run when orders are viewed. Hourly-granular expiry is not guaranteed.

## 5. Verified test baseline (this programme)
Full in-process regression run on `d31cb74` against the isolated test MongoDB: **62 suites, 1,290 passed, 2 failed, 0 skipped**.
The 2 failures (`test_vendor_foundation::test_profile_api_ignores_any_status_sent_by_the_vendor`,
`::test_active_vendor_keeps_selling_access_and_contact_only_edits`) are a **Batch 14 regression now on main**: the new vendor
contact validation (`vendor_routes._validate_contact`) rejects a stored state abbreviation (`"RJ"`), so approved vendors with such a
state cannot save contact changes (backlog B-008). The seven server-dependent suites were not re-run in this programme (last result
Batch 13: 96 passed, 6 skipped with reasons).

## 6. Deployment and environments (from the repo only)
- Two Vercel projects (frontend, backend); `main` auto-deploys. Preview deployments may point at the production API
  (`deploy/ENVIRONMENT.md`) — environment separation is not enforced.
- `deploy/vercel-api/` is a stale, git-ignored copy of the backend (differs from `backend/` in 11 of 12 files; missing `stripe` and
  the second cron) — deploying from it would break the API.
- Not present in the repo: backups / restore tooling, error monitoring, uptime / cron alerting, CSP for the frontend.

## 7. Where the evidence lives
Every finding in the companion documents cites file paths, functions, routes, collections or tests. Items marked "suspicion" or
"cannot be verified from the repo" (production credentials, hosting topology, Emergent-hosted behaviour) need owner confirmation.
