import React, { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Eye, EyeOff, LogIn, Store } from "lucide-react";
import { VendorPublicShell, VButton, VCard, VField, VInput, VBanner } from "@/components/vendor/VendorUI";
import { useAuth } from "@/context/AuthContext";
import { homeRouteFor } from "@/lib/homeRoute";
import { API, apiError } from "@/lib/api";

/** Instant vendor sign-up is retired (Vendor Pillar). The public route is "Apply to sell"; old links land there. */
export function VendorRegister() {
  return <Navigate to="/vendor/apply" replace />;
}

/** Sign-in for approved vendor owners and their staff. Accounts still in onboarding or awaiting the invitation are refused by the server. */
export function VendorLogin() {
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    if (!id.trim() || !pw) { setError("Enter your mobile, email or vendor ID and your password."); return; }
    setBusy(true);
    setError("");
    try {
      const { data } = await API.post("/auth/login", { email: id.trim(), password: pw });
      applyAuth(data);
      if (data.user.role !== "vendor" && data.user.role !== "vendor_staff") toast.info("This is not a vendor account — taking you to your account.");
      navigate(homeRouteFor(data.user));
    } catch (err) {
      setError(apiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <VendorPublicShell>
      <VCard className="p-6 sm:p-8" data-testid="vendor-login-card">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-choco-800 text-aurum-300 shadow-lg"><Store size={26} aria-hidden /></span>
        <h1 className="hgv-title mt-5 text-3xl font-bold">Vendor login</h1>
        <p className="hgv-muted mt-1 text-[15px]">Manage your products, orders, dispatch and settlements.</p>
        {error && <VBanner tone="red" className="mt-5"><span data-testid="vl-error">{error}</span></VBanner>}
        <form onSubmit={submit} noValidate className="mt-6 grid gap-4" data-testid="vendor-login-form">
          <VField id="vl-id" label="Mobile, email or vendor ID" required>
            <VInput id="vl-id" value={id} onChange={(e) => setId(e.target.value)} autoComplete="username" placeholder="VD000001 / mobile / email" data-testid="vl-id" />
          </VField>
          <VField id="vl-password" label="Password" required>
            <div className="relative">
              <VInput id="vl-password" type={show ? "text" : "password"} value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" className="!pr-12" data-testid="vl-password" />
              <button type="button" onClick={() => setShow(!show)} className="absolute right-1 top-1/2 mt-0.5 flex h-11 w-11 -translate-y-1/2 items-center justify-center rounded-full text-choco-600 hover:bg-cream-200"
                      aria-label={show ? "Hide password" : "Show password"}>{show ? <EyeOff size={19} /> : <Eye size={19} />}</button>
            </div>
          </VField>
          <VButton type="submit" variant="primary" icon={LogIn} busy={busy} className="mt-1 w-full" data-testid="vl-submit">Sign in</VButton>
          <div className="text-right"><Link to="/forgot" className="text-sm font-semibold text-choco-600 underline-offset-2 hover:underline">Forgot password?</Link></div>
        </form>
        <div className="hgv-rule mt-6 grid gap-3 border-t pt-6">
          <p className="hgv-muted text-center text-sm">New to HOME GENIES as a supplier?</p>
          <VButton to="/vendor/apply" variant="secondary" className="w-full" data-testid="to-vendor-apply">Apply to sell</VButton>
          <p className="hgv-muted text-center text-sm">Shopping or selling as a HomeGenie? <Link to="/login" className="font-semibold text-choco-700 underline underline-offset-2">Log in here</Link></p>
        </div>
      </VCard>
      <p className="hgv-muted mt-5 text-center text-xs">Approved vendors receive a secure link to set their password. Until then, sign-in is not available.</p>
    </VendorPublicShell>
  );
}
