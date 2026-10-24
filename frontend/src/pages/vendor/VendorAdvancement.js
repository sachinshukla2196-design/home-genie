import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ArrowRight, Info, TrendingUp } from "lucide-react";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { Chart } from "@/pages/vendor/VendorAnalytics";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Money, Pill, RangeBar, StateBlock, fmtDate, inrP } from "@/components/vendor/kit";

const axis = { fontSize: 11, fill: "#9A8FB0" };
const query = (range, from, to) => ({ range, date_from: range === "custom" ? from : undefined, date_to: range === "custom" ? to : undefined });
const pctOrDash = (v) => (v === null || v === undefined ? "—" : `${v}%`);

/** Growth figure with its direction shown as text as well as colour. */
function Change({ pct, t }) {
  if (pct === null || pct === undefined) return <span className="text-xs text-muted2">{t("vx.adv.noBaseline")}</span>;
  return <span className={`text-xs font-medium ${pct >= 0 ? "text-hg-success" : "text-danger"}`}>{pct >= 0 ? t("vx.adv.up", { pct }) : t("vx.adv.down", { pct: Math.abs(pct) })}</span>;
}

export default function VendorAdvancement() {
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
    API.get("/vendor/reports/advancement", { params: query(range, from, to) })
      .then(({ data }) => { if (id === req.current) setD(data); }).catch((e) => { if (id === req.current) setError(apiError(e)); });
  }, [range, from, to]);
  useEffect(() => { load(); }, [load]);

  if (!d) return <StateBlock loading={!error} error={error} onRetry={load} rows={4} testid="adv" />;

  const g = d.growth, k = d.kpis, n = k.orders, rep = d.repeat_customers, stock = d.stock;
  const trend = d.trend.map((x) => ({ ...x, label: fmtDate(x.date, lang).slice(0, 6) }));
  const hasTrend = d.trend.some((x) => x.orders > 0);
  const progress = g.target_order_value_paise > 0 ? Math.round((g.order_value_paise.current / g.target_order_value_paise) * 100) : null;
  const suggestions = d.suggestions.map((s) => ({ ...s, params: { ...s.params, ...(s.params.change !== undefined ? { change: Math.abs(s.params.change) } : {}) } }));

  const kpi = (key, label, value, hint) => (
    <div key={key} className="hg-card p-4" data-testid={`adv-${key}`}>
      <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted2">{label}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-ink">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted2">{hint}</div>}
    </div>
  );

  return (
    <div className="space-y-6" data-testid="vendor-advancement">
      <PageHeader title={t("vx.nav.advancement")} subtitle={t("vx.adv.sub")} icon={TrendingUp} />
      <RangeBar value={range} onChange={(r) => setParams(r === "30d" ? {} : { range: r })} from={from} to={to}
        onCustom={(f, tt) => setParams({ range: "custom", ...(f ? { from: f } : {}), ...(tt ? { to: tt } : {}) })} />
      <p className="flex gap-2 rounded-xl bg-white/5 p-3 text-xs text-muted2 ring-1 ring-white/10"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.adv.note")}</p>
      {k.small_sample && n > 0 && <p className="flex gap-2 rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note" data-testid="adv-small-sample"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.an.smallSample", { n })}</p>}

      <SectionCard title={t("vx.adv.growth")} testid="adv-growth">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="hg-tile p-4" data-testid="adv-growth-value">
            <div className="text-xs text-muted2">{t("vx.rep.orderValue")}</div>
            <Money paise={g.order_value_paise.current} className="mt-1 block text-2xl font-semibold text-ink" />
            <div className="mt-1"><Change pct={g.order_value_paise.change_pct} t={t} /></div>
          </div>
          <div className="hg-tile p-4" data-testid="adv-growth-orders">
            <div className="text-xs text-muted2">{t("vx.an.orders")}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-ink">{g.orders.current}</div>
            <div className="mt-1"><Change pct={g.orders.change_pct} t={t} /></div>
          </div>
        </div>
        <div className="mt-4" data-testid="adv-target">
          {progress === null ? <p className="text-sm text-muted2">{t("vx.adv.targetNone")}</p> : (
            <>
              <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                <span className="text-ink">{t("vx.adv.target", { v: inrP(g.target_order_value_paise) })}</span>
                <span className="text-xs text-muted2">{t("vx.adv.targetHint", { pct: g.target_pct, p: progress })}</span>
              </div>
              <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-white/10" role="progressbar" aria-label={t("vx.adv.target", { v: inrP(g.target_order_value_paise) })}
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(progress, 100)}>
                <div className="h-full rounded-full bg-hg-violet" style={{ width: `${Math.min(progress, 100)}%` }} />
              </div>
            </>
          )}
        </div>
      </SectionCard>

      <Chart title={t("vx.dash.trend")} testid="adv-trend" empty={hasTrend ? null : t("vx.dash.noData")} summary={t("vx.dash.trendSummary", { n, v: inrP(g.order_value_paise.current) })}
        rows={trend.map((x) => [x.date, `${x.orders} / ${inrP(x.value_paise)}`])}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={trend}><CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" /><XAxis dataKey="label" tick={axis} interval="preserveStartEnd" />
            <YAxis tick={axis} width={64} tickFormatter={(v) => `₹${Math.round(v / 100).toLocaleString("en-IN")}`} /><Tooltip formatter={(v) => inrP(v)} />
            <Area dataKey="value_paise" stroke="#8B3DFF" fill="#8B3DFF33" strokeWidth={2} name={t("vp.k.orderValue")} /></AreaChart>
        </ResponsiveContainer>
      </Chart>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SectionCard title={t("vx.adv.kpis")} testid="adv-kpis">
          <div className="grid gap-3 sm:grid-cols-2">
            {kpi("cancel", t("vx.an.cancelRate"), pctOrDash(k.cancellation_rate), t("vx.an.cancelHint"))}
            {kpi("return", t("vx.an.returnRate"), pctOrDash(k.return_rate), t("vx.an.returnHint"))}
            {kpi("delivered", t("vx.adv.delivered"), pctOrDash(k.delivered_rate), t("vx.adv.deliveredHint"))}
            {kpi("aov", t("vx.an.aov"), k.average_order_value_paise === null ? "—" : inrP(k.average_order_value_paise), t("vx.an.aovHint"))}
            {kpi("rating", t("vx.adv.rating"), "—", t("vx.adv.ratingNone"))}
            {kpi("repeat", t("vx.adv.repeat"), pctOrDash(rep.repeat_rate), rep.buyers ? t("vx.adv.repeatHint", { n: rep.repeat, buyers: rep.buyers }) : t("vx.adv.repeatNone"))}
          </div>
        </SectionCard>

        <SectionCard title={t("vx.adv.stock")} testid="adv-stock">
          {stock.items.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="adv-stock-empty">{t("vx.adv.stockOk")}</p>
            : <ul className="space-y-2">{stock.items.map((p) => (
              <li key={p.id} className="hg-tile flex items-center justify-between gap-3 p-3 text-sm" data-testid={`adv-stock-${p.sku}`}>
                <span className="min-w-0 truncate text-ink">{p.name}</span>
                <span className="flex shrink-0 items-center gap-2"><span className="text-xs text-muted2">{p.stock}</span>
                  {p.stock <= 0 ? <Pill tone="bad">{t("vx.rep.stock.out")}</Pill> : <Pill tone="warn">{t("vx.rep.stock.low")}</Pill>}</span>
              </li>))}</ul>}
        </SectionCard>
      </div>

      <SectionCard title={t("vx.adv.suggest")} testid="adv-suggest">
        {suggestions.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="adv-suggest-empty">{t("vx.adv.suggestNone")}</p>
          : <ul className="space-y-2">{suggestions.map((s) => (
            <li key={s.key} className="hg-tile flex flex-wrap items-center justify-between gap-3 p-3 text-sm" data-testid={`adv-suggestion-${s.key}`}>
              <span className="min-w-0 text-ink">{t(`vx.adv.s.${s.key}`, s.params)}</span>
              <Link to={s.link} className="inline-flex shrink-0 items-center gap-1 text-hg-lavender underline">{t("vx.adv.open")} <ArrowRight size={14} aria-hidden /></Link>
            </li>))}</ul>}
      </SectionCard>
    </div>
  );
}
