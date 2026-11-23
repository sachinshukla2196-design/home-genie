# HOME GENIES — Product information management (specification as built)

Code: `backend/catalogue_templates.py` (data), `backend/catalogue.py` (field validation), `backend/pim.py` (drafts, submission,
review), `backend/vendor_routes.py` (`create_vendor_product`, `apply_product_update`), frontend
`components/catalogue/ProductStudio.js`, `pages/vendor/VendorProductStudio.js`, `pages/admin/AdminCatalogue.js`.
Tests: `tests/test_pim_batch12.py`, `tests/test_catalogue_batch3.py`, staff matrix in `tests/test_staff_permissions_batch12.py`.

## One model, two entry points
| | Vendor (Products → Add / Edit) | Admin (Catalogue → Add for a vendor) |
|---|---|---|
| Draft API | `/api/vendor/pim/drafts` | `/api/admin/pim/drafts` (`vendor_id` required; selling vendors only) |
| Who | owner; staff with `products.create` / `products.edit` (submit: `products.submit`) | super_admin, admin |
| Ownership | the vendor | the vendor (`created_on_behalf_by` records the admin) |
| Review | same review queue | same review; the preparing admin cannot approve it |
| Validation | identical (`check_product` + `VendorProductIn` + `catalogue` rules) | identical |

## Lifecycle (existing fields, no contradictory status)
`draft` (product_drafts) → submitted → product `approval_status: pending` → `approved` (+ `is_active` when the vendor is selling,
not archived, not taken down) / `rejected` (with reason). Live controls: pause / resume (`is_active`), archive, admin takedown
(sticky), all existing. A change to an approved product is a **pending revision** (`pending_revision.status`
pending → approved / rejected / changes_requested); the approved version stays exactly as it is until approval.

## Sections and what is required to submit
| Section | Fields | Blocking when missing |
|---|---|---|
| Basic information | title, category (4 pillars), sub-category (template list), brand, model / product code, short and full description, up to 6 highlights, keywords, Hindi title / description | title, category, sub-category, short description ≥ 10, description ≥ 30 |
| Images | up to 8, ordered (first = main), uploaded through the signed storage flow (`safe_image_refs`, ownership check), alternative text per image | at least one image (missing alt text is a warning) |
| Price & tax | MRP, selling price (GST-inclusive), GST %, HSN; live breakdown of taxable value / GST / discount | MRP, price, price ≤ MRP, GST 0–28; missing HSN is a reviewer warning (D-15) |
| Variants & stock | product SKU, low-stock alert, opening stock (new products only), variants with own SKU / optional price & MRP / opening stock; bulk generation from a template dimension | SKU; each variant SKU; opening stock for single-stock products |
| Product details | the pillar's template groups (text, long text, number with unit, date, select, multi-select, yes/no) | fields marked required for the pillar or for the chosen sub-category |
| Shipping & returns | packed weight, dispatch days, package dimensions, fragile, returnable + reason | weight, dispatch days; a reason when not returnable (dimensions are a warning) |
| Documents & declarations | typed documents (licence, test report, invoice, authenticity, certificate, other) uploaded via storage, notes, declarations | none; the template's review flags are shown to the reviewer |

## Invariants
- Stock is never taken from a form for an existing product or variant; only opening stock of something new. All later changes go
  through the journaled stock endpoints; revision approval writes are conditional on the stock values read (no lost update).
- A product SKU never changes; SKUs are unique across products and variants (unique indexes).
- Selling price ≤ MRP (product and each variant).
- Approval writes the first `price_history` entry; an approved revision that changes MRP / price / GST / HSN appends one.
- Shop endpoints never return pending revisions, price history, compliance documents or reviewer identities (`P_SHOP`).
- Drafts are versioned (stale saves refused) and there is one open draft per existing product (unique partial index).
- Every step is audited: draft created / submitted / discarded, product submitted / updated, revision approve / reject /
  request_changes, product approved / rejected.

## Not built yet (tracked in the roadmap)
Merchandising controls (badges, featured, collections, ranking; admin-only), scheduled publishing, promotional pricing, CSV
import onto the new fields, category / attribute management screens (templates are code today), video.
