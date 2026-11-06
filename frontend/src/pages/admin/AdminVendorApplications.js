import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { AlertTriangle, ArrowRightCircle, Ban, Copy, Inbox, Mail, MapPin, Phone, Search, Store, UserCog, XCircle } from "lucide-react";
import { VButton, VCard, VField, VInput, VStatus, VBanner, VTextarea } from "@/components/vendor/VendorUI";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { BUSINESS_TYPES } from "@/lib/vendorOptions";

const MANAGE = ["super_admin", "admin"];          // the server enforces this; hiding controls is only a convenience
const TABS = [["open", "Open"], ["in_review", "In review"], ["converted", "Onboarding started"], ["declined", "Declined"], ["duplicate", "Duplicate"], ["all", "All"]];
const when = (iso) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "");

export default function AdminVendorApplications() {
  const { user } = useAuth();
  const canManage = MANAGE.includes(user?.role);
  const navigate = useNavigate();
  const [tab, setTab] = useState("open");
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [mode, setMode] = useState(null);           // decline | duplicate | edit
  const [reason, setReason] = useState("");
  const [dupOf, setDupOf] = useState("");
  const [edit, setEdit] = useState({});
  const [busy, setBusy] = useState(null);

  const load = useCallback(() => {
    API.get("/admin/vendor-applications", { params: { status: tab, q: q || undefined, page_size: 50 } })
      .then(({ data: d }) => setData(d)).catch((e) => { setData({ items: [], counts: {} }); toast.error(apiError(e)); });
  }, [tab, q]);
  useEffect(() => { load(); }, [load]);

  const open = useCallback((id) => {
    setSelected(id); setMode(null); setReason(""); setDupOf("");
    API.get(`/admin/vendor-applications/${id}`).then(({ data: d }) => { setDetail(d); setEdit({ mobile: d.mobile, email: d.email || "", contact_name: d.contact_name }); })
      .catch((e) => toast.error(apiError(e)));
  }, []);

  const act = async (action, extra = {}) => {
    setBusy(action);
    try {
      const { data: d } = await API.post(`/admin/vendor-applications/${selected}/action`, { action, ...extra });
      if (action === "convert" && d.vendor_id) {
        toast.success(`Onboarding started for ${d.business_name}`);
        navigate(`/admin/vendors/${d.vendor_id}/onboarding`);
        return;
      }
      toast.success("Application updated");
      setDetail({ ...detail, ...d }); setMode(null); setReason(""); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  const saveEdit = async () => {
    setBusy("edit");
    try {
      const { data: d } = await API.put(`/admin/vendor-applications/${selected}`, { mobile: edit.mobile, email: edit.email, contact_name: edit.contact_name, note: "Contact corrected" });
      setDetail(d); setMode(null); toast.success("Contact details updated"); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  const counts = data?.counts || {};
  const isOpen = detail && ["new", "in_review"].includes(detail.status);

  return (
    <div className="hgv-surface -mx-1 rounded-[1.75rem] p-3 ring-1 ring-aurum-400/40 sm:mx-0 sm:p-6" data-testid="admin-vendor-applications">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.16em] text-aurum-700">Vendor Pillar</p>
          <h1 className="hgv-title mt-1 text-3xl font-bold">Vendor applications</h1>
          <p className="hgv-muted mt-1 text-sm">Review “Apply to sell” requests. Converting one starts onboarding; only a super admin gives final approval.</p>
        </div>
        <div className="flex gap-2">
          <span className="hgv-pill hgv-pill-gold">New {counts.new || 0}</span>
          <span className="hgv-pill hgv-pill-blue">In review {counts.in_review || 0}</span>
        </div>
      </div>

      <div className="mt-5 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1" role="tablist" aria-label="Application status">
          {TABS.map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} aria-pressed={tab === k} className="hgv-chip shrink-0"
                    onClick={() => { setTab(k); setSelected(null); setDetail(null); }} data-testid={`apps-tab-${k}`}>{label}</button>
          ))}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <label htmlFor="apps-q" className="hgv-visually-hidden">Search applications</label>
          <VInput id="apps-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, mobile, city, VA number" className="!mt-0 lg:!w-80" data-testid="apps-search" />
          <VButton type="submit" variant="secondary" icon={Search} size="sm" aria-label="Search">Search</VButton>
        </form>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
        <div className="space-y-3" data-testid="apps-list">
          {!data && <VCard className="p-6 text-center text-sm hgv-muted">Loading…</VCard>}
          {data && data.items.length === 0 && (
            <VCard className="p-8 text-center"><Inbox size={28} className="mx-auto text-aurum-600" aria-hidden /><p className="hgv-muted mt-2 text-sm">No applications here.</p></VCard>
          )}
          {data?.items.map((a) => (
            <button key={a.id} type="button" onClick={() => open(a.id)} aria-current={selected === a.id ? "true" : undefined}
                    className={`hgv-card block w-full p-4 text-left transition hover:-translate-y-0.5 ${selected === a.id ? "ring-2 ring-aurum-500" : ""}`} data-testid={`app-${a.number}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold text-choco-900">{a.business_name}</span>
                <VStatus status={a.status} />
              </div>
              <div className="hgv-muted mt-1 text-xs">{a.number} · {BUSINESS_TYPES[a.business_type] || a.business_type} · {a.city}, {a.state}</div>
              <div className="mt-2 flex flex-wrap gap-1.5">{(a.categories || []).map((c) => <span key={c} className="hgv-pill hgv-pill-muted">{c}</span>)}</div>
              <div className="hgv-muted mt-2 text-[11px]">Received {when(a.created_at)}</div>
            </button>
          ))}
        </div>

        <div className="lg:sticky lg:top-4 lg:self-start">
          {!detail ? (
            <VCard className="hidden p-8 text-center lg:block"><Store size={30} className="mx-auto text-aurum-600" aria-hidden /><p className="hgv-muted mt-2 text-sm">Choose an application to review it.</p></VCard>
          ) : (
            <VCard className="p-5 sm:p-6" data-testid="app-detail">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="hgv-title text-2xl font-bold">{detail.business_name}</h2>
                  <p className="hgv-muted text-sm">{detail.number} · {BUSINESS_TYPES[detail.business_type] || detail.business_type}</p>
                </div>
                <VStatus status={detail.status} />
              </div>

              {detail.existing_account && (
                <VBanner tone="red" icon={AlertTriangle} className="mt-4">
                  <b>The {detail.existing_account.matches.join(" and ")} belongs to an existing {detail.existing_account.kind} account.</b> Existing accounts are never
                  converted into vendors. Edit the contact to the business’s own mobile and email before converting.
                </VBanner>
              )}

              <dl className="mt-5 grid gap-3 text-sm sm:grid-cols-2">
                <div className="flex items-start gap-2"><UserCog size={16} className="mt-0.5 text-aurum-600" aria-hidden /><div><dt className="hgv-muted text-xs">Contact</dt><dd className="font-semibold">{detail.contact_name}</dd></div></div>
                <div className="flex items-start gap-2"><Phone size={16} className="mt-0.5 text-aurum-600" aria-hidden /><div><dt className="hgv-muted text-xs">Mobile</dt><dd className="font-semibold">{detail.mobile}</dd></div></div>
                <div className="flex items-start gap-2"><Mail size={16} className="mt-0.5 text-aurum-600" aria-hidden /><div className="min-w-0"><dt className="hgv-muted text-xs">Email</dt><dd className="break-all font-semibold">{detail.email || "—"}</dd></div></div>
                <div className="flex items-start gap-2"><MapPin size={16} className="mt-0.5 text-aurum-600" aria-hidden /><div><dt className="hgv-muted text-xs">Location</dt><dd className="font-semibold">{detail.city}, {detail.state}</dd></div></div>
              </dl>
              <div className="mt-4">
                <p className="hgv-muted text-xs">Categories</p>
                <div className="mt-1 flex flex-wrap gap-1.5">{(detail.categories || []).map((c) => <span key={c} className="hgv-pill hgv-pill-gold">{c}</span>)}</div>
              </div>
              <div className="mt-4"><p className="hgv-muted text-xs">About the business</p><p className="mt-1 whitespace-pre-line text-sm text-choco-800">{detail.description}</p></div>
              {detail.website && <p className="mt-3 text-sm"><span className="hgv-muted text-xs">Website </span><a href={detail.website} target="_blank" rel="noreferrer noopener" className="break-all font-semibold text-choco-700 underline">{detail.website}</a></p>}
              {detail.decline_reason && <VBanner tone="red" className="mt-4">Declined: {detail.decline_reason}</VBanner>}
              {detail.duplicate_of && <VBanner tone="gold" icon={Copy} className="mt-4">Duplicate of {detail.duplicate_of}</VBanner>}
              {detail.converted_vendor_id && (
                <VButton variant="gold" icon={ArrowRightCircle} className="mt-4 w-full sm:w-auto" to={`/admin/vendors/${detail.converted_vendor_id}/onboarding`}>Open onboarding</VButton>
              )}
              {detail.other_applications?.length > 0 && (
                <p className="hgv-muted mt-4 text-xs">Earlier applications from this mobile: {detail.other_applications.map((o) => `${o.number} (${o.status})`).join(", ")}</p>
              )}

              {canManage && isOpen && (
                <div className="hgv-rule mt-6 border-t pt-5">
                  {mode === null && (
                    <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                      <VButton variant="primary" icon={ArrowRightCircle} busy={busy === "convert"} onClick={() => act("convert")} data-testid="app-convert">Convert to onboarding</VButton>
                      {detail.status === "new" && <VButton variant="secondary" busy={busy === "review"} onClick={() => act("review")} data-testid="app-review">Mark in review</VButton>}
                      <VButton variant="secondary" icon={UserCog} onClick={() => setMode("edit")} data-testid="app-edit">Edit contact</VButton>
                      <VButton variant="secondary" icon={Copy} onClick={() => setMode("duplicate")} data-testid="app-duplicate">Duplicate</VButton>
                      <VButton variant="danger" icon={XCircle} onClick={() => setMode("decline")} data-testid="app-decline">Decline</VButton>
                    </div>
                  )}
                  {mode === "decline" && (
                    <div className="grid gap-3">
                      <VField id="app-reason" label="Reason for declining" required help="Kept on the application for the team. It is not sent automatically.">
                        <VTextarea id="app-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} data-testid="app-reason" />
                      </VField>
                      <div className="flex flex-wrap gap-2">
                        <VButton variant="danger" icon={Ban} busy={busy === "decline"} disabled={reason.trim().length < 5} onClick={() => act("decline", { reason })} data-testid="app-decline-confirm">Decline application</VButton>
                        <VButton variant="secondary" onClick={() => setMode(null)}>Cancel</VButton>
                      </div>
                    </div>
                  )}
                  {mode === "duplicate" && (
                    <div className="grid gap-3">
                      <VField id="app-dup" label="Duplicate of (application number)" required>
                        <VInput id="app-dup" value={dupOf} onChange={(e) => setDupOf(e.target.value.toUpperCase())} placeholder="VA000012" />
                      </VField>
                      <div className="flex flex-wrap gap-2">
                        <VButton variant="primary" busy={busy === "duplicate"} disabled={dupOf.trim().length < 3} onClick={() => act("duplicate", { duplicate_of: dupOf })}>Mark as duplicate</VButton>
                        <VButton variant="secondary" onClick={() => setMode(null)}>Cancel</VButton>
                      </div>
                    </div>
                  )}
                  {mode === "edit" && (
                    <div className="grid gap-3 sm:grid-cols-2">
                      <VField id="app-ename" label="Contact name" required className="sm:col-span-2"><VInput id="app-ename" value={edit.contact_name} onChange={(e) => setEdit({ ...edit, contact_name: e.target.value })} /></VField>
                      <VField id="app-emobile" label="Business mobile" required><VInput id="app-emobile" value={edit.mobile} inputMode="numeric" maxLength={10} onChange={(e) => setEdit({ ...edit, mobile: e.target.value })} /></VField>
                      <VField id="app-eemail" label="Business email" optional><VInput id="app-eemail" value={edit.email} onChange={(e) => setEdit({ ...edit, email: e.target.value })} /></VField>
                      <div className="flex flex-wrap gap-2 sm:col-span-2">
                        <VButton variant="primary" busy={busy === "edit"} onClick={saveEdit}>Save contact</VButton>
                        <VButton variant="secondary" onClick={() => setMode(null)}>Cancel</VButton>
                      </div>
                    </div>
                  )}
                </div>
              )}
              {!canManage && <p className="hgv-muted mt-5 text-xs">Read-only: your role can view applications but not act on them.</p>}

              <details className="mt-6">
                <summary className="cursor-pointer text-sm font-semibold text-choco-700">History ({detail.history?.length || 0})</summary>
                <ol className="mt-3 space-y-2 border-l-2 border-aurum-300 pl-4">
                  {(detail.history || []).map((h, i) => (
                    <li key={i} className="text-xs"><span className="font-semibold capitalize text-choco-800">{h.action.replace(/_/g, " ")}</span> <span className="hgv-muted">· {when(h.at)}</span>{h.note ? <span className="block text-choco-700">{h.note}</span> : null}</li>
                  ))}
                </ol>
              </details>
            </VCard>
          )}
        </div>
      </div>
    </div>
  );
}
