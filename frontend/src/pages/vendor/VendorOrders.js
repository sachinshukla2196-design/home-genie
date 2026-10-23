import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ClipboardList } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { Pager, SearchBox, useDebounced } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { Money, Pill, ResponsiveTable, StateBlock, fmtDate, usePaged } from "@/components/vendor/kit";
import { FULFIL_PILL, OrderDetail } from "@/components/vendor/OrderDetail";

const TABS = ["all", "new", "accepted", "packed", "dispatched", "delivery_failed", "delivered", "returned_to_origin", "rejected", "cancelled"];

export default function VendorOrders() {
  const { t, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("status") || "all";
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const [open, setOpen] = useState(sp.get("open"));
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/orders", { q: dq || undefined, status: tab === "all" ? undefined : tab }, 15);
  const counts = data?.counts || {};
  useEffect(() => { setOpen(sp.get("open")); }, [sp]);

  const setTab = (s) => { const n = new URLSearchParams(sp); n.delete("open"); s === "all" ? n.delete("status") : n.set("status", s); setSp(n); };
  const close = () => { setOpen(null); if (sp.get("open")) { const n = new URLSearchParams(sp); n.delete("open"); setSp(n, { replace: true }); } };

  const columns = [
    { key: "order_number", label: t("order.number"), render: (o) => <span className="font-semibold text-ink">{o.order_number}<span className="ml-2 text-xs font-normal text-muted2">{fmtDate(o.created_at, lang)}</span></span> },
    { key: "items", label: t("vp.items"), render: (o) => <span className="block max-w-[22rem] truncate text-muted2">{o.items.map((li) => `${li.name}${li.variant ? ` (${li.variant})` : ""} ×${li.quantity}`).join(", ")}</span> },
    { key: "pay", label: t("vx.ord.payment"), render: (o) => <Pill tone="muted">{o.payment_method === "cod" ? t("vp.cod") : t("vp.prepaid")}</Pill> },
    { key: "deadline", label: t("vx.ord.deadline"), hideOnMobile: true, render: (o) => (o.dispatch_overdue ? <Pill tone="bad">{t("vx.ord.overdue")}</Pill> : ["new", "accepted", "packed"].includes(o.fulfilment.status) ? <span className="text-xs text-muted2">{fmtDate(o.dispatch_due_at, lang)}</span> : <span className="text-muted2">—</span>) },
    { key: "total", label: t("order.total"), align: "right", render: (o) => <Money paise={o.items_total_paise} className="font-semibold text-ink" /> },
    { key: "st", label: t("vx.status"), render: (o) => <span className="inline-flex flex-wrap items-center gap-1"><Pill tone={FULFIL_PILL[o.fulfilment.status]} testid={`vo-status-${o.order_number}`}>{t(`vp.f.${o.fulfilment.status}`)}</Pill>{o.cancel_requested && <Pill tone="warn">{t("vx.ord.cancelRequested")}</Pill>}</span> },
  ];

  return (
    <div className="space-y-5">
      <PageHeader title={t("vp.orders")} icon={ClipboardList} />
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist">
        {TABS.map((s) => (
          <button key={s} role="tab" aria-selected={tab === s} onClick={() => setTab(s)} data-testid={`vo-tab-${s}`}
            className={`shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${tab === s ? "hg-chip-on text-white" : "hg-chip-off"}`}>
            {s === "all" ? t("vp.o.all") : t(`vp.f.${s}`)} · {counts[s] ?? 0}</button>
        ))}
      </div>
      <SearchBox value={q} onChange={setQ} placeholder={t("vp.searchOrders")} testid="vo-search" />
      <StateBlock loading={loading} error={error} onRetry={reload} rows={4} testid="vo" empty={items && items.length === 0} emptyIcon={ClipboardList} emptyTitle={dq ? t("vp.noMatch") : t("vp.noOrders")}>
        <ResponsiveTable columns={columns} rows={items || []} onRowClick={(o) => setOpen(o.id)} rowTestid={(o) => `vo-row-${o.order_number}`} caption={t("vp.orders")} testid="vo-table" />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="vo-pager" />}

      <Dialog open={!!open} onOpenChange={(v) => !v && close()}>
        <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="vo-dialog">
          <DialogHeader><DialogTitle className="sr-only">{t("vx.ord.detail")}</DialogTitle><DialogDescription className="sr-only">{t("vx.ord.detail")}</DialogDescription></DialogHeader>
          {open && <OrderDetail orderId={open} onChanged={reload} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
