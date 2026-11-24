import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, Eye, Loader2, Megaphone, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { ImageInput } from "@/components/vendor/ImageInput";
import { API, apiError } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { can } from "@/lib/roles";
import { RoleNote } from "@/components/RoleGate";

const KIND_LABEL = { banner: "Banner", collection: "Collection", featured_products: "Featured products", featured_categories: "Featured categories",
  new_arrivals: "New arrivals (automatic)", bestsellers: "Bestsellers (from real sales)" };
const PILLARS = ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"];
const STATE_TONE = { live: "bg-hg-success/15 text-hg-success", scheduled: "bg-hg-gold/15 text-hg-gold", expired: "bg-danger/10 text-danger",
  draft: "bg-brand-50 text-ink", unpublished: "bg-brand-50 text-muted2" };
const SELECT = "h-11 w-full rounded-xl bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15";
const toLocal = (iso) => (iso ? new Date(iso).toLocaleString("sv-SE", { timeZone: "Asia/Kolkata" }).slice(0, 16).replace(" ", "T") : "");
const fromLocal = (v) => (v ? `${v}:00+05:30` : null);

/** Batch 13, Phase 10: merchandising sections (super_admin / admin edit; every change audited). */
export default function AdminMerchandising() {
  const { user } = useAuth();
  const canEdit = can(user, "contentEditor");        // W7: the server refuses every change from other roles; they still view and preview
  const [d, setD] = useState(null);
  const [edit, setEdit] = useState(null);
  const [preview, setPreview] = useState(null);
  const load = useCallback(() => API.get("/admin/merch/sections").then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))), []);
  useEffect(() => { load(); }, [load]);
  const act = async (fn, msg) => { try { await fn(); if (msg) toast.success(msg); load(); } catch (e) { toast.error(apiError(e)); } };
  const move = (i, dir) => {
    const ids = d.sections.map((s) => s.id);
    const j = i + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    act(() => API.post("/admin/merch/sections/order", { ids }));
  };
  if (!d) return <Loader2 className="animate-spin text-muted2" />;
  return (
    <div className="space-y-5">
      <PageHeader title="Merchandising" subtitle="Banners and product sections on the shop home. Only approved products on sale are shown." icon={Megaphone}
        actions={canEdit && <Button className="hg-btn h-11 rounded-full px-5" onClick={() => setEdit({ kind: "collection", title: "", subtitle: "", product_ids: [], categories: [], limit: 8, window_days: 30, image_desktop: "", image_mobile: "", alt: "", link: "" })} data-testid="merch-add"><Plus size={16} /> New section</Button>} />
      {!canEdit && <RoleNote set="contentEditor" what="Changing merchandising" testid="merch-readonly" />}
      {d.sections.length === 0 ? <p className="text-sm text-muted2">No sections yet. The shop home shows its normal product list.</p> : (
        <ul className="space-y-2" data-testid="merch-list">
          {d.sections.map((s, i) => (
            <li key={s.id} className="hg-card flex flex-wrap items-center gap-3 p-3 text-sm">
              {canEdit && <div className="flex flex-col"><button aria-label="Move up" onClick={() => move(i, -1)} disabled={i === 0} className="disabled:opacity-30"><ArrowUp size={15} /></button>
                <button aria-label="Move down" onClick={() => move(i, 1)} disabled={i === d.sections.length - 1} className="disabled:opacity-30"><ArrowDown size={15} /></button></div>}
              <div className="min-w-0 flex-1"><div className="font-medium text-ink">{s.title}</div>
                <div className="text-xs text-muted2">{KIND_LABEL[s.kind]}{s.starts_at ? ` · from ${toLocal(s.starts_at).replace("T", " ")}` : ""}{s.ends_at ? ` · until ${toLocal(s.ends_at).replace("T", " ")}` : ""} IST</div></div>
              <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${STATE_TONE[s.state] || ""}`}>{s.state}</span>
              <Button variant="outline" size="sm" className="rounded-full" onClick={() => API.get(`/admin/merch/sections/${s.id}/preview`).then(({ data }) => setPreview({ s, data })).catch((e) => toast.error(apiError(e)))}><Eye size={14} /> Preview</Button>
              {canEdit && <><Button variant="outline" size="sm" className="rounded-full" onClick={() => setEdit({ ...s, starts_local: toLocal(s.starts_at), ends_local: toLocal(s.ends_at) })}><Pencil size={14} /> Edit</Button>
              {s.status !== "published"
                ? <Button size="sm" className="hg-btn rounded-full" onClick={() => act(() => API.post(`/admin/merch/sections/${s.id}/status`, { action: "publish" }), "Published")} data-testid={`merch-publish-${i}`}>Publish</Button>
                : <Button variant="outline" size="sm" className="rounded-full" onClick={() => act(() => API.post(`/admin/merch/sections/${s.id}/status`, { action: "unpublish" }), "Unpublished")}>Unpublish</Button>}
              <Button variant="ghost" size="sm" className="rounded-full text-danger" aria-label="Delete section" onClick={() => window.confirm("Delete this section?") && act(() => API.post(`/admin/merch/sections/${s.id}/status`, { action: "delete" }), "Deleted")}><Trash2 size={14} /></Button></>}
            </li>
          ))}
        </ul>
      )}
      {edit && <Editor value={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
      <Dialog open={!!preview} onOpenChange={(o) => !o && setPreview(null)}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto rounded-3xl">
          <DialogHeader><DialogTitle>Preview: {preview?.s.title}</DialogTitle><DialogDescription>What this section would show right now if it were live.</DialogDescription></DialogHeader>
          {preview && (preview.data.empty ? <p className="text-sm text-muted2">Nothing to show: no product in it is on sale and in stock right now.</p> : <PreviewBody sec={preview.data.section} />)}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function PreviewBody({ sec }) {
  if (sec.kind === "banner") return <img src={sec.image_desktop} alt={sec.alt} className="w-full rounded-2xl" />;
  if (sec.kind === "featured_categories") return <div className="flex flex-wrap gap-2">{sec.categories.map((c) => <span key={c} className="hg-chip-off rounded-full px-3 py-1.5 text-sm">{c}</span>)}</div>;
  return <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{sec.products.map((p) => <div key={p.id} className="hg-tile p-2 text-xs"><div className="font-medium">{p.name}</div><div>₹{p.selling_price}</div></div>)}</div>;
}

function Editor({ value, onClose, onSaved }) {
  const [f, setF] = useState(value);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [found, setFound] = useState([]);
  const [names, setNames] = useState({});
  useEffect(() => {
    if (!f.product_ids?.length) return;
    API.get("/catalog/products", { params: { ids: f.product_ids.join(",") } }).then(({ data }) => setNames(Object.fromEntries((data.items || []).map((p) => [p.id, p.name])))).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const search = () => API.get("/catalog/search", { params: { q, page_size: 12 } }).then(({ data }) => setFound(data.items || [])).catch((e) => toast.error(apiError(e)));
  const save = async () => {
    setBusy(true);
    const body = { kind: f.kind, title: f.title, subtitle: f.subtitle || "", starts_at: fromLocal(f.starts_local), ends_at: fromLocal(f.ends_local),
      image_desktop: f.image_desktop || "", image_mobile: f.image_mobile || "", alt: f.alt || "", link: f.link || "", product_ids: f.product_ids || [],
      categories: f.categories || [], limit: Number(f.limit) || 8, window_days: Number(f.window_days) || 30 };
    try { if (f.id) await API.put(`/admin/merch/sections/${f.id}`, body); else await API.post("/admin/merch/sections", body); toast.success("Saved as it is; publish to show it."); onSaved(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const ids = f.product_ids || [];
  return (
    <SectionCard title={f.id ? "Edit section" : "New section"} icon={Pencil} testid="merch-editor">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm font-medium">Type<select className={`${SELECT} mt-1`} value={f.kind} disabled={!!f.id} onChange={(e) => setF({ ...f, kind: e.target.value })} data-testid="merch-kind">
          {Object.entries(KIND_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
        <label className="text-sm font-medium">Title<Input className="mt-1 h-11 rounded-xl" value={f.title} maxLength={80} onChange={(e) => setF({ ...f, title: e.target.value })} data-testid="merch-title" /></label>
        <label className="text-sm font-medium sm:col-span-2">Subtitle (optional)<Input className="mt-1 h-11 rounded-xl" value={f.subtitle || ""} maxLength={160} onChange={(e) => setF({ ...f, subtitle: e.target.value })} /></label>
        <label className="text-sm font-medium">Starts (IST, optional)<Input type="datetime-local" className="mt-1 h-11 rounded-xl" value={f.starts_local || ""} onChange={(e) => setF({ ...f, starts_local: e.target.value })} /></label>
        <label className="text-sm font-medium">Ends (IST, optional)<Input type="datetime-local" className="mt-1 h-11 rounded-xl" value={f.ends_local || ""} onChange={(e) => setF({ ...f, ends_local: e.target.value })} /></label>
        <label className="text-sm font-medium sm:col-span-2">Link (a page of this shop, optional)<Input className="mt-1 h-11 rounded-xl" placeholder="/app/products?category=Sarees" value={f.link || ""} onChange={(e) => setF({ ...f, link: e.target.value })} /></label>
        {f.kind === "banner" && <>
          <div className="sm:col-span-2"><div className="text-sm font-medium">Desktop image</div><ImageInput admin kind="merchandising" value={f.image_desktop ? [f.image_desktop] : []} max={1} onChange={(v) => setF({ ...f, image_desktop: v[0] || "" })} testid="merch-img-d" /></div>
          <div className="sm:col-span-2"><div className="text-sm font-medium">Mobile image (optional)</div><ImageInput admin kind="merchandising" value={f.image_mobile ? [f.image_mobile] : []} max={1} onChange={(v) => setF({ ...f, image_mobile: v[0] || "" })} testid="merch-img-m" /></div>
          <label className="text-sm font-medium sm:col-span-2">Image description (alternative text)<Input className="mt-1 h-11 rounded-xl" maxLength={125} value={f.alt || ""} onChange={(e) => setF({ ...f, alt: e.target.value })} /></label>
        </>}
        {f.kind === "featured_categories" && <div className="flex flex-wrap gap-2 sm:col-span-2">{PILLARS.map((c) => { const on = (f.categories || []).includes(c); return (
          <button type="button" key={c} aria-pressed={on} onClick={() => setF({ ...f, categories: on ? f.categories.filter((x) => x !== c) : [...(f.categories || []), c] })}
            className={`h-10 rounded-full px-4 text-sm font-semibold ${on ? "hg-chip-on text-white" : "hg-chip-off"}`}>{c}</button>); })}</div>}
        {["new_arrivals", "bestsellers"].includes(f.kind) && <label className="text-sm font-medium">How many products<Input type="number" min="1" max="24" className="mt-1 h-11 rounded-xl" value={f.limit} onChange={(e) => setF({ ...f, limit: e.target.value })} /></label>}
        {f.kind === "bestsellers" && <label className="text-sm font-medium">Sales in the last N days<Input type="number" min="1" max="365" className="mt-1 h-11 rounded-xl" value={f.window_days} onChange={(e) => setF({ ...f, window_days: e.target.value })} /></label>}
        {["collection", "featured_products"].includes(f.kind) && (
          <div className="space-y-2 sm:col-span-2">
            <div className="text-sm font-medium">Products (in this order)</div>
            <ol className="space-y-1">{ids.map((id, i) => <li key={id} className="hg-tile flex items-center gap-2 px-3 py-1.5 text-sm"><span className="flex-1 truncate">{i + 1}. {names[id] || id}</span>
              <button aria-label="Up" disabled={i === 0} onClick={() => { const n = [...ids]; [n[i - 1], n[i]] = [n[i], n[i - 1]]; setF({ ...f, product_ids: n }); }}><ArrowUp size={14} /></button>
              <button aria-label="Remove" onClick={() => setF({ ...f, product_ids: ids.filter((x) => x !== id) })}><X size={14} /></button></li>)}</ol>
            <div className="flex gap-2"><Input className="h-10 rounded-xl" placeholder="Search products on sale" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), search())} />
              <Button variant="outline" className="h-10 rounded-full" onClick={search}><Search size={15} /></Button></div>
            <div className="flex flex-wrap gap-2">{found.filter((p) => !ids.includes(p.id)).map((p) => <button key={p.id} type="button" onClick={() => { setNames({ ...names, [p.id]: p.name }); setF({ ...f, product_ids: [...ids, p.id].slice(0, 24) }); }} className="hg-chip-off rounded-full px-3 py-1 text-xs">+ {p.name}</button>)}</div>
          </div>
        )}
      </div>
      <div className="mt-4 flex justify-end gap-2"><Button variant="outline" className="rounded-full" onClick={onClose} disabled={busy}>Cancel</Button>
        <Button className="hg-btn rounded-full" onClick={save} disabled={busy || f.title.trim().length < 2} data-testid="merch-save">{busy ? <Loader2 size={15} className="animate-spin" /> : "Save"}</Button></div>
    </SectionCard>
  );
}
