import React, { useState } from "react";
import { Truck } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { Pager } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { Money, Pill, ResponsiveTable, StateBlock, fmtDateTime, usePaged } from "@/components/vendor/kit";
import { FULFIL_PILL, OrderDetail } from "@/components/vendor/OrderDetail";

const QUEUES = [["packed", "vx.dsp.ready"], ["accepted", "vx.dsp.toPack"], ["dispatched", "vx.dsp.inTransit"], ["delivery_failed", "vx.dsp.exceptions"]];

/** The dispatch queue: what to pack, what is ready to hand over, what is on the road and what failed. Tracking is entered manually. */
export default function VendorDispatch({ embedded = false }) {
  const { t, lang } = useI18n();
  const [queue, setQueue] = useState("packed");
  const [open, setOpen] = useState(null);
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/orders", { status: queue }, 15);
  const counts = data?.counts || {};
  const rows = [...(items || [])].sort((a, b) => (a.dispatch_due_at || "9").localeCompare(b.dispatch_due_at || "9"));   // soonest deadline first
  const columns = [
    { key: "n", label: t("order.number"), render: (o) => <span className="font-semibold text-ink">{o.order_number}</span> },
    { key: "to", label: t("vp.shipTo"), render: (o) => <span className="text-muted2">{o.ship_to.city}, {o.ship_to.state}</span> },
    { key: "due", label: t("vx.ord.deadline"), render: (o) => (o.dispatch_overdue ? <Pill tone="bad" testid={`dsp-overdue-${o.order_number}`}>{t("vx.ord.overdue")}</Pill> : <span className="text-xs text-muted2">{fmtDateTime(o.dispatch_due_at, lang)}</span>) },
    { key: "trk", label: t("vp.tracking"), hideOnMobile: true, render: (o) => <span className="font-mono text-xs text-muted2">{o.fulfilment.tracking_number || "—"}</span> },
    { key: "pay", label: t("vx.ord.payment"), hideOnMobile: true, render: (o) => <Pill tone="muted">{o.payment_method === "cod" ? t("vp.cod") : t("vp.prepaid")}</Pill> },
    { key: "amt", label: t("order.total"), align: "right", render: (o) => <Money paise={o.items_total_paise} className="font-semibold text-ink" /> },
    { key: "st", label: t("vx.status"), render: (o) => <Pill tone={FULFIL_PILL[o.fulfilment.status]}>{t(`vp.f.${o.fulfilment.status}`)}</Pill> },
  ];
  return (
    <div className="space-y-5">
      {!embedded && <PageHeader title={t("vx.nav.dispatch")} subtitle={t("vx.dsp.sub")} icon={Truck} />}
      <p className="rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note" data-testid="dsp-manual-note">{t("vx.ord.manualTracking")}</p>
      <div className="flex flex-wrap gap-2" role="tablist">
        {QUEUES.map(([k, l]) => <button key={k} role="tab" aria-selected={queue === k} onClick={() => setQueue(k)} data-testid={`dsp-tab-${k}`} className={`rounded-full px-4 py-2 text-sm font-medium ${queue === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(l)} · {counts[k] ?? 0}</button>)}
      </div>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="dsp" empty={items && items.length === 0} emptyIcon={Truck} emptyTitle={t("vx.dsp.empty")}>
        <ResponsiveTable columns={columns} rows={rows} onRowClick={(o) => setOpen(o.id)} rowTestid={(o) => `dsp-row-${o.order_number}`} caption={t("vx.nav.dispatch")} />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="dsp-pager" />}
      <Dialog open={!!open} onOpenChange={(v) => !v && setOpen(null)}>
        <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="dsp-dialog">
          <DialogHeader><DialogTitle className="sr-only">{t("vx.ord.detail")}</DialogTitle><DialogDescription className="sr-only">{t("vx.ord.detail")}</DialogDescription></DialogHeader>
          {open && <OrderDetail orderId={open} onChanged={reload} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
