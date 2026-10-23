# HOME GENIES — Vendor Panel: audit and phased plan

Audited against the repository at commit `fcc88e3` (plus local Phase A changes). Evidence = code read +
live probes against the local test database + automated tests. Nothing here was verified on production
(the production backend cannot yet reach its database).

Legend: **Done** (implemented and tested) · **Works** (implemented, not yet covered by tests) ·
**Partial** · **Missing** · **Pending decision** (needs owner approval before building).

## 1. Baseline verified
React 19 (CRA/craco) + FastAPI + MongoDB (Motor), Vercel, English/Hindi. Vendor code: `backend/vendor_routes.py`
(537 lines, 18 endpoints), `frontend/src/pages/vendor/*` (5 pages), `frontend/src/components/VendorLayout.js`.
Vendor orders are not a separate collection: each order has a `fulfilments[]` array, one entry per vendor.

## 2. Findings

### Working
| Area | Evidence |
|---|---|
| Vendor sign-up / login, draft → submitted → approved / rejected / suspended / reinstated | code; admin decisions are audited and notify the vendor |
| Tenant isolation (products, stock, history, listing, orders, fulfilment) | **9 automated tests + live probe**: every cross-vendor request returns 404 |
| Role and approval gating (customer, HomeGenie, draft, suspended vendors refused; no token = 401) | automated test |
| Four locked pillars enforced server-side | code + test |
| New/changed product goes to admin review and stays hidden until approved; vendor cannot self-list | automated test |
| Stock cannot go negative; every manual change needs a reason and is logged with before/after | automated test |
| Last unit cannot be oversold by two simultaneous orders (atomic conditional update) | automated test (200 + 409, stock 0) |
| Fulfilment state machine (new → accepted → packed → dispatched → delivered), replay-safe, tracking and delivery evidence required, reject/cancel restock exactly once | automated test |
| COD: vendor cannot confirm cash; delivered ≠ paid | automated test |
| Bank account / PAN masked for vendors; legal/bank edits blocked after approval | code |
| Audit log on sensitive vendor actions; in-app notifications | code |
| EN/HI: all vendor pages use `t()` | code (no hard-coded strings found) |

### Broken or inconsistent
1. **Unvalidated product images** — any string (`javascript:`, `http://`, `data:`) was accepted. **Fixed in Phase A** (`vendor_routes.py`, tested).
2. **Stock leak on abandoned/failed online payments** — stock is reserved at order placement and only a *vendor* reject/cancel/return-to-origin restocked. **Fixed in Phase A2 for unpaid online orders** (15-minute window, `backend/stock.py`, 13 tests + mutation checks). **A2 follow-up:** confirmed admin cancellation (status change or refund-with-cancel) now restocks goods that have not left; returned goods restock only after the vendor records receipt + inspection. **Still open:** customer-initiated cancellation/returns after delivery (no workflow exists yet).
3. ~~Dashboard "gross this month" includes unpaid COD orders~~ **Fixed in the A2 follow-up:** the dashboard now shows order value, collected (paid) and unpaid-COD separately, in exact decimal arithmetic; `gross_this_month` stays only as a deprecated alias.
4. **COD collection sets the parent order to "delivered" regardless of the vendor's fulfilment state**, and vendor roll-up also sets "delivered": two writers for one status.
5. **Money uses floats** (`orders`, `commission.py`) — brief requires exact decimal / integer-paise arithmetic.
6. Possible 500 on a duplicate-SKU double submit (pre-check then insert; unique index exists, `DuplicateKeyError` not caught). Low risk.

### Partial
- Dashboard: counts only; low-stock threshold hard-coded (≤5); no date range, trends, action centre, or clickable KPIs.
- Orders list: status filter only, capped at 500, no search/pagination/date filter; no order timeline view beyond `events`.
- Onboarding: no "under review", no status history or resubmission history (only last reason), no contact verification, no document upload; no path to change bank details after approval.
- Products: `options` is a free-form list; stock is per product, not per variant; no category attributes, shipping dimensions, compliance fields.
- Product images: vendors can only paste a URL — the upload endpoints are admin-only (`/admin/uploads/product-image`) or profile-photo.
- Delivery/tracking is manual text only (no courier integration, no proof file).
- Admin refund exists (`/admin/orders/{id}/refund`) but is not connected to vendor records or stock.

### Missing
Variants with their own SKU/stock · bulk CSV import/export · returns/replacements workflow · vendor ledger,
settlements, reconciliation, statements · analytics beyond counts · support tickets · vendor KYC documents ·
action centre · vendor staff roles · automated vendor frontend tests · rate limiting on vendor sign-up.

### Security
- No horizontal-escalation gap found (tested). Sessions are revocable (`iat` vs `password_changed_at`).
- Token lives in `localStorage` (XSS-exposed by design); CORS locked to explicit origins.
- Gap: unvalidated image strings (fixed). Gap: no sign-up rate limit / captcha.
- Not yet reviewed: file-upload hardening beyond type/size checks (content sniffing), PII exposure in order `ship_to` (needed for dispatch, but not masked).

### Third-party / Emergent dependencies
Google sign-in (`demobackend.emergentagent.com`) · object storage and image upload (`EMERGENT_LLM_KEY`,
`integrations.emergentagent.com`) · outbound email (`EMERGENT_EMAIL_KEY`) · `emergentintegrations` (replaced on Vercel by the official Stripe SDK) ·
analytics scripts in `frontend/public/index.html`. Vendor image upload will depend on storage, so a decision on storage is needed.

### Must not break
Order creation and atomic stock reservation, the fulfilment state machine, `/api/vendor/*` contracts used by
the 5 existing pages, commission logic (`commission.py`) and COD collection, admin vendor/product approval,
the four pillars, EN/HI.

## 3. Data-model changes needed (none applied yet; all additive)
| Change | Why |
|---|---|
| `vendor_status_history` (vendor_id, from, to, reason, actor, at) | onboarding history, resubmissions |
| `product_variants` (product_id, sku, attributes, stock, price) + `stock_movements.variant_id` | SKU-level stock |
| `vendor_ledger` (immutable, integer paise, idempotency key, reversal link, policy version) | finance |
| `settlements` (vendor_id, period, entry refs, status, reference) | finance |
| `return_cases` (order, line, reason, state, timeline) | returns/replacements |
| `support_tickets` + messages | vendor support |
| `vendor_documents` (type, file ref, status, reviewer) | KYC/compliance |
| indexes: `orders.fulfilments.vendor_id`, `products.vendor_id`, `stock_movements.product_id`, ledger `(vendor_id, posted_at)`, unique ledger idempotency key | performance and integrity |
Rollback: all new collections are additive; removing them leaves the current app unchanged.

## 4. Phased plan
| Phase | Scope | Status |
|---|---|---|
| **A** Audit & stabilise | This audit; baseline vendor test suite (9 tests); image validation fix | **Done** (local, uncommitted) |
| **A2 follow-up** | Confirmed-cancellation restock; return inspection; late-payment hold + admin Needs-refund queue; money split on dashboard; pagination + search on vendor lists; Cloudinary plan (§6) | **Done** (local, uncommitted) except Cloudinary (plan only) |
| **A2** | 15-minute expiry of unpaid online orders with atomic, idempotent release; late-payment handling; shared per-line release for vendor reject; duplicate-SKU race fixed; image validation extended | **Done** (local, uncommitted). Remaining: vendor image upload (storage decision), pagination/search on vendor lists, restock on admin/customer cancel and refunds (decision 1b) |
| **B** Vendor core | Dashboard KPIs with separated definitions + action centre; onboarding status history; product form sections; variants + per-variant stock; low-stock threshold | Pending |
| **C** Operations | Order detail/timeline, filters; COD tracking view (read-only for vendor); manual shipping workflow | Pending |
| **D** Finance | Ledger + settlement *visibility* only; entries posted only under an approved policy | Pending decision |
| **E** Service & growth | Returns/replacements, analytics, support tickets, compliance centre | Pending decision |
| **F** Production readiness | Security review, e2e tests, monitoring, deployment verification (needs Atlas access fixed) | Pending |

## 5. Decisions needed from the owner (not guessed)
1. **Stock reservation**: *answered* — unpaid online orders expire after 15 minutes; COD keeps stock once created. **1b (open):** should stock be restored when an admin/customer cancels, or when a paid/COD order is refunded or returned? And what happens to a customer who pays after the 15 minutes (implemented provisionally: stock re-reserved if available, else flagged `needs_refund` for admin)?
2. **Order state machine**: approve the current vendor states, or the longer candidate lifecycle in the brief.
3. **Finance**: commission funding (vendor vs platform), settlement schedule, reserves, deductions, thresholds — until approved, the ledger will show *sales and refunds only* with no payout logic.
4. **Returns**: window (7 days is provisional), category exclusions, who pays return shipping.
5. **Vendor pricing**: can vendors set selling price freely, or is it admin-controlled?
6. **Storage / auth provider** for vendor images and documents (currently Emergent).
7. **Vendor staff roles**: build now or later.

## 6. Cloudinary vendor image uploads — secure plan (not implemented)
**Goal:** vendors upload product images to Cloudinary. The `images: [string]` field does not change, so **no migration** and
every existing value keeps working (`/api/files/…`, `/brand/…`, any `https://…`, already validated by `_safe_images`).

**Flow (signed, direct-from-browser upload)**
1. UI: the vendor picks a file; the client checks type (jpeg/png/webp) and size (≤ 5 MB) for UX only.
2. `POST /api/vendor/uploads/sign` — approved vendors only (same guard as the other vendor routes), rate-limited per vendor
   (e.g. 30/hour, counter in MongoDB), audited. The **server** chooses everything that matters: `folder =
   homegenies/vendors/{vendor_id}/products`, a random `public_id` (uuid), `overwrite=false`, `allowed_formats=jpg,png,webp`,
   `upload_preset` (a *signed* preset created in the Cloudinary console with a max file size, format allow-list, locked folder,
   EXIF stripping), and `timestamp`. It signs them with `CLOUDINARY_API_SECRET` and returns
   `{cloud_name, api_key, timestamp, signature, folder, public_id, upload_preset}`. The client cannot pick the folder or id.
3. The browser POSTs the file straight to `https://api.cloudinary.com/v1_1/<cloud>/image/upload`. Bytes never pass through
   Vercel (which would otherwise cap request bodies at ~4.5 MB) and the API secret never reaches the browser.
4. On product create/update the backend validates each image reference. Existing rules stay. **New rule for Cloudinary
   hosts:** the host must be `res.cloudinary.com`, the path must start with `/<our cloud>/image/upload/` and contain
   `/homegenies/vendors/<this vendor's id>/`, so a vendor cannot attach someone else's or a third-party Cloudinary asset.
   Optionally the server confirms with one Cloudinary Admin-API call that the asset exists, is an image, and is within limits.
5. Rendering: the shop rewrites the stored URL to add `f_auto,q_auto,w_…` at display time; the stored value is untouched.

**Controls:** short-lived signature (Cloudinary rejects > 1 h); no unsigned preset; no SVG/GIF; per-vendor folders;
audit entry `vendor_image_signed`; CSP `img-src res.cloudinary.com`, `connect-src api.cloudinary.com`; no Cloudinary secret in any
`REACT_APP_*` variable. Orphaned uploads (uploaded, product never saved) cleaned by a periodic job comparing the vendor folder
with referenced images.

**Environment (backend / Vercel only):** `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`,
`CLOUDINARY_UPLOAD_PRESET`. If any is missing the sign endpoint returns 503 "uploads not configured" and the UI keeps today's
paste-a-URL field, so nothing breaks before the account exists.

**Tests to write with it:** sign endpoint refuses customers/HomeGenies/draft/suspended vendors and anonymous callers;
client-supplied folder/public_id are ignored; the signature verifies against a known test secret; rate limit trips; validator
accepts own-folder URLs and rejects another vendor's folder, another cloud, `http://`; legacy paths still pass; frontend uploader
test with a mocked `fetch`.

**Rollout:** (1) backend sign + validator behind the env check, (2) uploader in the product form, (3) orphan cleanup.

**Decisions needed:** who owns the Cloudinary account and plan (free tier is credit-limited); whether to later restrict images to an
allow-list of hosts (this would reject arbitrary `https://` values some products may already use, so it needs approval);
moderation add-on; max images and size per product.
