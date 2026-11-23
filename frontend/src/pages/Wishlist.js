import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Heart, Loader2, ShoppingBag, ShoppingCart, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { useCart } from "@/context/CartContext";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const SELECT = "h-10 w-full rounded-xl bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15";
const rupees = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

/** Batch 13, Phase 7B: the wishlist, showing each product's CURRENT price and availability from the server. Moving an item to the
 *  cart needs an in-stock option for products sold in variants; the order endpoint re-checks everything at checkout. */
export default function Wishlist() {
  const { t, lang } = useI18n();
  const { add } = useCart();
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [pick, setPick] = useState({});
  const load = useCallback(() => API.get("/wishlist").then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))), []);
  useEffect(() => { load(); }, [load]);

  const remove = async (i) => {
    try { await API.delete(`/wishlist/${i.product_id}`, { params: { variant_sku: i.variant_sku } }); load(); } catch (e) { toast.error(apiError(e)); }
  };
  const toCart = async (i) => {
    const p = i.product;
    let sku = i.variant_sku;
    if (i.status === "choose_variant") sku = pick[i.product_id];
    if (p.variants?.length && !sku) { toast.error(t("wish.chooseOption")); return; }
    const v = p.variants?.find((x) => x.sku === sku);
    if (v && !(v.stock > 0)) { toast.error(t("wish.optionOut")); return; }
    const label = v ? Object.values(v.attributes || {}).join(" / ") : "";
    add(p, 1, label, sku || "", v?.price ?? p.selling_price);
    await remove(i);
    toast.success(t("wish.moved"));
  };

  if (!d) return <Loader2 className="animate-spin text-muted2" />;
  return (
    <div className="space-y-5">
      <PageHeader title={t("wish.title")} subtitle={t("wish.sub")} icon={Heart} />
      {d.items.length === 0 ? <EmptyState icon={Heart} title={t("wish.empty")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="wish-empty" /> : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {d.items.map((i) => {
            const p = i.product;
            const inStock = (p?.variants || []).filter((v) => v.stock > 0);
            return (
              <li key={`${i.product_id}:${i.variant_sku}`} className="hg-card flex flex-col gap-3 p-4" data-testid={`wish-item-${i.product_id}`}>
                <div className="flex gap-3">
                  {p?.images?.[0] ? <img src={p.images[0]} alt="" className="h-20 w-20 shrink-0 rounded-xl object-cover" /> : <span className="flex h-20 w-20 shrink-0 items-center justify-center rounded-xl bg-brand-50"><ShoppingBag size={22} className="text-muted2" /></span>}
                  <div className="min-w-0 text-sm">
                    <button onClick={() => p && navigate(`/app/products/${p.id}`)} disabled={!p} className="line-clamp-2 text-left font-medium text-ink">{lang === "hi" && p?.name_hi ? p.name_hi : i.name}</button>
                    {i.variant_sku && <div className="text-xs text-muted2">{i.variant_sku}</div>}
                    {i.price != null && <div className="mt-1 font-display text-lg font-semibold tabular-nums">{rupees(i.price)}
                      {i.price_change && <span className={`ml-2 inline-flex items-center gap-0.5 text-xs font-medium ${i.price_change === "down" ? "text-hg-success" : "text-danger"}`}>
                        {i.price_change === "down" ? <ArrowDown size={12} /> : <ArrowUp size={12} />}{t(i.price_change === "down" ? "wish.priceDown" : "wish.priceUp")} {rupees(i.price_at_add)}</span>}</div>}
                    <div className={`text-xs font-semibold ${i.status === "available" || i.status === "choose_variant" ? "text-hg-success" : "text-danger"}`}>{t(`wish.status.${i.status}`)}</div>
                  </div>
                </div>
                {i.status === "choose_variant" && (
                  <select aria-label={t("wish.chooseOption")} className={SELECT} value={pick[i.product_id] || ""} onChange={(e) => setPick({ ...pick, [i.product_id]: e.target.value })}>
                    <option value="">{t("wish.chooseOption")}</option>
                    {inStock.map((v) => <option key={v.sku} value={v.sku}>{Object.values(v.attributes || {}).join(" / ")} · {rupees(v.price ?? p.selling_price)}</option>)}
                  </select>
                )}
                <div className="mt-auto flex gap-2">
                  <Button className="hg-btn flex-1 rounded-full" disabled={!["available", "choose_variant"].includes(i.status)} onClick={() => toCart(i)} data-testid={`wish-cart-${i.product_id}`}><ShoppingCart size={15} /> {t("wish.toCart")}</Button>
                  <Button variant="outline" size="icon" className="rounded-full" aria-label={t("wish.remove")} onClick={() => remove(i)}><Trash2 size={15} /></Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
