import React, { useState } from "react";
import { Link, useSearchParams, useLocation } from "react-router-dom";
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
  const location = useLocation();
  const gEmail = location.state?.googleEmail || "";
  const gName = location.state?.googleName || "";
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [pinLookup, setPinLookup] = useState(false);
  const [pinNotice, setPinNotice] = useState("");
  const [form, setForm] = useState({
    full_name: gName, mobile: "", email: gEmail, password: "", confirm_password: "",
    sponsor_id: params.get("ref") || "", aadhaar_number: "", address: "", state: "", city: "", pincode: "",
    google_verified: !!gEmail,
  });

  const googleSignup = () => {
    // REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    window.location.href = `https://auth.emergentagent.com/?redirect=${encodeURIComponent(window.location.origin + "/register")}`;
  };
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target?.value ?? e }));

  const cityOptions = Array.from(new Set([
    ...(form.city ? [form.city] : []),
    ...(CITIES[form.state] || []),
    "Other",
  ]));

  const matchState = (name) => {
    if (!name) return "";
    const norm = (s) => s.toLowerCase().replace(/[^a-z]/g, "");
    return STATES.find((s) => norm(s) === norm(name)) || "";
  };

  const lookupPincode = async (pin) => {
    const code = pin.trim();
    if (!/^\d{6}$/.test(code)) return;
    setPinLookup(true);
    setPinNotice("");
    try {
      const res = await fetch(`https://api.postalpincode.in/pincode/${code}`);
      const json = await res.json();
      const po = json?.[0]?.PostOffice;
      if (!po || !po.length) {
        setPinNotice("We couldn't find this pincode. Please pick your state and city manually.");
        return;
      }
      const st = matchState(po[0].State);
      const district = po[0].District || "";
      setForm((f) => ({ ...f, state: st || f.state, city: district || f.city }));
    } catch {
      setPinNotice("Couldn't look up the pincode right now. Please pick your state and city manually.");
    } finally {
      setPinLookup(false);
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!/^[6-9]\d{9}$/.test(form.mobile.trim())) return toast.error("Enter a valid 10-digit mobile number.");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email.trim())) return toast.error("A valid email address is required.");
    if (!form.google_verified) {
      if (form.password.length < 6) return toast.error("Password must be at least 6 characters.");
      if (form.password !== form.confirm_password) return toast.error("Passwords do not match.");
    }
    if (!form.sponsor_id.trim()) return toast.error("Please enter a valid Referral / Sponsor ID.");
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
            <p className="mt-2 text-muted2">Your registration has been submitted.<br />Our team will review and approve your HomeGenie account. You'll be able to log in once your HomeGenie ID is created.</p>
            <Link to="/login"><Button className="mt-6 h-11 rounded-full bg-forest px-8 hover:bg-brand" data-testid="pending-to-login">Go to Login</Button></Link>
          </motion.div>
        ) : (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mx-auto mt-8 w-full max-w-md">
            <h1 className="font-display text-3xl font-semibold text-ink">{t("auth.createAccount")}</h1>
            <p className="mt-1 text-muted2">Fill in your details. Admin will review and approve your account.</p>

            {form.google_verified ? (
              <div className="mt-5 rounded-xl border border-forest/20 bg-forest/5 p-3 text-sm text-forest" data-testid="reg-google-note">
                Verified with Google as <span className="font-semibold">{form.email}</span>. Just add your sponsor and details below.
              </div>
            ) : (
              <>
                <Button type="button" onClick={googleSignup} variant="outline" className="mt-5 h-11 w-full rounded-full gap-2 border-brand-50" data-testid="reg-google-btn">
                  <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="" className="h-4 w-4" />
                  Continue with Google
                </Button>
                <div className="my-4 flex items-center gap-3 text-xs text-muted2">
                  <span className="h-px flex-1 bg-brand-50" /> OR fill manually <span className="h-px flex-1 bg-brand-50" />
                </div>
              </>
            )}

            <form onSubmit={submit} className="mt-2 space-y-3.5" data-testid="register-form">
              <Field label={t("auth.fullName")} value={form.full_name} onChange={set("full_name")} required testid="reg-fullname" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={t("auth.mobile")} value={form.mobile} onChange={set("mobile")} required testid="reg-mobile" />
                <div>
                  <Label className="text-sm text-ink">{t("auth.email")}</Label>
                  <Input type="email" value={form.email} onChange={set("email")} required readOnly={form.google_verified}
                         className={`mt-1.5 h-11 rounded-lg focus-visible:ring-brand ${form.google_verified ? "bg-muted/40" : ""}`} data-testid="reg-email" />
                </div>
              </div>
              {!form.google_verified && (
                <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                  <Field label={t("auth.password")} type="password" value={form.password} onChange={set("password")} required testid="reg-password" />
                  <Field label={t("auth.confirmPassword")} type="password" value={form.confirm_password} onChange={set("confirm_password")} required testid="reg-confirm" />
                </div>
              )}
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
                <Field label={t("auth.sponsorId")} value={form.sponsor_id} onChange={set("sponsor_id")} testid="reg-sponsor" />
              </div>
              <Field label={`${t("auth.address")} (optional)`} value={form.address} onChange={set("address")} testid="reg-address" />
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
                <div>
                  <Label className="text-sm text-ink">{t("auth.pincode")} *</Label>
                  <Input
                    value={form.pincode}
                    onChange={(e) => {
                      const v = e.target.value.replace(/\D/g, "").slice(0, 6);
                      setForm((f) => ({ ...f, pincode: v }));
                      setPinNotice("");
                      if (v.length === 6) lookupPincode(v);
                    }}
                    inputMode="numeric"
                    maxLength={6}
                    required
                    className={`mt-1.5 h-11 rounded-lg focus-visible:ring-brand ${pinNotice ? "border-amber-400" : ""}`}
                    data-testid="reg-pincode"
                  />
                  <p className={`mt-1 text-xs ${pinNotice ? "text-amber-600" : "text-muted2"}`} data-testid="reg-pincode-notice">
                    {pinNotice || (pinLookup ? "Detecting location…" : "State & city auto-fill from pincode")}
                  </p>
                </div>
                <div>
                  <Label className="text-sm text-ink">{t("auth.state")} *</Label>
                  <Select value={form.state} onValueChange={(v) => setForm((f) => ({ ...f, state: v, city: "" }))}>
                    <SelectTrigger className="mt-1.5 h-11 rounded-lg" data-testid="reg-state"><SelectValue placeholder="Select" /></SelectTrigger>
                    <SelectContent className="max-h-64">{STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-sm text-ink">{t("auth.city")} *</Label>
                  <Input
                    list="reg-city-options"
                    value={form.city}
                    onChange={set("city")}
                    disabled={!form.state}
                    placeholder={form.state ? "Select or type" : "State first"}
                    className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand"
                    data-testid="reg-city"
                  />
                  <datalist id="reg-city-options">
                    {cityOptions.map((c) => <option key={c} value={c} />)}
                  </datalist>
                </div>
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
