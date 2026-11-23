# HOME GENIES — Customer address book and wishlist (Batch 13, Phase 7)

Code: `backend/customer_routes.py`, `shop_routes.create_order` (`address_id`), frontend `pages/Addresses.js`, `pages/Checkout.js`
(saved-address picker), `pages/Wishlist.js`, `components/WishButton.js`. Tests: `tests/test_customer_batch13.py`.

## Address book — `addresses`
| Field | Rule |
|---|---|
| label | `home` / `work` / `other` |
| full_name | required, 2–80 characters |
| mobile | required, Indian 10-digit starting 6–9 (`+91`, spaces and dashes are removed) |
| line1 | required, 3–120 |
| line2, locality, landmark, district | optional, up to 120 |
| city | required, 2–60 |
| state | required, one of the 36 states / union territories |
| pincode | required, 6 digits, first digit 1–9 |
| country | India (the only country offered: payments, mobile and PIN formats are Indian) |
| user_id, created_at, updated_at, last_used_at, deleted_at | server-managed |

- Up to 20 addresses per account. Every query is filtered by the caller's id, so another person's id answers "not found".
- **Default**: a single pointer `users.default_address_id`; the first address becomes the default; making another default is a single
  write (no two defaults even under concurrency); deleting the default moves it to the most recently used / created remaining address,
  or to none.
- **Delete** is soft (`deleted_at`) and idempotent; a deleted address cannot be used for a new order.
- **Checkout** sends `address_id`; the server copies the address (with `address_id`) into the order. Editing or deleting it later never
  changes the order. A typed address still works and is now validated (10-digit mobile, 6-digit PIN, required fields).
- **Billing address**: not separate — the invoice model has one address per order; a separate billing address would need an invoice
  change and is not built.

## Wishlist — `wishlist_items`
- One row per (account, product, variant option); unique index → repeated or simultaneous saves are harmless. Remove is idempotent.
- Only products on sale (approved, active, not archived) can be saved; a named option must exist.
- `GET /api/wishlist` reports each item's live state: `available`, `choose_variant` (product sold in options, none chosen),
  `out_of_stock`, `unavailable` (no longer sold — no product details are returned for it), the current price, the price when saved and
  whether it went up or down. No alert or notification is sent (none exists).
- Move to cart: needs an in-stock option for variant products; the cart is re-priced and re-checked by the order endpoint, so a saved
  item never becomes purchasable if the product is not.
- Up to 200 items per account.

## Endpoints
`GET/POST /api/addresses`, `PUT/DELETE /api/addresses/{id}`, `POST /api/addresses/{id}/default`, `GET/POST /api/wishlist`,
`DELETE /api/wishlist/{product_id}?variant_sku=`, `GET /api/wishlist/ids`. All require sign-in.
