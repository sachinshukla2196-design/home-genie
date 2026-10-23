import React, { useState } from "react";
import { ShieldCheck, KeyRound, CheckCircle2, Circle } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Field, useAction } from "@/components/vendor/kit";

export const passwordChecks = (pw) => ({ length: pw.length >= 8, letters: /[A-Za-z]/.test(pw), digits: /\d/.test(pw) });

export default function VendorSecurity() {
  const { t } = useI18n();
  const [f, setF] = useState({ current_password: "", new_password: "", confirm: "" });
  const [run, busy] = useAction();
  const c = passwordChecks(f.new_password);
  const match = f.new_password === f.confirm && f.confirm.length > 0;
  const ok = c.length && c.letters && c.digits && match && f.current_password.length > 0 && f.new_password !== f.current_password;
  const submit = () => run(async () => {
    const { data } = await API.put("/auth/change-password", { current_password: f.current_password, new_password: f.new_password });
    if (data.token) localStorage.setItem("anj_token", data.token);   // keep THIS session signed in; every other session is signed out
    setF({ current_password: "", new_password: "", confirm: "" });
  }, { success: t("vx.sec.changed") });
  const Rule = ({ on, label }) => <li className={`flex items-center gap-2 text-xs ${on ? "text-hg-success" : "text-muted2"}`}>{on ? <CheckCircle2 size={13} aria-hidden /> : <Circle size={13} aria-hidden />} {label}</li>;
  return (
    <div className="space-y-5">
      <PageHeader title={t("vx.nav.security")} subtitle={t("vx.sec.sub")} icon={ShieldCheck} />
      <SectionCard title={t("vx.sec.changePassword")} icon={KeyRound} testid="sec-password">
        <form onSubmit={(e) => { e.preventDefault(); if (ok) submit(); }} className="max-w-md space-y-3" autoComplete="off">
          <Field label={t("vx.sec.current")} htmlFor="sec-cur"><Input id="sec-cur" type="password" autoComplete="current-password" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} data-testid="sec-current" /></Field>
          <Field label={t("vx.sec.new")} htmlFor="sec-new"><Input id="sec-new" type="password" autoComplete="new-password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} data-testid="sec-new" /></Field>
          <ul aria-label={t("vx.sec.rules")} className="space-y-1" data-testid="sec-rules"><Rule on={c.length} label={t("vx.sec.rule.length")} /><Rule on={c.letters} label={t("vx.sec.rule.letters")} /><Rule on={c.digits} label={t("vx.sec.rule.digits")} /></ul>
          <Field label={t("vx.sec.confirm")} htmlFor="sec-conf" error={f.confirm && !match ? t("vx.sec.mismatch") : undefined}><Input id="sec-conf" type="password" autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} data-testid="sec-confirm" /></Field>
          <Button type="submit" className="hg-btn h-11 rounded-full px-6" disabled={busy || !ok} data-testid="sec-submit">{t("vx.sec.update")}</Button>
        </form>
        <p className="mt-4 text-xs text-muted2">{t("vx.sec.signOutNote")}</p>
      </SectionCard>
      <SectionCard title={t("vx.sec.tips")} testid="sec-tips"><ul className="list-disc space-y-1 pl-5 text-sm text-muted2"><li>{t("vx.sec.tip1")}</li><li>{t("vx.sec.tip2")}</li><li>{t("vx.sec.tip3")}</li></ul></SectionCard>
    </div>
  );
}
