/**
 * HomeGenie share-link attribution.
 * A share link looks like  /products?ref=HG000123  or  /?ref=HG000123
 * The code is remembered for 30 days so the commission follows the sale even if
 * the customer browses, registers and checks out later.
 */
const KEY = "hg_seller_ref";
const TTL_DAYS = 30;

export function captureSellerRef(search) {
  const ref = new URLSearchParams(search || window.location.search).get("ref");
  if (!ref) return;
  localStorage.setItem(KEY, JSON.stringify({ ref: ref.trim().toUpperCase(), at: Date.now() }));
}

export function getSellerRef() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || "null");
    if (!raw?.ref) return null;
    if (Date.now() - raw.at > TTL_DAYS * 86400000) { localStorage.removeItem(KEY); return null; }
    return raw.ref;
  } catch { return null; }
}

export function clearSellerRef() {
  localStorage.removeItem(KEY);
}
