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

function Shell({ title, sub, children }) {
  return (
    <div className="flex min-h-screen flex-col p-6 sm:p-12">
      <div className="flex items-center justify-between">
        <Link to="/"><Logo /></Link>
        <LanguageSwitcher />
      </div>
      <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} className="mx-auto mt-16 w-full max-w-sm">
        <h1 className="font-display text-3xl font-semibold text-ink">{title}</h1>
        <p className="mt-1 text-muted2">{sub}</p>
        {children}
      </motion.div>
    </div>
  );
}

function Field({ label, value, onChange, type = "text", testid }) {
  return (
    <div>
      <Label className="text-sm text-ink">{label}</Label>
      <Input type={type} value={value} onChange={onChange} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} />
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
      const { data } = await API.post("/auth/login-otp/send", { mobile });
      if (data.dev_otp) { setOtp(data.dev_otp); toast.info(`Demo OTP: ${data.dev_otp}`, { duration: 8000 }); }
      else toast.success(data.test_number ? "Use test OTP 123456" : "OTP sent to your mobile");
      setStep(2);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };
  const verify = async () => {
    setLoading(true);
    try {
      const { data } = await API.post("/auth/login-otp/verify", { mobile, otp });
      applyAuth(data); toast.success(t("auth.welcomeBack"));
      const roles = ["super_admin", "admin", "accounts_admin", "support_admin"];
      navigate(roles.includes(data.user.role) ? "/admin" : "/app/dashboard");
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  return (
    <Shell title="Login with OTP" sub="Enter your registered mobile number">
      <div className="mt-8 space-y-4">
        <Field label={t("auth.mobile")} value={mobile} onChange={(e) => setMobile(e.target.value)} testid="otp-mobile" />
        {step === 2 && <Field label={t("auth.otp")} value={otp} onChange={(e) => setOtp(e.target.value)} testid="otp-code" />}
        <Button onClick={step === 1 ? send : verify} disabled={loading} className="h-11 w-full rounded-full btn-grad" data-testid="otp-submit">
          {loading ? t("common.loading") : step === 1 ? t("auth.sendOtp") : t("cta.login")}
        </Button>
        <p className="text-center text-sm text-muted2"><Link to="/login" className="font-semibold text-forest hover:underline">Login with password</Link></p>
      </div>
    </Shell>
  );
}

export function ForgotPassword() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const send = async () => {
    setLoading(true);
    try {
      const { data } = await API.post("/auth/forgot/send", { email });
      if (data.dev_otp) { setOtp(data.dev_otp); toast.info(`Demo code: ${data.dev_otp}`, { duration: 8000 }); }
      else toast.success("A reset code has been sent to your email.");
      setStep(2);
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };
  const reset = async () => {
    setLoading(true);
    try {
      await API.post("/auth/forgot/reset", { email, otp, password });
      toast.success("Password updated. Please log in.");
      navigate("/login");
    } catch (e) { toast.error(apiError(e)); } finally { setLoading(false); }
  };

  return (
    <Shell title="Forgot password" sub="We'll email you a reset code">
      <div className="mt-8 space-y-4">
        <Field label={t("auth.email")} type="email" value={email} onChange={(e) => setEmail(e.target.value)} testid="forgot-email" />
        <p className="text-xs text-muted2" data-testid="forgot-no-email-note">No email on your account? Please contact the admin to reset your password.</p>
        {step === 2 && <>
          <Field label="Reset code (from email)" value={otp} onChange={(e) => setOtp(e.target.value)} testid="forgot-otp" />
          <Field label="New password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} testid="forgot-password" />
        </>}
        <Button onClick={step === 1 ? send : reset} disabled={loading} className="h-11 w-full rounded-full btn-grad" data-testid="forgot-submit">
          {loading ? t("common.loading") : step === 1 ? "Send reset code" : "Reset password"}
        </Button>
        <p className="text-center text-sm text-muted2"><Link to="/login" className="font-semibold text-forest hover:underline">{t("cta.back")} to login</Link></p>
      </div>
    </Shell>
  );
}
