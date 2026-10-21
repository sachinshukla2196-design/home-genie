import React from "react";
import { useNavigate } from "react-router-dom";
import { Trash2, Minus, Plus, ShoppingBag } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
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
    <div>
      <h1 className="mb-6 font-display text-2xl font-semibold text-ink">{t("cart.title")}</h1>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {items.map((i) => (
            <div key={`${i.product_id}-${i.variant || ""}`} className="flex items-center gap-4 rounded-2xl border border-brand-50 bg-white p-4" data-testid={`cart-item-${i.sku}`}>
              <img src={i.image} alt={i.name} className="h-20 w-20 rounded-lg object-cover" />
              <div className="flex-1">
                <div className="font-medium text-ink">{lang === "hi" && i.name_hi ? i.name_hi : i.name}</div>
                <div className="text-sm text-muted2">{money(i.price)}{i.variant ? ` · ${i.variant}` : ""}</div>
                <div className="mt-2 inline-flex items-center rounded-full border border-brand-50">
                  <button onClick={() => setQty(i.product_id, i.quantity - 1, i.variant)} className="p-1.5 text-forest"><Minus size={14} /></button>
                  <span className="w-8 text-center text-sm font-semibold">{i.quantity}</span>
                  <button onClick={() => setQty(i.product_id, i.quantity + 1, i.variant)} className="p-1.5 text-forest"><Plus size={14} /></button>
                </div>
              </div>
              <div className="text-right">
                <div className="font-display font-semibold text-forest">{money(i.price * i.quantity)}</div>
                <button onClick={() => remove(i.product_id, i.variant)} className="mt-2 text-danger hover:opacity-70" data-testid={`remove-${i.sku}`}><Trash2 size={16} /></button>
              </div>
            </div>
          ))}
        </div>
        <div className="h-fit rounded-2xl border border-brand-50 bg-white p-6">
          <h3 className="font-display text-lg font-medium text-ink">{t("cart.summary")}</h3>
          <div className="mt-4 space-y-2 text-sm">
            <Row label={t("order.subtotal")} value={money(subtotal)} />
            <Row label={`${t("order.gst")} (5%)`} value={money(gst)} />
            <div className="my-2 border-t border-brand-50" />
            <Row label={t("order.total")} value={money(total)} bold />
          </div>
          <Button onClick={() => navigate("/app/checkout")} className="mt-6 w-full rounded-full bg-forest hover:bg-brand" data-testid="cart-checkout-btn">{t("cta.checkout")}</Button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value, bold }) {
  return <div className={`flex justify-between ${bold ? "font-display text-lg font-semibold text-forest" : "text-muted2"}`}><span>{label}</span><span>{value}</span></div>;
}
