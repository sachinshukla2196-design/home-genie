import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { ShoppingCart, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { API } from "@/lib/api";
import { pressable } from "@/components/motion";
import { MerchSections } from "@/components/MerchSections";

export default function Products() {
  const { t, lang } = useI18n();
  const { add, count } = useCart();
  const navigate = useNavigate();
  const [sp, setSp] = useSearchParams();
  const cat = sp.get("category") || "all";
  const [q, setQ] = useState(sp.get("q") || "");
  const [dq, setDq] = useState(q);
  const [sort, setSort] = useState("relevance");
  const [brand, setBrand] = useState("");
  const [colour, setColour] = useState("");
  const [inStock, setInStock] = useState(false);
  const [maxPrice, setMaxPrice] = useState("");
  const [page, setPage] = useState(1);
  const [res, setRes] = useState(null);
  const [facets, setFacets] = useState(null);
  const [sugg, setSugg] = useState(null);
  const [cats, setCats] = useState([]);
  const [added, setAdded] = useState(null);
  const sym = "₹";

  // Batch 13 (Phase 11): search, filters, sorting and paging run on the server (only products on sale are ever returned)
  useEffect(() => { API.get("/categories").then(({ data }) => setCats(data)).catch(() => {}); }, []);
  useEffect(() => { const h = setTimeout(() => { setDq(q.trim()); setPage(1); }, 300); return () => clearTimeout(h); }, [q]);
  useEffect(() => {
    setFacets(null);
    API.get("/catalog/facets", { params: cat !== "all" ? { category: cat } : {} }).then(({ data }) => setFacets(data)).catch(() => {});
  }, [cat]);
  useEffect(() => {
    if (q.trim().length < 2) { setSugg(null); return undefined; }
    const h = setTimeout(() => API.get("/catalog/suggest", { params: { q: q.trim() } }).then(({ data }) => setSugg(data)).catch(() => {}), 200);
    return () => clearTimeout(h);
  }, [q]);
  useEffect(() => {
    setRes(null);
    const params = [["sort", sort === "relevance" && !dq ? "newest" : sort], ["page", page], ["page_size", 24]];
    if (dq) params.push(["q", dq]);
    if (cat !== "all") params.push(["category", cat]);
    if (brand) params.push(["brand", brand]);
    if (colour) params.push(["attr.colour", colour]);
    if (inStock) params.push(["in_stock", "true"]);
    if (maxPrice) params.push(["max_price", maxPrice]);
    const qs = new URLSearchParams(params.map(([k, v]) => [k, String(v)])).toString();
    API.get(`/catalog/search?${qs}`).then(({ data }) => setRes(data)).catch(() => setRes({ items: [], total: 0, pages: 1 }));
  }, [dq, cat, sort, brand, colour, inStock, maxPrice, page]);
  const setCat = (c) => { const n = new URLSearchParams(sp); if (c === "all") n.delete("category"); else n.set("category", c); setSp(n, { replace: true }); setPage(1); setBrand(""); setColour(""); };
  const products = res ? res.items : null;
  const filtered = products || [];
  const browsing = !dq && cat === "all" && !brand && !colour && !inStock && !maxPrice && page === 1;
  const addToCart = (p) => {
    add(p);
    toast.success(t("cta.addToCart"));
    setAdded(p.id);
    setTimeout(() => setAdded((cur) => (cur === p.id ? null : cur)), 1400);
  };
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;

  return (
    <div className="space-y-5">
      <div className="hidden flex-wrap items-center justify-between gap-3 lg:flex">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.products")}</h1>
          <p className="text-sm text-muted2">{t("landing.productsSub")}</p>
        </div>
        <Button onClick={() => navigate("/app/cart")} variant="outline" className="rounded-full border-forest/20 text-forest" data-testid="view-cart-btn">
          <ShoppingCart size={16} className="mr-1.5" /> {t("cart.title")} {count > 0 && `(${count})`}
        </Button>
      </div>

      <div className="relative flex flex-wrap items-center gap-2" data-testid="shop-tools">
        <input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => setTimeout(() => setSugg(null), 200)} placeholder="Search products, brands, fabrics" aria-label="Search products"
          className="hgv-input h-11 min-w-0 flex-1 rounded-full px-4 text-sm" data-testid="shop-search" autoComplete="off" />
        <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} aria-label="Sort products" className="hgv-input h-11 rounded-full px-4 text-sm" data-testid="shop-sort">
          <option value="relevance">{dq ? "Best match" : "Newest"}</option><option value="newest">Newest</option>
          <option value="price_asc">Price: low to high</option><option value="price_desc">Price: high to low</option><option value="name">Name</option>
        </select>
        {sugg && (sugg.products.length > 0 || sugg.brands.length > 0) && (
          <div className="absolute left-0 right-0 top-12 z-30 rounded-2xl bg-white p-2 shadow-xl ring-1 ring-brand-100 dark:bg-hg-bg" role="listbox" data-testid="shop-suggest">
            {sugg.products.map((p) => <button key={p.id} role="option" aria-selected="false" onMouseDown={() => navigate(`/app/products/${p.id}`)} className="block w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-brand-50">{p.name}</button>)}
            {sugg.brands.map((b) => <button key={b} role="option" aria-selected="false" onMouseDown={() => { setBrand(b); setQ(""); setSugg(null); }} className="block w-full rounded-lg px-3 py-2 text-left text-sm text-muted2 hover:bg-brand-50">Brand: {b}</button>)}
          </div>
        )}
      </div>
      {facets && (
        <div className="flex flex-wrap items-center gap-2 text-sm" data-testid="shop-filters">
          {facets.brands.length > 0 && <select aria-label="Brand" value={brand} onChange={(e) => { setBrand(e.target.value); setPage(1); }} className="hgv-input h-10 rounded-full px-3"><option value="">All brands</option>{facets.brands.map((b) => <option key={b} value={b}>{b}</option>)}</select>}
          {facets.attributes?.colour && <select aria-label="Colour" value={colour} onChange={(e) => { setColour(e.target.value); setPage(1); }} className="hgv-input h-10 rounded-full px-3"><option value="">Any colour</option>{facets.attributes.colour.map((b) => <option key={b} value={b}>{b}</option>)}</select>}
          {facets.price.max > 0 && <select aria-label="Maximum price" value={maxPrice} onChange={(e) => { setMaxPrice(e.target.value); setPage(1); }} className="hgv-input h-10 rounded-full px-3"><option value="">Any price</option>{[500, 1000, 2000, 5000, 10000].filter((v) => v < facets.price.max).map((v) => <option key={v} value={v}>Up to ₹{v.toLocaleString("en-IN")}</option>)}</select>}
          <label className="flex items-center gap-2 rounded-full px-3 py-2 ring-1 ring-brand-100"><input type="checkbox" checked={inStock} onChange={(e) => { setInStock(e.target.checked); setPage(1); }} /> In stock only</label>
          {res && <span className="ml-auto text-xs text-muted2">{res.total} products</span>}
        </div>
      )}
      {browsing && <MerchSections />}
      <div className="no-scrollbar -mx-4 flex gap-2.5 overflow-x-auto px-4 pb-1">
        {["all", ...cats.map((c) => c.name)].map((c) => (
          <motion.button key={c} whileTap={{ scale: 0.94 }} onClick={() => setCat(c)} data-testid={`cat-${c}`}
            className={`relative shrink-0 whitespace-nowrap rounded-full px-5 py-2.5 text-sm font-medium transition-colors ${cat === c ? "text-white dark:text-white" : "hg-chip-off"}`}>
            {cat === c && <motion.span layoutId="cat-pill" className="hg-chip-on absolute inset-0 rounded-full" transition={{ type: "spring", stiffness: 480, damping: 34 }} />}
            <span className="relative">{c === "all" ? t("common.all") : c}</span>
          </motion.button>
        ))}
      </div>

      {!products ? (
        <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-72 rounded-3xl" />)}</div>
      ) : (
        filtered.length === 0 ? (
          <div className="hg-card p-10 text-center text-muted2" data-testid="products-empty">{t("empty.products")}</div>
        ) : (
        <div className="grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4">
          {filtered.map((p, i) => {
            const off = p.mrp > p.selling_price ? Math.round((1 - p.selling_price / p.mrp) * 100) : 0;
            return (
            <motion.div key={p.id} layout initial={{ opacity: 0, y: 18, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }}
              transition={{ delay: Math.min(i, 8) * 0.05, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
              className="hg-card hg-lift group flex flex-col overflow-hidden" data-testid={`product-card-${p.sku}`}>
              <div className="relative aspect-square cursor-pointer overflow-hidden bg-brand-50" onClick={() => navigate(`/app/products/${p.id}`)}>
                {p.images?.[0] && <img src={p.images[0]} alt={p.name} loading="lazy" className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110" />}
                <span className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/30 to-transparent" />
                {off > 0 && <span className="hg-off-badge absolute right-2.5 top-2.5 rounded-lg px-2 py-0.5 text-xs font-bold shadow-sm" data-testid={`off-${p.sku}`}>-{off}%</span>}
              </div>
              <div className="flex flex-1 flex-col p-3.5 sm:p-4">
                <h3 className="line-clamp-1 text-base font-medium text-ink">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h3>
                <div className="mt-0.5 line-clamp-1 text-xs text-muted2 sm:text-sm">{p.category}</div>
                <div className="mt-2 flex flex-wrap items-baseline gap-x-2">
                  <span className="font-display text-xl font-semibold text-hg-violet dark:text-hg-lavender">{money(p.selling_price)}</span>
                  {off > 0 && <span className="text-sm text-muted2 line-through">{money(p.mrp)}</span>}
                </div>
                <div className="flex-1" />
                <motion.div {...pressable} className="mt-3">
                  <Button onClick={() => addToCart(p)} className="hg-btn h-11 w-full overflow-hidden rounded-full text-sm" data-testid={`add-cart-${p.sku}`}>
                    <AnimatePresence mode="wait" initial={false}>
                      {added === p.id ? (
                        <motion.span key="ok" className="inline-flex items-center gap-1.5" initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -14, opacity: 0 }}>
                          <Check size={16} /> {t("cta.added")}
                        </motion.span>
                      ) : (
                        <motion.span key="add" className="inline-flex items-center gap-1.5" initial={{ y: 14, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: -14, opacity: 0 }}>
                          <ShoppingCart size={16} /> {t("cta.addToCart")}
                        </motion.span>
                      )}
                    </AnimatePresence>
                  </Button>
                </motion.div>
              </div>
            </motion.div>
            );
          })}
        </div>
        )
      )}
      {res && res.pages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm" data-testid="shop-pager">
          <Button variant="outline" className="rounded-full" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
          <span className="text-muted2">{page} / {res.pages}</span>
          <Button variant="outline" className="rounded-full" disabled={page >= res.pages} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </div>
  );
}
