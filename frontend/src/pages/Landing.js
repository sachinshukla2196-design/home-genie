import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ArrowRight, Coins, Crown, Headphones, HelpCircle, Home as HomeIcon, IndianRupee, LogIn, Package, ShieldCheck, ShoppingBag, ShoppingCart,
  Sparkles, Truck, UserPlus, Users,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Stagger, StaggerItem, pressable } from "@/components/motion";
import { captureSellerRef } from "@/lib/sellerRef";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";
import { homeRouteFor } from "@/lib/homeRoute";
import { HowItWorks, PhoneMock } from "@/components/LandingHero";
import { PillarsSection, WhySection, DashboardPreviewSection, TrustSection, ClosingCTA, SiteFooter } from "@/components/LandingSections";



const FAQS = ["faq.1", "faq.2", "faq.3", "faq.4", "faq.5", "faq.6"];
const EASE = [0.16, 1, 0.3, 1];
const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

function Section({ id, children, className = "" }) {
  return (
    <section id={id} className={`relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-10 sm:px-8 lg:py-14 ${className}`}>
      {children}
    </section>
  );
}

function Eyebrow({ children }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-hg-violet/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-hg-lavender ring-1 ring-hg-lavender/25">
      <Sparkles size={12} /> {children}
    </span>
  );
}

/** Section heading that fades up when it scrolls into view. */
function Heading({ eyebrow, title, sub, center = false }) {
  return (
    <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }}
      transition={{ duration: 0.5, ease: EASE }} className={center ? "text-center" : ""}>
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{title}</h2>
      {sub && <p className={`mt-3 max-w-2xl text-base text-muted2 ${center ? "mx-auto" : ""}`}>{sub}</p>}
    </motion.div>
  );
}

export default function Landing() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const homeLink = user ? homeRouteFor(user) : "/register";
  const [products, setProducts] = useState([]);

  useEffect(() => { captureSellerRef(); }, []);
  useEffect(() => {
    API.get("/products").then(({ data }) => setProducts((data || []).slice(0, 4))).catch(() => setProducts([]));
  }, []);

  const name = (p) => (lang === "hi" && p.name_hi ? p.name_hi : p.name);
  const join = () => navigate(user ? homeRouteFor(user) : "/register");
  const shop = () => navigate(user ? "/app/products" : "/login");
  const NAV = [["#top", HomeIcon, t("lp.nav.home")], ["#categories", ShoppingBag, t("lp.nav.shop")], ["#how-it-works", Coins, t("lp.nav.earn")],
               ["#about", Users, t("lp.nav.business")], ["#faq", Headphones, t("lp.nav.support")]];

  return (
    <div id="top" className="min-h-screen overflow-x-hidden bg-background" data-testid="landing-page">
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

      {/* ---------- Hero: photo fading in from the right + the HOME GENIES app on a floating phone ---------- */}
      <section className="relative overflow-hidden bg-gradient-to-br from-[#FFF8EC] via-[#FBF1DF] to-[#F3E3C6]" data-testid="hero-full">
        <div className="pointer-events-none absolute inset-y-0 right-0 hidden w-[56%] lg:block"
             style={{ WebkitMaskImage: "linear-gradient(to right, transparent 0%, #000 30%)", maskImage: "linear-gradient(to right, transparent 0%, #000 30%)" }}>
          <img src="/brand/hero.jpg" alt={t("lp.heroAlt")} className="h-full w-full object-cover object-[72%_center]" />
          <span className="absolute inset-0 bg-gradient-to-t from-[#F3E3C6]/70 via-transparent to-transparent" />
        </div>
        <div className="relative mx-auto grid max-w-6xl items-center gap-8 px-4 py-8 sm:px-6 lg:min-h-[540px] lg:grid-cols-[1.05fr_1fr] lg:gap-6 lg:py-10">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, ease: EASE }} className="relative z-10">
            <span className="inline-flex w-fit items-center gap-1.5 rounded-md bg-gradient-to-r from-[#C08A3E] to-[#9A6A33] px-3 py-1 text-[11px] font-bold uppercase tracking-[0.14em] text-[#FFF7E6] shadow-sm">
              <Sparkles size={12} aria-hidden /> {t("lp.badge")}
            </span>
            <h1 className="mt-4 font-serif text-[2.3rem] font-extrabold leading-[1.08] sm:text-5xl lg:whitespace-nowrap lg:text-[2.8rem] xl:text-[3.05rem]" data-testid="hero-title">
              <span className="block text-[#2B1A10]">{t("lp.h1")}</span>
              <span className="block text-[#A8562F]">{t("lp.h2")}</span>
              <span className="block text-[#A8562F]">{t("lp.h3")}</span>
            </h1>
            <p className="mt-3 max-w-md text-[15px] leading-relaxed text-[#4A2E1E]">{t("lp.sub")}</p>
            <div className="mt-5 flex flex-col gap-3 sm:flex-row">
              <button type="button" onClick={join} className="hg-btn inline-flex h-[52px] items-center justify-center gap-2 rounded-full px-6 text-[15px] font-semibold" data-testid="hero-join">
                <UserPlus size={18} aria-hidden /> {t("lp.cta1")} <ArrowRight size={17} aria-hidden />
              </button>
              <button type="button" onClick={shop} className="inline-flex h-[52px] items-center justify-center gap-2 rounded-full border-[1.5px] border-[#C9A13B] bg-[#FFFDF8] px-6 text-[15px] font-semibold text-[#3B2417] shadow-sm transition hover:bg-[#FBF1DA]" data-testid="hero-explore">
                <ShoppingCart size={18} aria-hidden /> {t("lp.cta2")}
              </button>
            </div>
            <div className="mt-6 grid max-w-lg grid-cols-4 divide-x divide-[#C9A13B]/35">
              {[[Truck, "lp.f1"], [ShieldCheck, "lp.f2"], [IndianRupee, "lp.f3"], [Package, "lp.f4"]].map(([Icon, k]) => (
                <div key={k} className="flex flex-col items-center gap-1.5 px-1 text-center">
                  <Icon size={22} className="text-[#3B2417]" aria-hidden />
                  <span className="text-[11px] font-medium leading-tight text-[#4A2E1E] sm:text-xs">{t(k)}</span>
                </div>
              ))}
            </div>
          </motion.div>

          <div className="relative mx-auto h-[430px] w-full max-w-md sm:h-[480px] lg:max-w-none">
            {/* phones/tablets: the photo sits in a rounded frame behind the phone */}
            <div className="absolute inset-0 overflow-hidden rounded-[2rem] ring-1 ring-[#C9A13B]/30 lg:hidden">
              <img src="/brand/hero.jpg" alt={t("lp.heroAlt")} className="h-full w-full object-cover object-[75%_center]" data-testid="hero-image" />
              <span className="absolute inset-0 bg-gradient-to-t from-[#2B1A10]/35 via-transparent to-transparent" />
            </div>
            <motion.div initial={{ opacity: 0, y: 60, rotate: -2 }} animate={{ opacity: 1, y: 0, rotate: 0 }} transition={{ duration: 0.9, delay: 0.35, ease: EASE }}
              className="absolute left-3 top-6 z-10 origin-bottom-left scale-[0.8] sm:left-6 sm:scale-90 lg:left-[-2%] lg:top-4 lg:scale-[0.95]">
              <div style={{ transform: "rotate(-5deg)" }}><div className="hg-float-slow"><PhoneMock t={t} products={products} name={name} /></div></div>
            </motion.div>
            <motion.div initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6, delay: 0.6, ease: EASE }}
              className="absolute right-3 top-3 z-20 w-36 rounded-2xl border border-[#DDB862] bg-gradient-to-b from-[#4A2E1E] to-[#2B1A10] p-3 text-center shadow-xl sm:w-44 sm:p-4 lg:right-0 lg:top-2" data-testid="hero-ribbon">
              <Crown size={22} className="mx-auto text-[#EAD394]" aria-hidden />
              <p className="mt-1.5 font-serif text-[13px] font-semibold leading-snug text-[#FBF1DA] sm:text-[15px]">{t("lp.ribbon")}</p>
            </motion.div>
            <div className="absolute bottom-3 right-3 z-20 text-right lg:bottom-6 lg:right-0" aria-hidden>
              <div className="hg-script rotate-[-6deg] rounded-xl bg-[#FFFDF8]/85 px-3 py-1 text-2xl leading-none text-[#5C3A26] shadow-sm backdrop-blur-sm lg:text-[1.6rem]">{t("landing.moreThan")}</div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- Hero + How it works (sequenced entrance) ---------- */}
      <HowItWorks t={t} />

      {/* ---------- Four pillars (bento, wipe-in + tilt) ---------- */}
      <PillarsSection t={t} navigate={navigate} />

      {/* ---------- Featured products (real catalogue only) ---------- */}
      {products.length > 0 && (
        <Section id="featured" className="!pt-0">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <Heading eyebrow={t("nav.shop")} title={t("landing.featured")} sub={t("landing.productsSub")} />
            <Link to="/login" className="group inline-flex items-center gap-1 text-sm font-semibold text-hg-lavender">{t("cta.viewAll")} <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" /></Link>
          </div>
          <Stagger className="mt-8 grid grid-cols-2 gap-3 sm:gap-5 lg:grid-cols-4" data-testid="landing-featured">
            {products.map((p) => {
              const off = p.mrp > p.selling_price ? Math.round((1 - p.selling_price / p.mrp) * 100) : 0;
              return (
                <StaggerItem as="button" key={p.id} {...pressable} onClick={() => navigate("/login")} className="hg-card hg-lift group overflow-hidden text-left">
                  <div className="relative aspect-square overflow-hidden bg-brand-50">
                    {p.images?.[0] && <img src={p.images[0]} alt={name(p)} loading="lazy" className="h-full w-full object-cover transition-transform duration-700 group-hover:scale-110" />}
                    {off > 0 && <span className="hg-off-badge absolute right-2.5 top-2.5 rounded-lg px-2 py-0.5 text-xs font-bold">-{off}%</span>}
                  </div>
                  <div className="p-3.5 sm:p-4">
                    <div className="line-clamp-1 font-medium text-ink">{name(p)}</div>
                    <div className="mt-0.5 line-clamp-1 text-xs text-muted2">{p.category}</div>
                    <div className="mt-2 flex items-baseline gap-2">
                      <span className="font-display text-lg font-semibold text-hg-lavender">{inr(p.selling_price)}</span>
                      {off > 0 && <span className="text-xs text-muted2 line-through">{inr(p.mrp)}</span>}
                    </div>
                  </div>
                </StaggerItem>
              );
            })}
          </Stagger>
        </Section>
      )}

      {/* ---------- Why HOME GENIES + self-drawing journey ---------- */}
      <WhySection t={t} navigate={navigate} homeLink={homeLink} />

      {/* ---------- Dashboard preview (3D window, no figures) + trust emblem ---------- */}
      <DashboardPreviewSection t={t} />
      <TrustSection t={t} />

      {/* ---------- FAQ ---------- */}
      <Section id="faq">
        <Heading eyebrow={t("faq.eyebrow")} title={t("faq.title")} />
        <motion.div initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true, margin: "-60px" }}
          transition={{ duration: 0.5, ease: EASE }} className="hg-card mt-8 px-5 sm:px-7">
          <Accordion type="single" collapsible data-testid="faq-accordion">
            {FAQS.map((k, i) => (
              <AccordionItem key={k} value={k} className="border-brand-50 last:border-b-0" data-testid={`faq-item-${i + 1}`}>
                <AccordionTrigger className="py-5 text-left font-semibold text-ink hover:no-underline">
                  <span className="flex items-center gap-3"><span className="hg-icon-chip !h-8 !w-8 !rounded-lg"><HelpCircle size={15} /></span>{t(`${k}.q`)}</span>
                </AccordionTrigger>
                <AccordionContent className="pl-11 text-sm leading-relaxed text-muted2">{t(`${k}.a`)}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </motion.div>
      </Section>

      {/* ---------- Closing CTA + footer ---------- */}
      <ClosingCTA t={t} navigate={navigate} />
      <SiteFooter t={t} Link={Link} Logo={Logo} />
    </div>
  );
}
