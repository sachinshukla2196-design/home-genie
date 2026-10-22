import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { ArrowLeft, Check, Minus, Plus, ShoppingCart, Zap, PackageX } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { Stagger, StaggerItem, pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { API } from "@/lib/api";

export default function ProductDetail() {
  const { id } = useParams();
  const { t, lang } = useI18n();
  const { add } = useCart();
  const navigate = useNavigate();
  const [p, setP] = useState(null);
  const [failed, setFailed] = useState(false);
  const [qty, setQty] = useState(1);
  const [picked, setPicked] = useState({});
  const [added, setAdded] = useState(false);
  const sym = "₹";

  useEffect(() => { API.get(`/products/${id}`).then(({ data }) => setP(data)).catch(() => setFailed(true)); }, [id]);
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;
  const variantLabel = () => (p?.options || []).map((o) => `${o.name}: ${picked[o.name] || ""}`).filter((x) => !x.endsWith(": ")).join(" / ");
  const missingChoice = () => (p?.options || []).some((o) => (o.values || []).length > 0 && !picked[o.name]);
  const guard = () => { if (missingChoice()) { toast.error(t("product.chooseOptions")); return false; } return true; };

  const backBtn = (
    <button onClick={() => navigate("/app/products")} className="group mb-4 inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-sm font-medium text-muted2 transition-colors hover:bg-brand-50 hover:text-ink" data-testid="back-products">
      <ArrowLeft size={16} className="transition-transform group-hover:-translate-x-0.5" /> {t("cta.back")}
    </button>
  );

  if (!p && failed) return (
    <div className="mx-auto max-w-lg">
      {backBtn}
      <EmptyState icon={PackageX} title={t("product.unavailable")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="product-unavailable" />
    </div>
  );

  if (!p) return (
    <div className="grid gap-6 lg:grid-cols-2 lg:gap-8">
      <Skeleton className="aspect-square w-full rounded-3xl" />
      <div className="space-y-4">
        <Skeleton className="h-5 w-24 rounded-full" />
        <Skeleton className="h-9 w-3/4 rounded-xl" />
        <Skeleton className="h-8 w-40 rounded-xl" />
        <Skeleton className="h-24 w-full rounded-2xl" />
        <Skeleton className="h-11 w-full rounded-full" />
      </div>
    </div>
  );

  const off = p.mrp > p.selling_price ? Math.round((1 - p.selling_price / p.mrp) * 100) : 0;

  const addToCart = () => {
    if (!guard()) return;
    add(p, qty, variantLabel());
    toast.success(t("cta.addToCart"));
    setAdded(true);
    setTimeout(() => setAdded(false), 1400);
  };

  return (
    <div>
      {backBtn}
      <div className="grid gap-6 lg:grid-cols-2 lg:gap-8">
        <motion.div initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
          className="hg-card relative overflow-hidden !rounded-3xl lg:sticky lg:top-24 lg:self-start">
          <div className="relative aspect-square overflow-hidden bg-brand-50">
            {p.images?.[0] && <img src={p.images[0]} alt={p.name} className="h-full w-full object-cover" />}
            <span className="pointer-events-none absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-black/35 to-transparent" />
            {off > 0 && <span className="hg-off-badge absolute right-3 top-3 rounded-lg px-2.5 py-1 text-sm font-bold shadow-sm">-{off}%</span>}
          </div>
        </motion.div>

        <Stagger className="hg-card min-w-0 space-y-5 p-5 sm:p-6">
          <StaggerItem>
            {p.category && <span className="inline-flex rounded-full bg-hg-violet/15 px-3 py-1 text-xs font-semibold text-hg-violet ring-1 ring-hg-lavender/25 dark:text-hg-lavender">{p.category}</span>}
            <h1 className="mt-3 break-words font-display text-2xl font-semibold text-ink sm:text-3xl">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h1>
            <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="font-display text-3xl font-semibold tabular-nums text-hg-violet dark:text-hg-lavender">{money(p.selling_price)}</span>
              {off > 0 && <span className="text-lg text-muted2 line-through">{money(p.mrp)}</span>}
              {off > 0 && <span className="rounded-full bg-hg-success/15 px-2.5 py-0.5 text-xs font-semibold text-hg-success ring-1 ring-hg-success/25">{off}% OFF</span>}
            </div>
          </StaggerItem>

          <StaggerItem>
            <p className="break-words leading-relaxed text-muted2">{lang === "hi" && p.description_hi ? p.description_hi : p.description}</p>
            <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted2">
              <span className="hg-tile rounded-full px-3 py-1">GST: {p.gst_percent}%</span>
              <span className="hg-tile rounded-full px-3 py-1">SKU: {p.sku}</span>
              <span className="hg-tile rounded-full px-3 py-1">Stock: {p.stock}</span>
            </div>
          </StaggerItem>

          {(p.options || []).length > 0 && (
            <StaggerItem className="space-y-4" data-testid="variant-options">
              {(p.options || []).map((opt) => (
                <div key={opt.name}>
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted2">{opt.name}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(opt.values || []).map((v) => {
                      const active = picked[opt.name] === v;
                      return (
                        <motion.button key={v} type="button" whileTap={{ scale: 0.94 }} onClick={() => setPicked((x) => ({ ...x, [opt.name]: v }))}
                          data-testid={`variant-${opt.name}-${v}`} aria-pressed={active}
                          className={`relative rounded-full px-4 py-2 text-sm font-medium transition-colors ${active ? "text-white" : "hg-chip-off"}`}>
                          {active && <motion.span layoutId={`opt-pill-${opt.name}`} className="hg-chip-on absolute inset-0 rounded-full" transition={{ type: "spring", stiffness: 480, damping: 34 }} />}
                          <span className="relative">{v}</span>
                        </motion.button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </StaggerItem>
          )}

          <StaggerItem>
            <div className="text-xs font-semibold uppercase tracking-wide text-muted2">{t("cart.qty")}</div>
            <div className="hg-tile mt-2 inline-flex items-center rounded-full p-1">
              <motion.button whileTap={{ scale: 0.88 }} onClick={() => setQty((q) => Math.max(1, q - 1))} aria-label="Decrease quantity"
                className="flex h-9 w-9 items-center justify-center rounded-full text-ink transition-colors hover:bg-brand-50" data-testid="qty-minus"><Minus size={16} /></motion.button>
              <span className="w-10 text-center font-semibold tabular-nums text-ink" data-testid="qty-value">{qty}</span>
              <motion.button whileTap={{ scale: 0.88 }} onClick={() => setQty((q) => q + 1)} aria-label="Increase quantity"
                className="flex h-9 w-9 items-center justify-center rounded-full text-ink transition-colors hover:bg-brand-50" data-testid="qty-plus"><Plus size={16} /></motion.button>
            </div>
          </StaggerItem>

          <StaggerItem className="grid gap-3 sm:grid-cols-2">
            <motion.div {...pressable}>
              <Button onClick={addToCart} className="hg-btn h-11 w-full overflow-hidden rounded-full px-6" data-testid="detail-add-cart">
                <AnimatePresence mode="wait" initial={false}>
                  {added ? (
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
            <motion.div {...pressable}>
              <Button onClick={() => { if (!guard()) return; add(p, qty, variantLabel()); navigate("/app/cart"); }} variant="outline"
                className="h-11 w-full rounded-full border-brand-50 bg-transparent px-6 text-ink" data-testid="detail-buy-now">
                <Zap size={16} className="mr-1.5" /> {t("cta.buyNow")}
              </Button>
            </motion.div>
          </StaggerItem>
        </Stagger>
      </div>
    </div>
  );
}
