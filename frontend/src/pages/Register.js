import React, { useState } from "react";
import { Link, useSearchParams, useLocation } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Check, CheckCircle2, KeyRound, MapPin, ShieldCheck, UserRound, Users } from "lucide-react";
import { Stagger, StaggerItem } from "@/components/motion";
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

  const spinner = <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />;

  return (
    <div className="relative isolate grid min-h-screen overflow-hidden lg:grid-cols-2" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      <span aria-hidden="true" className="pointer-events-none absolute -left-24 top-10 -z-10 h-72 w-72 rounded-full bg-hg-violet/25 blur-3xl" />
      <span aria-hidden="true" className="pointer-events-none absolute -bottom-24 right-1/3 -z-10 h-72 w-72 rounded-full bg-hg-pink/15 blur-3xl" />

      <div className="flex min-w-0 flex-col px-4 pb-10 pt-4 sm:p-10">
        <div className="flex items-center justify-between gap-3">
          <Link to="/" className="min-w-0"><Logo size="sm" /></Link>
          <LanguageSwitcher />
        </div>

        {done ? (
          <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="hg-glass mx-auto mt-16 w-full max-w-md p-6 text-center sm:p-8" data-testid="register-pending">
            <motion.div initial={{ scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 320, damping: 14, delay: 0.1 }}
              className="relative mx-auto flex h-20 w-20 items-center justify-center rounded-full bg-hg-success/15 text-hg-success ring-1 ring-hg-success/30">
              <span aria-hidden="true" className="absolute inset-0 -z-10 rounded-full bg-hg-success/20 blur-xl" />
              <CheckCircle2 size={40} />
            </motion.div>
            <h1 className="mt-6 font-display text-2xl font-semibold text-ink">Request submitted</h1>
            <p className="mt-2 leading-relaxed text-muted2">Your registration has been submitted.<br />Our team will review and approve your HomeGenie account. You'll be able to log in once your HomeGenie ID is created.</p>
            <Link to="/login" className="mt-7 inline-block"><Button className="hg-btn h-11 rounded-full px-8" data-testid="pending-to-login">Go to Login</Button></Link>
          </motion.div>
        ) : (
          <Stagger className="mx-auto mt-6 w-full max-w-xl">
            <StaggerItem className="flex items-center gap-3 lg:hidden">
              <img src="/brand/logo-icon.png" alt="" className="hg-float h-12 w-12 rounded-2xl ring-1 ring-hg-violet/40" />
              <span className="text-sm text-muted2">{t("brand.tagline")}</span>
            </StaggerItem>
            <StaggerItem className="mt-4 lg:mt-0">
              <h1 className="font-display text-3xl font-semibold text-ink">{t("auth.createAccount")}</h1>
              <p className="mt-1 text-muted2">Fill in your details. Admin will review and approve your account.</p>
            </StaggerItem>

            <StaggerItem className="hg-glass mt-6 p-5 sm:p-7">
              {form.google_verified ? (
                <div className="flex items-start gap-3 rounded-2xl bg-hg-success/10 p-3 text-sm text-ink ring-1 ring-hg-success/30" data-testid="reg-google-note">
                  <ShieldCheck size={18} className="mt-0.5 shrink-0 text-hg-success" />
                  <span className="min-w-0 break-words">Verified with Google as <span className="font-semibold">{form.email}</span>. Just add your sponsor and details below.</span>
                </div>
              ) : (
                <>
                  <Button type="button" onClick={googleSignup} variant="outline" className="h-12 w-full gap-2 rounded-2xl border-brand-50 bg-transparent" data-testid="reg-google-btn">
                    <img src="https://www.gstatic.com/firebasejs/ui/2.0.0/images/auth/google.svg" alt="" className="h-4 w-4" />
                    Continue with Google
                  </Button>
                  <div className="my-5 flex items-center gap-3 text-xs text-muted2">
                    <span className="h-px flex-1 bg-brand-50" /> OR fill manually <span className="h-px flex-1 bg-brand-50" />
                  </div>
                </>
              )}

              <form onSubmit={submit} className="mt-5 space-y-4" data-testid="register-form">
                <Section icon={UserRound}>
                  <Field label={t("auth.fullName")} value={form.full_name} onChange={set("full_name")} required testid="reg-fullname" />
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Field label={t("auth.mobile")} value={form.mobile} onChange={set("mobile")} required testid="reg-mobile" />
                    <div className="min-w-0">
                      <Label className="text-sm text-ink">{t("auth.email")}</Label>
                      <Input type="email" value={form.email} onChange={set("email")} required readOnly={form.google_verified}
                             className={`mt-1.5 ${form.google_verified ? "opacity-70" : ""}`} data-testid="reg-email" />
                    </div>
                  </div>
                </Section>

                {!form.google_verified && (
                  <Section icon={KeyRound}>
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <Field label={t("auth.password")} type="password" value={form.password} onChange={set("password")} required testid="reg-password" />
                      <Field label={t("auth.confirmPassword")} type="password" value={form.confirm_password} onChange={set("confirm_password")} required testid="reg-confirm" />
                    </div>
                  </Section>
                )}

                <Section icon={Users}>
                  <Field label={t("auth.sponsorId")} value={form.sponsor_id} onChange={set("sponsor_id")} testid="reg-sponsor" />
                </Section>

                <Section icon={MapPin}>
                  <Field label={`${t("auth.address")} (optional)`} value={form.address} onChange={set("address")} testid="reg-address" />
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                    <div className="min-w-0">
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
                        className={`mt-1.5 ${pinNotice ? "border-hg-gold/70" : ""}`}
                        data-testid="reg-pincode"
                      />
                      <p className={`mt-1 flex items-center gap-1.5 text-xs ${pinNotice ? "text-hg-gold" : "text-muted2"}`} data-testid="reg-pincode-notice">
                        {pinLookup && !pinNotice && <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent" />}
                        <span>{pinNotice || (pinLookup ? "Detecting location…" : "State & city auto-fill from pincode")}</span>
                      </p>
                    </div>
                    <div className="min-w-0">
                      <Label className="text-sm text-ink">{t("auth.state")} *</Label>
                      <Select value={form.state} onValueChange={(v) => setForm((f) => ({ ...f, state: v, city: "" }))}>
                        <SelectTrigger className="mt-1.5 h-11 rounded-xl" data-testid="reg-state"><SelectValue placeholder="Select" /></SelectTrigger>
                        <SelectContent className="max-h-64">{STATES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                      </Select>
                    </div>
                    <div className="min-w-0">
                      <Label className="text-sm text-ink">{t("auth.city")} *</Label>
                      <Input
                        list="reg-city-options"
                        value={form.city}
                        onChange={set("city")}
                        disabled={!form.state}
                        placeholder={form.state ? "Select or type" : "State first"}
                        className="mt-1.5"
                        data-testid="reg-city"
                      />
                      <datalist id="reg-city-options">
                        {cityOptions.map((c) => <option key={c} value={c} />)}
                      </datalist>
                    </div>
                  </div>
                </Section>

                <Button type="submit" disabled={loading} className="hg-btn h-12 w-full rounded-2xl text-base font-semibold shadow-[0_12px_28px_-12px_rgba(168,85,247,0.8)] transition-transform hover:-translate-y-0.5 active:scale-[0.98]" data-testid="reg-submit">
                  {loading ? <span className="inline-flex items-center gap-2">{spinner}{t("common.loading")}</span> : "Submit Registration Request"}
                </Button>
              </form>
            </StaggerItem>

            <StaggerItem>
              <p className="mt-6 text-center text-sm text-muted2">
                {t("auth.haveAccount")} <Link to="/login" className="font-semibold text-hg-lavender hover:underline" data-testid="to-login">{t("cta.login")}</Link>
              </p>
            </StaggerItem>
          </Stagger>
        )}
      </div>

      <div className="hidden p-6 lg:block">
        <div className="hg-violet hg-sheen flex h-full min-h-[calc(100vh-3rem)] flex-col justify-between overflow-hidden rounded-[2rem] p-10 xl:p-12">
          <span aria-hidden="true" className="hg-orb pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-hg-pink/30 blur-3xl" />
          <span aria-hidden="true" className="hg-orb pointer-events-none absolute -bottom-24 -left-16 h-80 w-80 rounded-full bg-hg-violet/40 blur-3xl" />
          <motion.div initial={{ scale: 0.7, opacity: 0, rotate: -8 }} animate={{ scale: 1, opacity: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 200, damping: 16 }} className="relative w-fit">
            <span className="hg-logo-glow absolute inset-0 -z-10 rounded-full bg-hg-violet/50 blur-3xl" />
            <img src="/brand/logo-icon.png" alt="HOME GENIES" className="hg-float h-28 w-28 rounded-[1.75rem] object-cover shadow-2xl ring-1 ring-white/20" />
          </motion.div>
          <Stagger className="relative">
            <StaggerItem as="h2" className="font-display text-3xl font-semibold leading-snug xl:text-4xl">{t("landing.oppTitle")}</StaggerItem>
            <StaggerItem as="p" className="mt-3 max-w-md text-white/75">{t("brand.tagline")}</StaggerItem>
            <ul className="mt-8 space-y-3">
              {[t("landing.heroSub"), t("landing.oppSub"), t("auth.roleNote")].map((b) => (
                <StaggerItem as="li" key={b} className="flex items-start gap-3 rounded-2xl bg-white/[0.07] p-3.5 text-sm leading-relaxed text-white/85 ring-1 ring-white/10">
                  <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-hg-lavender/25 text-hg-lavender"><Check size={14} /></span>
                  <span>{b}</span>
                </StaggerItem>
              ))}
            </ul>
          </Stagger>
        </div>
      </div>
    </div>
  );
}

function Section({ icon: Icon, children }) {
  return (
    <div className="hg-tile relative space-y-4 p-4 sm:p-5">
      {Icon && <span aria-hidden="true" className="hg-icon-chip absolute -left-2 -top-2 !h-7 !w-7 !rounded-lg"><Icon size={14} /></span>}
      {children}
    </div>
  );
}

function Field({ label, type = "text", value, onChange, required, testid }) {
  return (
    <div className="min-w-0">
      <Label className="text-sm text-ink">{label}</Label>
      <Input type={type} value={value} onChange={onChange} required={required} className="mt-1.5" data-testid={testid} />
    </div>
  );
}
