import React, { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { STATES, CITIES } from "@/data/indiaLocations";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function Register() {
  const { t } = useI18n();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [step, setStep] = useState(1);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({
    full_name: "", email: "", mobile: "", aadhaar_number: "", password: "", confirm_password: "",
    sponsor_id: params.get("ref") || "", address: "", state: "", city: "", pincode: "",
    otp: "", accept_terms: false,
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target?.value ?? e }));

  const sendOtp = async (e) => {
    e.preventDefault();
    if (!form.sponsor_id.trim()) return toast.error("A referral / sponsor ID is required to register.");
    if (!/^\d{12}$/.test(form.aadhaar_number.trim())) return toast.error("Enter a valid 12-digit Aadhaar number.");
    if (form.password !== form.confirm_password) return toast.error("Passwords do not match.");
    if (!form.accept_terms) return toast.error(t("auth.acceptTerms"));
    setLoading(true);
    try {
      const { data } = await API.post("/auth/send-otp", { email: form.email, mobile: form.mobile, sponsor_id: form.sponsor_id });
      toast.success(t("auth.otpSent"));
      if (data.dev_otp) {
        setForm((f) => ({ ...f, otp: data.dev_otp }));
        toast.info(`${t("auth.devOtp")}: ${data.dev_otp}`, { duration: 8000 });
      }
      setStep(2);
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setLoading(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await API.post("/auth/register", form);
      applyAuth(data);
      toast.success(`${t("cta.getStarted")} — ${data.user.distributor_id}`);
      navigate("/app/dashboard");
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col p-6 sm:p-12">
        <div className="flex items-center justify-between">
          <Link to="/"><Logo /></Link>
          <LanguageSwitcher />
        </div>
        <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mx-auto mt-8 w-full max-w-md">
          <h1 className="font-display text-3xl font-semibold text-ink">{t("auth.createAccount")}</h1>
          <p className="mt-1 text-muted2">{t("auth.registerSub")}</p>

          {step === 1 ? (
            <form onSubmit={sendOtp} className="mt-6 space-y-3.5" data-testid="register-step1">
              <Field label={t("auth.fullName")} value={form.full_name} onChange={set("full_name")} required testid="reg-fullname" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={t("auth.email")} type="email" value={form.email} onChange={set("email")} required testid="reg-email" />
                <Field label={`${t("auth.mobile")}`} value={form.mobile} onChange={set("mobile")} required testid="reg-mobile" />
              </div>
              <Field label={`${t("auth.aadhaar")} *`} value={form.aadhaar_number} onChange={set("aadhaar_number")} required testid="reg-aadhaar" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={t("auth.password")} type="password" value={form.password} onChange={set("password")} required testid="reg-password" />
                <Field label={t("auth.confirmPassword")} type="password" value={form.confirm_password} onChange={set("confirm_password")} required testid="reg-confirm" />
              </div>
              <div>
                <Field label={`${t("auth.sponsorId")} *`} value={form.sponsor_id} onChange={set("sponsor_id")} required testid="reg-sponsor" />
                <p className="mt-1 text-xs text-muted2">{t("auth.sponsorRequired")}</p>
              </div>
              <Field label={t("auth.address")} value={form.address} onChange={set("address")} testid="reg-address" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                <div>
                  <Label className="text-sm text-ink">{t("auth.state")}</Label>
                  <Select value={form.state} onValueChange={(v) => setForm((f) => ({ ...f, state: v, city: "" }))}>
                    <SelectTrigger className="mt-1.5 h-11 rounded-lg" data-testid="reg-state"><SelectValue placeholder="Select" /></SelectTrigger>
                    <SelectContent className="max-h-64">{STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-sm text-ink">{t("auth.city")}</Label>
                  <Select value={form.city} onValueChange={(v) => setForm((f) => ({ ...f, city: v }))} disabled={!form.state}>
                    <SelectTrigger className="mt-1.5 h-11 rounded-lg" data-testid="reg-city"><SelectValue placeholder={form.state ? "Select" : "State first"} /></SelectTrigger>
                    <SelectContent className="max-h-64">{[...(CITIES[form.state] || []), "Other"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <Field label={t("auth.pincode")} value={form.pincode} onChange={set("pincode")} testid="reg-pincode" />
              </div>
              <label className="flex items-center gap-2 pt-1 text-sm text-muted2">
                <Checkbox checked={form.accept_terms} onCheckedChange={(v) => setForm((f) => ({ ...f, accept_terms: !!v }))} data-testid="reg-terms" />
                {t("auth.acceptTerms")}
              </label>
              <Button type="submit" disabled={loading} className="h-11 w-full rounded-full bg-forest hover:bg-brand" data-testid="reg-sendotp">
                {loading ? t("common.loading") : t("auth.sendOtp")}
              </Button>
            </form>
          ) : (
            <form onSubmit={submit} className="mt-6 space-y-4" data-testid="register-step2">
              <p className="rounded-lg bg-brand-50 px-4 py-3 text-sm text-forest">{t("auth.otpSent")} — <b>{form.email}</b></p>
              <Field label={t("auth.otp")} value={form.otp} onChange={set("otp")} required testid="reg-otp" />
              <Button type="submit" disabled={loading} className="h-11 w-full rounded-full bg-forest hover:bg-brand" data-testid="reg-verify">
                {loading ? t("common.loading") : t("auth.verifyOtp")}
              </Button>
              <button type="button" onClick={() => setStep(1)} className="w-full text-center text-sm text-muted2 hover:text-forest">{t("cta.back")}</button>
            </form>
          )}

          <p className="mt-6 text-center text-sm text-muted2">
            {t("auth.haveAccount")} <Link to="/login" className="font-semibold text-forest hover:underline" data-testid="to-login">{t("cta.login")}</Link>
          </p>
        </motion.div>
      </div>

      <div className="relative hidden bg-forest lg:block">
        <img src="https://images.pexels.com/photos/4174743/pexels-photo-4174743.jpeg" alt="" className="h-full w-full object-cover opacity-30" />
        <div className="absolute inset-0 flex flex-col justify-end p-12 text-white">
          <h2 className="font-display text-3xl font-medium leading-snug">{t("landing.oppTitle")}</h2>
          <p className="mt-3 max-w-md text-white/70">{t("landing.oppSub")}</p>
        </div>
      </div>
    </div>
  );
}

function Field({ label, type = "text", value, onChange, required, testid }) {
  return (
    <div>
      <Label className="text-sm text-ink">{label}</Label>
      <Input type={type} value={value} onChange={onChange} required={required} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} />
    </div>
  );
}
