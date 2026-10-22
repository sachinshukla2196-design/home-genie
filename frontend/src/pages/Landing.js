import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Sparkles, ArrowRight, HelpCircle, LogIn } from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Stagger, StaggerItem, pressable } from "@/components/motion";
import { captureSellerRef } from "@/lib/sellerRef";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";
import { LandingHero, HowItWorks } from "@/components/LandingHero";
import { PillarsSection, WhySection, DashboardPreviewSection, TrustSection, ClosingCTA, SiteFooter } from "@/components/LandingSections";



const FAQS = ["faq.1", "faq.2", "faq.3", "faq.4", "faq.5", "faq.6"];
const EASE = [0.16, 1, 0.3, 1];
const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

function Section({ id, children, className = "" }) {
  return (
    <section id={id} className={`relative mx-auto w-full max-w-6xl scroll-mt-20 px-4 py-16 sm:px-8 lg:py-24 ${className}`}>
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
  const homeLink = user ? "/app/dashboard" : "/register";
  const [products, setProducts] = useState([]);
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => { captureSellerRef(); }, []);
  useEffect(() => {
    API.get("/products").then(({ data }) => setProducts((data || []).slice(0, 4))).catch(() => setProducts([]));
  }, []);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const name = (p) => (lang === "hi" && p.name_hi ? p.name_hi : p.name);

  return (
    <div className="min-h-screen overflow-x-hidden bg-background" data-testid="landing-page">
      {/* ---------- Header: transparent, turns to glass on scroll ---------- */}
      <header className={`sticky top-0 z-40 transition-[background-color,border-color,backdrop-filter] duration-300 ${scrolled ? "glass-nav" : "border-b border-transparent"}`}
        style={{ top: "env(safe-area-inset-top, 0px)" }}>
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-2 px-4 sm:px-8">
          <Link to="/" data-testid="header-logo" aria-label="HOME GENIES home">
            <Logo size="sm" variant="icon" className="sm:hidden" /><span className="hidden sm:block"><Logo size="sm" /></span>
          </Link>
          <nav className="hidden items-center gap-6 whitespace-nowrap text-sm font-medium text-muted2 lg:flex" aria-label="Sections">
            <a href="#how-it-works" className="hover:text-ink">{t("how.eyebrow")}</a>
            <a href="#categories" className="hover:text-ink">{t("pillars.eyebrow")}</a>
            <a href="#faq" className="hover:text-ink">{t("faq.eyebrow")}</a>
          </nav>
          <div className="flex items-center gap-1.5 sm:gap-3">
            <LanguageSwitcher />
            <Link to="/login" className="hg-icon-btn !h-10 !w-10 sm:!w-auto sm:px-4 text-sm font-medium" aria-label={t("cta.login")} data-testid="header-login">
              <LogIn size={18} className="sm:hidden" /><span className="hidden sm:inline">{t("cta.login")}</span>
            </Link>
            <Button onClick={() => navigate("/register")} className="hg-btn h-10 rounded-full px-4 text-xs sm:px-5 sm:text-sm" data-testid="header-join">
              <span className="hidden sm:inline">{t("cta.joinGenie")}</span>
              <span className="sm:hidden">{t("cta.register")}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* ---------- Hero + How it works (sequenced entrance) ---------- */}
      <LandingHero t={t} lang={lang} navigate={navigate} homeLink={homeLink} products={products} />
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
