import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Trophy, Crown, Medal, Star, Banknote, Share2, History, ChevronRight, Sparkles } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Stagger, StaggerItem, CountUp, ProgressBar, pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";
import { JourneyCard } from "@/components/JourneyCard";

const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const num = (v) => Number(v || 0).toLocaleString("en-IN", { maximumFractionDigits: 0 });

// Rank styling: gold / silver / bronze circles for the podium.
const RANK_STYLE = {
  1: "bg-hg-gold/15 text-hg-gold ring-1 ring-hg-gold/40",
  2: "bg-[#CBD5E1]/15 text-[#CBD5E1] ring-1 ring-[#CBD5E1]/35",
  3: "bg-[#F59E0B]/15 text-[#F59E0B] ring-1 ring-[#F59E0B]/35",
};

function RankIcon({ rank }) {
  if (rank === 1) return <Crown size={26} className="hg-float text-hg-gold" fill="#F2CB4B" />;
  if (rank <= 3) return <Medal size={24} className={rank === 2 ? "text-[#CBD5E1]" : "text-[#F59E0B]"} />;
  if (rank <= 5) return <Medal size={24} className="text-hg-gold" />;
  return <Star size={24} className="text-hg-gold" fill="#F2CB4B" />;
}

function Row({ r, t, max }) {
  const share = max ? Math.max((r.sales / max) * 100, 4) : 0;
  return (
    <motion.div
      variants={{ hidden: { opacity: 0, x: -18 }, show: { opacity: 1, x: 0, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] } } }}
      whileHover={{ scale: 1.01 }}
      className={`relative overflow-hidden rounded-2xl px-4 py-3.5 ${r.is_me ? "hg-me-row" : "hg-tile"}`}
      data-testid={`lb-row-${r.rank}`}
    >
      {/* Relative sales bar behind the row */}
      <motion.span aria-hidden className={`absolute inset-y-0 left-0 ${r.is_me ? "bg-hg-gold/10" : "bg-hg-violet/[0.07]"}`}
        initial={{ width: 0 }} whileInView={{ width: `${share}%` }} viewport={{ once: true }}
        transition={{ duration: 1, ease: [0.16, 1, 0.3, 1], delay: 0.2 }} />
      <div className="relative flex items-center gap-3.5">
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-bold ${RANK_STYLE[r.rank] || "text-ink"}`}>{r.rank}</span>
        <span className="flex w-8 shrink-0 justify-center"><RankIcon rank={r.rank} /></span>
        <div className="min-w-0 flex-1">
          <div className={`flex items-baseline gap-1.5 text-base font-semibold ${r.is_me ? "text-hg-gold" : "text-ink"}`}>
            <span className="truncate">{r.name}</span>
            {r.is_me && <span className="shrink-0 rounded-full bg-hg-gold/15 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide">{t("lb.you")}</span>}
          </div>
          {r.city && <div className="truncate text-sm text-muted2">{r.city}</div>}
        </div>
        <div className="text-right text-base font-semibold tabular-nums text-ink">{inr(r.sales)}</div>
      </div>
    </motion.div>
  );
}

function Banner({ onClick, className, icon: Icon, eyebrow, title, sub, testid, plain = false }) {
  const soft = plain ? "text-muted2" : "text-white/85";
  return (
    <motion.button {...pressable} onClick={onClick} data-testid={testid}
      className={`group relative flex w-full items-center gap-4 overflow-hidden rounded-3xl p-5 text-left ${plain ? "" : "hg-sheen"} ${className}`}>
      {!plain && <span className="hg-orb -right-6 -top-8 h-28 w-28 bg-white/25" />}
      <span className={`flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-105 ${plain ? "hg-icon-chip !h-16 !w-16 !rounded-2xl" : "bg-white/20 ring-1 ring-white/25"}`}>
        <Icon size={30} />
      </span>
      <span className="min-w-0 flex-1">
        {eyebrow && <span className={`block text-xs font-semibold uppercase tracking-wider ${soft}`}>{eyebrow}</span>}
        <span className="block text-lg font-semibold leading-snug">{title}</span>
        <span className={`block text-sm ${soft}`}>{sub}</span>
      </span>
      <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition-transform duration-300 group-hover:translate-x-1 ${plain ? "bg-brand-50" : "bg-white/15"}`}>
        <ChevronRight size={20} />
      </span>
    </motion.button>
  );
}

export default function Rewards() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [lb, setLb] = useState(null);
  const [d, setD] = useState(null);

  useEffect(() => {
    API.get("/leaderboard").then(({ data }) => setLb(data)).catch(() => setLb({ top: [], me: null }));
    API.get("/dashboard").then(({ data }) => setD(data)).catch(() => {});
  }, []);

  const badge = d?.badge;
  const available = d?.wallet?.available_balance ?? 0;
  const meOutsideTop = lb?.me && !lb.top.some((r) => r.is_me);
  const max = lb?.top?.[0]?.sales || 0;

  return (
    <Stagger className="mx-auto max-w-2xl space-y-5" data-testid="rewards-page">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.rewards")}</h1>

      {/* How HomeGenie works — live 5-step progress */}
      <StaggerItem>
        {!d ? <Skeleton className="h-[34rem] rounded-3xl" /> : <JourneyCard d={d} t={t} />}
      </StaggerItem>

      {/* Points + badge card */}
      <StaggerItem>
        {!d ? <Skeleton className="h-56 rounded-3xl" /> : (
          <div className="hg-card relative overflow-hidden p-7 text-center" data-testid="rewards-points-card">
            <span className="hg-orb left-1/2 top-4 h-28 w-40 -translate-x-1/2 bg-hg-gold/15" />
            <div className="relative">
              <div className="inline-flex items-center gap-1.5 text-base text-muted2"><Sparkles size={16} className="text-hg-gold" /> {t("rewards.balance")}</div>
              <div className="mt-1 font-display text-5xl font-bold tabular-nums text-hg-gold" data-testid="rewards-points"><CountUp value={available} /></div>
              <motion.span initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: 0.35, type: "spring", stiffness: 300, damping: 18 }}
                className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-hg-gold/15 px-4 py-1.5 text-sm font-semibold text-hg-gold ring-1 ring-hg-gold/25" data-testid="rewards-badge">
                <Trophy size={14} /> {badge?.badge || t("badge.none")}
              </motion.span>
              {badge?.next_badge && (
                <div className="mx-auto mt-5 max-w-sm">
                  <ProgressBar pct={badge.progress_pct} />
                  <div className="mt-2 text-sm text-muted2">
                    <span className="font-semibold text-ink">{inr(badge.sales_value)}</span> / {inr(badge.next_target)} {t("rewards.toNext")} <span className="font-semibold text-hg-gold">{badge.next_badge}</span>
                  </div>
                </div>
              )}
              <p className="mt-4 text-xs text-muted2">{t("badge.note")}</p>
            </div>
          </div>
        )}
      </StaggerItem>

      <StaggerItem>
        <Banner testid="rewards-withdraw" onClick={() => navigate("/app/withdrawals")} className="hg-orange" icon={Banknote}
          eyebrow={t("nav.withdrawals")} title={t("rewards.withdrawTitle")} sub={`${num(available)} ${t("rewards.withdrawSub")}`} />
      </StaggerItem>
      <StaggerItem>
        <Banner testid="rewards-share" onClick={() => navigate("/app/referral")} className="hg-violet" icon={Share2}
          title={t("rewards.shareTitle")} sub={t("rewards.shareSub")} />
      </StaggerItem>

      {/* Leaderboard */}
      <StaggerItem className="hg-card p-5 sm:p-6" data-testid="leaderboard">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="hg-icon-chip !bg-hg-pink/15 !text-hg-pink"><Trophy size={22} /></span>
            <h2 className="font-display text-base font-semibold text-ink sm:text-xl">{t("lb.title")}</h2>
          </div>
          <span className="shrink-0 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-muted2">{t("lb.thisMonth")}</span>
        </div>
        {!lb ? (
          <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-16 rounded-2xl" />)}</div>
        ) : lb.top.length === 0 ? (
          <div className="hg-tile flex flex-col items-center gap-3 p-8 text-center text-sm text-muted2" data-testid="lb-empty">
            <span className="hg-icon-chip hg-float !h-14 !w-14"><Trophy size={26} /></span>
            {t("lb.empty")}
          </div>
        ) : (
          <motion.div className="space-y-2.5" initial="hidden" animate="show"
            variants={{ hidden: {}, show: { transition: { staggerChildren: 0.07, delayChildren: 0.15 } } }}>
            {lb.top.map((r) => <Row key={r.rank} r={r} t={t} max={max} />)}
            {meOutsideTop && <><div className="text-center text-muted2">···</div><Row r={lb.me} t={t} max={max} /></>}
          </motion.div>
        )}
        <p className="mt-4 text-xs text-muted2">{t("lb.note")}</p>
      </StaggerItem>

      <StaggerItem>
        <Banner testid="rewards-history" onClick={() => navigate("/app/wallet")} className="hg-card hg-lift text-ink" plain icon={History}
          title={t("rewards.historyTitle")} sub={t("rewards.historySub")} />
      </StaggerItem>
    </Stagger>
  );
}
