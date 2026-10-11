import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Wallet, TrendingUp, Package, Users, ShoppingBag, Share2, ShieldCheck, LifeBuoy,
  ArrowRight, Sparkles, CheckCircle2, PieChart,
} from "lucide-react";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { StatCard } from "@/components/StatCard";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

export default function Dashboard() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [d, setD] = useState(null);

  useEffect(() => { API.get("/dashboard").then(({ data }) => setD(data)).catch(() => {}); }, []);

  const sym = d?.settings?.currency_symbol || "₹";
  const money = (v) => `${sym}${Number(v || 0).toLocaleString("en-IN")}`;
  const isGreen = user?.status === "green";

  const quick = [
    { key: "qa.shop", icon: ShoppingBag, to: "/app/products" },
    { key: "qa.share", icon: Share2, to: "/app/referral" },
    { key: "qa.orders", icon: Package, to: "/app/orders" },
    { key: "qa.wallet", icon: Wallet, to: "/app/wallet" },
    { key: "qa.team", icon: Users, to: "/app/team" },
    { key: "qa.kyc", icon: ShieldCheck, to: "/app/kyc" },
  ];

  if (!d) return (
    <div className="space-y-6">
      <Skeleton className="h-28 w-full rounded-xl" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}</div>
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink">{t("dash.greeting")}, {user?.full_name?.split(" ")[0]}</h1>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted2">
            <span className="font-semibold text-forest">{user?.distributor_id}</span>
          </div>
        </div>
      </div>

      {/* Activation banner / active msg */}
      {!isGreen ? (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          className="relative overflow-hidden rounded-2xl bg-forest p-6 text-white sm:p-8" data-testid="activation-banner">
          <div className="absolute right-0 top-0 h-40 w-40 -translate-y-10 translate-x-10 rounded-full bg-gold/20 blur-2xl" />
          <div className="relative flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-gold/20 px-2.5 py-1 text-xs font-semibold text-gold"><Sparkles size={12} /> {t("status.red")}</span>
              <h2 className="mt-3 font-display text-xl font-medium sm:text-2xl">{t("dash.activateBanner")}</h2>
              <p className="mt-1 text-white/70">{t("dash.activateBannerSub")} <b className="text-gold">{money(d.settings.activation_amount)}</b></p>
            </div>
            <Button onClick={() => navigate("/app/products")} className="rounded-full bg-gold px-6 text-forest hover:bg-gold/90" data-testid="activate-now-btn">
              {t("cta.activateNow")} <ArrowRight size={16} className="ml-1.5" />
            </Button>
          </div>
        </motion.div>
      ) : (
        <div className="flex items-center gap-3 rounded-2xl border border-brand-50 bg-brand-50/50 p-4 text-forest" data-testid="active-banner">
          <CheckCircle2 size={22} /> <span className="font-medium">{t("dash.activeMsg")}</span>
        </div>
      )}

      {/* Rank / BV progress */}
      {d.rank && (
        <div className="rounded-2xl border border-brand-50 bg-white p-5 shadow-card" data-testid="rank-progress">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wide text-muted2">{t("dash.currentRank")}</div>
              <div className="font-display text-lg font-semibold text-forest" data-testid="rank-current">{d.rank.current}</div>
            </div>
            <div className="text-right">
              <div className="text-xs uppercase tracking-wide text-muted2">{d.rank.is_max ? t("dash.topRank") : t("dash.nextRank")}</div>
              <div className="font-display text-lg font-semibold text-gold" data-testid="rank-next">{d.rank.is_max ? "★" : d.rank.next}</div>
            </div>
          </div>
          <div className="mt-3 h-2.5 w-full overflow-hidden rounded-full bg-brand-50">
            <motion.div initial={{ width: 0 }} animate={{ width: `${d.rank.progress}%` }} transition={{ duration: 0.7 }} className="h-full rounded-full bg-forest" data-testid="rank-bar" />
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-muted2">
            <span data-testid="rank-bv">BV {Number(d.rank.current_bv).toLocaleString("en-IN")}{!d.rank.is_max && ` / ${Number(d.rank.next_bv).toLocaleString("en-IN")}`}</span>
            <span className="font-semibold text-forest">{d.rank.progress}%</span>
          </div>
        </div>
      )}

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard testid="stat-wallet" icon={Wallet} accent="brand" label={t("dash.walletBalance")} value={money(d.wallet.available_balance)} sub={`${t("wallet.pending")}: ${money(d.wallet.pending_balance)}`} index={0} />
        <StatCard testid="stat-total-income" icon={TrendingUp} accent="gold" label={t("dash.totalIncome")} value={money(d.stats.total_income)} index={1} />
        <StatCard testid="stat-today-income" icon={Sparkles} accent="brand" label={t("dash.todayIncome")} value={money(d.stats.today_income)} index={2} />
        <StatCard testid="stat-orders" icon={Package} accent="ink" label={t("dash.totalOrders")} value={d.stats.total_orders} index={3} />
        <StatCard testid="stat-referrals" icon={Share2} accent="brand" label={t("dash.referralCount")} value={d.stats.referral_count} index={4} />
        <StatCard testid="stat-team" icon={Users} accent="gold" label={t("dash.activeTeam")} value={d.stats.active_team} index={5} />
        <StatCard testid="stat-withdrawn" icon={Wallet} accent="ink" label={t("wallet.withdrawn")} value={money(d.wallet.total_withdrawn)} index={6} />
        <StatCard testid="stat-rank" icon={TrendingUp} accent="gold" label={t("dash.rank")} value={d.rank?.current || "—"} sub={d.rank ? (d.rank.is_max ? t("dash.topRank") : `${t("dash.nextRank")}: ${d.rank.next}`) : t("dash.rankSoon")} index={7} />
      </div>

      {/* Income breakdown by source */}
      {d.income_breakdown && (
        <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="income-breakdown">
          <div className="flex items-center gap-2">
            <PieChart size={18} className="text-brand" />
            <h3 className="font-display text-lg font-medium text-ink">{t("dash.incomeBreakdown")}</h3>
          </div>
          <p className="mt-1 text-sm text-muted2">{t("dash.incomeBreakdownSub")}</p>
          {(() => {
            const total = d.income_breakdown.reduce((s, x) => s + (x.amount || 0), 0);
            const colors = { matrix: "#176B43", team: "#2E9E63", repurchase: "#C9A227", pool: "#66736B" };
            if (total <= 0) return <EmptyState icon={PieChart} title={t("empty.income")} testid="empty-breakdown" />;
            return (
              <div className="mt-4 space-y-3.5">
                {d.income_breakdown.map((b) => {
                  const pct = Math.round(((b.amount || 0) / total) * 100);
                  return (
                    <div key={b.key} data-testid={`income-bd-${b.key}`}>
                      <div className="flex items-center justify-between text-sm">
                        <span className="font-medium text-ink">{b.label}</span>
                        <span className="font-display font-semibold text-forest" data-testid={`income-bd-${b.key}-amount`}>
                          {money(b.amount)} <span className="text-xs font-normal text-muted2">({pct}%)</span>
                        </span>
                      </div>
                      <div className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-brand-50">
                        <motion.div initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.6 }}
                          className="h-full rounded-full" style={{ background: colors[b.key] }} />
                      </div>
                    </div>
                  );
                })}
                <div className="flex items-center justify-between border-t border-brand-50 pt-3 text-sm">
                  <span className="font-semibold text-ink">{t("dash.totalIncome")}</span>
                  <span className="font-display font-semibold text-forest" data-testid="income-bd-total">{money(total)}</span>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Income chart */}
        <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card lg:col-span-2">
          <h3 className="font-display text-lg font-medium text-ink">{t("dash.incomeOverview")}</h3>
          <div className="mt-4 h-64 w-full">
            <ResponsiveContainer width="100%" height={256} minWidth={0} debounce={1}>
              <LineChart data={d.income_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#EAF5ED" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#66736B", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#66736B", fontSize: 12 }} axisLine={false} tickLine={false} width={30} />
                <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #EAF5ED" }} formatter={(v) => money(v)} />
                <Line type="monotone" dataKey="income" stroke="#176B43" strokeWidth={2.5} dot={{ r: 3, fill: "#C9A227" }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Quick actions */}
        <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
          <h3 className="font-display text-lg font-medium text-ink">{t("dash.quickActions")}</h3>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {quick.map((q) => {
              const Icon = q.icon;
              return (
                <button key={q.key} onClick={() => navigate(q.to)} data-testid={`qa-${q.key.split(".")[1]}`}
                  className="flex flex-col items-center gap-2 rounded-xl border border-brand-50 p-3 text-center text-xs font-medium text-forest hover:bg-brand-50 hover:-translate-y-0.5 transition-all">
                  <Icon size={20} className="text-brand" /><span>{t(q.key)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Recent orders + transactions */}
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-display text-lg font-medium text-ink">{t("dash.recentOrders")}</h3>
            <button onClick={() => navigate("/app/orders")} className="text-sm font-medium text-brand hover:underline">{t("cta.viewAll")}</button>
          </div>
          {d.recent_orders.length === 0 ? <EmptyState icon={Package} title={t("empty.orders")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="empty-orders" /> : (
            <div className="space-y-3">
              {d.recent_orders.map((o) => (
                <div key={o.id} className="flex items-center justify-between rounded-lg border border-brand-50 p-3">
                  <div><div className="font-medium text-ink">{o.order_number}</div><div className="text-xs text-muted2">{o.status}</div></div>
                  <div className="font-display font-semibold text-forest">{money(o.total)}</div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <h3 className="font-display text-lg font-medium text-ink">{t("dash.recentTxns")}</h3>
            <button onClick={() => navigate("/app/wallet")} className="text-sm font-medium text-brand hover:underline">{t("cta.viewAll")}</button>
          </div>
          {d.recent_transactions.length === 0 ? <EmptyState icon={Wallet} title={t("empty.income")} testid="empty-txns" /> : (
            <div className="space-y-3">
              {d.recent_transactions.map((tx) => (
                <div key={tx.id} className="flex items-center justify-between rounded-lg border border-brand-50 p-3">
                  <div><div className="font-medium text-ink">{tx.type.replace(/_/g, " ")}</div><div className="text-xs text-muted2">{(tx.created_at || "").slice(0, 10)}</div></div>
                  <div className={`font-display font-semibold ${tx.direction === "credit" ? "text-brand" : "text-danger"}`}>{tx.direction === "credit" ? "+" : "-"}{money(tx.amount)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
