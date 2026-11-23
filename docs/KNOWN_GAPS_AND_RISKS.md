# HOME GENIES — Known gaps and risks (current)

## Open risks
| # | Risk | Severity | Mitigation / status |
|---|---|---|---|
| R-1 | The IP used for rate limits is trustworthy only if the API is reachable solely through Vercel (or a private proxy) | High if false | D-10: owner to confirm hosting |
| R-2 | Admin can still set a vendor order's status to "delivered" (display only; no payout effect) | Medium | D-04; payouts read vendor fulfilments |
| R-3 | COD cash confirmation is single-person and by `admin`, not finance | Medium | D-03 |
| R-4 | The return window that controls payouts can be changed by `admin` | Medium | D-05 |
| R-5 | Accounts registered through the legacy sign-up before Batch 12 may carry an unproven `email_verified: true`, so Google sign-in into them stays possible | Medium | not rewritten (no history rewrite); owner may choose a one-off re-verification campaign |
| R-6 | Tokens issued before the `jti` field cannot be revoked by logout; they expire within 7 days of issue | Low | time-bounded |
| R-7 | UPI confirm that loses the race to expiry leaves the UTR reserved and a stray transaction row (L2); two concurrent confirms with different UTRs both answer 200 (L3) | Low | Phase 3 follow-up |
| R-8 | Clawback is proportional to gross value, not per-line taxable value, on mixed-GST orders (L5) | Low | follow-up |
| R-9 | Full PAN / Aadhaar / bank details stored in plaintext; any role can submit KYC (L10) | Medium | encryption-at-rest design needed |
| R-10 | No external error monitoring; frontend CSP missing | Medium | Phase 10 |
| R-11 | ~~The 7 live HTTP suites were not green~~ resolved in Batch 13 (green on a disposable server; staging run pending) | Low | run on staging |
| R-12 | `backend/scripts/demo_environment.py` uses old contracts | Low | dev tool only |
| R-13 | Product template changes are code changes (no admin screen) | Low | Phase 9 |

## Functional gaps (after Batch 13)
Customer support tickets, notification preferences, VEN-04 / VEN-05 / VEN-06 (D-04), platform role expansion (D-16), separate billing
address (D-18), vendor merchandising requests (D-19), webhook events linked to orders, merging the old admin Orders page into the
new order lookup, promotional pricing.

## Added in Batch 13
| # | Risk | Severity | Mitigation / status |
|---|---|---|---|
| R-14 | The frontend build's ESLint setup enforces only the React hooks rules, so an undefined identifier compiles and fails at run time (it happened once in Batch 13 and was caught by the browser check) | Medium | a one-off undefined-name scan is clean; owner may approve adding `no-undef` / `react/jsx-no-undef` to the build config |
| R-15 | Two card-payment live tests are skipped on test servers (no gateway credentials) | Low | run on staging with test-mode gateway keys |

## Things that are safe by design (do not "fix")
- Admin delivered status on vendor goods is recorded but has no payout effect (until D-04).
- COD cash confirmation records payment only; delivery comes from the vendor.
- A change to an approved product never hides it; the approved version stays on sale until the change is approved.
