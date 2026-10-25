import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
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
    <div className="mx-auto max-w-lg space-y-6 px-4 py-10" data-testid="vendor-owner-invite">
      <PageHeader title={t("oi.title")} subtitle={info ? t("oi.sub", { business: info.business_name }) : undefined} icon={ShieldCheck} />
      {error && <p role="alert" className="hg-card p-5 text-sm text-danger" data-testid="owner-invite-error">{t("oi.invalid")}</p>}
      {!error && !info && <p className="text-sm text-muted2">{t("vx.loading")}</p>}
      {info && !done && (
        <SectionCard title={t("oi.setPassword")} testid="owner-invite-form-card">
          <p className="mb-4 text-xs text-muted2">{t("oi.mobileHint", { hint: info.mobile_hint })}</p>
          <form onSubmit={submit} noValidate className="grid gap-4" data-testid="owner-invite-form">
            <div>
              <label htmlFor="oi-pw" className="text-sm font-medium text-ink">{t("oi.password")}</label>
              <Input id="oi-pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} className="mt-1.5" data-testid="owner-invite-password" />
              <p className="mt-1 text-xs text-muted2">{t("oi.passwordHint")}</p>
              {tried && !strong && <p role="alert" className="mt-1 text-xs text-danger">{t("oi.errPassword")}</p>}
            </div>
            <div>
              <label htmlFor="oi-confirm" className="text-sm font-medium text-ink">{t("oi.confirm")}</label>
              <Input id="oi-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} className="mt-1.5" data-testid="owner-invite-confirm" />
              {tried && !same && <p role="alert" className="mt-1 text-xs text-danger">{t("oi.errConfirm")}</p>}
            </div>
            <Button type="submit" disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="owner-invite-submit">{t("oi.submit")}</Button>
          </form>
        </SectionCard>
      )}
      {done && (
        <SectionCard title={t("oi.doneTitle")} testid="owner-invite-done">
          <p className="text-sm text-ink">{t("oi.doneBody")}</p>
          <Link to="/login" className="hg-btn mt-4 inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold">{t("oi.signIn")}</Link>
        </SectionCard>
      )}
    </div>
  );
}
