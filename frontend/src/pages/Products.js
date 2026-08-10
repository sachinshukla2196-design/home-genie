import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { ShoppingCart, Sparkles, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { API } from "@/lib/api";

export default function Products() {
  const { t, lang } = useI18n();
  const { add, count } = useCart();
  const navigate = useNavigate();
  const [products, setProducts] = useState(null);
  const [cat, setCat] = useState("all");
  const [cats, setCats] = useState([]);
  const sym = "₹";

  useEffect(() => {
    API.get("/products").then(({ data }) => setProducts(data)).catch(() => setProducts([]));
    API.get("/categories").then(({ data }) => setCats(data)).catch(() => {});
  }, []);

  const filtered = products?.filter((p) => cat === "all" || p.category === cat) || [];
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.products")}</h1>
          <p className="text-sm text-muted2">{t("landing.productsSub")}</p>
        </div>
        <Button onClick={() => navigate("/app/cart")} variant="outline" className="rounded-full border-forest/20 text-forest" data-testid="view-cart-btn">
          <ShoppingCart size={16} className="mr-1.5" /> {t("cart.title")} {count > 0 && `(${count})`}
        </Button>
      </div>

      <div className="flex flex-wrap gap-2">
        {["all", ...cats.map((c) => c.name)].map((c) => (
          <button key={c} onClick={() => setCat(c)} data-testid={`cat-${c}`}
            className={`rounded-full px-4 py-1.5 text-sm font-medium transition-all ${cat === c ? "bg-forest text-white" : "bg-white border border-brand-50 text-muted2 hover:text-forest"}`}>
            {c === "all" ? t("common.all") : c}
          </button>
        ))}
      </div>

      {!products ? (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-80 rounded-2xl" />)}</div>
      ) : (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((p, i) => (
            <motion.div key={p.id} initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}
              className="group flex flex-col overflow-hidden rounded-2xl border border-brand-50 bg-white shadow-card hover:shadow-soft transition-all" data-testid={`product-card-${p.sku}`}>
              <div className="relative aspect-[4/3] cursor-pointer overflow-hidden bg-brand-50" onClick={() => navigate(`/app/products/${p.id}`)}>
                <img src={p.images?.[0]} alt={p.name} className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" />
                {p.is_activation_product && <span className="absolute left-3 top-3 inline-flex items-center gap-1 rounded-full bg-gold px-2.5 py-1 text-[11px] font-bold text-forest"><Sparkles size={11} /> Activation</span>}
              </div>
              <div className="flex flex-1 flex-col p-5">
                <div className="text-xs font-semibold uppercase tracking-wide text-gold">{p.category}</div>
                <h3 className="mt-1 font-display text-lg font-medium text-ink line-clamp-1">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h3>
                <p className="mt-1 line-clamp-2 flex-1 text-sm text-muted2">{lang === "hi" && p.description_hi ? p.description_hi : p.description}</p>
                <div className="mt-4 flex items-center justify-between">
                  <div className="flex items-baseline gap-2">
                    <span className="font-display text-xl font-semibold text-forest">{money(p.selling_price)}</span>
                    <span className="text-sm text-muted2 line-through">{money(p.mrp)}</span>
                  </div>
                </div>
                <Button onClick={() => { add(p); toast.success(t("cta.addToCart")); }} className="mt-4 w-full rounded-full bg-forest hover:bg-brand" data-testid={`add-cart-${p.sku}`}>
                  {t("cta.addToCart")}
                </Button>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </div>
  );
}
