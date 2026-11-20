/**
 * HomeGenie sales attribution (HG-01).
 * A product share link looks like  /app/products/<id>?ref=HG000123  (or /?ref=HG000123 for the shop).
 * The code is remembered for 30 days so the commission follows a genuine sale even if the customer logs in or registers
 * first. The server decides whether the code is eligible (an activated HomeGenie who is not the buyer).
 *
 * Rules that keep attribution honest:
 *  - only a well-formed HomeGenie ID is accepted;
 *  - /register?ref=... is a SPONSOR code for a new member, never a seller code (no earning from recruitment);
 *  - the code is cleared after the order it attributed is placed, and on logout (shared devices).
 */
const KEY = "hg_seller_ref";
const TTL_DAYS = 30;
const ID_RE = /^HG\d{4,10}$/;

export function captureSellerRef(search, pathname) {
  try {
    const path = pathname ?? window.location.pathname;
    if (path.startsWith("/register")) return;
    const ref = (new URLSearchParams(search ?? window.location.search).get("ref") || "").trim().toUpperCase();
    if (!ID_RE.test(ref)) return;
    localStorage.setItem(KEY, JSON.stringify({ ref, at: Date.now() }));
  } catch { /* storage unavailable: attribution is simply not remembered */ }
}

export function getSellerRef() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!raw?.ref || !ID_RE.test(raw.ref)) return null;
    if (Date.now() - raw.at > TTL_DAYS * 86400000) { localStorage.removeItem(KEY); return null; }
    return raw.ref;
  } catch { return null; }
}

export function clearSellerRef() {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

export function productShareLink(productId, distributorId) {
  return `${window.location.origin}/app/products/${productId}?ref=${encodeURIComponent(distributorId)}`;
}
