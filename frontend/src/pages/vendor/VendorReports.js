import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Download, FileBarChart, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Money, Pill, RangeBar, ResponsiveTable, StateBlock, downloadCsv, inrP } from "@/components/vendor/kit";

const SETTLE_STATUSES = ["requested", "approved", "paid", "rejected", "failed"];
const query = (range, from, to) => ({ range, date_from: range === "custom" ? from : undefined, date_to: range === "custom" ? to : undefined });

const metric = (k, label, value, hint) => (
  <div key={k} className="hg-card p-4" data-testid={`rep-${k}`}>
    <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted2">{label}</div>
    <div className="mt-2 text-2xl font-semibold tabular-nums text-ink">{value}</div>
    {hint && <div className="mt-1 text-xs text-muted2">{hint}</div>}
  </div>
);

const row = (label, paise, testid, negative) => (
  <div key={testid} className="hg-tile flex items-center justify-between gap-3 p-3 text-sm" data-testid={testid}>
    <span className="text-muted2">{label}</span>
    <Money paise={paise} className={`font-semibold ${negative && paise < 0 ? "text-danger" : "text-ink"}`} />
  </div>
);

export default function VendorReports() {
  const { t } = useI18n();
  const [params, setParams] = useSearchParams();
  const range = params.get("range") || "30d";
  const from = params.get("from") || "";
  const to = params.get("to") || "";
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const req = useRef(0);
  const load = useCallback(() => {
    if (range === "custom" && !(from && to)) return;
    const id = ++req.current; setError(null);
    API.get("/vendor/reports/current", { params: query(range, from, to) })
      .then(({ data }) => { if (id === req.current) setD(data); }).catch((e) => { if (id === req.current) setError(apiError(e)); });
  }, [range, from, to]);
  useEffect(() => { load(); }, [load]);

  const exportCsv = () => {
    downloadCsv("/vendor/reports/current.csv", `vendor-report-${d.range.from}-to-${d.range.to}.csv`, query(range, from, to))
      .catch((e) => toast.error(apiError(e)));
  };

  if (!d) return <StateBlock loading={!error} error={error} onRetry={load} rows={4} testid="rep" />;

  const s = d.sales, e = d.earnings, n = s.orders, st = d.settlements;
  const statusRows = Object.entries(d.orders_by_status).map(([k, v]) => ({ key: k, name: t(`vp.f.${k}`), n: v }));
  const columns = [
    { key: "name", label: t("vx.rep.colProduct"), render: (p) => <span className="font-medium text-ink">{p.name}<span className="block text-xs text-muted2">{p.sku}</span></span> },
    { key: "units", label: t("vx.rep.colUnits"), align: "right", render: (p) => p.units_sold },
    { key: "value", label: t("vx.rep.colValue"), align: "right", render: (p) => <Money paise={p.value_paise} /> },
    { key: "stock", label: t("vx.rep.colStock"), align: "right", render: (p) => p.stock },
    {
      key: "status", label: t("vx.rep.colStatus"),
      render: (p) => (
        <span className="flex flex-wrap gap-1">
          {p.out_of_stock ? <Pill tone="bad">{t("vx.rep.stock.out")}</Pill> : p.low_stock ? <Pill tone="warn">{t("vx.rep.stock.low")}</Pill> : <Pill tone="ok">{t("vx.rep.stock.ok")}</Pill>}
          {p.archived ? <Pill tone="muted">{t("vx.rep.archived")}</Pill> : !p.is_active && <Pill tone="muted">{t("vx.rep.notLive")}</Pill>}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-6" data-testid="vendor-reports">
      <PageHeader title={t("vx.nav.report")} subtitle={t("vx.rep.sub")} icon={FileBarChart}
        actions={<Button variant="outline" className="h-10 rounded-full" onClick={exportCsv} data-testid="rep-export"><Download size={15} /> {t("vx.export")}</Button>} />
      <RangeBar value={range} onChange={(r) => setParams(r === "30d" ? {} : { range: r })} from={from} to={to}
        onCustom={(f, tt) => setParams({ range: "custom", ...(f ? { from: f } : {}), ...(tt ? { to: tt } : {}) })} />
      {n === 0 && <p className="flex gap-2 rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note" data-testid="rep-no-orders"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.rep.noOrders")}</p>}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="rep-summary">
        {metric("orders", t("vx.an.orders"), n)}
        {metric("value", t("vx.rep.orderValue"), inrP(s.order_value_paise), t("vx.rep.orderValueHint"))}
        {metric("collected", t("vx.rep.collected"), inrP(s.collected_paise), t("vx.rep.collectedHint"))}
        {metric("cod", t("vx.rep.codAwaiting"), inrP(s.cod_awaiting_paise))}
        {metric("net", t("vx.rep.net"), inrP(e.net_paise), t("vx.rep.netHint"))}
        {metric("refunds", t("vx.rep.refunds"), inrP(e.refunds_paise), t("vx.rep.refundsHint", { n: e.refund_count }))}
        {metric("cancelled", t("vx.rep.cancelled"), d.cancellation_return.cancelled_or_rejected)}
        {metric("returned", t("vx.rep.returned"), d.cancellation_return.returned_or_failed)}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SectionCard title={t("vx.dash.byStatus")} testid="rep-status">
          {statusRows.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2">{t("vx.dash.noData")}</p>
            : <div className="space-y-2">{statusRows.map((r) => (
              <div key={r.key} className="hg-tile flex items-center justify-between gap-3 p-3 text-sm" data-testid={`rep-status-${r.key}`}>
                <span className="text-muted2">{r.name}</span><span className="font-semibold tabular-nums text-ink">{r.n}</span>
              </div>))}</div>}
        </SectionCard>

        <SectionCard title={t("vx.dash.bestSellers")} testid="rep-best">
          {d.best_sellers.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2">{t("vx.dash.noData")}</p>
            : <ol className="space-y-2">{d.best_sellers.map((b, i) => <li key={b.product_id} className="hg-tile flex items-center justify-between gap-3 p-3 text-sm"><span className="min-w-0 truncate text-ink">{i + 1}. {b.name}</span><span className="text-xs text-muted2">{t("vx.dash.units", { n: b.quantity })}</span><Money paise={b.value_paise} className="font-semibold text-ink" /></li>)}</ol>}
        </SectionCard>

        <SectionCard title={t("vx.rep.earnTitle")} testid="rep-earnings">
          <p className="mb-3 text-xs text-muted2">{t("vx.rep.earnSub")}</p>
          <div className="space-y-2">
            {row(t("vx.rep.row.sales"), e.sales_paise, "rep-earn-sales")}
            {row(t("vx.rep.row.reversals"), e.reversals_paise, "rep-earn-reversals", true)}
            {row(t("vx.rep.row.refunds"), e.refunds_paise, "rep-earn-refunds", true)}
            {row(t("vx.rep.row.adjustments"), e.adjustments_paise, "rep-earn-adjustments", true)}
            {row(t("vx.rep.row.net"), e.net_paise, "rep-earn-net", true)}
            {row(t("vx.rep.row.settled"), e.settled_paise, "rep-earn-settled")}
          </div>
        </SectionCard>

        <SectionCard title={t("vx.rep.settleTitle")} testid="rep-settlements">
          {Object.keys(st.by_status).length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="rep-settlements-empty">{t("vx.rep.settleNone")}</p>
            : <div className="space-y-2">{SETTLE_STATUSES.filter((k) => st.by_status[k]).map((k) => (
              <div key={k} className="hg-tile flex items-center justify-between gap-3 p-3 text-sm" data-testid={`rep-settle-${k}`}>
                <span className="flex items-center gap-2"><Pill tone={k === "paid" ? "ok" : k === "failed" || k === "rejected" ? "bad" : "warn"}>{t(`vx.rep.st.${k}`)}</Pill><span className="text-muted2">{st.by_status[k].count}</span></span>
                <Money paise={st.by_status[k].amount_paise} className="font-semibold text-ink" />
              </div>))}</div>}
          <p className="mt-3 text-xs text-muted2" data-testid="rep-settle-open">{t("vx.rep.settleOpen", { p: inrP(st.pending_paise), q: inrP(st.in_progress_paise), a: inrP(st.available_paise) })}</p>
        </SectionCard>

        <SectionCard title={t("vx.rep.commTitle")} testid="rep-commission">
          <p className="flex gap-2 text-sm text-muted2" data-testid="rep-commission-none"><Info size={15} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.rep.commNone")}</p>
        </SectionCard>
      </div>

      <SectionCard title={t("vx.rep.prodTitle")} testid="rep-products">
        <p className="mb-3 text-xs text-muted2">{t("vx.rep.prodSub")}</p>
        {d.products.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="rep-products-empty">{t("vx.rep.prodNone")}</p>
          : <ResponsiveTable columns={columns} rows={d.products} rowKey={(p) => p.product_id} caption={t("vx.rep.prodTitle")} testid="rep-products-table" rowTestid={(p) => `rep-product-${p.sku}`} />}
      </SectionCard>
    </div>
  );
}
