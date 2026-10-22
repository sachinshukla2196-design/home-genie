import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Store, Eye, EyeOff, Users, PackageCheck, ShieldCheck, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Logo } from "@/components/Logo";
import { Stagger, StaggerItem } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { homeRouteFor } from "@/lib/homeRoute";
import { API, apiError } from "@/lib/api";

/** Split layout shared by vendor sign-up and vendor login. */
function Shell({ children }) {
  const { t } = useI18n();
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1.05fr]">
      <aside className="hg-violet hg-sheen relative hidden overflow-hidden lg:flex lg:flex-col lg:justify-between lg:p-12">
        <span className="hg-orb -left-16 top-20 h-72 w-72 bg-hg-pink/25" />
        <span className="hg-orb -bottom-20 right-0 h-80 w-80 bg-hg-violet/40" />
        <Link to="/" className="relative"><Logo /></Link>
        <Stagger className="relative">
          <StaggerItem><span className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-3 py-1 text-xs font-semibold uppercase tracking-wider text-white ring-1 ring-white/25"><Store size={13} /> {t("vp.portal")}</span></StaggerItem>
          <StaggerItem as="h2" className="mt-5 font-display text-4xl font-bold leading-tight text-white">{t("vr.title")}</StaggerItem>
          <StaggerItem as="p" className="mt-3 max-w-md text-white/80">{t("vr.sub")}</StaggerItem>
          {[["vr.b1", Users], ["vr.b2", PackageCheck], ["vr.b3", ShieldCheck]].map(([k, I]) => (
            <StaggerItem key={k} className="mt-4 flex items-center gap-3 text-white/90">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/15 ring-1 ring-white/20"><I size={18} /></span>{t(k)}
            </StaggerItem>
          ))}
        </Stagger>
        <p className="relative text-xs text-white/60">© {new Date().getFullYear()} HOME GENIES</p>
      </aside>

      <main className="flex flex-col px-4 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Link to="/" className="lg:invisible"><Logo size="sm" /></Link>
          <LanguageSwitcher />
        </div>
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45 }} className="mx-auto my-auto w-full max-w-md py-8">
          {children}
        </motion.div>
      </main>
    </div>
  );
}

function PasswordInput({ value, onChange, testid }) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative mt-1.5">
      <Input type={show ? "text" : "password"} value={value} onChange={onChange} required className="pr-12" data-testid={testid} autoComplete="new-password" />
      <button type="button" onClick={() => setShow(!show)} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted2" aria-label="Show password">
        {show ? <EyeOff size={19} /> : <Eye size={19} />}
      </button>
    </div>
  );
}

export function VendorRegister() {
  const { t } = useI18n();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [f, setF] = useState({ business_name: "", full_name: "", mobile: "", email: "", password: "", confirm_password: "", accept_terms: false });
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const submit = async (e) => {
    e.preventDefault();
    if (f.password !== f.confirm_password) return toast.error(t("vr.mismatch"));
    setBusy(true);
    try {
      const { data } = await API.post("/auth/vendor-register", f);
      applyAuth(data);
      toast.success(t("vr.next"));
      navigate("/vendor/profile");
    } catch (err) { toast.error(apiError(err)); }
    finally { setBusy(false); }
  };

  return (
    <Shell>
      <div className="hg-card p-6 sm:p-8">
        <span className="hg-icon-chip"><Store size={22} /></span>
        <h1 className="mt-4 font-display text-2xl font-bold text-ink">{t("vl.register")}</h1>
        <p className="mt-1 text-sm text-muted2 lg:hidden">{t("vr.sub")}</p>
        <form onSubmit={submit} className="mt-6 space-y-4" data-testid="vendor-register-form">
          <div><Label className="text-sm text-ink">{t("vr.business")}</Label><Input value={f.business_name} onChange={set("business_name")} required className="mt-1.5" data-testid="vr-business" /></div>
          <div><Label className="text-sm text-ink">{t("vr.name")}</Label><Input value={f.full_name} onChange={set("full_name")} required className="mt-1.5" autoComplete="name" data-testid="vr-name" /></div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div><Label className="text-sm text-ink">{t("vr.mobile")}</Label><Input value={f.mobile} onChange={set("mobile")} required inputMode="numeric" maxLength={10} className="mt-1.5" autoComplete="tel" data-testid="vr-mobile" /></div>
            <div><Label className="text-sm text-ink">{t("vr.email")}</Label><Input type="email" value={f.email} onChange={set("email")} className="mt-1.5" autoComplete="email" data-testid="vr-email" /></div>
          </div>
          <div><Label className="text-sm text-ink">{t("vr.password")}</Label><PasswordInput value={f.password} onChange={set("password")} testid="vr-password" /></div>
          <div><Label className="text-sm text-ink">{t("vr.confirm")}</Label><PasswordInput value={f.confirm_password} onChange={set("confirm_password")} testid="vr-confirm" /></div>
          <label className="flex cursor-pointer items-start gap-3 text-sm text-ink">
            <input type="checkbox" checked={f.accept_terms} onChange={(e) => setF({ ...f, accept_terms: e.target.checked })} className="mt-0.5 h-4 w-4 accent-[#8B3DFF]" data-testid="vr-terms" />
            <span>{t("vr.terms")} <Link to="/legal/terms" className="text-hg-lavender underline">{t("legal.terms")}</Link></span>
          </label>
          <Button type="submit" disabled={busy || !f.accept_terms} className="hg-btn h-12 w-full rounded-2xl text-base font-semibold" data-testid="vr-submit">
            {busy ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : <>{t("vr.create")} <ArrowRight size={17} /></>}
          </Button>
        </form>
        <p className="mt-5 text-center text-sm text-muted2">{t("vr.haveAccount")} <Link to="/vendor/login" className="font-semibold text-hg-lavender" data-testid="to-vendor-login">{t("vr.loginLink")}</Link></p>
      </div>
    </Shell>
  );
}

export function VendorLogin() {
  const { t } = useI18n();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await API.post("/auth/login", { email: id, password: pw });
      applyAuth(data);
      if (data.user.role !== "vendor") toast.info(t("vl.notVendor"));
      navigate(homeRouteFor(data.user));
    } catch (err) { toast.error(apiError(err)); }
    finally { setBusy(false); }
  };

  return (
    <Shell>
      <div className="hg-card p-6 sm:p-8">
        <span className="hg-icon-chip"><Store size={22} /></span>
        <h1 className="mt-4 font-display text-2xl font-bold text-ink">{t("vl.title")}</h1>
        <p className="mt-1 text-sm text-muted2">{t("vl.sub")}</p>
        <form onSubmit={submit} className="mt-6 space-y-4" data-testid="vendor-login-form">
          <div><Label className="text-sm text-ink">{t("vr.mobile")} / Email / ID</Label>
            <Input value={id} onChange={(e) => setId(e.target.value)} required className="mt-1.5" placeholder="VD000001 / mobile / email" autoComplete="username" data-testid="vl-id" /></div>
          <div><Label className="text-sm text-ink">{t("auth.password")}</Label><PasswordInput value={pw} onChange={(e) => setPw(e.target.value)} testid="vl-password" /></div>
          <Button type="submit" disabled={busy} className="hg-btn h-12 w-full rounded-2xl text-base font-semibold" data-testid="vl-submit">
            {busy ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : t("cta.login")}
          </Button>
          <div className="text-right"><Link to="/forgot" className="text-sm text-muted2 hover:text-ink">Forgot password?</Link></div>
        </form>
        <div className="mt-5 space-y-2 border-t border-brand-50 pt-5 text-center text-sm text-muted2">
          <p>{t("vl.noAccount")} <Link to="/vendor/register" className="font-semibold text-hg-lavender" data-testid="to-vendor-register">{t("vl.register")}</Link></p>
          <p>{t("vl.shopper")} <Link to="/login" className="font-semibold text-ink underline-offset-2 hover:underline">{t("vl.shopperLink")}</Link></p>
        </div>
      </div>
    </Shell>
  );
}
