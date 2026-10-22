import React from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { Trash2, Minus, Plus, ShoppingBag, ShoppingCart, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";

export default function Cart() {
  const { t, lang } = useI18n();
  const { items, setQty, remove, subtotal } = useCart();
  const navigate = useNavigate();
  const sym = "₹";
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;
  const gst = Math.round(subtotal * 0.05);
  const total = subtotal + gst;

  if (items.length === 0) return (
    <div className="mx-auto max-w-lg py-10">
      <EmptyState icon={ShoppingBag} title={t("cart.empty")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="empty-cart" />
    </div>
  );

  return (
    <div className="space-y-5">
      <PageHeader title={t("cart.title")} icon={ShoppingCart} />
      <div className="grid gap-5 lg:grid-cols-3">
        <motion.div layout className="space-y-3 lg:col-span-2">
          <AnimatePresence initial={true}>
            {items.map((i, idx) => (
              <motion.div key={`${i.product_id}-${i.variant || ""}`} layout
                initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0, transition: { delay: idx * 0.05, duration: 0.4, ease: [0.16, 1, 0.3, 1] } }}
                exit={{ opacity: 0, x: -40, scale: 0.96, transition: { duration: 0.25 } }}
                className="hg-card flex items-center gap-3 p-3 sm:gap-4 sm:p-4" data-testid={`cart-item-${i.sku}`}>
                <div className="h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-brand-50 sm:h-20 sm:w-20">
                  {i.image && <img src={i.image} alt={i.name} className="h-full w-full object-cover" />}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-ink">{lang === "hi" && i.name_hi ? i.name_hi : i.name}</div>
                  <div className="truncate text-sm text-muted2">{money(i.price)}{i.variant ? ` · ${i.variant}` : ""}</div>
                  <div className="hg-tile mt-2 inline-flex items-center rounded-full p-0.5">
                    <motion.button whileTap={{ scale: 0.88 }} onClick={() => setQty(i.product_id, i.quantity - 1, i.variant)} aria-label="Decrease quantity"
                      className="flex h-8 w-8 items-center justify-center rounded-full text-ink transition-colors hover:bg-brand-50"><Minus size={14} /></motion.button>
                    <span className="w-8 text-center text-sm font-semibold tabular-nums text-ink">{i.quantity}</span>
                    <motion.button whileTap={{ scale: 0.88 }} onClick={() => setQty(i.product_id, i.quantity + 1, i.variant)} aria-label="Increase quantity"
                      className="flex h-8 w-8 items-center justify-center rounded-full text-ink transition-colors hover:bg-brand-50"><Plus size={14} /></motion.button>
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <div className="font-display font-semibold tabular-nums text-hg-violet dark:text-hg-lavender">{money(i.price * i.quantity)}</div>
                  <motion.button whileTap={{ scale: 0.88 }} onClick={() => remove(i.product_id, i.variant)} aria-label={t("cart.remove")} title={t("cart.remove")}
                    className="flex h-8 w-8 items-center justify-center rounded-full text-danger transition-colors hover:bg-danger/10" data-testid={`remove-${i.sku}`}><Trash2 size={16} /></motion.button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
          className="hg-card h-fit p-5 sm:p-6 lg:sticky lg:top-24">
          <h3 className="font-display text-lg font-semibold text-ink">{t("cart.summary")}</h3>
          <div className="mt-4 space-y-2.5 text-sm">
            <Row label={t("order.subtotal")} value={money(subtotal)} />
            <Row label={`${t("order.gst")} (5%)`} value={money(gst)} />
            <div className="my-2 border-t border-brand-50" />
            <Row label={t("order.total")} value={money(total)} bold />
          </div>
          <motion.div {...pressable} className="mt-6">
            <Button onClick={() => navigate("/app/checkout")} className="hg-btn h-11 w-full rounded-full px-6" data-testid="cart-checkout-btn">
              {t("cta.checkout")} <ArrowRight size={16} className="ml-1.5" />
            </Button>
          </motion.div>
        </motion.div>
      </div>
    </div>
  );
}

function Row({ label, value, bold }) {
  return (
    <div className={`flex justify-between gap-3 ${bold ? "font-display text-lg font-semibold text-ink" : "text-muted2"}`}>
      <span>{label}</span><span className={`tabular-nums ${bold ? "text-hg-violet dark:text-hg-lavender" : ""}`}>{value}</span>
    </div>
  );
}
