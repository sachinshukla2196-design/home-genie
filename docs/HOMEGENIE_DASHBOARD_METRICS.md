# HOME GENIES — HomeGenie dashboard metrics (Batch 13, Phase 8; fixes HG-03)

Code: `backend/homegenie_metrics.py` (`GET /api/homegenie/metrics`, `GET /api/homegenie/orders`). Tests:
`tests/test_homegenie_metrics_b13.py`. The frontend only displays these numbers; it never calculates commission.

## What was wrong (HG-03, old `/api/dashboard`)
- "Sales" counted only `payment_status == paid`: partly refunded sales were dropped, paid-then-cancelled orders were still counted.
- Commission figures added gross `amount`, ignoring reversals; "team" figures included unreleased commission.
- Days were cut at UTC midnight, not Indian midnight. "Total orders" was the member's own purchases, not attributed sales.
The old endpoint is kept unchanged for compatibility; the dashboard now reads the metrics endpoint.

## Scope and time
- **Attributed order** = an order whose `seller_user_id` is the member (set at checkout from a valid share code). One order counts once
  however many vendors or lines it has; lines are counted separately.
- **Range**: inclusive IST dates (`frm`, `to`), default the last 30 days, at most 366 days. Orders, commissions and withdrawals are
  filtered by their own `created_at`.
- **Money** is integer paise from the stored records.

## Definitions
| # | Metric | Definition (source) |
|---|---|---|
| 1 | Attributed orders | count of attributed orders created in range (`orders`) |
| — | Attributed order lines | number of item lines on those orders |
| 2 | Paid orders | attributed orders whose payment was received: `payment_status` ∈ paid, partially_refunded, refunded |
| 3 | Delivered orders | paid, not cancelled, and delivered by the vendor fulfilments (`eligibility.delivered_at`) |
| 4 | Cancelled orders | `status = cancelled` |
| 5 | Returned orders | paid orders with a counted return case (`return_cases`, active / refunded / closed) |
| 6 | Refunded orders | `payment_status = refunded` (full); partly refunded reported separately |
| 7 | Gross attributed sales | sum of the goods value of paid orders (GST-inclusive item total, COD fee excluded; duplicate captures are never added) |
| — | Net sales | gross − refunded goods value (refunds capped at the goods value) |
| 8 | Eligible commission basis | sum of `base_paise` on the member's direct commissions (taxable value of supplied goods, as frozen by the engine) |
| 9 | Held commission | net (amount − reversed) of commissions not yet released and not fully reversed |
| 10 | Released commission | net of released commissions |
| 11 | Reversed commission | sum of `reversed_paise` |
| 12 | Withdrawal requests | count and amount of requests created in range |
| 13 | Withdrawals paid | count and amount with `status = paid` |
| 14 | Pending withdrawal amount | amount with status pending / under_review / approved |

Also returned: commission by type (direct / referral / team, net), a daily trend (paid orders, net sales, commission earned — sums equal
the totals), held-commission reasons grouped by the finance rule's own reason code (all-time open commissions), and the wallet as it is
now. `GET /api/homegenie/orders` lists attributed orders, server-paged, with one state per order (awaiting payment, paid, delivered,
partially refunded, returned, cancelled, refunded), goods value, refunded value, lines, vendors, the customer's first name only, and
the member's direct commission (net, status, release date).

Only `distributor` accounts can call these endpoints, and only for their own records.
