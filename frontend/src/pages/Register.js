import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { CheckCircle2 } from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { STATES, CITIES } from "@/data/indiaLocations";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function Register() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [form, setForm] = useState({
    full_name: "", mobile: "", email: "", password: "", confirm_password: "",
    sponsor_id: params.get("ref") || "", aadhaar_number: "", address: "", state: "", city: "", pincode: "",
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target?.value ?? e }));

  const submit = async (e) => {
    e.preventDefault();
    if (!/^[6-9]\d{9}$/.test(form.mobile.trim())) return toast.error("Enter a valid 10-digit mobile number.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())) return toast.error("A valid email address is required.");
    if (form.password.length < 6) return toast.error("Password must be at least 6 characters.");
    if (form.password !== form.confirm_password) return toast.error("Passwords do not match.");
    if (!/^\d{12}$/.test(form.aadhaar_number.trim())) return toast.error("Enter a valid 12-digit Aadhaar number.");
    if (!form.state || !form.city || !form.pincode.trim()) return toast.error("State, City and Pincode are required.");
    setLoading(true);
    try {
      const { data } = await API.post("/auth/register-request", form);
      toast.success(data.message);
      setDone(true);
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

        {done ? (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mx-auto mt-16 w-full max-w-md text-center" data-testid="register-pending">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-brand-50 text-forest"><CheckCircle2 size={34} /></div>
            <h1 className="mt-6 font-display text-2xl font-semibold text-ink">Request submitted</h1>
            <p className="mt-2 text-muted2">Your registration request has been submitted.<br />Please wait for Admin approval. You'll be able to log in once your Distributor ID is created.</p>
            <Link to="/login"><Button className="mt-6 h-11 rounded-full bg-forest px-8 hover:bg-brand" data-testid="pending-to-login">Go to Login</Button></Link>
          </motion.div>
        ) : (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mx-auto mt-8 w-full max-w-md">
            <h1 className="font-display text-3xl font-semibold text-ink">{t("auth.createAccount")}</h1>
            <p className="mt-1 text-muted2">Fill in your details. Admin will review and approve your account.</p>

            <form onSubmit={submit} className="mt-6 space-y-3.5" data-testid="register-form">
              <Field label={t("auth.fullName")} value={form.full_name} onChange={set("full_name")} required testid="reg-fullname" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={t("auth.mobile")} value={form.mobile} onChange={set("mobile")} required testid="reg-mobile" />
                <Field label={t("auth.email")} type="email" value={form.email} onChange={set("email")} required testid="reg-email" />
              </div>
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={t("auth.password")} type="password" value={form.password} onChange={set("password")} required testid="reg-password" />
                <Field label={t("auth.confirmPassword")} type="password" value={form.confirm_password} onChange={set("confirm_password")} required testid="reg-confirm" />
              </div>
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={`${t("auth.aadhaar")} *`} value={form.aadhaar_number} onChange={set("aadhaar_number")} required testid="reg-aadhaar" />
                <Field label={`${t("auth.sponsorId")} (optional)`} value={form.sponsor_id} onChange={set("sponsor_id")} testid="reg-sponsor" />
              </div>
              <Field label={`${t("auth.address")} (optional)`} value={form.address} onChange={set("address")} testid="reg-address" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                <div>
                  <Label className="text-sm text-ink">{t("auth.state")} *</Label>
                  <Select value={form.state} onValueChange={(v) => setForm((f) => ({ ...f, state: v, city: "" }))}>
                    <SelectTrigger className="mt-1.5 h-11 rounded-lg" data-testid="reg-state"><SelectValue placeholder="Select" /></SelectTrigger>
                    <SelectContent className="max-h-64">{STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-sm text-ink">{t("auth.city")} *</Label>
                  <Select value={form.city} onValueChange={(v) => setForm((f) => ({ ...f, city: v }))} disabled={!form.state}>
                    <SelectTrigger className="mt-1.5 h-11 rounded-lg" data-testid="reg-city"><SelectValue placeholder={form.state ? "Select" : "State first"} /></SelectTrigger>
                    <SelectContent className="max-h-64">{[...(CITIES[form.state] || []), "Other"].map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <Field label={`${t("auth.pincode")} *`} value={form.pincode} onChange={set("pincode")} required testid="reg-pincode" />
              </div>
              <Button type="submit" disabled={loading} className="h-11 w-full rounded-full bg-forest hover:bg-brand" data-testid="reg-submit">
                {loading ? t("common.loading") : "Submit Registration Request"}
              </Button>
            </form>

            <p className="mt-6 text-center text-sm text-muted2">
              {t("auth.haveAccount")} <Link to="/login" className="font-semibold text-forest hover:underline" data-testid="to-login">{t("cta.login")}</Link>
            </p>
          </motion.div>
        )}
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
