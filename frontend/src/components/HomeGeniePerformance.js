import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { BarChart3, ListOrdered, Loader2, PiggyBank, TrendingUp } from "lucide-react";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { SectionCard } from "@/components/PageHeader";
import { API, apiError } from "@/lib/api";

const rupees = (p) => `₹${(Number(p || 0) / 100).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
const RANGES = [["7", "7 days"], ["30", "30 days"], ["90", "90 days"]];
const STATE = { awaiting_payment: "Awaiting payment", paid: "Paid", delivered: "Delivered", partially_refunded: "Partly refunded",
  returned: "Returned", cancelled: "Cancelled", refunded: "Refunded" };
const REASON = { not_delivered: "Waiting for delivery", return_window_open: "Return window still open", open_return_or_refund: "Return or refund in progress",
  refund_due: "Refund pending on the order", duplicate_payment_refund_due: "Payment issue being resolved", cancelled: "Order cancelled",
  held_by_finance: "Held by HOME GENIES finance", due_for_release: "Due in the next daily release", order_missing: "Order not found" };
const istDate = (d) => new Date(d.getTime() + 330 * 60000).toISOString().slice(0, 10);

/** Batch 13, Phase 8 (HG-03): the HomeGenie's figures from GET /api/homegenie/metrics and /orders. Nothing is calculated here. */
export function HomeGeniePerformance() {
  const [days, setDays] = useState("30");
  const [d, setD] = useState(null);
  const [orders, setOrders] = useState(null);
  const [page, setPage] = useState(1);
  const range = useCallback(() => {
    const to = new Date();
    return { frm: istDate(new Date(to.getTime() - (Number(days) - 1) * 86400000)), to: istDate(to) };
  }, [days]);
  useEffect(() => {
    setD(null);
    API.get("/homegenie/metrics", { params: range() }).then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e)));
  }, [range]);
  useEffect(() => {
    API.get("/homegenie/orders", { params: { ...range(), page, page_size: 10 } }).then(({ data }) => setOrders(data)).catch(() => {});
  }, [range, page]);

  const m = d?.metrics;
  const cards = m ? [
    ["Attributed orders", m.attributed_orders, `${m.attributed_order_lines} lines`],
    ["Paid orders", m.paid_orders, `${m.delivered_orders} delivered`],
    ["Net sales", rupees(m.net_sales_paise), `${rupees(m.gross_sales_paise)} before refunds`],
    ["Commission earned", rupees(m.commission_earned_paise - m.commission_reversed_paise), `on ${rupees(m.commission_basis_paise)} basis`],
    ["Held", rupees(m.commission_held_paise), "not yet payable"],
    ["Released", rupees(m.commission_released_paise), `${rupees(m.commission_reversed_paise)} reversed`],
  ] : [];
  return (
    <div className="space-y-5" data-testid="hg-performance">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-ink"><BarChart3 size={19} /> Your sales performance</h2>
        <div className="flex gap-2" role="radiogroup" aria-label="Date range">
          {RANGES.map(([k, label]) => <button key={k} role="radio" aria-checked={days === k} onClick={() => { setDays(k); setPage(1); }} data-testid={`hgp-range-${k}`}
            className={`h-9 rounded-full px-4 text-sm font-semibold ${days === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{label}</button>)}
        </div>
      </div>
      {!m ? <Loader2 className="animate-spin text-muted2" /> : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-3" data-testid="hgp-cards">
            {cards.map(([label, v, sub]) => (
              <div key={label} className="hg-card p-4"><div className="text-xs text-muted2">{label}</div>
                <div className="mt-1 font-display text-xl font-semibold tabular-nums text-ink sm:text-2xl">{v}</div><div className="mt-0.5 text-xs text-muted2">{sub}</div></div>
            ))}
          </div>
          <p className="text-xs text-muted2">Days run on Indian time ({d.range.from} to {d.range.to}). Sales count paid orders once each, whatever the number of sellers; refunds are taken off. Commission is shown as the finance records hold it.</p>
          <div className="grid gap-5 lg:grid-cols-3">
            <SectionCard title="Sales and commission by day" icon={TrendingUp} className="min-w-0 lg:col-span-2">
              <div className="h-60 w-full min-w-0">
                <ResponsiveContainer width="100%" height={240} minWidth={0} debounce={1}>
                  <LineChart data={d.trend.map((x) => ({ date: x.date.slice(5), sales: x.sales_paise / 100, commission: x.commission_paise / 100 }))} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(145,133,164,0.25)" vertical={false} />
                    <XAxis dataKey="date" tick={{ fill: "#A08C74", fontSize: 11 }} axisLine={false} tickLine={false} minTickGap={16} />
                    <YAxis tick={{ fill: "#A08C74", fontSize: 11 }} axisLine={false} tickLine={false} width={44} />
                    <Tooltip formatter={(v) => `₹${Number(v).toLocaleString("en-IN")}`} contentStyle={{ background: "rgba(59,36,23,.92)", border: 0, color: "#fff", borderRadius: 12 }} labelStyle={{ color: "#E9D9BC" }} />
                    <Line type="monotone" dataKey="sales" name="Net sales" stroke="#5C3A26" strokeWidth={2.2} dot={false} />
                    <Line type="monotone" dataKey="commission" name="Commission" stroke="#C9A13B" strokeWidth={2.2} dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </SectionCard>
            <SectionCard title="Commission and withdrawals" icon={PiggyBank} className="min-w-0">
              <dl className="space-y-1.5 text-sm">
                {[["Direct", m.commission_by_type.COMMISSION_DIRECT], ["Referral", m.commission_by_type.COMMISSION_REFERRAL], ["Team", m.commission_by_type.COMMISSION_TEAM]].map(([k, v]) => (
                  <div key={k} className="flex justify-between"><dt className="text-muted2">{k}</dt><dd className="tabular-nums">{rupees(v)}</dd></div>))}
                <div className="flex justify-between border-t border-brand-50 pt-1.5"><dt className="text-muted2">Withdrawals paid</dt><dd className="tabular-nums">{rupees(m.withdrawals_paid_paise)} ({m.withdrawals_paid})</dd></div>
                <div className="flex justify-between"><dt className="text-muted2">Withdrawals pending</dt><dd className="tabular-nums">{rupees(m.withdrawals_pending_paise)}</dd></div>
              </dl>
              {d.held_reasons.length > 0 && <div className="mt-3 border-t border-brand-50 pt-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted2">Why commission is held</div>
                <ul className="mt-1.5 space-y-1 text-sm">{d.held_reasons.map((r) => <li key={r.reason} className="flex justify-between gap-2"><span className="text-muted2">{REASON[r.reason] || r.reason} ({r.count})</span><span className="tabular-nums">{rupees(r.amount_paise)}</span></li>)}</ul>
              </div>}
            </SectionCard>
          </div>
        </>
      )}
      <SectionCard title="Orders from your shares" icon={ListOrdered} testid="hgp-orders" className="min-w-0">
        {!orders ? <Loader2 className="animate-spin text-muted2" /> : orders.items.length === 0 ? <p className="text-sm text-muted2">No orders came through your share links in this period yet.</p> : (
          <>
            <ul className="divide-y divide-brand-50">
              {orders.items.map((o) => (
                <li key={o.order_number} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                  <span className="min-w-0"><span className="font-mono font-medium text-ink">{o.order_number}</span> <span className="text-xs text-muted2">· {o.customer || "Customer"} · {(o.created_at || "").slice(0, 10)} · {o.lines} item line(s){o.vendors > 1 ? `, ${o.vendors} sellers` : ""}</span></span>
                  <span className="flex items-center gap-3"><span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-[11px] font-semibold text-ink">{STATE[o.state] || o.state}</span>
                    <span className="tabular-nums">{rupees(o.goods_paise - o.refunded_paise)}</span>
                    {o.commission && <span className="text-xs text-muted2">you: {rupees(o.commission.net_paise)}</span>}</span>
                </li>
              ))}
            </ul>
            {orders.pages > 1 && <div className="mt-3 flex items-center justify-end gap-2 text-sm">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-full px-3 py-1 ring-1 ring-brand-100 disabled:opacity-40">Previous</button>
              <span className="text-muted2">{page} / {orders.pages}</span>
              <button disabled={page >= orders.pages} onClick={() => setPage(page + 1)} className="rounded-full px-3 py-1 ring-1 ring-brand-100 disabled:opacity-40">Next</button></div>}
          </>
        )}
      </SectionCard>
    </div>
  );
}
