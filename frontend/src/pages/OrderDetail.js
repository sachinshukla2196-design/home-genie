import React, { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Logo } from "@/components/Logo";
import { useI18n } from "@/context/I18nContext";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function OrderDetail() {
  const { id } = useParams();
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [o, setO] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;
  const { user } = useAuth();

  const load = useCallback(() => { API.get(`/orders/${id}`).then(({ data }) => setO(data)).catch(() => {}); }, [id]);
  useEffect(() => { load(); }, [load]);

  const markCollected = async () => {
    try {
      await API.post(`/orders/${id}/cod-collected`);
      toast.success(t("order.collectedOk"));
      load();
    } catch (err) { toast.error(apiError(err)); }
  };
  if (!o) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4 flex items-center justify-between">
        <button onClick={() => navigate("/app/orders")} className="flex items-center gap-1.5 text-sm font-medium text-muted2 hover:text-forest"><ArrowLeft size={16} /> {t("cta.back")}</button>
        <Button onClick={() => window.print()} variant="outline" className="rounded-full border-forest/20 text-forest" data-testid="print-invoice"><Download size={15} className="mr-1.5" /> {t("order.invoice")}</Button>
      </div>
      <div className="rounded-2xl border border-brand-50 bg-white p-8 shadow-card" data-testid="invoice-card">
        <div className="flex items-start justify-between border-b border-brand-50 pb-6">
          <Logo />
          <div className="text-right">
            <div className="font-display text-xl font-semibold text-forest">{t("order.invoice")}</div>
            <div className="text-sm text-muted2">{o.invoice_number || "—"}</div>
            <div className="text-sm text-muted2">{o.order_number}</div>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-6 py-6 text-sm">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted2">Bill To</div>
            <div className="font-medium text-ink">{o.address?.full_name}</div>
            <div className="text-muted2">{o.address?.line1}</div>
            <div className="text-muted2">{o.address?.city}, {o.address?.state} - {o.address?.pincode}</div>
            <div className="text-muted2">{o.address?.mobile}</div>
          </div>
          <div className="text-right">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted2">{t("order.status")}</div>
            <div className="font-medium capitalize text-forest">{o.status}</div>
            <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted2">{t("order.date")}</div>
            <div className="text-muted2">{(o.created_at || "").slice(0, 10)}</div>
          </div>
        </div>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="pb-2">{t("common.name")}</th><th className="pb-2 text-center">{t("cart.qty")}</th><th className="pb-2 text-right">Price</th><th className="pb-2 text-right">{t("order.total")}</th></tr></thead>
          <tbody>
            {o.items.map((i) => (
              <tr key={i.product_id} className="border-b border-brand-50/60">
                <td className="py-3 font-medium text-ink">{lang === "hi" && i.name_hi ? i.name_hi : i.name}</td>
                <td className="py-3 text-center text-muted2">{i.quantity}</td>
                <td className="py-3 text-right text-muted2">{money(i.price)}</td>
                <td className="py-3 text-right font-medium text-ink">{money(i.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="ml-auto mt-6 w-full max-w-xs space-y-2 text-sm">
          <div className="flex justify-between text-muted2"><span>{t("order.subtotal")}</span><span>{money(o.subtotal)}</span></div>
          <div className="flex justify-between text-muted2"><span>{t("order.gst")} ({o.gst_percent}%)</span><span>{money(o.gst_amount)}</span></div>
          <div className="flex justify-between border-t border-brand-50 pt-2 font-display text-lg font-semibold text-forest"><span>{t("order.total")}</span><span>{money(o.total)}</span></div>
        </div>
        {o.payment_method === "cod" && o.payment_status === "cod_pending" && o.seller_user_id === user?.id && (
          <Button onClick={markCollected} className="mt-6 w-full rounded-full btn-gold" data-testid="order-cod-collected">
            {t("order.markCollected")}
          </Button>
        )}
        {o.payment_status !== "paid" && o.payment_method !== "cod" && (
          <Button onClick={() => navigate("/app/checkout")} className="mt-6 w-full rounded-full bg-forest hover:bg-brand" data-testid="order-paynow">{t("order.payNow")}</Button>
        )}
      </div>
    </div>
  );
}
