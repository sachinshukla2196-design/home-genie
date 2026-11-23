# HOME GENIES — Merchandising and discovery (Batch 13, Phases 10–11)

## Merchandising — `backend/merchandising.py`, `pages/admin/AdminMerchandising.js`, `components/MerchSections.js`
| Section | Content | Source |
|---|---|---|
| banner | desktop + optional mobile image (uploaded storage references only), alt text (required), internal link | admin |
| collection / featured_products | hand-ordered products (max 24) | admin; only products on sale can be added |
| featured_categories | ordered pillars | admin |
| new_arrivals | newest products on sale | computed |
| bestsellers | most units in paid, not cancelled orders over N days | computed from orders; no numbers shown |

- Lifecycle draft → published → unpublished; delete is a soft status. `starts_at` / `ends_at` are evaluated on every read, so
  campaigns start and stop on time with no scheduler; the admin list shows live / scheduled / expired.
- Ordering of sections (and of products inside a collection); preview of what a section would show now; every change audited and
  kept in a short history.
- Shop rules applied at read time: approved, active, not archived, in stock; a section with nothing to show is hidden; no ratings,
  popularity claims or discounts; links can only point inside the shop. Only super_admin / admin edit; support can view; vendors none.
- Shown on the shop page (when not searching or filtering) and on the customer home. The public landing page is unchanged.
- Not built: vendor merchandising requests (vendors cannot create or request placements), promotional pricing.

## Discovery — `backend/discovery.py`, `pages/Products.js`, `components/RelatedProducts.js`
- `GET /api/catalog/search`: text (weighted text index), category, sub-category, brands, price range, in stock, attribute filters
  (`attr.colour=Red`, only known attribute keys), sort (relevance / newest / price / name), paging (max 48). Only products on sale;
  shop projection (no internal fields). Input is escaped (no regex or operator injection).
- `GET /api/catalog/facets`: real brands, price range, sub-categories and attribute values among products on sale.
- `GET /api/catalog/suggest`: up to 8 products, brands and categories for the search box.
- `GET /api/catalog/products/{id}/related`: same sub-category, then category, in stock first.
- `GET /api/catalog/products?ids=`: products on sale by id (the shopper's recently viewed list, kept in their own browser).
- Indexes: `products_text`, `products_shop_category_price`; the test suite checks the query plans use them (TEXT / IXSCAN).
- No paid search service.
