import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, ChevronLeft, ChevronRight } from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";
import { LEGAL_LINKS } from "@/pages/Legal";

const BANNERS = [
  "https://customer-assets-jt897jd0.emergentagent.net/job_anjali-ayurveda-mvp/artifacts/0gaw4tbu_file_00000000625c8211a258936d4ac2b802.png",
  "https://customer-assets-jt897jd0.emergentagent.net/job_anjali-ayurveda-mvp/artifacts/uuv7y4vz_file_0000000029708211978b8f664a84d93d.png",
  "https://customer-assets-jt897jd0.emergentagent.net/job_anjali-ayurveda-mvp/artifacts/p90dxthf_file_0000000082848211b7666f867b23c943.png",
];

export default function Landing() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [products, setProducts] = useState([]);
  const [settings, setSettings] = useState({ currency_symbol: "₹", activation_amount: 1500, referral_commission: 100 });

  useEffect(() => {
    API.get("/products").then(({ data }) => setProducts(data)).catch(() => {});
    API.get("/settings/public").then(({ data }) => setSettings((s) => ({ ...s, ...data }))).catch(() => {});
  }, []);

  const sym = settings.currency_symbol || "₹";

  const [slide, setSlide] = useState(0);
  const go = (n) => setSlide((s) => (s + n + BANNERS.length) % BANNERS.length);
  useEffect(() => {
    const id = setInterval(() => setSlide((s) => (s + 1) % BANNERS.length), 5500);
    return () => clearInterval(id);
  }, []);

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

      {/* Hero slider */}
      <section className="relative w-full overflow-hidden" data-testid="hero-slider">
        <div className="relative w-full aspect-[16/9] max-h-[82vh] bg-[#f4f7ef]">
          {BANNERS.map((src, i) => (
            <button
              key={i}
              type="button"
              onClick={() => navigate("/register")}
              aria-hidden={i !== slide}
              tabIndex={i === slide ? 0 : -1}
              aria-label={`Anjali Herbal Life banner ${i + 1} — join now`}
              className="absolute inset-0 block h-full w-full cursor-pointer border-0 bg-transparent p-0 transition-opacity duration-1000 ease-in-out"
              style={{ opacity: i === slide ? 1 : 0, pointerEvents: i === slide ? "auto" : "none" }}
              data-testid={`hero-slide-${i}`}
            >
              <img
                src={src}
                alt={`Anjali Herbal Life banner ${i + 1}`}
                className="h-full w-full object-contain"
                loading={i === 0 ? "eager" : "lazy"}
                fetchpriority={i === 0 ? "high" : "low"}
                decoding="async"
                draggable={false}
              />
            </button>
          ))}

          <button
            type="button"
            onClick={() => go(-1)}
            aria-label="Previous banner"
            data-testid="hero-prev"
            className="absolute left-3 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/70 p-2 text-forest shadow-soft backdrop-blur-sm transition hover:bg-white sm:left-5"
          >
            <ChevronLeft size={22} />
          </button>
          <button
            type="button"
            onClick={() => go(1)}
            aria-label="Next banner"
            data-testid="hero-next"
            className="absolute right-3 top-1/2 z-10 -translate-y-1/2 rounded-full bg-white/70 p-2 text-forest shadow-soft backdrop-blur-sm transition hover:bg-white sm:right-5"
          >
            <ChevronRight size={22} />
          </button>

          <div className="absolute bottom-3 left-1/2 z-10 flex -translate-x-1/2 gap-2 sm:bottom-5">
            {BANNERS.map((_, i) => (
              <button
                key={i}
                type="button"
                onClick={() => setSlide(i)}
                aria-label={`Go to banner ${i + 1}`}
                data-testid={`hero-dot-${i}`}
                className={`h-2.5 rounded-full transition-all ${i === slide ? "w-7 bg-forest" : "w-2.5 bg-forest/40 hover:bg-forest/60"}`}
              />
            ))}
          </div>
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
          <nav className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs" data-testid="legal-links">
            {LEGAL_LINKS.map(([slug, label]) => <Link key={slug} to={`/legal/${slug}`} className="hover:text-forest hover:underline" data-testid={`legal-link-${slug}`}>{label}</Link>)}
          </nav>
          <span>© {new Date().getFullYear()} {t("brand.full")}</span>
        </div>
      </footer>
    </div>
  );
}
