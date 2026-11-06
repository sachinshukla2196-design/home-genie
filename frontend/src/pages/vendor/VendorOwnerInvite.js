import React, { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";
import { VendorPublicShell, VButton, VCard, VField, VInput, VBanner } from "@/components/vendor/VendorUI";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

/** The vendor owner opens their invitation link here and sets their own password. Nothing else is shown until the link is checked. */
export default function VendorOwnerInvite() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) { setError(true); return; }
    API.get("/vendor/invitation/owner", { params: { token } }).then(({ data }) => setInfo(data)).catch(() => setError(true));
  }, [token]);

  const strong = pw.length >= 8 && /[A-Za-z]/.test(pw) && /\d/.test(pw);
  const same = confirm !== "" && confirm === pw;

  const submit = async (e) => {
    e.preventDefault();
    setTried(true);
    if (!strong || !same || busy) return;
    setBusy(true);
    try {
      await API.post("/vendor/invitation/owner/accept", { token, password: pw });
      setDone(true);
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <VendorPublicShell>
      <div className="space-y-5" data-testid="vendor-owner-invite">
        <div className="text-center">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-choco-800 text-aurum-300 shadow-lg"><ShieldCheck size={26} aria-hidden /></span>
          <h1 className="hgv-title mt-4 text-3xl font-bold">{t("oi.title")}</h1>
          {info && <p className="hgv-muted mt-2 text-[15px]">{t("oi.sub", { business: info.business_name })}</p>}
        </div>
        {error && <VBanner tone="red" icon={ShieldCheck}><span data-testid="owner-invite-error">{t("oi.invalid")}</span></VBanner>}
        {!error && !info && <p className="hgv-muted text-center text-sm">{t("vx.loading")}</p>}
        {info && !done && (
          <VCard className="p-6 sm:p-7" data-testid="owner-invite-form-card">
            <h2 className="hgv-title text-xl font-semibold">{t("oi.setPassword")}</h2>
            <p className="hgv-muted mt-1 text-sm">{t("oi.mobileHint", { hint: info.mobile_hint })}</p>
            <form onSubmit={submit} noValidate className="mt-5 grid gap-4" data-testid="owner-invite-form">
              <VField id="oi-pw" label={t("oi.password")} required help={t("oi.passwordHint")} error={tried && !strong ? t("oi.errPassword") : null}>
                <VInput id="oi-pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} invalid={tried && !strong} data-testid="owner-invite-password" />
              </VField>
              <VField id="oi-confirm" label={t("oi.confirm")} required error={tried && !same ? t("oi.errConfirm") : null}>
                <VInput id="oi-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} invalid={tried && !same} data-testid="owner-invite-confirm" />
              </VField>
              <VButton type="submit" variant="primary" busy={busy} className="w-full" data-testid="owner-invite-submit">{t("oi.submit")}</VButton>
            </form>
          </VCard>
        )}
        {done && (
          <VCard className="p-6 text-center sm:p-7" data-testid="owner-invite-done">
            <h2 className="hgv-title text-xl font-semibold">{t("oi.doneTitle")}</h2>
            <p className="hgv-muted mt-2 text-sm">{t("oi.doneBody")}</p>
            <VButton to="/vendor/login" variant="primary" className="mt-5">{t("oi.signIn")}</VButton>
          </VCard>
        )}
      </div>
    </VendorPublicShell>
  );
}
