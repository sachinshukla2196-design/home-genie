import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Plus, Pencil, Power, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const EMPTY = { sku: "", name: "", name_hi: "", description: "", description_hi: "", images: [""], mrp: 0, selling_price: 0, gst_percent: 5, stock: 100, category: "General", is_active: true, is_activation_product: false };

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

  if (!products) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.products")}</h1>
        <Button onClick={openNew} className="rounded-full bg-forest hover:bg-brand" data-testid="admin-add-product"><Plus size={16} className="mr-1.5" /> {t("cta.getStarted")}</Button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {products.map((p) => (
          <div key={p.id} className={`rounded-2xl border bg-white p-5 shadow-card ${p.is_active ? "border-brand-50" : "border-danger/30 opacity-70"}`} data-testid={`admin-product-${p.sku}`}>
            <div className="flex items-start justify-between">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-gold">{p.category}</div>
                <h3 className="mt-1 font-display font-medium text-ink">{p.name}</h3>
                <div className="mt-1 text-sm text-muted2">{p.sku}</div>
              </div>
              {p.is_activation_product && <span className="rounded-full bg-gold px-2 py-0.5 text-[10px] font-bold text-forest">ACTIVATION</span>}
            </div>
            <div className="mt-3 flex items-baseline gap-2"><span className="font-display text-lg font-semibold text-forest">{money(p.selling_price)}</span><span className="text-sm text-muted2 line-through">{money(p.mrp)}</span></div>
            <div className="mt-1 text-xs text-muted2">Stock: {p.stock} · GST {p.gst_percent}%</div>
            <div className="mt-4 flex gap-2">
              <Button onClick={() => openEdit(p)} variant="outline" size="sm" className="flex-1 rounded-full border-forest/20 text-forest" data-testid={`edit-${p.sku}`}><Pencil size={14} className="mr-1" /> Edit</Button>
              <Button onClick={() => toggle(p)} variant="outline" size="sm" className={`rounded-full ${p.is_active ? "border-danger/30 text-danger" : "border-brand/30 text-brand"}`} data-testid={`toggle-${p.sku}`}><Power size={14} /></Button>
              <Button onClick={() => del(p)} variant="outline" size="sm" className="rounded-full border-danger/40 text-danger hover:bg-danger/10" data-testid={`delete-${p.sku}`}><Trash2 size={14} /></Button>
            </div>
          </div>
        ))}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader><DialogTitle>{editing ? "Edit Product" : "New Product"}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <FF label="SKU" value={form.sku} onChange={set("sku")} testid="pf-sku" />
              <FF label="Category" value={form.category} onChange={set("category")} testid="pf-category" />
            </div>
            <FF label="Name (EN)" value={form.name} onChange={set("name")} testid="pf-name" />
            <FF label="Name (HI)" value={form.name_hi} onChange={set("name_hi")} testid="pf-name-hi" />
            <div><Label className="text-sm">Description (EN)</Label><Textarea value={form.description} onChange={set("description")} className="mt-1.5" data-testid="pf-desc" /></div>
            <div>
              <Label className="text-sm">Product Image</Label>
              <div className="mt-1.5 flex items-center gap-3">
                {form.images?.[0]
                  ? <img src={form.images[0]} alt="" className="h-16 w-16 rounded-lg border border-brand-50 object-cover" data-testid="pf-image-preview" />
                  : <div className="flex h-16 w-16 items-center justify-center rounded-lg border border-dashed border-brand-50 text-[10px] text-muted2">No image</div>}
                <div className="flex-1 space-y-2">
                  <input type="file" accept="image/jpeg,image/png,image/webp" disabled={imgUploading} onChange={onImageFile} className="block w-full text-xs text-muted2 file:mr-2 file:cursor-pointer file:rounded-full file:border-0 file:bg-forest file:px-3 file:py-1.5 file:text-white hover:file:bg-brand disabled:opacity-50" data-testid="pf-image-upload" />
                  {imgUploading && <p className="text-xs text-muted2" data-testid="pf-image-uploading">Uploading…</p>}
                  <Input placeholder="…or paste an image URL" value={form.images[0]?.startsWith("data:") ? "" : (form.images[0] || "")} onChange={(e) => setForm((f) => ({ ...f, images: [e.target.value] }))} className="h-9" data-testid="pf-image-url" />
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-3">
              <FF label="MRP" type="number" value={form.mrp} onChange={set("mrp")} testid="pf-mrp" />
              <FF label="Price" type="number" value={form.selling_price} onChange={set("selling_price")} testid="pf-price" />
              <FF label="Stock" type="number" value={form.stock} onChange={set("stock")} testid="pf-stock" />
            </div>
            <label className="flex items-center justify-between rounded-lg border border-brand-50 p-3 text-sm"><span>Activation / Qualifying Product</span><Switch checked={form.is_activation_product} onCheckedChange={(v) => setForm((f) => ({ ...f, is_activation_product: v }))} data-testid="pf-activation" /></label>
          </div>
          <DialogFooter><Button onClick={save} className="rounded-full bg-forest hover:bg-brand" data-testid="pf-save">{t("cta.save")}</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function FF({ label, type = "text", value, onChange, testid }) {
  return <div><Label className="text-sm">{label}</Label><Input type={type} value={value} onChange={onChange} className="mt-1.5 h-10" data-testid={testid} /></div>;
}
