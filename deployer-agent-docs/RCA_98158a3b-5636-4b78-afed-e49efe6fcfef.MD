# RCA — anjali-ayurveda-mvp redeploy failure (run 98158a3b-5636-4b78-afed-e49efe6fcfef)

## Outcome
Redeploy failed at the **deploy_k8s / health_check** step. The rollout never became ready because the backend process crashes on boot, so nginx's `/health` probe gets `connection refused` on `127.0.0.1:8001` and the pod is never Ready. This repeated identically across 4 consecutive attempts (12:44, 13:06, 21:56, 22:14 UTC on Oct 1).

The app was NOT taken down — the previous healthy run (`4f139512...`, amd64, deployed 2026-09-12) remains live at https://anjali-ayurveda-mvp.emergent.host. A failed run is never promoted.

## Root cause (verified)
Backend dies immediately at import time:

```
RuntimeError: CORS_ORIGINS is not configured with explicit production origin(s).
  File "/app/backend/server.py", line 60, in <module>
    raise RuntimeError("CORS_ORIGINS is not configured with explicit production origin(s).")
```

`server.py` now enforces a hardened CORS guard that rejects a wildcard / non-explicit value and demands explicit production origins.

The production secret store still holds the old value: I verified via `list_secrets` that **`CORS_ORIGINS` is present, non-empty, and equals `"*"`** (matches_expected=true against `"*"`). The wildcard is exactly what the new guard rejects, so the process exits before binding port 8001.

Why a plain re-run won't fix it: deployment secret VALUES are preserved (never overwritten) across redeploys. Every retry re-ships the same `CORS_ORIGINS="*"` and crashes the same way — confirmed by the 4 identical failures. This is why I did NOT re-fire `resume_pipeline`.

Note: this is a secret/config fault, not a manifest or build fault and not reproducible in the eph sandbox (no secrets are injected there), so no manifest edit was made.

## Fix (required before redeploy)
Update the `CORS_ORIGINS` secret VALUE from `*` to the explicit production origins, then redeploy. Since pre-existing secret values are not overwritten by redeploy, this MUST be done in the UI:

Deployment Panel → Secrets → edit `CORS_ORIGINS` → set to the app's real production origins, comma-separated, e.g.:

```
https://anjaliherbal.life,https://www.anjaliherbal.life,https://anjali-ayurveda-mvp.emergent.host
```

(Match whatever format `server.py` parses — comma-separated list of full https origins with no trailing slash and no wildcard.) Save, then redeploy.

Alternative (only if the strict guard is unintended): relax the check in `backend/server.py` around line 60 to accept the intended origins — but the guard looks deliberate (production hardening), so updating the secret value is the correct path.

## Evidence
- `describe_deployment_state`: failing run 98158a3b (arm64) and 3 prior siblings all `failed` at deploy, same traceback; active run 4f139512 still `success`.
- Rollout log: `connect() failed (111: Connection refused) ... /health ... 127.0.0.1:8001` → `Backend died, shutting down nginx...` → the CORS RuntimeError.
- `list_secrets` (active run): `CORS_ORIGINS` is_empty=false, matches_expected=true for value `"*"`.
