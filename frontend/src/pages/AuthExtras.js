import React, { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle2 } from "lucide-react";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Stagger, StaggerItem } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { homeRouteFor } from "@/lib/homeRoute";
import { API, apiError } from "@/lib/api";

const spinner = <span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />;
const primaryBtn = "hg-btn h-12 w-full rounded-2xl text-base font-semibold shadow-[0_12px_28px_-12px_rgba(168,85,247,0.8)] transition-transform hover:-translate-y-0.5 active:scale-[0.98]";

function Shell({ title, sub, children }) {
  return (
    <div className="relative isolate min-h-screen overflow-hidden px-4 pb-10" style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}>
      <span aria-hidden="true" className="pointer-events-none absolute -left-24 top-24 -z-10 h-72 w-72 rounded-full bg-hg-violet/25 blur-3xl" />
      <span aria-hidden="true" className="pointer-events-none absolute -right-24 bottom-10 -z-10 h-64 w-64 rounded-full bg-hg-pink/15 blur-3xl" />
      <div className="mx-auto w-full max-w-md">
        <div className="flex items-center justify-between gap-3 pt-4">
          <Link to="/" className="min-w-0"><Logo size="sm" /></Link>
          <LanguageSwitcher />
        </div>
        <Stagger className="mt-8">
          <StaggerItem className="text-center">
            <Link to="/" className="relative mx-auto block w-fit">
              <span className="hg-logo-glow absolute inset-0 -z-10 rounded-full bg-hg-violet/35 blur-3xl" />
              <motion.img src="/brand/logo-icon.png" alt="HOME GENIES" className="hg-float h-24 w-24 rounded-[1.6rem] object-cover shadow-2xl ring-1 ring-hg-violet/40"
                initial={{ scale: 0.7, opacity: 0, rotate: -8 }} animate={{ scale: 1, opacity: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 200, damping: 16 }} />
            </Link>
          </StaggerItem>
          <StaggerItem className="hg-glass mt-6 p-6">
            <div className="text-center">
              <h1 className="font-display text-2xl font-semibold text-ink">{title}</h1>
              <p className="mt-1 text-muted2">{sub}</p>
            </div>
            {children}
          </StaggerItem>
        </Stagger>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", testid }) {
  return (
    <div>
      <Label className="text-sm text-ink">{label}</Label>
      <Input type={type} value={value} onChange={onChange} className="mt-1.5 h-12 rounded-2xl" data-testid={testid} />
    </div>
  );
}

export function LoginOtp() {
  const { t } = useI18n();
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [mobile, setMobile] = useState("");
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);

  const send = async () => {
    setLoading(true);
    try {
      await API.post("/auth/login-otp/send", { mobile });
      toast.success("OTP sent to your mobile");
      setStep(2);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };
  const verify = async () => {
    setLoading(true);
    try {
      const { data } = await API.post("/auth/login-otp/verify", { mobile, otp });
      applyAuth(data); toast.success(t("auth.welcomeBack"));
      navigate(homeRouteFor(data.user));
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  return (
    <Shell title="Login with OTP" sub="Enter your registered mobile number">
      <div className="mt-6 space-y-4">
        <Field label={t("auth.mobile")} value={mobile} onChange={(e) => setMobile(e.target.value)} testid="otp-mobile" />
        <AnimatePresence initial={false}>
          {step === 2 && (
            <motion.div key="otp" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} exit={{ opacity: 0, height: 0 }} transition={{ duration: 0.3 }} className="-m-1 overflow-hidden p-1">
              <Field label={t("auth.otp")} value={otp} onChange={(e) => setOtp(e.target.value)} testid="otp-code" />
            </motion.div>
          )}
        </AnimatePresence>
        <Button onClick={step === 1 ? send : verify} disabled={loading} className={primaryBtn} data-testid="otp-submit">
          {loading ? <span className="inline-flex items-center gap-2">{spinner}{t("common.loading")}</span> : step === 1 ? t("auth.sendOtp") : t("cta.login")}
        </Button>
        <p className="text-center text-sm text-muted2"><Link to="/login" className="font-semibold text-hg-lavender hover:underline">Login with password</Link></p>
      </div>
    </Shell>
  );
}

export function ForgotPassword() {
  const { t } = useI18n();
  const [identifier, setIdentifier] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const submit = async () => {
    setLoading(true);
    try {
      await API.post("/auth/forgot/send", { identifier });
      setDone(true);
      toast.success("Request sent to the admin.");
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  return (
    <Shell title="Forgot password" sub="Request an admin-assisted password reset">
      <div className="mt-6 space-y-4">
        {done ? (
          <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }} transition={{ type: "spring", stiffness: 300, damping: 20 }}
            className="flex items-start gap-3 rounded-2xl bg-hg-success/10 px-4 py-4 text-sm leading-relaxed text-ink ring-1 ring-hg-success/30" data-testid="forgot-done">
            <CheckCircle2 size={20} className="mt-0.5 shrink-0 text-hg-success" />
            <span>Your request has been sent to the admin. Our team will reset your password and contact you shortly.</span>
          </motion.div>
        ) : (
          <>
            <Field label="HomeGenie ID or registered mobile" value={identifier} onChange={(e) => setIdentifier(e.target.value)} testid="forgot-identifier" />
            <p className="text-xs leading-relaxed text-muted2" data-testid="forgot-admin-note">There is no OTP. An admin will reset your password and share it with you.</p>
            <Button onClick={submit} disabled={loading || !identifier.trim()} className={primaryBtn} data-testid="forgot-submit">
              {loading ? <span className="inline-flex items-center gap-2">{spinner}{t("common.loading")}</span> : "Send request to admin"}
            </Button>
          </>
        )}
        <p className="text-center text-sm text-muted2"><Link to="/login" className="font-semibold text-hg-lavender hover:underline">{t("cta.back")} to login</Link></p>
      </div>
    </Shell>
  );
}
