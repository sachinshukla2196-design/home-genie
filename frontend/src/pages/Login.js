import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { Check, Eye, EyeOff, UserPlus } from "lucide-react";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { homeRouteFor } from "@/lib/homeRoute";
import { API, apiError } from "@/lib/api";

export default function Login() {
  const { t, lang, setLang } = useI18n();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [show, setShow] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    await doLogin(email, password);
  };

  const doLogin = async (em, pw) => {
    setLoading(true);
    try {
      const { data } = await API.post("/auth/login", { email: em, password: pw });
      applyAuth(data);
      toast.success(t("auth.welcomeBack"));
      navigate(homeRouteFor(data.user));
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setLoading(false);
    }
  };

  const googleLogin = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    const redirectUrl = window.location.origin + "/app/dashboard";
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(redirectUrl)}`;
  };

  return (
    <div className="min-h-screen px-4 pb-10" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      <div className="mx-auto w-full max-w-md">
        <div className="flex justify-end pt-4"><span className="hg-icon-btn"><ThemeToggle /></span></div>

        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="text-center">
          <Link to="/" className="relative mx-auto block w-fit">
            <span className="hg-logo-glow absolute inset-0 -z-10 rounded-full bg-hg-violet/35 blur-3xl" />
            <motion.img src="/brand/logo-icon.png" alt="HOME GENIES" className="hg-float h-36 w-36 rounded-[2rem] object-cover ring-1 ring-hg-violet/40 shadow-2xl"
              initial={{ scale: 0.7, opacity: 0, rotate: -8 }} animate={{ scale: 1, opacity: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 200, damping: 16 }} />
          </Link>
          <div className="mt-5 font-display text-4xl font-bold tracking-tight"><span className="text-[#1B1024] dark:text-white">HOME </span><span className="bg-gradient-to-b from-[#E9A8F7] via-hg-lavender to-[#9333EA] bg-clip-text text-transparent">GENIES</span></div>
          <div className="mt-1 text-lg text-muted2">{t("brand.tagline")}</div>

          <div className="mt-8 text-sm font-medium uppercase tracking-[0.18em] text-muted2">{t("login.chooseLang")}</div>
          <div className="mt-3 grid grid-cols-2 gap-3">
            {[["en", "English", "EN"], ["hi", "हिन्दी", "Hindi"]].map(([code, label, sub]) => (
              <motion.button key={code} type="button" onClick={() => setLang(code)} data-testid={`lang-${code}-btn`}
                whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }} animate={lang === code ? { scale: [1, 1.04, 1] } : { scale: 1 }} transition={{ duration: 0.35 }}
                className={`relative rounded-3xl border px-4 py-5 transition-colors ${lang === code ? "hg-chip-on border-transparent shadow-[0_14px_30px_-12px_rgba(168,85,247,0.7)]" : "hg-card"}`}>
                <AnimatePresence>
                  {lang === code && (
                    <motion.span initial={{ scale: 0, rotate: -90 }} animate={{ scale: 1, rotate: 0 }} exit={{ scale: 0 }} transition={{ type: "spring", stiffness: 500, damping: 20 }}
                      className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-white/30"><Check size={14} /></motion.span>
                  )}
                </AnimatePresence>
                <div className={`text-2xl font-semibold ${code === "hi" ? "font-hindi" : ""}`}>{label}</div>
                <div className="mt-1 text-sm opacity-75">{sub}</div>
              </motion.button>
            ))}
          </div>
        </motion.div>

        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }} className="hg-card mt-6 p-6">
          <div className="text-center">
            <h1 className="font-display text-2xl font-semibold text-ink">{t("auth.welcomeBack")}</h1>
            <p className="mt-1 text-muted2">{t("auth.loginSub")}</p>
          </div>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <Label className="text-sm text-ink">HomeGenie ID / Mobile / Email</Label>
              <Input type="text" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="HG000001 / mobile / email" className="mt-1.5 h-12 rounded-2xl focus-visible:ring-brand" data-testid="login-email" />
            </div>
            <div>
              <Label className="text-sm text-ink">{t("auth.password")}</Label>
              <div className="relative mt-1.5">
                <Input type={show ? "text" : "password"} required value={password} onChange={(e) => setPassword(e.target.value)} className="h-12 rounded-2xl pr-12 focus-visible:ring-brand" data-testid="login-password" />
                <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted2" aria-label="Show password" data-testid="login-toggle-password">
                  <AnimatePresence mode="wait" initial={false}>
                    <motion.span key={show ? "off" : "on"} className="block" initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.5, opacity: 0 }} transition={{ duration: 0.15 }}>
                      {show ? <EyeOff size={20} /> : <Eye size={20} />}
                    </motion.span>
                  </AnimatePresence>
                </button>
              </div>
            </div>
            <Button type="submit" disabled={loading} className="hg-btn h-12 w-full rounded-2xl text-base font-semibold shadow-[0_12px_28px_-12px_rgba(168,85,247,0.8)] transition-transform hover:-translate-y-0.5 active:scale-[0.98]" data-testid="login-submit">
              {loading ? <span className="inline-flex items-center gap-2"><span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />{t("common.loading")}</span> : t("cta.login")}
            </Button>
          </form>
          <div className="my-5 flex items-center gap-3 text-xs text-muted2">
            <span className="h-px flex-1 bg-brand-50" /> OR <span className="h-px flex-1 bg-brand-50" />
          </div>
          <Button type="button" onClick={googleLogin} variant="outline" className="h-12 w-full gap-2 rounded-2xl border-brand-50 bg-transparent" data-testid="login-google-btn">
            <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="" className="h-4 w-4" />
            Continue with Google
          </Button>
          <div className="mt-4 flex items-center justify-between text-sm">
            <Link to="/login-otp" className="font-medium text-forest hover:underline" data-testid="to-login-otp">Login with OTP</Link>
            <Link to="/forgot" className="font-medium text-muted2 hover:text-forest" data-testid="to-forgot">Forgot password?</Link>
          </div>
        </motion.div>

        <Link to="/register" className="hg-card hg-lift group mt-4 flex items-center justify-center gap-2 px-4 py-4 font-semibold text-ink" data-testid="to-register">
          <UserPlus size={20} className="text-hg-lavender transition-transform duration-300 group-hover:scale-110" /> {t("auth.noAccount")} {t("cta.register")}
        </Link>
        <p className="mt-4 text-center text-sm text-muted2">
          {t("login.vendorPrompt")} <Link to="/vendor/login" className="font-semibold text-hg-lavender" data-testid="to-vendor-login">{t("login.vendorLink")}</Link>
        </p>
      </div>
    </div>
  );
}
