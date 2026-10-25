import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const MOBILE = /^[6-9]\d{9}$/;

/** Public page a staff member opens from their invitation link. It shows only what the invitation allows and sets their own password. */
export default function VendorStaffInvite() {
  const { t } = useI18n();
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [f, setF] = useState({ mobile: "", full_name: "", password: "", confirm: "" });
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (!token) { setError("vx.invite.invalid"); return; }
    API.get("/vendor/staff/invitation", { params: { token } })
      .then(({ data }) => setInfo(data))
      .catch(() => setError("vx.invite.invalid"));
    // the page only depends on the token in the link
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const problems = {
    mobile: MOBILE.test(f.mobile.trim()) ? null : "vx.invite.errMobile",
    full_name: f.full_name.trim().length < 2 ? "vx.invite.errName" : null,
    password: f.password.length >= 8 && /[A-Za-z]/.test(f.password) && /\d/.test(f.password) ? null : "vx.invite.errPassword",
    confirm: f.confirm === f.password && f.confirm ? null : "vx.invite.errConfirm",
  };
  const valid = Object.values(problems).every((p) => !p);

  const submit = async (e) => {
    e.preventDefault();
    setTried(true);
    if (!valid || busy) return;
    setBusy(true);
    try {
      await API.post("/vendor/staff/accept", { token, mobile: f.mobile.trim(), full_name: f.full_name.trim(), password: f.password });
      setDone(true);
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  };

  const field = (key, label, id, type = "text", extra = {}) => (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-ink">{label}</label>
      <Input id={id} type={type} value={f[key]} onChange={(e) => setF({ ...f, [key]: e.target.value })} className="mt-1.5" data-testid={`invite-${key}`} {...extra} />
      {tried && problems[key] && <p role="alert" className="mt-1 text-xs text-danger">{t(problems[key])}</p>}
    </div>
  );

  return (
    <div className="mx-auto max-w-lg space-y-6 px-4 py-10" data-testid="vendor-invite">
      <PageHeader title={t("vx.invite.title")} subtitle={info ? t("vx.invite.sub", { business: info.business_name, role: t(`vx.staff.role.${info.role}`) }) : undefined} icon={UserPlus} />
      {error && <p role="alert" className="hg-card p-5 text-sm text-danger" data-testid="invite-error">{t(error)}</p>}
      {!error && !info && <p className="text-sm text-muted2">{t("vx.loading")}</p>}
      {info && !done && (
        <SectionCard title={t("vx.invite.formTitle")} testid="invite-form-card">
          <p className="mb-4 text-xs text-muted2">{t("vx.invite.mobileHint", { hint: info.mobile_hint })}</p>
          <form onSubmit={submit} noValidate className="grid gap-4" data-testid="invite-form">
            {field("mobile", t("vx.invite.mobile"), "inv-mobile", "tel", { inputMode: "numeric", maxLength: 10 })}
            {field("full_name", t("vx.invite.name"), "inv-name")}
            {field("password", t("vx.invite.password"), "inv-password", "password", { autoComplete: "new-password" })}
            <p className="-mt-2 text-xs text-muted2">{t("vx.invite.passwordHint")}</p>
            {field("confirm", t("vx.invite.confirm"), "inv-confirm", "password", { autoComplete: "new-password" })}
            <Button type="submit" disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="invite-submit">{t("vx.invite.submit")}</Button>
          </form>
        </SectionCard>
      )}
      {done && (
        <SectionCard title={t("vx.invite.doneTitle")} testid="invite-done">
          <p className="text-sm text-ink">{t("vx.invite.doneBody")}</p>
          <Link to="/login" className="hg-btn mt-4 inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold">{t("vx.invite.signIn")}</Link>
        </SectionCard>
      )}
    </div>
  );
}
