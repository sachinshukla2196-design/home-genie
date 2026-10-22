import React, { useCallback, useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowLeft, Download, Package, Check, Circle, XCircle, MapPin, Banknote, Truck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Logo } from "@/components/Logo";
import { useI18n } from "@/context/I18nContext";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { pressable } from "@/components/motion";

const STATUS_COLORS = {
  paid: "bg-hg-success/15 text-hg-success ring-hg-success/30",
  processing: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30",
  shipped: "bg-hg-violet/15 text-hg-violet ring-hg-lavender/30 dark:text-hg-lavender",
  delivered: "bg-hg-success/15 text-hg-success ring-hg-success/30",
  payment_pending: "bg-danger/10 text-danger ring-danger/25",
  cancelled: "bg-danger/10 text-danger ring-danger/25",
};

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
  if (!o) return <Skeleton className="h-96 rounded-3xl" />;

  // Visual progress of the existing status field (no extra tracking data is invented).
  const flow = ["payment_pending", "paid", "processing", "shipped", "delivered"];
  const cancelled = o.status === "cancelled";
  const curIdx = flow.indexOf(o.status);
  const steps = cancelled ? [o.status] : curIdx >= 0 ? flow : [o.status];
  const reached = (idx) => cancelled || curIdx < 0 || idx <= curIdx;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <button onClick={() => navigate("/app/orders")} className="group inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-sm font-medium text-muted2 transition-colors hover:bg-brand-50 hover:text-ink">
          <ArrowLeft size={16} className="transition-transform group-hover:-translate-x-0.5" /> {t("cta.back")}
        </button>
        <Button onClick={() => window.print()} variant="outline" className="h-11 rounded-full border-brand-50 bg-transparent px-5 text-ink" data-testid="print-invoice"><Download size={15} className="mr-1.5" /> {t("order.invoice")}</Button>
      </div>

      {/* Status timeline */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="hg-card p-5 sm:p-6 print:hidden">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2.5 font-display text-lg font-semibold text-ink">
            <span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><Package size={18} /></span> {t("order.status")}
          </h3>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${STATUS_COLORS[o.status] || "bg-brand-50 text-muted2 ring-brand-50"}`}>{o.status}</span>
        </div>
        <ol className="relative space-y-0">
          {steps.map((s, idx) => {
            const done = reached(idx);
            const current = s === o.status;
            const last = idx === steps.length - 1;
            const bad = cancelled || s === "payment_pending";
            return (
              <motion.li key={s} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.1 + idx * 0.07, duration: 0.35 }}
                className="relative flex gap-3 pb-4 last:pb-0">
                {!last && <span className={`absolute left-[11px] top-6 h-[calc(100%-1.25rem)] w-0.5 rounded-full ${done && reached(idx + 1) ? "bg-hg-violet" : "bg-brand-50"}`} />}
                <span className={`relative z-[1] flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${current ? (bad ? "bg-danger text-white ring-4 ring-danger/20" : "bg-hg-violet text-white ring-4 ring-hg-violet/25") : done ? "bg-hg-violet/80 text-white" : "bg-brand-50 text-muted2 ring-1 ring-brand-50"}`}>
                  {current && cancelled ? <XCircle size={14} /> : done ? <Check size={13} strokeWidth={3} /> : <Circle size={8} />}
                </span>
                <span className={`pt-0.5 text-sm ${current ? "font-semibold text-ink" : done ? "text-ink" : "text-muted2"}`}>{s.replace(/_/g, " ")}</span>
              </motion.li>
            );
          })}
        </ol>
      </motion.div>

      {/* Per-seller shipments (vendor-fulfilled lines) */}
      {(o.fulfilments || []).length > 0 && (
        <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, delay: 0.04 }}
          className="hg-card p-5 sm:p-6 print:hidden" data-testid="shipments-card">
          <div className="mb-3 flex items-center gap-2 font-display text-lg font-semibold text-ink"><span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><Truck size={17} /></span>{t("ship.title")}</div>
          <div className="space-y-3">
            {o.fulfilments.map((f) => (
              <div key={f.vendor_id} className="hg-tile p-4" data-testid={`shipment-${f.vendor_id}`}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm"><span className="text-muted2">{t("ship.seller")}:</span> <b className="text-ink">{f.vendor_name}</b></div>
                  <span className="rounded-full bg-hg-violet/15 px-2.5 py-0.5 text-[11px] font-semibold text-hg-lavender ring-1 ring-hg-lavender/30" data-testid="shipment-status">{t(`vp.f.${f.status}`)}</span>
                </div>
                <div className="mt-1 truncate text-xs text-muted2">{o.items.filter((li) => li.vendor_id === f.vendor_id).map((li) => `${li.name} ×${li.quantity}`).join(", ")}</div>
                {f.tracking_number && (
                  <div className="mt-2 text-sm text-ink" data-testid="shipment-tracking">{t("ship.tracking")}: {f.carrier} · <b>{f.tracking_number}</b>
                    {/^https:\/\//.test(f.tracking_url || "") && <a href={f.tracking_url} target="_blank" rel="noopener noreferrer" className="ml-2 text-hg-lavender underline">↗</a>}
                  </div>
                )}
                {(f.events || []).slice(-1).map((e) => e.note && ["rejected", "cancelled", "delivery_failed"].includes(e.status) ? <div key="n" className="mt-1 text-xs text-danger">{e.note}</div> : null)}
              </div>
            ))}
          </div>
        </motion.div>
      )}

      <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, delay: 0.08, ease: [0.16, 1, 0.3, 1] }}
        className="hg-card p-5 sm:p-8" data-testid="invoice-card">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-brand-50 pb-6">
          <Logo />
          <div className="min-w-0 text-right">
            <div className="font-display text-xl font-semibold text-hg-violet dark:text-hg-lavender">{t("order.invoice")}</div>
            <div className="break-all text-sm text-muted2">{o.invoice_number || "—"}</div>
            <div className="break-all text-sm text-muted2">{o.order_number}</div>
          </div>
        </div>
        <div className="grid gap-4 py-6 text-sm sm:grid-cols-2">
          <div className="hg-tile min-w-0 p-4">
            <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted2"><MapPin size={13} /> Bill To</div>
            <div className="break-words font-medium text-ink">{o.address?.full_name}</div>
            <div className="break-words text-muted2">{o.address?.line1}</div>
            <div className="break-words text-muted2">{o.address?.city}, {o.address?.state} - {o.address?.pincode}</div>
            <div className="text-muted2">{o.address?.mobile}</div>
          </div>
          <div className="hg-tile min-w-0 p-4 sm:text-right">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted2">{t("order.status")}</div>
            <div className="font-medium capitalize text-ink">{o.status}</div>
            <div className="mt-2 text-xs font-semibold uppercase tracking-wide text-muted2">{t("order.date")}</div>
            <div className="text-muted2">{(o.created_at || "").slice(0, 10)}</div>
            {o.payment_method === "cod" && (
              <span className="mt-2 inline-flex items-center gap-1 rounded-full bg-hg-gold/15 px-2.5 py-0.5 text-[11px] font-semibold text-hg-gold ring-1 ring-hg-gold/30">
                <Banknote size={12} /> {o.payment_status === "paid" ? t("order.cod") : t("order.codPending")}
              </span>
            )}
          </div>
        </div>
        <div className="-mx-5 overflow-x-auto px-5 sm:mx-0 sm:px-0">
          <table className="w-full min-w-[420px] text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className="pb-2 font-semibold">{t("common.name")}</th><th className="pb-2 text-center font-semibold">{t("cart.qty")}</th><th className="pb-2 text-right font-semibold">Price</th><th className="pb-2 text-right font-semibold">{t("order.total")}</th></tr></thead>
            <tbody>
              {o.items.map((i) => (
                <tr key={i.product_id} className="border-t border-brand-50 transition-colors hover:bg-brand-50/60">
                  <td className="py-3 pr-2 font-medium text-ink">{lang === "hi" && i.name_hi ? i.name_hi : i.name}</td>
                  <td className="py-3 text-center tabular-nums text-muted2">{i.quantity}</td>
                  <td className="py-3 text-right tabular-nums text-muted2">{money(i.price)}</td>
                  <td className="py-3 text-right font-medium tabular-nums text-ink">{money(i.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="ml-auto mt-6 w-full max-w-xs space-y-2 text-sm">
          <div className="flex justify-between text-muted2"><span>{t("order.subtotal")}</span><span className="tabular-nums">{money(o.subtotal)}</span></div>
          <div className="flex justify-between text-muted2"><span>{t("order.gst")} ({o.gst_percent}%)</span><span className="tabular-nums">{money(o.gst_amount)}</span></div>
          <div className="flex justify-between border-t border-brand-50 pt-2 font-display text-lg font-semibold text-ink"><span>{t("order.total")}</span><span className="tabular-nums text-hg-violet dark:text-hg-lavender">{money(o.total)}</span></div>
        </div>
        {o.payment_method === "cod" && o.payment_status === "cod_pending" && o.seller_user_id === user?.id && (
          <motion.div {...pressable} className="mt-6 print:hidden">
            <Button onClick={markCollected} className="btn-gold h-11 w-full rounded-full" data-testid="order-cod-collected">
              <Banknote size={16} className="mr-1.5" /> {t("order.markCollected")}
            </Button>
          </motion.div>
        )}
        {o.payment_status !== "paid" && o.payment_method !== "cod" && (
          <motion.div {...pressable} className="mt-6 print:hidden">
            <Button onClick={() => navigate("/app/checkout")} className="hg-btn h-11 w-full rounded-full" data-testid="order-paynow">{t("order.payNow")}</Button>
          </motion.div>
        )}
      </motion.div>
    </div>
  );
}
