import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, Check, ClipboardCheck, FilePlus2, FileEdit, Loader2, MessageSquareWarning, PackageCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { API, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { can } from "@/lib/roles";
import { RoleGate, RoleNote } from "@/components/RoleGate";
import { ProductStudio } from "@/components/catalogue/ProductStudio";

const TABS = [["revisions", "Changes to review"], ["new", "New products"], ["drafts", "Drafts"], ["add", "Add for a vendor"]];
const SELECT = "h-11 w-full rounded-xl bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15";
const show = (v) => (v === null || v === undefined || v === "" ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

/** Batch 12, Phase 4: catalogue moderation. Reviews use the server's decision endpoints; nothing here changes stock or money. */
export default function AdminCatalogue() {
  const [tab, setTab] = useState("revisions");
  return (
    <div className="space-y-5">
      <PageHeader title="Catalogue" subtitle="Review vendors' new products and changes, and add products on a vendor's behalf." icon={PackageCheck} />
      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} data-testid={`cat-tab-${id}`}
            className={`h-10 rounded-full px-5 text-sm font-semibold ${tab === id ? "hg-chip-on text-white" : "hg-chip-off"}`}>{label}</button>
        ))}
      </div>
      {tab === "revisions" && <Revisions />}
      {tab === "new" && <NewProducts />}
      {tab === "drafts" && <Drafts />}
      {tab === "add" && <RoleGate set="contentEditor" what="Adding a product for a vendor"><AddForVendor /></RoleGate>}
    </div>
  );
}

function Revisions() {
  const [rows, setRows] = useState(null);
  const [open, setOpen] = useState(null);
  const load = useCallback(() => API.get("/admin/pim/revisions").then(({ data }) => setRows(data)).catch((e) => toast.error(apiError(e))), []);
  useEffect(() => { load(); }, [load]);
  if (!rows) return <Loader2 className="animate-spin text-muted2" />;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <SectionCard title="Waiting for review" icon={ClipboardCheck} className="min-w-0">
        {rows.length === 0 ? <p className="text-sm text-muted2">No product changes are waiting.</p> : (
          <ul className="space-y-2">
            {rows.map((r) => (
              <li key={r.product.id}><button onClick={() => setOpen(r.product.id)} data-testid={`cat-rev-${r.product.id}`}
                className={`hg-tile flex w-full items-center gap-3 p-3 text-left ${open === r.product.id ? "ring-2 ring-hg-gold/50" : ""}`}>
                {r.product.images?.[0] ? <img src={r.product.images[0]} alt="" className="h-12 w-12 shrink-0 rounded-lg object-cover" /> : <span className="h-12 w-12 shrink-0 rounded-lg bg-brand-50" />}
                <span className="min-w-0 text-sm"><span className="block truncate font-medium text-ink">{r.product.name}</span>
                  <span className="text-xs text-muted2">{r.product.vendor_name} · {r.revision.changed.length} change(s) · {(r.revision.submitted_at || "").slice(0, 10)}</span></span>
              </button></li>
            ))}
          </ul>
        )}
      </SectionCard>
      {open && <RevisionDetail pid={open} onDecided={() => { setOpen(null); load(); }} />}
    </div>
  );
}

function RevisionDetail({ pid, onDecided }) {
  const { user } = useAuth();
  const canDecide = can(user, "contentEditor");       // W7: the server refuses decisions from other roles
  const [d, setD] = useState(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { setD(null); API.get(`/admin/pim/products/${pid}/revision`).then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))); }, [pid]);
  const decide = async (action) => {
    setBusy(true);
    try {
      await API.post(`/admin/pim/products/${pid}/revision/decision`, { action, reason });
      toast.success({ approve: "Change approved and live.", reject: "Change rejected; the product stays as it was.", request_changes: "Sent back to the vendor." }[action]);
      onDecided();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  if (!d) return <Loader2 className="animate-spin text-muted2" />;
  const warnings = Object.values(d.check.sections).flatMap((s) => s.warnings);
  return (
    <SectionCard title={d.product.name} icon={FileEdit} testid="cat-revision-detail" className="min-w-0">
      <p className="text-xs text-muted2">The approved version stays on sale until you decide. Stock is never changed by a review.</p>
      <div className="-mx-1 mt-3 overflow-x-auto">
        <table className="w-full min-w-[480px] text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className="px-2 py-1.5">Field</th><th className="px-2 py-1.5">Live now</th><th className="px-2 py-1.5">Proposed</th></tr></thead>
          <tbody>{Object.entries(d.diff).map(([k, v]) => (
            <tr key={k} className="border-t border-brand-50 align-top"><td className="px-2 py-2 font-medium">{k.replace(/_/g, " ")}</td>
              <td className="max-w-[220px] break-words px-2 py-2 text-muted2">{show(v.live)}</td><td className="max-w-[220px] break-words px-2 py-2 text-ink">{show(v.proposed)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      {warnings.length > 0 && <ul className="mt-3 space-y-1 text-xs text-hg-gold">{warnings.map((w) => <li key={w} className="flex gap-1.5"><MessageSquareWarning size={13} className="mt-0.5 shrink-0" /> {w}</li>)}</ul>}
      {!canDecide ? <div className="mt-3"><RoleNote set="contentEditor" what="Deciding on catalogue changes" testid="cat-readonly" /></div> : <>
      <Textarea className="mt-3" rows={2} placeholder="Reason for the vendor (needed to reject or ask for changes)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
      <div className="mt-3 flex flex-wrap gap-2">
        <Button onClick={() => decide("approve")} disabled={busy} className="hg-btn rounded-full" data-testid="cat-approve"><Check size={15} /> Approve</Button>
        <Button variant="outline" onClick={() => decide("request_changes")} disabled={busy || reason.trim().length < 5} className="rounded-full">Ask for changes</Button>
        <Button variant="outline" onClick={() => decide("reject")} disabled={busy || reason.trim().length < 5} className="rounded-full text-danger"><X size={15} /> Reject</Button>
      </div></>}
    </SectionCard>
  );
}

function NewProducts() {
  const { user } = useAuth();
  const canDecide = can(user, "contentEditor");       // W7: the server refuses decisions from other roles
  const [rows, setRows] = useState(null);
  const [reason, setReason] = useState({});
  const load = useCallback(() => API.get("/admin/vendor-products", { params: { status: "pending" } }).then(({ data }) => setRows(data)).catch((e) => toast.error(apiError(e))), []);
  useEffect(() => { load(); }, [load]);
  const decide = async (p, action) => {
    try { await API.post(`/admin/vendor-products/${p.id}/decision`, { action, reason: reason[p.id] || "" }); toast.success(action === "approve" ? "Approved" : "Rejected"); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  if (!rows) return <Loader2 className="animate-spin text-muted2" />;
  if (rows.length === 0) return <p className="text-sm text-muted2">No new products are waiting for review.</p>;
  return (<>
    {!canDecide && <div className="mb-3"><RoleNote set="contentEditor" what="Approving or rejecting new products" testid="cat-new-readonly" /></div>}
    <ul className="grid gap-4 md:grid-cols-2">
      {rows.map((p) => (
        <li key={p.id} className="hg-card space-y-2 p-4" data-testid={`cat-new-${p.sku}`}>
          <div className="flex gap-3">
            {p.images?.[0] ? <img src={p.images[0]} alt={(p.image_alt || {})[p.images[0]] || ""} className="h-20 w-20 shrink-0 rounded-xl object-cover" /> : <span className="h-20 w-20 shrink-0 rounded-xl bg-brand-50" />}
            <div className="min-w-0 text-sm"><div className="font-medium text-ink">{p.name}</div>
              <div className="text-xs text-muted2">{p.vendor_name} · {p.category}{p.subcategory ? ` · ${p.subcategory}` : ""} · {p.sku}</div>
              <div className="mt-1">₹{p.selling_price} <span className="text-xs text-muted2">MRP ₹{p.mrp} · GST {p.gst_percent}% · HSN {p.hsn_code || "not given"}</span></div>
              {p.created_on_behalf_by && <div className="mt-1 text-xs text-hg-gold">Prepared by an admin on the vendor's behalf</div>}</div>
          </div>
          {p.short_description && <p className="text-sm text-muted2">{p.short_description}</p>}
          {Object.keys(p.attributes || {}).length > 0 && <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">{Object.entries(p.attributes).map(([k, v]) => <React.Fragment key={k}><dt className="text-muted2">{k.replace(/_/g, " ")}</dt><dd className="text-ink">{show(v)}</dd></React.Fragment>)}</dl>}
          {(p.compliance_documents || []).length > 0 && <div className="text-xs">Documents: {p.compliance_documents.map((d) => <a key={d.url} href={d.url} target="_blank" rel="noreferrer" className="mr-2 underline">{d.type}</a>)}</div>}
          {canDecide && <><Textarea rows={2} placeholder="Reason (needed to reject)" value={reason[p.id] || ""} onChange={(e) => setReason({ ...reason, [p.id]: e.target.value })} aria-label="Reason" />
          <div className="flex gap-2">
            <Button size="sm" className="hg-btn rounded-full" onClick={() => decide(p, "approve")}><Check size={14} /> Approve</Button>
            <Button size="sm" variant="outline" className="rounded-full text-danger" disabled={(reason[p.id] || "").trim().length < 5} onClick={() => decide(p, "reject")}><X size={14} /> Reject</Button>
          </div></>}
        </li>
      ))}
    </ul>
  </>);
}

function Drafts() {
  const [rows, setRows] = useState(null);
  const navigate = useNavigate();
  useEffect(() => { API.get("/admin/pim/drafts").then(({ data }) => setRows(data)).catch((e) => toast.error(apiError(e))); }, []);
  if (!rows) return <Loader2 className="animate-spin text-muted2" />;
  if (rows.length === 0) return <p className="text-sm text-muted2">No open drafts.</p>;
  return (
    <ul className="grid gap-2 md:grid-cols-2">
      {rows.map((d) => (
        <li key={d.id} className="hg-tile flex items-center justify-between gap-2 p-3 text-sm">
          <span className="min-w-0"><span className="block truncate font-medium text-ink">{d.name}</span>
            <span className="text-xs text-muted2">{d.on_behalf ? "Admin draft for a vendor" : "Vendor's own draft (read only here)"} · {d.check.ok ? "ready" : `${d.check.blocking} to complete`}</span></span>
          {d.on_behalf && <Button size="sm" variant="outline" className="rounded-full" onClick={() => navigate(`/admin/catalogue/studio/${d.id}`)}>Continue</Button>}
        </li>
      ))}
    </ul>
  );
}

function AddForVendor() {
  const [vendors, setVendors] = useState(null);
  const [vid, setVid] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => { API.get("/admin/vendors").then(({ data }) => setVendors((data || []).filter((v) => ["approved", "active"].includes(v.status)))).catch((e) => toast.error(apiError(e))); }, []);
  const start = async () => {
    setBusy(true);
    try { const { data } = await API.post("/admin/pim/drafts", { vendor_id: vid }); navigate(`/admin/catalogue/studio/${data.id}`); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  return (
    <SectionCard title="Add a product for a vendor" icon={FilePlus2}>
      <p className="text-sm text-muted2">The product belongs to the vendor and goes through the same review. A different admin must approve a product you prepare.</p>
      {!vendors ? <Loader2 className="mt-3 animate-spin text-muted2" /> : (
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <label htmlFor="cat-vendor" className="sr-only">Vendor</label>
          <select id="cat-vendor" className={SELECT} value={vid} onChange={(e) => setVid(e.target.value)} data-testid="cat-vendor">
            <option value="">Choose an approved vendor…</option>
            {vendors.map((v) => <option key={v.id} value={v.id}>{v.business_name} ({v.vendor_code})</option>)}
          </select>
          <Button onClick={start} disabled={!vid || busy} className="hg-btn h-11 shrink-0 rounded-full" data-testid="cat-start">Start product</Button>
        </div>
      )}
    </SectionCard>
  );
}

/** /admin/catalogue/studio/:draftId */
export function AdminCatalogueStudio() {
  const { draftId } = useParams();
  const navigate = useNavigate();
  return <ProductStudio base="/admin/pim" draftId={draftId} onDone={() => navigate("/admin/catalogue")}
    header={<Link to="/admin/catalogue" className="mb-1 inline-flex items-center gap-1 text-xs text-muted2 hover:text-ink"><ArrowLeft size={13} /> Catalogue</Link>} />;
}
