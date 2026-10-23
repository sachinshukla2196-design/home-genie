import React, { useRef, useState } from "react";
import { Download, FileUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Pill, downloadCsv, useAction } from "@/components/vendor/kit";

/** CSV import with a mandatory preview. The server is all-or-nothing: any invalid row blocks the whole import and is reported. */
export function ImportDialog({ open, onClose, onDone, initialMode = "products" }) {
  const { t } = useI18n();
  const [mode, setMode] = useState(initialMode);
  const [text, setText] = useState("");
  const [report, setReport] = useState(null);
  const [run, busy] = useAction();
  const file = useRef(null);

  const reset = (m) => { setMode(m); setReport(null); };
  const readFile = (e) => {
    const f = e.target.files && e.target.files[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > 1_000_000) { setReport({ error: t("vx.imp.tooBig") }); return; }
    const r = new FileReader();
    r.onload = () => { setText(String(r.result || "")); setReport(null); };
    r.readAsText(f);
  };
  const send = async (commit) => {
    setReport(null);
    try {
      const { data } = await API.post("/vendor/products/import", { mode, csv: text, commit });
      setReport(data);
      return data;
    } catch (e) {
      const d = e?.response?.data?.detail;
      setReport(d && typeof d === "object" ? { ...d, error: d.message } : { error: apiError(e) });
      return null;
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto rounded-3xl" data-testid="import-dialog">
        <DialogHeader><DialogTitle>{t("vx.imp.title")}</DialogTitle><DialogDescription>{t("vx.imp.desc")}</DialogDescription></DialogHeader>
        <div className="flex flex-wrap gap-2" role="tablist">
          {["products", "stock"].map((m) => (
            <button key={m} role="tab" aria-selected={mode === m} onClick={() => reset(m)} data-testid={`imp-mode-${m}`}
              className={`rounded-full px-4 py-1.5 text-sm font-medium ${mode === m ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(`vx.imp.mode.${m}`)}</button>
          ))}
          <Button variant="outline" className="ml-auto h-9 rounded-full" onClick={() => downloadCsv("/vendor/products/import-template.csv", `import-${mode}.csv`, { mode })} data-testid="imp-template"><Download size={14} /> {t("vx.imp.template")}</Button>
        </div>
        <Textarea rows={7} value={text} onChange={(e) => { setText(e.target.value); setReport(null); }} placeholder={t("vx.imp.paste")} className="font-mono text-xs" aria-label={t("vx.imp.paste")} data-testid="imp-text" />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" className="h-10 rounded-full" onClick={() => file.current && file.current.click()} data-testid="imp-file"><FileUp size={15} /> {t("vx.imp.choose")}</Button>
          <input ref={file} type="file" accept=".csv,text/csv" className="sr-only" onChange={readFile} aria-label={t("vx.imp.choose")} />
          <Button className="hg-btn h-10 rounded-full" disabled={busy || !text.trim()} onClick={() => run(() => send(false))} data-testid="imp-preview">{t("vx.imp.preview")}</Button>
          <Button className="h-10 rounded-full bg-hg-success text-white hover:bg-hg-success/90" data-testid="imp-commit"
            disabled={busy || !report || report.invalid !== 0 || report.committed || !(report.rows > 0)}
            onClick={() => run(async () => { const d = await send(true); if (d && d.committed) { onDone && onDone(); } }, { success: t("vx.imp.done") })}>{t("vx.imp.commit")}</Button>
        </div>
        {report && report.error && !report.report && <p role="alert" className="text-sm text-danger" data-testid="imp-error">{report.error}</p>}
        {report && report.report && (
          <div className="space-y-2" data-testid="imp-report">
            <p className="text-sm text-ink" role="status">
              {report.committed ? t("vx.imp.committed", { n: report.valid }) : t("vx.imp.summary", { rows: report.rows, ok: report.valid, bad: report.invalid })}
              {report.invalid > 0 && <span className="ml-2 text-danger">{t("vx.imp.nothingWritten")}</span>}
            </p>
            <div className="max-h-56 overflow-y-auto rounded-xl bg-white/5">
              <table className="w-full text-xs"><thead><tr className="text-left text-muted2"><th className="p-2">{t("vx.imp.row")}</th><th className="p-2">SKU</th><th className="p-2">{t("vx.status")}</th><th className="p-2">{t("vx.imp.errors")}</th></tr></thead>
                <tbody>{report.report.map((r) => (
                  <tr key={r.row} className="border-t border-white/10" data-testid={`imp-row-${r.row}`}>
                    <td className="p-2 tabular-nums">{r.row}</td><td className="p-2 font-mono">{r.sku}</td>
                    <td className="p-2"><Pill tone={r.status === "ok" ? "ok" : "bad"}>{r.status === "ok" ? t("vx.imp.ok") : t("vx.imp.error")}</Pill></td>
                    <td className="p-2 text-danger">{r.errors.join("; ")}</td></tr>))}</tbody></table>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
