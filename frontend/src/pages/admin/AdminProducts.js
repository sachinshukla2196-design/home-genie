import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Power, Trash2, Package, ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/PageHeader";
import { EmptyState } from "@/components/EmptyState";
import { Stagger, StaggerItem } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const EMPTY = { sku: "", name: "", name_hi: "", description: "", description_hi: "", images: [""], mrp: 0, selling_price: 0, gst_percent: 5, stock: 100, category: "Household Essentials", is_active: true, options: [] };

export default function AdminProducts() {
  const { t } = useI18n();
  const [products, setProducts] = useState(null);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [imgUploading, setImgUploading] = useState(false);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  const load = useCallback(() => API.get("/products?active=false").then(({ data }) => setProducts(data)).catch(() => setProducts([])), []);
  useEffect(() => { load(); }, [load]);

  const openNew = () => { setEditing(null); setForm(EMPTY); setOpen(true); };
  const openEdit = (p) => { setEditing(p); setForm({ ...p, images: p.images?.length ? p.images : [""] }); setOpen(true); };

  const save = async () => {
    const payload = { ...form, mrp: parseFloat(form.mrp), selling_price: parseFloat(form.selling_price), gst_percent: parseFloat(form.gst_percent), stock: parseInt(form.stock), images: form.images.filter(Boolean) };
    try {
      if (editing) await API.put(`/admin/products/${editing.id}`, payload);
      else await API.post("/admin/products", payload);
      toast.success(t("cta.save")); setOpen(false); load();
    } catch (err) { toast.error(apiError(err)); }
  };
  const toggle = async (p) => { try { if (p.is_active) { await API.delete(`/admin/products/${p.id}`); } else { await API.put(`/admin/products/${p.id}`, { ...p, is_active: true }); } load(); } catch (err) { toast.error(apiError(err)); } };
  const del = async (p) => { if (!window.confirm(`Permanently delete "${p.name}"? This cannot be undone.`)) return; try { await API.delete(`/admin/products/${p.id}/permanent`); toast.success("Product deleted"); load(); } catch (err) { toast.error(apiError(err)); } };
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target?.value ?? e }));

  const onImageFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) { toast.error("Only JPG, PNG or WebP images are allowed."); return; }
    if (file.size > 5 * 1024 * 1024) { toast.error("Image too large. Please choose an image under 5MB."); return; }
    setImgUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await API.post("/admin/uploads/product-image", fd);
      setForm((f) => ({ ...f, images: [data.url] }));
      toast.success("Image uploaded");
    } catch (err) { toast.error(apiError(err)); }
    finally { setImgUploading(false); e.target.value = ""; }
  };

  const addBtn = <Button onClick={openNew} className="hg-btn h-11 rounded-full px-6" data-testid="admin-add-product"><Plus size={16} className="mr-1.5" /> {t("cta.getStarted")}</Button>;

  if (!products) return (
    <div className="space-y-5">
      <PageHeader title={t("nav.products")} icon={Package} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-52 rounded-[20px]" />)}</div>
    </div>
  );

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.products")} icon={Package} actions={addBtn} />
      {products.length === 0 && <EmptyState icon={Package} title={t("nav.products")} />}
      <Stagger className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {products.map((p) => (
          <StaggerItem key={p.id} className={`hg-card hg-lift flex min-w-0 flex-col p-5 ${p.is_active ? "" : "opacity-70 ring-1 ring-danger/30"}`} data-testid={`admin-product-${p.sku}`}>
            <div className="flex items-start gap-3.5">
              {p.images?.[0]
                ? <img src={p.images[0]} alt="" className="h-16 w-16 shrink-0 rounded-xl object-cover ring-1 ring-brand-50" loading="lazy" />
                : <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl bg-hg-violet/10 text-hg-lavender ring-1 ring-brand-50"><ImageIcon size={22} /></span>}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="max-w-full truncate text-xs font-semibold uppercase tracking-wide text-hg-lavender">{p.category}</span>
                  {!p.is_active && <span className="rounded-full bg-danger/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-danger ring-1 ring-danger/25">Inactive</span>}
                </div>
                <h3 className="mt-1 break-words font-display font-medium leading-snug text-ink">{p.name}</h3>
                <div className="mt-0.5 truncate font-mono text-xs text-muted2">{p.sku}</div>
              </div>
            </div>
            <div className="mt-4 flex items-baseline gap-2"><span className="font-display text-lg font-semibold tabular-nums text-ink">{money(p.selling_price)}</span><span className="text-sm tabular-nums text-muted2 line-through">{money(p.mrp)}</span></div>
            <div className="mt-1 text-xs text-muted2">Stock: {p.stock} · GST {p.gst_percent}%</div>
            <div className="mt-auto flex gap-2 pt-4">
              <Button onClick={() => openEdit(p)} variant="outline" size="sm" className="h-9 flex-1 rounded-full border-brand-50 bg-transparent" data-testid={`edit-${p.sku}`}><Pencil size={14} className="mr-1" /> Edit</Button>
              <Button onClick={() => toggle(p)} variant="outline" size="sm" aria-label={p.is_active ? "Deactivate product" : "Activate product"} title={p.is_active ? "Deactivate" : "Activate"} className={`h-9 w-9 rounded-full bg-transparent p-0 ${p.is_active ? "border-danger/30 text-danger hover:bg-danger/10 hover:text-danger" : "border-hg-success/40 text-hg-success hover:bg-hg-success/10 hover:text-hg-success"}`} data-testid={`toggle-${p.sku}`}><Power size={14} /></Button>
              <Button onClick={() => del(p)} variant="outline" size="sm" aria-label="Delete product" title="Delete" className="h-9 w-9 rounded-full border-danger/40 bg-transparent p-0 text-danger hover:bg-danger/10 hover:text-danger" data-testid={`delete-${p.sku}`}><Trash2 size={14} /></Button>
            </div>
          </StaggerItem>
        ))}
      </Stagger>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[88vh] overflow-y-auto sm:max-w-2xl">
          <DialogHeader><DialogTitle className="font-display text-xl">{editing ? "Edit Product" : "New Product"}</DialogTitle></DialogHeader>
          <div className="space-y-5">
            <section className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <FF label="SKU" value={form.sku} onChange={set("sku")} testid="pf-sku" />
                <FF label="Category" value={form.category} onChange={set("category")} testid="pf-category" />
                <FF label="Name (EN)" value={form.name} onChange={set("name")} testid="pf-name" />
                <FF label="Name (HI)" value={form.name_hi} onChange={set("name_hi")} testid="pf-name-hi" />
              </div>
              <div><Label className="text-sm text-ink">Description (EN)</Label><Textarea value={form.description} onChange={set("description")} className="mt-1.5 min-h-[96px] rounded-xl" data-testid="pf-desc" /></div>
            </section>
            <section className="hg-tile rounded-2xl p-4">
              <Label className="text-sm text-ink">Product Image</Label>
              <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-center">
                {form.images?.[0]
                  ? <img src={form.images[0]} alt="" className="h-20 w-20 shrink-0 rounded-xl object-cover ring-1 ring-brand-50" data-testid="pf-image-preview" />
                  : <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-xl border border-dashed border-brand-50 text-[10px] text-muted2">No image</div>}
                <div className="min-w-0 flex-1 space-y-2">
                  <input type="file" accept="image/jpeg,image/png,image/webp" disabled={imgUploading} onChange={onImageFile} className="block w-full text-xs text-muted2 file:mr-2 file:cursor-pointer file:rounded-full file:border-0 file:bg-hg-violet file:px-3 file:py-1.5 file:font-semibold file:text-white hover:file:bg-hg-violet/85 disabled:opacity-50" data-testid="pf-image-upload" />
                  {imgUploading && <p className="text-xs text-muted2" data-testid="pf-image-uploading">Uploading…</p>}
                  <Input placeholder="…or paste an image URL" value={form.images[0]?.startsWith("data:") ? "" : (form.images[0] || "")} onChange={(e) => setForm((f) => ({ ...f, images: [e.target.value] }))} data-testid="pf-image-url" />
                </div>
              </div>
            </section>
            <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <FF label="MRP" type="number" value={form.mrp} onChange={set("mrp")} testid="pf-mrp" />
              <FF label="Price" type="number" value={form.selling_price} onChange={set("selling_price")} testid="pf-price" />
              <FF label="Stock" type="number" value={form.stock} onChange={set("stock")} testid="pf-stock" />
            </section>
          </div>
          <DialogFooter className="gap-2 pt-2"><Button onClick={save} className="hg-btn h-11 w-full rounded-full px-8 sm:w-auto" data-testid="pf-save">{t("cta.save")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function FF({ label, type = "text", value, onChange, testid }) {
  return <div className="min-w-0"><Label className="text-sm text-ink">{label}</Label><Input type={type} value={value} onChange={onChange} className="mt-1.5" data-testid={testid} /></div>;
}
