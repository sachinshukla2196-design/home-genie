import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Sparkles, Check, Minus, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useCart } from "@/context/CartContext";
import { API } from "@/lib/api";

export default function ProductDetail() {
  const { id } = useParams();
  const { t, lang } = useI18n();
  const { add } = useCart();
  const navigate = useNavigate();
  const [p, setP] = useState(null);
  const [qty, setQty] = useState(1);
  const sym = "₹";

  useEffect(() => { API.get(`/products/${id}`).then(({ data }) => setP(data)).catch(() => {}); }, [id]);
  const money = (v) => `${sym}${Number(v).toLocaleString("en-IN")}`;

  if (!p) return <div className="grid gap-8 lg:grid-cols-2"><Skeleton className="h-96 rounded-2xl" /><Skeleton className="h-96 rounded-2xl" /></div>;

  return (
    <div>
      <button onClick={() => navigate("/app/products")} className="mb-4 flex items-center gap-1.5 text-sm font-medium text-muted2 hover:text-forest" data-testid="back-products"><ArrowLeft size={16} /> {t("cta.back")}</button>
      <div className="grid gap-8 lg:grid-cols-2">
        <div className="overflow-hidden rounded-2xl border border-brand-50 bg-white">
          <img src={p.images?.[0]} alt={p.name} className="aspect-square w-full object-cover" />
        </div>
        <div>
          <div className="mt-3 text-xs font-semibold uppercase tracking-wide text-gold">{p.category}</div>
          <h1 className="mt-1 font-display text-3xl font-semibold text-ink">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h1>
          <div className="mt-4 flex items-baseline gap-3">
            <span className="font-display text-3xl font-semibold text-forest">{money(p.selling_price)}</span>
            <span className="text-lg text-muted2 line-through">{money(p.mrp)}</span>
            <span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand">{Math.round((1 - p.selling_price / p.mrp) * 100)}% OFF</span>
          </div>
          <p className="mt-5 leading-relaxed text-muted2">{lang === "hi" && p.description_hi ? p.description_hi : p.description}</p>
          <div className="mt-4 text-sm text-muted2">GST: {p.gst_percent}% · SKU: {p.sku} · Stock: {p.stock}</div>

          <div className="mt-6 flex items-center gap-4">
            <div className="flex items-center rounded-full border border-brand-50">
              <button onClick={() => setQty((q) => Math.max(1, q - 1))} className="p-2.5 text-forest" data-testid="qty-minus"><Minus size={16} /></button>
              <span className="w-10 text-center font-semibold" data-testid="qty-value">{qty}</span>
              <button onClick={() => setQty((q) => q + 1)} className="p-2.5 text-forest" data-testid="qty-plus"><Plus size={16} /></button>
            </div>
          </div>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button onClick={() => { add(p, qty); toast.success(t("cta.addToCart")); }} variant="outline" className="rounded-full border-forest/20 px-7 text-forest hover:bg-brand-50" data-testid="detail-add-cart">{t("cta.addToCart")}</Button>
            <Button onClick={() => { add(p, qty); navigate("/app/cart"); }} className="rounded-full bg-forest px-7 hover:bg-brand" data-testid="detail-buy-now">{t("cta.buyNow")}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
