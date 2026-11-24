# HOME GENIES — Dependency security audit and controlled upgrades (Programme 02 / W6)

Date 2026-11-24. Working tree of `main` @ `d31cb74` (Programme 00 / 01 / DEF-03 / W8 work uncommitted); checkpoint
`~/home-genie-checkpoints/hg-20261124-1229-pre-w6-worktree.tar.gz`. Nothing staged, committed, pushed or deployed. Audits were run
on 2026-11-24 with `pip-audit` 2.10.1 (PyPI and OSV databases) and `npm audit` (npm 10.9.8, node 22.23.2). Advisory identifiers
are those the databases returned on that date. Readiness reference: `HOME_GENIES_PROGRAMME_02_READINESS.md` W6.

## 1. Summary
| Set | Before | After | Remaining (all with a written reason, §6) |
|---|---|---|---|
| Production backend (`backend/pyproject.toml` = Vercel API; fresh resolution, 26 → 27 packages) | 4 vulnerable packages, 36 PyPI / 54 OSV advisories (1 critical, 14 high) | **0 / 0** | none |
| Emergent environment (`backend/requirements.txt`, 127 auditable pins) | 15 vulnerable packages, 124 PyPI / 183 OSV advisories | 5 packages, 60 / 84 advisories | pillow, python-jose, ecdsa, filelock, oauthlib: none imported by the application; fix is a major version or no fix exists |
| Frontend (`frontend/package-lock.json`, 1,509 → 1,484 entries) | 38 findings: 0 critical, 22 high, 4 moderate, 12 low | 26 findings: 0 critical, 13 high, 4 moderate, 9 low | the CRA 5 (react-scripts) build / dev-server / test toolchain only; none of these packages is in the browser bundle (§4.3) |

Every critical and every fixable high advisory **in code the application runs** (API server, browser bundle) is fixed.
The remainder sits in the build toolchain (fix = migrate off Create React App) or in Emergent-only packages the application does not
import (fix = major upgrade or removal, tied to decision D-10). One compatibility shim was required (PyMongo SRV, §5.1).

## 2. Inventory
| Manifest | Role | Notes |
|---|---|---|
| `backend/pyproject.toml` | **Production API (Vercel)**: 16 exact pins; sub-dependencies resolved at build time | the authoritative production set |
| `deploy/vercel-api/requirements.txt` | tracked slim copy for the Vercel API project (15 pins; `backend/` copy is git-ignored) | identical pins to pyproject except `stripe` (absent since before W6; stripe is imported behind a fallback) |
| `backend/requirements.txt` | Emergent platform environment: full freeze, 129 lines, private `emergentintegrations==0.2.0`, a `litellm` wheel URL, AI / LLM SDKs and dev tools | the in-process and live test venv mirrors it |
| `frontend/package.json` + `package-lock.json` | React 19 / CRA 5 (react-scripts 5.0.1) via CRACO 7.1.0; npm lockfile v3 | `packageManager: yarn@1.22.22` and a 42-entry yarn-only `resolutions` block, but no `yarn.lock` (§5.4) |
| `frontend/.npmrc` | `legacy-peer-deps=true` (pre-existing, for `react-day-picker`) | applies to every npm install, including Vercel's (§5.5) |
| `frontend/vercel.json` | `npm run build`; no install command → Vercel detects `package-lock.json` (npm) | |
| `.github/workflows/deploy-frontend.yml` | manual Vercel deploy (node 22, `vercel build`) | no audit step |
| Dockerfiles | none in the repository | |

**Application imports (backend, third-party):** bcrypt, dotenv, emergentintegrations (try / except fallback to `stripe_checkout.py`),
fastapi, httpx, jwt (PyJWT), motor, pydantic, pymongo, razorpay, requests, starlette, stripe; plus runtime-required python-multipart
(`UploadFile`), email-validator (`EmailStr`), dnspython (`mongodb+srv`). Twilio is called over REST with `requests` (the `twilio` SDK is
unused). Not imported anywhere in application code: aiohttp, multidict, pyasn1, black, certifi, urllib3, pillow, filelock, oauthlib,
python-jose, ecdsa, litellm, openai, google-genai, boto3, twilio (checked with `grep` over `backend/*.py`, `tests/`, `scripts/`).

**Unused / duplicate / obsolete (frontend):** `zod` (0 imports; removed). Top-level `eslint` 9.23.0 duplicated the ESLint 8.57.1 that
react-scripts runs, and was **not** unused (§5.3). `@eslint/js` and `globals` (flat-config helpers; 0 references; removed). The
yarn `resolutions` block is obsolete under npm (§5.4).

## 3. Python audit (pip-audit, PyPI + OSV)
### 3.1 Vulnerability register — before
| Package | Version | Direct / transitive (in which set) | Severity (count) | Critical / high advisories | Fixed in | Affected functionality |
|---|---|---|---|---|---|---|
| starlette | 0.37.2 | direct (prod + Emergent) | 3 high, 3 moderate, 1 low | CVE-2024-47874 (multipart DoS), CVE-2026-54283 (urlencoded form limits ignored), CVE-2026-48818 (Windows StaticFiles SSRF) | 0.40.0 … **1.3.1** | every request; uploads (multipart); forms |
| PyJWT | 2.13.0 | direct (prod + Emergent) | **1 critical**, 6 high, 8 moderate | CVE-2026-102268 (asymmetric-PEM detection bypass), CVE-2026-102266, -102267, -102271, -102272, -102273, GHSA-pxh4-856f-4h89 | 2.14.0 / **2.15.0** | login sessions (HS256 tokens in `core.py`) |
| pymongo | 4.6.3 | direct (prod + Emergent) | 3 high, 2 moderate | CVE-2026-96749 (BSON encode heap write), CVE-2026-96748 (URI host injection), CVE-2026-106435 (BSON regex OOB read) | **4.18.3** | every database call |
| dnspython | 2.8.0 | direct (prod + Emergent) | 2 high | CVE-2026-114605, CVE-2026-128089 (CPU / memory use) | **2.9.2** | `mongodb+srv` resolution |
| certifi | 2026.7.22 | transitive (Emergent pin; prod already 2026.11.20) | **1 critical** | GHSA-6q48-6c7w-9gw2 (emSign root CAs, compromised intermediates) | **2026.10.18** | outbound TLS (payments, SMS, storage) |
| urllib3 | 2.7.0 | transitive (Emergent pin; prod already 2.8.0) | 2 high, 1 moderate | CVE-2026-97687 (HTTPS-proxy TLS config ignored), CVE-2026-97689 (unbounded chunk-size line) | **2.8.0** | outbound HTTP via `requests` |
| aiohttp | 3.14.3 | transitive (litellm, twilio, aiohttp-retry; Emergent only) | 11 high, 5 moderate, 1 low | CVE-2026-128127, -123817, -128128, -111064, -111066, -128124, -128126, -128130, -128132, -128131, -128129 | **3.14.4** | not used by the application |
| multidict | 6.7.1 | transitive (aiohttp, yarl; Emergent) | 1 moderate | — | **6.9.1** | not used |
| pyasn1 | 0.6.4 | transitive (rsa, python-jose; Emergent) | 4 high | CVE-2026-119194 … -119197 (quadratic decoding) | **0.6.5** | not used |
| black | 26.5.1 | dev tool pin (Emergent) | 1 high | CVE-2026-114134 (GitHub Action version install) | **26.10.1** | formatter only |
| pillow | 12.3.0 | top-level pin, nothing requires it (Emergent) | **5 critical**, 24 high, 14 moderate | CVE-2026-112398, -112403, -96639, -112393, -112900 (critical) + 24 high | 13.0.0 (major) | **not imported** |
| python-jose | 3.5.0 | top-level pin, nothing requires it (Emergent) | **1 critical** | CVE-2026-85394 (algorithm-confusion guard bypass) | **no fix** | **not imported** (the app uses PyJWT) |
| ecdsa | 0.19.2 | via python-jose (Emergent) | 1 high | CVE-2024-23342 (Minerva timing) | **no fix** | not used |
| filelock | 3.32.2 | via huggingface_hub (Emergent) | 1 high, 9 moderate, 2 low | CVE-2026-112940 | 4.2.1 (major) | not used |
| oauthlib | 3.3.1 | via requests-oauthlib (Emergent) | 2 high, 2 moderate | CVE-2026-49272, CVE-2026-118669 | 4.0.1 (major) | not used |

The production set (`pyproject.toml`) contained only the first four rows; its own sub-dependencies (certifi, urllib3) were already patched
because they float at build time. Full per-advisory data: the audit JSON files listed in §8.

### 3.2 After
- Production set (fresh venv from `deploy/vercel-api/requirements.txt` + stripe, `pip check` clean): **0 vulnerable packages** on PyPI and
  OSV. PyJWT 2.15.0 is also outside the range of PYSEC-2026-4146 (options-dict mutation), which had no fixed version at the first audit.
- Emergent set: 5 vulnerable packages remain (pillow, python-jose, ecdsa, filelock, oauthlib) — §6.

## 4. npm audit
### 4.1 Before → after
`npm audit --omit=dev` equals the full audit in both runs because `react-scripts` (and with it the whole build / test toolchain) is
declared under `dependencies`; production vs development was therefore separated by inspecting the **built bundle** (§4.3).

| Package | Before | Direct? | Severity | Advisories | Action | After |
|---|---|---|---|---|---|---|
| axios | 1.18.0 | direct | high | GHSA-3pq3-5fj3-cg6v, GHSA-44g4-m2mj-wpvx, GHSA-4hqw-qxg8-jxx2, … (vulnerable 1.0.0 – 1.19.0) | upgrade to smallest fixed **1.20.0** | resolved |
| react-router-dom / react-router | 7.15.0 | direct / transitive | high | GHSA-337j-9hxr-rhxg, GHSA-84g9-w2xq-vcv6, GHSA-chx6-hx7r-mcp5, … (vulnerable ≤ 7.18.1) | upgrade to **7.18.2** | resolved |
| zod | 3.24.4 | direct | high | GHSA-mrhx-c7xc-m3w5 (fix only in 4.x) | **removed** (0 imports) | resolved |
| postcss (top level) | 8.5.10 | direct (dev) | high | GHSA-6g55-p6wh-862q, GHSA-7fh5-64p2-3v2j, GHSA-fxqj-rqcc-2cmp | upgrade to **8.5.23** | top-level resolved; nested postcss 7.0.39 in resolve-url-loader remains (CRA) |
| eslint (top level) | 9.23.0 | direct (dev) | low (@eslint/plugin-kit GHSA-xffm-g5w8-qvg7) | | **aligned to 8.57.1** (§5.3) | resolved |
| @eslint/js, globals | 9.23.0, 15.15.0 | direct (dev) | — | | removed (unused) | — |
| underscore | 1.13.6 | transitive (react-scripts → bfj → jsonpath) | high | GHSA-qpx9-hpmf-5gmw | npm `overrides` **1.13.8** (patch; only that path) | resolved (bfj, jsonpath findings also cleared) |
| follow-redirects, node-forge, body-parser, set-cookie-parser | 1.16.1, 1.4.0, 1.20.8, 2.7.2 | transitive | high | GHSA-mrwp-f3q8-3g9p; GHSA-2vgq-wchc-25w7 …; GHSA-27r3-jxmh-p828 | `npm audit fix` (in-range patches): 1.16.3, 1.4.4, 1.20.9, 2.7.3 | resolved |
| svgo, @svgr/*, css-select, nth-check, serialize-javascript, rollup-plugin-terser, workbox-*, webpack-dev-server, webpack-dev-middleware, css-minimizer-webpack-plugin, resolve-url-loader, sockjs, uuid, react-scripts | — | transitive (react-scripts) | 13 high, 4 moderate | e.g. GHSA-rp65-9cf3-cjxr (nth-check), GHSA-5c6j-r48x-rmvq (serialize-javascript), GHSA-4v9v-hfq4-rm2v (webpack-dev-server), GHSA-w5hq-g745-h8pq (uuid) | none possible: npm's only fix is "react-scripts major" (= leave CRA) | **remain** (§6) |
| jest 27 / jsdom 16 / http-proxy-agent 4.0.1 / @tootallnate/once 1.1.2 chain | — | transitive (react-scripts test runner) | 9 low | GHSA-vpq2-c234-7xj6 | `npm audit fix` cannot apply it: http-proxy-agent 4.0.1 requires `@tootallnate/once@1`, fixed only in 2.0.1+ (major) | **remain** (§6) |

### 4.2 Peer conflicts
Checked with a strict install resolution (`--legacy-peer-deps=false`, dry run) on copies of both lockfiles:
- Before: `react-day-picker@8.10.1` (React ≤ 18, date-fns ≤ 3 vs the app's React 19 / date-fns 4) **and 10 overrides caused by the
  top-level ESLint 9.23.0** (react-app config, eslint-webpack-plugin, typescript-eslint, flowtype, jest, testing-library and the
  react-app copy of react-hooks all require ESLint ≤ 8). `npm ls` listed 66 "invalid" entries.
- After: only `react-day-picker` remains (pre-existing; used only by `components/ui/calendar.jsx`, which no page renders). `npm ls`: 52
  "invalid" entries, all the react-day-picker / React 19 / date-fns pair and one `fdir` → picomatch 2 entry, all pre-existing.

### 4.3 Runtime vs build-time (bundle evidence)
The production bundle's source maps list **1,159 modules from 84 npm packages** (W8 baseline: 1,156). None of the 26 remaining
flagged packages is among them (svgo, postcss, webpack-dev-server, serialize-javascript, workbox, uuid, jsdom, underscore, … all absent).
The W6-changed packages that do ship to browsers: axios (52 modules) and react-router (1 module; react-router-dom re-exports it).

## 5. Compatibility findings
### 5.1 PyMongo 4.18: `mongodb+srv` resolution is now lazy (code shim, behaviour preserved)
PyMongo 4.6.3 resolved a `mongodb+srv://` host while constructing the client, so `core.py` caught a wrong cluster host **at import** and
every request answered 503 with `missing_env: ["MONGO_URL_INVALID …"]` (test `test_vercel_cors_dbdown::test_unresolvable_srv_host_gives_503_not_import_crash`).
PyMongo 4.18.3 defers the lookup to the first operation: the candidate regression failed that test (generic 503, no diagnostic on Vercel;
on a non-Vercel host the guard would not trigger at all). Fix in `backend/core.py`: the existing import-time `try` now first calls
`pymongo.uri_parser.parse_uri(mongo_url)` — public API, no deprecation warning, which still resolves SRV eagerly (≈ 0.03 s; no network
work for `mongodb://` URLs). Result: identical behaviour and response to before; the test passes unchanged on the old and the new
driver; no other code changed.

### 5.2 Starlette 1.x and FastAPI 0.133
- Starlette's smallest release fixing all three high advisories is **1.3.1** (a major version from 0.37). FastAPI ≥ 0.133 is the first
  line that accepts Starlette 1.x; 0.133.1 was chosen (FastAPI ≥ 0.164 requires Starlette ≥ 1.6, not needed).
- `@app.on_event("startup" / "shutdown")` (server.py): Starlette 1.x removed these hooks; FastAPI 0.133.1 runs them itself
  (`fastapi/routing.py`: "Handle on_startup/on_shutdown locally since Starlette removed support"). Verified at runtime: §7.
- Multipart: Starlette ≥ 0.40 limits **non-file** form parts to 1 MB and 1,000 fields / files; file parts are spooled and unaffected, so
  the application's own 5 MB image limit (`storage.py MAX_BYTES`) still governs uploads — verified at runtime (§7).
- `starlette.testclient` now warns that `httpx` is deprecated in favour of `httpx2` (test-only warning; future item).
- FastAPI 0.133 adds one production sub-dependency: `annotated-doc` 0.0.7.

### 5.3 The top-level ESLint package was functional, not redundant
W8 recorded the top-level `eslint` 9.23.0 as unused. W6 found otherwise: `eslint-plugin-import` (used by the W8 `.eslintrc.js` through
`react-app`) calls `require('eslint')` from the top-level `node_modules` (`exportMap/visitor.js`, which builds the export maps behind
`import/named`, and `rules/no-unused-modules.js`). Removing the package made `npm run lint` and `npm run build:check` crash ("Failed to
load plugin 'import' … Cannot find module 'eslint'"). With ESLint 9 present, the import rules ran inside ESLint 8 while loading pieces of
ESLint 9. **Action:** the top-level devDependency is now `eslint` **8.57.1** — the engine react-scripts actually runs — so there is one
ESLint in the tree (npm dedupes it), the low advisory and the 10 peer overrides disappear, and `@eslint/js` / `globals` (flat-config
helpers, unused) are removed. Lint output and all 13 guard results are byte-identical to the W8 baseline; W8 configuration unchanged.

### 5.4 Package-manager declaration (npm vs yarn) — not changed, registered
`package.json` declares `packageManager: yarn@1.22.22` and carries a 42-entry yarn `resolutions` block, but the only lockfile is npm's
and Vercel's install uses it. npm ignores `resolutions`, so those pins have never applied. Under yarn they would now force
versions **below** the patched ones (e.g. react-router 7.15.1, follow-redirects 1.16.0, node-forge 1.4.0, postcss 8.5.10), and several
entries are majors CRA 5 does not support (webpack-dev-server 5, resolve-url-loader 5, uuid 11, serialize-javascript 7). Rewriting the
block cannot be tested without a yarn lockfile, so it was left untouched; the inconsistency is recorded (remaining-work register W6-R3).
The npm `overrides` block (underscore only) is the mechanism npm honours.

### 5.5 `legacy-peer-deps=true` in `frontend/.npmrc` (pre-existing)
Every npm install of this project uses it, including the installs in this workstream (no flag was added on the command line). W6 did
not rely on it: the strict resolution in §4.2 shows the new tree needs no peer override except the pre-existing react-day-picker one. Removing
the setting requires resolving react-day-picker first (remaining-work register W6-R4).

### 5.6 Motor
Motor had to move with PyMongo. Motor 3.3.1's metadata allows `pymongo<5`, but with PyMongo 4.18.3 it fails at import
(`ImportError: cannot import name '_QUERY_OPTIONS' from 'pymongo.cursor'`, checked in a throwaway venv); Motor 3.6.x pins `pymongo<4.10`;
Motor 3.7.1 (`pymongo>=4.9,<5`) is the smallest release that works with 4.18.3. Motor itself is deprecated upstream in favour of
PyMongo's native async API — a future migration, not needed now.

### 5.7 emergentintegrations (unverifiable)
`emergentintegrations==0.2.0` is private and not installable here, so its own constraints on fastapi / starlette / pymongo / aiohttp cannot
be checked. The production API (Vercel) does not install it (the app falls back to `stripe_checkout.py`). If the Emergent environment is
still used (decision D-10), install there must be verified before relying on it.

## 6. Unresolved findings — written reasons
| Finding | Severity | Where it runs | Why not fixed in W6 | Path |
|---|---|---|---|---|
| CRA 5 toolchain: svgo / @svgr, css-select / nth-check, serialize-javascript, rollup-plugin-terser, workbox, webpack-dev-server / -middleware, sockjs, uuid, css-minimizer, resolve-url-loader (+ nested postcss 7) | 13 high, 4 moderate | `npm run build` / `npm start` on a developer or CI machine; **not in the browser bundle** (§4.3) | the only fix is a react-scripts major = replacing Create React App (framework replacement needs separate approval) | future migration F-1 (CRA → Vite or equivalent) |
| Jest 27 / jsdom 16 chain (@tootallnate/once) | 9 low | unit tests only | fix crosses a major inside react-scripts' test runner | F-1 |
| pillow 12.3.0 | 5 critical, 24 high | Emergent environment only; not imported | fix is 13.0.0 (major); package unused | remove with the Emergent clean-up, F-3 (D-10) |
| python-jose 3.5.0 / ecdsa 0.19.2 | 1 critical / 1 high | Emergent only; not imported | no fixed version exists | remove, F-3 (D-10) |
| filelock 3.32.2 (via huggingface_hub), oauthlib 3.3.1 (via requests-oauthlib) | 1 high / 2 high | Emergent only; not imported | fix is a major; constrained by their parents | F-3 (D-10) |
| emergentintegrations 0.2.0 compatibility with the upgraded pins | unknown | Emergent only | private package not available | verify on the Emergent host if it is still used (D-10) |

No unresolved finding is labelled fixed. No high or critical advisory is left without a reason (readiness criterion b).

## 7. Verification
(Recorded after the upgrade; details in `ENGINEERING_LOG_BATCH12_ONWARD.md`, Programme 02 / W6.)

- **Backend lint:** pyflakes over `backend/*.py` — 32 findings, identical to the `d31cb74` and DEF-03 baselines (0 new).
- **Candidate regression** (scratch venv with the new pins, before the `core.py` shim): 72 suites, 1,463 passed, 1 failed
  (`test_vercel_cors_dbdown::test_unresolvable_srv_host_gives_503_not_import_crash`) → root cause §5.1 of the audit report → shim.
- **Final full in-process regression** (real test venv upgraded to the new pins; `pip freeze` identical to the verified candidate venv;
  pre-W6 freeze saved for rollback): **72 suites, 1,464 passed, 0 failed, 0 skipped** — same count as the DEF-03 baseline. Integration areas
  covered through the HTTP stack: auth / JWT (≈ 35 suites), payments and webhooks (≈ 50), database and money paths (all), uploads
  (multipart in `test_programme01_admin_media`, `test_programme01_cross_module`), jobs / sweeps / cron (≈ 70); 67 suites start the app with
  `with TestClient` (startup hooks run).
- **Upload limits under Starlette 1.3.1** (scratch test reusing the admin-media fixtures): 1.5 MB and 4.9 MB images accepted (200);
  5 MB + 16 B refused with the application's own "Maximum size is 5 MB" (not a parser error).
- **Live-server suites** (uvicorn, `~/.cache/hg-test/live/run_live.sh`, disposable DB): **96 passed, 6 skipped** — identical to Programme 01
  (`test_health_dashboard` counted from the SMS-on run as before; its `test_register_send_otp` needs the SMS test adapter and fails with SMS
  off exactly as in the pre-W6 log). Every server logged "Application startup complete", "DB initialisation complete" and a clean shutdown
  → `@app.on_event` hooks run under Starlette 1.3.1 / FastAPI 0.133.1.
- **Frontend:** `npm ci` from the verified lockfile; `npm run lint` 172 files, 0 errors, 9 warnings (identical to W8); `npm run test:ci`
  7/7 in 2 suites; `npm run build:check` 13/13; `npm run quality` exit 0; production build `main.adee6fad.js` 551.17 kB gzip (repo build
  byte-identical to the verified scratch build). Bundle: 1,159 modules (W8: 1,156).
- **W8 compatibility:** real `craco build` on a scratch copy with injected fixtures fails for an undefined name (`no-undef`), an unresolved
  `@/` import ("Module not found"), an invalid named re-export and an invalid named import ("Attempted import error"); `import/named` is
  still proven by the `build:check` guard; standalone lint and the build use the same `.eslintrc.js` and now the same single ESLint 8.57.1.
  Fixtures existed only in the scratch copy.
- **Browser** (throwaway API on the upgraded backend + `hg_w6_ui_test`, production bundle with axios 1.20.0 / react-router 7.18.2, 1366 and
  390 px): **64/64** — UI logins (customer, HomeGenie member, admin) issuing JWTs, protected-route redirects, catch-all route, history back,
  deep-link reload, axios 401 error path (message shown, no token, no crash), 7 customer, 5 member and 8 admin screens; no page errors, no
  5xx, no sideways scroll; the only 4xx / console error is the deliberate wrong-password 401. Approved design unchanged (screenshots
  reviewed). One check was corrected during the run: at 390 px each page `h1` is hidden by design (`index.css:318-320`), so text is now
  read from the DOM rather than the visible text.
- **Audit after:** production backend 0 advisories (PyPI and OSV); Emergent set 5 packages; npm 26 (13 high, 4 moderate, 9 low; none in
  the bundle).

## 8. Before / after versions
**Backend — production and Emergent sets (`pyproject.toml`, `deploy/vercel-api/requirements.txt`, `requirements.txt`):**
fastapi 0.110.1 → 0.133.1 · starlette 0.37.2 → 1.3.1 · PyJWT 2.13.0 → 2.15.0 · pymongo 4.6.3 → 4.18.3 · motor 3.3.1 → 3.7.1 ·
dnspython 2.8.0 → 2.9.2.
**Backend — Emergent set only (`requirements.txt`):** certifi 2026.7.22 → 2026.10.18 · urllib3 2.7.0 → 2.8.0 · aiohttp 3.14.3 → 3.14.4 ·
multidict 6.7.1 → 6.9.1 · yarl 1.24.5 → 1.25.1 (required by aiohttp 3.14.4) · pyasn1 0.6.4 → 0.6.5 · black 26.5.1 → 26.10.1.
**Frontend (`package.json`, `package-lock.json`):** axios 1.18.0 → 1.20.0 · react-router-dom 7.15.0 → 7.18.2 (react-router 7.15.0 →
7.18.2) · postcss 8.5.10 → 8.5.23 · eslint 9.23.0 → 8.57.1 (aligned) · zod 3.24.4, @eslint/js 9.23.0, globals 15.15.0 removed ·
`overrides: { underscore: 1.13.8 }` added · in-range transitive patches: follow-redirects 1.16.1 → 1.16.3, node-forge 1.4.0 → 1.4.4,
body-parser 1.20.8 → 1.20.9, set-cookie-parser 2.7.2 → 2.7.3, underscore 1.13.6 → 1.13.8. Lockfile: 1,509 → 1,484 entries, 47 paths
changed (most are the removal of ESLint 9's own tree). All pins exact; no wildcard or range added.
**Not changed (class "no change"):** pydantic 2.13.4, bcrypt 4.1.3, httpx 0.28.1, requests 2.34.2, razorpay 2.0.1, stripe 14.4.1,
python-multipart 0.0.32, email-validator 2.3.0, python-dotenv 1.2.2 (no advisories); React 19.0.0, react-scripts 5.0.1, CRACO 7.1.0.

Audit evidence (scratch, not tracked): `audit_{req,prod}_{pypi,osv}.json`, `audit_{req,prod}_after_{pypi,osv}.json`,
`npm_audit_all.json`, `npm_audit_final.json`, `npm_audit_final_prod.json` in the session scratch directory; re-run with the commands in §9.

## 9. Upgrade plan by class (package by package)
| Class | Packages |
|---|---|
| Critical fix | PyJWT 2.15.0 (prod); certifi 2026.10.18 (Emergent pin) |
| High fix | starlette 1.3.1 + fastapi 0.133.1; pymongo 4.18.3 + motor 3.7.1; dnspython 2.9.2; urllib3 2.8.0; aiohttp 3.14.4; pyasn1 0.6.5; black 26.10.1; axios 1.20.0; react-router-dom 7.18.2; postcss 8.5.23; underscore 1.13.8 (override); follow-redirects, node-forge, body-parser (audit fix) |
| Maintenance | multidict 6.9.1, yarl 1.25.1; set-cookie-parser 2.7.3 |
| Breaking (separate work) | F-1 CRA → Vite (clears the 13 high / 4 moderate / 9 low toolchain findings); F-2 Motor → PyMongo async API; pillow 13, filelock 4, oauthlib 4 (only if those packages are kept) |
| Unused / duplicate | removed: zod, @eslint/js, globals; aligned: eslint 9 → 8.57.1; to remove with D-10: pillow, python-jose, ecdsa, twilio SDK, litellm, openai, google-genai and other Emergent-only packages (F-3) |
| No change | the "not changed" list in §8 |

**Repeatable audit (no install into the project):**
- Python: `pip-audit -r <requirements> --no-deps --disable-pip -s osv` (and `-s pypi`) on `backend/requirements.txt` minus the two
  non-index lines, and on a fresh resolution of `deploy/vercel-api/requirements.txt` + stripe.
- Frontend: `npm audit` in `frontend/`, then check flagged packages against the bundle's source maps (§4.3).

## 10. Future migrations (not started)
- **F-1 Create React App → Vite (or another maintained toolchain).** Clears all remaining npm findings; touches the build, Jest → Vitest,
  env-var prefix (`REACT_APP_`), CRACO / W8 ESLint wiring and the W8 guards. Needs separate approval.
- **F-2 Motor → PyMongo native async.** Motor is deprecated upstream; mechanical but touches every database call.
- **F-3 Emergent environment clean-up (D-10).** If Emergent hosting is retired, reduce `requirements.txt` to the production set (removes
  all five remaining Python findings and the unverifiable private package); if it is kept, verify `emergentintegrations` against the new pins.
- **F-4 Package-manager declaration.** Remove the yarn `packageManager` / `resolutions` (npm is what installs) or adopt yarn with a lockfile.
- **F-5 `httpx2` for Starlette's TestClient** (test-only deprecation warning).
- **F-6 Audit step in CI** (`deploy-frontend.yml` has none).
