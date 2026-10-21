import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Coins, Package, ShoppingBag, Share2, LifeBuoy, User, ArrowRight,
  Sparkles, CheckCircle2, Users, Info, TrendingUp,
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
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [d, setD] = useState(null);

  useEffect(() => { API.get("/dashboard").then(({ data }) => setD(data)).catch(() => {}); }, []);

  const sym = d?.settings?.currency_symbol || "₹";
  const money = (v) => `${sym}${Number(v || 0).toLocaleString("en-IN")}`;
  const approved = user?.status === "green";

  const quick = [
    { key: "qa.shop", icon: ShoppingBag, to: "/app/products" },
    { key: "qa.share", icon: Share2, to: "/app/referral" },
    { key: "qa.orders", icon: Package, to: "/app/orders" },
    { key: "qa.wallet", icon: Coins, to: "/app/wallet" },
    { key: "qa.profile", icon: User, to: "/app/profile" },
    { key: "qa.support", icon: LifeBuoy, to: "/legal/support" },
  ];

  if (!d) return (
    <div className="space-y-6">
      <Skeleton className="h-28 w-full rounded-xl" />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-28 rounded-xl" />)}</div>
    </div>
  );

  return (
    <div className="space-y-6" data-testid="homegenie-dashboard">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-display text-2xl font-semibold text-ink">{t("dash.greeting")}, {user?.full_name?.split(" ")[0]}</h1>
          <div className="mt-1 flex items-center gap-2 text-sm text-muted2">
            <span className="font-semibold text-forest" data-testid="dash-member-id">{user?.distributor_id}</span>
          </div>
        </div>
      </div>

      {/* Approval status */}
      {!approved ? (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
          className="relative overflow-hidden rounded-2xl hg-royal p-6 text-white sm:p-8" data-testid="pending-banner">
          <div className="relative flex flex-wrap items-center justify-between gap-4">
            <div>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-gold/20 px-2.5 py-1 text-xs font-semibold text-gold"><Sparkles size={12} /> {t("status.red")}</span>
              <h2 className="mt-3 font-display text-xl font-medium sm:text-2xl">{t("dash.pendingBanner")}</h2>
              <p className="mt-1 max-w-xl text-white/75">{t("dash.pendingBannerSub")}</p>
            </div>
            <Button onClick={() => navigate("/app/products")} className="btn-gold rounded-full px-6" data-testid="shop-now-btn">
              {t("cta.shopNow")} <ArrowRight size={16} className="ml-1.5" />
            </Button>
          </div>
        </motion.div>
      ) : (
        <div className="flex items-center gap-3 rounded-2xl border border-brand-50 bg-brand-50/50 p-4 text-forest" data-testid="active-banner">
          <CheckCircle2 size={22} /> <span className="font-medium">{t("dash.activeMsg")}</span>
        </div>
      )}

      {/* Sales & order overview — real account data only */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard testid="stat-orders" icon={Package} accent="brand" label={t("dash.totalOrders")} value={d.stats.total_orders} index={0} />
        <StatCard testid="stat-customers" icon={Users} accent="gold" label={t("dash.referralCount")} value={d.stats.referral_count} index={1} />
        <StatCard testid="stat-points-available" icon={Coins} accent="brand" label={t("wallet.available")} value={money(d.wallet.available_balance)} sub={`${t("wallet.pending")}: ${money(d.wallet.pending_balance)}`} index={2} />
        <StatCard testid="stat-points-released" icon={TrendingUp} accent="ink" label={t("wallet.withdrawn")} value={money(d.wallet.total_withdrawn)} index={3} />
      </div>

      {/* Commission & team sales — explicitly pending */}
      <div className="rounded-2xl border border-dashed border-brand-50 bg-brand-50/30 p-5" data-testid="commission-pending-card">
        <div className="flex items-start gap-3">
          <Info size={18} className="mt-0.5 shrink-0 text-brand" />
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="font-display text-base font-semibold text-ink">{t("dash.commissionTitle")}</h3>
              <span className="rounded-full bg-gold-light px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-ink" data-testid="commission-pending-badge">
                {t("common.pendingConfig")}
              </span>
            </div>
            <p className="mt-1.5 text-sm text-muted2">{t("dash.commissionPending")}</p>
          </div>
        </div>
      </div>

      {/* Points note */}
      <div className="rounded-2xl border border-brand-50 bg-white p-5 shadow-card" data-testid="points-card">
        <h3 className="font-display text-base font-semibold text-ink">{t("dash.pointsTitle")}</h3>
        <p className="mt-1.5 text-sm text-muted2">{t("dash.pointsNote")}</p>
        <p className="mt-2 text-xs font-medium text-brand-700">{t("wallet.rate")}</p>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Sales chart */}
        <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card lg:col-span-2">
          <h3 className="font-display text-lg font-medium text-ink">{t("dash.salesOverview")}</h3>
          <div className="mt-4 h-64 w-full">
            <ResponsiveContainer width="100%" height={256} minWidth={0} debounce={1}>
              <LineChart data={d.income_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="#EDE4FF" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#6B6475", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#6B6475", fontSize: 12 }} axisLine={false} tickLine={false} width={30} />
                <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid #EDE4FF" }} formatter={(v) => money(v)} />
                <Line type="monotone" dataKey="income" stroke="#6D28D9" strokeWidth={2.5} dot={{ r: 3, fill: "#C9A227" }} />
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
                  className="flex flex-col items-center gap-2 rounded-xl border border-brand-50 p-3 text-center text-xs font-medium text-forest hover:-translate-y-0.5 hover:bg-brand-50 transition-all">
                  <Icon size={20} className="text-brand" /><span>{t(q.key)}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {/* Recent orders + point activity */}
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
          {d.recent_transactions.length === 0 ? <EmptyState icon={Coins} title={t("empty.wallet")} testid="empty-txns" /> : (
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
