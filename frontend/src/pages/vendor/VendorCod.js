import React, { useState } from "react";
import { Banknote } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Pager } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { Money, Pill, ResponsiveTable, StateBlock, fmtDate, usePaged } from "@/components/vendor/kit";

const STATES = ["", "awaiting_delivery", "delivered_awaiting_cash", "collected", "discrepancy"];
const TONE = { awaiting_delivery: "muted", delivered_awaiting_cash: "warn", collected: "ok", discrepancy: "bad", not_applicable: "muted" };

/** Read-only COD reconciliation: delivered vs cash confirmed. Vendors cannot confirm cash; a HomeGenie or admin does. */
export default function VendorCod() {
  const { t, lang } = useI18n();
  const [state, setState] = useState("");
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/finance/cod", { state: state || undefined }, 20);
  const s = data?.summary;
  const cards = s ? [["delivered_awaiting_cash_paise", "vx.cod.awaitingCash", "warn"], ["overdue_paise", "vx.cod.overdue", "bad"], ["discrepancy_paise", "vx.cod.discrepancy", "bad"], ["collected_paise", "vx.cod.collected", "ok"], ["awaiting_delivery_paise", "vx.cod.awaitingDelivery", "muted"]] : [];
  const columns = [
    { key: "o", label: t("order.number"), render: (r) => <span className="font-semibold text-ink">{r.order_number}</span> },
    { key: "d", label: t("vx.date"), hideOnMobile: true, render: (r) => fmtDate(r.created_at, lang) },
    { key: "f", label: t("vx.cod.delivery"), render: (r) => t(`vp.f.${r.fulfilment_status}`) },
    { key: "st", label: t("vx.cod.cash"), render: (r) => <span className="inline-flex flex-wrap items-center gap-1"><Pill tone={TONE[r.state]}>{t(`vx.cod.state.${r.state}`)}</Pill>{r.overdue && <Pill tone="bad" testid={`cod-overdue-${r.order_number}`}>{t("vx.cod.overdueBy", { n: r.days_waiting })}</Pill>}</span> },
    { key: "amt", label: t("vx.amount"), align: "right", render: (r) => <Money paise={r.amount_paise} className="font-semibold text-ink" /> },
  ];
  return (
    <div className="space-y-5">
      <PageHeader title={t("vx.nav.cod")} subtitle={t("vx.cod.sub")} icon={Banknote} />
      {s && <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" data-testid="cod-summary">{cards.map(([k, l]) => <div key={k} className="hg-card p-4" data-testid={`cod-${k}`}><div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted2">{t(l)}</div><Money paise={s[k]} className="mt-2 block text-xl font-semibold text-ink" /></div>)}</div>}
      <p className="text-xs text-muted2" role="note">{t("vx.cod.note", { n: s?.overdue_days ?? 7 })}</p>
      <div className="flex flex-wrap gap-2" role="tablist">{STATES.map((k) => <button key={k || "all"} role="tab" aria-selected={state === k} onClick={() => setState(k)} data-testid={`cod-tab-${k || "all"}`} className={`rounded-full px-4 py-2 text-sm font-medium ${state === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{k ? t(`vx.cod.state.${k}`) : t("vp.o.all")}</button>)}</div>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="cod" empty={items && items.length === 0} emptyIcon={Banknote} emptyTitle={t("vx.cod.empty")}>
        <ResponsiveTable columns={columns} rows={items || []} rowKey={(r) => r.order_id} rowTestid={(r) => `cod-row-${r.order_number}`} caption={t("vx.nav.cod")} />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="cod-pager" />}
    </div>
  );
}
