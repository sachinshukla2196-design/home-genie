import React, { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, Circle, Layers, Loader2, Plus, Send, Trash2, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { API, apiError } from "@/lib/api";
import { Field, Pill, inrV } from "@/components/vendor/kit";
import { ImageInput } from "@/components/vendor/ImageInput";

/**
 * Product studio (Batch 12, Phase 4): one guided, sectioned editor for vendors and for admins adding a product on a vendor's
 * behalf. It edits a server-side DRAFT (autosaved, versioned) and shows the server's own completeness check per section;
 * nothing reaches the live catalogue until the draft is submitted and reviewed. `base` is "/vendor/pim" or "/admin/pim".
 */

const SELECT = "h-10 w-full rounded-lg bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet";
const DOC_TYPES = ["license", "test_report", "invoice", "authenticity", "certificate", "other"];
const numOrEmpty = (v) => (v === "" || v === null || v === undefined ? "" : Number(v));
const intOrEmpty = (v) => (v === "" || v === null || v === undefined ? "" : parseInt(v, 10));

const STATUS_ICON = {
  complete: <CheckCircle2 size={16} className="text-hg-success" aria-label="complete" />,
  check: <AlertTriangle size={16} className="text-hg-gold" aria-label="needs a look" />,
  incomplete: <Circle size={16} className="text-muted2" aria-label="incomplete" />,
};

export function ProductStudio({ base, draftId, onDone, header }) {
  const [tpl, setTpl] = useState(null);
  const [draft, setDraft] = useState(null);
  const [data, setData] = useState(null);
  const [step, setStep] = useState("basics");
  const [saveState, setSaveState] = useState("saved");   // saved | dirty | saving | conflict | error
  const [submitting, setSubmitting] = useState(false);
  const version = useRef(0);
  const timer = useRef(null);
  const pending = useRef(null);

  useEffect(() => {
    API.get("/pim/template").then(({ data: d }) => setTpl(d)).catch((e) => toast.error(apiError(e)));
    API.get(`${base}/drafts/${draftId}`).then(({ data: d }) => { setDraft(d); setData(d.data || {}); version.current = d.version; })
      .catch((e) => toast.error(apiError(e)));
  }, [base, draftId]);

  const flush = useCallback(async () => {
    if (!pending.current) return;
    const body = pending.current;
    pending.current = null;
    setSaveState("saving");
    try {
      const { data: d } = await API.put(`${base}/drafts/${draftId}`, { data: body, version: version.current });
      version.current = d.version;
      setDraft(d);
      setSaveState(pending.current ? "dirty" : "saved");
    } catch (e) {
      if (e?.response?.status === 409) setSaveState("conflict");
      else { setSaveState("error"); toast.error(apiError(e)); pending.current = pending.current || body; }
    }
  }, [base, draftId]);

  const update = useCallback((patch) => {
    setData((cur) => {
      const next = { ...cur, ...patch };
      pending.current = next;
      return next;
    });
    setSaveState("dirty");
    clearTimeout(timer.current);
    timer.current = setTimeout(flush, 1200);
  }, [flush]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const submit = async () => {
    clearTimeout(timer.current);
    await flush();
    setSubmitting(true);
    try {
      const { data: r } = await API.post(`${base}/drafts/${draftId}/submit`);
      toast.success(r.result === "revision_pending" ? "Changes sent for review. The product stays on sale as it is until they are approved."
        : r.result === "created" ? "Product submitted for review." : "Product updated and sent for review.");
      onDone && onDone(r);
    } catch (e) {
      const d = e?.response?.data?.detail;
      if (d && d.check) { setDraft((x) => ({ ...x, check: d.check })); toast.error(d.message); }
      else toast.error(apiError(e));
    } finally { setSubmitting(false); }
  };

  if (!tpl || !draft || !data) return <div className="flex items-center gap-2 p-8 text-muted2"><Loader2 className="animate-spin" size={18} /> Loading product…</div>;
  if (draft.status !== "draft") return <div className="hg-tile p-6 text-sm">This draft was already submitted.</div>;

  const check = draft.check || { sections: {}, blocking: 0, ok: false };
  const sections = tpl.sections;
  const idx = sections.findIndex((s) => s.id === step);
  const ctx = { data, update, tpl, isEdit: !!draft.product_id, check, admin: base === "/admin/pim" };   // admin: platform uploads (B-009)

  return (
    <div className="space-y-4" data-testid="product-studio">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          {header}
          <h1 className="truncate font-display text-xl font-semibold text-ink sm:text-2xl">{data.name || "New product"}</h1>
          <p className="text-xs text-muted2">{draft.product_id ? "Changing an existing product" : "New product"} · <SaveState s={saveState} /></p>
        </div>
        <Button onClick={submit} disabled={submitting || !check.ok || saveState === "conflict"} className="hg-btn h-11 rounded-full px-5" data-testid="studio-submit">
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />} Submit for review
        </Button>
      </div>
      {saveState === "conflict" && (
        <div className="hg-tile flex flex-wrap items-center justify-between gap-2 p-3 text-sm text-danger" role="alert">
          This draft was changed in another tab or by a colleague. <Button variant="outline" size="sm" onClick={() => window.location.reload()}>Reload</Button>
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[230px_1fr]">
        <nav aria-label="Product sections" className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 lg:mx-0 lg:block lg:space-y-1 lg:overflow-visible lg:px-0">
          {sections.map((s, i) => {
            const st = s.id === "review" ? (check.ok ? "complete" : "incomplete") : check.sections?.[s.id]?.status || "incomplete";
            return (
              <button key={s.id} onClick={() => setStep(s.id)} aria-current={step === s.id ? "step" : undefined} data-testid={`studio-step-${s.id}`}
                className={`flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-left text-sm lg:w-full ${step === s.id ? "bg-brand-50 font-semibold text-ink" : "text-muted2 hover:bg-brand-50/60"}`}>
                {STATUS_ICON[st]} <span className="whitespace-nowrap">{i + 1}. {s.label}</span>
              </button>
            );
          })}
        </nav>
        <div className="hg-tile min-w-0 space-y-4 p-4 sm:p-5">
          <SectionProblems sec={check.sections?.[step]} />
          {step === "basics" && <Basics {...ctx} />}
          {step === "media" && <Media {...ctx} />}
          {step === "pricing" && <Pricing {...ctx} />}
          {step === "variants" && <Variants {...ctx} />}
          {step === "details" && <Details {...ctx} />}
          {step === "shipping" && <Shipping {...ctx} />}
          {step === "compliance" && <Compliance {...ctx} />}
          {step === "review" && <Review {...ctx} sections={sections} go={setStep} />}
          <div className="flex justify-between gap-2 border-t border-brand-50 pt-4">
            <Button variant="outline" disabled={idx <= 0} onClick={() => setStep(sections[idx - 1].id)} className="rounded-full"><ArrowLeft size={15} /> Back</Button>
            {idx < sections.length - 1 && <Button onClick={() => setStep(sections[idx + 1].id)} className="hg-btn rounded-full">Next <ArrowRight size={15} /></Button>}
          </div>
        </div>
      </div>
    </div>
  );
}

function SaveState({ s }) {
  const t = { saved: "All changes saved", dirty: "Unsaved changes", saving: "Saving…", conflict: "Not saved: changed elsewhere", error: "Not saved: will retry" }[s];
  return <span data-testid="studio-save-state" className={s === "conflict" || s === "error" ? "text-danger" : ""}>{t}</span>;
}

function SectionProblems({ sec }) {
  if (!sec || (!sec.problems.length && !sec.warnings.length)) return null;
  return (
    <div className="space-y-1.5 text-sm" data-testid="studio-problems">
      {sec.problems.map((p) => <p key={p} className="flex items-start gap-2 text-danger"><Circle size={14} className="mt-0.5 shrink-0" /> {p}</p>)}
      {sec.warnings.map((p) => <p key={p} className="flex items-start gap-2 text-hg-gold"><AlertTriangle size={14} className="mt-0.5 shrink-0" /> {p}</p>)}
    </div>
  );
}

/* ------------------------------------------------------------------ sections */
function Basics({ data, update, tpl }) {
  const t = tpl.templates[data.category];
  const highlights = data.highlights || [];
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Field label="Product title" htmlFor="ps-name" hint="What a shopper would search for, e.g. Banarasi silk saree with zari border" className="sm:col-span-2">
        <Input id="ps-name" value={data.name || ""} maxLength={140} onChange={(e) => update({ name: e.target.value })} data-testid="ps-name" />
      </Field>
      <Field label="Category" htmlFor="ps-category">
        <select id="ps-category" className={SELECT} value={data.category || ""} data-testid="ps-category"
          onChange={(e) => update({ category: e.target.value, subcategory: "", attributes: {} })}>
          <option value="">Choose…</option>
          {Object.keys(tpl.templates).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </Field>
      <Field label="Sub-category" htmlFor="ps-sub">
        <select id="ps-sub" className={SELECT} value={data.subcategory || ""} disabled={!t} onChange={(e) => update({ subcategory: e.target.value })} data-testid="ps-subcategory">
          <option value="">Choose…</option>
          {(t?.subcategories || []).map((c) => <option key={c} value={c}>{c}</option>)}
          {data.subcategory && t && !t.subcategories.includes(data.subcategory) && <option value={data.subcategory}>{data.subcategory}</option>}
        </select>
      </Field>
      <Field label="Brand" htmlFor="ps-brand" hint="Leave blank for unbranded products">
        <Input id="ps-brand" value={data.brand || ""} maxLength={60} onChange={(e) => update({ brand: e.target.value })} />
      </Field>
      <Field label="Model / product code" htmlFor="ps-model">
        <Input id="ps-model" value={data.model_number || ""} maxLength={60} onChange={(e) => update({ model_number: e.target.value })} />
      </Field>
      <Field label="Short description" htmlFor="ps-short" hint="One or two lines shown under the title (up to 200 characters)" className="sm:col-span-2">
        <Input id="ps-short" value={data.short_description || ""} maxLength={200} onChange={(e) => update({ short_description: e.target.value })} data-testid="ps-short" />
      </Field>
      <Field label="Full description" htmlFor="ps-desc" className="sm:col-span-2">
        <Textarea id="ps-desc" rows={6} value={data.description || ""} maxLength={5000} onChange={(e) => update({ description: e.target.value })} data-testid="ps-description" />
      </Field>
      <div className="sm:col-span-2">
        <div className="text-sm font-medium text-ink">Highlights <span className="font-normal text-muted2">(up to {tpl.max_highlights} short points)</span></div>
        <div className="mt-1.5 space-y-2">
          {highlights.map((h, i) => (
            <div key={i} className="flex gap-2">
              <Input aria-label={`Highlight ${i + 1}`} value={h} maxLength={120} onChange={(e) => update({ highlights: highlights.map((x, j) => (j === i ? e.target.value : x)) })} />
              <Button variant="outline" size="icon" aria-label="Remove highlight" onClick={() => update({ highlights: highlights.filter((_, j) => j !== i) })}><Trash2 size={15} /></Button>
            </div>
          ))}
          {highlights.length < tpl.max_highlights && <Button variant="outline" size="sm" onClick={() => update({ highlights: [...highlights, ""] })}><Plus size={14} /> Add highlight</Button>}
        </div>
      </div>
      <Field label="Search keywords" htmlFor="ps-kw" hint="Comma separated, up to 10 (e.g. wedding saree, zari)" className="sm:col-span-2">
        <Input id="ps-kw" value={(data.keywords || []).join(", ")} onChange={(e) => update({ keywords: e.target.value.split(",").map((x) => x.trimStart()).slice(0, 10) })} />
      </Field>
      <details className="sm:col-span-2">
        <summary className="cursor-pointer text-sm font-medium text-ink">Hindi title and description (optional)</summary>
        <div className="mt-3 grid gap-3">
          <Input aria-label="Hindi title" value={data.name_hi || ""} maxLength={140} onChange={(e) => update({ name_hi: e.target.value })} />
          <Textarea aria-label="Hindi description" rows={4} value={data.description_hi || ""} onChange={(e) => update({ description_hi: e.target.value })} />
        </div>
      </details>
    </div>
  );
}

function Media({ data, update, tpl, admin }) {
  const imgs = data.images || [];
  const alt = data.image_alt || {};
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted2">The first image is the main image. JPG, PNG or WebP up to 5 MB each; use clear photos on a plain background.</p>
      <ImageInput admin={admin} value={imgs} max={tpl.max_images} onChange={(v) => update({ images: v, image_alt: Object.fromEntries(v.map((u) => [u, alt[u] || ""])) })} testid="ps-images" />
      {imgs.length > 0 && (
        <div className="space-y-2">
          <div className="text-sm font-medium text-ink">Describe each image</div>
          {imgs.map((u, i) => (
            <div key={u} className="flex items-center gap-3">
              <img src={u} alt="" className="h-12 w-12 shrink-0 rounded-lg object-cover ring-1 ring-white/15" />
              <Input aria-label={`Description of image ${i + 1}`} placeholder={i === 0 ? "Main image, e.g. Red silk saree, front view" : "e.g. Close-up of the border"}
                value={alt[u] || ""} maxLength={125} onChange={(e) => update({ image_alt: { ...alt, [u]: e.target.value } })} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function Pricing({ data, update }) {
  const mrp = Number(data.mrp) || 0;
  const price = Number(data.selling_price) || 0;
  const gst = Number(data.gst_percent) || 0;
  const taxable = price ? (price * 100) / (100 + gst) : 0;
  const off = mrp && price && price <= mrp ? Math.round(((mrp - price) / mrp) * 100) : 0;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="MRP (₹)" htmlFor="ps-mrp"><Input id="ps-mrp" type="number" min="0" step="0.01" inputMode="decimal" value={data.mrp ?? ""} onChange={(e) => update({ mrp: numOrEmpty(e.target.value) })} data-testid="ps-mrp" /></Field>
        <Field label="Selling price (₹, GST included)" htmlFor="ps-price" error={price > mrp && mrp ? "Cannot be higher than the MRP" : null}>
          <Input id="ps-price" type="number" min="0" step="0.01" inputMode="decimal" value={data.selling_price ?? ""} onChange={(e) => update({ selling_price: numOrEmpty(e.target.value) })} data-testid="ps-price" />
        </Field>
        <Field label="GST rate (%)" htmlFor="ps-gst" hint="The rate that applies to this product. Ask your tax adviser if unsure.">
          <Input id="ps-gst" type="number" min="0" max="28" step="0.01" inputMode="decimal" value={data.gst_percent ?? ""} onChange={(e) => update({ gst_percent: numOrEmpty(e.target.value) })} data-testid="ps-gst" />
        </Field>
        <Field label="HSN code" htmlFor="ps-hsn" hint="As used on your GST invoices">
          <Input id="ps-hsn" value={data.hsn_code || ""} maxLength={10} inputMode="numeric" onChange={(e) => update({ hsn_code: e.target.value.replace(/[^0-9]/g, "") })} />
        </Field>
      </div>
      {price > 0 && (
        <div className="hg-tile grid grid-cols-2 gap-2 p-3 text-sm sm:grid-cols-4" data-testid="ps-price-preview">
          <div><div className="text-xs text-muted2">Customer pays</div><div className="font-semibold">{inrV(price)}</div></div>
          <div><div className="text-xs text-muted2">Taxable value</div><div className="font-semibold">{inrV(taxable)}</div></div>
          <div><div className="text-xs text-muted2">GST included</div><div className="font-semibold">{inrV(price - taxable)}</div></div>
          <div><div className="text-xs text-muted2">Discount on MRP</div><div className="font-semibold">{off}%</div></div>
        </div>
      )}
      <p className="text-xs text-muted2">Prices are GST-inclusive. The invoice shows the taxable value and the GST contained in the price.</p>
    </div>
  );
}

function variantKeys(tpl, category) {
  const t = tpl.templates[category];
  return t ? t.groups.flatMap((g) => g.fields).filter((f) => f.variant) : [];
}

function Variants({ data, update, tpl, isEdit }) {
  const variants = data.variants || [];
  const keys = variantKeys(tpl, data.category);
  const [dim, setDim] = useState(keys[0]?.key || "");
  const [values, setValues] = useState("");
  const useVariants = variants.length > 0;
  const setRow = (i, patch) => update({ variants: variants.map((v, j) => (j === i ? { ...v, ...patch } : v)) });
  const generate = () => {
    const vals = values.split(",").map((x) => x.trim()).filter(Boolean);
    if (!dim || !vals.length) return;
    const base = (data.sku || "SKU").toUpperCase();
    const rows = vals.map((v) => ({ sku: `${base}-${v.toUpperCase().replace(/[^A-Z0-9]+/g, "")}`.slice(0, 40), attributes: { [dim]: v }, stock: 0, isNew: true }));
    update({ variants: [...variants, ...rows.filter((r) => !variants.some((x) => x.sku === r.sku))] });
    setValues("");
  };
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Product SKU" htmlFor="ps-sku" hint={isEdit ? "The SKU cannot change once created" : "Your own code, 2-40 letters, numbers, . _ -"}>
          <Input id="ps-sku" value={data.sku || ""} disabled={isEdit} maxLength={40} onChange={(e) => update({ sku: e.target.value.toUpperCase() })} data-testid="ps-sku" />
        </Field>
        <Field label="Low-stock alert at" htmlFor="ps-low"><Input id="ps-low" type="number" min="0" value={data.low_stock_threshold ?? 5} onChange={(e) => update({ low_stock_threshold: intOrEmpty(e.target.value) })} /></Field>
      </div>
      {!useVariants && (
        <Field label={isEdit ? "Current stock" : "Opening stock"} htmlFor="ps-stock" hint={isEdit ? "Change stock from Inventory, with a reason (every change is recorded)." : "How many you have ready to sell now"}>
          <Input id="ps-stock" type="number" min="0" disabled={isEdit} value={data.stock ?? 0} onChange={(e) => update({ stock: intOrEmpty(e.target.value) })} data-testid="ps-stock" />
        </Field>
      )}
      <div className="hg-tile space-y-3 p-3">
        <div className="flex items-center gap-2 text-sm font-medium text-ink"><Layers size={16} /> Options (variants)</div>
        <p className="text-xs text-muted2">Use variants only when the same product is sold in several sizes, colours, shades or pack sizes. Each variant has its own SKU, stock and optional price.</p>
        {keys.length > 0 && (
          <div className="flex flex-wrap items-end gap-2">
            <select aria-label="Option type" className={`${SELECT} max-w-[180px]`} value={dim} onChange={(e) => setDim(e.target.value)}>
              {keys.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
            </select>
            <Input aria-label="Option values" className="min-w-[180px] flex-1" placeholder="Values, comma separated: S, M, L" value={values} onChange={(e) => setValues(e.target.value)} />
            <Button variant="outline" onClick={generate} data-testid="ps-generate-variants"><Wand2 size={15} /> Add variants</Button>
          </div>
        )}
        {variants.map((v, i) => (
          <div key={i} className="grid gap-2 rounded-xl p-2 ring-1 ring-brand-100 dark:ring-white/10 sm:grid-cols-[1.3fr_1fr_0.8fr_0.8fr_0.7fr_auto]" data-testid="ps-variant-row">
            <Input aria-label="Variant SKU" value={v.sku} disabled={!v.isNew && isEdit} onChange={(e) => setRow(i, { sku: e.target.value.toUpperCase() })} />
            <Input aria-label="Variant option" value={Object.entries(v.attributes || {}).map(([k, x]) => `${x}`).join(" / ")} disabled title={Object.keys(v.attributes || {}).join(", ")} />
            <Input aria-label="Variant price" type="number" min="0" step="0.01" placeholder="Price" value={v.price ?? ""} onChange={(e) => setRow(i, { price: numOrEmpty(e.target.value) || undefined })} />
            <Input aria-label="Variant MRP" type="number" min="0" step="0.01" placeholder="MRP" value={v.mrp ?? ""} onChange={(e) => setRow(i, { mrp: numOrEmpty(e.target.value) || undefined })} />
            <Input aria-label="Variant stock" type="number" min="0" placeholder="Stock" disabled={!v.isNew} value={v.stock ?? 0} onChange={(e) => setRow(i, { stock: intOrEmpty(e.target.value) })} />
            <Button variant="outline" size="icon" aria-label="Remove variant" disabled={!v.isNew && (v.stock || 0) > 0} onClick={() => update({ variants: variants.filter((_, j) => j !== i) })}><Trash2 size={15} /></Button>
          </div>
        ))}
        {useVariants && <p className="text-xs text-muted2">A variant that still has stock cannot be removed; bring its stock to 0 from Inventory first.</p>}
      </div>
    </div>
  );
}

function AttrInput({ f, value, onChange }) {
  const id = `ps-attr-${f.key}`;
  if (f.type === "textarea") return <Textarea id={id} rows={3} maxLength={f.max} value={value || ""} onChange={(e) => onChange(e.target.value)} />;
  if (f.type === "number") return <Input id={id} type="number" min="0" max={f.max} step="any" value={value ?? ""} onChange={(e) => onChange(numOrEmpty(e.target.value))} />;
  if (f.type === "date") return <Input id={id} type="date" value={value || ""} onChange={(e) => onChange(e.target.value)} />;
  if (f.type === "select") return (
    <select id={id} className={SELECT} value={value || ""} onChange={(e) => onChange(e.target.value)}>
      <option value="">Choose…</option>{f.options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>);
  if (f.type === "multi") {
    const cur = Array.isArray(value) ? value : [];
    return (
      <div className="flex flex-wrap gap-2" id={id}>
        {f.options.map((o) => {
          const on = cur.includes(o);
          return <button type="button" key={o} aria-pressed={on} onClick={() => onChange(on ? cur.filter((x) => x !== o) : [...cur, o])}
            className={`rounded-full px-3 py-1 text-xs ring-1 ${on ? "bg-hg-violet/20 font-semibold text-ink ring-hg-lavender/40" : "text-muted2 ring-brand-100 dark:ring-white/15"}`}>{on && <Check size={12} className="mr-1 inline" />}{o}</button>;
        })}
      </div>);
  }
  if (f.type === "bool") return (
    <select id={id} className={SELECT} value={value === true ? "yes" : value === false ? "no" : ""} onChange={(e) => onChange(e.target.value === "" ? "" : e.target.value === "yes")}>
      <option value="">Choose…</option><option value="yes">Yes</option><option value="no">No</option>
    </select>);
  return <Input id={id} maxLength={f.max} value={value || ""} onChange={(e) => onChange(e.target.value)} />;
}

function Details({ data, update, tpl }) {
  const t = tpl.templates[data.category];
  if (!t) return <p className="text-sm text-muted2">Choose a category in Basic information first.</p>;
  const attrs = data.attributes || {};
  const req = (f) => f.required === true || (Array.isArray(f.required) && f.required.includes(data.subcategory));
  return (
    <div className="space-y-5">
      {t.groups.map((g) => (
        <fieldset key={g.id} className="space-y-3">
          <legend className="text-sm font-semibold text-ink">{g.label}</legend>
          <div className="grid gap-3 sm:grid-cols-2">
            {g.fields.map((f) => (
              <Field key={f.key} htmlFor={`ps-attr-${f.key}`} label={<>{f.label}{f.unit ? ` (${f.unit})` : ""}{req(f) ? <span className="text-danger"> *</span> : <span className="font-normal text-muted2"> (optional)</span>}</>}
                hint={f.help} className={f.type === "textarea" || f.type === "multi" ? "sm:col-span-2" : ""}>
                <AttrInput f={f} value={attrs[f.key]} onChange={(v) => update({ attributes: { ...attrs, [f.key]: v } })} />
              </Field>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}

function Shipping({ data, update, tpl }) {
  const pkg = data.package || {};
  const setPkg = (patch) => update({ package: { ...pkg, ...patch } });
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Packed weight (g)" htmlFor="ps-w"><Input id="ps-w" type="number" min="1" value={pkg.weight_g ?? ""} onChange={(e) => setPkg({ weight_g: numOrEmpty(e.target.value) })} data-testid="ps-weight" /></Field>
        <Field label="Dispatch time (days)" htmlFor="ps-h" hint="Days to hand an order to the courier"><Input id="ps-h" type="number" min="0" max="30" value={pkg.handling_days ?? ""} onChange={(e) => setPkg({ handling_days: intOrEmpty(e.target.value) })} data-testid="ps-handling" /></Field>
        <Field label="Fragile" htmlFor="ps-f">
          <select id="ps-f" className={SELECT} value={pkg.fragile ? "yes" : "no"} onChange={(e) => setPkg({ fragile: e.target.value === "yes" })}><option value="no">No</option><option value="yes">Yes, handle with care</option></select>
        </Field>
        {[["length_cm", "Length (cm)"], ["width_cm", "Width (cm)"], ["height_cm", "Height (cm)"]].map(([k, l]) => (
          <Field key={k} label={`Package ${l.toLowerCase()}`} htmlFor={`ps-${k}`}><Input id={`ps-${k}`} type="number" min="1" value={pkg[k] ?? ""} onChange={(e) => setPkg({ [k]: numOrEmpty(e.target.value) })} /></Field>
        ))}
      </div>
      <div className="hg-tile space-y-3 p-3">
        <div className="text-sm font-medium text-ink">Returns</div>
        <p className="text-xs text-muted2">Customers can return eligible products within {tpl.returns_policy?.window_days ?? "the"} days of delivery under the HOME GENIES return policy. {tpl.returns_policy?.note}</p>
        <Field label="Can this product be returned?" htmlFor="ps-ret">
          <select id="ps-ret" className={SELECT} value={data.returnable === false ? "no" : "yes"} onChange={(e) => update({ returnable: e.target.value === "yes" })}>
            <option value="yes">Yes, under the platform return policy</option><option value="no">No (needs a reason, reviewed by HOME GENIES)</option>
          </select>
        </Field>
        <Field label={data.returnable === false ? "Why it cannot be returned" : "Return or warranty notes (optional)"} htmlFor="ps-rp">
          <Textarea id="ps-rp" rows={2} maxLength={300} value={data.return_policy || ""} onChange={(e) => update({ return_policy: e.target.value })} />
        </Field>
      </div>
    </div>
  );
}

function Compliance({ data, update, admin }) {
  const docs = data.compliance_documents || [];
  const setDoc = (i, patch) => update({ compliance_documents: docs.map((d, j) => (j === i ? { ...d, ...patch } : d)) });
  const decl = (data.declarations || []).join("\n");
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted2">Add supporting documents where they apply: licences, test reports, brand authorisation or purchase invoices. HOME GENIES checks them during review.</p>
      {docs.map((d, i) => (
        <div key={i} className="hg-tile space-y-2 p-3">
          <div className="flex gap-2">
            <select aria-label="Document type" className={SELECT} value={d.type} onChange={(e) => setDoc(i, { type: e.target.value })}>
              {DOC_TYPES.map((x) => <option key={x} value={x}>{x.replace(/_/g, " ")}</option>)}
            </select>
            <Button variant="outline" size="icon" aria-label="Remove document" onClick={() => update({ compliance_documents: docs.filter((_, j) => j !== i) })}><Trash2 size={15} /></Button>
          </div>
          <ImageInput admin={admin} value={d.url ? [d.url] : []} max={1} onChange={(v) => setDoc(i, { url: v[0] || "" })} testid={`ps-doc-${i}`} />
          <Input aria-label="Document note" placeholder="Note, e.g. licence number or validity" maxLength={200} value={d.note || ""} onChange={(e) => setDoc(i, { note: e.target.value })} />
        </div>
      ))}
      {docs.length < 10 && <Button variant="outline" size="sm" onClick={() => update({ compliance_documents: [...docs, { type: "certificate", url: "", note: "" }] })}><Plus size={14} /> Add document</Button>}
      <Field label="Declarations (one per line)" htmlFor="ps-decl" hint="e.g. This product is genuine and sourced from the brand">
        <Textarea id="ps-decl" rows={3} value={decl} onChange={(e) => update({ declarations: e.target.value.split("\n").slice(0, 10) })} />
      </Field>
    </div>
  );
}

function Review({ data, check, sections, go }) {
  return (
    <div className="space-y-4" data-testid="studio-review">
      {check.ok
        ? <p className="flex items-center gap-2 text-sm text-hg-success"><CheckCircle2 size={17} /> Everything required is filled in. Submit when ready.</p>
        : <p className="flex items-center gap-2 text-sm text-danger"><AlertTriangle size={17} /> {check.blocking} item(s) still need attention before you can submit.</p>}
      <div className="space-y-2">
        {sections.filter((s) => s.id !== "review").map((s) => {
          const sec = check.sections?.[s.id];
          if (!sec || (!sec.problems.length && !sec.warnings.length)) return null;
          return (
            <button key={s.id} onClick={() => go(s.id)} className="hg-tile block w-full p-3 text-left text-sm hover:bg-brand-50/60">
              <div className="flex items-center gap-2 font-medium text-ink">{STATUS_ICON[sec.status]} {s.label}</div>
              {[...sec.problems, ...sec.warnings].map((p) => <div key={p} className="mt-1 text-xs text-muted2">{p}</div>)}
            </button>
          );
        })}
      </div>
      <div className="hg-tile flex gap-4 p-3" data-testid="studio-preview">
        {data.images?.[0] ? <img src={data.images[0]} alt={(data.image_alt || {})[data.images[0]] || data.name} className="h-28 w-28 shrink-0 rounded-xl object-cover" />
          : <div className="h-28 w-28 shrink-0 rounded-xl bg-brand-50" />}
        <div className="min-w-0 text-sm">
          <div className="font-semibold text-ink">{data.name || "Untitled product"}</div>
          <div className="text-xs text-muted2">{[data.brand, data.category, data.subcategory].filter(Boolean).join(" · ")}</div>
          <div className="mt-1 font-display text-lg font-semibold">{data.selling_price ? inrV(data.selling_price) : "—"}
            {data.mrp > data.selling_price && <span className="ml-2 text-xs text-muted2 line-through">{inrV(data.mrp)}</span>}</div>
          <ul className="mt-1 list-disc pl-4 text-xs text-muted2">{(data.highlights || []).filter(Boolean).map((h) => <li key={h}>{h}</li>)}</ul>
          {(data.variants || []).length > 0 && <Pill tone="violet" className="mt-2">{data.variants.length} variants</Pill>}
        </div>
      </div>
    </div>
  );
}
