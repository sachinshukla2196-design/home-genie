import React, { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, UserPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const EMPTY = { business_name: "", full_name: "", mobile: "", email: "" };
const MOBILE = /^[6-9]\d{9}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Admin form that creates a vendor account (draft). The vendor then signs in at the normal login and completes their profile. */
export function VendorAccountForm({ onCreated }) {
  const { t } = useI18n();
  const [f, setF] = useState(EMPTY);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState(null);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const problems = {
    business_name: f.business_name.trim().length < 2 ? "avc.errBusiness" : null,
    full_name: f.full_name.trim().length < 2 ? "avc.errName" : null,
    mobile: MOBILE.test(f.mobile.trim()) ? null : "avc.errMobile",
    email: !f.email.trim() || EMAIL.test(f.email.trim()) ? null : "avc.errEmail",
  };
  const valid = Object.values(problems).every((p) => !p);

  const submit = async (e) => {
    e.preventDefault();
    setTried(true);
    if (!valid || busy) return;
    setBusy(true);
    try {
      const { data } = await API.post("/admin/vendors/create", { business_name: f.business_name.trim(), full_name: f.full_name.trim(), mobile: f.mobile.trim(), email: f.email.trim() });
      setCreated(data);
      setF(EMPTY);
      setTried(false);
      toast.success(t("avc.done"));
      if (onCreated) onCreated(data);
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  };

  const field = (key, label, id, type = "text", extra = {}) => (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-ink">{label}</label>
      <Input id={id} type={type} value={f[key]} onChange={set(key)} className="mt-1.5" data-testid={`avc-${key}`} aria-invalid={tried && !!problems[key]} {...extra} />
      {tried && problems[key] && <p role="alert" className="mt-1 text-xs text-danger">{t(problems[key])}</p>}
    </div>
  );

  if (created) {
    const inv = created.invitation || {};
    const link = inv.token ? `${window.location.origin}/vendor/owner-invite?token=${inv.token}` : null;
    return (
      <SectionCard title={t("avc.createdTitle")} icon={UserPlus} testid="avc-created">
        <p className="text-sm text-ink" data-testid="avc-created-code">{t("avc.createdBody", { code: created.vendor_code })}</p>
        {inv.delivered
          ? <p className="mt-2 text-sm text-ink" data-testid="avc-emailed">{t("avc.emailed")}</p>
          : link && (
            <div className="mt-4" data-testid="avc-link-box">
              <p className="text-sm text-ink">{t("avc.linkNote", { hours: 72 })}</p>
              <code className="mt-2 block break-all rounded-lg bg-white/5 px-3 py-2 text-xs text-ink ring-1 ring-white/15" data-testid="avc-link">{link}</code>
            </div>
          )}
        <div className="mt-4 flex flex-wrap gap-3">
          <Button variant="outline" className="h-10 rounded-full" onClick={() => setCreated(null)}>{t("avc.another")}</Button>
        </div>
      </SectionCard>
    );
  }

  return (
    <SectionCard title={t("avc.title")} icon={UserPlus} testid="avc-card">
      <p className="mb-4 text-sm text-muted2">{t("avc.sub")}</p>
      <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2" data-testid="avc-form">
        {field("business_name", t("avc.business"), "avc-business")}
        {field("full_name", t("avc.name"), "avc-name")}
        {field("mobile", t("avc.mobile"), "avc-mobile", "tel", { inputMode: "numeric", maxLength: 10 })}
        {field("email", t("avc.email"), "avc-email", "email")}
        <div className="sm:col-span-2">
          <Button type="submit" disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="avc-submit">{t("avc.submit")}</Button>
        </div>
      </form>
    </SectionCard>
  );
}

/** Separate page for creating a vendor account (same form as the Vendors page). */
export default function AdminVendorCreate() {
  const { t } = useI18n();
  return (
    <div className="space-y-6" data-testid="admin-vendor-create">
      <PageHeader title={t("avc.title")} subtitle={t("avc.sub")} icon={UserPlus}
        actions={<Link to="/admin/vendors" className="hg-icon-btn inline-flex h-10 items-center gap-2 rounded-full px-4 text-sm font-medium"><ArrowLeft size={15} /> {t("avc.back")}</Link>} />
      <VendorAccountForm />
    </div>
  );
}
