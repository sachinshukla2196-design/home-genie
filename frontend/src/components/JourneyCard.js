import React from "react";
import { useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "framer-motion";
import {
  UserPlus, ShoppingCart, Coins, Users, Trophy, Check, ChevronRight, Lock, Sparkles,
  ShieldCheck, Eye, HeartHandshake, Award,
} from "lucide-react";
import { ProgressBar } from "@/components/motion";

/**
 * "How HomeGenie works" — five honest steps, each ticked from the user's real /api/dashboard data:
 *   1 approved (status green) · 2 has placed an order or made a sale · 3 has points credited
 *   4 has referred customers · 5 holds a badge this month.
 * Nothing here credits anything; it only reflects what the account already shows.
 */
const EASE = [0.16, 1, 0.3, 1];

export function journeySteps(d) {
  const s = d?.stats || {};
  const w = d?.wallet || {};
  const b = d?.badge || {};
  return [
    { id: 1, icon: UserPlus, done: d?.user?.status === "green" },
    { id: 2, icon: ShoppingCart, done: (s.total_orders || 0) > 0 || (s.sales_count || 0) > 0, to: "/app/products", cta: "jr.s2.cta" },
    { id: 3, icon: Coins, done: (w.total_earned || 0) > 0 || (w.pending_balance || 0) > 0, to: "/app/wallet", cta: "jr.s3.cta" },
    { id: 4, icon: Users, done: (s.referral_count || 0) > 0, to: "/app/referral", cta: "jr.s4.cta" },
    { id: 5, icon: Trophy, done: Boolean(b.badge), to: null },
  ];
}

const FEATURES = [
  { key: "jr.f1", icon: ShieldCheck },
  { key: "jr.f2", icon: Eye },
  { key: "jr.f3", icon: HeartHandshake },
  { key: "jr.f4", icon: Award },
];

export function JourneyCard({ d, t }) {
  const navigate = useNavigate();
  const reduce = useReducedMotion();
  const at = (x) => (reduce ? 0 : x);
  const steps = journeySteps(d);
  const doneCount = steps.filter((s) => s.done).length;
  const current = steps.find((s) => !s.done)?.id; // the first unfinished step is "Next"
  const badge = d?.badge || {};
  const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

  return (
    <section className="hg-card relative overflow-hidden p-5 sm:p-6" data-testid="journey-workflow" aria-labelledby="jr-title">
      <span className="hg-orb -right-12 -top-12 h-44 w-44 bg-hg-violet/25" />
      <span className="hg-orb -bottom-16 -left-10 h-40 w-40 bg-hg-pink/15" />

      {/* Header */}
      <div className="relative text-center">
        <motion.img src="/brand/logo-icon.png" alt="" className="mx-auto h-12 w-12 rounded-2xl ring-1 ring-white/15"
          initial={{ scale: reduce ? 1 : 0.6, rotate: reduce ? 0 : -10, opacity: 0 }} animate={{ scale: 1, rotate: 0, opacity: 1 }}
          transition={{ type: "spring", stiffness: 260, damping: 16 }} />
        <h2 id="jr-title" className="mt-3 font-display text-2xl font-bold leading-snug">
          <span className="hg-gradient-text -mt-[0.2em] inline-block pt-[0.2em]">{t("jr.title")}</span>
        </h2>
        <p className="mt-1 text-sm text-muted2">{t("jr.sub")}</p>
        <div className="mx-auto mt-4 max-w-xs">
          <ProgressBar pct={(doneCount / steps.length) * 100} testid="jr-progress" />
          <div className="mt-1.5 text-xs font-semibold text-muted2" data-testid="jr-count">
            <span className="text-ink">{doneCount}/{steps.length}</span> {t("jr.progress")}
          </div>
        </div>
      </div>

      {/* Steps on a self-drawing line */}
      <ol className="relative mt-6 space-y-3">
        <span aria-hidden className="absolute bottom-8 left-[1.85rem] top-8 w-[2px] rounded-full bg-white/10" />
        <motion.span aria-hidden className="absolute bottom-8 left-[1.85rem] top-8 w-[2px] origin-top rounded-full bg-gradient-to-b from-hg-violet via-hg-lavender to-hg-pink"
          initial={{ scaleY: reduce ? 1 : 0 }} animate={{ scaleY: 1 }} transition={{ duration: 1.6, delay: at(0.3), ease: "easeInOut" }} />

        {steps.map((s, i) => {
          const isNow = s.id === current;
          const state = s.done ? "done" : isNow ? "now" : "locked";
          const Icon = s.icon;
          return (
            <motion.li key={s.id} data-testid={`jr-step-${s.id}`} data-state={state}
              initial={{ opacity: 0, x: reduce ? 0 : 24 }} animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.5, delay: at(0.35 + i * 0.16), ease: EASE }}
              className={`relative flex gap-3.5 rounded-2xl p-3 transition-colors ${isNow ? "bg-hg-violet/[0.12] ring-1 ring-hg-lavender/40" : "hg-tile"}`}>
              {/* step medallion */}
              <motion.span initial={{ scale: reduce ? 1 : 0.5 }} animate={{ scale: 1 }}
                transition={{ type: "spring", stiffness: 380, damping: 15, delay: at(0.4 + i * 0.16) }}
                className={`relative z-10 flex h-[3.25rem] w-[3.25rem] shrink-0 items-center justify-center rounded-full ring-4 ring-hg-bg2 ${
                  s.done ? "bg-gradient-to-br from-hg-violet to-hg-pink text-white shadow-[0_0_24px_-4px_rgba(139,61,255,0.8)]"
                    : isNow ? "bg-gradient-to-br from-hg-violet to-[#6B2BD0] text-white" : "bg-white/[0.06] text-muted2"}`}>
                <Icon size={22} />
                {isNow && !reduce && <span className="absolute inset-0 animate-ping rounded-full bg-hg-violet/30 [animation-duration:2s]" />}
                {s.done && (
                  <span className="absolute -bottom-0.5 -right-0.5 flex h-5 w-5 items-center justify-center rounded-full bg-hg-success text-hg-bg ring-2 ring-hg-bg2">
                    <Check size={12} strokeWidth={3} />
                  </span>
                )}
              </motion.span>

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-hg-gold/15 text-xs font-bold text-hg-gold ring-1 ring-hg-gold/30">{s.id}</span>
                  <span className="font-display text-[15px] font-semibold leading-tight text-ink">{t(`jr.s${s.id}.t`)}</span>
                  <span className={`ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ring-1 ${
                    s.done ? "bg-hg-success/15 text-hg-success ring-hg-success/30"
                      : isNow ? "bg-hg-violet/20 text-hg-lavender ring-hg-lavender/30" : "bg-white/5 text-muted2 ring-white/10"}`}>
                    {s.done ? <Check size={10} /> : isNow ? <Sparkles size={10} /> : <Lock size={10} />}
                    {s.done ? t("jr.done") : isNow ? t("jr.now") : t("jr.locked")}
                  </span>
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-muted2">{t(`jr.s${s.id}.d`)}</p>

                {/* live detail per step */}
                {s.id === 1 && !s.done && (
                  <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-hg-gold/10 px-2.5 py-1 text-xs font-semibold text-hg-gold ring-1 ring-hg-gold/25" data-testid="jr-pending">
                    <Lock size={12} /> {t("jr.s1.pending")}
                  </div>
                )}
                {s.id === 5 && (
                  <div className="mt-2" data-testid="jr-badge">
                    {badge.next_badge ? (
                      <>
                        <div className="flex justify-between text-xs text-muted2">
                          <span>{badge.badge || t("badge.none")}</span>
                          <span>{inr(badge.sales_value)} / {inr(badge.next_target)} · {badge.next_badge}</span>
                        </div>
                        <div className="mt-1"><ProgressBar pct={badge.progress_pct || 0} /></div>
                      </>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full bg-hg-gold/15 px-2.5 py-1 text-xs font-semibold text-hg-gold"><Trophy size={12} /> {badge.badge}</span>
                    )}
                  </div>
                )}
                {s.to && isNow && (
                  <motion.button whileTap={{ scale: 0.96 }} onClick={() => navigate(s.to)} data-testid={`jr-cta-${s.id}`}
                    className="hg-btn group mt-2.5 inline-flex h-9 items-center gap-1 rounded-full px-4 text-xs font-semibold">
                    {t(s.cta)} <ChevronRight size={14} className="transition-transform group-hover:translate-x-0.5" />
                  </motion.button>
                )}
              </div>
            </motion.li>
          );
        })}
      </ol>

      {/* Feature strip */}
      <motion.div initial={{ opacity: 0, y: reduce ? 0 : 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: at(1.3) }}
        className="relative mt-5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {FEATURES.map((f) => (
          <div key={f.key} className="flex items-center gap-2 rounded-xl bg-white/[0.04] px-2.5 py-2 ring-1 ring-white/10">
            <f.icon size={15} className="shrink-0 text-hg-gold" />
            <span className="text-[11px] font-semibold leading-tight text-ink">{t(f.key)}</span>
          </div>
        ))}
      </motion.div>
    </section>
  );
}
