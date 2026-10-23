import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/EmptyState";
import { AlertDialog, AlertDialogContent, AlertDialogHeader, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter } from "@/components/ui/alert-dialog";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

/* ------------------------------------------------------------------ formatting (exact: paise in, rupees out) */
const NF = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** Integer paise -> "₹1,234.56". Never does arithmetic on floats: the backend sends exact paise. */
export const inrP = (paise) => {
  const p = Math.round(Number(paise) || 0);
  return `${p < 0 ? "-" : ""}₹${NF.format(Math.abs(p) / 100)}`;
};
/** Rupee number (already exact to 2 dp from the API) -> "₹1,234.56". */
export const inrV = (v) => inrP(Math.round((Number(v) || 0) * 100));
export function Money({ paise, value, className = "" }) {
  return <span className={`tabular-nums ${className}`}>{paise !== undefined ? inrP(paise) : inrV(value)}</span>;
}
export const fmtDate = (iso, lang = "en") => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", { day: "2-digit", month: "short", year: "numeric" });
};
export const fmtDateTime = (iso, lang = "en") => {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(lang === "hi" ? "hi-IN" : "en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
};

/* ------------------------------------------------------------------ status pills (always text + a shape: never colour alone) */
export const TONES = {
  ok: ["bg-hg-success/15 text-hg-success ring-hg-success/30", "●"],
  warn: ["bg-hg-gold/15 text-hg-gold ring-hg-gold/30", "▲"],
  bad: ["bg-danger/10 text-danger ring-danger/30", "■"],
  info: ["bg-[#5B7CFF]/15 text-[#8FA6FF] ring-[#8FA6FF]/30", "◆"],
  violet: ["bg-hg-violet/15 text-hg-lavender ring-hg-lavender/30", "●"],
  muted: ["bg-white/10 text-muted2 ring-white/15", "○"],
};
export function Pill({ tone = "muted", children, testid, className = "" }) {
  const [cls, glyph] = TONES[tone] || TONES.muted;
  return (
    <span data-testid={testid} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${cls} ${className}`}>
      <span aria-hidden className="text-[8px] leading-none">{glyph}</span>{children}
    </span>
  );
}

/* ------------------------------------------------------------------ loading / error / empty */
export function StateBlock({ loading, error, empty, onRetry, emptyIcon, emptyTitle, emptyDesc, ctaLabel, onCta, rows = 3, testid, children }) {
  const { t } = useI18n();
  if (loading) {
    return <div className="space-y-3" role="status" aria-label={t("vx.loading")} data-testid={testid ? `${testid}-loading` : "state-loading"}>
      {Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}</div>;
  }
  if (error) {
    return (
      <div role="alert" className="hg-card flex flex-col items-center gap-3 p-8 text-center" data-testid={testid ? `${testid}-error` : "state-error"}>
        <AlertTriangle className="text-danger" />
        <p className="text-sm text-ink">{typeof error === "string" ? error : t("vx.loadFailed")}</p>
        {onRetry && <Button variant="outline" onClick={onRetry} className="h-10 rounded-full"><RefreshCw size={15} /> {t("vx.retry")}</Button>}
      </div>
    );
  }
  if (empty) return <EmptyState icon={emptyIcon} title={emptyTitle} desc={emptyDesc} ctaLabel={ctaLabel} onCta={onCta} testid={testid ? `${testid}-empty` : "state-empty"} />;
  return children;
}

/* ------------------------------------------------------------------ server-paged list hook */
/** Loads `url` with page/page_size/params. Only the newest response may update the screen; an out-of-range page is clamped. */
export function usePaged(url, params = {}, pageSize = 15) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [page, setPage] = useState(1);
  const [tick, setTick] = useState(0);
  const req = useRef(0);
  const key = JSON.stringify(params);
  useEffect(() => { setPage(1); }, [key]);
  useEffect(() => {
    const id = ++req.current;
    setError(null);
    API.get(url, { params: { ...JSON.parse(key), page, page_size: pageSize } })
      .then(({ data: d }) => { if (id === req.current) setData(d); })
      .catch((e) => { if (id === req.current) { setError(apiError(e)); setData(null); } });
  }, [url, key, page, pageSize, tick]);
  useEffect(() => { if (data && page > data.pages) setPage(data.pages); }, [data, page]);
  const reload = useCallback(() => setTick((x) => x + 1), []);
  return { data, items: data ? data.items : null, loading: data === null && !error, error, page, setPage, reload };
}

/** Runs an async action once at a time (no double submits), with a success / failure toast. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const run = useCallback(async (fn, { success, onDone } = {}) => {
    if (lock.current) return undefined;
    lock.current = true; setBusy(true);
    try {
      const r = await fn();
      if (success) toast.success(success);
      if (onDone) onDone(r);
      return r;
    } catch (e) { toast.error(apiError(e)); return undefined; }
    finally { lock.current = false; setBusy(false); }
  }, []);
  return [run, busy];
}

/* ------------------------------------------------------------------ responsive table: table on desktop, cards on phones */
export function ResponsiveTable({ columns, rows, rowKey = (r) => r.id, onRowClick, caption, testid, rowTestid }) {
  const primary = columns.filter((c) => !c.hideOnMobile);
  const open = (r) => onRowClick && onRowClick(r);
  return (
    <div data-testid={testid}>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-sm">
          {caption && <caption className="sr-only">{caption}</caption>}
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2">
            {columns.map((c) => <th key={c.key} scope="col" className={`px-3 py-2 font-semibold ${c.align === "right" ? "text-right" : ""}`}>{c.label}</th>)}
          </tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={rowKey(r)} data-testid={rowTestid ? rowTestid(r) : undefined} onClick={() => open(r)}
                onKeyDown={(e) => onRowClick && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open(r))}
                tabIndex={onRowClick ? 0 : undefined} role={onRowClick ? "button" : undefined}
                className={`border-t border-white/10 align-middle ${onRowClick ? "cursor-pointer hover:bg-brand-50/50 focus-visible:bg-brand-50/60" : ""}`}>
                {columns.map((c) => <td key={c.key} className={`px-3 py-3 ${c.align === "right" ? "text-right" : ""} ${c.className || ""}`}>{c.render ? c.render(r) : r[c.key]}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="space-y-2 md:hidden">
        {rows.map((r) => (
          <li key={rowKey(r)}>
            <div role={onRowClick ? "button" : undefined} tabIndex={onRowClick ? 0 : undefined} onClick={() => open(r)}
              onKeyDown={(e) => onRowClick && (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open(r))}
              className="hg-tile space-y-1.5 p-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet" data-testid={rowTestid ? rowTestid(r) : undefined}>
              {primary.map((c) => (
                <div key={c.key} className="flex items-start justify-between gap-3 text-sm">
                  <span className="shrink-0 text-xs text-muted2">{c.label}</span>
                  <span className="min-w-0 text-right text-ink">{c.render ? c.render(r) : r[c.key]}</span>
                </div>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ------------------------------------------------------------------ confirmation before a consequential action */
export function ConfirmDialog({ open, title, body, confirmLabel, cancelLabel, danger, busy, onConfirm, onClose }) {
  const { t } = useI18n();
  return (
    <AlertDialog open={open} onOpenChange={(v) => !v && !busy && onClose()}>
      <AlertDialogContent data-testid="confirm-dialog">
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {body && <AlertDialogDescription>{body}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy} className="h-10 rounded-full" data-testid="confirm-cancel">{cancelLabel || t("vx.cancel")}</Button>
          <Button onClick={onConfirm} disabled={busy} className={`h-10 rounded-full ${danger ? "bg-danger text-white hover:bg-danger/90" : "hg-btn"}`} data-testid="confirm-ok">{confirmLabel || t("vx.confirm")}</Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

/* ------------------------------------------------------------------ date range selector */
export const RANGES = ["today", "7d", "30d", "month", "custom"];
export function RangeBar({ value, onChange, from, to, onCustom }) {
  const { t } = useI18n();
  return (
    <div className="flex flex-wrap items-center gap-2" role="tablist" aria-label={t("vx.range")} data-testid="range-bar">
      {RANGES.map((r) => (
        <button key={r} role="tab" aria-selected={value === r} onClick={() => onChange(r)} data-testid={`range-${r}`}
          className={`rounded-full px-3.5 py-1.5 text-xs font-medium ${value === r ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(`vx.range.${r}`)}</button>
      ))}
      {value === "custom" && (
        <span className="flex flex-wrap items-center gap-2 text-xs">
          <label className="sr-only" htmlFor="rf">{t("vx.from")}</label>
          <input id="rf" type="date" value={from || ""} onChange={(e) => onCustom(e.target.value, to)} className="h-9 rounded-lg bg-white/5 px-2 text-ink ring-1 ring-white/15" data-testid="range-from" />
          <label className="sr-only" htmlFor="rt">{t("vx.to")}</label>
          <input id="rt" type="date" value={to || ""} onChange={(e) => onCustom(from, e.target.value)} className="h-9 rounded-lg bg-white/5 px-2 text-ink ring-1 ring-white/15" data-testid="range-to" />
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ small form helpers */
export function Field({ label, htmlFor, hint, error, children, className = "" }) {
  return (
    <div className={className}>
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">{label}</label>
      <div className="mt-1.5">{children}</div>
      {hint && !error && <p className="mt-1 text-xs text-muted2">{hint}</p>}
      {error && <p role="alert" className="mt-1 text-xs text-danger">{error}</p>}
    </div>
  );
}

/** Downloads an authenticated CSV (the token lives in the API client, so a plain <a href> would not work). */
export async function downloadCsv(url, filename, params) {
  const { data } = await API.get(url, { params, responseType: "blob" });
  const href = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = href; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 2000);
}

export function useMemoKey(obj) { return useMemo(() => JSON.stringify(obj), [obj]); }
