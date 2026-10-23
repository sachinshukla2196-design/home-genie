import React, { useCallback, useEffect, useState } from "react";
import { Check, MapPin, Package, Phone, Truck, AlertTriangle, Undo2, Landmark, Info } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Field, Money, Pill, StateBlock, fmtDateTime, useAction } from "@/components/vendor/kit";

// Actions available from each fulfilment state (mirrors the server state machine; the server enforces it too).
export const ACTIONS = {
  new: [{ to: "accepted", key: "vp.act.accept", primary: true }, { to: "rejected", key: "vp.act.reject", needs: "reason" }],
  accepted: [{ to: "packed", key: "vp.act.pack", primary: true }, { to: "cancelled", key: "vp.act.cancel", needs: "reason" }],
  packed: [{ to: "dispatched", key: "vp.act.dispatch", primary: true, needs: "tracking" }, { to: "cancelled", key: "vp.act.cancel", needs: "reason" }],
  dispatched: [{ to: "delivered", key: "vp.act.deliver", primary: true, needs: "evidence" }, { to: "delivery_failed", key: "vp.act.fail", needs: "reason" }],
  delivery_failed: [{ to: "dispatched", key: "vp.act.redispatch", primary: true, needs: "tracking" }, { to: "returned_to_origin", key: "vp.act.rto", needs: "reason" }],
};
export const FULFIL_PILL = { new: "warn", accepted: "violet", packed: "violet", dispatched: "info", delivered: "ok", delivery_failed: "bad", rejected: "bad", cancelled: "bad", returned_to_origin: "muted" };
const EMPTY = { note: "", carrier: "", tracking_number: "", tracking_url: "" };

/** Returned goods go back into stock ONLY after the vendor confirms receipt + inspection (the server enforces it too). */
function Inspection({ o, onDone }) {
  const { t } = useI18n();
  const rec = o.fulfilment.return_inspection;
  const [received, setReceived] = useState(false);
  const [outcome, setOutcome] = useState("resellable");
  const [note, setNote] = useState("");
  const [run, busy] = useAction();
  if (rec) return <div className="rounded-2xl bg-white/[0.04] p-4 text-sm ring-1 ring-white/10" data-testid="vo-inspection-done"><div className="font-semibold text-ink">{t("vp.insp.done")}: {rec.outcome === "resellable" ? t("vp.insp.resellable") : t("vp.insp.damaged")}</div><div className="mt-1 text-xs text-muted2">{rec.note}</div></div>;
  return (
    <div className="space-y-3 rounded-2xl bg-hg-gold/10 p-4 ring-1 ring-hg-gold/30" data-testid="vo-inspection">
      <div><div className="font-semibold text-ink">{t("vp.insp.title")}</div><p className="text-xs text-muted2">{t("vp.insp.hint")}</p></div>
      <label className="flex items-center gap-2 text-sm text-ink"><input type="checkbox" checked={received} onChange={(e) => setReceived(e.target.checked)} data-testid="vo-insp-received" /> {t("vp.insp.received")}</label>
      <div className="flex flex-col gap-1.5 text-sm text-ink" role="radiogroup" aria-label={t("vp.insp.title")}>
        {["resellable", "damaged"].map((v) => <label key={v} className="flex items-center gap-2"><input type="radio" name="insp-outcome" checked={outcome === v} onChange={() => setOutcome(v)} data-testid={`vo-insp-${v}`} /> {t(`vp.insp.${v}`)}</label>)}
      </div>
      <Field label={t("vp.insp.note")} htmlFor="vo-insp-note"><Input id="vo-insp-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} data-testid="vo-insp-note" /></Field>
      <Button disabled={busy || !received || note.trim().length < 5} className="hg-btn h-11 rounded-full px-5" data-testid="vo-insp-submit"
        onClick={() => run(async () => { await API.post(`/vendor/orders/${o.id}/return-inspection`, { received, outcome, note }); onDone(); }, { success: t("vp.insp.done") + " ✓" })}>{t("vp.insp.submit")}</Button>
    </div>
  );
}

export function OrderDetail({ orderId, onChanged }) {
  const { t, lang } = useI18n();
  const [o, setO] = useState(null);
  const [error, setError] = useState(null);
  const [action, setAction] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [run, busy] = useAction();

  const load = useCallback(() => {
    setError(null);
    API.get(`/vendor/orders/${orderId}`, { params: { detail: true } }).then(({ data }) => setO(data)).catch((e) => setError(apiError(e)));
  }, [orderId]);
  useEffect(() => { setO(null); load(); }, [load]);

  if (!o) return <StateBlock loading={!error} error={error} onRetry={load} rows={2} testid="od" />;
  const f = o.fulfilment;
  const perform = (a) => run(async () => {
    await API.post(`/vendor/orders/${o.id}/fulfilment`, { status: a.to, ...form });
    setAction(null); setForm(EMPTY); load(); onChanged && onChanged();
  }, { success: `${t(`vp.f.${a.to}`)} ✓` });
  const start = (a) => (a.needs ? setAction(a) : perform(a));
  const canGo = (a) => !(a.needs === "reason" && form.note.trim().length < 5) && !(a.needs === "evidence" && form.note.trim().length < 3) && !(a.needs === "tracking" && !(form.carrier.trim() && form.tracking_number.trim()));

  return (
    <div className="space-y-4" data-testid="order-detail">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-display text-xl font-semibold text-ink" data-testid="od-number">{o.order_number}</span>
        <Pill tone={FULFIL_PILL[f.status]} testid="vo-dialog-status">{t(`vp.f.${f.status}`)}</Pill>
        <Pill tone="muted">{o.payment_method === "cod" ? t("vp.cod") : t("vp.prepaid")}</Pill>
        <Pill tone={o.payment_status === "paid" ? "ok" : o.payment_status === "cod_discrepancy" ? "bad" : "warn"}>{t(`vx.pay.${o.payment_status}`) === `vx.pay.${o.payment_status}` ? o.payment_status : t(`vx.pay.${o.payment_status}`)}</Pill>
        {o.dispatch_overdue && <Pill tone="bad" testid="od-overdue">{t("vx.ord.overdue")}</Pill>}
        {o.cancel_requested && <Pill tone="warn" testid="od-cancel-requested">{t("vx.ord.cancelRequested")}</Pill>}
      </div>
      {o.dispatch_due_at && ["new", "accepted", "packed"].includes(f.status) && <p className="text-xs text-muted2">{t("vx.ord.dispatchBy", { d: fmtDateTime(o.dispatch_due_at, lang) })}</p>}
      {o.cancel_requested && <p className="flex gap-2 rounded-xl bg-hg-gold/10 p-3 text-xs text-ink" role="note"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.ord.cancelRequestedHelp", { r: o.cancel_requested.reason })}</p>}

      <div className="hg-tile p-4 text-sm">
        <div className="mb-1.5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><MapPin size={13} aria-hidden /> {t("vp.shipTo")}</div>
        <div className="font-medium text-ink">{o.ship_to.full_name}</div>
        <div className="text-muted2">{o.ship_to.line1}, {o.ship_to.city}, {o.ship_to.state} - {o.ship_to.pincode}</div>
        <div className="mt-1 flex items-center gap-1.5 text-muted2"><Phone size={12} aria-hidden /> {o.ship_to.mobile}</div>
      </div>

      <div>
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><Package size={13} aria-hidden /> {t("vp.items")}</div>
        <ul className="space-y-2">
          {o.items.map((li, i) => (
            <li key={`${li.sku}-${i}`} className="hg-tile flex items-center gap-3 p-2.5">
              {li.image && <img src={li.image} alt="" className="h-11 w-11 rounded-lg object-cover" loading="lazy" />}
              <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium text-ink">{li.name}</div><div className="text-xs text-muted2">{li.sku}{li.variant ? ` · ${li.variant}` : ""} · ×{li.quantity}</div></div>
              <Money paise={li.total_paise ?? Math.round(li.total * 100)} className="text-sm font-semibold text-ink" />
            </li>
          ))}
        </ul>
        <dl className="mt-2 space-y-1 text-sm" data-testid="od-financial">
          <div className="flex justify-between"><dt className="text-muted2">{t("vx.ord.itemsValue")}</dt><dd><Money paise={o.financial.items_total_paise} className="font-semibold text-ink" /></dd></div>
          <div className="flex justify-between text-xs"><dt className="text-muted2">{t("vx.ord.paymentStatus")}</dt><dd className="text-ink">{o.payment_status}</dd></div>
        </dl>
        <p className="mt-1 text-[11px] text-muted2">{t("vx.ord.taxNote")}</p>
      </div>

      {o.exceptions.length > 0 && (
        <div className="space-y-1.5 rounded-2xl bg-danger/10 p-3 ring-1 ring-danger/25" data-testid="od-exceptions">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-danger"><AlertTriangle size={13} aria-hidden /> {t("vx.ord.exceptions")}</div>
          {o.exceptions.map((e, i) => <div key={i} className="text-sm text-ink">{t(`vp.f.${e.status}`)} · <span className="text-muted2">{fmtDateTime(e.at, lang)}</span>{e.note && <div className="text-xs text-muted2">{e.note}</div>}</div>)}
        </div>
      )}

      {(o.shipment.tracking_number || ["packed", "accepted"].includes(f.status)) && (
        <div className="rounded-xl bg-[#5B7CFF]/10 p-3 text-sm ring-1 ring-[#8FA6FF]/25" data-testid="od-shipment">
          <div className="flex items-center gap-2"><Truck size={16} className="text-[#8FA6FF]" aria-hidden />
            {o.shipment.tracking_number ? <span>{o.shipment.carrier} · <b className="text-ink">{o.shipment.tracking_number}</b>{o.shipment.tracking_url && <> · <a href={o.shipment.tracking_url} target="_blank" rel="noopener noreferrer" className="text-hg-lavender underline">{t("vx.ord.track")}</a></>}</span> : <span className="text-muted2">{t("vx.ord.noTracking")}</span>}</div>
          <p className="mt-1 text-[11px] text-muted2">{t("vx.ord.manualTracking")}</p>
        </div>
      )}

      {o.returns.length > 0 && (
        <div className="space-y-1.5" data-testid="od-returns">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><Undo2 size={13} aria-hidden /> {t("vx.nav.returns")}</div>
          {o.returns.map((r) => <a key={r.id} href={`/vendor/returns?open=${r.id}`} className="hg-tile flex items-center justify-between gap-2 p-2.5 text-sm text-ink hover:bg-brand-50/60"><span>{r.number} · {t(`vx.ret.kind.${r.kind}`)}</span><Pill tone="info">{t(`vx.ret.st.${r.status}`)}</Pill></a>)}
        </div>
      )}

      {o.ledger.length > 0 && (
        <div className="space-y-1.5" data-testid="od-ledger">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted2"><Landmark size={13} aria-hidden /> {t("vx.ord.ledger")}</div>
          {o.ledger.map((e) => <div key={e.id} className="hg-tile flex justify-between gap-2 p-2.5 text-sm"><span className="text-ink">{t(`vx.led.${e.type}`)}</span><Money paise={e.amount_paise} className={`font-semibold ${e.amount_paise < 0 ? "text-danger" : "text-hg-success"}`} /></div>)}
        </div>
      )}

      <div>
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted2">{t("vp.timeline")}</div>
        <ol className="relative space-y-3 pl-6" data-testid="od-timeline">
          <span aria-hidden className="absolute bottom-2 left-[0.55rem] top-2 w-px bg-white/15" />
          {o.timeline.map((e, i) => (
            <li key={i} className="relative text-sm">
              <span aria-hidden className="absolute -left-6 top-0.5 flex h-[1.15rem] w-[1.15rem] items-center justify-center rounded-full bg-hg-violet text-white"><Check size={11} /></span>
              <span className="font-medium text-ink">{e.status ? t(`vp.f.${e.status}`) : e.label}</span>
              <span className="ml-2 text-xs text-muted2">{fmtDateTime(e.at, lang)} · {t(`vx.by.${e.by}`)}</span>
              {e.note && <div className="text-xs text-muted2">{e.note}</div>}
            </li>
          ))}
        </ol>
      </div>

      {f.status === "returned_to_origin" && <Inspection o={o} onDone={() => { load(); onChanged && onChanged(); }} />}

      {action ? (
        <div className="space-y-3 rounded-2xl bg-white/[0.04] p-4 ring-1 ring-white/10" data-testid="od-action-form">
          {action.needs === "tracking" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t("vp.carrier")} htmlFor="vo-carrier"><Input id="vo-carrier" value={form.carrier} onChange={(e) => setForm({ ...form, carrier: e.target.value })} data-testid="vo-carrier" /></Field>
              <Field label={t("vp.tracking")} htmlFor="vo-tracking"><Input id="vo-tracking" value={form.tracking_number} onChange={(e) => setForm({ ...form, tracking_number: e.target.value })} data-testid="vo-tracking" /></Field>
              <Field label={t("vp.trackingUrl")} htmlFor="vo-turl" className="sm:col-span-2"><Input id="vo-turl" value={form.tracking_url} onChange={(e) => setForm({ ...form, tracking_url: e.target.value })} /></Field>
              <p className="text-[11px] text-muted2 sm:col-span-2">{t("vx.ord.manualTracking")}</p>
            </div>
          )}
          {(action.needs === "reason" || action.needs === "evidence") && (
            <Field label={action.needs === "evidence" ? t("vp.evidence") : t("vp.reason")} htmlFor="vo-note" hint={action.needs === "evidence" ? t("vx.ord.evidenceHint") : undefined}><Input id="vo-note" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} data-testid="vo-note" /></Field>
          )}
          <p className="text-xs text-muted2">{t(`vx.ord.impact.${action.to}`)}</p>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setAction(null)} className="h-10 rounded-full" aria-label={t("vx.cancel")}>✕</Button>
            <Button onClick={() => perform(action)} disabled={busy || !canGo(action)} className={`h-10 rounded-full px-5 ${action.primary ? "hg-btn" : "bg-danger text-white hover:bg-danger/90"}`} data-testid="vo-confirm">{t("vp.confirm")} · {t(action.key)}</Button>
          </div>
        </div>
      ) : (ACTIONS[f.status] || []).length > 0 && (
        <div className="flex flex-wrap gap-2" data-testid="od-actions">
          {ACTIONS[f.status].map((a) => (
            <Button key={a.to} onClick={() => start(a)} disabled={busy} data-testid={`vo-act-${a.to}`}
              className={`h-11 flex-1 rounded-full px-5 ${a.primary ? "hg-btn" : "border border-danger/40 bg-transparent text-danger hover:bg-danger/10"}`}>{t(a.key)}</Button>
          ))}
        </div>
      )}
    </div>
  );
}
