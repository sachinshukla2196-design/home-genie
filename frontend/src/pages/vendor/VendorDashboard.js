import React, { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { LayoutDashboard, Inbox, PackageCheck, Truck, AlertTriangle, CheckCircle2, Package, Boxes, Undo2, IndianRupee, Clock, Hourglass, ShieldQuestion, Landmark, ChevronRight, Info } from "lucide-react";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Money, Pill, RangeBar, StateBlock, fmtDate, inrP, inrV } from "@/components/vendor/kit";

export const FULFIL_TONE = {
  new: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30", accepted: "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/30",
  packed: "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/30", dispatched: "bg-[#5B7CFF]/15 text-[#8FA6FF] ring-[#8FA6FF]/30",
  delivered: "bg-hg-success/15 text-hg-success ring-hg-success/30", delivery_failed: "bg-danger/10 text-danger ring-danger/30",
  rejected: "bg-danger/10 text-danger ring-danger/30", cancelled: "bg-danger/10 text-danger ring-danger/30",
  returned_to_origin: "bg-white/10 text-muted2 ring-white/15",
};
export const inr = inrV;   // kept for the other vendor pages

const VIOLET = "#8B3DFF";
const GOLD = "#E0A92E";
const PRIORITY_TONE = { high: "bad", medium: "warn", low: "info" };

function Kpi({ to, icon: Icon, label, value, sub, tone = "violet", testid }) {
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted2">{label}</span>
        <span className="hg-icon-chip !h-8 !w-8 !rounded-lg" aria-hidden><Icon size={15} /></span>
      </div>
      <div className="mt-2 truncate font-display text-2xl font-semibold tabular-nums text-ink">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted2">{sub}</div>}
    </>
  );
  const cls = "hg-card hg-lift block p-4 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet";
  return to ? <Link to={to} className={cls} data-testid={testid} aria-label={`${label}: ${typeof value === "string" ? value : ""}`}>{body}</Link> : <div className={cls} data-testid={testid}>{body}</div>;
}

/** A chart plus a screen-reader table with the same numbers (charts alone are not accessible). */
function ChartCard({ title, summary, rows, children, testid }) {
  return (
    <SectionCard title={title} testid={testid}>
      <div role="img" aria-label={summary} className="h-56 w-full">{children}</div>
      <table className="sr-only"><caption>{title}</caption><tbody>{rows.map((r) => <tr key={r[0]}><th scope="row">{r[0]}</th><td>{r[1]}</td></tr>)}</tbody></table>
    </SectionCard>
  );
}

export default function VendorDashboard() {
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const range = params.get("range") || "month";
  const from = params.get("from") || "";
  const to = params.get("to") || "";
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const req = useRef(0);

  const load = useCallback(() => {
    if (range === "custom" && !(from && to)) return;
    const id = ++req.current;
    setError(null);
    API.get("/vendor/dashboard", { params: { range, date_from: range === "custom" ? from : undefined, date_to: range === "custom" ? to : undefined } })
      .then(({ data }) => { if (id === req.current) setD(data); })
      .catch((e) => { if (id === req.current) setError(apiError(e)); });
  }, [range, from, to]);
  useEffect(() => { load(); }, [load]);

  const setRange = (r) => setParams(r === "month" ? {} : { range: r });
  const setCustom = (f, tt) => setParams({ range: "custom", ...(f ? { from: f } : {}), ...(tt ? { to: tt } : {}) });

  if (!d && !error) return <StateBlock loading rows={4} testid="vd" />;
  if (error && !d) return <StateBlock error={error} onRetry={load} testid="vd" />;

  const s = d.sales;
  const q = d.queue;
  const go = (p) => `/vendor/${p}`;
  const dayLabel = (iso) => fmtDate(iso, lang).slice(0, 6);
  const trend = d.trend.map((x) => ({ ...x, label: dayLabel(x.date) }));
  const statusRows = Object.entries(d.orders_by_status).map(([k, n]) => ({ k, name: t(`vp.f.${k}`), n }));
  const best = d.best_sellers.map((b) => ({ ...b, short: b.name.length > 16 ? `${b.name.slice(0, 15)}…` : b.name }));

  return (
    <div className="space-y-6" data-testid="vendor-dashboard">
      <PageHeader title={t("vp.dashboard")} subtitle={d.vendor.business_name} icon={LayoutDashboard} />
      <RangeBar value={range} onChange={setRange} from={from} to={to} onCustom={setCustom} />
      {error && <StateBlock error={error} onRetry={load} testid="vd-refresh" />}

      {/* ---------------------------------------------------------------- action centre */}
      <SectionCard title={t("vx.dash.actionCentre")} icon={Inbox} testid="action-centre">
        {d.action_centre.length === 0 ? (
          <p className="hg-tile flex items-center gap-2 p-4 text-sm text-muted2" data-testid="action-empty"><CheckCircle2 size={16} className="text-hg-success" aria-hidden /> {t("vx.dash.allClear")}</p>
        ) : (
          <ul className="space-y-2">
            {d.action_centre.map((a) => (
              <li key={a.key}>
                <Link to={a.link} className="hg-tile flex items-center gap-3 p-3 hover:bg-brand-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet" data-testid={`action-${a.key}`}>
                  <Pill tone={PRIORITY_TONE[a.priority]}>{t(`vx.priority.${a.priority}`)}</Pill>
                  <span className="min-w-0 flex-1">
                    <span className="block text-sm font-medium text-ink">{t(`vx.action.${a.key}`, { n: a.count })}</span>
                    <span className="block text-xs text-muted2">{t(`vx.action.${a.key}.why`)}</span>
                  </span>
                  <ChevronRight size={16} className="text-muted2" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {/* ---------------------------------------------------------------- sales by period (order value, live orders only) */}
      <section aria-label={t("vx.dash.salesSection")} className="grid grid-cols-1 gap-3 sm:grid-cols-3" data-testid="sales-periods">
        <Kpi to={go("analytics?range=today")} icon={IndianRupee} label={t("vx.dash.salesToday")} value={inrP(d.sales_periods.today.value_paise)} testid="kpi-sales-today" />
        <Kpi to={go("analytics?range=7d")} icon={IndianRupee} label={t("vx.dash.salesWeek")} value={inrP(d.sales_periods.week.value_paise)} testid="kpi-sales-week" />
        <Kpi to={go("analytics")} icon={IndianRupee} label={t("vx.dash.salesMonth")} value={inrP(d.sales_periods.month.value_paise)} testid="kpi-sales-month" />
      </section>

      {/* ---------------------------------------------------------------- operational KPIs (each opens the matching list) */}
      <section aria-label={t("vx.dash.operations")} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        <Kpi to={go("orders")} icon={Inbox} label={t("vx.dash.today")} value={d.today.orders} testid="kpi-today" />
        <Kpi to={go("orders?status=new")} icon={Inbox} label={t("vx.dash.needAction")} value={q.new} testid="kpi-new" />
        <Kpi to={go("orders?status=accepted")} icon={PackageCheck} label={t("vx.dash.processing")} value={q.to_pack + q.to_dispatch} testid="kpi-processing" />
        <Kpi to={go("orders?status=dispatched")} icon={Truck} label={t("vx.dash.dispatched")} value={q.in_transit} testid="kpi-dispatched" />
        <Kpi to={go("orders?status=delivered")} icon={CheckCircle2} label={t("vx.dash.delivered")} value={q.delivered} testid="kpi-delivered" />
        <Kpi to={go("orders?status=delivery_failed")} icon={AlertTriangle} label={t("vx.dash.exceptions")} value={q.exceptions} testid="kpi-exceptions" />
        <Kpi to={go("returns")} icon={Undo2} label={t("vx.dash.returns")} value={d.returns.requested + d.returns.to_inspect + d.returns.replacements_due} sub={t("vx.dash.returnsSub", { a: d.returns.requested, b: d.returns.to_inspect })} testid="kpi-returns" />
        <Kpi to={go("products?approval=approved")} icon={Package} label={t("vx.dash.active")} value={`${d.products.live} / ${d.products.total}`} testid="kpi-active" />
        <Kpi to={go("products?approval=pending")} icon={Hourglass} label={t("vx.dash.inReview")} value={d.products.pending_review} testid="kpi-review" />
        <Kpi to={go("inventory?stock=low")} icon={Boxes} label={t("vx.dash.low")} value={d.products.low_stock} testid="kpi-low" />
        <Kpi to={go("inventory?stock=out")} icon={Boxes} label={t("vx.dash.out")} value={d.products.out_of_stock} testid="kpi-out" />
        <Kpi to={go("cod")} icon={Clock} label={t("vx.dash.codOverdue")} value={inrP(d.cod.overdue_paise)} testid="kpi-cod-overdue" />
      </section>

      {/* ---------------------------------------------------------------- money: never blended */}
      <SectionCard title={t("vx.dash.money")} icon={IndianRupee} testid="money-section">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Kpi icon={IndianRupee} label={t("vp.k.orderValue")} value={<Money paise={s.order_value_paise} />} sub={t("vp.k.orderValueHint")} testid="vk-order-value" />
          <Kpi icon={CheckCircle2} label={t("vp.k.collected")} value={<Money paise={s.collected_paise} />} sub={t("vx.dash.collectedHint")} testid="vk-collected" />
          <Kpi to={go("cod")} icon={Clock} label={t("vp.k.codWaiting")} value={<Money paise={s.cod_awaiting_paise} />} sub={t("vx.dash.codHint")} testid="vk-cod-waiting" />
          <Kpi icon={ShieldQuestion} label={t("vp.k.awaitConfirm")} value={<Money paise={s.awaiting_confirmation_paise} />} sub={t("vx.dash.upiHint")} testid="vk-awaiting-confirm" />
          <Kpi icon={Hourglass} label={t("vx.dash.underReview")} value={<Money paise={s.under_review_paise} />} sub={t("vx.dash.underReviewHint")} testid="vk-under-review" />
          <Kpi to={go("finance")} icon={Landmark} label={t("vx.dash.pendingSettlement")} value={<Money paise={d.finance.pending_settlement_paise} />}
            sub={d.finance.policy_active ? t("vx.dash.settledSub", { v: inrP(d.finance.settled_paise) }) : t("vx.dash.policyPending")} testid="vk-pending-settlement" />
        </div>
        <p className="mt-3 flex items-start gap-2 text-xs text-muted2"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.dash.definitions")}</p>
      </SectionCard>

      {/* ---------------------------------------------------------------- charts (real data only) */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ChartCard title={t("vx.dash.trend")} testid="chart-trend" summary={t("vx.dash.trendSummary", { n: s.orders, v: inrP(s.order_value_paise) })}
          rows={trend.map((x) => [x.date, `${x.orders} / ${inrP(x.value_paise)}`])}>
          {s.orders === 0 ? <p className="flex h-full items-center justify-center text-sm text-muted2" data-testid="trend-empty">{t("vx.dash.noData")}</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={trend} margin={{ left: 0, right: 8, top: 8, bottom: 0 }}>
                <defs><linearGradient id="gv" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={VIOLET} stopOpacity={0.5} /><stop offset="100%" stopColor={VIOLET} stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
                <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#9A8FB0" }} interval="preserveStartEnd" />
                <YAxis tick={{ fontSize: 11, fill: "#9A8FB0" }} tickFormatter={(v) => `₹${Math.round(v / 100).toLocaleString("en-IN")}`} width={64} />
                <Tooltip formatter={(v) => inrP(v)} labelStyle={{ color: "#111" }} />
                <Area type="monotone" dataKey="value_paise" stroke={VIOLET} fill="url(#gv)" strokeWidth={2} name={t("vp.k.orderValue")} />
              </AreaChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
        <ChartCard title={t("vx.dash.byStatus")} testid="chart-status" summary={t("vx.dash.byStatusSummary", { n: statusRows.reduce((a, r) => a + r.n, 0) })} rows={statusRows.map((r) => [r.name, r.n])}>
          {statusRows.length === 0 ? <p className="flex h-full items-center justify-center text-sm text-muted2">{t("vx.dash.noData")}</p> : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusRows} layout="vertical" margin={{ left: 8, right: 16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: "#9A8FB0" }} />
                <YAxis type="category" dataKey="name" width={110} tick={{ fontSize: 11, fill: "#9A8FB0" }} />
                <Tooltip />
                <Bar dataKey="n" maxBarSize={28} fill={GOLD} radius={[0, 6, 6, 0]} name={t("vp.orders")} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </ChartCard>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SectionCard title={t("vx.dash.bestSellers")} icon={Package} testid="best-sellers">
          {best.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="best-empty">{t("vx.dash.noData")}</p> : (
            <ol className="space-y-2">
              {best.map((b, i) => (
                <li key={b.product_id} className="hg-tile flex items-center gap-3 p-3" data-testid={`best-${i}`}>
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-hg-violet/20 text-xs font-bold text-hg-lavender" aria-hidden>{i + 1}</span>
                  <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-ink">{b.name}</span>
                    <span className="block text-xs text-muted2">{b.sku} · {t("vx.dash.units", { n: b.quantity })}{b.category ? ` · ${t(`vx.pillar.${b.category}`)}` : ""}</span></span>
                  <Money paise={b.value_paise} className="text-sm font-semibold text-ink" />
                </li>
              ))}
            </ol>
          )}
        </SectionCard>
        <SectionCard title={t("vx.dash.inventoryAlerts")} icon={Boxes} action={<Link to="/vendor/inventory" className="text-sm font-medium text-hg-lavender">{t("cta.viewAll")}</Link>} testid="inventory-alerts">
          {d.inventory_alerts.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="alerts-empty">{t("vx.dash.stockHealthy")}</p> : (
            <ul className="space-y-2">
              {d.inventory_alerts.map((a) => (
                <li key={a.id} className="hg-tile flex items-center justify-between gap-3 p-3">
                  <span className="min-w-0"><span className="block truncate text-sm font-medium text-ink">{a.name}</span><span className="block text-xs text-muted2">{a.sku}</span></span>
                  <Pill tone={a.stock <= 0 ? "bad" : "warn"}>{a.stock <= 0 ? t("vx.inv.out") : t("vx.inv.leftN", { n: a.stock })}</Pill>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>
      </div>

      <SectionCard title={t("vp.recent")} icon={Inbox} action={<Link to="/vendor/orders" className="text-sm font-medium text-hg-lavender">{t("cta.viewAll")}</Link>} testid="recent-orders">
        {d.recent.length === 0 ? <p className="hg-tile p-6 text-center text-sm text-muted2" data-testid="recent-empty">{t("vp.noOrders")}</p> : (
          <ul className="space-y-2">
            {d.recent.map((o) => (
              <li key={o.id}>
                <button onClick={() => navigate(`/vendor/orders?open=${o.id}`)} className="hg-tile flex w-full items-center justify-between gap-3 p-3 text-left hover:bg-brand-50/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet" data-testid={`recent-${o.order_number}`}>
                  <span className="min-w-0"><span className="block font-medium text-ink">{o.order_number}</span><span className="block truncate text-xs text-muted2">{o.items.map((li) => `${li.name} ×${li.quantity}`).join(", ")}</span></span>
                  <span className="flex shrink-0 items-center gap-3"><Money paise={o.items_total_paise} className="hidden font-semibold text-ink sm:inline" />
                    <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${FULFIL_TONE[o.fulfilment.status]}`}>{t(`vp.f.${o.fulfilment.status}`)}</span></span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}
