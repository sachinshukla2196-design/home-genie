import React, { useEffect, useMemo, useState } from "react";
import { Plus, Trash2, Eye, EyeOff } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";
import { Field, Money, Pill } from "@/components/vendor/kit";
import { ImageInput } from "@/components/vendor/ImageInput";

const SELECT = "h-10 w-full rounded-lg bg-white/5 px-3 text-sm text-ink ring-1 ring-white/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet";
const num = (v) => (v === "" || v === null || v === undefined ? undefined : Number(v));

export const EMPTY_PRODUCT = {
  sku: "", name: "", name_hi: "", short_description: "", description: "", description_hi: "", images: [], mrp: "", selling_price: "", gst_percent: 5,
  hsn_code: "", stock: 0, low_stock_threshold: 5, category: "Sarees", subcategory: "", brand: "", keywords: "", attributes: {}, package: {},
  variants: [], compliance_documents: [], declarations: "", returnable: true, return_policy: "",
};

/** Server payload from the editable form state (numbers cast, empty optional fields dropped). */
export function toPayload(f) {
  const pkg = {};
  ["weight_g", "length_cm", "width_cm", "height_cm"].forEach((k) => { if (num(f.package[k]) !== undefined) pkg[k] = num(f.package[k]); });
  if (num(f.package.handling_days) !== undefined) pkg.handling_days = parseInt(f.package.handling_days, 10);
  if (f.package.fragile) pkg.fragile = true;
  const attrs = {};
  Object.entries(f.attributes || {}).forEach(([k, v]) => { if (v !== "" && v !== undefined && v !== null) attrs[k] = v; });
  return {
    sku: f.sku.trim(), name: f.name.trim(), name_hi: f.name_hi, short_description: f.short_description, description: f.description, description_hi: f.description_hi,
    images: f.images, mrp: Number(f.mrp), selling_price: Number(f.selling_price), gst_percent: Number(f.gst_percent), hsn_code: f.hsn_code,
    stock: parseInt(f.stock, 10) || 0, low_stock_threshold: parseInt(f.low_stock_threshold, 10) || 0, category: f.category, subcategory: f.subcategory, brand: f.brand,
    keywords: String(f.keywords || "").split(",").map((x) => x.trim()).filter(Boolean).slice(0, 10), attributes: attrs, package: pkg,
    variants: (f.variants || []).map((v) => ({ sku: v.sku, attributes: v.attributes, ...(num(v.price) !== undefined ? { price: num(v.price) } : {}),
      ...(num(v.mrp) !== undefined ? { mrp: num(v.mrp) } : {}), ...(v.isNew ? { stock: parseInt(v.stock, 10) || 0 } : {}) })),
    compliance_documents: f.compliance_documents.map((d) => ({ type: d.type, url: d.url, note: d.note || "" })),
    declarations: String(f.declarations || "").split("\n").map((x) => x.trim()).filter(Boolean), returnable: !!f.returnable, return_policy: f.return_policy,
  };
}

/** Existing product -> editable form state. */
export function fromProduct(p) {
  return { ...EMPTY_PRODUCT, ...p, keywords: (p.keywords || []).join(", "), declarations: (p.declarations || []).join("\n"), attributes: p.attributes || {}, package: p.package || {},
    variants: (p.variants || []).map((v) => ({ ...v, isNew: false })), compliance_documents: p.compliance_documents || [] };
}

function Section({ title, children, testid }) {
  return <fieldset className="hg-tile space-y-3 p-4" data-testid={testid}><legend className="px-1 text-sm font-semibold text-ink">{title}</legend>{children}</fieldset>;
}

export function ProductForm({ value, onChange, isEdit, spec }) {
  const { t, lang } = useI18n();
  const [preview, setPreview] = useState(false);
  const set = (k, v) => onChange({ ...value, [k]: v });
  const attrs = useMemo(() => (spec?.attributes?.[value.category] || []), [spec, value.category]);
  const hasVariants = value.variants.length > 0;
  const setVariant = (i, patch) => set("variants", value.variants.map((v, j) => (j === i ? { ...v, ...patch } : v)));
  const attrLabel = (k) => { const l = t(`vx.attr.${k}`); return l === `vx.attr.${k}` ? k.replace(/_/g, " ") : l; };

  return (
    <div className="space-y-4" data-testid="product-form">
      <Section title={t("vx.pf.basic")} testid="pf-basic">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("vx.pf.sku")} htmlFor="pf-sku" hint={isEdit ? t("vx.pf.skuFixed") : undefined}>
            <Input id="pf-sku" value={value.sku} disabled={isEdit} onChange={(e) => set("sku", e.target.value)} className="font-mono uppercase" maxLength={40} data-testid="pf-sku" />
          </Field>
          <Field label={t("vx.pf.category")} htmlFor="pf-cat">
            <select id="pf-cat" className={SELECT} value={value.category} onChange={(e) => onChange({ ...value, category: e.target.value, attributes: {} })} data-testid="pf-category">
              {(spec?.pillars || ["Sarees", "Fashion Products", "Makeup, Beauty & Skincare", "Household Essentials"]).map((p) => <option key={p} value={p}>{t(`vx.pillar.${p}`)}</option>)}
            </select>
          </Field>
          <Field label={t("vx.pf.name")} htmlFor="pf-name" className="sm:col-span-2"><Input id="pf-name" value={value.name} onChange={(e) => set("name", e.target.value)} maxLength={140} data-testid="pf-name" /></Field>
          <Field label={t("vx.pf.nameHi")} htmlFor="pf-name-hi" className="sm:col-span-2"><Input id="pf-name-hi" value={value.name_hi} onChange={(e) => set("name_hi", e.target.value)} maxLength={140} /></Field>
          <Field label={t("vx.pf.subcategory")} htmlFor="pf-sub"><Input id="pf-sub" value={value.subcategory} onChange={(e) => set("subcategory", e.target.value)} maxLength={60} /></Field>
          <Field label={t("vx.pf.brand")} htmlFor="pf-brand"><Input id="pf-brand" value={value.brand} onChange={(e) => set("brand", e.target.value)} maxLength={60} /></Field>
          <Field label={t("vx.pf.short")} htmlFor="pf-short" className="sm:col-span-2"><Input id="pf-short" value={value.short_description} onChange={(e) => set("short_description", e.target.value)} maxLength={200} /></Field>
          <Field label={t("vx.pf.description")} htmlFor="pf-desc" className="sm:col-span-2"><Textarea id="pf-desc" rows={3} value={value.description} onChange={(e) => set("description", e.target.value)} /></Field>
          <Field label={t("vx.pf.descriptionHi")} htmlFor="pf-desc-hi" className="sm:col-span-2"><Textarea id="pf-desc-hi" rows={2} value={value.description_hi} onChange={(e) => set("description_hi", e.target.value)} /></Field>
          <Field label={t("vx.pf.keywords")} htmlFor="pf-kw" hint={t("vx.pf.keywordsHint")} className="sm:col-span-2"><Input id="pf-kw" value={value.keywords} onChange={(e) => set("keywords", e.target.value)} /></Field>
        </div>
      </Section>

      <Section title={t("vx.pf.media")} testid="pf-media"><ImageInput value={value.images} onChange={(v) => set("images", v)} /></Section>

      <Section title={t("vx.pf.pricing")} testid="pf-pricing">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("vx.pf.mrp")} htmlFor="pf-mrp"><Input id="pf-mrp" type="number" min="0" step="0.01" inputMode="decimal" value={value.mrp} onChange={(e) => set("mrp", e.target.value)} data-testid="pf-mrp" /></Field>
          <Field label={t("vx.pf.price")} htmlFor="pf-price"><Input id="pf-price" type="number" min="0" step="0.01" inputMode="decimal" value={value.selling_price} onChange={(e) => set("selling_price", e.target.value)} data-testid="pf-price" /></Field>
          <Field label={t("vx.pf.gst")} htmlFor="pf-gst" hint={t("vx.pf.gstHint")}><Input id="pf-gst" type="number" min="0" max="28" step="0.5" value={value.gst_percent} onChange={(e) => set("gst_percent", e.target.value)} /></Field>
          <Field label={t("vx.pf.hsn")} htmlFor="pf-hsn"><Input id="pf-hsn" value={value.hsn_code} onChange={(e) => set("hsn_code", e.target.value)} maxLength={10} className="font-mono" /></Field>
        </div>
        {Number(value.selling_price) > Number(value.mrp) && Number(value.mrp) > 0 && <p role="alert" className="text-xs text-danger" data-testid="pf-price-error">{t("vx.pf.priceError")}</p>}
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={value.returnable} onChange={(e) => set("returnable", e.target.checked)} /> {t("vx.pf.returnable")}</label>
        <Field label={t("vx.pf.returnPolicy")} htmlFor="pf-rp"><Input id="pf-rp" value={value.return_policy} onChange={(e) => set("return_policy", e.target.value)} /></Field>
      </Section>

      <Section title={t("vx.pf.inventory")} testid="pf-inventory">
        <div className="grid gap-3 sm:grid-cols-2">
          {!hasVariants && (
            <Field label={t("vx.pf.stock")} htmlFor="pf-stock" hint={isEdit ? t("vx.pf.stockEditHint") : undefined}>
              <Input id="pf-stock" type="number" min="0" value={value.stock} disabled={isEdit} onChange={(e) => set("stock", e.target.value)} data-testid="pf-stock" />
            </Field>
          )}
          <Field label={t("vx.pf.threshold")} htmlFor="pf-thr" hint={t("vx.pf.thresholdHint")}><Input id="pf-thr" type="number" min="0" value={value.low_stock_threshold} onChange={(e) => set("low_stock_threshold", e.target.value)} /></Field>
        </div>
        <div className="space-y-2" data-testid="pf-variants">
          <div className="flex items-center justify-between"><h4 className="text-sm font-medium text-ink">{t("vx.pf.variants")}</h4>
            <Button type="button" variant="outline" className="h-9 rounded-full" onClick={() => set("variants", [...value.variants, { sku: "", attributes: { size: "" }, price: "", mrp: "", stock: 0, isNew: true }])} data-testid="pf-add-variant"><Plus size={14} /> {t("vx.pf.addVariant")}</Button></div>
          {!hasVariants && <p className="text-xs text-muted2">{t("vx.pf.variantsHint")}</p>}
          {value.variants.map((v, i) => {
            const [ak, av] = Object.entries(v.attributes || {})[0] || ["size", ""];
            return (
              <div key={i} className="grid gap-2 rounded-xl bg-white/5 p-3 sm:grid-cols-6" data-testid={`pf-variant-${i}`}>
                <Field label={t("vx.pf.variantSku")} htmlFor={`pf-v-sku-${i}`} className="sm:col-span-2"><Input id={`pf-v-sku-${i}`} value={v.sku} disabled={!v.isNew} className="font-mono uppercase" onChange={(e) => setVariant(i, { sku: e.target.value })} /></Field>
                <Field label={t("vx.pf.variantAttr")} htmlFor={`pf-v-attr-${i}`}>
                  <select id={`pf-v-attr-${i}`} className={SELECT} value={ak} onChange={(e) => setVariant(i, { attributes: { [e.target.value]: av } })}>
                    {(spec?.variant_attributes || ["size", "colour"]).map((k) => <option key={k} value={k}>{attrLabel(k)}</option>)}
                  </select></Field>
                <Field label={t("vx.pf.variantValue")} htmlFor={`pf-v-val-${i}`}><Input id={`pf-v-val-${i}`} value={av} onChange={(e) => setVariant(i, { attributes: { [ak]: e.target.value } })} /></Field>
                <Field label={t("vx.pf.variantPrice")} htmlFor={`pf-v-price-${i}`}><Input id={`pf-v-price-${i}`} type="number" min="0" step="0.01" value={v.price ?? ""} onChange={(e) => setVariant(i, { price: e.target.value })} /></Field>
                <Field label={t("vx.pf.stock")} htmlFor={`pf-v-stock-${i}`}><Input id={`pf-v-stock-${i}`} type="number" min="0" value={v.stock} disabled={!v.isNew} onChange={(e) => setVariant(i, { stock: e.target.value })} /></Field>
                <div className="flex items-end sm:col-span-6 sm:justify-end">
                  <Button type="button" variant="ghost" className="h-9 text-danger" onClick={() => set("variants", value.variants.filter((_, j) => j !== i))} aria-label={t("vx.remove")}><Trash2 size={14} /> {t("vx.remove")}</Button>
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {attrs.length > 0 && (
        <Section title={t("vx.pf.attributes", { c: t(`vx.pillar.${value.category}`) })} testid="pf-attributes">
          <div className="grid gap-3 sm:grid-cols-2">
            {attrs.map((a) => (
              <Field key={a.key} label={attrLabel(a.key)} htmlFor={`pf-a-${a.key}`} className={a.max > 200 ? "sm:col-span-2" : ""}>
                {a.max > 200 ? <Textarea id={`pf-a-${a.key}`} rows={2} maxLength={a.max} value={value.attributes[a.key] ?? ""} onChange={(e) => set("attributes", { ...value.attributes, [a.key]: e.target.value })} data-testid={`pf-attr-${a.key}`} />
                  : <Input id={`pf-a-${a.key}`} type={a.type === "number" ? "number" : a.type === "date" ? "date" : "text"} value={value.attributes[a.key] ?? ""} maxLength={a.type === "text" ? a.max : undefined}
                      onChange={(e) => set("attributes", { ...value.attributes, [a.key]: a.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value })} data-testid={`pf-attr-${a.key}`} />}
              </Field>
            ))}
          </div>
        </Section>
      )}

      <Section title={t("vx.pf.shipping")} testid="pf-shipping">
        <div className="grid gap-3 sm:grid-cols-3">
          {["weight_g", "length_cm", "width_cm", "height_cm", "handling_days"].map((k) => (
            <Field key={k} label={t(`vx.pf.${k}`)} htmlFor={`pf-p-${k}`}>
              <Input id={`pf-p-${k}`} type="number" min="0" value={value.package[k] ?? ""} onChange={(e) => set("package", { ...value.package, [k]: e.target.value })} data-testid={`pf-pkg-${k}`} />
            </Field>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={!!value.package.fragile} onChange={(e) => set("package", { ...value.package, fragile: e.target.checked })} /> {t("vx.pf.fragile")}</label>
      </Section>

      <Section title={t("vx.pf.compliance")} testid="pf-compliance">
        <Field label={t("vx.pf.declarations")} htmlFor="pf-decl" hint={t("vx.pf.declarationsHint")}><Textarea id="pf-decl" rows={2} value={value.declarations} onChange={(e) => set("declarations", e.target.value)} /></Field>
        {value.compliance_documents.map((d, i) => (
          <div key={i} className="flex flex-wrap items-center gap-2 rounded-xl bg-white/5 p-2 text-sm" data-testid={`pf-doc-${i}`}>
            <Pill tone={d.status === "verified" ? "ok" : d.status === "rejected" ? "bad" : "warn"}>{t(`vx.docstatus.${d.status || "submitted"}`)}</Pill>
            <span className="font-medium text-ink">{t(`vx.doctype.${d.type}`)}</span><span className="min-w-0 flex-1 truncate text-xs text-muted2">{d.url}</span>
            <Button type="button" variant="ghost" className="h-8 text-danger" onClick={() => set("compliance_documents", value.compliance_documents.filter((_, j) => j !== i))} aria-label={t("vx.remove")}><Trash2 size={14} /></Button>
          </div>
        ))}
        <NewDoc spec={spec} onAdd={(d) => set("compliance_documents", [...value.compliance_documents, d])} />
        <p className="text-xs text-muted2">{t("vx.pf.docsHint")}</p>
      </Section>

      <div className="flex items-center justify-between">
        <Button type="button" variant="outline" className="h-10 rounded-full" onClick={() => setPreview((p) => !p)} data-testid="pf-preview-toggle">{preview ? <EyeOff size={15} /> : <Eye size={15} />} {t("vx.pf.preview")}</Button>
      </div>
      {preview && (
        <div className="hg-card max-w-xs overflow-hidden" data-testid="pf-preview">
          <div className="aspect-[4/3] bg-white/5">{value.images[0] && <img src={value.images[0]} alt="" className="h-full w-full object-cover" />}</div>
          <div className="space-y-1 p-3">
            <div className="text-sm font-semibold text-ink">{(lang === "hi" && value.name_hi) || value.name || t("vx.pf.name")}</div>
            <div className="text-xs text-muted2">{value.brand}{value.brand && value.subcategory ? " · " : ""}{value.subcategory}</div>
            <div className="flex items-baseline gap-2"><Money value={Number(value.selling_price) || 0} className="font-semibold text-hg-lavender" />
              {Number(value.mrp) > Number(value.selling_price) && <Money value={Number(value.mrp)} className="text-xs text-muted2 line-through" />}</div>
            {hasVariants && <div className="flex flex-wrap gap-1">{value.variants.map((v, i) => <Pill key={i} tone="muted">{Object.values(v.attributes || {})[0] || v.sku}</Pill>)}</div>}
          </div>
        </div>
      )}
    </div>
  );
}

function NewDoc({ spec, onAdd }) {
  const { t } = useI18n();
  const [d, setD] = useState({ type: "test_report", url: "", note: "" });
  useEffect(() => { if (spec?.document_types && !spec.document_types.includes(d.type)) setD((x) => ({ ...x, type: spec.document_types[0] })); }, [spec]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="grid gap-2 sm:grid-cols-6" data-testid="pf-newdoc">
      <select aria-label={t("vx.pf.docType")} className={`${SELECT} sm:col-span-2`} value={d.type} onChange={(e) => setD({ ...d, type: e.target.value })}>
        {(spec?.document_types || ["test_report", "license", "invoice", "authenticity", "certificate", "other"]).map((k) => <option key={k} value={k}>{t(`vx.doctype.${k}`)}</option>)}
      </select>
      <Input aria-label={t("vx.pf.docUrl")} placeholder="https://…" className="sm:col-span-3" value={d.url} onChange={(e) => setD({ ...d, url: e.target.value })} data-testid="pf-doc-url" />
      <Button type="button" variant="outline" className="h-10 rounded-full" onClick={() => { if (d.url.trim()) { onAdd({ ...d, url: d.url.trim(), status: "submitted" }); setD({ ...d, url: "", note: "" }); } }} data-testid="pf-doc-add"><Plus size={14} /> {t("vx.add")}</Button>
    </div>
  );
}

export function useCatalogueSpec() {
  const [spec, setSpec] = useState(null);
  useEffect(() => { API.get("/vendor/catalogue/spec").then(({ data }) => setSpec(data)).catch(() => setSpec(null)); }, []);
  return spec;
}
