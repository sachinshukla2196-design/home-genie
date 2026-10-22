import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  Coins, Package, ShoppingBag, Share2, LifeBuoy, User, ArrowRight,
  Sparkles, CheckCircle2, Users, TrendingUp, Trophy, ChevronRight,
  ArrowUpRight, ArrowDownRight,
} from "lucide-react";
import { LineChart, Line, ResponsiveContainer, XAxis, YAxis, Tooltip, CartesianGrid } from "recharts";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";
import { Stagger, StaggerItem, CountUp, ProgressBar, pressable } from "@/components/motion";
import { SectionCard } from "@/components/PageHeader";

export default function Dashboard() {
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  const [featured, setFeatured] = useState([]);

  useEffect(() => {
    API.get("/dashboard").then(({ data }) => setD(data)).catch(() => {});
    API.get("/products").then(({ data }) => setFeatured((data || []).slice(0, 8))).catch(() => {});
  }, []);

  const sym = d?.settings?.currency_symbol || "₹";
  const money = (v) => `${sym}${Number(v || 0).toLocaleString("en-IN")}`;
  const pts = (v) => `${Number(v || 0).toLocaleString("en-IN")} pts`;
  const approved = user?.status === "green";

  const quick = [
    { key: "qa.shop", icon: ShoppingBag, to: "/app/products" },
    { key: "qa.share", icon: Share2, to: "/app/referral" },
    { key: "qa.orders", icon: Package, to: "/app/orders" },
    { key: "qa.wallet", icon: Coins, to: "/app/wallet" },
    { key: "nav.withdrawals", icon: Coins, to: "/app/withdrawals" },
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
    <div className="space-y-5" data-testid="homegenie-dashboard">
      <div className="hidden flex-wrap items-center justify-between gap-3 lg:flex">
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
          className="relative overflow-hidden rounded-3xl hg-violet p-6 sm:p-8" data-testid="pending-banner">
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
        <div className="hg-card flex items-center gap-3 p-4 text-forest" data-testid="active-banner">
          <CheckCircle2 size={22} /> <span className="font-medium">{t("dash.activeMsg")}</span>
        </div>
      )}

      {/* Points hero (app style) */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
        className="hg-hero hg-sheen relative overflow-hidden rounded-3xl p-6 sm:p-7" data-testid="points-hero">
        <span className="hg-orb -right-10 -top-12 h-40 w-40 bg-hg-pink/30" />
        <span className="hg-orb -bottom-16 -left-10 h-40 w-40 bg-hg-violet/40" />
        <div className="flex items-start justify-between gap-3">
          <div className="text-sm font-medium uppercase tracking-wider text-white/80">{t("wallet.available")}</div>
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-white/30 bg-white/15 px-3.5 py-1.5 text-sm font-semibold" data-testid={d.badge?.badge ? "badge-earned" : "badge-none"}>
            <Trophy size={15} /> {d.badge?.badge || t("badge.none")}
          </span>
        </div>
        <div className="mt-1 font-display text-5xl font-bold tabular-nums" data-testid="stat-points-available"><CountUp value={d.wallet.available_balance} /></div>
        <div className="mt-1 text-sm text-white/85">{t("wallet.pending")}: {pts(d.wallet.pending_balance)}</div>
        <button onClick={() => navigate("/app/rewards")} className="group mt-5 block w-full text-left" data-testid="badge-card">
          <div className="flex items-center justify-between gap-3 text-sm text-white/90">
            <span>{t("badge.sales")}</span>
            <span className="whitespace-nowrap font-semibold" data-testid="badge-sales">{money(d.badge?.sales_value)}{d.badge?.next_target ? ` / ${money(d.badge.next_target)}` : ""}</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <div className="flex-1"><ProgressBar pct={d.badge?.progress_pct || 0} trackClassName="bg-white/20" testid="badge-progress" /></div>
            <ChevronRight size={20} className="text-white/80 transition-transform duration-300 group-hover:translate-x-1" />
          </div>
          {d.badge?.next_badge && <div className="mt-2 text-sm font-medium text-hg-gold" data-testid="badge-next">{money(d.badge.remaining)} {t("badge.toGo")} · {d.badge.next_badge}</div>}
        </button>
      </motion.div>

      {/* Quick stat tiles */}
      <Stagger className="grid grid-cols-3 gap-3 sm:gap-4">
        {[
          { icon: Package, v: d.stats.total_orders, k: "dash.totalOrders", c: "text-hg-lavender", bg: "bg-hg-lavender/15", id: "stat-orders" },
          { icon: TrendingUp, v: d.stats.sales_count ?? 0, k: "dash.mySales", c: "text-hg-pink", bg: "bg-hg-pink/15", id: "stat-sales" },
          { icon: Users, v: d.stats.referral_count, k: "dash.referralCount", c: "text-hg-success", bg: "bg-hg-success/15", id: "stat-customers" },
        ].map((x) => (
          <StaggerItem key={x.id} {...pressable} className="hg-card hg-lift flex flex-col items-center px-2 py-5 text-center" data-testid={x.id}>
            <span className={`flex h-11 w-11 items-center justify-center rounded-2xl ${x.bg}`}><x.icon size={22} className={x.c} /></span>
            <div className="mt-2.5 font-display text-3xl font-semibold tabular-nums text-ink"><CountUp value={x.v} /></div>
            <div className="mt-1 text-xs leading-tight text-muted2 sm:text-sm">{t(x.k)}</div>
          </StaggerItem>
        ))}
      </Stagger>

      {/* Featured products — real catalogue only */}
      {featured.length > 0 && (
        <div data-testid="featured-products">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="flex items-center gap-2.5 font-display text-lg font-semibold text-ink"><span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><ShoppingBag size={18} /></span> {t("nav.products")}</h3>
            <button onClick={() => navigate("/app/products")} className="group flex items-center gap-1 rounded-full px-2 py-1 text-sm font-medium text-hg-lavender hover:bg-brand-50">{t("cta.viewAll")} <ChevronRight size={16} className="transition-transform group-hover:translate-x-0.5" /></button>
          </div>
          <Stagger className="no-scrollbar -mx-4 flex snap-x snap-mandatory gap-3 overflow-x-auto px-4 pb-3 pt-1">
            {featured.map((p) => {
              const off = p.mrp > p.selling_price ? Math.round((1 - p.selling_price / p.mrp) * 100) : 0;
              return (
                <StaggerItem as="button" key={p.id} {...pressable} onClick={() => navigate(`/app/products/${p.id}`)} className="hg-card hg-lift group w-44 shrink-0 snap-start overflow-hidden text-left" data-testid={`featured-${p.sku}`}>
                  <div className="relative aspect-[4/3] overflow-hidden bg-brand-50">
                    {p.images?.[0] && <img src={p.images[0]} alt={p.name} loading="lazy" className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-110" />}
                    <span className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/35 to-transparent" />
                    {off > 0 && <span className="hg-off-badge absolute right-2 top-2 rounded-lg px-2 py-0.5 text-xs font-bold shadow-sm">-{off}%</span>}
                  </div>
                  <div className="p-3">
                    <div className="line-clamp-1 text-sm font-medium text-ink">{p.name}</div>
                    <div className="mt-1 flex items-baseline gap-1.5">
                      <span className="font-semibold text-hg-lavender">{money(p.selling_price)}</span>
                      {off > 0 && <span className="text-xs text-muted2 line-through">{money(p.mrp)}</span>}
                    </div>
                  </div>
                </StaggerItem>
              );
            })}
          </Stagger>
        </div>
      )}

      <motion.button {...pressable} onClick={() => navigate("/app/referral")} className="hg-orange hg-sheen group relative flex w-full items-center gap-4 overflow-hidden rounded-3xl p-5 text-left" data-testid="share-banner">
        <span className="hg-orb -right-6 -top-8 h-28 w-28 bg-white/25" />
        <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-white/20 ring-1 ring-white/25 transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-105"><Share2 size={26} /></span>
        <span className="min-w-0 flex-1">
          <span className="block text-lg font-semibold">{t("rewards.shareTitle")}</span>
          <span className="block text-sm text-white/85">{t("rewards.shareSub")}</span>
        </span>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/15 transition-transform duration-300 group-hover:translate-x-1"><ChevronRight size={20} /></span>
      </motion.button>

      {/* Commission — live rules */}
      <SectionCard title={t("plan.title")} icon={TrendingUp} testid="commission-card">
        <Stagger className="grid gap-3 sm:grid-cols-3">
          {[
            { k: "plan.direct", v: d.plan?.direct_pct, id: "direct" },
            { k: "plan.referral", v: d.plan?.referral_pct, id: "referral" },
            { k: "plan.team", v: d.plan?.team_pct, id: "team" },
          ].map((x) => (
            <StaggerItem key={x.k} className="hg-tile p-4" data-testid={`plan-${x.id}`}>
              <div className="font-display text-2xl font-semibold tabular-nums text-hg-violet dark:text-hg-lavender">{Number(x.v || 0)}%</div>
              <div className="mt-1 text-sm text-muted2">{t(x.k)}</div>
            </StaggerItem>
          ))}
        </Stagger>
        <ul className="mt-4 space-y-1.5 text-xs text-muted2">
          <li className="flex gap-2"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-hg-lavender" /><span>{t("plan.base")}</span></li>
          <li className="flex gap-2"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-hg-lavender" /><span>{t("plan.release")} ({d.plan?.return_window_days} {t("common.days")})</span></li>
          <li className="flex gap-2"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-hg-lavender" /><span>{t("plan.rules")}</span></li>
        </ul>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="hg-tile min-w-0 p-3.5" data-testid="my-sales">
            <div className="text-xs uppercase tracking-wide text-muted2">{t("dash.mySales")}</div>
            <div className="mt-1 font-display text-lg font-semibold tabular-nums text-ink">{d.stats.sales_count ?? 0}</div>
          </div>
          <div className="hg-tile min-w-0 p-3.5" data-testid="pending-commission">
            <div className="text-xs uppercase tracking-wide text-muted2">{t("dash.pendingCommission")}</div>
            <div className="mt-1 font-display text-lg font-semibold tabular-nums text-hg-gold">{pts(d.stats.pending_commission)}</div>
          </div>
          <div className="hg-tile min-w-0 p-3.5" data-testid="team-commission">
            <div className="text-xs uppercase tracking-wide text-muted2">{t("dash.teamCommission")}</div>
            <div className="mt-1 font-display text-lg font-semibold tabular-nums text-ink">{pts(d.stats.team_commission)}</div>
          </div>
        </div>
      </SectionCard>

      {/* Points note */}
      <SectionCard title={t("dash.pointsTitle")} icon={Coins} testid="points-card">
        <p className="text-sm text-muted2">{t("withdraw.note")}</p>
        <p className="mt-3 inline-flex rounded-full bg-hg-violet/15 px-3 py-1 text-xs font-medium text-hg-violet ring-1 ring-hg-lavender/25 dark:text-hg-lavender">{t("wallet.rate")}</p>
      </SectionCard>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Sales chart */}
        <SectionCard title={t("dash.salesOverview")} icon={TrendingUp} className="min-w-0 lg:col-span-2">
          <div className="h-64 w-full min-w-0">
            <ResponsiveContainer width="100%" height={256} minWidth={0} debounce={1}>
              <LineChart data={d.income_series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(145,133,164,0.25)" vertical={false} />
                <XAxis dataKey="date" tick={{ fill: "#9185A4", fontSize: 12 }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fill: "#9185A4", fontSize: 12 }} axisLine={false} tickLine={false} width={30} />
                <Tooltip
                  contentStyle={{ background: "rgba(25,14,43,.92)", border: "1px solid rgba(255,255,255,.14)", color: "#fff", borderRadius: 12 }}
                  labelStyle={{ color: "#C9BED9" }} itemStyle={{ color: "#fff" }}
                  cursor={{ stroke: "rgba(198,155,255,0.35)" }}
                  formatter={(v) => money(v)} />
                <Line type="monotone" dataKey="income" stroke="#8B3DFF" strokeWidth={2.5}
                  dot={{ r: 3.5, fill: "#C69BFF", stroke: "#8B3DFF", strokeWidth: 1.5 }}
                  activeDot={{ r: 5.5, fill: "#C69BFF", stroke: "#fff", strokeWidth: 2 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </SectionCard>

        {/* Quick actions */}
        <SectionCard title={t("dash.quickActions")} icon={Sparkles}>
          <Stagger className="grid grid-cols-3 gap-2.5">
            {quick.map((q) => {
              const Icon = q.icon;
              return (
                <StaggerItem as="button" key={q.key} {...pressable} onClick={() => navigate(q.to)} data-testid={`qa-${q.key.split(".")[1]}`}
                  className="hg-tile group flex min-w-0 flex-col items-center gap-2 p-3 text-center text-xs font-medium text-ink transition-colors hover:bg-brand-50/60">
                  <span className="hg-icon-chip !h-10 !w-10 transition-transform duration-300 group-hover:scale-110"><Icon size={19} /></span>
                  <span className="w-full break-words leading-tight">{t(q.key)}</span>
                </StaggerItem>
              );
            })}
          </Stagger>
        </SectionCard>
      </div>

      {/* Recent orders + point activity */}
      <div className="grid gap-5 lg:grid-cols-2">
        <SectionCard title={t("dash.recentOrders")} icon={Package} className="min-w-0"
          action={<button onClick={() => navigate("/app/orders")} className="group flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-sm font-medium text-hg-violet hover:bg-brand-50 dark:text-hg-lavender">{t("cta.viewAll")} <ChevronRight size={16} className="transition-transform group-hover:translate-x-0.5" /></button>}>
          {d.recent_orders.length === 0 ? <EmptyState icon={Package} title={t("empty.orders")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="empty-orders" /> : (
            <Stagger className="space-y-2.5">
              {d.recent_orders.map((o) => (
                <StaggerItem key={o.id} className="hg-tile flex items-center justify-between gap-3 p-3.5">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className="hg-icon-chip !h-9 !w-9 shrink-0 !rounded-xl"><Package size={16} /></span>
                    <div className="min-w-0"><div className="truncate font-medium text-ink">{o.order_number}</div><div className="truncate text-xs capitalize text-muted2">{o.status}</div></div>
                  </div>
                  <div className="shrink-0 font-display font-semibold tabular-nums text-ink">{money(o.total)}</div>
                </StaggerItem>
              ))}
            </Stagger>
          )}
        </SectionCard>

        <SectionCard title={t("dash.recentTxns")} icon={Coins} className="min-w-0"
          action={<button onClick={() => navigate("/app/wallet")} className="group flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-sm font-medium text-hg-violet hover:bg-brand-50 dark:text-hg-lavender">{t("cta.viewAll")} <ChevronRight size={16} className="transition-transform group-hover:translate-x-0.5" /></button>}>
          {d.recent_transactions.length === 0 ? <EmptyState icon={Coins} title={t("empty.wallet")} testid="empty-txns" /> : (
            <Stagger className="space-y-2.5">
              {d.recent_transactions.map((tx) => {
                const credit = tx.direction === "credit";
                return (
                  <StaggerItem key={tx.id} className="hg-tile flex items-center justify-between gap-3 p-3.5">
                    <div className="flex min-w-0 items-center gap-3">
                      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${credit ? "bg-hg-success/15 text-hg-success ring-hg-success/25" : "bg-danger/10 text-danger ring-danger/25"}`}>
                        {credit ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                      </span>
                      <div className="min-w-0"><div className="truncate font-medium capitalize text-ink">{tx.type.replace(/_/g, " ")}</div><div className="text-xs text-muted2">{(tx.created_at || "").slice(0, 10)}</div></div>
                    </div>
                    <div className={`shrink-0 font-display font-semibold tabular-nums ${credit ? "text-hg-success" : "text-danger"}`}>{credit ? "+" : "-"}{pts(tx.amount)}</div>
                  </StaggerItem>
                );
              })}
            </Stagger>
          )}
        </SectionCard>
      </div>
    </div>
  );
}
