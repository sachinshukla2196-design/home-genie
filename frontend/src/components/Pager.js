import React, { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Input } from "@/components/ui/input";

/** Debounces a fast-changing value (search box) so the server is not queried on every keystroke. */
export function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value);
  useEffect(() => { const id = setTimeout(() => setV(value), ms); return () => clearTimeout(id); }, [value, ms]);
  return v;
}

export function SearchBox({ value, onChange, placeholder, testid }) {
  return (
    <div className="relative w-full sm:max-w-sm">
      <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted2" aria-hidden />
      <Input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={placeholder}
        maxLength={80} className="h-11 rounded-full pl-10" data-testid={testid} />
    </div>
  );
}

export function Pager({ page, pages, total, onPage, t, testid = "pager" }) {
  if (!total || pages <= 1) return total ? <div className="text-center text-xs text-muted2" data-testid={`${testid}-total`}>{total} {t("vp.results")}</div> : null;
  const btn = "inline-flex h-10 items-center gap-1 rounded-full px-4 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 hg-chip-off";
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 pt-1" data-testid={testid}>
      <span className="text-xs text-muted2">{total} {t("vp.results")}</span>
      <div className="flex items-center gap-2">
        <button type="button" className={btn} disabled={page <= 1} onClick={() => onPage(page - 1)} data-testid={`${testid}-prev`}><ChevronLeft size={16} /> {t("vp.prev")}</button>
        <span className="min-w-[5.5rem] text-center text-sm tabular-nums text-ink" aria-live="polite">{t("vp.page")} {page} / {pages}</span>
        <button type="button" className={btn} disabled={page >= pages} onClick={() => onPage(page + 1)} data-testid={`${testid}-next`}>{t("vp.next")} <ChevronRight size={16} /></button>
      </div>
    </div>
  );
}
