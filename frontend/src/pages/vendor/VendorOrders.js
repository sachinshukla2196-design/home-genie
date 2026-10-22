import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { ClipboardList, MapPin, Phone, Package, Truck, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { FULFIL_TONE, inr } from "@/pages/vendor/VendorDashboard";

const TABS = ["all", "new", "accepted", "packed", "dispatched", "delivery_failed", "delivered"];

// Actions available from each fulfilment state (mirrors the server state machine).
const ACTIONS = {
  new: [{ to: "accepted", key: "vp.act.accept", primary: true }, { to: "rejected", key: "vp.act.reject", needs: "reason" }],
  accepted: [{ to: "packed", key: "vp.act.pack", primary: true }, { to: "cancelled", key: "vp.act.cancel", needs: "reason" }],
  packed: [{ to: "dispatched", key: "vp.act.dispatch", primary: true, needs: "tracking" }, { to: "cancelled", key: "vp.act.cancel", needs: "reason" }],
  dispatched: [{ to: "delivered", key: "vp.act.deliver", primary: true, needs: "evidence" }, { to: "delivery_failed", key: "vp.act.fail", needs: "reason" }],
  delivery_failed: [{ to: "dispatched", key: "vp.act.redispatch", primary: true, needs: "tracking" }, { to: "returned_to_origin", key: "vp.act.rto", needs: "reason" }],
};

export default function VendorOrders() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const tab = params.get("status") || "all";
  const [orders, setOrders] = useState(null);
  const [open, setOpen] = useState(null);

  const load = useCallback(() => API.get("/vendor/orders").then(({ data }) => setOrders(data)).catch(() => setOrders([])), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const id = params.get("open");
    if (id && orders) setOpen(orders.find((o) => o.id === id) || null);
  }, [params, orders]);

  const shown = (orders || []).filter((o) => tab === "all" || o.fulfilment.status === tab);
  const count = (s) => (orders || []).filter((o) => s === "all" || o.fulfilment.status === s).length;

  return (
    <div className="space-y-5">
      <PageHeader title={t("vp.orders")} icon={ClipboardList} />
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist">
        {TABS.map((s) => {
          const on = tab === s;
          return (
            <button key={s} role="tab" aria-selected={on} onClick={() => setParams(s === "all" ? {} : { status: s })} data-testid={`vo-tab-${s}`}
              className={`relative shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${on ? "text-white" : "hg-chip-off"}`}>
              {on && <motion.span layoutId="vendor-orders-tab" className="hg-chip-on absolute inset-0 rounded-full" />}
              <span className="relative">{s === "all" ? t("vp.o.all") : t(`vp.f.${s}`)} · {count(s)}</span>
            </button>
          );
        })}
      </div>

      {!orders ? <Skeleton className="h-64 rounded-3xl" /> : shown.length === 0 ? <EmptyState icon={ClipboardList} title={t("vp.noOrders")} testid="vo-empty" /> : (
        <div className="space-y-3">
          {shown.map((o, i) => (
            <motion.button key={o.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.04 }}
              onClick={() => setOpen(o)} data-testid={`vo-row-${o.order_number}`}
              className="hg-card hg-lift flex w-full flex-wrap items-center gap-3 p-4 text-left sm:flex-nowrap">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="font-semibold text-ink">{o.order_number}</span>
                  <span className="text-xs text-muted2">{(o.created_at || "").slice(0, 10)}</span></div>
                <div className="truncate text-sm text-muted2">{o.items.map((li) => `${li.name}${li.variant ? ` (${li.variant})` : ""} ×${li.quantity}`).join(", ")}</div>
              </div>
              <span className="rounded-full bg-white/5 px-2.5 py-0.5 text-[11px] font-semibold text-muted2 ring-1 ring-white/10">{o.payment_method === "cod" ? t("vp.cod") : t("vp.prepaid")}</span>
              <span className="font-semibold tabular-nums text-ink">{inr(o.items_total)}</span>
              <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${FULFIL_TONE[o.fulfilment.status]}`} data-testid={`vo-status-${o.order_number}`}>{t(`vp.f.${o.fulfilment.status}`)}</span>
            </motion.button>
          ))}
        </div>
      )}

      {open && <OrderDialog o={open} t={t} onClose={() => { setOpen(null); if (params.get("open")) { params.delete("open"); setParams(params); } }}
        onUpdated={(fresh) => { setOpen(fresh); load(); }} />}
    </div>
  );
}

function OrderDialog({ o, t, onClose, onUpdated }) {
  const [action, setAction] = useState(null);
  const [form, setForm] = useState({ note: "", carrier: "", tracking_number: "", tracking_url: "" });
  const [busy, setBusy] = useState(false);
  const f = o.fulfilment;

  const run = async (a) => {
    setBusy(true);
    try {
      const { data } = await API.post(`/vendor/orders/${o.id}/fulfilment`, { status: a.to, ...form });
      toast.success(t(`vp.f.${a.to}`) + " ✓");
      setAction(null); setForm({ note: "", carrier: "", tracking_number: "", tracking_url: "" });
      onUpdated(data);
    } catch (err) { toast.error(apiError(err)); }
    finally { setBusy(false); }
  };
  const start = (a) => (a.needs ? setAction(a) : run(a));

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="vo-dialog">
        <DialogHeader>
          <DialogTitle className="flex flex-wrap items-center gap-2">
            {o.order_number}
            <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${FULFIL_TONE[f.status]}`} data-testid="vo-dialog-status">{t(`vp.f.${f.status}`)}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="hg-tile p-4 text-sm">
          <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><MapPin size={13} /> {t("vp.shipTo")}</div>
          <div className="font-medium text-ink">{o.ship_to.full_name}</div>
          <div className="text-muted2">{o.ship_to.line1}, {o.ship_to.city}, {o.ship_to.state} - {o.ship_to.pincode}</div>
          <div className="mt-1 flex items-center gap-1.5 text-muted2"><Phone size={12} /> {o.ship_to.mobile}</div>
        </div>

        <div>
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><Package size={13} /> {t("vp.items")}</div>
          <div className="space-y-2">
            {o.items.map((li) => (
              <div key={li.sku + li.variant} className="hg-tile flex items-center gap-3 p-2.5">
                {li.image && <img src={li.image} alt="" className="h-11 w-11 rounded-lg object-cover" />}
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-ink">{li.name}</div>
                  <div className="text-xs text-muted2">{li.sku}{li.variant ? ` · ${li.variant}` : ""} · ×{li.quantity}</div></div>
                <div className="text-sm font-semibold tabular-nums text-ink">{inr(li.total)}</div>
              </div>
            ))}
          </div>
          <div className="mt-2 flex justify-between text-sm"><span className="text-muted2">{o.payment_method === "cod" ? t("vp.cod") : t("vp.prepaid")}</span><b className="text-ink">{inr(o.items_total)}</b></div>
        </div>

        {f.tracking_number && (
          <div className="flex items-center gap-2 rounded-xl bg-[#5B7CFF]/10 p-3 text-sm ring-1 ring-[#8FA6FF]/25">
            <Truck size={16} className="text-[#8FA6FF]" /> {f.carrier} · <b className="text-ink">{f.tracking_number}</b>
          </div>
        )}

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted2">{t("vp.timeline")}</div>
          <ol className="relative space-y-3 pl-6">
            <span aria-hidden className="absolute bottom-2 left-[0.55rem] top-2 w-px bg-white/15" />
            {f.events.map((e, i) => (
              <li key={i} className="relative text-sm">
                <span className="absolute -left-6 top-0.5 flex h-[1.15rem] w-[1.15rem] items-center justify-center rounded-full bg-hg-violet text-white"><Check size={11} /></span>
                <span className="font-medium text-ink">{t(`vp.f.${e.status}`)}</span>
                <span className="ml-2 text-xs text-muted2">{(e.at || "").slice(0, 16).replace("T", " ")}</span>
                {e.note && <div className="text-xs text-muted2">{e.note}</div>}
              </li>
            ))}
          </ol>
        </div>

        {action ? (
          <div className="space-y-3 rounded-2xl bg-white/[0.04] p-4 ring-1 ring-white/10">
            {action.needs === "tracking" && (
              <div className="grid gap-3 sm:grid-cols-2">
                <div><Label className="text-sm text-ink">{t("vp.carrier")}</Label><Input value={form.carrier} onChange={(e) => setForm({ ...form, carrier: e.target.value })} className="mt-1.5" data-testid="vo-carrier" /></div>
                <div><Label className="text-sm text-ink">{t("vp.tracking")}</Label><Input value={form.tracking_number} onChange={(e) => setForm({ ...form, tracking_number: e.target.value })} className="mt-1.5" data-testid="vo-tracking" /></div>
                <div className="sm:col-span-2"><Label className="text-sm text-ink">{t("vp.trackingUrl")}</Label><Input value={form.tracking_url} onChange={(e) => setForm({ ...form, tracking_url: e.target.value })} className="mt-1.5" /></div>
              </div>
            )}
            {(action.needs === "reason" || action.needs === "evidence") && (
              <div><Label className="text-sm text-ink">{action.needs === "evidence" ? t("vp.evidence") : t("vp.reason")}</Label>
                <Input value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} className="mt-1.5" data-testid="vo-note" /></div>
            )}
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setAction(null)} className="h-10 rounded-full border-brand-50 bg-transparent px-4">✕</Button>
              <Button onClick={() => run(action)} disabled={busy} className={`h-10 rounded-full px-5 ${action.primary ? "hg-btn" : "bg-danger text-white hover:bg-danger/90"}`} data-testid="vo-confirm">{t("vp.confirm")} · {t(action.key)}</Button>
            </div>
          </div>
        ) : (
          (ACTIONS[f.status] || []).length > 0 && (
            <div className="flex flex-wrap gap-2">
              {ACTIONS[f.status].map((a) => (
                <Button key={a.to} onClick={() => start(a)} disabled={busy} data-testid={`vo-act-${a.to}`}
                  className={`h-11 flex-1 rounded-full px-5 ${a.primary ? "hg-btn" : "border border-danger/40 bg-transparent text-danger hover:bg-danger/10"}`}>
                  {t(a.key)}
                </Button>
              ))}
            </div>
          )
        )}
      </DialogContent>
    </Dialog>
  );
}
