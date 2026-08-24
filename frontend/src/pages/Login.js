import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function Login() {
  const { t } = useI18n();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

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
      const roles = ["super_admin", "admin", "accounts_admin", "support_admin"];
      navigate(roles.includes(data.user.role) ? "/admin" : "/app/dashboard");
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden bg-forest lg:block">
        <img src="https://images.pexels.com/photos/18408805/pexels-photo-18408805.jpeg" alt="" className="h-full w-full object-cover opacity-30" />
        <div className="absolute inset-0 flex flex-col justify-between p-12 text-white">
          <Logo dark />
          <div>
            <h2 className="font-display text-3xl font-medium leading-snug">{t("landing.heroTitle")}</h2>
            <p className="mt-3 max-w-md text-white/70">{t("landing.heroSub")}</p>
          </div>
        </div>
      </div>

      <div className="flex flex-col p-6 sm:p-12">
        <div className="flex items-center justify-between">
          <Link to="/"><Logo /></Link>
          <LanguageSwitcher />
        </div>
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mx-auto mt-auto w-full max-w-sm">
          <h1 className="font-display text-3xl font-semibold text-ink">{t("auth.welcomeBack")}</h1>
          <p className="mt-1 text-muted2">{t("auth.loginSub")}</p>
          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <Label className="text-sm text-ink">{t("auth.email")}</Label>
              <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid="login-email" />
            </div>
            <div>
              <Label className="text-sm text-ink">{t("auth.password")}</Label>
              <Input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid="login-password" />
            </div>
            <Button type="submit" disabled={loading} className="h-11 w-full rounded-full btn-grad" data-testid="login-submit">
              {loading ? t("common.loading") : t("cta.login")}
            </Button>
          </form>
          <div className="mt-3 flex items-center justify-between text-sm">
            <Link to="/login-otp" className="font-medium text-forest hover:underline" data-testid="to-login-otp">Login with OTP</Link>
            <Link to="/forgot" className="font-medium text-muted2 hover:text-forest" data-testid="to-forgot">Forgot password?</Link>
          </div>
          <p className="mt-6 text-center text-sm text-muted2">
            {t("auth.noAccount")} <Link to="/register" className="font-semibold text-forest hover:underline" data-testid="to-register">{t("cta.register")}</Link>
          </p>

          <div className="mt-6">
            <div className="flex items-center gap-3 text-xs uppercase tracking-wider text-muted2">
              <span className="h-px flex-1 bg-brand-50" /> {t("auth.tryDemo")} <span className="h-px flex-1 bg-brand-50" />
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <button type="button" onClick={() => doLogin("demo.distributor@anjaliherballife.in", "Demo@1234")} disabled={loading}
                className="rounded-xl border border-brand-50 bg-white p-3 text-left transition-all hover:-translate-y-0.5 hover:shadow-card" data-testid="demo-distributor-btn">
                <div className="text-sm font-semibold text-forest">{t("auth.demoDistributor")}</div>
                <div className="mt-0.5 text-xs text-muted2">GREEN · wallet · team</div>
              </button>
              <button type="button" onClick={() => doLogin("sachin.shukla2196@gmail.com", "Admin@12345")} disabled={loading}
                className="rounded-xl border border-gold/30 bg-gold-light/40 p-3 text-left transition-all hover:-translate-y-0.5 hover:shadow-card" data-testid="demo-admin-btn">
                <div className="text-sm font-semibold text-forest">{t("auth.demoAdmin")}</div>
                <div className="mt-0.5 text-xs text-muted2">Admin panel</div>
              </button>
            </div>
          </div>
        </motion.div>
        <div className="mt-auto" />
      </div>
    </div>
  );
}
