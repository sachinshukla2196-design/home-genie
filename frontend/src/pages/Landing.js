import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Leaf, ShieldCheck, TrendingUp, ArrowRight, Sparkles, Check } from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

export default function Landing() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [products, setProducts] = useState([]);
  const [settings, setSettings] = useState({ currency_symbol: "₹", activation_amount: 1500, referral_commission: 100 });

  useEffect(() => {
    API.get("/products").then(({ data }) => setProducts(data.filter((p) => !p.is_activation_product))).catch(() => {});
    API.get("/settings/public").then(({ data }) => setSettings((s) => ({ ...s, ...data }))).catch(() => {});
  }, []);

  const sym = settings.currency_symbol || "₹";

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 glass-nav">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3 lg:px-8">
          <Logo />
          <div className="flex items-center gap-2 sm:gap-3">
            <ThemeToggle />
            <LanguageSwitcher />
            {user ? (
              <Button onClick={() => navigate("/app/dashboard")} className="rounded-full bg-forest hover:bg-brand" data-testid="landing-dashboard-btn">{t("nav.dashboard")}</Button>
            ) : (
              <>
                <Link to="/login" className="hidden sm:block text-sm font-medium text-forest hover:text-brand" data-testid="landing-login-link">{t("cta.login")}</Link>
                <Button onClick={() => navigate("/register")} className="rounded-full bg-forest hover:bg-brand" data-testid="landing-register-btn">{t("cta.getStarted")}</Button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 -z-10">
          <img src="https://images.pexels.com/photos/4046683/pexels-photo-4046683.jpeg" alt="" className="h-full w-full object-cover opacity-[0.08]" />
        </div>
        <motion.div aria-hidden className="pointer-events-none absolute -right-24 -top-24 -z-10 h-96 w-96 rounded-full bg-gold/20 blur-3xl"
          animate={{ scale: [1, 1.15, 1], opacity: [0.35, 0.55, 0.35] }} transition={{ duration: 9, repeat: Infinity, ease: "easeInOut" }} />
        <motion.div aria-hidden className="pointer-events-none absolute -left-32 bottom-0 -z-10 h-96 w-96 rounded-full bg-brand/20 blur-3xl"
          animate={{ scale: [1.1, 1, 1.1], opacity: [0.3, 0.5, 0.3] }} transition={{ duration: 11, repeat: Infinity, ease: "easeInOut" }} />
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-4 py-16 lg:grid-cols-2 lg:px-8 lg:py-24">
          <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.6 }}>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-gold-light px-3 py-1 text-xs font-semibold text-gold">
              <Sparkles size={13} /> {t("brand.tagline")}
            </span>
            <h1 className={`mt-5 text-4xl font-semibold tracking-tight text-forest sm:text-5xl lg:text-6xl ${lang === "hi" ? "font-hindi" : "font-display"}`}>
              {t("landing.heroTitle")}
            </h1>
            <p className="mt-5 max-w-xl text-base leading-relaxed text-muted2">{t("landing.heroSub")}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button onClick={() => navigate("/register")} size="lg" className="group rounded-full btn-grad px-7" data-testid="hero-register-btn">
                {t("cta.getStarted")} <ArrowRight size={17} className="ml-1.5 transition-transform group-hover:translate-x-1" />
              </Button>
              <Button onClick={() => navigate("/login")} size="lg" variant="outline" className="rounded-full border-forest/20 px-7 text-forest hover:bg-brand-50" data-testid="hero-login-btn">{t("cta.login")}</Button>
            </div>
            <div className="mt-10 flex flex-wrap gap-6">
              {[["landing.trust1", Leaf], ["landing.trust2", ShieldCheck], ["landing.trust3", TrendingUp]].map(([k, Icon]) => (
                <div key={k} className="flex items-center gap-2 text-sm font-medium text-forest">
                  <Icon size={17} className="text-gold" /> {t(k)}
                </div>
              ))}
            </div>
          </motion.div>
          <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.6, delay: 0.1 }} className="relative">
            <motion.div className="overflow-hidden rounded-3xl border border-brand-50 shadow-lift"
              whileHover={{ y: -6 }} transition={{ type: "spring", stiffness: 300, damping: 20 }}>
              <img src="https://images.pexels.com/photos/7615621/pexels-photo-7615621.jpeg" alt="Ayurvedic products" className="h-[420px] w-full object-cover" />
            </motion.div>
            <motion.div className="absolute -bottom-5 -left-5 rounded-2xl border border-brand-50 bg-white p-4 shadow-soft"
              animate={{ y: [0, -8, 0] }} transition={{ duration: 4, repeat: Infinity, ease: "easeInOut" }}>
              <div className="text-xs font-semibold uppercase tracking-wide text-muted2">{t("landing.step3")}</div>
              <div className="mt-1 font-display text-2xl font-semibold text-forest">{sym}{settings.referral_commission} <span className="text-sm font-normal text-muted2">/ activation</span></div>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* Products */}
      <section className="mx-auto max-w-7xl px-4 py-16 lg:px-8">
        <div className="mb-10 text-center">
          <h2 className="font-display text-3xl font-medium tracking-tight text-ink">{t("landing.productsTitle")}</h2>
          <p className="mx-auto mt-2 max-w-lg text-muted2">{t("landing.productsSub")}</p>
        </div>
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((p, i) => (
            <motion.div key={p.id} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.08 }}
              whileHover={{ y: -6 }}
              className="group overflow-hidden rounded-2xl border border-brand-50 bg-white shadow-card transition-shadow hover:shadow-lift">
              <div className="aspect-[4/3] overflow-hidden bg-brand-50">
                <img src={p.images?.[0]} alt={p.name} className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-110" />
              </div>
              <div className="p-5">
                <div className="text-xs font-semibold uppercase tracking-wide text-gold">{p.category}</div>
                <h3 className="mt-1 font-display text-lg font-medium text-ink">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h3>
                <div className="mt-3 flex items-baseline gap-2">
                  <span className="font-display text-xl font-semibold text-forest">{sym}{p.selling_price}</span>
                  <span className="text-sm text-muted2 line-through">{sym}{p.mrp}</span>
                </div>
                <Button onClick={() => navigate("/register")} className="mt-4 w-full rounded-full bg-forest hover:bg-brand" data-testid={`buy-${p.sku}`}>Purchase Now</Button>
              </div>
            </motion.div>
          ))}
        </div>
      </section>

      {/* Opportunity */}
      <section className="bg-forest py-20 text-white">
        <div className="mx-auto max-w-7xl px-4 lg:px-8">
          <div className="mb-12 text-center">
            <h2 className="font-display text-3xl font-medium tracking-tight">{t("landing.oppTitle")}</h2>
            <p className="mx-auto mt-2 max-w-lg text-white/70">{t("landing.oppSub")}</p>
          </div>
          <div className="grid gap-6 md:grid-cols-3">
            {[["landing.step1", "landing.step1d"], ["landing.step2", "landing.step2d"], ["landing.step3", "landing.step3d"]].map(([tk, dk], i) => (
              <motion.div key={tk} initial={{ opacity: 0, y: 16 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: i * 0.1 }}
                whileHover={{ y: -6 }}
                className="rounded-2xl border border-white/10 bg-white/5 p-7 transition-colors hover:border-gold/50 hover:bg-white/[0.08]">
                <div className="flex h-11 w-11 items-center justify-center rounded-full bg-gold font-display text-lg font-bold text-forest">{i + 1}</div>
                <h3 className="mt-4 font-display text-lg font-medium">{t(tk)}</h3>
                <p className="mt-2 text-sm text-white/70">{t(dk)}</p>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="mx-auto max-w-4xl px-4 py-20 text-center lg:px-8">
        <h2 className="font-display text-3xl font-semibold tracking-tight text-forest sm:text-4xl">{t("landing.ctaTitle")}</h2>
        <Button onClick={() => navigate("/register")} size="lg" className="mt-8 rounded-full bg-forest px-8 hover:bg-brand" data-testid="cta-register-btn">
          {t("cta.getStarted")} <ArrowRight size={17} className="ml-1.5" />
        </Button>
      </section>

      <footer className="border-t border-brand-50 bg-white py-8">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 text-sm text-muted2 sm:flex-row lg:px-8">
          <Logo size="sm" />
          <span>© {new Date().getFullYear()} {t("brand.full")}</span>
        </div>
      </footer>
    </div>
  );
}
