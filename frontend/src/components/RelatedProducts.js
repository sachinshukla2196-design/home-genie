import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { API } from "@/lib/api";

const KEY = "hg_recent_products";
const money = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

/** Remembers the last products this browser opened (a per-viewer convenience; nothing is sent to the server until shown). */
export function rememberView(id) {
  try {
    const cur = JSON.parse(localStorage.getItem(KEY) || "[]").filter((x) => x !== id);
    localStorage.setItem(KEY, JSON.stringify([id, ...cur].slice(0, 12)));
  } catch { /* storage unavailable: nothing to remember */ }
}

function Strip({ title, items, testid }) {
  const navigate = useNavigate();
  if (!items || items.length === 0) return null;
  return (
    <section aria-label={title} data-testid={testid}>
      <h2 className="mb-2 font-display text-lg font-semibold text-ink">{title}</h2>
      <div className="no-scrollbar -mx-4 flex gap-3 overflow-x-auto px-4 pb-1">
        {items.map((p) => (
          <button key={p.id} onClick={() => navigate(`/app/products/${p.id}`)} className="hg-card w-36 shrink-0 overflow-hidden text-left sm:w-44">
            {p.images?.[0] ? <img src={p.images[0]} alt={p.name} className="aspect-square w-full object-cover" loading="lazy" /> : <div className="aspect-square w-full bg-brand-50" />}
            <div className="p-2.5"><div className="line-clamp-2 text-sm font-medium text-ink">{p.name}</div><div className="mt-1 font-display font-semibold">{money(p.selling_price)}</div></div>
          </button>
        ))}
      </div>
    </section>
  );
}

/** Batch 13, Phase 11: related products (same sub-category / category, on sale) and recently viewed (only products still on sale). */
export function RelatedProducts({ productId }) {
  const [related, setRelated] = useState([]);
  const [recent, setRecent] = useState([]);
  useEffect(() => {
    API.get(`/catalog/products/${productId}/related`).then(({ data }) => setRelated(data.items || [])).catch(() => {});
    let ids = [];
    try { ids = JSON.parse(localStorage.getItem(KEY) || "[]").filter((x) => x !== productId).slice(0, 10); } catch { ids = []; }
    if (ids.length) API.get("/catalog/products", { params: { ids: ids.join(",") } }).then(({ data }) => setRecent(data.items || [])).catch(() => {});
    rememberView(productId);
  }, [productId]);
  return (
    <div className="space-y-5">
      <Strip title="You may also like" items={related} testid="related-products" />
      <Strip title="Recently viewed" items={recent} testid="recent-products" />
    </div>
  );
}
