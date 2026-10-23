import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Store, Landmark, Receipt, Tags, Clock, AlertTriangle, CheckCircle2, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useVendor, VENDOR_STATUS_TONE } from "@/components/VendorLayout";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { Governance } from "@/components/vendor/Governance";

const PILLARS = ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"];
const PILLAR_KEY = { "Sarees": "pillar.sarees.t", "Fashion Products": "pillar.fashion.t", "Makeup, Beauty & Skincare": "pillar.beauty.t", "Household Essentials": "pillar.household.t" };
const EMPTY = { business_name: "", contact_person: "", phone: "", support_email: "", address: "", city: "", state: "", pincode: "",
  return_address: "", gstin: "", pan: "", bank_account_name: "", bank_account: "", ifsc: "", categories: [], agree_terms: false };

function Field({ label, value, onChange, testid, disabled, type = "text", required }) {
  return (
    <div>
      <Label className="text-sm text-ink">{label}{required && <span className="text-danger"> *</span>}</Label>
      <Input type={type} value={value} onChange={onChange} disabled={disabled} className="mt-1.5" data-testid={testid} />
    </div>
  );
}

export default function VendorProfile() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { vendor, reload } = useVendor();
  const navigate = useNavigate();
  const [f, setF] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (vendor === null) return;
    if (vendor) setF({ ...EMPTY, ...vendor, bank_account: "", pan: "", agree_terms: false });
    else setF({ ...EMPTY, contact_person: user?.full_name || "", phone: user?.mobile || "", support_email: user?.email || "" });
  }, [vendor, user]);

  if (!f) return <Skeleton className="h-96 rounded-3xl" />;

  const status = vendor ? vendor.status : "draft";
  const locked = status === "approved" || status === "suspended";
  const underReview = status === "submitted" || status === "under_review";
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const toggleCat = (c) => setF({ ...f, categories: f.categories.includes(c) ? f.categories.filter((x) => x !== c) : [...f.categories, c] });

  const save = async (submit) => {
    setBusy(true);
    try {
      await API.put("/vendor/me", { ...f, submit });
      await reload();
      toast.success(submit ? t("vp.onboard.pending") : t(locked ? "vp.saveContact" : "vp.saveDraft") + " ✓");
      if (locked) navigate("/vendor");
    } catch (err) { toast.error(apiError(err)); }
    finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title={vendor ? t("vp.profile") : t("vp.onboard.title")} subtitle={!locked ? t("vp.onboard.sub") : undefined} icon={Store}
        actions={vendor && <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${VENDOR_STATUS_TONE[status]}`} data-testid="vendor-profile-status">{t(`vp.st.${status}`)}</span>} />

      {underReview && <Banner icon={Clock} tone="gold" testid="vendor-pending">{t("vp.onboard.pending")}</Banner>}
      {status === "rejected" && <Banner icon={AlertTriangle} tone="danger" testid="vendor-rejected">{t("vp.onboard.rejected")} <b>{vendor.rejection_reason}</b></Banner>}
      {status === "suspended" && <Banner icon={AlertTriangle} tone="danger">{t("vp.onboard.suspended")} {vendor.status_reason && <b>{vendor.status_reason}</b>}</Banner>}
      {status === "approved" && <Banner icon={CheckCircle2} tone="success">{t("vp.st.approved")} · {vendor.vendor_code}</Banner>}

      <SectionCard title={t("vp.sec.business")} icon={Store}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("vp.f.business")} value={f.business_name} onChange={set("business_name")} disabled={locked || underReview} testid="vp-business" required />
          <Field label={t("vp.f.contact")} value={f.contact_person} onChange={set("contact_person")} disabled={underReview} testid="vp-contact" required />
          <Field label={t("vp.f.phone")} value={f.phone} onChange={set("phone")} disabled={underReview} testid="vp-phone" required />
          <Field label={t("vp.f.email")} value={f.support_email} onChange={set("support_email")} disabled={underReview} type="email" testid="vp-email" />
          <div className="sm:col-span-2"><Field label={t("vp.f.address")} value={f.address} onChange={set("address")} disabled={underReview} testid="vp-address" required /></div>
          <Field label={t("vp.f.city")} value={f.city} onChange={set("city")} disabled={underReview} testid="vp-city" />
          <Field label={t("vp.f.state")} value={f.state} onChange={set("state")} disabled={underReview} testid="vp-state" />
          <Field label={t("vp.f.pincode")} value={f.pincode} onChange={set("pincode")} disabled={underReview} testid="vp-pincode" />
          <Field label={t("vp.f.return")} value={f.return_address} onChange={set("return_address")} disabled={underReview} testid="vp-return" />
        </div>
      </SectionCard>

      {locked ? (
        <SectionCard title={t("vp.sec.bank")} icon={Lock}>
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <ReadOnly label={t("vp.f.bankName")} value={vendor.bank_account_name} />
            <ReadOnly label={t("vp.f.bank")} value={vendor.bank_account} />
            <ReadOnly label={t("vp.f.ifsc")} value={vendor.ifsc} />
            <ReadOnly label={t("vp.f.gstin")} value={vendor.gstin || "—"} />
            <div className="sm:col-span-2"><ReadOnly label={t("vp.sec.cats")} value={(vendor.categories || []).map((c) => t(PILLAR_KEY[c])).join(", ")} /></div>
          </div>
          <p className="mt-4 text-xs text-muted2">{t("vp.locked")}</p>
        </SectionCard>
      ) : (
        <>
          <SectionCard title={t("vp.sec.tax")} icon={Receipt}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("vp.f.gstin")} value={f.gstin} onChange={set("gstin")} disabled={underReview} testid="vp-gstin" />
              <Field label={t("vp.f.pan")} value={f.pan} onChange={set("pan")} disabled={underReview} testid="vp-pan" />
            </div>
          </SectionCard>
          <SectionCard title={t("vp.sec.bank")} icon={Landmark}>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={t("vp.f.bankName")} value={f.bank_account_name} onChange={set("bank_account_name")} disabled={underReview} testid="vp-bank-name" required />
              <Field label={t("vp.f.bank")} value={f.bank_account} onChange={set("bank_account")} disabled={underReview} testid="vp-bank" required />
              <Field label={t("vp.f.ifsc")} value={f.ifsc} onChange={set("ifsc")} disabled={underReview} testid="vp-ifsc" required />
            </div>
          </SectionCard>
          <SectionCard title={t("vp.f.categories")} icon={Tags}>
            <div className="flex flex-wrap gap-2" role="group" aria-label={t("vp.f.categories")}>
              {PILLARS.map((c) => {
                const on = f.categories.includes(c);
                return (
                  <button key={c} type="button" disabled={underReview} onClick={() => toggleCat(c)} aria-pressed={on} data-testid={`vp-cat-${c}`}
                    className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${on ? "hg-chip-on" : "hg-chip-off"}`}>
                    {on ? "✓ " : ""}{t(PILLAR_KEY[c])}
                  </button>
                );
              })}
            </div>
          </SectionCard>
          {!underReview && (
            <label className="hg-card flex cursor-pointer items-start gap-3 p-5 text-sm text-ink">
              <input type="checkbox" checked={f.agree_terms} onChange={(e) => setF({ ...f, agree_terms: e.target.checked })}
                className="mt-0.5 h-4 w-4 accent-[#8B3DFF]" data-testid="vp-terms" />
              <span>{t("vp.f.terms")}</span>
            </label>
          )}
        </>
      )}

      {!underReview && (
        <div className="flex flex-wrap justify-end gap-3">
          {locked ? (
            <Button onClick={() => save(false)} disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="vp-save-contact">{t("vp.saveContact")}</Button>
          ) : (
            <>
              <Button onClick={() => save(false)} disabled={busy} variant="outline" className="h-11 rounded-full border-brand-50 bg-transparent px-6" data-testid="vp-save-draft">{t("vp.saveDraft")}</Button>
              <Button onClick={() => save(true)} disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="vp-submit">{t("vp.submit")}</Button>
            </>
          )}
        </div>
      )}

      <Governance approved={status === "approved"} />
    </div>
  );
}

function Banner({ icon: Icon, tone, children, testid }) {
  const tones = { gold: "bg-hg-gold/10 ring-hg-gold/30 text-ink", danger: "bg-danger/10 ring-danger/30 text-ink", success: "bg-hg-success/10 ring-hg-success/30 text-ink" };
  const ic = { gold: "text-hg-gold", danger: "text-danger", success: "text-hg-success" };
  return <div className={`flex items-start gap-3 rounded-2xl p-4 text-sm ring-1 ${tones[tone]}`} data-testid={testid}><Icon size={18} className={`mt-0.5 shrink-0 ${ic[tone]}`} /><div>{children}</div></div>;
}

function ReadOnly({ label, value }) {
  return <div className="hg-tile p-3"><div className="text-xs text-muted2">{label}</div><div className="mt-0.5 font-medium text-ink">{value || "—"}</div></div>;
}
