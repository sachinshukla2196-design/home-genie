import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { ShoppingCart, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { API } from "@/lib/api";
import { pressable } from "@/components/motion";

export default function Products() {
  const { t, lang } = useI18n();
  const { add, count } = useCart();
  const navigate = useNavigate();
  const [products, setProducts] = useState(null);
  const [cat, setCat] = useState("all");
  const [cats, setCats] = useState([]);
  const [added, setAdded] = useState(null);
  const sym = "₹";

  useEffect(() => {
    API.get("/products").then(({ data }) => setProducts(data)).catch(() => setProducts([]));
    API.get("/categories").then(({ data }) => setCats(data)).catch(() => {});
  }, []);

  const filtered = products?.filter((p) => cat === "all" || p.category === cat) || [];
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
              transition={{ delay: i * 0.05, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
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
    </div>
  );
}
