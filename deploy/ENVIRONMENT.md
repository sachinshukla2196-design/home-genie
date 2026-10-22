# HOME GENIES — environment variables

Set these in the hosting provider's secret/environment settings (e.g. Vercel → Project → Settings →
Environment Variables). **Never commit real values** to Git, docs, commit messages or chat.

## Frontend (`frontend/`, Create React App)

| Variable | Required | Notes |
|---|---|---|
| `REACT_APP_BACKEND_URL` | Yes | Public origin of the API: `https://…`, no path, no trailing slash, e.g. `https://<api-project>.vercel.app`. Baked in **at build time**: redeploy the frontend after changing it. Not secret. (A `VITE_*` name will not work — this is not a Vite app.) |

- `npm run build` runs `scripts/check-env.js` first and **fails** if the variable is missing, not https,
  points at localhost, or includes a path such as `/api`. There is no fallback URL.
- In Vercel set it for **Production** and **Preview** (Preview may point at a staging API if you have one;
  otherwise the same production API). Development uses `frontend/.env.development.local` (git-ignored).
- Every `REACT_APP_*` value is public (it ships inside the JavaScript bundle). Never put API keys,
  database URLs, admin passwords or other secrets in frontend variables.
- Node.js: **22.x** (`package.json` `engines`, `.nvmrc`). Set Vercel → Settings → General → Node.js Version to 22.x to match.

## Backend / API (`backend/`, FastAPI)

### Required
| Variable | Notes |
|---|---|
| `MONGO_URL` | MongoDB connection string (e.g. Atlas `mongodb+srv://…`). Secret. |
| `DB_NAME` | Database name, e.g. `homegenies`. |
| `JWT_SECRET` | Long random string (64+ chars) used to sign login sessions. Secret. Changing it signs everyone out. |
| `CORS_ORIGINS` | Comma-separated exact frontend origin(s), e.g. `https://home-genie-9zfc.vercel.app`. `*` is rejected. (`CORS_ALLOWED_ORIGINS` also accepted.) |
| `ADMIN_EMAIL` | Super-admin login email. |
| `ADMIN_PASSWORD_HASH` | **Preferred.** bcrypt hash of the admin password, from `python3 backend/scripts/hash_admin_password.py`. Keeps the plaintext out of every env store. |
| `ADMIN_PASSWORD` | Plaintext alternative to `ADMIN_PASSWORD_HASH` (ignored when the hash is set). Remove it once the hash is configured. |

The admin account is synchronised from these on startup (on Vercel: on the first request). When the
configured credential differs from the stored one, the account is updated, the change is written to
the audit log, and **all admin sessions issued before the change are signed out**.

### Optional
| Variable | Notes |
|---|---|
| `ADMIN_USERNAME` | Admin username (default `admin`). |
| `CRON_SECRET` (Vercel) / `WEBHOOK_CRON_SECRET` (Emergent) | Bearer secret for the daily points-release job. Vercel Cron sends `CRON_SECRET` automatically. |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Online payments. Without them, online checkout returns "not configured" (COD still works). |
| `TWILIO_ENABLED`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `OTP_PEPPER` | SMS OTP. Disabled unless `TWILIO_ENABLED=true`. |
| `OTP_TTL_SECONDS`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN` | OTP tuning. |
| `EMERGENT_LLM_KEY`, `INTEGRATION_PROXY_URL` | Emergent object storage (image uploads). Uploads fail without it. |
| `EMERGENT_EMAIL_KEY`, `EMAIL_FROM_NAME` | Outbound email. |
| `STRIPE_API_KEY` | Only with the Emergent Stripe package; card checkout is disabled elsewhere. |
| `ADMIN_PASSCODE` | **Unused** — the admin passcode was removed. Delete it from any environment. |

## Rotating the admin password safely
1. `python3 backend/scripts/hash_admin_password.py --generate` (or without `--generate` to type your own).
   Save the shown password in a password manager.
2. Set `ADMIN_PASSWORD_HASH` to the printed hash in the API's environment; delete `ADMIN_PASSWORD`.
3. Redeploy/restart the API. Log in with the new password; old admin sessions stop working.
4. Changing the password does **not** remove old passwords from Git history or chat logs — treat every
   previously shared value as compromised and never reuse it.
