import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import {
  ShoppingBag, Share2, BadgeIndianRupee, Sparkles, ShieldCheck, Truck,
  RotateCcw, HeartHandshake, ArrowRight, Check, HelpCircle, LayoutDashboard,
} from "lucide-react";
import { Logo, LogoHero } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";

const PILLARS = [
  { key: "pillar.sarees", img: "/brand/pillar-sarees.jpg", cat: "Sarees" },
  { key: "pillar.fashion", img: "/brand/pillar-fashion.jpg", cat: "Fashion Products" },
  { key: "pillar.beauty", img: "/brand/pillar-beauty.jpg", cat: "Makeup, Beauty & Skincare" },
  { key: "pillar.household", img: "/brand/pillar-household.jpg", cat: "Household Essentials" },
];

const STEPS = [
  { icon: ShoppingBag, key: "how.shop" },
  { icon: Share2, key: "how.share" },
  { icon: HeartHandshake, key: "how.sell" },
  { icon: BadgeIndianRupee, key: "how.earn" },
];

const WHY = ["why.1", "why.2", "why.3", "why.4"];
const JOURNEY = ["journey.1", "journey.2", "journey.3", "journey.4"];
const TRUST = [
  { icon: ShieldCheck, key: "trust.commission" },
  { icon: RotateCcw, key: "trust.returns" },
  { icon: Truck, key: "trust.delivery" },
  { icon: HeartHandshake, key: "trust.support" },
];
const FAQS = ["faq.1", "faq.2", "faq.3", "faq.4", "faq.5", "faq.6"];

function Section({ id, children, className = "" }) {
  return (
    <section id={id} className={`mx-auto w-full max-w-6xl px-5 py-16 sm:px-8 lg:py-24 ${className}`}>
      {children}
    </section>
  );
}

function Eyebrow({ children }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-brand-700">
      <Sparkles size={12} /> {children}
    </span>
  );
}

export default function Landing() {
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const homeLink = user ? "/app/dashboard" : "/register";

  return (
    <div className="min-h-screen bg-background" data-testid="landing-page">
      {/* ---------- Header ---------- */}
      <header className="sticky top-0 z-40 glass-nav">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5 sm:px-8">
          <Link to="/" data-testid="header-logo"><Logo size="sm" variant="icon" className="sm:hidden" /><span className="hidden sm:block"><Logo size="sm" /></span></Link>
          <div className="flex items-center gap-2 sm:gap-3">
            <LanguageSwitcher />
            <Link to="/login" className="hidden text-sm font-medium text-muted2 hover:text-brand sm:block" data-testid="header-login">
              {t("cta.login")}
            </Link>
            <Button onClick={() => navigate("/register")} className="btn-grad rounded-full px-4 text-xs sm:px-5 sm:text-sm" data-testid="header-join">
              <span className="hidden sm:inline">{t("cta.joinGenie")}</span>
              <span className="sm:hidden">{t("cta.register")}</span>
            </Button>
          </div>
        </div>
      </header>

      {/* ---------- Hero ---------- */}
      <div className="relative overflow-hidden hg-royal">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-5 py-16 sm:px-8 lg:grid-cols-2 lg:py-24">
          <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5 }}>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gold/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-gold">
              <Sparkles size={12} /> {t("brand.tagline")}
            </span>
            <h1 className="mt-5 font-display text-4xl font-bold leading-[1.08] text-white sm:text-5xl lg:text-6xl">
              {t("hero.title")}
            </h1>
            <div className="hg-gold-rule mt-5 w-32" />
            <p className="mt-5 max-w-lg text-base text-white/80">{t("hero.sub")}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button onClick={() => navigate(homeLink)} className="btn-gold rounded-full px-6 py-6 text-sm font-semibold" data-testid="hero-join-btn">
                {t("cta.joinGenie")} <ArrowRight size={16} className="ml-1.5" />
              </Button>
              <Button onClick={() => navigate("/login")} variant="outline"
                className="rounded-full border-white/30 bg-white/5 px-6 py-6 text-sm font-semibold text-white hover:bg-white/15" data-testid="hero-explore-btn">
                {t("cta.exploreProducts")}
              </Button>
            </div>
            <p className="mt-4 text-xs text-white/55">{t("hero.note")}</p>
          </motion.div>

          <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.6, delay: 0.1 }}
            className="relative">
            <div className="overflow-hidden rounded-3xl border border-white/15 shadow-lift">
              <img src="/brand/hero.jpg" alt={t("hero.imgAlt")} className="h-[300px] w-full object-cover sm:h-[420px]" data-testid="hero-image" />
            </div>
            <div className="absolute -bottom-6 -left-4 hidden rounded-2xl bg-white/95 p-3 shadow-lift backdrop-blur sm:block">
              <LogoHero className="h-20 w-20" />
            </div>
          </motion.div>
        </div>
      </div>

      {/* ---------- How it works ---------- */}
      <Section id="how-it-works">
        <Eyebrow>{t("how.eyebrow")}</Eyebrow>
        <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{t("how.title")}</h2>
        <p className="mt-3 max-w-2xl text-base text-muted2">{t("how.sub")}</p>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s, i) => {
            const Icon = s.icon;
            return (
              <motion.div key={s.key} initial={{ opacity: 0, y: 14 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }}
                transition={{ delay: i * 0.07 }}
                className="hg-surface rounded-2xl border border-brand-50 p-6 shadow-card" data-testid={`how-step-${i + 1}`}>
                <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-50 text-brand"><Icon size={20} /></div>
                <div className="mt-4 font-display text-lg font-semibold text-ink">{t(`${s.key}.t`)}</div>
                <p className="mt-1.5 text-sm text-muted2">{t(`${s.key}.d`)}</p>
              </motion.div>
            );
          })}
        </div>
      </Section>

      {/* ---------- Four pillars ---------- */}
      <div className="bg-brand-50/40">
        <Section id="categories">
          <Eyebrow>{t("pillars.eyebrow")}</Eyebrow>
          <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{t("pillars.title")}</h2>
          <p className="mt-3 max-w-2xl text-base text-muted2">{t("pillars.sub")}</p>
          <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {PILLARS.map((p, i) => (
              <motion.button key={p.key} onClick={() => navigate(`/login?next=products&category=${encodeURIComponent(p.cat)}`)}
                initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.06 }}
                className="group overflow-hidden rounded-2xl border border-brand-50 bg-white text-left shadow-card hover:-translate-y-1 hover:shadow-lift"
                data-testid={`pillar-${i + 1}`}>
                <div className="aspect-[4/3] overflow-hidden">
                  <img src={p.img} alt={t(`${p.key}.t`)} className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105" />
                </div>
                <div className="p-5">
                  <div className="font-display text-lg font-semibold text-ink">{t(`${p.key}.t`)}</div>
                  <p className="mt-1 text-sm text-muted2">{t(`${p.key}.d`)}</p>
                </div>
              </motion.button>
            ))}
          </div>
        </Section>
      </div>

      {/* ---------- Why HOME GENIES ---------- */}
      <Section id="about">
        <div className="grid gap-12 lg:grid-cols-2">
          <div>
            <Eyebrow>{t("why.eyebrow")}</Eyebrow>
            <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{t("why.title")}</h2>
            <p className="mt-3 text-base text-muted2">{t("why.sub")}</p>
            <ul className="mt-7 space-y-4">
              {WHY.map((k, i) => (
                <li key={k} className="flex gap-3" data-testid={`why-${i + 1}`}>
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-gold-light text-gold"><Check size={14} /></span>
                  <div>
                    <div className="font-semibold text-ink">{t(`${k}.t`)}</div>
                    <p className="text-sm text-muted2">{t(`${k}.d`)}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          {/* HomeGenie journey */}
          <div className="rounded-3xl border border-brand-50 hg-surface p-7 shadow-card" data-testid="journey-card">
            <h3 className="font-display text-2xl font-semibold text-ink">{t("journey.title")}</h3>
            <p className="mt-2 text-sm text-muted2">{t("journey.sub")}</p>
            <ol className="mt-6 space-y-5">
              {JOURNEY.map((k, i) => (
                <li key={k} className="flex gap-4" data-testid={`journey-${i + 1}`}>
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-sm font-bold text-white">{i + 1}</span>
                  <div>
                    <div className="font-semibold text-ink">{t(`${k}.t`)}</div>
                    <p className="text-sm text-muted2">{t(`${k}.d`)}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </Section>

      {/* ---------- Business dashboard preview ---------- */}
      <div className="bg-brand-50/40">
        <Section id="dashboard-preview">
          <Eyebrow>{t("preview.eyebrow")}</Eyebrow>
          <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{t("preview.title")}</h2>
          <p className="mt-3 max-w-2xl text-base text-muted2">{t("preview.sub")}</p>
          <div className="mt-8 rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="dashboard-preview">
            <div className="flex items-center gap-2 text-brand"><LayoutDashboard size={18} /><span className="text-sm font-semibold">{t("preview.label")}</span></div>
            <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {["preview.sales", "preview.orders", "preview.commission", "preview.points"].map((k) => (
                <div key={k} className="rounded-xl border border-dashed border-brand-50 bg-brand-50/30 p-4" data-testid={`preview-${k.split(".")[1]}`}>
                  <div className="text-xs font-medium uppercase tracking-wide text-muted2">{t(k)}</div>
                  <div className="mt-2 font-display text-xl font-semibold text-muted2">—</div>
                </div>
              ))}
            </div>
            <p className="mt-5 rounded-lg bg-gold-light/40 px-3 py-2 text-xs font-medium text-ink" data-testid="preview-disclaimer">
              {t("preview.disclaimer")}
            </p>
          </div>
        </Section>
      </div>

      {/* ---------- Trust & transparency ---------- */}
      <Section id="trust">
        <Eyebrow>{t("trust.eyebrow")}</Eyebrow>
        <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{t("trust.title")}</h2>
        <div className="mt-10 grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {TRUST.map((x, i) => {
            const Icon = x.icon;
            return (
              <div key={x.key} className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid={`trust-${i + 1}`}>
                <Icon size={20} className="text-magenta" />
                <div className="mt-4 font-display text-base font-semibold text-ink">{t(`${x.key}.t`)}</div>
                <p className="mt-1.5 text-sm text-muted2">{t(`${x.key}.d`)}</p>
              </div>
            );
          })}
        </div>
      </Section>

      {/* ---------- FAQ ---------- */}
      <div className="bg-brand-50/40">
        <Section id="faq">
          <Eyebrow>{t("faq.eyebrow")}</Eyebrow>
          <h2 className="mt-4 font-display text-3xl font-bold text-ink sm:text-4xl">{t("faq.title")}</h2>
          <div className="mt-8 rounded-2xl border border-brand-50 bg-white px-5 shadow-card sm:px-7">
            <Accordion type="single" collapsible data-testid="faq-accordion">
              {FAQS.map((k, i) => (
                <AccordionItem key={k} value={k} data-testid={`faq-item-${i + 1}`}>
                  <AccordionTrigger className="text-left font-semibold text-ink hover:no-underline">
                    <span className="flex items-center gap-2"><HelpCircle size={15} className="shrink-0 text-brand" />{t(`${k}.q`)}</span>
                  </AccordionTrigger>
                  <AccordionContent className="text-sm text-muted2">{t(`${k}.a`)}</AccordionContent>
                </AccordionItem>
              ))}
            </Accordion>
          </div>
        </Section>
      </div>

      {/* ---------- Closing CTA ---------- */}
      <div className="hg-royal">
        <Section className="text-center">
          <LogoHero className="mx-auto h-24 w-24" />
          <h2 className="mt-6 font-display text-3xl font-bold text-white sm:text-4xl">{t("cta.closingTitle")}</h2>
          <p className="mx-auto mt-3 max-w-xl text-base text-white/80">{t("cta.closingSub")}</p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Button onClick={() => navigate("/register")} className="btn-gold rounded-full px-7 py-6 text-sm font-semibold" data-testid="closing-register-btn">
              {t("cta.joinGenie")} <ArrowRight size={16} className="ml-1.5" />
            </Button>
            <Button onClick={() => navigate("/login")} variant="outline"
              className="rounded-full border-white/30 bg-white/5 px-7 py-6 text-sm font-semibold text-white hover:bg-white/15" data-testid="closing-browse-btn">
              {t("cta.exploreProducts")}
            </Button>
          </div>
        </Section>
      </div>

      {/* ---------- Footer ---------- */}
      <footer className="border-t border-brand-50 bg-white" data-testid="site-footer">
        <div className="mx-auto grid max-w-6xl gap-8 px-5 py-12 sm:grid-cols-2 sm:px-8 lg:grid-cols-4">
          <div>
            <Logo size="sm" />
            <p className="mt-3 text-sm text-muted2">{t("footer.about")}</p>
          </div>
          <div>
            <div className="font-display text-sm font-semibold text-ink">{t("footer.shop")}</div>
            <ul className="mt-3 space-y-2 text-sm text-muted2">
              {PILLARS.map((p) => <li key={p.key}><Link to="/login" className="hover:text-brand">{t(`${p.key}.t`)}</Link></li>)}
            </ul>
          </div>
          <div>
            <div className="font-display text-sm font-semibold text-ink">{t("footer.company")}</div>
            <ul className="mt-3 space-y-2 text-sm text-muted2">
              <li><a href="#about" className="hover:text-brand">{t("footer.aboutUs")}</a></li>
              <li><a href="#how-it-works" className="hover:text-brand">{t("how.title")}</a></li>
              <li><a href="#faq" className="hover:text-brand">{t("faq.title")}</a></li>
              <li><Link to="/legal/support" className="hover:text-brand">{t("nav.support")}</Link></li>
            </ul>
          </div>
          <div>
            <div className="font-display text-sm font-semibold text-ink">{t("footer.policies")}</div>
            <ul className="mt-3 space-y-2 text-sm text-muted2">
              <li><Link to="/legal/terms" className="hover:text-brand" data-testid="footer-terms">{t("legal.terms")}</Link></li>
              <li><Link to="/legal/privacy" className="hover:text-brand" data-testid="footer-privacy">{t("legal.privacy")}</Link></li>
              <li><Link to="/legal/returns" className="hover:text-brand" data-testid="footer-returns">{t("legal.returns")}</Link></li>
              <li><Link to="/legal/refunds" className="hover:text-brand" data-testid="footer-refunds">{t("legal.refunds")}</Link></li>
            </ul>
          </div>
        </div>
        <div className="border-t border-brand-50 px-5 py-5 text-center text-xs text-muted2 sm:px-8">
          © {new Date().getFullYear()} HOME GENIES — {t("brand.tagline")}
        </div>
      </footer>
    </div>
  );
}
