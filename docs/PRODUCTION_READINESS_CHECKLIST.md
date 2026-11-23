# HOME GENIES — Production readiness checklist

Status: **not ready for public launch.** Batches 12–13 are uncommitted and has only been verified locally on a test database.

## Before staging
- [ ] Owner reviews and commits Batches 12–13 (nothing is staged or committed by the engineering sessions).
- [ ] Owner decisions D-01 (return window), D-03 (COD authority), D-04 (delivery confirmation), D-05 (who changes the window),
      D-10 (hosting / proxy), D-15 (tax classification) answered — the safe interim behaviour is documented for each.
- [x] The 7 live HTTP suites updated to the approved contracts and green on a disposable local server (Batch 13; 6 explicit skips).
- [ ] Run them against staging (card-payment tests need test-mode gateway keys there).

## Staging
- [ ] `mongodump` of the target database.
- [ ] Index migration: `python scripts/vendor_foundation_migrate.py` (dry run) then `--apply`. New in Batch 12:
      `product_drafts_*`, `products_pending_revision`. New in Batch 13: `addresses_*`, `wishlist_user_product_variant_unique`,
      `orders_seller_created`, `commissions_user_created`, `withdrawal_requests_user_created`, `products_text`,
      `products_shop_category_price`, `merch_sections_status_position`. Resolve any duplicate webhook `event_id` it reports.
- [ ] Environment: `FRONTEND_PUBLIC_URL`, `REACT_APP_BACKEND_URL` on the frontend project (Production and Preview),
      `CORS_ORIGINS`, Twilio (SMS OTP), storage keys; confirm `VERCEL` is set at runtime (client IP trust).
- [ ] Create a second finance admin (two-person rules need two people).
- [ ] Full regression + live suites + browser walkthrough of every role at desktop and 390 px.

## Production
- [ ] Error monitoring and alerting on money paths.
- [ ] Frontend Content Security Policy.
- [ ] Backup and restore drill; rollback plan = restore code **and** refuse refunds on `money_version 3` orders under the old
      code (old refund maths over-refunds GST-inclusive orders), or roll forward only.
- [ ] Owner sign-off on launch-gap classifications (Batch 11 section H, D-14).

## Latest local evidence
See `docs/ENGINEERING_LOG_BATCH12_ONWARD.md` for test totals per phase.
