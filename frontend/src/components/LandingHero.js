import React from "react";
import { motion, useReducedMotion } from "framer-motion";
import {
  ArrowRight, Sparkles, Smartphone, Clock, ShoppingBag, Eye,
  Search, Home, Gift, User, Heart, ShoppingCart, Users, ClipboardCheck, IndianRupee,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { pressable } from "@/components/motion";

/*
 * Landing hero + "How it works", animated as one timed sequence:
 *   0.00s banner photo settles in
 *   0.15s eyebrow pill
 *   0.30s headline, line by line (masked slide-up), then the highlight underline draws
 *   0.95s paragraph → 1.10s buttons → 1.25s benefit row (staggered)
 *   0.70s phone mockup slides up → 1.35s+ glass cards pop out of it one by one
 *   1.90s handwritten note + arrow draws
 * Everything collapses to a plain fade when the visitor prefers reduced motion.
 */

const EASE = [0.16, 1, 0.3, 1];
const PILLARS = [
  { key: "pillar.sarees", img: "/brand/pillar-sarees.jpg" },
  { key: "pillar.fashion", img: "/brand/pillar-fashion.jpg" },
  { key: "pillar.beauty", img: "/brand/pillar-beauty.jpg" },
  { key: "pillar.household", img: "/brand/pillar-household.jpg" },
];
const BENEFITS = [
  { key: "why.1", icon: Smartphone },
  { key: "why.2", icon: Clock },
  { key: "why.3", icon: ShoppingBag },
  { key: "why.4", icon: Eye },
];
const STEPS = [
  { key: "how.shop", icon: ShoppingCart, tone: "bg-hg-violet text-white" },
  { key: "how.share", icon: Users, tone: "bg-[#5B7CFF] text-white" },
  { key: "how.sell", icon: ClipboardCheck, tone: "bg-hg-success text-hg-bg" },
  { key: "how.earn", icon: IndianRupee, tone: "bg-hg-gold text-hg-deep" },
];
const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

/** Entrance props for one step of the sequence. */
function useEnter() {
  const reduce = useReducedMotion();
  return (delay, from = { opacity: 0, y: 18 }, duration = 0.6) =>
    reduce
      ? { initial: { opacity: 0 }, animate: { opacity: 1 }, transition: { duration: 0.25 } }
      : { initial: from, animate: { opacity: 1, x: 0, y: 0, scale: 1, rotate: 0 }, transition: { duration, delay, ease: EASE } };
}

/** Splits "Shop smart. Sell proudly. Establish yourself." into lines; the middle line is highlighted. */
function HeroTitle({ text, lang }) {
  const reduce = useReducedMotion();
  const lines = text.split(/(?<=[.।!?])\s+/).filter(Boolean);
  const hl = lines.length >= 3 ? 1 : -1;
  return (
    <h1 className={`mt-5 font-display text-[2.6rem] font-bold tracking-tight text-ink sm:text-6xl lg:text-[4.1rem] ${lang === "hi" ? "leading-[1.3]" : "leading-[1.06]"}`}>
      {lines.map((line, i) => (
        <span key={i} className="-mt-[0.2em] block overflow-hidden pb-1 pt-[0.2em]">
          <motion.span className={`relative inline-block ${i === hl ? "hg-gradient-text -mt-[0.25em] pt-[0.25em]" : ""}`}
            initial={reduce ? { opacity: 0 } : { y: "105%" }} animate={reduce ? { opacity: 1 } : { y: 0 }}
            transition={{ duration: 0.75, delay: reduce ? 0 : 0.3 + i * 0.13, ease: EASE }}>
            {line}
            {i === hl && (
              <svg aria-hidden viewBox="0 0 300 14" preserveAspectRatio="none" className="absolute -bottom-1.5 left-0 h-3 w-full">
                <motion.path d="M3 9 C 70 2, 160 2, 297 8" fill="none" stroke="url(#hg-ul)" strokeWidth="4" strokeLinecap="round"
                  initial={{ pathLength: reduce ? 1 : 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.7, delay: reduce ? 0 : 0.95, ease: "easeInOut" }} />
                <defs><linearGradient id="hg-ul" x1="0" x2="1"><stop offset="0" stopColor="#8B3DFF" /><stop offset="1" stopColor="#ED9BEA" /></linearGradient></defs>
              </svg>
            )}
          </motion.span>
        </span>
      ))}
    </h1>
  );
}

/** Phone mockup that renders the real catalogue (no invented items). */
function PhoneMock({ t, products, name }) {
  return (
    <div className="w-[230px] rounded-[2.2rem] bg-gradient-to-b from-[#3B1A73] to-[#1C0C38] p-[7px] shadow-[0_30px_70px_-20px_rgba(139,61,255,0.75)] ring-1 ring-white/25">
      <div className="relative overflow-hidden rounded-[1.8rem] bg-[#FBF9FD] text-[#1B1024]">
        <div className="absolute left-1/2 top-1.5 h-4 w-20 -translate-x-1/2 rounded-full bg-[#1C0C38]" />
        <div className="px-3.5 pb-3 pt-7">
          <div className="flex items-center gap-1.5">
            <img src="/brand/logo-icon.png" alt="" className="h-5 w-5 rounded-md" />
            <span className="text-[10px] font-bold tracking-tight">HOME <span className="text-[#8B3DFF]">GENIES</span></span>
          </div>
          <div className="mt-2.5 text-[13px] font-bold">{t("dash.greeting")} 👋</div>
          <div className="mt-2 flex items-center gap-1.5 rounded-full bg-[#F1EAFB] px-2.5 py-1.5 text-[9px] text-[#7A6E8C]"><Search size={10} /> {t("common.search")}…</div>
          <div className="mt-3 grid grid-cols-4 gap-1.5">
            {PILLARS.map((p) => (
              <div key={p.key} className="text-center">
                <img src={p.img} alt="" className="mx-auto h-9 w-9 rounded-full object-cover ring-2 ring-[#EDE4FF]" />
                <div className="mt-1 truncate text-[7.5px] font-medium text-[#4B3B60]">{t(`${p.key}.t`)}</div>
              </div>
            ))}
          </div>
          {products.length > 0 ? (
            <>
              <div className="mt-3 text-[10px] font-bold">{t("landing.featured")}</div>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                {products.slice(0, 2).map((p) => (
                  <div key={p.id} className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-[#EDE4FF]">
                    <div className="aspect-[4/3] bg-[#F1EAFB]">{p.images?.[0] && <img src={p.images[0]} alt="" className="h-full w-full object-cover" />}</div>
                    <div className="p-1.5">
                      <div className="truncate text-[8px] font-semibold">{name(p)}</div>
                      <div className="text-[9px] font-bold text-[#8B3DFF]">{inr(p.selling_price)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="mt-3 text-[10px] font-bold">{t("pillars.eyebrow")}</div>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                {PILLARS.slice(0, 2).map((p) => (
                  <div key={p.key} className="overflow-hidden rounded-xl bg-white shadow-sm ring-1 ring-[#EDE4FF]">
                    <div className="aspect-[4/3] bg-[#F1EAFB]"><img src={p.img} alt="" className="h-full w-full object-cover" /></div>
                    <div className="truncate p-1.5 text-[8px] font-semibold">{t(`${p.key}.t`)}</div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
        <div className="flex justify-around border-t border-[#EDE4FF] bg-white px-2 py-2 text-[#7A6E8C]">
          <Home size={13} className="text-[#8B3DFF]" /><ShoppingBag size={13} /><Gift size={13} /><User size={13} />
        </div>
      </div>
    </div>
  );
}

export function LandingHero({ t, lang, navigate, homeLink, products }) {
  const enter = useEnter();
  const reduce = useReducedMotion();
  const name = (p) => (lang === "hi" && p.name_hi ? p.name_hi : p.name);

  return (
    <section className="relative -mt-16 overflow-hidden pt-16" aria-label={t("hero.title")}>
      {/* 0.00s — banner photo (desktop: full-bleed right side, faded into the page) */}
      <motion.div {...enter(0, { opacity: 0, scale: 1.08 }, 1.3)}
        className="pointer-events-none absolute inset-y-0 right-0 hidden w-[58%] lg:block"
        style={{ WebkitMaskImage: "linear-gradient(to right, transparent 0%, #000 32%)", maskImage: "linear-gradient(to right, transparent 0%, #000 32%)" }}>
        <img src="/brand/hero.jpg" alt={t("hero.imgAlt")} className="h-full w-full object-cover object-[70%_center]" />
        <span className="absolute inset-0 bg-gradient-to-t from-hg-bg via-transparent to-hg-bg/40" />
      </motion.div>
      <span className="hg-orb left-[-10%] top-10 h-72 w-72 bg-hg-violet/35" />

      <div className="relative mx-auto grid max-w-6xl items-center gap-10 px-4 lg:gap-24 pb-14 pt-8 sm:px-8 lg:min-h-[640px] lg:grid-cols-[1.1fr_1fr] lg:pb-20 lg:pt-12">
        {/* ---- Text column ---- */}
        <div className="relative z-10 lg:-ml-[100px]">
          <motion.span {...enter(0.15, { opacity: 0, x: -16 })}
            className="inline-flex items-center gap-1.5 rounded-full bg-hg-violet/15 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wider text-hg-lavender ring-1 ring-hg-lavender/30">
            <Sparkles size={13} className="text-hg-gold" /> {t("brand.tagline")}
          </motion.span>

          <HeroTitle text={t("hero.title")} lang={lang} />

          <motion.p {...enter(0.95)} className="mt-6 max-w-xl text-base leading-relaxed text-muted2 sm:text-lg">{t("hero.sub")}</motion.p>

          <motion.div {...enter(1.1)} className="mt-8 flex flex-wrap gap-3">
            <motion.div {...pressable}>
              <Button onClick={() => navigate(homeLink)} className="hg-btn h-14 rounded-full px-7 text-base font-semibold" data-testid="hero-join-btn">
                {t("cta.joinGenie")} <ArrowRight size={18} />
              </Button>
            </motion.div>
            <motion.div {...pressable}>
              <Button onClick={() => navigate("/login")} variant="outline" className="btn-glass h-14 rounded-full px-7 text-base font-semibold text-ink" data-testid="hero-explore-btn">
                {t("cta.exploreProducts")}
              </Button>
            </motion.div>
          </motion.div>

          {/* 1.25s — benefit row, one after another */}
          <div className="mt-9 grid max-w-xl grid-cols-2 gap-2.5">
            {BENEFITS.map((b, i) => (
              <motion.div key={b.key} {...enter(1.25 + i * 0.1, { opacity: 0, y: 14 })} className="hg-tile flex min-w-0 items-center gap-2.5 px-3 py-2.5" data-testid={`hero-benefit-${i + 1}`}>
                <span className="hg-icon-chip !h-9 !w-9 !rounded-full"><b.icon size={16} /></span>
                <span className="min-w-0 break-words text-[13px] font-semibold leading-snug text-ink">{t(`${b.key}.t`)}</span>
              </motion.div>
            ))}
          </div>
          <motion.p {...enter(1.65, { opacity: 0 })} className="mt-6 text-xs text-muted2">{t("hero.note")}</motion.p>
        </div>

        {/* ---- Visual column ---- */}
        <div className="relative mx-auto h-[460px] w-full max-w-md sm:h-[520px] lg:max-w-none">
          {/* Mobile/tablet: the photo sits in a rounded frame behind the phone */}
          <motion.div {...enter(0, { opacity: 0, scale: 1.06 }, 1.1)} className="absolute inset-0 overflow-hidden rounded-[2rem] border border-white/15 lg:hidden">
            <img src="/brand/hero.jpg" alt={t("hero.imgAlt")} className="h-full w-full object-cover object-[72%_center]" data-testid="hero-image" />
            <span className="absolute inset-0 bg-gradient-to-t from-hg-bg/80 via-transparent to-transparent" />
          </motion.div>

          {/* 0.70s — phone slides up, then floats */}
          <motion.div {...enter(0.7, { opacity: 0, y: 70, rotate: -2 }, 0.9)} className="absolute left-3 top-8 z-10 origin-bottom-left scale-[0.82] sm:left-6 sm:scale-90 lg:left-[-3%] lg:top-6 lg:scale-100">
            <div style={{ transform: "rotate(-5deg)" }}>
              <div className={reduce ? "" : "hg-float-slow"}><PhoneMock t={t} products={products} name={name} /></div>
            </div>
          </motion.div>

          {/* 1.90s — handwritten note with a self-drawing arrow */}
          <motion.div {...enter(1.9, { opacity: 0, x: 12 })} className="absolute bottom-4 right-3 z-20 text-right lg:bottom-24 lg:right-[-4%]" aria-hidden>
            <div className="hg-script rotate-[-6deg] text-2xl leading-none text-white drop-shadow lg:text-[1.7rem]">{t("landing.moreThan")}</div>
            <svg viewBox="0 0 100 50" className="ml-auto mr-12 mt-1 h-10 w-24 text-hg-pink">
              <motion.path d="M92 6 Q 60 46 14 30 M14 30 L 27 25 M14 30 L 23 40" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
                initial={{ pathLength: reduce ? 1 : 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.9, delay: reduce ? 0 : 2.05, ease: "easeInOut" }} />
            </svg>
          </motion.div>
        </div>
      </div>

      {/* Bottom wave that draws in under the hero */}
      <svg aria-hidden viewBox="0 0 1440 90" preserveAspectRatio="none" className="pointer-events-none relative -mt-6 block h-14 w-full text-hg-violet sm:h-20">
        <motion.path d="M0 60 C 240 10, 480 90, 720 50 S 1200 20, 1440 55" fill="none" stroke="currentColor" strokeOpacity="0.55" strokeWidth="2"
          initial={{ pathLength: reduce ? 1 : 0 }} animate={{ pathLength: 1 }} transition={{ duration: 1.6, delay: reduce ? 0 : 1.2, ease: "easeInOut" }} />
      </svg>
    </section>
  );
}

/** "Shop. Share. Sell. Earn." — cards reveal left→right, each arrow draws before the next card. */
export function HowItWorks({ t }) {
  const reduce = useReducedMotion();
  const parts = t("how.title").split(/(?<=[.।])\s+/).filter(Boolean);
  const view = { once: true, margin: "-80px" };
  const at = (d) => (reduce ? 0 : d);

  return (
    <section id="how-it-works" className="relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8 lg:py-24">
      <div className="grid items-center gap-10 lg:grid-cols-[0.85fr_2fr]">
        <motion.div initial={{ opacity: 0, x: reduce ? 0 : -20 }} whileInView={{ opacity: 1, x: 0 }} viewport={view} transition={{ duration: 0.6, ease: EASE }}>
          <span className="inline-flex items-center gap-1.5 rounded-full bg-hg-violet/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-hg-lavender ring-1 ring-hg-lavender/25">
            <Sparkles size={12} /> {t("how.eyebrow")}
          </span>
          <h2 className="mt-4 font-display text-3xl font-bold leading-tight text-ink sm:text-4xl">
            {parts.map((p, i) => <span key={i} className={i === 2 ? "hg-gradient-text" : ""}>{p}{i < parts.length - 1 ? " " : ""}</span>)}
          </h2>
          <p className="mt-3 text-base text-muted2">{t("how.sub")}</p>
          <div className="hg-script mt-6 hidden -rotate-6 text-2xl text-hg-lavender lg:block">{t("landing.empowered")} <Heart size={16} className="inline text-hg-pink" fill="currentColor" /></div>
        </motion.div>

        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-6">
          {STEPS.map((s, i) => (
            <li key={s.key} className="relative">
              <motion.div initial={{ opacity: 0, y: reduce ? 0 : 22, scale: reduce ? 1 : 0.96 }} whileInView={{ opacity: 1, y: 0, scale: 1 }} viewport={view}
                transition={{ duration: 0.5, delay: at(i * 0.42), ease: EASE }} whileHover={reduce ? undefined : { y: -4 }}
                className="hg-card hg-lift h-full p-5" data-testid={`how-step-${i + 1}`}>
                <motion.span initial={{ scale: reduce ? 1 : 0, rotate: reduce ? 0 : -30 }} whileInView={{ scale: 1, rotate: 0 }} viewport={view}
                  transition={{ type: "spring", stiffness: 380, damping: 16, delay: at(i * 0.42 + 0.18) }}
                  className={`flex h-12 w-12 items-center justify-center rounded-full shadow-lg ${s.tone}`}><s.icon size={22} /></motion.span>
                <div className="mt-4 font-display text-base font-semibold text-ink">{i + 1}. {t(`${s.key}.t`)}</div>
                <p className="mt-1.5 text-sm leading-relaxed text-muted2">{t(`${s.key}.d`)}</p>
              </motion.div>
              {/* Arrow to the next step draws after this card lands */}
              {i < STEPS.length - 1 && (
                <svg aria-hidden viewBox="0 0 24 24" className="absolute -right-[1.15rem] top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 text-hg-lavender lg:block">
                  <motion.path d="M3 12 H 19 M13 6 L 19 12 L 13 18" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"
                    initial={{ pathLength: reduce ? 1 : 0, opacity: reduce ? 1 : 0 }} whileInView={{ pathLength: 1, opacity: 1 }} viewport={view}
                    transition={{ duration: 0.35, delay: at(i * 0.42 + 0.3) }} />
                </svg>
              )}
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
