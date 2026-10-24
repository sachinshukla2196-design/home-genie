import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { Pager } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { ConfirmDialog, Field, Money, Pill, ResponsiveTable, StateBlock, fmtDate, fmtDateTime, useAction, usePaged } from "@/components/vendor/kit";

const TABS = ["all", "requested", "contested", "approved", "in_transit", "received", "inspected", "replacement_due", "refund_pending", "refunded", "rejected", "closed", "cancelled"];
const TONE = { requested: "warn", contested: "bad", approved: "violet", in_transit: "info", received: "info", inspected: "info", replacement_due: "warn", refund_pending: "warn", refunded: "ok", closed: "ok", rejected: "muted", cancelled: "muted" };

function ReturnDetail({ id, onChanged }) {
  const { t, lang } = useI18n();
  const [rc, setRc] = useState(null);
  const [error, setError] = useState(null);
  const [mode, setMode] = useState(null);           // contest | inspect | replacement
  const [note, setNote] = useState("");
  const [ship, setShip] = useState({ carrier: "", tracking_number: "" });
  const [outcomes, setOutcomes] = useState({});
  const [confirmReceive, setConfirmReceive] = useState(false);
  const [run, busy] = useAction();
  const load = useCallback(() => { setError(null); API.get(`/vendor/returns/${id}`).then(({ data }) => setRc(data)).catch((e) => setError(apiError(e))); }, [id]);
  useEffect(() => { setRc(null); setMode(null); load(); }, [load]);
  if (!rc) return <StateBlock loading={!error} error={error} onRetry={load} rows={2} testid="rd" />;

  const act = (action, extra = {}, msg) => run(async () => { await API.post(`/vendor/returns/${id}/action`, { action, note, ...extra }); setMode(null); setNote(""); setConfirmReceive(false); load(); onChanged(); }, { success: msg });
  const inspect = () => run(async () => {
    await API.post(`/vendor/returns/${id}/inspection`, { lines: rc.lines.map((_, i) => ({ index: i, outcome: outcomes[i] || "resellable" })), note });
    setMode(null); setNote(""); load(); onChanged();
  }, { success: t("vp.insp.done") + " ✓" });

  return (
    <div className="space-y-4" data-testid="return-detail">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-xl font-semibold text-ink">{rc.number}</span>
        <Pill tone={TONE[rc.status]} testid="rd-status">{t(`vx.ret.st.${rc.status}`)}</Pill><Pill tone="muted">{t(`vx.ret.kind.${rc.kind}`)}</Pill>
      </div>
      <p className="text-sm text-muted2">{t("vx.ret.forOrder", { n: rc.order_number })} · {fmtDate(rc.created_at, lang)}</p>
      <div className="hg-tile p-3 text-sm"><div className="text-xs font-semibold uppercase tracking-wide text-muted2">{t("vx.ret.reason")}</div><p className="mt-1 text-ink" data-testid="rd-reason">{rc.reason}</p></div>
      {rc.photos?.length > 0 && <div className="flex flex-wrap gap-2" data-testid="rd-photos">{rc.photos.map((u) => <a key={u} href={u} target="_blank" rel="noopener noreferrer"><img src={u} alt={t("vx.ret.photo")} className="h-20 w-20 rounded-lg object-cover" loading="lazy" /></a>)}</div>}
      <ul className="space-y-2">{rc.lines.map((l, i) => (
        <li key={i} className="hg-tile flex items-center justify-between gap-3 p-2.5 text-sm"><span className="min-w-0 truncate text-ink">{l.name} ×{l.quantity}</span>
          {rc.inspection ? <Pill tone={rc.inspection.lines[i]?.outcome === "resellable" ? "ok" : "bad"}>{t(`vp.insp.${rc.inspection.lines[i]?.outcome}`)}</Pill> : <Money paise={l.price_paise * l.quantity} className="text-xs text-muted2" />}</li>))}</ul>
      {rc.suggested_refund_paise > 0 && <p className="text-xs text-muted2">{t("vx.ret.suggested")}: <Money paise={rc.suggested_refund_paise} className="font-semibold text-ink" /> · {t("vx.ret.refundByAdmin")}</p>}
      <ol className="space-y-2 border-l border-white/15 pl-4" data-testid="rd-timeline">{rc.events.map((e, i) => <li key={i} className="text-sm"><span className="font-medium text-ink">{t(`vx.ret.st.${e.status}`)}</span><span className="ml-2 text-xs text-muted2">{fmtDateTime(e.at, lang)}</span>{e.note && <div className="text-xs text-muted2">{e.note}</div>}</li>)}</ol>

      {mode === "contest" && <div className="space-y-2 rounded-2xl bg-white/[0.04] p-4"><p className="text-xs text-muted2">{t("vx.ret.contestHelp")}</p><Field label={t("vp.reason")} htmlFor="rd-note"><Input id="rd-note" value={note} onChange={(e) => setNote(e.target.value)} data-testid="rd-note" /></Field>
        <div className="flex justify-end gap-2"><Button variant="outline" className="h-10 rounded-full" onClick={() => setMode(null)}>{t("vx.cancel")}</Button><Button className="h-10 rounded-full bg-danger text-white" disabled={busy || note.trim().length < 5} onClick={() => act("contest", {}, t("vx.ret.contested"))} data-testid="rd-contest-confirm">{t("vx.ret.contest")}</Button></div></div>}
      {mode === "inspect" && (
        <div className="space-y-3 rounded-2xl bg-hg-gold/10 p-4 ring-1 ring-hg-gold/30" data-testid="rd-inspect">
          <p className="text-xs text-muted2">{t("vp.insp.hint")}</p>
          {rc.lines.map((l, i) => (
            <fieldset key={i} className="flex flex-wrap items-center gap-3 text-sm"><legend className="sr-only">{l.name}</legend><span className="min-w-0 flex-1 truncate text-ink">{l.name} ×{l.quantity}</span>
              {["resellable", "damaged"].map((o) => <label key={o} className="flex items-center gap-1.5"><input type="radio" name={`out-${i}`} checked={(outcomes[i] || "resellable") === o} onChange={() => setOutcomes({ ...outcomes, [i]: o })} data-testid={`rd-out-${i}-${o}`} /> {t(`vp.insp.${o}`)}</label>)}</fieldset>))}
          <Field label={t("vp.insp.note")} htmlFor="rd-insp-note"><Input id="rd-insp-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} data-testid="rd-insp-note" /></Field>
          <div className="flex justify-end gap-2"><Button variant="outline" className="h-10 rounded-full" onClick={() => setMode(null)}>{t("vx.cancel")}</Button><Button className="hg-btn h-10 rounded-full" disabled={busy || note.trim().length < 5} onClick={inspect} data-testid="rd-inspect-submit">{t("vp.insp.submit")}</Button></div>
        </div>)}
      {mode === "replacement" && <div className="space-y-2 rounded-2xl bg-white/[0.04] p-4"><div className="grid gap-3 sm:grid-cols-2"><Field label={t("vp.carrier")} htmlFor="rd-car"><Input id="rd-car" value={ship.carrier} onChange={(e) => setShip({ ...ship, carrier: e.target.value })} /></Field><Field label={t("vp.tracking")} htmlFor="rd-trk"><Input id="rd-trk" value={ship.tracking_number} onChange={(e) => setShip({ ...ship, tracking_number: e.target.value })} /></Field></div>
        <p className="text-[11px] text-muted2">{t("vx.ord.manualTracking")} {t("vx.ret.replacementStock")}</p>
        <div className="flex justify-end gap-2"><Button variant="outline" className="h-10 rounded-full" onClick={() => setMode(null)}>{t("vx.cancel")}</Button><Button className="hg-btn h-10 rounded-full" disabled={busy || !ship.carrier.trim() || !ship.tracking_number.trim()} onClick={() => act("replacement_dispatched", ship, t("vx.ret.replacementSent"))} data-testid="rd-replace-confirm">{t("vx.ret.dispatchReplacement")}</Button></div></div>}

      {!mode && (
        <div className="flex flex-wrap gap-2" data-testid="rd-actions">
          {rc.status === "requested" && <><Button className="hg-btn h-11 flex-1 rounded-full" disabled={busy} onClick={() => act("approve", {}, t("vx.ret.approved"))} data-testid="rd-approve">{t("vx.ret.approve")}</Button>
            <Button variant="outline" className="h-11 flex-1 rounded-full border-danger/40 text-danger" onClick={() => setMode("contest")} data-testid="rd-contest">{t("vx.ret.contest")}</Button></>}
          {["approved", "in_transit"].includes(rc.status) && <Button className="hg-btn h-11 flex-1 rounded-full" onClick={() => setConfirmReceive(true)} data-testid="rd-receive">{t("vx.ret.receive")}</Button>}
          {rc.status === "received" && <Button className="hg-btn h-11 flex-1 rounded-full" onClick={() => setMode("inspect")} data-testid="rd-inspect-open">{t("vx.ret.inspect")}</Button>}
          {rc.status === "replacement_due" && <Button className="hg-btn h-11 flex-1 rounded-full" onClick={() => setMode("replacement")} data-testid="rd-replace-open">{t("vx.ret.dispatchReplacement")}</Button>}
          {rc.status === "contested" && <p className="text-sm text-muted2" role="note">{t("vx.ret.contestedWait")}</p>}
        </div>)}
      <ConfirmDialog open={confirmReceive} busy={busy} title={t("vx.ret.receiveTitle")} body={t("vx.ret.receiveBody")} confirmLabel={t("vx.ret.receive")} onClose={() => setConfirmReceive(false)} onConfirm={() => act("receive", {}, t("vx.ret.received"))} />
    </div>
  );
}

export default function VendorReturns({ embedded = false }) {
  const { t, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("status") || "all";
  const open = sp.get("open");
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/returns", { status: tab === "all" ? undefined : tab }, 15);
  const counts = data?.counts || {};
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const setParam = (k, v) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n, { replace: k === "open" }); };
  const columns = [
    { key: "n", label: t("vx.ret.number"), render: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "o", label: t("order.number"), render: (r) => r.order_number },
    { key: "k", label: t("vx.ret.type"), render: (r) => t(`vx.ret.kind.${r.kind}`) },
    { key: "l", label: t("vp.items"), hideOnMobile: true, render: (r) => <span className="block max-w-[16rem] truncate text-muted2">{r.lines.map((l) => `${l.name} ×${l.quantity}`).join(", ")}</span> },
    { key: "d", label: t("vx.date"), hideOnMobile: true, render: (r) => fmtDate(r.created_at, lang) },
    { key: "s", label: t("vx.status"), render: (r) => <Pill tone={TONE[r.status]}>{t(`vx.ret.st.${r.status}`)}</Pill> },
  ];
  return (
    <div className="space-y-5">
      {!embedded && <PageHeader title={t("vx.nav.returns")} subtitle={t("vx.ret.sub")} icon={Undo2} />}
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0" role="tablist">
        {TABS.filter((s) => s === "all" || counts[s] || tab === s).map((s) => <button key={s} role="tab" aria-selected={tab === s} onClick={() => setParam("status", s === "all" ? "" : s)} data-testid={`ret-tab-${s}`}
          className={`shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${tab === s ? "hg-chip-on text-white" : "hg-chip-off"}`}>{s === "all" ? t("vp.o.all") : t(`vx.ret.st.${s}`)} · {s === "all" ? total : counts[s] ?? 0}</button>)}
      </div>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="ret" empty={items && items.length === 0} emptyIcon={Undo2} emptyTitle={t("vx.ret.empty")} emptyDesc={t("vx.ret.emptyDesc")}>
        <ResponsiveTable columns={columns} rows={items || []} onRowClick={(r) => setParam("open", r.id)} rowTestid={(r) => `ret-row-${r.number}`} caption={t("vx.nav.returns")} />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="ret-pager" />}
      <Dialog open={!!open} onOpenChange={(v) => !v && setParam("open", "")}>
        <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="ret-dialog">
          <DialogHeader><DialogTitle className="sr-only">{t("vx.nav.returns")}</DialogTitle><DialogDescription className="sr-only">{t("vx.ret.sub")}</DialogDescription></DialogHeader>
          {open && <ReturnDetail id={open} onChanged={reload} />}
        </DialogContent>
      </Dialog>
    </div>
  );
}
