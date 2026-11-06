import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import {
  ArrowLeft, BadgeCheck, Banknote, Building2, CheckCircle2, ClipboardList, Copy, FileCheck2, Handshake, KeyRound, MapPinned,
  Save, Scale, Send, ShieldCheck, Truck, UserRound, XCircle, Undo2, AlertTriangle,
} from "lucide-react";
import { VButton, VCard, VChips, VField, VInput, VSelect, VStatus, VTextarea, VYesNo, VBanner } from "@/components/vendor/VendorUI";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const ICONS = { business: Building2, person: UserRound, legal: Scale, addresses: MapPinned, operations: Truck, bank: Banknote, documents: FileCheck2, commercial: Handshake };
const HELP = {
  business: "Who the business is. The legal name is used for invoices and agreements; the store name is what customers see.",
  person: "The person HOME GENIES deals with. Their mobile and email become the vendor owner's login after final approval.",
  legal: "PAN is always needed. GST, LLP and company details are asked only when they apply to this business type.",
  addresses: "Registered address for legal records, a pickup address for dispatch and a return address for returned goods.",
  operations: "The minimum operating details: dispatch time, support contact and who packs and ships.",
  bank: "Where settlements are paid. After approval, changes go through a finance-approved request.",
  documents: "Upload and verify the documents this business type needs. Only verified documents count.",
  commercial: "Finance prepares the commercial agreement; a second finance admin approves it.",
};
const ORDER = ["business", "person", "legal", "addresses", "operations", "bank", "documents", "commercial"];
const EDIT_ROLES = ["super_admin", "admin"];
const REVIEW_DOC_ROLES = ["super_admin", "admin", "support_admin"];

function errorDetail(err) {
  const d = err?.response?.data?.detail;
  if (d && typeof d === "object" && d.missing) return d;
  return { message: apiError(err) };
}

function AddressBlock({ kind, label, value, onChange, disabled, sameOptions, optional }) {
  const sameKey = `${kind}_same_as`;
  const same = value[sameKey] || "";
  const addr = value[kind] || {};
  const set = (k) => (e) => onChange({ ...value, [kind]: { ...addr, [k]: e.target.value } });
  return (
    <fieldset className="hgv-card p-4 sm:p-5">
      <legend className="hgv-title px-1 text-base font-semibold">{label}</legend>
      {sameOptions && (
        <div className="flex flex-wrap gap-2">
          {sameOptions.map(([k, l]) => (
            <button key={k || "own"} type="button" className="hgv-chip" aria-pressed={same === k} disabled={disabled}
                    onClick={() => onChange({ ...value, [sameKey]: k })}>{l}</button>
          ))}
        </div>
      )}
      {!same && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <VField id={`${kind}-l1`} label="Address line 1" required={!optional} optional={optional} className="sm:col-span-2"><VInput id={`${kind}-l1`} value={addr.line1 || ""} onChange={set("line1")} disabled={disabled} maxLength={160} /></VField>
          <VField id={`${kind}-l2`} label="Address line 2" optional className="sm:col-span-2"><VInput id={`${kind}-l2`} value={addr.line2 || ""} onChange={set("line2")} disabled={disabled} maxLength={160} /></VField>
          <VField id={`${kind}-city`} label="City" required={!optional} optional={optional}><VInput id={`${kind}-city`} value={addr.city || ""} onChange={set("city")} disabled={disabled} maxLength={60} /></VField>
          <VField id={`${kind}-state`} label="State" required={!optional} optional={optional}><VSelect id={`${kind}-state`} options={value.__states || []} value={addr.state || ""} onChange={set("state")} disabled={disabled} /></VField>
          <VField id={`${kind}-pin`} label="PIN code" required={!optional} optional={optional}><VInput id={`${kind}-pin`} value={addr.pincode || ""} onChange={set("pincode")} inputMode="numeric" maxLength={6} disabled={disabled} /></VField>
          <VField id={`${kind}-lm`} label="Landmark" optional><VInput id={`${kind}-lm`} value={addr.landmark || ""} onChange={set("landmark")} disabled={disabled} maxLength={80} /></VField>
        </div>
      )}
    </fieldset>
  );
}

export default function AdminVendorOnboarding() {
  const { id } = useParams();
  const { user } = useAuth();
  const role = user?.role;
  const [data, setData] = useState(null);
  const [opts, setOpts] = useState(null);
  const [active, setActive] = useState("business");
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(null);
  const [missing, setMissing] = useState(null);
  const [reason, setReason] = useState("");
  const [decision, setDecision] = useState(null);       // request_changes | reject
  const [invite, setInvite] = useState(null);
  const [doc, setDoc] = useState({ type: "", url: "", note: "" });
  const [docNotes, setDocNotes] = useState({});

  const apply = (d) => {
    setData(d);
    const o = d.onboarding || {};
    setForm({ ...Object.fromEntries(ORDER.map((k) => [k, { ...(o[k] || {}) }])), bank: { ...(o.bank || {}), account_number: "", account_number_confirm: "" } });
  };
  const load = useCallback(() => API.get(`/admin/vendors/${id}/onboarding`).then(({ data: d }) => apply(d)).catch((e) => toast.error(apiError(e))), [id]);
  useEffect(() => { load(); API.get("/admin/vendor-onboarding/options").then(({ data: d }) => setOpts(d)).catch(() => {}); }, [load]);

  const status = data?.vendor?.status;
  const editable = status === "onboarding" && EDIT_ROLES.includes(role);
  const sections = useMemo(() => Object.fromEntries((data?.checklist?.sections || []).map((s) => [s.key, s])), [data]);
  const done = (data?.checklist?.sections || []).filter((s) => s.complete).length;
  const f = form[active] || {};
  const setF = (patch) => setForm({ ...form, [active]: { ...f, ...patch } });
  const val = (k) => (f[k] === undefined || f[k] === null ? "" : f[k]);
  const text = (k) => (e) => setF({ [k]: e.target.value });

  const save = async (next) => {
    setBusy("save");
    try {
      let body = { ...f };
      delete body.saved_at; delete body.saved_by;
      if (active === "business" && body.year_established !== "" && body.year_established !== undefined) body.year_established = Number(body.year_established) || body.year_established;
      if (active === "operations" && body.handling_days !== "" && body.handling_days !== undefined) body.handling_days = Number(body.handling_days) || body.handling_days;
      if (active === "addresses") {
        body = Object.fromEntries(Object.entries(body).filter(([k]) => !k.startsWith("__")));
        for (const kind of ["pickup", "return", "correspondence"]) if (body[`${kind}_same_as`]) delete body[kind];
      }
      const { data: d } = await API.put(`/admin/vendors/${id}/onboarding/${active}`, body);
      apply(d);
      toast.success(`${(opts?.sections || {})[active] || "Section"} saved`);
      if (next) { const i = ORDER.indexOf(active); setActive(ORDER[Math.min(i + 1, ORDER.length - 1)]); window.scrollTo({ top: 0, behavior: "smooth" }); }
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  const submitForApproval = async () => {
    setBusy("submit"); setMissing(null);
    try { const { data: d } = await API.post(`/admin/vendors/${id}/submit-for-approval`); apply(d); toast.success("Submitted for super admin approval"); }
    catch (e) { const d = errorDetail(e); if (d.missing) setMissing(d.missing); toast.error(d.message); load(); }
    finally { setBusy(null); }
  };

  const finalReview = async (action) => {
    setBusy(action); setMissing(null);
    try {
      const { data: d } = await API.post(`/admin/vendors/${id}/final-review`, { action, reason });
      apply(d); setDecision(null); setReason("");
      if (d.invitation) { setInvite(d.invitation); setTimeout(() => document.querySelector("[data-testid=owner-access-card]")?.scrollIntoView({ behavior: "smooth", block: "center" }), 150); }
      toast.success(action === "approve" ? (d.invitation?.token ? "Vendor approved. Share the owner invitation." : "Vendor approved and activated. The owner signs in with the password they chose.") : action === "reopen" ? "Reopened for onboarding" : "Decision recorded");
    } catch (e) { const d = errorDetail(e); if (d.missing) setMissing(d.missing); toast.error(d.message); }
    finally { setBusy(null); }
  };

  const ownerAccess = async (resend) => {
    setBusy("owner");
    try { const { data: d } = await API.post(`/admin/vendors/${id}/owner-access`, { resend }); setInvite(d); load(); toast.success(d.token ? "Invitation issued" : "No new invitation was needed"); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  const addDoc = async () => {
    setBusy("doc");
    try { await API.post(`/admin/vendors/${id}/onboarding/documents`, doc); setDoc({ type: "", url: "", note: "" }); await load(); toast.success("Document added — verify it to count it"); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };
  const reviewDoc = async (docId, st) => {
    setBusy(docId);
    try { await API.post(`/admin/vendor-documents/${docId}/review`, { status: st, note: docNotes[docId] || "" }); await load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  if (!data || !opts) return <div className="hgv-surface rounded-[1.75rem] p-8 text-center text-sm hgv-muted">Loading registration…</div>;
  const v = data.vendor;
  const labels = opts.document_labels || {};
  const inviteLink = invite?.token ? `${window.location.origin}/vendor/owner-invite?token=${invite.token}` : null;
  const statesForAddr = { ...(form.addresses || {}), __states: opts.states };

  return (
    <div className="hgv-surface -mx-1 rounded-[1.75rem] p-3 ring-1 ring-aurum-400/40 sm:mx-0 sm:p-6" data-testid="admin-vendor-onboarding">
      <Link to="/admin/vendors" className="inline-flex min-h-[44px] items-center gap-1.5 text-sm font-semibold text-choco-700"><ArrowLeft size={16} aria-hidden /> All vendors</Link>

      <VCard className="hgv-card-dark mt-2 p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-aurum-300">Vendor registration · {v.vendor_code}</p>
            <h1 className="hgv-title mt-1 break-words text-3xl font-bold" style={{ color: "#FBF1DA" }}>{v.business_name}</h1>
            {data.application && <p className="mt-1 text-sm text-cream-300">From application {data.application.number}</p>}
          </div>
          <VStatus status={v.status} />
        </div>
        <div className="mt-5">
          <div className="flex items-center justify-between text-sm text-cream-200"><span>{done} of {ORDER.length} sections complete</span><span className="font-bold text-aurum-300">{Math.round((done / ORDER.length) * 100)}%</span></div>
          <div className="hgv-progress mt-2 !bg-choco-700"><span style={{ width: `${(done / ORDER.length) * 100}%` }} /></div>
        </div>
      </VCard>

      <div className="mt-4 space-y-3">
        {status === "onboarding" && v.review_feedback && <VBanner tone="gold" icon={Undo2}><b>Changes requested by the super admin:</b> {v.review_feedback}</VBanner>}
        {status === "ready_for_review" && role !== "super_admin" && <VBanner tone="gold" icon={ShieldCheck}>Submitted. Waiting for a super admin to give final approval. The registration is locked meanwhile.</VBanner>}
        {status === "rejected" && <VBanner tone="red" icon={XCircle}><b>Rejected:</b> {v.rejection_reason}</VBanner>}
        {missing && status !== "onboarding" && (
          <VBanner tone="red" icon={AlertTriangle}>
            <b>Not complete yet:</b>
            <ul className="mt-1 list-disc pl-5">{missing.map((m) => <li key={m}>{m}</li>)}</ul>
          </VBanner>
        )}
        {!EDIT_ROLES.includes(role) && <VBanner tone="gold">Read-only: your role can view this registration but cannot change it.</VBanner>}
      </div>

      {(inviteLink || ["approved", "active"].includes(status)) && (
        <VCard className="mt-4 p-5 sm:p-6" data-testid="owner-access-card">
          <h2 className="hgv-title flex items-center gap-2 text-xl font-semibold"><KeyRound size={19} className="text-aurum-600" aria-hidden /> Owner access</h2>
          <p className="hgv-muted mt-1 text-sm">Owner account: <b className="text-choco-800">{data.owner.account_status}</b>{data.owner.invitation ? ` · invitation ${data.owner.invitation.status}, expires ${new Date(data.owner.invitation.expires_at).toLocaleString("en-IN")}` : ""}</p>
          {data.owner.account_status === "active" && (
            <VBanner tone="green" icon={CheckCircle2} className="mt-4"><span data-testid="owner-active">The owner's vendor login is active. They sign in at Vendor login with their mobile and password.</span></VBanner>
          )}
          {inviteLink && (
            <div className="mt-4" data-testid="invite-link-box">
              <VBanner tone="green" icon={CheckCircle2}>Send this one-time link to the owner. It is shown only now and expires in 72 hours.</VBanner>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <code className="block min-w-0 flex-1 break-all rounded-xl bg-cream-200 px-3 py-3 text-xs text-choco-900 ring-1 ring-aurum-400/50" data-testid="invite-link">{inviteLink}</code>
                <VButton variant="secondary" icon={Copy} onClick={() => { navigator.clipboard?.writeText(inviteLink); toast.success("Link copied"); }}>Copy link</VButton>
              </div>
            </div>
          )}
          {role === "super_admin" && data.owner.account_status !== "active" && ["approved", "active"].includes(status) && (
            <div className="mt-4 flex flex-wrap gap-2">
              {!data.owner.invitation && <VButton variant="primary" icon={KeyRound} busy={busy === "owner"} onClick={() => ownerAccess(false)} data-testid="owner-issue">Issue invitation</VButton>}
              {data.owner.invitation && <VButton variant="secondary" busy={busy === "owner"} onClick={() => ownerAccess(true)} data-testid="owner-resend">Replace invitation link</VButton>}
            </div>
          )}
        </VCard>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[250px_minmax(0,1fr)]">
        <nav aria-label="Registration sections" className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:block lg:space-y-1.5 lg:overflow-visible lg:px-0">
          {ORDER.map((k, i) => {
            const Icon = ICONS[k];
            return (
              <button key={k} type="button" className="hgv-step w-auto shrink-0 lg:w-full" aria-current={active === k ? "step" : undefined} onClick={() => setActive(k)} data-testid={`step-${k}`}>
                <span className="hgv-step-dot" data-done={sections[k]?.complete ? "true" : "false"}>{sections[k]?.complete ? <CheckCircle2 size={16} aria-hidden /> : i + 1}</span>
                <span className="flex items-center gap-2 whitespace-nowrap"><Icon size={15} className="text-aurum-700" aria-hidden />{opts.sections[k]}</span>
              </button>
            );
          })}
        </nav>

        <VCard className="p-5 sm:p-6" data-testid={`section-${active}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="hgv-title text-2xl font-semibold">{opts.sections[active]}</h2>
              <p className="hgv-muted mt-1 max-w-2xl text-sm">{HELP[active]}</p>
            </div>
            {sections[active]?.complete ? <span className="hgv-pill hgv-pill-green"><BadgeCheck size={13} aria-hidden /> Complete</span> : <span className="hgv-pill hgv-pill-gold">Incomplete</span>}
          </div>
          {sections[active]?.missing?.length > 0 && (
            <p className="mt-3 text-sm text-choco-700"><b>Still needed:</b> {sections[active].missing.join(" · ")}</p>
          )}

          <div className="mt-5 grid gap-4 sm:grid-cols-2">
            {active === "business" && (<>
              <VField id="b-legal" label="Legal business name" required help="As on PAN / GST / registration"><VInput id="b-legal" value={val("legal_name")} onChange={text("legal_name")} disabled={!editable} maxLength={160} /></VField>
              <VField id="b-display" label="Store name shown to customers" required><VInput id="b-display" value={val("display_name")} onChange={text("display_name")} disabled={!editable} maxLength={120} /></VField>
              <VField id="b-type" label="Business type" required><VSelect id="b-type" options={opts.business_types} value={val("business_type")} onChange={text("business_type")} disabled={!editable} /></VField>
              {f.business_type === "other" && <VField id="b-type-o" label="Describe the business type" required><VInput id="b-type-o" value={val("business_type_other")} onChange={text("business_type_other")} disabled={!editable} maxLength={80} /></VField>}
              <VField id="b-year" label="Year established" optional><VInput id="b-year" value={val("year_established")} onChange={text("year_established")} inputMode="numeric" maxLength={4} disabled={!editable} /></VField>
              <VField id="b-roles" label="Supplier role" required help="Choose all that apply." className="sm:col-span-2"><VChips options={opts.supplier_roles} value={f.supplier_roles || []} onChange={(x) => setF({ supplier_roles: x })} disabled={!editable} /></VField>
              <VField id="b-cats" label="Approved product categories" required help="The vendor may list products only in these pillars." className="sm:col-span-2"><VChips options={opts.categories} value={f.categories || []} onChange={(x) => setF({ categories: x })} disabled={!editable} /></VField>
              <VField id="b-desc" label="Business description" required className="sm:col-span-2" help={`${String(val("description")).length}/1000`}><VTextarea id="b-desc" value={val("description")} onChange={text("description")} disabled={!editable} maxLength={1000} /></VField>
              <VField id="b-web" label="Website" optional className="sm:col-span-2"><VInput id="b-web" value={val("website")} onChange={text("website")} placeholder="https://" disabled={!editable} maxLength={200} /></VField>
            </>)}

            {active === "person" && (<>
              <VField id="p-name" label="Full name" required><VInput id="p-name" value={val("full_name")} onChange={text("full_name")} disabled={!editable} maxLength={80} /></VField>
              <VField id="p-desig" label="Designation" required><VInput id="p-desig" value={val("designation")} onChange={text("designation")} disabled={!editable} maxLength={60} /></VField>
              <VField id="p-mobile" label="Mobile (owner login)" required help="Must not belong to any existing HOME GENIES account."><VInput id="p-mobile" value={val("mobile")} onChange={text("mobile")} inputMode="numeric" maxLength={10} disabled={!editable} /></VField>
              <VField id="p-email" label="Email (owner login)" required><VInput id="p-email" type="email" value={val("email")} onChange={text("email")} disabled={!editable} maxLength={120} /></VField>
              <VField id="p-alt" label="Alternate mobile" optional><VInput id="p-alt" value={val("alternate_mobile")} onChange={text("alternate_mobile")} inputMode="numeric" maxLength={10} disabled={!editable} /></VField>
              <VField id="p-rel" label="Relationship to the business" required><VSelect id="p-rel" options={opts.relationships} value={val("relationship")} onChange={text("relationship")} disabled={!editable} /></VField>
              <VField id="p-sig" label="Is this person the authorised signatory?" required className="sm:col-span-2"><VYesNo name="Authorised signatory" value={f.is_authorised_signatory} onChange={(x) => setF({ is_authorised_signatory: x })} disabled={!editable} /></VField>
              {f.is_authorised_signatory === false && <VField id="p-signame" label="Authorised signatory's name" required help="An authorisation letter will be needed in Documents."><VInput id="p-signame" value={val("signatory_name")} onChange={text("signatory_name")} disabled={!editable} maxLength={80} /></VField>}
            </>)}

            {active === "legal" && (<>
              <VField id="l-pan" label={form.business?.business_type === "proprietorship" ? "Proprietor's PAN" : "Business PAN"} required help="10 characters, e.g. ABCDE1234F"><VInput id="l-pan" value={val("pan")} onChange={(e) => setF({ pan: e.target.value.toUpperCase() })} maxLength={10} disabled={!editable} /></VField>
              <VField id="l-gst" label="Is the business GST registered?" required><VYesNo name="GST registered" value={f.gst_registered} onChange={(x) => setF({ gst_registered: x })} disabled={!editable} /></VField>
              {f.gst_registered === true && <VField id="l-gstin" label="GSTIN" required help="15 characters; characters 3–12 are the PAN." className="sm:col-span-2"><VInput id="l-gstin" value={val("gstin")} onChange={(e) => setF({ gstin: e.target.value.toUpperCase() })} maxLength={15} disabled={!editable} /></VField>}
              {f.gst_registered === false && (
                <label className="flex items-start gap-3 text-sm text-choco-800 sm:col-span-2">
                  <input type="checkbox" className="mt-0.5 h-6 w-6 accent-[#3B2417]" checked={!!f.gst_exemption_declared} onChange={(e) => setF({ gst_exemption_declared: e.target.checked })} disabled={!editable} />
                  <span><b>Declaration recorded:</b> the vendor has declared in writing that it is not required to register for GST for these supplies. Confirm GST applicability with your CA.</span>
                </label>
              )}
              {form.business?.business_type === "llp" && <VField id="l-llpin" label="LLPIN" required help="e.g. AAB-1234"><VInput id="l-llpin" value={val("llpin")} onChange={(e) => setF({ llpin: e.target.value.toUpperCase() })} maxLength={8} disabled={!editable} /></VField>}
              {["private_limited", "public_limited"].includes(form.business?.business_type) && <VField id="l-cin" label="CIN" required help="21 characters"><VInput id="l-cin" value={val("cin")} onChange={(e) => setF({ cin: e.target.value.toUpperCase() })} maxLength={21} disabled={!editable} /></VField>}
              <VField id="l-udyam" label="Udyam (MSME) number" optional help="UDYAM-XX-00-0000000"><VInput id="l-udyam" value={val("udyam")} onChange={(e) => setF({ udyam: e.target.value.toUpperCase() })} maxLength={19} disabled={!editable} /></VField>
              {!form.business?.business_type && <p className="hgv-muted text-sm sm:col-span-2">Choose the business type first: it decides which registration numbers are asked.</p>}
            </>)}

            {active === "addresses" && (
              <div className="grid gap-4 sm:col-span-2">
                <AddressBlock kind="registered" label="Registered / legal address" value={statesForAddr} onChange={(x) => setF(x)} disabled={!editable} />
                <AddressBlock kind="pickup" label="Pickup / warehouse address" value={statesForAddr} onChange={(x) => setF(x)} disabled={!editable}
                              sameOptions={[["registered", "Same as registered"], ["", "Different address"]]} />
                <div className="grid gap-4 sm:grid-cols-2">
                  <VField id="a-pcn" label="Pickup contact name" required><VInput id="a-pcn" value={val("pickup_contact_name")} onChange={text("pickup_contact_name")} disabled={!editable} maxLength={80} /></VField>
                  <VField id="a-pcp" label="Pickup contact mobile" required><VInput id="a-pcp" value={val("pickup_contact_phone")} onChange={text("pickup_contact_phone")} inputMode="numeric" maxLength={10} disabled={!editable} /></VField>
                </div>
                <AddressBlock kind="return" label="Return address" value={statesForAddr} onChange={(x) => setF(x)} disabled={!editable}
                              sameOptions={[["pickup", "Same as pickup"], ["registered", "Same as registered"], ["", "Different address"]]} />
                <AddressBlock kind="correspondence" label="Correspondence address (optional)" optional value={statesForAddr} onChange={(x) => setF(x)} disabled={!editable}
                              sameOptions={[["registered", "Same as registered"], ["", "Different address"]]} />
              </div>
            )}

            {active === "operations" && (<>
              <VField id="o-days" label="Usual dispatch time (days)" required help="1–15 days after payment"><VInput id="o-days" value={val("handling_days")} onChange={text("handling_days")} inputMode="numeric" maxLength={2} disabled={!editable} /></VField>
              <VField id="o-hours" label="Support hours" required><VInput id="o-hours" value={val("support_hours")} onChange={text("support_hours")} placeholder="Mon–Sat, 10am–7pm" disabled={!editable} maxLength={80} /></VField>
              <VField id="o-phone" label="Support mobile" required><VInput id="o-phone" value={val("support_phone")} onChange={text("support_phone")} inputMode="numeric" maxLength={10} disabled={!editable} /></VField>
              <VField id="o-email" label="Support email" optional><VInput id="o-email" value={val("support_email")} onChange={text("support_email")} disabled={!editable} maxLength={120} /></VField>
              <VField id="o-pack" label="Who packs orders?" required><VSelect id="o-pack" options={opts.responsibility} value={val("packaging_by")} onChange={text("packaging_by")} disabled={!editable} /></VField>
              <VField id="o-ship" label="Who ships orders?" required><VSelect id="o-ship" options={opts.responsibility} value={val("shipping_by")} onChange={text("shipping_by")} disabled={!editable} /></VField>
              <VField id="o-notes" label="Operational notes" optional className="sm:col-span-2"><VTextarea id="o-notes" value={val("notes")} onChange={text("notes")} disabled={!editable} maxLength={500} /></VField>
            </>)}

            {active === "bank" && (<>
              <VField id="k-holder" label="Account holder name" required><VInput id="k-holder" value={val("account_holder")} onChange={text("account_holder")} disabled={!editable} maxLength={120} /></VField>
              <VField id="k-bank" label="Bank name" required><VInput id="k-bank" value={val("bank_name")} onChange={text("bank_name")} disabled={!editable} maxLength={80} /></VField>
              <VField id="k-acct" label="Account number" required help={data.onboarding?.bank?.account_number ? `Saved: ${data.onboarding.bank.account_number}. Leave blank to keep it.` : "Digits or letters, 6–24 characters"}>
                <VInput id="k-acct" value={val("account_number")} onChange={text("account_number")} autoComplete="off" disabled={!editable} maxLength={24} />
              </VField>
              <VField id="k-acct2" label="Confirm account number" required={!!f.account_number}><VInput id="k-acct2" value={val("account_number_confirm")} onChange={text("account_number_confirm")} autoComplete="off" disabled={!editable} maxLength={24} /></VField>
              <VField id="k-ifsc" label="IFSC" required help="e.g. SBIN0001234"><VInput id="k-ifsc" value={val("ifsc")} onChange={(e) => setF({ ifsc: e.target.value.toUpperCase() })} maxLength={11} disabled={!editable} /></VField>
              <VField id="k-type" label="Account type" required><VSelect id="k-type" options={opts.account_types} value={val("account_type")} onChange={text("account_type")} disabled={!editable} /></VField>
              <VField id="k-branch" label="Branch" optional><VInput id="k-branch" value={val("branch")} onChange={text("branch")} disabled={!editable} maxLength={80} /></VField>
            </>)}

            {active === "documents" && (
              <div className="grid gap-5 sm:col-span-2">
                <div className="grid gap-3 md:grid-cols-3">
                  {[["Required", data.checklist.documents.required.map((t) => ({ type: t }))], ["Conditional", data.checklist.documents.conditional],
                    ["Optional", data.checklist.documents.optional.map((t) => ({ type: t }))]].map(([title, rows]) => (
                    <div key={title} className="hgv-card p-4">
                      <h3 className="text-sm font-bold uppercase tracking-wide text-aurum-700">{title}</h3>
                      {rows.length === 0 && <p className="hgv-muted mt-2 text-xs">None for this vendor.</p>}
                      <ul className="mt-2 space-y-2">
                        {rows.map((r) => (
                          <li key={r.type} className="flex items-start justify-between gap-2 text-sm">
                            <span className="min-w-0"><span className="font-semibold text-choco-800">{labels[r.type] || r.type}</span>{r.reason && <span className="hgv-muted block text-xs">{r.reason}</span>}</span>
                            <VStatus status={data.checklist.documents.state[r.type] || "missing"} label={data.checklist.documents.state[r.type] || "Missing"} />
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                {editable && (
                  <div className="hgv-card grid gap-3 p-4 sm:grid-cols-[1fr_1.4fr] sm:p-5">
                    <VField id="d-type" label="Document type" required><VSelect id="d-type" options={labels} value={doc.type} onChange={(e) => setDoc({ ...doc, type: e.target.value })} /></VField>
                    <VField id="d-url" label="File link" required help="An uploaded file path or a secure https:// link"><VInput id="d-url" value={doc.url} onChange={(e) => setDoc({ ...doc, url: e.target.value })} placeholder="https://" /></VField>
                    <VField id="d-note" label="Note" optional className="sm:col-span-2"><VInput id="d-note" value={doc.note} onChange={(e) => setDoc({ ...doc, note: e.target.value })} maxLength={200} /></VField>
                    <div className="sm:col-span-2"><VButton variant="secondary" icon={FileCheck2} busy={busy === "doc"} disabled={!doc.type || !doc.url} onClick={addDoc} data-testid="doc-add">Add document</VButton></div>
                  </div>
                )}
                <div className="space-y-2">
                  {data.documents.length === 0 && <p className="hgv-muted text-sm">No documents yet.</p>}
                  {data.documents.map((d) => (
                    <div key={d.id} className="hgv-card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-choco-800">{labels[d.type] || d.type}</span><VStatus status={d.status === "submitted" ? "in_review" : d.status} label={d.status === "submitted" ? "Awaiting check" : d.status} /></div>
                        <a href={d.url} target="_blank" rel="noreferrer noopener" className="block truncate text-xs text-choco-600 underline">{d.url}</a>
                        {d.review_note && <p className="hgv-muted text-xs">Note: {d.review_note}</p>}
                      </div>
                      {REVIEW_DOC_ROLES.includes(role) && d.status === "submitted" && (
                        <div className="flex flex-wrap items-center gap-2">
                          <VInput aria-label="Reason if rejecting" placeholder="Reason if rejecting" value={docNotes[d.id] || ""} onChange={(e) => setDocNotes({ ...docNotes, [d.id]: e.target.value })} className="!mt-0 sm:!w-48" />
                          <VButton size="sm" variant="primary" icon={BadgeCheck} busy={busy === d.id} onClick={() => reviewDoc(d.id, "verified")}>Verify</VButton>
                          <VButton size="sm" variant="danger" disabled={(docNotes[d.id] || "").trim().length < 5} onClick={() => reviewDoc(d.id, "rejected")}>Reject</VButton>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {active === "commercial" && (
              <div className="sm:col-span-2">
                {data.checklist.agreement ? (
                  <VBanner tone="green" icon={Handshake}>
                    Approved agreement v{data.checklist.agreement.version}: {data.checklist.agreement.commission_pct}% commission
                    {data.checklist.agreement.fixed_fee_paise ? ` + ₹${(data.checklist.agreement.fixed_fee_paise / 100).toFixed(2)} per order` : ""}, {data.checklist.agreement.settlement_schedule} settlement,
                    effective {data.checklist.agreement.effective_from}.
                  </VBanner>
                ) : (
                  <VBanner tone="gold" icon={ClipboardList}>
                    {data.checklist.agreement_draft_waiting ? "A draft agreement is waiting for a second finance admin to approve it." : "No approved commercial agreement yet."} Finance
                    (accounts admin or super admin) prepares it under Agreements; a different finance admin approves it.
                  </VBanner>
                )}
                <VButton variant="secondary" icon={Handshake} className="mt-4" to="/admin/agreements">Open agreements</VButton>
              </div>
            )}
          </div>

          {editable && !["documents", "commercial"].includes(active) && (
            <div className="hgv-rule mt-6 flex flex-col gap-2 border-t pt-5 sm:flex-row sm:justify-end">
              <VButton variant="secondary" icon={Save} busy={busy === "save"} onClick={() => save(false)} data-testid="section-save">Save section</VButton>
              <VButton variant="primary" icon={Save} busy={busy === "save"} onClick={() => save(true)} data-testid="section-save-next">Save &amp; continue</VButton>
            </div>
          )}
        </VCard>
      </div>

      {status === "onboarding" && EDIT_ROLES.includes(role) && (
        <VCard className="mt-5 flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div>
            <h2 className="hgv-title text-xl font-semibold">Submit for final approval</h2>
            <p className="hgv-muted text-sm">{data.checklist.complete ? "Every section is complete. A super admin will review and decide." : `${ORDER.length - done} section(s) still incomplete. The server refuses submission until everything is complete.`}</p>
          </div>
          <VButton variant="gold" icon={Send} busy={busy === "submit"} onClick={submitForApproval} data-testid="submit-for-approval">Submit for approval</VButton>
        </VCard>
      )}
      {status === "onboarding" && missing && (
        <VBanner tone="red" icon={AlertTriangle} className="mt-3">
          <span data-testid="submit-missing"><b>Not complete yet:</b></span>
          <ul className="mt-1 list-disc pl-5">{missing.map((m) => <li key={m}>{m}</li>)}</ul>
        </VBanner>
      )}

      {status === "ready_for_review" && role === "super_admin" && (
        <VCard className="hgv-card-dark mt-5 p-5 sm:p-6" data-testid="final-review-card">
          <h2 className="hgv-title flex items-center gap-2 text-2xl font-semibold" style={{ color: "#FBF1DA" }}><ShieldCheck size={22} className="text-aurum-300" aria-hidden /> Final review</h2>
          <p className="mt-1 text-sm text-cream-300">Check every section above. Approving makes the vendor operational and issues one owner invitation.</p>
          {!decision ? (
            <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
              <VButton variant="gold" icon={BadgeCheck} busy={busy === "approve"} onClick={() => finalReview("approve")} data-testid="final-approve">Approve vendor</VButton>
              <VButton variant="secondary" icon={Undo2} onClick={() => setDecision("request_changes")} data-testid="final-changes">Request changes</VButton>
              <VButton variant="danger" icon={XCircle} onClick={() => setDecision("reject")} data-testid="final-reject">Reject</VButton>
            </div>
          ) : (
            <div className="mt-5 grid gap-3">
              <label htmlFor="fr-reason" className="text-sm font-semibold text-cream-100">{decision === "reject" ? "Reason for rejection" : "What needs to change?"} <span className="hgv-req">Required</span></label>
              <textarea id="fr-reason" className="hgv-input" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} data-testid="final-reason" />
              <div className="flex flex-wrap gap-2">
                <VButton variant={decision === "reject" ? "danger" : "gold"} busy={busy === decision} disabled={reason.trim().length < 5} onClick={() => finalReview(decision)} data-testid="final-confirm">
                  {decision === "reject" ? "Reject registration" : "Send back to onboarding"}
                </VButton>
                <VButton variant="secondary" onClick={() => { setDecision(null); setReason(""); }}>Cancel</VButton>
              </div>
            </div>
          )}
        </VCard>
      )}

      {status === "rejected" && role === "super_admin" && v.onboarding_path && (
        <div className="mt-5"><VButton variant="secondary" icon={Undo2} busy={busy === "reopen"} onClick={() => finalReview("reopen")}>Reopen for onboarding</VButton></div>
      )}

      <details className="mt-6">
        <summary className="cursor-pointer text-sm font-semibold text-choco-700">Status history ({data.history.length})</summary>
        <ol className="mt-3 space-y-2 border-l-2 border-aurum-300 pl-4">
          {data.history.map((h) => (
            <li key={h.id || h.at} className="text-xs"><span className="font-semibold text-choco-800">{h.from || "—"} → {h.to}</span> <span className="hgv-muted">· {new Date(h.at).toLocaleString("en-IN")}</span>{h.reason && <span className="block text-choco-700">{h.reason}</span>}</li>
          ))}
        </ol>
      </details>
    </div>
  );
}
