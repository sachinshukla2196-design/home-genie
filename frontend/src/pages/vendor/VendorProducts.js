import React, { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Package, Plus, Pencil, Pause, Play, Archive, ArchiveRestore, Download, Upload, Boxes, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { Pager, SearchBox, useDebounced } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { ConfirmDialog, Money, Pill, StateBlock, downloadCsv, fmtDate, useAction, usePaged } from "@/components/vendor/kit";
import { EMPTY_PRODUCT, ProductForm, fromProduct, toPayload, useCatalogueSpec } from "@/components/vendor/ProductForm";
import { ImportDialog } from "@/components/vendor/ImportDialog";

const FILTERS = [["all", "vp.o.all"], ["pending", "vp.a.pending"], ["approved", "vp.a.approved"], ["rejected", "vp.a.rejected"], ["low", "vp.p.f.low"], ["out", "vp.p.f.out"]];
const SORTS = [["created:desc", "vx.sort.newest"], ["updated:desc", "vx.sort.updated"], ["name:asc", "vx.sort.name"], ["price:asc", "vx.sort.priceLow"], ["price:desc", "vx.sort.priceHigh"], ["stock:asc", "vx.sort.stockLow"]];
const APPROVAL_TONE = { pending: "warn", approved: "ok", rejected: "bad" };
const SELECT = "h-11 rounded-full bg-white/5 px-4 text-sm text-ink ring-1 ring-white/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet";

export default function VendorProducts() {
  const { t, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const filter = sp.get("approval") || sp.get("stock") || "all";
  const category = sp.get("category") || "";
  const sort = sp.get("sort") || "created:desc";
  const showArchived = sp.get("archived") === "true";
  const [q, setQ] = useState("");
  const dq = useDebounced(q.trim());
  const [sortKey, sortOrder] = sort.split(":");
  const params = { q: dq || undefined, category: category || undefined, sort: sortKey, order: sortOrder, archived: showArchived || undefined,
    approval: ["pending", "approved", "rejected"].includes(filter) ? filter : undefined, stock: ["low", "out"].includes(filter) ? filter : undefined };
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/products", params, 12);
  const spec = useCatalogueSpec();
  const [edit, setEdit] = useState(null);       // product form state
  const [confirm, setConfirm] = useState(null); // { kind, p }
  const [importing, setImporting] = useState(false);
  const [run, busy] = useAction();

  const update = (patch) => { const n = new URLSearchParams(sp); Object.entries(patch).forEach(([k, v]) => (v ? n.set(k, v) : n.delete(k))); setSp(n, { replace: true }); };
  const setFilter = (k) => update({ approval: undefined, stock: undefined, ...(["low", "out"].includes(k) ? { stock: k } : k !== "all" ? { approval: k } : {}) });

  const save = () => run(async () => {
    const body = toPayload(edit);
    if (edit.id) await API.put(`/vendor/products/${edit.id}`, body); else await API.post("/vendor/products", body);
    setEdit(null); reload();
  }, { success: t("vp.p.save") + " ✓" });
  const toggleListing = (p) => run(async () => { await API.post(`/vendor/products/${p.id}/listing`, { active: !p.is_active }); reload(); });
  const archive = (p, archived) => run(async () => { await API.post(`/vendor/products/${p.id}/archive`, { archived }); setConfirm(null); reload(); }, { success: t(archived ? "vx.prod.archived" : "vx.prod.restored") });
  const exportCsv = () => downloadCsv("/vendor/products/export.csv", "my-products.csv").catch((e) => toast.error(apiError(e)));

  const counts = data?.counts;
  return (
    <div className="space-y-5">
      <PageHeader title={t("vp.products")} icon={Package}
        actions={<>
          <Button variant="outline" onClick={exportCsv} className="h-11 rounded-full" data-testid="vp-export"><Download size={15} /> {t("vx.export")}</Button>
          <Button variant="outline" onClick={() => setImporting(true)} className="h-11 rounded-full" data-testid="vp-import"><Upload size={15} /> {t("vx.import")}</Button>
          <Button onClick={() => setEdit({ ...EMPTY_PRODUCT })} className="hg-btn h-11 rounded-full px-5" data-testid="vp-add-product"><Plus size={16} /> {t("vp.addProduct")}</Button>
        </>} />

      {counts && (counts.all > 0 || counts.archived > 0) && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SearchBox value={q} onChange={setQ} placeholder={t("vp.searchProducts")} testid="vp-search" />
            <label className="sr-only" htmlFor="vp-category">{t("vx.pf.category")}</label>
            <select id="vp-category" className={SELECT} value={category} onChange={(e) => update({ category: e.target.value })} data-testid="vp-category-filter">
              <option value="">{t("vx.allCategories")}</option>
              {(spec?.pillars || []).map((pl) => <option key={pl} value={pl}>{t(`vx.pillar.${pl}`)}</option>)}
            </select>
            <label className="sr-only" htmlFor="vp-sort">{t("vx.sortBy")}</label>
            <select id="vp-sort" className={SELECT} value={sort} onChange={(e) => update({ sort: e.target.value === "created:desc" ? "" : e.target.value })} data-testid="vp-sort">
              {SORTS.map(([k, l]) => <option key={k} value={k}>{t(l)}</option>)}
            </select>
          </div>
          <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist">
            {FILTERS.map(([k, label]) => (
              <button key={k} role="tab" aria-selected={!showArchived && filter === k} onClick={() => { update({ archived: "" }); setFilter(k); }} data-testid={`vp-filter-${k}`}
                className={`shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${!showArchived && filter === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(label)} · {counts[k === "all" ? "all" : k] ?? 0}</button>
            ))}
            <button role="tab" aria-selected={showArchived} onClick={() => update({ archived: showArchived ? "" : "true", approval: "", stock: "" })} data-testid="vp-filter-archived"
              className={`shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${showArchived ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t("vx.prod.archivedTab")} · {counts.archived}</button>
          </div>
        </div>
      )}

      <StateBlock loading={loading} error={error} onRetry={reload} rows={3} testid="vp"
        empty={items && items.length === 0} emptyIcon={Package} emptyTitle={counts && (counts.all > 0 || counts.archived > 0) ? t("vp.noMatch") : t("vp.noProducts")}
        ctaLabel={counts && counts.all === 0 && counts.archived === 0 ? t("vp.addProduct") : undefined} onCta={() => setEdit({ ...EMPTY_PRODUCT })}>
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {(items || []).map((p) => (
            <li key={p.id} className="hg-card hg-lift flex min-w-0 flex-col p-5" data-testid={`vp-product-${p.sku}`}>
              <div className="flex items-start gap-3.5">
                {p.images?.[0] ? <img src={p.images[0]} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover ring-1 ring-brand-50" loading="lazy" /> : <span className="hg-icon-chip !h-16 !w-16" aria-hidden><Package size={22} /></span>}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap gap-1.5">
                    <Pill tone={APPROVAL_TONE[p.approval_status] || "ok"}>{t(`vp.a.${p.approval_status || "approved"}`)}</Pill>
                    {p.archived ? <Pill tone="muted">{t("vx.prod.archivedTab")}</Pill> : p.approval_status === "approved" && <Pill tone={p.is_active ? "violet" : "muted"}>{p.is_active ? t("vp.live") : t("vp.paused")}</Pill>}
                  </div>
                  <h3 className="mt-1.5 line-clamp-2 font-medium leading-snug text-ink">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h3>
                  <div className="mt-0.5 truncate font-mono text-xs text-muted2">{p.sku} · {t(`vx.pillar.${p.category}`)}</div>
                </div>
              </div>
              {p.approval_status === "rejected" && p.rejection_reason && (
                <p className="mt-3 flex gap-2 rounded-xl bg-danger/10 p-2.5 text-xs text-danger" role="note" data-testid={`vp-reject-${p.sku}`}><AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden /> <span><b>{t("vx.prod.rejectedWhy")}</b> {p.rejection_reason}</span></p>
              )}
              <div className="mt-4 flex items-baseline gap-2"><Money value={p.selling_price} className="text-lg font-semibold text-hg-lavender" />{p.mrp > p.selling_price && <Money value={p.mrp} className="text-xs text-muted2 line-through" />}</div>
              <div className="mt-1 flex items-center gap-2 text-xs text-muted2"><Boxes size={13} aria-hidden /> {t("vp.stock")}: <b className={p.stock <= 0 ? "text-danger" : "text-ink"}>{p.stock}</b>{p.variants?.length > 0 && <span>· {t("vx.prod.nVariants", { n: p.variants.length })}</span>}<span className="ml-auto">{fmtDate(p.updated_at, lang)}</span></div>
              <div className="mt-4 flex flex-wrap gap-2">
                {!p.archived && <Button variant="outline" className="h-9 rounded-full" onClick={() => setEdit(fromProduct(p))} data-testid={`vp-edit-${p.sku}`}><Pencil size={14} /> {t("vp.editProduct")}</Button>}
                {!p.archived && p.approval_status === "approved" && <Button variant="outline" className="h-9 rounded-full" disabled={busy} onClick={() => toggleListing(p)} data-testid={`vp-toggle-${p.sku}`}>{p.is_active ? <><Pause size={14} /> {t("vp.pause")}</> : <><Play size={14} /> {t("vp.resume")}</>}</Button>}
                {!p.archived && <Link to={`/vendor/inventory?q=${encodeURIComponent(p.sku)}`} className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 text-sm text-hg-lavender hover:bg-brand-50/60"><Boxes size={14} /> {t("vx.nav.inventory")}</Link>}
                <Button variant="ghost" className="h-9 rounded-full" onClick={() => setConfirm({ kind: p.archived ? "restore" : "archive", p })} data-testid={`vp-archive-${p.sku}`}>{p.archived ? <><ArchiveRestore size={14} /> {t("vx.prod.restore")}</> : <><Archive size={14} /> {t("vx.prod.archive")}</>}</Button>
              </div>
            </li>
          ))}
        </ul>
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="vp-pager" />}

      <Dialog open={!!edit} onOpenChange={(o) => !o && !busy && setEdit(null)}>
        <DialogContent className="max-h-[92vh] max-w-3xl overflow-y-auto rounded-3xl" data-testid="vp-dialog">
          <DialogHeader><DialogTitle>{edit?.id ? t("vp.editProduct") : t("vp.addProduct")}</DialogTitle><DialogDescription>{t("vx.pf.reviewNote")}</DialogDescription></DialogHeader>
          {edit && <ProductForm value={edit} onChange={setEdit} isEdit={!!edit.id} spec={spec} />}
          <div className="sticky bottom-0 -mx-6 flex justify-end gap-2 border-t border-white/10 bg-background/90 px-6 py-3 backdrop-blur">
            <Button variant="outline" className="h-11 rounded-full" onClick={() => setEdit(null)} disabled={busy}>{t("vx.cancel")}</Button>
            <Button className="hg-btn h-11 rounded-full px-6" onClick={save} disabled={busy || !edit?.sku || !edit?.name || !edit?.mrp || !edit?.selling_price} data-testid="vp-save">{busy ? t("vx.saving") : t("vp.p.save")}</Button>
          </div>
        </DialogContent>
      </Dialog>

      <ConfirmDialog open={!!confirm} busy={busy} danger={confirm?.kind === "archive"} onClose={() => setConfirm(null)}
        title={confirm?.kind === "archive" ? t("vx.prod.archiveTitle") : t("vx.prod.restoreTitle")} body={confirm?.kind === "archive" ? t("vx.prod.archiveBody") : t("vx.prod.restoreBody")}
        confirmLabel={confirm?.kind === "archive" ? t("vx.prod.archive") : t("vx.prod.restore")} onConfirm={() => archive(confirm.p, confirm.kind === "archive")} />
      <ImportDialog open={importing} onClose={() => setImporting(false)} onDone={() => { reload(); }} />
    </div>
  );
}
