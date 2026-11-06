import React, { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, UserPlus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { VButton, VCard, VField, VInput } from "@/components/vendor/VendorUI";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const EMPTY = { business_name: "", full_name: "", mobile: "", email: "" };
const MOBILE = /^[6-9]\d{9}$/;
const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

/** Admin form that starts a vendor registration (onboarding). No login or invitation exists until a super admin approves it. */
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
      toast.success("Registration started");
      if (onCreated) onCreated(data);
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setBusy(false);
    }
  };

  const field = (key, label, id, type = "text", extra = {}, optional = false) => (
    <VField id={id} label={label} required={!optional} optional={optional} error={tried && problems[key] ? t(problems[key]) : null}>
      <VInput id={id} type={type} value={f[key]} onChange={set(key)} data-testid={`avc-${key}`} invalid={tried && !!problems[key]} {...extra} />
    </VField>
  );

  if (created) {
    return (
      <VCard className="p-5 sm:p-6" data-testid="avc-created">
        <h2 className="hgv-title text-xl font-semibold">Registration started</h2>
        <p className="hgv-muted mt-1 text-sm" data-testid="avc-created-code">{created.vendor_code} is in onboarding. Complete the registration; a super admin gives final approval,
          and the owner gets their sign-in link only then.</p>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <VButton variant="primary" to={`/admin/vendors/${created.vendor_id}/onboarding`} data-testid="avc-continue">Continue registration</VButton>
          <VButton variant="secondary" onClick={() => setCreated(null)}>{t("avc.another")}</VButton>
        </div>
      </VCard>
    );
  }

  return (
    <VCard className="p-5 sm:p-6" data-testid="avc-card">
      <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><UserPlus size={19} className="text-aurum-600" aria-hidden /> Start a vendor registration</h2>
      <p className="hgv-muted mb-4 mt-1 text-sm">For a vendor HOME GENIES is onboarding directly. Use the business's own mobile and email: existing customer or HomeGenie accounts are never converted.</p>
      <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2" data-testid="avc-form">
        {field("business_name", t("avc.business"), "avc-business")}
        {field("full_name", t("avc.name"), "avc-name")}
        {field("mobile", t("avc.mobile"), "avc-mobile", "tel", { inputMode: "numeric", maxLength: 10 })}
        {field("email", t("avc.email"), "avc-email", "email", {}, true)}
        <div className="sm:col-span-2">
          <VButton type="submit" variant="primary" icon={UserPlus} busy={busy} data-testid="avc-submit">Start registration</VButton>
        </div>
      </form>
    </VCard>
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
