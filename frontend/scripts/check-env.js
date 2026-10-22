#!/usr/bin/env node
/*
 * Runs automatically before `npm run build` (npm "prebuild" hook).
 * Production builds must know where the API lives: REACT_APP_BACKEND_URL is baked into the bundle at
 * build time, so a missing or wrong value would ship a site that cannot log in or load products.
 * This only validates a *public* URL — never put secrets in REACT_APP_* variables (they are public).
 */
const raw = (process.env.REACT_APP_BACKEND_URL || "").trim();
const fail = (msg) => {
  console.error(`\n✖ ${msg}\n  Set REACT_APP_BACKEND_URL to the API's public origin, e.g. https://<api-project>.vercel.app`);
  console.error("  (Vercel: Project → Settings → Environment Variables, for Production and Preview.)\n");
  process.exit(1);
};

if (!raw) fail("REACT_APP_BACKEND_URL is not set.");
let url;
try { url = new URL(raw); } catch { fail(`REACT_APP_BACKEND_URL is not a valid URL: "${raw}".`); }
if (url.protocol !== "https:") fail("REACT_APP_BACKEND_URL must use https:// in a production build.");
if (["localhost", "127.0.0.1", "0.0.0.0"].includes(url.hostname)) fail("REACT_APP_BACKEND_URL points at localhost.");
if (url.pathname.replace(/\/+$/, "") !== "" || url.search || url.hash) {
  fail("REACT_APP_BACKEND_URL must be just the origin (no path such as /api, no query).");
}
console.log(`✓ REACT_APP_BACKEND_URL = ${url.origin}`);
