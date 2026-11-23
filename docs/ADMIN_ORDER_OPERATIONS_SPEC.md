# HOME GENIES — Admin order operations (Batch 13, Phase 9; ADM-06)

Code: `backend/admin_order_ops.py`, `admin_routes.update_order_status` (reason), frontend `pages/admin/AdminOrderOps.js`
(Order lookup + order detail), link from the existing Orders page. Tests: `tests/test_admin_order_ops_b13.py`.

## Order list — `GET /api/admin/order-ops/orders` (any admin role)
Server-side filters: free text (order number, order id, delivery name, customer name / mobile / account id), vendor, payment status,
order status, vendor fulfilment step, method (prepaid / COD), refund state (none / partial / full / open refund case), has return,
IST date range. Sorting by date, total or number; paging (default 25). Each row: number, date, statuses, total, refunded, lines,
vendors and each vendor's step, customer name with **masked** mobile, flags (needs refund, refund due after cancel, duplicate payment).
The older `GET /api/admin/orders` (used by the payment-exception workflows on the Orders page) is unchanged.

## Export — `GET /api/admin/order-ops/orders.csv`
super_admin, admin, accounts_admin (support refused). Same filters, max 5,000 rows, no addresses, masked mobile, spreadsheet-formula
safe, and every export is audited with its filters.

## Order detail — `GET /api/admin/order-ops/orders/{id}`
One read of every source: order money (goods GST-inclusive, GST contained, COD fee, total, refunded, payment reference, invoice,
duplicate captures, COD collection / discrepancy, expected COD cash, commission base); the **address snapshot**; the customer (full
contact for super_admin / admin / support_admin, masked for accounts_admin); the attributed HomeGenie; **each vendor separately**
(goods value, lines, status, tracking, timeline, delivery evidence note, delivered time, refund due, its ledger entries and net, and
whether its money is payable now with the finance rule's reason); the whole-order delivery and commission eligibility; payment
attempts; commissions (member, type, amount, reversed, status); returns; refund cases and refund events; the audit history.
Webhook events are stored per gateway event, not per order, so they are not listed (documented gap).

## Actions
No new money action. Status change keeps its endpoint and permission and now records a **reason** (the detail screen requires
one); for vendor goods it is recorded as `status_set_by_admin` and is not a delivery (owner decision D-04 open). Refunds, COD
confirmation, UPI confirmation, returns and refund cases keep their own endpoints, permissions, two-person rules and audits.
An admin cannot create a delivery record to make an order payable: delivery comes only from the vendor fulfilment.
