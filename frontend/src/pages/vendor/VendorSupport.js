import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { LifeBuoy, Plus, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { PageHeader } from "@/components/PageHeader";
import { Pager } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Field, Pill, ResponsiveTable, StateBlock, fmtDateTime, useAction, usePaged } from "@/components/vendor/kit";
import { ImageInput } from "@/components/vendor/ImageInput";

const CATEGORIES = ["order", "payment", "product", "settlement", "return", "kyc", "technical", "other"];
const RELATED = ["", "order", "product", "settlement", "return"];
const TONE = { open: "warn", in_progress: "info", waiting_vendor: "bad", resolved: "ok", closed: "muted" };
const SELECT = "h-10 w-full rounded-lg bg-white/5 px-3 text-sm text-ink ring-1 ring-white/15";

function NewTicket({ initial, onClose, onCreated }) {
  const { t } = useI18n();
  const [f, setF] = useState({ category: initial || "order", priority: "normal", subject: "", body: "", related_type: "", related_id: "", attachments: [] });
  const [run, busy] = useAction();
  const urgent = ["payment", "settlement"].includes(f.category);
  const valid = f.subject.trim().length >= 3 && f.body.trim().length >= 5 && (!!f.related_type === !!f.related_id.trim());
  const send = () => run(async () => {
    const body = { ...f, related_type: f.related_type || undefined, related_id: f.related_id.trim() || undefined };
    const { data } = await API.post("/vendor/support/tickets", body);
    onCreated(data);
  }, { success: t("vx.sup.created") });
  return (
    <div className="space-y-3" data-testid="new-ticket">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label={t("vx.sup.category")} htmlFor="tk-cat"><select id="tk-cat" className={SELECT} value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} data-testid="tk-category">{CATEGORIES.map((c) => <option key={c} value={c}>{t(`vx.sup.cat.${c}`)}</option>)}</select></Field>
        <Field label={t("vx.sup.priority")} htmlFor="tk-pri" hint={urgent ? t("vx.sup.urgentHint") : undefined}><select id="tk-pri" className={SELECT} value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })} data-testid="tk-priority">{["low", "normal", "high"].map((p) => <option key={p} value={p}>{t(`vx.priority.${p}`)}</option>)}</select></Field>
        <Field label={t("vx.sup.related")} htmlFor="tk-rel"><select id="tk-rel" className={SELECT} value={f.related_type} onChange={(e) => setF({ ...f, related_type: e.target.value })} data-testid="tk-related-type">{RELATED.map((r) => <option key={r} value={r}>{r ? t(`vx.sup.rel.${r}`) : t("vx.sup.none")}</option>)}</select></Field>
        <Field label={t("vx.sup.relatedId")} htmlFor="tk-rid" hint={t("vx.sup.relatedIdHint")}><Input id="tk-rid" value={f.related_id} disabled={!f.related_type} onChange={(e) => setF({ ...f, related_id: e.target.value })} data-testid="tk-related-id" /></Field>
      </div>
      <Field label={t("vx.sup.subject")} htmlFor="tk-sub"><Input id="tk-sub" value={f.subject} maxLength={120} onChange={(e) => setF({ ...f, subject: e.target.value })} data-testid="tk-subject" /></Field>
      <Field label={t("vx.sup.message")} htmlFor="tk-body"><Textarea id="tk-body" rows={5} value={f.body} maxLength={3000} onChange={(e) => setF({ ...f, body: e.target.value })} data-testid="tk-body" /></Field>
      <div><div className="mb-1 text-sm font-medium text-ink">{t("vx.sup.attachments")}</div><ImageInput value={f.attachments} onChange={(v) => setF({ ...f, attachments: v })} max={5} testid="tk-att" /></div>
      <div className="flex justify-end gap-2"><Button variant="outline" className="h-10 rounded-full" onClick={onClose} disabled={busy}>{t("vx.cancel")}</Button><Button className="hg-btn h-10 rounded-full" onClick={send} disabled={busy || !valid} data-testid="tk-send"><Send size={14} /> {t("vx.sup.send")}</Button></div>
    </div>
  );
}

function TicketView({ id, onChanged }) {
  const { t, lang } = useI18n();
  const [tk, setTk] = useState(null);
  const [error, setError] = useState(null);
  const [text, setText] = useState("");
  const [run, busy] = useAction();
  const load = useCallback(() => { setError(null); API.get(`/vendor/support/tickets/${id}`).then(({ data }) => setTk(data)).catch((e) => setError(apiError(e))); }, [id]);
  useEffect(() => { setTk(null); load(); }, [load]);
  if (!tk) return <StateBlock loading={!error} error={error} onRetry={load} rows={2} testid="tv" />;
  const reply = () => run(async () => { await API.post(`/vendor/support/tickets/${id}/reply`, { body: text, attachments: [] }); setText(""); load(); onChanged(); });
  return (
    <div className="space-y-3" data-testid="ticket-view">
      <div className="flex flex-wrap items-center gap-2"><span className="font-display text-lg font-semibold text-ink">{tk.number}</span><Pill tone={TONE[tk.status]} testid="tv-status">{t(`vx.sup.st.${tk.status}`)}</Pill>{tk.urgent && <Pill tone="bad">{t("vx.sup.urgent")}</Pill>}<Pill tone="muted">{t(`vx.sup.cat.${tk.category}`)}</Pill></div>
      <h3 className="text-base font-medium text-ink">{tk.subject}</h3>
      <ul className="max-h-72 space-y-2 overflow-y-auto" aria-label={t("vx.sup.conversation")} data-testid="tv-messages">{tk.messages.map((m) => (
        <li key={m.id} className={`rounded-2xl p-3 text-sm ${m.role === "admin" ? "bg-hg-violet/15" : "bg-white/5"}`}><div className="mb-1 text-[11px] font-semibold text-muted2">{m.role === "admin" ? t("vx.sup.team") : t("vx.sup.you")} · {fmtDateTime(m.at, lang)}</div><p className="whitespace-pre-wrap text-ink">{m.body}</p>
          {m.attachments?.length > 0 && <div className="mt-2 flex gap-2">{m.attachments.map((u) => <a key={u} href={u} target="_blank" rel="noopener noreferrer"><img src={u} alt={t("vx.sup.attachment")} className="h-14 w-14 rounded-lg object-cover" loading="lazy" /></a>)}</div>}</li>))}</ul>
      {tk.resolution && <p className="rounded-xl bg-hg-success/10 p-3 text-xs text-ink ring-1 ring-hg-success/25" data-testid="tv-resolution"><b>{t("vx.sup.resolution")}:</b> {tk.resolution.note}</p>}
      {tk.status === "closed" ? <p className="text-sm text-muted2" role="note" data-testid="tv-closed">{t("vx.sup.closedNote")}</p> : (
        <div className="flex gap-2"><Textarea rows={2} value={text} onChange={(e) => setText(e.target.value)} aria-label={t("vx.sup.reply")} placeholder={t("vx.sup.reply")} data-testid="tv-reply" /><Button className="hg-btn h-auto rounded-2xl px-4" disabled={busy || text.trim().length < 2} onClick={reply} data-testid="tv-send" aria-label={t("vx.sup.send")}><Send size={16} /></Button></div>)}
    </div>
  );
}

export default function VendorSupport() {
  const { t, lang } = useI18n();
  const [sp, setSp] = useSearchParams();
  const [status, setStatus] = useState("");
  const open = sp.get("open");
  const creating = sp.get("new");
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/support/tickets", { status: status || undefined }, 15);
  const setParam = (k, v) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); setSp(n, { replace: true }); };
  const columns = [
    { key: "n", label: t("vx.sup.number"), render: (r) => <span className="font-semibold text-ink">{r.number}</span> },
    { key: "s", label: t("vx.sup.subject"), render: (r) => <span className="block max-w-[20rem] truncate text-ink">{r.subject}</span> },
    { key: "c", label: t("vx.sup.category"), hideOnMobile: true, render: (r) => t(`vx.sup.cat.${r.category}`) },
    { key: "u", label: t("vx.updated"), hideOnMobile: true, render: (r) => <span className="text-xs text-muted2">{fmtDateTime(r.updated_at, lang)}</span> },
    { key: "st", label: t("vx.status"), render: (r) => <span className="inline-flex gap-1"><Pill tone={TONE[r.status]}>{t(`vx.sup.st.${r.status}`)}</Pill>{r.urgent && <Pill tone="bad">{t("vx.sup.urgent")}</Pill>}</span> },
  ];
  return (
    <div className="space-y-5">
      <PageHeader title={t("vx.nav.support")} subtitle={t("vx.sup.sub")} icon={LifeBuoy} actions={<Button className="hg-btn h-11 rounded-full px-5" onClick={() => setParam("new", "order")} data-testid="sup-new"><Plus size={16} /> {t("vx.sup.new")}</Button>} />
      <div className="flex flex-wrap gap-2" role="tablist">{["", "open", "in_progress", "waiting_vendor", "resolved", "closed"].map((k) => <button key={k || "all"} role="tab" aria-selected={status === k} onClick={() => setStatus(k)} data-testid={`sup-tab-${k || "all"}`} className={`rounded-full px-4 py-2 text-sm font-medium ${status === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{k ? t(`vx.sup.st.${k}`) : t("vp.o.all")}</button>)}</div>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="sup" empty={items && items.length === 0} emptyIcon={LifeBuoy} emptyTitle={t("vx.sup.empty")} emptyDesc={t("vx.sup.emptyDesc")} ctaLabel={t("vx.sup.new")} onCta={() => setParam("new", "order")}>
        <ResponsiveTable columns={columns} rows={items || []} onRowClick={(r) => setParam("open", r.id)} rowTestid={(r) => `sup-row-${r.number}`} caption={t("vx.nav.support")} />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="sup-pager" />}
      <Dialog open={!!creating} onOpenChange={(v) => !v && setParam("new", "")}>
        <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="sup-new-dialog"><DialogHeader><DialogTitle>{t("vx.sup.new")}</DialogTitle><DialogDescription>{t("vx.sup.newHelp")}</DialogDescription></DialogHeader>
          {creating && <NewTicket initial={CATEGORIES.includes(creating) ? creating : "other"} onClose={() => setParam("new", "")} onCreated={(tk) => { const n = new URLSearchParams(); n.set("open", tk.id); setSp(n, { replace: true }); reload(); }} />}</DialogContent>
      </Dialog>
      <Dialog open={!!open} onOpenChange={(v) => !v && setParam("open", "")}>
        <DialogContent className="max-h-[90vh] max-w-xl overflow-y-auto rounded-3xl" data-testid="sup-dialog"><DialogHeader><DialogTitle className="sr-only">{t("vx.nav.support")}</DialogTitle><DialogDescription className="sr-only">{t("vx.sup.sub")}</DialogDescription></DialogHeader>
          {open && <TicketView id={open} onChanged={reload} />}</DialogContent>
      </Dialog>
    </div>
  );
}
