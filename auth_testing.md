Auth-Gated App Testing Playbook (Emergent Google Auth)

NOTE: This app uses Emergent Google Auth ONLY to identify an existing distributor's verified
email, then mints the app's OWN JWT (stored in localStorage as `anj_token`, sent as
`Authorization: Bearer <token>`). There is NO cookie session and NO `user_sessions` collection.
Google sign-in is for EXISTING distributors only (matched by email); no new account is created.

Backend endpoint:
- POST /api/auth/google/session   body: {"session_id": "<id from URL fragment>"}
  -> calls Emergent https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data (X-Session-ID)
  -> finds existing user by email; returns {token, user} just like /api/auth/login
  -> 404 if no account linked to that email; 403 if blocked.

Manual test (existing user):
1. Ensure a distributor user exists with a known email, e.g. via admin or /api/auth/register.
2. Frontend: on /login click "Continue with Google" (data-testid="login-google-btn").
3. Complete Google on auth.emergentagent.com; you return to /app/dashboard#session_id=...
4. AppRoutes detects the fragment and renders AuthCallback (data-testid="google-auth-callback"),
   which POSTs session_id, stores anj_token, and navigates to /app/dashboard.

Negative test:
- A Google email with no matching account must get a 404 toast and land back on /login.

Token-based API checks (reuse existing JWT):
  curl -s $REACT_APP_BACKEND_URL/api/auth/me -H "Authorization: Bearer <anj_token>"

Success indicators: dashboard loads, /api/auth/me returns the user.
Failure indicators: bounced to /login, 401/404.
