import React from "react";
import { motion, useMotionValue, useSpring, useTransform, useReducedMotion } from "framer-motion";
import {
  ArrowRight, ArrowUpRight, Sparkles, Smartphone, Clock, ShoppingBag, Eye, Heart, CheckCircle2,
  TrendingUp, Package, BadgeIndianRupee, Coins, LayoutDashboard, Share2, ShieldCheck, RotateCcw, Truck, HeartHandshake,
  ShoppingCart, Users, ClipboardCheck, IndianRupee, ArrowUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { pressable } from "@/components/motion";

/*
 * Premium landing sections that match the hero's motion language:
 *  - PillarsSection: bento grid; each card's photo wipes open on scroll, then tilts toward the cursor on hover.
 *  - WhySection: feature cards that rise in sequence + a journey timeline whose line draws as it scrolls in,
 *    lighting each step when the line reaches it, ending in a call to action.
 * Reduced motion → simple fades, no wipes, no tilt.
 */

const EASE = [0.16, 1, 0.3, 1];
const VIEW = { once: true, margin: "-80px" };

const PILLARS = [
  { key: "pillar.sarees", img: "/brand/pillar-sarees.jpg", cat: "Sarees",
    span: "col-span-2 h-[300px] sm:h-[360px] lg:col-span-2 lg:row-span-2 lg:h-auto" },
  { key: "pillar.fashion", img: "/brand/pillar-fashion.jpg", cat: "Fashion Products",
    span: "col-span-1 h-[230px] lg:col-span-2 lg:h-auto" },
  { key: "pillar.beauty", img: "/brand/pillar-beauty.jpg", cat: "Makeup, Beauty & Skincare",
    span: "col-span-1 h-[230px] lg:h-auto" },
  { key: "pillar.household", img: "/brand/pillar-household.jpg", cat: "Household Essentials",
    span: "col-span-2 h-[220px] lg:col-span-1 lg:h-auto" },
];

const WHY = [
  { key: "why.1", icon: Smartphone, tone: "from-hg-violet to-[#B36BFF]" },
  { key: "why.2", icon: Clock, tone: "from-[#5B7CFF] to-[#8FA6FF]" },
  { key: "why.3", icon: ShoppingBag, tone: "from-[#2BB98A] to-hg-success" },
  { key: "why.4", icon: Eye, tone: "from-[#E0A92E] to-hg-gold" },
];
const JOURNEY = ["journey.1", "journey.2", "journey.3", "journey.4"];

/** Title with the part after the comma (or the last two words) in the brand gradient. */
function SplitTitle({ text, className = "" }) {
  let head = text, tail = "";
  const comma = text.search(/[,،]/);
  if (comma > 0) { head = text.slice(0, comma + 1) + " "; tail = text.slice(comma + 1).trim(); }
  else {
    const w = text.split(" ");
    if (w.length > 3) { tail = w.slice(-2).join(" "); head = w.slice(0, -2).join(" ") + " "; }
  }
  return (
    <h2 className={`font-display text-3xl font-bold leading-tight text-ink sm:text-[2.6rem] ${className}`}>
      {head}{tail && <span className="hg-gradient-text -mt-[0.2em] inline-block pt-[0.2em]">{tail}</span>}
    </h2>
  );
}

function Eyebrow({ children }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-hg-violet/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-hg-lavender ring-1 ring-hg-lavender/25">
      <Sparkles size={12} /> {children}
    </span>
  );
}

/** Card that tilts toward the cursor (hover devices only, not with reduced motion). */
function TiltCard({ children, className, disabled, ...rest }) {
  const mx = useMotionValue(0), my = useMotionValue(0);
  const rx = useSpring(useTransform(my, [-0.5, 0.5], [7, -7]), { stiffness: 220, damping: 20 });
  const ry = useSpring(useTransform(mx, [-0.5, 0.5], [-9, 9]), { stiffness: 220, damping: 20 });
  const onMove = (e) => {
    if (disabled) return;
    const r = e.currentTarget.getBoundingClientRect();
    mx.set((e.clientX - r.left) / r.width - 0.5);
    my.set((e.clientY - r.top) / r.height - 0.5);
  };
  const reset = () => { mx.set(0); my.set(0); };
  return (
    <motion.button type="button" onMouseMove={onMove} onMouseLeave={reset}
      style={disabled ? undefined : { rotateX: rx, rotateY: ry, transformPerspective: 900 }}
      className={className} {...rest}>
      {children}
    </motion.button>
  );
}

export function PillarsSection({ t, navigate }) {
  const reduce = useReducedMotion();
  // Per-card sequence (custom = card index): photo wipes up → photo settles from zoom → copy rises.
  const wipe = {
    hidden: reduce ? { opacity: 0 } : { opacity: 1, clipPath: "inset(100% 0% 0% 0% round 24px)" },
    show: (i) => ({ opacity: 1, clipPath: "inset(0% 0% 0% 0% round 24px)",
      transition: { duration: reduce ? 0.3 : 0.9, delay: reduce ? 0 : i * 0.13, ease: EASE } }),
  };
  const zoom = {
    hidden: { scale: reduce ? 1.05 : 1.3 },
    show: (i) => ({ scale: 1.05, transition: { duration: reduce ? 0 : 1.4, delay: reduce ? 0 : i * 0.13, ease: EASE } }),
  };
  const rise = {
    hidden: { opacity: 0, y: reduce ? 0 : 14 },
    show: (i) => ({ opacity: 1, y: 0, transition: { duration: 0.5, delay: reduce ? 0 : 0.45 + i * 0.13, ease: EASE } }),
  };
  return (
    <section id="categories" className="relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8 lg:py-24">
      <span className="hg-orb -left-24 top-24 h-72 w-72 bg-hg-violet/20" />
      <div className="relative flex flex-wrap items-end justify-between gap-6">
        <motion.div className="max-w-2xl" initial={{ opacity: 0, y: reduce ? 0 : 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ duration: 0.6, ease: EASE }}>
          <Eyebrow>{t("pillars.eyebrow")}</Eyebrow>
          <SplitTitle text={t("pillars.title")} className="mt-4" />
          <p className="mt-3 text-base text-muted2">{t("pillars.sub")}</p>
        </motion.div>
        <motion.div initial={{ opacity: 0, x: reduce ? 0 : 20 }} whileInView={{ opacity: 1, x: 0 }} viewport={VIEW} transition={{ duration: 0.6, delay: 0.2, ease: EASE }}
          className="hg-script hidden -rotate-6 text-2xl text-hg-lavender md:block" aria-hidden>
          {t("landing.moreThan")} <Heart size={15} className="inline text-hg-pink" fill="currentColor" />
        </motion.div>
      </div>

      <div className="relative mt-10 grid grid-cols-2 gap-3 sm:gap-4 lg:h-[580px] lg:grid-cols-4 lg:grid-rows-2">
        {PILLARS.map((p, i) => {
          const big = i === 0;
          return (
            // The outer wrapper is the scroll trigger (never clipped, so it is always detected);
            // the wipe, photo zoom and copy below follow it as one orchestrated sequence.
            <motion.div key={p.key} className={`relative ${p.span}`} initial="hidden" whileInView="show" viewport={VIEW} custom={i}>
              <motion.div variants={wipe} custom={i} className="h-full w-full">
              <TiltCard disabled={reduce} onClick={() => navigate(`/login?next=products&category=${encodeURIComponent(p.cat)}`)}
                className="group relative block h-full w-full overflow-hidden rounded-3xl border border-white/15 text-left shadow-lift outline-none transition-shadow duration-500 hover:shadow-[0_30px_60px_-20px_rgba(139,61,255,0.6)] focus-visible:ring-2 focus-visible:ring-hg-lavender"
                data-testid={`pillar-${i + 1}`} aria-label={`${t(`${p.key}.t`)} — ${t(`${p.key}.d`)}`}>
                <motion.span variants={zoom} custom={i} className="absolute inset-0 block">
                  <img src={p.img} alt="" loading="lazy" className="h-full w-full object-cover transition-transform duration-1000 ease-out group-hover:scale-110" />
                </motion.span>
                {/* colour + legibility layers */}
                <span className="absolute inset-0 bg-gradient-to-t from-hg-bg via-hg-bg/35 to-transparent" />
                <span className="absolute inset-0 bg-gradient-to-br from-hg-violet/0 via-transparent to-hg-pink/0 opacity-0 transition-opacity duration-500 group-hover:from-hg-violet/25 group-hover:to-hg-pink/15 group-hover:opacity-100" />
                <span className="pointer-events-none absolute inset-0 rounded-3xl ring-1 ring-inset ring-white/10 transition duration-500 group-hover:ring-hg-lavender/50" />

                {/* top row: index + arrow */}
                <span className="absolute left-4 top-4 rounded-full bg-black/25 px-2.5 py-1 font-display text-xs font-semibold tracking-widest text-white ring-1 ring-white/25 backdrop-blur-md">
                  0{i + 1}
                </span>
                <span className="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/15 text-white ring-1 ring-white/25 backdrop-blur-md transition duration-500 group-hover:rotate-45 group-hover:bg-hg-violet">
                  <ArrowUpRight size={18} />
                </span>

                {/* bottom copy */}
                <span className="absolute inset-x-0 bottom-0 p-4 sm:p-5">
                  <motion.span variants={rise} custom={i} className="block">
                    <span className={`block font-display font-semibold leading-tight text-white ${big ? "text-2xl sm:text-3xl" : "text-lg sm:text-xl"}`}>{t(`${p.key}.t`)}</span>
                    <span className={`mt-1 block text-white/80 ${big ? "max-w-sm text-sm sm:text-base" : "text-xs sm:text-sm"}`}>{t(`${p.key}.d`)}</span>
                    <span className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3.5 py-1.5 text-xs font-semibold text-white ring-1 ring-white/25 backdrop-blur-md transition-all duration-500 group-hover:bg-white group-hover:text-hg-deep lg:translate-y-2 lg:opacity-0 lg:group-hover:translate-y-0 lg:group-hover:opacity-100">
                      {t("cta.exploreProducts")} <ArrowRight size={13} />
                    </span>
                  </motion.span>
                </span>
              </TiltCard>
              </motion.div>
            </motion.div>
          );
        })}
      </div>
    </section>
  );
}

export function WhySection({ t, navigate, homeLink }) {
  const reduce = useReducedMotion();
  const at = (d) => (reduce ? 0 : d);
  const STEP = 0.38; // seconds between journey steps lighting up

  return (
    <section id="about" className="relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8 lg:py-24">
      <span className="hg-orb -right-24 top-32 h-80 w-80 bg-hg-pink/10" />
      <div className="relative grid gap-10 lg:grid-cols-[1.15fr_1fr] lg:gap-12">
        {/* ---- Why: heading + feature cards ---- */}
        <div>
          <motion.div initial={{ opacity: 0, y: reduce ? 0 : 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ duration: 0.6, ease: EASE }}>
            <Eyebrow>{t("why.eyebrow")}</Eyebrow>
            <SplitTitle text={t("why.title")} className="mt-4" />
            <p className="mt-3 max-w-xl text-base text-muted2">{t("why.sub")}</p>
          </motion.div>

          <ul className="mt-8 grid gap-3 sm:grid-cols-2 sm:gap-4">
            {WHY.map((w, i) => (
              <motion.li key={w.key} data-testid={`why-${i + 1}`}
                initial={{ opacity: 0, y: reduce ? 0 : 26 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW}
                transition={{ duration: 0.55, delay: at(0.1 + i * 0.12), ease: EASE }}
                whileHover={reduce ? undefined : { y: -5 }}
                className="hg-card group relative overflow-hidden p-5 transition-[border-color,box-shadow] duration-500 hover:border-hg-lavender/40 hover:shadow-[0_24px_48px_-20px_rgba(139,61,255,0.55)]">
                {/* top accent line grows in */}
                <motion.span aria-hidden className={`absolute left-0 top-0 h-[2px] bg-gradient-to-r ${w.tone}`}
                  initial={{ width: reduce ? "100%" : "0%" }} whileInView={{ width: "100%" }} viewport={VIEW}
                  transition={{ duration: 0.9, delay: at(0.35 + i * 0.12), ease: EASE }} />
                <span className="hg-orb -right-10 -top-10 h-24 w-24 bg-hg-violet/0 transition-colors duration-500 group-hover:bg-hg-violet/25" />
                <span className={`relative flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br ${w.tone} text-white shadow-lg transition-transform duration-500 group-hover:-rotate-6 group-hover:scale-110`}>
                  <w.icon size={22} />
                </span>
                <div className="relative mt-4 font-display text-base font-semibold text-ink">{t(`${w.key}.t`)}</div>
                <p className="relative mt-1.5 text-sm leading-relaxed text-muted2">{t(`${w.key}.d`)}</p>
              </motion.li>
            ))}
          </ul>
        </div>

        {/* ---- Journey: timeline that draws itself ---- */}
        <motion.div initial={{ opacity: 0, y: reduce ? 0 : 30, scale: reduce ? 1 : 0.98 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={VIEW}
          transition={{ duration: 0.7, ease: EASE }}
          className="hg-glass relative flex flex-col overflow-hidden !rounded-[2rem] p-6 sm:p-8" data-testid="journey-card">
          <span className="hg-orb -right-12 -top-12 h-48 w-48 bg-hg-pink/25" />
          <span className="hg-orb -bottom-16 -left-12 h-48 w-48 bg-hg-violet/30" />

          <div className="relative flex items-start justify-between gap-3">
            <div>
              <h3 className="font-display text-2xl font-semibold text-ink">{t("journey.title")}</h3>
              <p className="mt-1.5 text-sm text-muted2">{t("journey.sub")}</p>
            </div>
            <img src="/brand/logo-icon.png" alt="" className="hg-float-slow h-12 w-12 shrink-0 rounded-2xl ring-1 ring-white/20" />
          </div>

          <ol className="relative mt-8 flex-1 space-y-7">
            {/* track + progress line */}
            <span aria-hidden className="absolute bottom-6 left-[1.2rem] top-5 w-[2px] rounded-full bg-white/10" />
            <motion.span aria-hidden className="absolute bottom-6 left-[1.2rem] top-5 w-[2px] origin-top rounded-full bg-gradient-to-b from-hg-violet via-hg-lavender to-hg-pink"
              initial={{ scaleY: reduce ? 1 : 0 }} whileInView={{ scaleY: 1 }} viewport={VIEW}
              transition={{ duration: STEP * (JOURNEY.length - 1) + 0.2, delay: at(0.35), ease: "linear" }} />

            {JOURNEY.map((k, i) => (
              <li key={k} className="relative flex gap-4" data-testid={`journey-${i + 1}`}>
                <motion.span initial={{ scale: reduce ? 1 : 0.4, opacity: reduce ? 1 : 0 }} whileInView={{ scale: 1, opacity: 1 }} viewport={VIEW}
                  transition={{ type: "spring", stiffness: 420, damping: 18, delay: at(0.3 + i * STEP) }}
                  className="hg-btn relative z-10 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-sm font-bold ring-4 ring-hg-bg2">
                  {i + 1}
                  {!reduce && <span className="absolute inset-0 animate-ping rounded-full bg-hg-violet/30 [animation-iteration-count:2]" style={{ animationDelay: `${0.3 + i * STEP}s` }} />}
                </motion.span>
                <motion.div className="pt-1.5" initial={{ opacity: 0, x: reduce ? 0 : 18 }} whileInView={{ opacity: 1, x: 0 }} viewport={VIEW}
                  transition={{ duration: 0.5, delay: at(0.38 + i * STEP), ease: EASE }}>
                  <div className="font-semibold text-ink">{t(`${k}.t`)}</div>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted2">{t(`${k}.d`)}</p>
                </motion.div>
              </li>
            ))}
          </ol>

          {/* closing call to action fills the card's foot */}
          <motion.div initial={{ opacity: 0, y: reduce ? 0 : 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW}
            transition={{ duration: 0.5, delay: at(0.4 + JOURNEY.length * STEP), ease: EASE }}
            className="relative mt-8 flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white/[0.06] p-4 ring-1 ring-white/10">
            <span className="flex items-center gap-2 text-sm font-semibold text-ink">
              <CheckCircle2 size={18} className="text-hg-success" /> {t("cta.closingTitle")}
            </span>
            <motion.div {...pressable}>
              <Button onClick={() => navigate(homeLink)} className="hg-btn h-10 rounded-full px-5 text-sm font-semibold" data-testid="journey-cta">
                {t("cta.joinGenie")} <ArrowRight size={15} />
              </Button>
            </motion.div>
          </motion.div>
        </motion.div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------------------------------
 * Dashboard preview: an app-window mock that tips forward in 3D as it scrolls in. Shows NO figures —
 * only labelled placeholders that shimmer, plus the honesty disclaimer.
 * ---------------------------------------------------------------------------------------------- */
const PREVIEW = [
  { key: "preview.sales", icon: TrendingUp, tone: "from-hg-violet to-[#B36BFF]" },
  { key: "preview.orders", icon: Package, tone: "from-[#5B7CFF] to-[#8FA6FF]" },
  { key: "preview.commission", icon: BadgeIndianRupee, tone: "from-[#E0A92E] to-hg-gold" },
  { key: "preview.points", icon: Coins, tone: "from-[#2BB98A] to-hg-success" },
];
const BARS = [38, 55, 46, 70, 58, 82, 64, 90, 74, 96]; // placeholder bar heights (%), purely decorative

function Shimmer({ className = "" }) {
  return <span aria-hidden className={`relative block overflow-hidden rounded-full bg-white/10 ${className}`}><span className="hg-progress-glint !w-1/2 opacity-60" /></span>;
}

export function DashboardPreviewSection({ t }) {
  const reduce = useReducedMotion();
  const at = (d) => (reduce ? 0 : d);
  return (
    <section id="dashboard-preview" className="relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8 lg:py-24">
      <span className="hg-orb left-1/2 top-40 h-80 w-[36rem] -translate-x-1/2 bg-hg-violet/20" />
      <motion.div className="relative mx-auto max-w-3xl text-center" initial={{ opacity: 0, y: reduce ? 0 : 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ duration: 0.6, ease: EASE }}>
        <Eyebrow>{t("preview.eyebrow")}</Eyebrow>
        <SplitTitle text={t("preview.title")} className="mt-4" />
        <p className="mx-auto mt-3 max-w-2xl text-base text-muted2">{t("preview.sub")}</p>
      </motion.div>

      <div className="relative mt-12" style={{ perspective: 1400 }}>
        <motion.div data-testid="dashboard-preview"
          initial={reduce ? { opacity: 0 } : { opacity: 0, rotateX: 22, y: 60, scale: 0.94 }}
          whileInView={reduce ? { opacity: 1 } : { opacity: 1, rotateX: 0, y: 0, scale: 1 }} viewport={VIEW}
          transition={{ duration: 1.1, ease: EASE }} style={{ transformOrigin: "50% 0%" }}
          className="hg-glass relative overflow-hidden !rounded-[2rem] shadow-[0_40px_90px_-30px_rgba(139,61,255,0.6)]">
          {/* window chrome */}
          <div className="flex items-center gap-3 border-b border-white/10 px-5 py-3.5">
            <span className="flex gap-1.5"><i className="h-3 w-3 rounded-full bg-[#FF6B8B]/80" /><i className="h-3 w-3 rounded-full bg-hg-gold/80" /><i className="h-3 w-3 rounded-full bg-hg-success/80" /></span>
            <span className="flex min-w-0 items-center gap-2 text-sm font-semibold text-hg-lavender"><LayoutDashboard size={16} /> <span className="truncate">{t("preview.label")}</span></span>
            <span className="ml-auto hidden h-7 w-40 rounded-full bg-white/[0.06] ring-1 ring-white/10 sm:block" />
          </div>

          <div className="flex">
            {/* mini sidebar */}
            <div className="hidden w-16 shrink-0 flex-col items-center gap-3 border-r border-white/10 py-5 sm:flex">
              <img src="/brand/logo-icon.png" alt="" className="h-9 w-9 rounded-xl" />
              {[LayoutDashboard, ShoppingBag, Package, Coins, Share2].map((I, i) => (
                <motion.span key={i} initial={{ opacity: 0, x: reduce ? 0 : -10 }} whileInView={{ opacity: 1, x: 0 }} viewport={VIEW}
                  transition={{ delay: at(0.5 + i * 0.07) }}
                  className={`flex h-9 w-9 items-center justify-center rounded-xl ${i === 0 ? "bg-hg-violet text-white shadow-lg" : "text-muted2"}`}><I size={17} /></motion.span>
              ))}
            </div>

            <div className="min-w-0 flex-1 p-4 sm:p-6">
              {/* stat tiles: labels only, shimmering placeholders instead of numbers */}
              <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
                {PREVIEW.map((s, i) => (
                  <motion.div key={s.key} data-testid={`preview-${s.key.split(".")[1]}`}
                    initial={{ opacity: 0, y: reduce ? 0 : 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW}
                    transition={{ duration: 0.5, delay: at(0.55 + i * 0.1), ease: EASE }}
                    className="hg-tile relative overflow-hidden p-4">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-muted2">{t(s.key)}</span>
                      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${s.tone} text-white`}><s.icon size={15} /></span>
                    </div>
                    <Shimmer className="mt-4 h-3.5 w-2/3" />
                    <Shimmer className="mt-2 h-2 w-1/3" />
                    <span className="sr-only">—</span>
                  </motion.div>
                ))}
              </div>

              {/* chart area: decorative bars grow in (no values, no axes) */}
              <div className="mt-4 grid gap-3 sm:gap-4 lg:grid-cols-[2fr_1fr]">
                <div className="hg-tile p-4 sm:p-5" aria-hidden>
                  <div className="flex items-center justify-between"><Shimmer className="h-2.5 w-28" /><Shimmer className="h-2.5 w-16" /></div>
                  <motion.div className="mt-5 flex h-36 items-end gap-2 sm:gap-3" initial="hidden" whileInView="show" viewport={VIEW}>
                    {BARS.map((h, i) => (
                      <motion.span key={i} className="flex-1 origin-bottom rounded-t-lg bg-gradient-to-t from-hg-violet/50 to-hg-lavender/70"
                        style={{ height: `${h}%` }}
                        variants={{ hidden: { scaleY: reduce ? 1 : 0 }, show: { scaleY: 1, transition: { duration: 0.7, delay: at(0.6 + i * 0.06), ease: EASE } } }} />
                    ))}
                  </motion.div>
                </div>
                <div className="hg-tile space-y-3 p-4 sm:p-5" aria-hidden>
                  <Shimmer className="h-2.5 w-24" />
                  {[0, 1, 2].map((r) => (
                    <motion.div key={r} className="flex items-center gap-3" initial={{ opacity: 0, x: reduce ? 0 : 12 }} whileInView={{ opacity: 1, x: 0 }} viewport={VIEW}
                      transition={{ delay: at(1.1 + r * 0.12) }}>
                      <span className="h-9 w-9 shrink-0 rounded-xl bg-white/10" />
                      <span className="flex-1 space-y-1.5"><Shimmer className="h-2.5 w-3/4" /><Shimmer className="h-2 w-1/2" /></span>
                    </motion.div>
                  ))}
                </div>
              </div>

              <motion.p initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={VIEW} transition={{ delay: at(1.4) }}
                className="mt-4 flex items-start gap-2 rounded-xl bg-hg-gold/10 px-3.5 py-2.5 text-xs font-medium text-ink ring-1 ring-hg-gold/25" data-testid="preview-disclaimer">
                <ShieldCheck size={15} className="mt-px shrink-0 text-hg-gold" /> {t("preview.disclaimer")}
              </motion.p>
            </div>
          </div>
        </motion.div>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------------------------------
 * Trust & transparency: an emblem (logo inside a rotating gradient ring with orbiting icons) beside
 * four commitment cards that reveal in sequence.
 * ---------------------------------------------------------------------------------------------- */
const TRUST = [
  { key: "trust.commission", icon: ShieldCheck, tone: "from-hg-violet to-[#B36BFF]" },
  { key: "trust.returns", icon: RotateCcw, tone: "from-[#5B7CFF] to-[#8FA6FF]" },
  { key: "trust.delivery", icon: Truck, tone: "from-[#2BB98A] to-hg-success" },
  { key: "trust.support", icon: HeartHandshake, tone: "from-[#D96AC9] to-hg-pink" },
];

export function TrustSection({ t }) {
  const reduce = useReducedMotion();
  const at = (d) => (reduce ? 0 : d);
  return (
    <section id="trust" className="relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8 lg:py-24">
      <div className="grid items-center gap-12 lg:grid-cols-[0.9fr_1.4fr]">
        {/* emblem + heading */}
        <motion.div initial={{ opacity: 0, y: reduce ? 0 : 18 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ duration: 0.6, ease: EASE }}
          className="text-center lg:text-left">
          <div className="relative mx-auto mb-8 h-44 w-44 lg:mx-0" aria-hidden>
            <span className="hg-logo-glow absolute inset-6 rounded-full bg-hg-violet/40 blur-2xl" />
            <motion.span className="absolute inset-0 rounded-full p-[2px]"
              style={{ background: "conic-gradient(from 0deg, #8B3DFF, #ED9BEA, #F2CB4B, #55D6A5, #8B3DFF)" }}
              animate={reduce ? undefined : { rotate: 360 }} transition={{ duration: 14, ease: "linear", repeat: Infinity }}>
              <span className="block h-full w-full rounded-full bg-hg-bg" />
            </motion.span>
            <img src="/brand/logo-icon.png" alt="" className="absolute inset-7 h-[calc(100%-3.5rem)] w-[calc(100%-3.5rem)] rounded-full object-cover ring-1 ring-white/15" />
            {/* orbiting icons */}
            <motion.div className="absolute inset-0" animate={reduce ? undefined : { rotate: -360 }} transition={{ duration: 22, ease: "linear", repeat: Infinity }}>
              {TRUST.map((x, i) => {
                const a = (i / TRUST.length) * Math.PI * 2 - Math.PI / 2;
                return (
                  <motion.span key={x.key} className={`absolute flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br ${x.tone} text-white shadow-lg ring-2 ring-hg-bg`}
                    style={{ left: `calc(50% + ${Math.cos(a) * 88}px - 18px)`, top: `calc(50% + ${Math.sin(a) * 88}px - 18px)` }}
                    animate={reduce ? undefined : { rotate: 360 }} transition={{ duration: 22, ease: "linear", repeat: Infinity }}>
                    <x.icon size={15} />
                  </motion.span>
                );
              })}
            </motion.div>
          </div>
          <Eyebrow>{t("trust.eyebrow")}</Eyebrow>
          <SplitTitle text={t("trust.title")} className="mt-4" />
          <p className="mx-auto mt-3 max-w-md text-base text-muted2 lg:mx-0">{t("journey.sub")}</p>
        </motion.div>

        {/* commitment cards */}
        <ol className="grid gap-3 sm:grid-cols-2 sm:gap-4">
          {TRUST.map((x, i) => (
            <motion.li key={x.key} data-testid={`trust-${i + 1}`}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: 28, rotateX: -12 }} whileInView={{ opacity: 1, y: 0, rotateX: 0 }} viewport={VIEW}
              transition={{ duration: 0.6, delay: at(0.15 + i * 0.13), ease: EASE }} whileHover={reduce ? undefined : { y: -6 }}
              style={{ transformPerspective: 900 }}
              className={`hg-card group relative overflow-hidden p-6 transition-[border-color,box-shadow] duration-500 hover:border-hg-lavender/40 hover:shadow-[0_24px_48px_-20px_rgba(139,61,255,0.55)] ${i % 2 ? "sm:translate-y-6" : ""}`}>
              <span className="pointer-events-none absolute -bottom-5 right-3 font-display text-7xl font-bold text-white/[0.05] transition-colors duration-500 group-hover:text-hg-lavender/10">0{i + 1}</span>
              <span className={`relative flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br ${x.tone} text-white shadow-lg transition-transform duration-500 group-hover:-rotate-6 group-hover:scale-110`}>
                <x.icon size={22} />
              </span>
              <div className="relative mt-4 font-display text-lg font-semibold text-ink">{t(`${x.key}.t`)}</div>
              <p className="relative mt-1.5 text-sm leading-relaxed text-muted2">{t(`${x.key}.d`)}</p>
              <motion.span aria-hidden className={`absolute bottom-0 left-0 h-[3px] bg-gradient-to-r ${x.tone}`}
                initial={{ width: reduce ? "100%" : "0%" }} whileInView={{ width: "100%" }} viewport={VIEW}
                transition={{ duration: 0.9, delay: at(0.45 + i * 0.13), ease: EASE }} />
            </motion.li>
          ))}
        </ol>
      </div>
    </section>
  );
}

/* ------------------------------------------------------------------------------------------------
 * Closing call to action: animated gradient border, drifting light, word-by-word headline and a
 * Shop → Share → Sell → Earn rail that slides in along a self-drawing line.
 * ---------------------------------------------------------------------------------------------- */
const RAIL = [
  { key: "how.shop", icon: ShoppingCart, tone: "from-hg-violet to-[#B36BFF]" },
  { key: "how.share", icon: Users, tone: "from-[#5B7CFF] to-[#8FA6FF]" },
  { key: "how.sell", icon: ClipboardCheck, tone: "from-[#2BB98A] to-hg-success" },
  { key: "how.earn", icon: IndianRupee, tone: "from-[#E0A92E] to-hg-gold" },
];

export function ClosingCTA({ t, navigate }) {
  const reduce = useReducedMotion();
  const at = (d) => (reduce ? 0 : d);
  const words = t("cta.closingTitle").split(" ");
  return (
    <section className="relative mx-auto w-full max-w-6xl px-4 py-16 sm:px-8 lg:py-24">
      <motion.div initial={{ opacity: 0, y: reduce ? 0 : 30, scale: reduce ? 1 : 0.97 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={VIEW}
        transition={{ duration: 0.8, ease: EASE }} className="relative rounded-[2.2rem] p-[1.5px]">
        {/* rotating gradient border */}
        <span aria-hidden className="absolute inset-0 overflow-hidden rounded-[2.2rem]">
          <motion.span className="absolute -inset-[60%]" style={{ background: "conic-gradient(from 0deg, #8B3DFF, #ED9BEA, #F2CB4B, #8B3DFF 40%, transparent 60%, #8B3DFF)" }}
            animate={reduce ? undefined : { rotate: 360 }} transition={{ duration: 8, ease: "linear", repeat: Infinity }} />
        </span>

        <div className="hg-hero relative overflow-hidden rounded-[2.15rem] px-6 py-12 sm:px-12 lg:py-14">
          {/* drifting lights */}
          <motion.span aria-hidden className="hg-orb left-[-8%] top-[-20%] h-72 w-72 bg-hg-pink/30"
            animate={reduce ? undefined : { x: [0, 60, 0], y: [0, 30, 0] }} transition={{ duration: 12, repeat: Infinity, ease: "easeInOut" }} />
          <motion.span aria-hidden className="hg-orb bottom-[-30%] right-[10%] h-80 w-80 bg-[#5B7CFF]/25"
            animate={reduce ? undefined : { x: [0, -50, 0], y: [0, -20, 0] }} transition={{ duration: 14, repeat: Infinity, ease: "easeInOut" }} />

          <div className="relative grid items-center gap-10 lg:grid-cols-[1.3fr_1fr]">
            <div className="min-w-0 text-center lg:text-left">
              <motion.span initial={{ opacity: 0, y: reduce ? 0 : 10 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ delay: at(0.2) }}
                className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-white ring-1 ring-white/25">
                <Sparkles size={13} className="text-hg-gold" /> {t("brand.tagline")}
              </motion.span>
              <motion.h2 className="mt-5 font-display text-3xl font-bold leading-tight text-white sm:text-5xl" initial="hidden" whileInView="show" viewport={VIEW}>
                {words.map((w, i) => (
                  <span key={i} className="-mt-[0.2em] inline-block overflow-hidden pb-1 pt-[0.2em] align-bottom">
                    <motion.span className={`inline-block ${i >= words.length - 1 ? "text-hg-gold" : ""}`}
                      variants={{ hidden: { y: reduce ? 0 : "110%", opacity: reduce ? 0 : 1 },
                        show: { y: 0, opacity: 1, transition: { duration: 0.6, delay: at(0.3 + i * 0.08), ease: EASE } } }}>{w}&nbsp;</motion.span>
                  </span>
                ))}
              </motion.h2>
              <motion.p initial={{ opacity: 0 }} whileInView={{ opacity: 1 }} viewport={VIEW} transition={{ delay: at(0.75) }}
                className="mx-auto mt-4 max-w-xl text-base text-white/85 sm:text-lg lg:mx-0">{t("cta.closingSub")}</motion.p>
              <motion.div initial={{ opacity: 0, y: reduce ? 0 : 12 }} whileInView={{ opacity: 1, y: 0 }} viewport={VIEW} transition={{ delay: at(0.9) }}
                className="mt-8 flex flex-wrap justify-center gap-3 lg:justify-start">
                <motion.div {...pressable}>
                  <Button onClick={() => navigate("/register")} className="btn-gold hg-sheen h-14 rounded-full px-7 text-base font-semibold" data-testid="closing-register-btn">
                    {t("cta.joinGenie")} <ArrowRight size={18} />
                  </Button>
                </motion.div>
                <motion.div {...pressable}>
                  <Button onClick={() => navigate("/login")} variant="outline" className="btn-glass h-14 rounded-full px-7 text-base font-semibold" data-testid="closing-browse-btn">
                    {t("cta.exploreProducts")}
                  </Button>
                </motion.div>
              </motion.div>
            </div>

            {/* step rail */}
            <ol className="relative mx-auto w-full min-w-0 max-w-sm space-y-3">
              <motion.span aria-hidden className="absolute bottom-6 left-[1.6rem] top-6 w-[2px] origin-top rounded-full bg-gradient-to-b from-white/60 to-white/10"
                initial={{ scaleY: reduce ? 1 : 0 }} whileInView={{ scaleY: 1 }} viewport={VIEW} transition={{ duration: 1.2, delay: at(0.5), ease: "easeInOut" }} />
              {RAIL.map((r, i) => (
                <motion.li key={r.key} initial={{ opacity: 0, x: reduce ? 0 : 40 }} whileInView={{ opacity: 1, x: 0 }} viewport={VIEW}
                  transition={{ duration: 0.55, delay: at(0.55 + i * 0.18), ease: EASE }} whileHover={reduce ? undefined : { x: -4 }}
                  className="relative flex min-w-0 items-center gap-3 rounded-2xl bg-white/10 p-2.5 pr-4 ring-1 ring-white/20 backdrop-blur-md">
                  <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${r.tone} text-white shadow-lg`}><r.icon size={18} /></span>
                  <span className="min-w-0">
                    <span className="block font-display text-sm font-semibold text-white">{i + 1}. {t(`${r.key}.t`)}</span>
                    <span className="block truncate text-xs text-white/70">{t(`${r.key}.d`)}</span>
                  </span>
                </motion.li>
              ))}
            </ol>
          </div>
        </div>
      </motion.div>
    </section>
  );
}

/* ------------------------------------------------------------------------------------------------
 * Footer: glowing top line that draws, staggered columns with underline hovers, a giant faint
 * wordmark and a back-to-top button. All links/testids are preserved.
 * ---------------------------------------------------------------------------------------------- */
function FootLink({ to, href, children, testid, Link }) {
  const cls = "group relative inline-block text-muted2 transition-colors hover:text-ink";
  const line = <span className="absolute -bottom-0.5 left-0 h-px w-0 bg-gradient-to-r from-hg-violet to-hg-pink transition-all duration-300 group-hover:w-full" />;
  return to
    ? <Link to={to} className={cls} data-testid={testid}>{children}{line}</Link>
    : <a href={href} className={cls}>{children}{line}</a>;
}

export function SiteFooter({ t, Link, Logo }) {
  const reduce = useReducedMotion();
  const cols = [
    { title: t("footer.shop"), links: ["pillar.sarees", "pillar.fashion", "pillar.beauty", "pillar.household"].map((k) => ({ label: t(`${k}.t`), to: "/login" })) },
    { title: t("footer.company"), links: [
      { label: t("footer.aboutUs"), href: "#about" }, { label: t("how.title"), href: "#how-it-works" },
      { label: t("faq.title"), href: "#faq" }, { label: t("nav.support"), to: "/legal/support" },
      { label: t("nav.becomeVendor"), to: "/vendor/register", testid: "footer-become-vendor" }, { label: t("login.vendorLink"), to: "/vendor/login" }] },
    { title: t("footer.policies"), links: [
      { label: t("legal.terms"), to: "/legal/terms", testid: "footer-terms" }, { label: t("legal.privacy"), to: "/legal/privacy", testid: "footer-privacy" },
      { label: t("legal.returns"), to: "/legal/returns", testid: "footer-returns" }, { label: t("legal.refunds"), to: "/legal/refunds", testid: "footer-refunds" }] },
  ];
  const toTop = () => window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });

  return (
    <footer className="relative mt-8 overflow-hidden border-t border-white/5 bg-gradient-to-b from-transparent to-hg-bg2/60" data-testid="site-footer">
      {/* glowing line draws across the top */}
      <motion.span aria-hidden className="absolute left-0 top-0 h-px w-full origin-center bg-gradient-to-r from-transparent via-hg-lavender to-transparent"
        initial={{ scaleX: reduce ? 1 : 0 }} whileInView={{ scaleX: 1 }} viewport={{ once: true }} transition={{ duration: 1.4, ease: EASE }} />
      <span aria-hidden className="absolute left-1/2 top-0 h-24 w-2/3 -translate-x-1/2 bg-hg-violet/20 blur-3xl" />

      <div className="relative mx-auto grid max-w-6xl gap-10 px-4 pb-10 pt-14 sm:grid-cols-2 sm:px-8 lg:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <motion.div initial={{ opacity: 0, y: reduce ? 0 : 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 0.5, ease: EASE }}>
          <Logo size="md" />
          <p className="mt-4 max-w-xs text-sm leading-relaxed text-muted2">{t("footer.about")}</p>
          <div className="hg-script mt-5 -rotate-3 text-xl text-hg-lavender">{t("landing.empowered")} <Heart size={13} className="inline text-hg-pink" fill="currentColor" /></div>
        </motion.div>
        {cols.map((c, ci) => (
          <motion.div key={c.title} initial={{ opacity: 0, y: reduce ? 0 : 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
            transition={{ duration: 0.5, delay: reduce ? 0 : 0.1 + ci * 0.1, ease: EASE }}>
            <div className="font-display text-sm font-semibold uppercase tracking-wider text-ink">{c.title}</div>
            <span className="mt-2 block h-0.5 w-8 rounded-full bg-gradient-to-r from-hg-violet to-hg-pink" />
            <ul className="mt-4 space-y-2.5 text-sm">
              {c.links.map((l) => <li key={l.label}><FootLink Link={Link} to={l.to} href={l.href} testid={l.testid}>{l.label}</FootLink></li>)}
            </ul>
          </motion.div>
        ))}
      </div>

      {/* giant faint wordmark */}
      <motion.div aria-hidden initial={{ opacity: 0, y: reduce ? 0 : 30 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ duration: 1, ease: EASE }}
        className="pointer-events-none relative select-none overflow-hidden px-4 text-center font-display text-[17vw] font-bold leading-[0.8] tracking-tighter text-transparent sm:text-[12vw] lg:text-[9.5rem]"
        style={{ WebkitTextStroke: "1px rgba(198,155,255,0.18)", backgroundImage: "linear-gradient(180deg, rgba(139,61,255,0.18), transparent 85%)", WebkitBackgroundClip: "text", backgroundClip: "text" }}>
        HOME GENIES
      </motion.div>

      <div className="relative border-t border-white/10">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-5 text-xs text-muted2 sm:px-8">
          <span>© {new Date().getFullYear()} HOME GENIES — {t("brand.tagline")}</span>
          <div className="flex items-center gap-4">
            <span data-testid="powered-by">
              Powered by{" "}
              <a href="https://verticalways.in" target="_blank" rel="noopener noreferrer" className="font-semibold text-hg-lavender hover:text-ink hover:underline">
                Vertical Ways
              </a>
            </span>
            <motion.button {...pressable} onClick={toTop} aria-label="Back to top" data-testid="back-to-top"
              className="flex h-10 w-10 items-center justify-center rounded-full bg-white/[0.06] text-ink ring-1 ring-white/15 hover:bg-hg-violet/40">
              <ArrowUp size={16} />
            </motion.button>
          </div>
        </div>
      </div>
    </footer>
  );
}
