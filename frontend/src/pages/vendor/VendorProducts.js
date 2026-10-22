import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Package, Plus, Pencil, Boxes, Pause, Play, Info, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { Stagger, StaggerItem } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { inr } from "@/pages/vendor/VendorDashboard";

const PILLARS = ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"];
const PILLAR_KEY = { "Sarees": "pillar.sarees.t", "Fashion Products": "pillar.fashion.t", "Makeup, Beauty & Skincare": "pillar.beauty.t", "Household Essentials": "pillar.household.t" };
const APPROVAL_TONE = { pending: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30", approved: "bg-hg-success/15 text-hg-success ring-hg-success/30", rejected: "bg-danger/10 text-danger ring-danger/30" };
const EMPTY = { sku: "", name: "", name_hi: "", description: "", description_hi: "", image: "", mrp: "", selling_price: "", gst_percent: 5, stock: 0, category: PILLARS[0], return_policy: "" };

export default function VendorProducts() {
  const { t, lang } = useI18n();
  const [items, setItems] = useState(null);
  const [edit, setEdit] = useState(null);      // product being created/edited (form state)
  const [stockFor, setStockFor] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => API.get("/vendor/products").then(({ data }) => setItems(data)).catch(() => setItems([])), []);
  useEffect(() => { load(); }, [load]);

  const openNew = () => setEdit({ ...EMPTY });
  const openEdit = (p) => setEdit({ ...EMPTY, ...p, image: (p.images || [])[0] || "" });

  const save = async () => {
    setBusy(true);
    try {
      const body = { ...edit, mrp: Number(edit.mrp), selling_price: Number(edit.selling_price), gst_percent: Number(edit.gst_percent),
        stock: Number(edit.stock) || 0, images: edit.image ? [edit.image.trim()] : [] };
      if (edit.id) await API.put(`/vendor/products/${edit.id}`, body);
      else await API.post("/vendor/products", body);
      toast.success(t("vp.p.save") + " ✓");
      setEdit(null); load();
    } catch (err) { toast.error(apiError(err)); }
    finally { setBusy(false); }
  };

  const toggleListing = async (p) => {
    try { await API.post(`/vendor/products/${p.id}/listing`, { active: !p.is_active }); load(); }
    catch (err) { toast.error(apiError(err)); }
  };

  return (
    <div className="space-y-5">
      <PageHeader title={t("vp.products")} icon={Package}
        actions={<Button onClick={openNew} className="hg-btn h-11 rounded-full px-5" data-testid="vp-add-product"><Plus size={16} /> {t("vp.addProduct")}</Button>} />

      {!items ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-48 rounded-3xl" />)}</div>
        : items.length === 0 ? <EmptyState icon={Package} title={t("vp.noProducts")} ctaLabel={t("vp.addProduct")} onCta={openNew} testid="vp-empty" />
        : (
          <Stagger className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((p) => (
              <StaggerItem key={p.id} className="hg-card hg-lift flex min-w-0 flex-col p-5" data-testid={`vp-product-${p.sku}`}>
                <div className="flex items-start gap-3.5">
                  {p.images?.[0] ? <img src={p.images[0]} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover ring-1 ring-brand-50" />
                    : <span className="hg-icon-chip !h-16 !w-16"><Package size={22} /></span>}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap gap-1.5">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ring-1 ${APPROVAL_TONE[p.approval_status] || APPROVAL_TONE.approved}`}>{t(`vp.a.${p.approval_status || "approved"}`)}</span>
                      {p.approval_status === "approved" && (
                        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ring-1 ${p.is_active ? "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/30" : "bg-white/10 text-muted2 ring-white/15"}`}>{p.is_active ? t("vp.live") : t("vp.paused")}</span>
                      )}
                    </div>
                    <h3 className="mt-1.5 line-clamp-2 font-medium leading-snug text-ink">{lang === "hi" && p.name_hi ? p.name_hi : p.name}</h3>
                    <div className="mt-0.5 truncate font-mono text-xs text-muted2">{p.sku} · {t(PILLAR_KEY[p.category] || "") || p.category}</div>
                  </div>
                </div>
                {p.approval_status === "rejected" && p.rejection_reason && (
                  <p className="mt-3 rounded-xl bg-danger/10 px-3 py-2 text-xs text-ink ring-1 ring-danger/25" data-testid={`vp-reject-${p.sku}`}>{p.rejection_reason}</p>
                )}
                <div className="mt-4 flex items-baseline gap-2">
                  <span className="font-display text-lg font-semibold text-ink">{inr(p.selling_price)}</span>
                  {p.mrp > p.selling_price && <span className="text-sm text-muted2 line-through">{inr(p.mrp)}</span>}
                  <span className={`ml-auto text-sm font-semibold ${p.stock <= 5 ? "text-danger" : "text-muted2"}`} data-testid={`vp-stock-${p.sku}`}>{t("vp.stock")}: {p.stock}</span>
                </div>
                <div className="mt-auto flex flex-wrap gap-2 pt-4">
                  <Button onClick={() => openEdit(p)} variant="outline" size="sm" className="h-9 flex-1 rounded-full border-brand-50 bg-transparent" data-testid={`vp-edit-${p.sku}`}><Pencil size={14} /> {t("vp.editProduct")}</Button>
                  <Button onClick={() => setStockFor(p)} variant="outline" size="sm" className="h-9 rounded-full border-brand-50 bg-transparent" aria-label={t("vp.adjust")} data-testid={`vp-stockbtn-${p.sku}`}><Boxes size={14} /></Button>
                  {p.approval_status === "approved" && (
                    <Button onClick={() => toggleListing(p)} variant="outline" size="sm" className="h-9 rounded-full border-brand-50 bg-transparent" aria-label={p.is_active ? t("vp.pause") : t("vp.resume")} title={p.is_active ? t("vp.pause") : t("vp.resume")} data-testid={`vp-listing-${p.sku}`}>
                      {p.is_active ? <Pause size={14} /> : <Play size={14} />}
                    </Button>
                  )}
                </div>
              </StaggerItem>
            ))}
          </Stagger>
        )}

      {/* Create / edit */}
      <Dialog open={!!edit} onOpenChange={(o) => !o && setEdit(null)}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto rounded-3xl">
          <DialogHeader><DialogTitle>{edit?.id ? t("vp.editProduct") : t("vp.addProduct")}</DialogTitle></DialogHeader>
          {edit && (
            <div className="space-y-4">
              {edit.id && <p className="flex gap-2 rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25"><Info size={14} className="mt-px shrink-0 text-hg-gold" />{t("vp.p.reviewNote")}</p>}
              <div className="grid gap-4 sm:grid-cols-2">
                <F label={t("vp.p.sku")} value={edit.sku} disabled={!!edit.id} onChange={(v) => setEdit({ ...edit, sku: v })} testid="vpf-sku" />
                <div>
                  <Label className="text-sm text-ink">{t("vp.p.category")}</Label>
                  <select value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} data-testid="vpf-category"
                    className="mt-1.5 h-11 w-full rounded-xl border border-input bg-transparent px-3 text-sm text-ink">
                    {PILLARS.map((c) => <option key={c} value={c}>{t(PILLAR_KEY[c])}</option>)}
                  </select>
                </div>
                <F label={t("vp.p.name")} value={edit.name} onChange={(v) => setEdit({ ...edit, name: v })} testid="vpf-name" />
                <F label={t("vp.p.nameHi")} value={edit.name_hi} onChange={(v) => setEdit({ ...edit, name_hi: v })} testid="vpf-name-hi" />
              </div>
              <div>
                <Label className="text-sm text-ink">{t("vp.p.desc")}</Label>
                <Textarea value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} className="mt-1.5 rounded-xl" rows={3} data-testid="vpf-desc" />
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <F label={t("vp.p.mrp")} type="number" value={edit.mrp} onChange={(v) => setEdit({ ...edit, mrp: v })} testid="vpf-mrp" />
                <F label={t("vp.p.price")} type="number" value={edit.selling_price} onChange={(v) => setEdit({ ...edit, selling_price: v })} testid="vpf-price" />
                <F label={t("vp.p.gst")} type="number" value={edit.gst_percent} onChange={(v) => setEdit({ ...edit, gst_percent: v })} testid="vpf-gst" />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                {!edit.id && <F label={t("vp.p.stock")} type="number" value={edit.stock} onChange={(v) => setEdit({ ...edit, stock: v })} testid="vpf-stock" />}
                <F label={t("vp.p.image")} value={edit.image} onChange={(v) => setEdit({ ...edit, image: v })} testid="vpf-image" />
              </div>
              <F label={t("vp.p.returns")} value={edit.return_policy} onChange={(v) => setEdit({ ...edit, return_policy: v })} testid="vpf-returns" />
              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setEdit(null)} className="h-11 rounded-full border-brand-50 bg-transparent px-5">{t("cta.cancel")}</Button>
                <Button onClick={save} disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="vpf-save">{t("vp.p.save")}</Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {stockFor && <StockDialog p={stockFor} t={t} onClose={() => setStockFor(null)} onDone={() => { setStockFor(null); load(); }} />}
    </div>
  );
}

function F({ label, value, onChange, type = "text", disabled, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input type={type} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)} className="mt-1.5" data-testid={testid} /></div>;
}

function StockDialog({ p, t, onClose, onDone }) {
  const [delta, setDelta] = useState("");
  const [reason, setReason] = useState("");
  const [hist, setHist] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { API.get(`/vendor/products/${p.id}/stock-history`).then(({ data }) => setHist(data)).catch(() => setHist([])); }, [p.id]);
  const submit = async () => {
    setBusy(true);
    try { await API.post(`/vendor/products/${p.id}/stock`, { delta: parseInt(delta, 10), reason }); toast.success(t("vp.adjust") + " ✓"); onDone(); }
    catch (err) { toast.error(apiError(err)); }
    finally { setBusy(false); }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md rounded-3xl">
        <DialogHeader><DialogTitle>{t("vp.adjust")} · {p.name}</DialogTitle></DialogHeader>
        <div className="text-sm text-muted2">{t("vp.stock")}: <b className="text-ink">{p.stock}</b></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div><Label className="text-sm text-ink">{t("vp.adjustQty")}</Label><Input type="number" value={delta} onChange={(e) => setDelta(e.target.value)} className="mt-1.5" data-testid="vps-delta" /></div>
          <div><Label className="text-sm text-ink">{t("vp.adjustReason")}</Label><Input value={reason} onChange={(e) => setReason(e.target.value)} className="mt-1.5" data-testid="vps-reason" /></div>
        </div>
        <Button onClick={submit} disabled={busy || !delta || reason.trim().length < 3} className="hg-btn h-11 rounded-full" data-testid="vps-save">{t("vp.confirm")}</Button>
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><History size={15} /> {t("vp.history")}</div>
          <div className="max-h-48 space-y-1.5 overflow-y-auto">
            {(hist || []).map((h) => (
              <div key={h.id} className="hg-tile flex items-center justify-between px-3 py-2 text-xs">
                <span className="truncate text-muted2">{(h.created_at || "").slice(0, 16).replace("T", " ")} · {h.reason}</span>
                <span className={`shrink-0 font-semibold ${h.delta > 0 ? "text-hg-success" : "text-danger"}`}>{h.delta > 0 ? "+" : ""}{h.delta}</span>
              </div>
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
