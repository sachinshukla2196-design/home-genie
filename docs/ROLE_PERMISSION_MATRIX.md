# HOME GENIES — Role and permission matrix

Two separate permission systems that never mix: **vendor team** (a vendor owner and its staff, scoped to that vendor) and the
**platform admin team** (HOME GENIES staff). The server decides every request; menus only mirror it.

## Vendor team (Batch 12, Phase 5)

- **Owner** (`role: vendor`): everything for its own vendor, including the owner-only areas staff can never reach: team, business
  profile, bank details and changes, documents, support tickets, advancement.
- **Staff** (`role: vendor_staff` + a `vendor_members` row): only what the membership's permissions open, checked on every request
  (`vendor_staff.authorize_staff`): the membership must be active, the owner account active (C-17), the request must match a rule
  and the member must hold that rule's permission. Anything without a rule is refused. Fulfilment steps are checked per step
  (`FULFILMENT_PERMISSION`); studio drafts check create vs edit in the handler.
- **Backward compatibility:** the original coarse permissions (`products.write`, `inventory.write`, `orders.fulfil`, `returns.act`)
  stay valid and imply the fine ones (`LEGACY_IMPLIES`); presets created before Batch 12 keep their exact access. No migration.
- **Only the owner** invites, changes, suspends, reactivates or revokes staff, so staff can never grant themselves or others more.
  Every change is audited (`vendor_staff_invited / _role_changed / _suspended / _reactivated / _revoked / _joined`).
- Money is **read only** for every staff role; no staff role can request, approve or receive a payout.

### Presets (effective permissions)

| Permission | Risk | Store manager | Catalogue manager | Product editor | Inventory manager | Warehouse staff | Order manager | Packing staff | Dispatch staff | Returns manager | Customer support | Finance viewer | Reports viewer |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `products.read` — See products | low | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| `products.create` — Prepare new products | low | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| `products.edit` — Prepare product changes | low | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| `products.submit` — Send products for review | medium | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| `products.archive` — Pause, resume and archive | medium | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| `inventory.read` — See stock | low | ✓ | ✓ |  | ✓ | ✓ |  |  |  |  |  |  |  |
| `inventory.adjust` — Adjust stock | medium | ✓ |  |  | ✓ |  |  |  |  |  |  |  |  |
| `orders.read` — See orders | medium | ✓ |  |  |  | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |
| `orders.accept` — Accept or decline orders | high | ✓ |  |  |  |  | ✓ |  |  |  |  |  |  |
| `orders.pack` — Mark orders packed | low | ✓ |  |  |  | ✓ | ✓ | ✓ |  |  |  |  |  |
| `orders.dispatch` — Dispatch and delivery updates | medium | ✓ |  |  |  |  | ✓ |  | ✓ |  |  |  |  |
| `returns.read` — See returns | low | ✓ |  |  |  |  | ✓ |  |  | ✓ | ✓ |  |  |
| `returns.respond` — Respond to returns | high | ✓ |  |  |  |  |  |  |  | ✓ |  |  |  |
| `returns.inspect` — Inspect returned goods | medium | ✓ |  |  |  |  |  |  |  | ✓ |  |  |  |
| `reports.read` — See dashboard and reports | medium | ✓ |  |  |  |  |  |  |  |  |  | ✓ | ✓ |
| `reports.export` — Download reports | medium |  |  |  |  |  |  |  |  |  |  |  |  |
| `finance.read` — See earnings and settlements | high |  |  |  |  |  |  |  |  |  |  | ✓ |  |
| `finance.export` — Download statements | high |  |  |  |  |  |  |  |  |  |  |  |  |

Older presets kept for existing members (not offered for new invitations): Product manager (older role), Inventory staff (older role).
Custom roles may hold any subset of the permissions above (legacy names accepted for compatibility).

### Endpoint → permission (staff)

| Area | Endpoint | Permission |
|---|---|---|
| Products | `GET /vendor/products`, export, template, catalogue spec, studio drafts list / get, revision | `products.read` |
| Products | `POST /vendor/pim/drafts` (new) · (for an existing product) | `products.create` · `products.edit` |
| Products | `PUT /vendor/pim/drafts/{id}`, `DELETE` | `products.create` (new) / `products.edit` (existing) |
| Products | `POST /vendor/pim/drafts/{id}/submit`, `POST /vendor/products`, import, `PUT /vendor/products/{id}` | `products.submit` |
| Products | `POST /vendor/products/{id}/listing`, `/archive` | `products.archive` |
| Products | `POST /vendor/uploads/sign` | `products.create` or `products.edit` |
| Inventory | stock history · stock adjustment | `inventory.read` · `inventory.adjust` |
| Orders | list / detail | `orders.read` |
| Orders | fulfilment → accepted / rejected / cancelled · packed · dispatched / delivered / delivery_failed / returned_to_origin | `orders.accept` · `orders.pack` · `orders.dispatch` |
| Returns | list / detail · action · inspection (incl. order return-inspection) | `returns.read` · `returns.respond` · `returns.inspect` |
| Reports | dashboard, reports · any `.csv` | `reports.read` · `reports.export` |
| Money | finance summary / ledger / settlements / COD / terms · statement `.csv` | `finance.read` · `finance.export` |
| Owner only | staff, profile, bank, documents, support, advancement | — |

Tested by `tests/test_staff_permissions_batch12.py` (every preset × every sensitive endpoint, step-by-step fulfilment, legacy
members) and `tests/test_vendor_staff.py`.

## Platform admin team

| Role | Money authority | Notes |
|---|---|---|
| super_admin | yes (finance) | final vendor approval (S-6); Admin Team management; protected from reset / block |
| admin | no | vendor lifecycle (with super_admin), catalogue review, COD cash confirmation today (D-03 open) |
| accounts_admin | yes (finance) | payment confirmation, refunds (confirm), approvals (checker), settlements, withdrawals |
| support_admin | no | read + support; cannot reset credentials (S-10), cannot block / delete vendor accounts (C-17) |

Two-person rules: wallet credits and vendor adjustments (maker ≠ checker); refunds (initiator(s) ≠ confirmer); settlements
(creator ≠ approver, approver ≠ payer; creator = payer is open decision D-02); withdrawals (approver ≠ payer); KYC (editor ≠
verifier); products an admin prepares for a vendor (preparer ≠ approver).

Expanding platform roles (Finance Admin, Catalogue Admin, Vendor / Customer Operations, Reports Viewer, custom platform roles) is
**BLOCKED BY OWNER DECISION D-16** because each needs a decision on money authority. The vendor permission engine above is the
pattern that would be reused.
