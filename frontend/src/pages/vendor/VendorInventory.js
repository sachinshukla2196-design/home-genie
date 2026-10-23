import React, { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Boxes, History, SlidersHorizontal, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { Pager, SearchBox, useDebounced } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Field, Pill, StateBlock, fmtDateTime, useAction, usePaged } from "@/components/vendor/kit";
import { ImportDialog } from "@/components/vendor/ImportDialog";

const TABS = [["all", "vx.inv.all"], ["low", "vp.p.f.low"], ["out", "vp.p.f.out"]];

function stockTone(stock, thr) { return stock <= 0 ? ["bad", "vx.inv.out"] : stock <= thr ? ["warn", "vx.inv.low"] : ["ok", "vx.inv.ok"]; }

export default function VendorInventory() {
  const { t, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const stock = sp.get("stock") || "all";
  const [q, setQ] = useState(sp.get("q") || "");
  const dq = useDebounced(q.trim());
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/products", { q: dq || undefined, stock: stock === "all" ? undefined : stock, sort: "stock", order: "asc" }, 15);
  const [adjust, setAdjust] = useState(null);   // { p, variant }
  const [history, setHistory] = useState(null); // { p, rows }
  const [importing, setImporting] = useState(false);
  const [form, setForm] = useState({ delta: "", reason: "", variant_sku: "" });
  const [run, busy] = useAction();
  const counts = data?.counts;

  const open = (p, v) => { setAdjust({ p, v }); setForm({ delta: "", reason: "", variant_sku: v ? v.sku : "" }); };
  const submit = () => run(async () => {
    const body = { delta: parseInt(form.delta, 10), reason: form.reason.trim(), ...(adjust.v ? { variant_sku: adjust.v.sku } : {}) };
    await API.post(`/vendor/products/${adjust.p.id}/stock`, body);
    setAdjust(null); reload();
  }, { success: t("vx.inv.saved") });
  const showHistory = async (p) => {
    try { const { data: rows } = await API.get(`/vendor/products/${p.id}/stock-history`); setHistory({ p, rows }); } catch (e) { setHistory({ p, rows: [], error: apiError(e) }); }
  };
  const valid = Number.isInteger(parseInt(form.delta, 10)) && parseInt(form.delta, 10) !== 0 && form.reason.trim().length >= 3;

  const row = (p, v) => {
    const s = v ? v.stock : p.stock;
    const [tone, label] = stockTone(s, p.low_stock_threshold ?? 5);
    return (
      <li key={`${p.id}-${v ? v.sku : ""}`} className={`flex flex-wrap items-center gap-3 p-3 ${v ? "ml-4 border-l-2 border-hg-violet/30" : "hg-tile"}`} data-testid={`inv-${v ? v.sku : p.sku}`}>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">{v ? Object.values(v.attributes || {}).join(" / ") : p.name}</div>
          <div className="font-mono text-xs text-muted2">{v ? v.sku : p.sku}{!v && p.variants?.length ? ` · ${t("vx.prod.nVariants", { n: p.variants.length })}` : ""}</div>
        </div>
        {!(p.variants?.length && !v) && <>
          <div className="text-right"><div className="font-display text-xl font-semibold tabular-nums text-ink" data-testid={`inv-stock-${v ? v.sku : p.sku}`}>{s}</div><div className="text-[11px] text-muted2">{t("vx.inv.threshold", { n: p.low_stock_threshold ?? 5 })}</div></div>
          <Pill tone={tone}>{t(label)}</Pill>
          <Button variant="outline" className="h-9 rounded-full" onClick={() => open(p, v)} data-testid={`inv-adjust-${v ? v.sku : p.sku}`}><SlidersHorizontal size={14} /> {t("vx.inv.adjust")}</Button>
        </>}
        {!v && <Button variant="ghost" className="h-9 rounded-full" onClick={() => showHistory(p)} data-testid={`inv-history-${p.sku}`}><History size={14} /> {t("vp.history")}</Button>}
        {p.variants?.length > 0 && !v && <div className="w-full text-xs text-muted2">{t("vx.inv.total", { n: p.stock })}</div>}
      </li>
    );
  };

  return (
    <div className="space-y-5">
      <PageHeader title={t("vx.nav.inventory")} subtitle={t("vx.inv.sub")} icon={Boxes}
        actions={<Button variant="outline" className="h-11 rounded-full" onClick={() => setImporting(true)} data-testid="inv-import"><Upload size={15} /> {t("vx.inv.importStock")}</Button>} />
      <div className="flex flex-wrap items-center gap-2">
        <SearchBox value={q} onChange={setQ} placeholder={t("vp.searchProducts")} testid="inv-search" />
        <div className="flex gap-2" role="tablist">
          {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={stock === k} onClick={() => { const n = new URLSearchParams(sp); k === "all" ? n.delete("stock") : n.set("stock", k); setSp(n, { replace: true }); }} data-testid={`inv-tab-${k}`}
            className={`rounded-full px-4 py-2 text-sm font-medium ${stock === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(l)}{counts ? ` · ${counts[k === "all" ? "all" : k]}` : ""}</button>)}
        </div>
      </div>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="inv" empty={items && items.length === 0} emptyIcon={Boxes} emptyTitle={t("vx.inv.empty")}>
        <ul className="space-y-2">{(items || []).flatMap((p) => [row(p, null), ...(p.variants || []).map((v) => row(p, v))])}</ul>
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="inv-pager" />}

      <Dialog open={!!adjust} onOpenChange={(o) => !o && !busy && setAdjust(null)}>
        <DialogContent className="max-w-md rounded-3xl" data-testid="inv-dialog">
          <DialogHeader><DialogTitle>{t("vx.inv.adjust")}</DialogTitle><DialogDescription>{adjust?.p.name}{adjust?.v ? ` · ${adjust.v.sku}` : ""} — {t("vx.inv.current", { n: adjust?.v ? adjust.v.stock : adjust?.p.stock })}</DialogDescription></DialogHeader>
          <Field label={t("vx.inv.delta")} htmlFor="inv-delta" hint={t("vx.inv.deltaHint")}><Input id="inv-delta" type="number" inputMode="numeric" value={form.delta} onChange={(e) => setForm({ ...form, delta: e.target.value })} data-testid="inv-delta" /></Field>
          <Field label={t("vx.inv.reason")} htmlFor="inv-reason" hint={t("vx.inv.reasonHint")}><Input id="inv-reason" value={form.reason} maxLength={120} onChange={(e) => setForm({ ...form, reason: e.target.value })} data-testid="inv-reason" /></Field>
          <div className="flex justify-end gap-2"><Button variant="outline" className="h-10 rounded-full" onClick={() => setAdjust(null)} disabled={busy}>{t("vx.cancel")}</Button>
            <Button className="hg-btn h-10 rounded-full" disabled={busy || !valid} onClick={submit} data-testid="inv-save">{t("vx.save")}</Button></div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!history} onOpenChange={(o) => !o && setHistory(null)}>
        <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="inv-history-dialog">
          <DialogHeader><DialogTitle>{t("vp.history")}</DialogTitle><DialogDescription>{history?.p.name}</DialogDescription></DialogHeader>
          {history?.error && <p role="alert" className="text-sm text-danger">{history.error}</p>}
          {history && history.rows.length === 0 && !history.error && <p className="text-sm text-muted2">{t("vx.inv.noHistory")}</p>}
          <ul className="space-y-1.5">{history?.rows.map((h) => (
            <li key={h.id} className="hg-tile flex items-center justify-between gap-3 p-2.5 text-xs">
              <span className="min-w-0"><span className="block truncate text-ink">{h.reason}{h.variant_sku ? ` · ${h.variant_sku}` : ""}</span><span className="text-muted2">{fmtDateTime(h.created_at, lang)}</span></span>
              <span className={`font-semibold tabular-nums ${h.delta < 0 ? "text-danger" : "text-hg-success"}`}>{h.delta > 0 ? `+${h.delta}` : h.delta}{h.after !== undefined ? ` → ${h.after}` : ""}</span>
            </li>))}</ul>
        </DialogContent>
      </Dialog>
      <ImportDialog open={importing} initialMode="stock" onClose={() => setImporting(false)} onDone={reload} />
    </div>
  );
}
