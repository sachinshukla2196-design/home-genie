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
import { INDIAN_STATES } from "@/lib/vendorOptions";

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
  // Batch 14 (VEN-05): the server says what may be edited in this status, what needs approval, and what is outstanding
  const [ov, setOv] = useState(null);
  useEffect(() => { API.get("/vendor/me/profile-overview").then(({ data }) => setOv(data)).catch(() => setOv(null)); }, [vendor]);

  useEffect(() => {
    if (vendor === null) return;
    if (vendor) setF({ ...EMPTY, ...vendor, bank_account: "", pan: "", agree_terms: false });
    else setF({ ...EMPTY, contact_person: user?.full_name || "", phone: user?.mobile || "", support_email: user?.email || "" });
  }, [vendor, user]);

  if (!f) return <Skeleton className="h-96 rounded-3xl" />;

  const status = vendor ? vendor.status : "draft";
  const mode = ov?.mode || "full";
  const locked = mode === "contact_only";
  const underReview = mode === "in_review" || mode === "onboarding";
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

      {mode === "onboarding" && <Banner icon={Clock} tone="gold" testid="vendor-onboarding">HOME GENIES is completing your registration with you. The details below are read-only until it is approved.</Banner>}
      {mode === "in_review" && <Banner icon={Clock} tone="gold" testid="vendor-pending">{t("vp.onboard.pending")}</Banner>}
      {ov && ov.vendor && <ProfileOverview ov={ov} />}
      {status === "rejected" && <Banner icon={AlertTriangle} tone="danger" testid="vendor-rejected">{t("vp.onboard.rejected")} <b>{vendor.rejection_reason}</b></Banner>}
      {status === "changes_requested" && <Banner icon={AlertTriangle} tone="danger" testid="vendor-changes-requested">{t("vp.onboard.changesRequested")} <b>{vendor.status_reason}</b></Banner>}
      {status === "pending_documents" && <Banner icon={AlertTriangle} tone="gold" testid="vendor-pending-docs">{t("vp.onboard.pendingDocs")} {vendor.status_reason && <b>{vendor.status_reason}</b>}</Banner>}
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
          <div>
            <Label className="text-sm text-ink">{t("vp.f.state")}</Label>
            <select value={f.state || ""} onChange={set("state")} disabled={underReview} data-testid="vp-state"
              className="mt-1.5 h-10 w-full rounded-md bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15">
              <option value="">Choose…</option>{INDIAN_STATES.map((x) => <option key={x} value={x}>{x}</option>)}
              {f.state && !INDIAN_STATES.includes(f.state) && <option value={f.state}>{f.state}</option>}
            </select>
          </div>
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
                className="mt-0.5 h-4 w-4 accent-[#5C3A26]" data-testid="vp-terms" />
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


const DOC_TONE = { verified: "text-hg-success", approved: "text-hg-success", rejected: "text-danger", submitted: "text-hg-gold", pending: "text-hg-gold" };

/** Batch 14 (VEN-05): documents, bank and verification status from GET /api/vendor/me/profile-overview. Read-only facts; nothing
 *  here approves anything. */
function ProfileOverview({ ov }) {
  const missing = ov.requirements?.missing || [];
  const lc = ov.bank?.latest_change;
  const locked = Object.entries(ov.approval_required || {});
  return (
    <SectionCard title="Profile status" icon={CheckCircle2} testid="vp-overview">
      <div className="grid gap-3 text-sm sm:grid-cols-3">
        <div className="hg-tile p-3"><div className="text-xs text-muted2">Documents</div>
          <div className="font-medium text-ink">{ov.documents.length} uploaded{missing.length ? `, ${missing.length} still needed` : ""}</div>
          {missing.length > 0 && <div className="mt-1 text-xs text-danger">Needed: {missing.join(", ").replace(/_/g, " ")}</div>}</div>
        <div className="hg-tile p-3"><div className="text-xs text-muted2">Settlement bank</div>
          <div className="font-medium text-ink">{ov.bank.account ? `${ov.bank.account} · ${ov.bank.ifsc || ""}` : "Not given yet"}</div>
          {lc && <div className={`mt-1 text-xs ${lc.status === "pending" ? "text-hg-gold" : lc.status === "rejected" ? "text-danger" : "text-hg-success"}`}>Change request {lc.status}{lc.admin_note ? `: ${lc.admin_note}` : ""}</div>}</div>
        <div className="hg-tile p-3"><div className="text-xs text-muted2">Contact verification</div>
          <div className="font-medium text-ink">Mobile {ov.verification.mobile ? "verified" : "not verified"} · E-mail {ov.verification.email ? "verified" : "not verified"}</div></div>
      </div>
      {ov.documents.length > 0 && <ul className="mt-3 space-y-1 text-xs">{ov.documents.map((d) => <li key={d.id} className="flex justify-between gap-2"><span>{(d.type || "").replace(/_/g, " ")}{d.note ? ` · ${d.note}` : ""}</span><span className={DOC_TONE[d.status] || "text-muted2"}>{d.status}</span></li>)}</ul>}
      {locked.length > 0 && (
        <details className="mt-3 text-sm"><summary className="flex cursor-pointer items-center gap-2 font-medium text-ink"><Lock size={14} /> Details that need HOME GENIES approval to change</summary>
          <ul className="mt-2 space-y-1 text-xs text-muted2">{locked.map(([k, how]) => <li key={k}><b className="text-ink">{k.replace(/_/g, " ")}:</b> {how}</li>)}</ul></details>
      )}
    </SectionCard>
  );
}
