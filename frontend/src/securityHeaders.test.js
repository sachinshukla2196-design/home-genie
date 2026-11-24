/**
 * Programme 02 / W1 (criterion d): the frontend is served with a Content-Security-Policy and frame protection (frontend/vercel.json),
 * and the build emits no inline script (INLINE_RUNTIME_CHUNK=false) so a strict script-src can hold. This test fails if either is
 * weakened. A browser check under these exact headers is recorded in the engineering log.
 */
const fs = require("fs");
const path = require("path");

const root = path.resolve(__dirname, "..");
const vercel = JSON.parse(fs.readFileSync(path.join(root, "vercel.json"), "utf8"));
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
const block = (vercel.headers || []).find((h) => h.source === "/(.*)");
const headers = Object.fromEntries(((block && block.headers) || []).map((h) => [h.key.toLowerCase(), h.value]));
const csp = Object.fromEntries((headers["content-security-policy"] || "").split(";").map((d) => d.trim()).filter(Boolean)
  .map((d) => { const [k, ...v] = d.split(/\s+/); return [k, v]; }));

test("every response carries the security headers", () => {
  expect(block).toBeTruthy();
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(headers["permissions-policy"]).toMatch(/camera=\(\)/);
});

test("the policy cannot be framed and allows no plugins or base hijack", () => {
  expect(csp["frame-ancestors"]).toEqual(["'none'"]);
  expect(csp["object-src"]).toEqual(["'none'"]);
  expect(csp["base-uri"]).toEqual(["'self'"]);
  expect(csp["form-action"]).toEqual(["'self'"]);
  expect(csp["default-src"]).toEqual(["'self'"]);
});

test("scripts: only our own files and the payment checkout - no inline, no eval, no wildcard", () => {
  expect(csp["script-src"]).toEqual(["'self'", "https://checkout.razorpay.com"]);
  const all = headers["content-security-policy"];
  expect(all).not.toMatch(/unsafe-eval/);
  expect(csp["script-src"].join(" ")).not.toMatch(/unsafe-inline|\*|https:$|data:/);
  expect(csp["frame-src"]).toEqual(["https://api.razorpay.com", "https://checkout.razorpay.com"]);
});

test("the production build emits no inline runtime script", () => {
  expect(pkg.scripts.build).toMatch(/INLINE_RUNTIME_CHUNK=false/);
});
