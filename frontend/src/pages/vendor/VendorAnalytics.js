import React, { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, Download, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Money, RangeBar, StateBlock, fmtDate, inrP } from "@/components/vendor/kit";

const COLORS = ["#8B3DFF", "#E0A92E", "#D946EF", "#5B7CFF", "#2BB98A"];
const axis = { fontSize: 11, fill: "#9A8FB0" };

function Chart({ title, summary, rows, empty, children, testid }) {
  return (
    <SectionCard title={title} testid={testid}>
      <div role="img" aria-label={summary} className="h-60 w-full">{empty ? <p className="flex h-full items-center justify-center text-sm text-muted2">{empty}</p> : children}</div>
      <table className="sr-only"><caption>{title}</caption><tbody>{rows.map((r, i) => <tr key={i}><th scope="row">{r[0]}</th><td>{r[1]}</td></tr>)}</tbody></table>
    </SectionCard>
  );
}

export default function VendorAnalytics() {
  const { t, lang } = useI18n();
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
    API.get("/vendor/dashboard", { params: { range, date_from: range === "custom" ? from : undefined, date_to: range === "custom" ? to : undefined } })
      .then(({ data }) => { if (id === req.current) setD(data); }).catch((e) => { if (id === req.current) setError(apiError(e)); });
  }, [range, from, to]);
  useEffect(() => { load(); }, [load]);
  if (!d) return <StateBlock loading={!error} error={error} onRetry={load} rows={4} testid="an" />;

  const s = d.sales;
  const n = s.orders;
  const pct = (a) => (n ? `${((a / n) * 100).toFixed(1)}%` : "—");
  const aov = n ? Math.round(s.order_value_paise / n) : 0;
  const trend = d.trend.map((x) => ({ ...x, label: fmtDate(x.date, lang).slice(0, 6) }));
  const status = Object.entries(d.orders_by_status).map(([k, v]) => ({ name: t(`vp.f.${k}`), n: v }));
  const methods = Object.entries(d.orders_by_payment_method).map(([k, v]) => ({ name: k === "cod" ? t("vp.cod") : t("vp.prepaid"), n: v }));
  const cats = d.category_performance.map((c) => ({ ...c, name: t(`vx.pillar.${c.category}`) }));
  const exportCsv = () => {
    const rows = [["date", "orders", "order_value_paise"], ...d.trend.map((x) => [x.date, x.orders, x.value_paise])];
    const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "sales-trend.csv"; a.click();
  };
  const metric = (k, label, value, hint) => <div key={k} className="hg-card p-4" data-testid={`an-${k}`}><div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted2">{label}</div><div className="mt-2 text-2xl font-semibold tabular-nums text-ink">{value}</div>{hint && <div className="mt-1 text-xs text-muted2">{hint}</div>}</div>;

  return (
    <div className="space-y-6" data-testid="vendor-analytics">
      <PageHeader title={t("vx.nav.analytics")} subtitle={t("vx.an.sub")} icon={BarChart3} actions={<Button variant="outline" className="h-10 rounded-full" onClick={exportCsv} data-testid="an-export"><Download size={15} /> {t("vx.export")}</Button>} />
      <RangeBar value={range} onChange={(r) => setParams(r === "30d" ? {} : { range: r })} from={from} to={to} onCustom={(f, tt) => setParams({ range: "custom", ...(f ? { from: f } : {}), ...(tt ? { to: tt } : {}) })} />
      {n > 0 && n < 10 && <p className="flex gap-2 rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note" data-testid="an-small-sample"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.an.smallSample", { n })}</p>}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {metric("orders", t("vx.an.orders"), n)}
        {metric("aov", t("vx.an.aov"), inrP(aov), t("vx.an.aovHint"))}
        {metric("cancel", t("vx.an.cancelRate"), pct(d.cancellation_return.cancelled_or_rejected), t("vx.an.cancelHint"))}
        {metric("return", t("vx.an.returnRate"), pct(d.cancellation_return.returned_or_failed), t("vx.an.returnHint"))}
      </div>
      <Chart title={t("vx.dash.trend")} testid="an-trend" empty={n === 0 ? t("vx.dash.noData") : null} summary={t("vx.dash.trendSummary", { n, v: inrP(s.order_value_paise) })} rows={trend.map((x) => [x.date, `${x.orders} / ${inrP(x.value_paise)}`])}>
        <ResponsiveContainer width="100%" height="100%"><AreaChart data={trend}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="label" tick={axis} interval="preserveStartEnd" /><YAxis tick={axis} width={64} tickFormatter={(v) => `₹${Math.round(v / 100).toLocaleString("en-IN")}`} /><Tooltip formatter={(v) => inrP(v)} /><Area dataKey="value_paise" stroke="#8B3DFF" fill="#8B3DFF33" strokeWidth={2} name={t("vp.k.orderValue")} /></AreaChart></ResponsiveContainer>
      </Chart>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Chart title={t("vx.an.byPillar")} testid="an-pillar" empty={cats.length === 0 ? t("vx.dash.noData") : null} summary={t("vx.an.byPillarSummary", { n: cats.length })} rows={cats.map((c) => [c.name, inrP(c.value_paise)])}>
          <ResponsiveContainer width="100%" height="100%"><BarChart data={cats} layout="vertical" margin={{ left: 8, right: 16 }}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" horizontal={false} /><XAxis type="number" tick={axis} tickFormatter={(v) => `₹${Math.round(v / 100).toLocaleString("en-IN")}`} /><YAxis type="category" dataKey="name" width={120} tick={axis} /><Tooltip formatter={(v) => inrP(v)} /><Bar dataKey="value_paise" maxBarSize={28} fill="#E0A92E" radius={[0, 6, 6, 0]} name={t("vp.k.orderValue")} /></BarChart></ResponsiveContainer>
        </Chart>
        <Chart title={t("vx.an.mix")} testid="an-mix" empty={methods.length === 0 ? t("vx.dash.noData") : null} summary={t("vx.an.mixSummary")} rows={methods.map((m) => [m.name, m.n])}>
          <ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={methods} dataKey="n" nameKey="name" innerRadius={50} outerRadius={80} label>{methods.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>
        </Chart>
        <Chart title={t("vx.dash.byStatus")} testid="an-status" empty={status.length === 0 ? t("vx.dash.noData") : null} summary={t("vx.dash.byStatusSummary", { n })} rows={status.map((r) => [r.name, r.n])}>
          <ResponsiveContainer width="100%" height="100%"><BarChart data={status} layout="vertical" margin={{ left: 8, right: 16 }}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" horizontal={false} /><XAxis type="number" allowDecimals={false} tick={axis} /><YAxis type="category" dataKey="name" width={110} tick={axis} /><Tooltip /><Bar dataKey="n" maxBarSize={28} fill="#8B3DFF" radius={[0, 6, 6, 0]} /></BarChart></ResponsiveContainer>
        </Chart>
        <SectionCard title={t("vx.dash.bestSellers")} testid="an-best">
          {d.best_sellers.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2">{t("vx.dash.noData")}</p> : <ol className="space-y-2">{d.best_sellers.map((b, i) => <li key={b.product_id} className="hg-tile flex items-center justify-between gap-3 p-3 text-sm"><span className="min-w-0 truncate text-ink">{i + 1}. {b.name}</span><span className="text-xs text-muted2">{t("vx.dash.units", { n: b.quantity })}</span><Money paise={b.value_paise} className="font-semibold text-ink" /></li>)}</ol>}
        </SectionCard>
      </div>
      <p className="text-xs text-muted2">{t("vx.dash.definitions")}</p>
    </div>
  );
}
