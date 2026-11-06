import React, { useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight, BadgeCheck, Briefcase, ChevronRight, Coins, Crown, Gift, Headphones, Home as HomeIcon, IndianRupee, LogIn, Package,
  RotateCcw, Share2, ShieldCheck, ShoppingBag, ShoppingCart, Sparkles, Store, TrendingUp, Truck, UserPlus, Users,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { captureSellerRef } from "@/lib/sellerRef";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { homeRouteFor } from "@/lib/homeRoute";

const EASE = [0.16, 1, 0.3, 1];
const rise = { initial: { opacity: 0, y: 18 }, whileInView: { opacity: 1, y: 0 }, viewport: { once: true, margin: "-40px" }, transition: { duration: 0.55, ease: EASE } };

function Ornament({ children, sub }) {
  return (
    <motion.div {...rise} className="text-center">
      <div className="flex items-center justify-center gap-3 sm:gap-5">
        <span className="h-px w-10 bg-gradient-to-r from-transparent to-[#C9A13B] sm:w-24" />
        <span className="text-[#C9A13B]" aria-hidden>✦</span>
        <h2 className="font-serif text-2xl font-bold text-[#2B1A10] sm:text-[2rem]">{children}</h2>
        <span className="text-[#C9A13B]" aria-hidden>✦</span>
        <span className="h-px w-10 bg-gradient-to-l from-transparent to-[#C9A13B] sm:w-24" />
      </div>
      {sub && <p className="mt-2 text-sm text-[#6B5642] sm:text-base">{sub}</p>}
    </motion.div>
  );
}

export default function Landing() {
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const join = () => navigate(user ? homeRouteFor(user) : "/register");
  const shop = () => navigate(user ? "/app/products" : "/login");

  useEffect(() => { captureSellerRef(); }, []);

  const NAV = [["#top", HomeIcon, t("lp.nav.home")], ["#products", ShoppingBag, t("lp.nav.shop")], ["#how", Coins, t("lp.nav.earn")],
               ["#why", Users, t("lp.nav.business")], ["#support", Headphones, t("lp.nav.support")]];
  const PILLARS = [["pillar-sarees.jpg", "lp.p1"], ["pillar-fashion.jpg", "lp.p2"], ["pillar-beauty.jpg", "lp.p3"], ["pillar-household.jpg", "lp.p4"]];
  const STEPS = [[ShoppingCart, "lp.s1"], [Share2, "lp.s2"], [Coins, "lp.s3"]];
  const WHY = [[Crown, "lp.w1"], [Gift, "lp.w2"], [TrendingUp, "lp.w3"], [Headphones, "lp.w4"]];
  const TRUST = [[Users, "lp.t1"], [BadgeCheck, "lp.t2"], [Truck, "lp.t3"], [RotateCcw, "lp.t4"], [ShieldCheck, "lp.t5"]];

  return (
    <div id="top" className="min-h-screen overflow-x-hidden bg-[#FBF6EC] text-[#2B1A10]" data-testid="landing-page"
         style={{ backgroundImage: "radial-gradient(1100px 520px at 85% -5%, #F6E3C4 0%, transparent 60%), radial-gradient(900px 500px at 0% 30%, #FFF6E4 0%, transparent 60%)" }}>
      {/* ---------- Header ---------- */}
      <header className="sticky top-0 z-40 border-b border-[#C9A13B]/20 bg-[#FBF6EC]/90 backdrop-blur-md" style={{ top: "env(safe-area-inset-top, 0px)" }}>
        <div className="mx-auto flex h-[72px] max-w-6xl items-center justify-between gap-2 px-4 sm:px-6">
          <Link to="/" aria-label="HOME GENIES home" data-testid="header-logo"><Logo size="md" className="hidden sm:inline-flex" /><Logo size="sm" className="sm:hidden" tagline={false} /></Link>
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Sections">
            {NAV.map(([href, Icon, label], i) => (
              <a key={href} href={href} className={`inline-flex h-10 items-center gap-1.5 rounded-full px-3.5 text-sm font-medium transition-colors ${i === 0 ? "bg-[#3B2417] text-[#FBF1DA] shadow-md" : "text-[#3B2417] hover:bg-[#F4E6C6]"}`}>
                <Icon size={15} aria-hidden /> {label}
              </a>
            ))}
          </nav>
          <div className="flex items-center gap-1.5 sm:gap-2.5">
            <LanguageSwitcher />
            {(user?.role === "vendor" || user?.role === "vendor_staff") && (
              <Link to="/vendor" className="hidden h-10 items-center rounded-full border-[1.5px] border-[#C9A13B] bg-[#FFFDF8] px-4 text-sm font-semibold text-[#3B2417] sm:inline-flex" data-testid="header-vendor-panel">{t("vp.portal")}</Link>
            )}
            <Link to="/login" className="inline-flex h-10 items-center gap-1.5 rounded-full border-[1.5px] border-[#3B2417]/70 bg-[#FFFDF8] px-4 text-sm font-semibold text-[#3B2417] transition hover:bg-[#F4E6C6]" data-testid="header-login">
              <LogIn size={15} className="sm:hidden" aria-hidden /><span>{t("lp.nav.login")}</span>
            </Link>
            <button type="button" onClick={join} className="hg-btn hidden h-10 items-center rounded-full px-4 text-sm font-semibold sm:inline-flex" data-testid="header-join">{t("lp.nav.join")}</button>
          </div>
        </div>
      </header>

      {/* ---------- Hero ---------- */}
      <section className="mx-auto max-w-6xl px-4 pt-6 sm:px-6 lg:pt-10">
        <div className="relative overflow-hidden rounded-[2rem] bg-gradient-to-br from-[#FFF8EC] via-[#F9EEDB] to-[#F1DFC2] ring-1 ring-[#C9A13B]/25 shadow-[0_30px_60px_-40px_rgba(59,36,23,0.6)]">
          <div className="grid items-center lg:grid-cols-[1.12fr_1fr]">
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: EASE }} className="relative z-10 p-6 sm:p-10 lg:py-14 lg:pl-12 lg:pr-4">
              <span className="inline-flex items-center gap-1.5 rounded-md bg-gradient-to-r from-[#C08A3E] to-[#9A6A33] px-3 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-[#FFF7E6] shadow-sm">
                <Sparkles size={12} aria-hidden /> {t("lp.badge")}
              </span>
              <h1 className="mt-5 font-serif text-[2.4rem] font-extrabold leading-[1.08] sm:text-5xl lg:whitespace-nowrap lg:text-[2.85rem] xl:text-[3.1rem]" data-testid="hero-title">
                <span className="block text-[#2B1A10]">{t("lp.h1")}</span>
                <span className="block text-[#A8562F]">{t("lp.h2")}</span>
                <span className="block text-[#A8562F]">{t("lp.h3")}</span>
              </h1>
              <p className="mt-4 max-w-md text-[15px] leading-relaxed text-[#4A2E1E]">{t("lp.sub")}</p>
              <div className="mt-6 flex flex-col gap-3 sm:flex-row">
                <button type="button" onClick={join} className="hg-btn inline-flex h-[52px] items-center justify-center gap-2 rounded-full px-6 text-[15px] font-semibold" data-testid="hero-join">
                  <UserPlus size={18} aria-hidden /> {t("lp.cta1")} <ArrowRight size={17} aria-hidden />
                </button>
                <button type="button" onClick={shop} className="inline-flex h-[52px] items-center justify-center gap-2 rounded-full border-[1.5px] border-[#C9A13B] bg-[#FFFDF8] px-6 text-[15px] font-semibold text-[#3B2417] shadow-sm transition hover:bg-[#FBF1DA]" data-testid="hero-explore">
                  <ShoppingCart size={18} aria-hidden /> {t("lp.cta2")}
                </button>
              </div>
              <div className="mt-7 grid max-w-lg grid-cols-4 divide-x divide-[#C9A13B]/35">
                {[[Truck, "lp.f1"], [ShieldCheck, "lp.f2"], [IndianRupee, "lp.f3"], [Package, "lp.f4"]].map(([Icon, k]) => (
                  <div key={k} className="flex flex-col items-center gap-1.5 px-1 text-center">
                    <Icon size={22} className="text-[#3B2417]" aria-hidden />
                    <span className="text-[11px] font-medium leading-tight text-[#4A2E1E] sm:text-xs">{t(k)}</span>
                  </div>
                ))}
              </div>
            </motion.div>
            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.7, ease: EASE, delay: 0.1 }} className="relative h-72 sm:h-96 lg:h-full lg:min-h-[480px]">
              <img src="/brand/hero.jpg" alt={t("lp.heroAlt")} className="absolute inset-0 h-full w-full object-cover object-[80%_center]" />
              <div className="absolute inset-0 bg-gradient-to-r from-[#F9EEDB] via-[#F9EEDB]/10 to-transparent lg:via-transparent" aria-hidden />
              <div className="absolute right-4 top-4 w-36 rounded-2xl border border-[#DDB862] bg-gradient-to-b from-[#4A2E1E] to-[#2B1A10] p-3 text-center shadow-xl sm:right-6 sm:top-6 sm:w-44 sm:p-4" data-testid="hero-ribbon">
                <Crown size={22} className="mx-auto text-[#EAD394]" aria-hidden />
                <p className="mt-1.5 font-serif text-[13px] font-semibold leading-snug text-[#FBF1DA] sm:text-[15px]">{t("lp.ribbon")}</p>
              </div>
            </motion.div>
          </div>
        </div>
      </section>

      {/* ---------- Product world ---------- */}
      <section id="products" className="mx-auto max-w-6xl scroll-mt-24 px-4 pt-14 sm:px-6">
        <Ornament sub={t("lp.worldSub")}>{t("lp.world")}</Ornament>
        <div className="mt-7 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="product-world">
          {PILLARS.map(([img, k], i) => (
            <motion.button key={k} type="button" onClick={shop} {...rise} transition={{ ...rise.transition, delay: i * 0.06 }}
              className="group flex items-center gap-3 rounded-2xl border border-[#C9A13B]/30 bg-[#FFFDF8] p-3 text-left shadow-[0_14px_30px_-22px_rgba(59,36,23,0.6)] transition hover:-translate-y-1 hover:shadow-[0_20px_36px_-22px_rgba(59,36,23,0.7)]">
              <img src={`/brand/${img}`} alt="" className="h-20 w-20 shrink-0 rounded-xl object-cover" loading="lazy" />
              <span className="min-w-0 flex-1">
                <span className="block font-semibold leading-tight text-[#2B1A10]">{t(`${k}.t`)}</span>
                <span className="mt-0.5 block text-xs text-[#6B5642]">{t(`${k}.s`)}</span>
              </span>
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-[#C08A3E] to-[#8A5A2B] text-white shadow transition group-hover:translate-x-0.5"><ArrowRight size={16} aria-hidden /></span>
            </motion.button>
          ))}
        </div>
      </section>

      {/* ---------- How it works ---------- */}
      <section id="how" className="mx-auto max-w-6xl scroll-mt-24 px-4 pt-12 sm:px-6">
        <motion.div {...rise} className="hg-violet relative overflow-hidden rounded-[1.75rem] p-6 sm:p-8">
          <div className="grid items-center gap-6 lg:grid-cols-[0.8fr_3fr]">
            <h2 className="font-serif text-3xl font-bold leading-tight text-[#FBF1DA] lg:border-r lg:border-[#DDB862]/35 lg:pr-6">
              {t("lp.howTitle")} <Sparkles size={18} className="inline text-[#EAD394]" aria-hidden />
            </h2>
            <ol className="grid gap-4 md:grid-cols-[1fr_auto_1fr_auto_1fr] md:items-center">
              {STEPS.map(([Icon, k], i) => (
                <React.Fragment key={k}>
                  <li className="flex items-center gap-3 rounded-full bg-[#FBF1DA] p-2 pr-5 shadow-inner">
                    <span className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-b from-[#8A3B2B] to-[#5A2318] text-[#FBF1DA] ring-4 ring-[#EAD394]/60">
                      <Icon size={22} aria-hidden />
                      <span className="absolute -left-1 -top-1 flex h-6 w-6 items-center justify-center rounded-full bg-[#EAD394] text-xs font-extrabold text-[#2B1A10]">{i + 1}</span>
                    </span>
                    <span><span className="block font-bold text-[#2B1A10]">{t(`${k}.t`)}</span><span className="block text-xs leading-snug text-[#5C3A26]">{t(`${k}.s`)}</span></span>
                  </li>
                  {i < STEPS.length - 1 && <span className="hidden text-2xl font-bold text-[#EAD394] md:block" aria-hidden>»</span>}
                </React.Fragment>
              ))}
            </ol>
          </div>
        </motion.div>
      </section>

      {/* ---------- Why choose ---------- */}
      <section id="why" className="mx-auto max-w-6xl scroll-mt-24 px-4 pt-14 sm:px-6">
        <Ornament>{t("lp.whyTitle")}</Ornament>
        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {WHY.map(([Icon, k]) => (
            <motion.div key={k} {...rise} className="flex items-center gap-3 rounded-2xl border border-[#C9A13B]/30 bg-[#FFFDF8] p-4 shadow-[0_12px_26px_-22px_rgba(59,36,23,0.6)]">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-[#FBF1DA] text-[#A9842A] ring-1 ring-[#C9A13B]/40"><Icon size={24} aria-hidden /></span>
              <span><span className="block font-semibold text-[#2B1A10]">{t(`${k}.t`)}</span><span className="block text-xs text-[#6B5642]">{t(`${k}.s`)}</span></span>
            </motion.div>
          ))}
        </div>
      </section>

      {/* ---------- Collections ---------- */}
      <section className="mx-auto grid max-w-6xl gap-4 px-4 pt-10 sm:px-6 md:grid-cols-3">
        {[["lp.c1", "pillar-sarees.jpg", "bg-gradient-to-br from-[#3B2417] to-[#5C3A26]", "text-[#FBF1DA]", "text-[#E9D9BC]", "btn-gold"],
          ["lp.c2", "pillar-beauty.jpg", "bg-gradient-to-br from-[#FBE6DD] to-[#F4CFC0]", "text-[#2B1A10]", "text-[#5C3A26]", "hg-btn"],
          ["lp.c3", "pillar-household.jpg", "bg-gradient-to-br from-[#FBF3E3] to-[#EFDFC0]", "text-[#2B1A10]", "text-[#5C3A26]", "hg-btn"]].map(([k, img, bg, tt, st, btn]) => (
          <motion.div key={k} {...rise} className={`relative flex min-h-[180px] overflow-hidden rounded-[1.5rem] ring-1 ring-[#C9A13B]/30 shadow-[0_18px_34px_-24px_rgba(59,36,23,0.7)] ${bg}`}>
            <div className="relative z-10 flex flex-col justify-center gap-1 p-5 pr-2">
              <h3 className={`font-serif text-xl font-bold ${tt}`} style={{ fontFamily: "'Playfair Display', Georgia, serif" }}>{t(`${k}.t`)}</h3>
              <p className={`text-sm ${st}`}>{t(`${k}.s`)}</p>
              <button type="button" onClick={shop} className={`${btn} mt-3 inline-flex h-11 w-fit items-center gap-1.5 rounded-full px-5 text-sm font-semibold`}>{t(`${k}.b`)} <ArrowRight size={15} aria-hidden /></button>
            </div>
            <img src={`/brand/${img}`} alt="" loading="lazy" className="ml-auto w-[42%] shrink-0 object-cover" style={{ maskImage: "linear-gradient(90deg, transparent, #000 35%)", WebkitMaskImage: "linear-gradient(90deg, transparent, #000 35%)" }} />
          </motion.div>
        ))}
      </section>

      {/* ---------- Trust strip ---------- */}
      <section id="support" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-10 sm:px-6">
        <motion.div {...rise} className="flex flex-col gap-4 rounded-[1.5rem] border border-[#C9A13B]/30 bg-[#FFFDF8] p-4 shadow-[0_16px_34px_-26px_rgba(59,36,23,0.7)] lg:flex-row lg:items-center">
          <ul className="grid flex-1 grid-cols-2 gap-x-3 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
            {TRUST.map(([Icon, k]) => (
              <li key={k} className="flex items-center gap-2.5">
                <Icon size={24} className="shrink-0 text-[#A9842A]" aria-hidden />
                <span className="text-xs font-semibold leading-tight text-[#3B2417]">{t(k)}</span>
              </li>
            ))}
          </ul>
          <button type="button" onClick={join} className="hg-btn inline-flex min-h-[56px] items-center justify-between gap-3 rounded-full py-2 pl-2 pr-5 text-left text-sm font-semibold" data-testid="trust-join">
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-[#EAD394] text-[#2B1A10]"><Users size={19} aria-hidden /></span>
            <span className="max-w-[12rem] leading-snug">{t("lp.join")}</span>
            <ChevronRight size={20} aria-hidden />
          </button>
        </motion.div>
      </section>

      {/* ---------- Footer ---------- */}
      <footer className="border-t border-[#C9A13B]/25 bg-[#F4EAD7]">
        <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-8 sm:px-6 md:flex-row md:items-center md:justify-between">
          <Logo size="md" />
          <nav className="flex flex-wrap gap-x-5 gap-y-2 text-sm font-medium text-[#3B2417]" aria-label="Footer">
            <Link to="/vendor/apply" className="inline-flex items-center gap-1.5 hover:underline" data-testid="footer-vendor-apply"><Store size={15} aria-hidden /> {t("lp.sell")}</Link>
            <Link to="/vendor/login" className="inline-flex items-center gap-1.5 hover:underline"><Briefcase size={15} aria-hidden /> {t("login.vendorLink")}</Link>
            <Link to="/legal/terms" className="hover:underline">{t("legal.terms")}</Link>
            <Link to="/legal/privacy" className="hover:underline">{t("lp.privacy")}</Link>
          </nav>
          <p className="text-xs text-[#6B5642]">© {new Date().getFullYear()} HOME GENIES</p>
        </div>
      </footer>
    </div>
  );
}
