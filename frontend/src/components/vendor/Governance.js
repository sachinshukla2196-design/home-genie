import React, { useCallback, useEffect, useState } from "react";
import { FileCheck2, History, Landmark, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Field, Pill, StateBlock, fmtDateTime, useAction } from "@/components/vendor/kit";

const DOC_TYPES = ["pan", "gst", "bank_proof", "address_proof", "identity", "business_registration", "other"];
const DOC_TONE = { submitted: "warn", verified: "ok", rejected: "bad" };
const SELECT = "h-10 w-full rounded-lg bg-white/5 px-3 text-sm text-ink ring-1 ring-white/15";

function useGet(url) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const load = useCallback(() => { setError(null); API.get(url).then(({ data: d }) => setData(d)).catch((e) => setError(apiError(e))); }, [url]);
  useEffect(() => { load(); }, [load]);
  return [data, error, load];
}

function History_() {
  const { t, lang } = useI18n();
  const [h, error, load] = useGet("/vendor/me/history");
  return (
    <SectionCard title={t("vx.gov.history")} icon={History} testid="gov-history">
      <StateBlock loading={!h && !error} error={error} onRetry={load} rows={2} testid="gh">
        {h && (h.items.length === 0 ? <p className="text-sm text-muted2">{t("vx.gov.noHistory")}</p> : (
          <ol className="space-y-2 border-l border-white/15 pl-4">
            {h.items.map((e) => (
              <li key={e.id} className="text-sm" data-testid={`gov-h-${e.to}`}>
                <Pill tone={e.to === "approved" ? "ok" : ["rejected", "suspended"].includes(e.to) ? "bad" : "info"}>{t(`vp.st.${e.to}`)}</Pill>
                <span className="ml-2 text-xs text-muted2">{fmtDateTime(e.at, lang)}</span>
                {e.reason && <div className="mt-0.5 text-xs text-muted2">{e.reason}</div>}
              </li>))}
          </ol>))}
        {h && <p className="mt-3 text-xs text-muted2">{t("vx.gov.terms", { v: h.terms_version_accepted || "—", c: h.terms_version_current })}</p>}
      </StateBlock>
    </SectionCard>
  );
}

function Documents() {
  const { t } = useI18n();
  const [docs, error, load] = useGet("/vendor/documents");
  const [req, , loadReq] = useGet("/vendor/me/requirements");
  const [d, setD] = useState({ type: "pan", url: "", note: "" });
  const [run, busy] = useAction();
  const add = () => run(async () => { await API.post("/vendor/documents", { ...d, url: d.url.trim() }); setD({ ...d, url: "", note: "" }); load(); loadReq(); }, { success: t("vx.gov.docAdded") });
  const remove = (x) => run(async () => { await API.delete(`/vendor/documents/${x.id}`); load(); loadReq(); });
  return (
    <SectionCard title={t("vx.gov.documents")} icon={FileCheck2} testid="gov-documents">
      {req && <p className={`mb-3 rounded-xl p-3 text-xs ${req.configured ? "bg-hg-gold/10 text-ink" : "bg-white/5 text-muted2"}`} role="note" data-testid="gov-requirements">
        {req.configured ? t("vx.gov.requiredList", { list: req.required.map((k) => t(`vx.gov.doc.${k}`)).join(", "), missing: req.missing.length ? req.missing.map((k) => t(`vx.gov.doc.${k}`)).join(", ") : t("vx.gov.none") }) : t("vx.gov.notDecided")}</p>}
      <StateBlock loading={!docs && !error} error={error} onRetry={load} rows={1} testid="gd">
        <ul className="space-y-2">{(docs?.items || []).map((x) => (
          <li key={x.id} className="hg-tile flex flex-wrap items-center gap-2 p-2.5 text-sm" data-testid={`gov-doc-${x.type}`}>
            <Pill tone={DOC_TONE[x.status]}>{t(`vx.docstatus.${x.status}`)}</Pill><span className="font-medium text-ink">{t(`vx.gov.doc.${x.type}`)}</span>
            <span className="min-w-0 flex-1 truncate text-xs text-muted2">{x.review_note || x.url}</span>
            {x.status !== "verified" && <Button variant="ghost" className="h-8 text-danger" onClick={() => remove(x)} disabled={busy} aria-label={t("vx.remove")}><Trash2 size={14} /></Button>}
          </li>))}
          {docs && docs.items.length === 0 && <li className="text-sm text-muted2">{t("vx.gov.noDocs")}</li>}</ul>
      </StateBlock>
      <div className="mt-3 grid gap-2 sm:grid-cols-6">
        <select aria-label={t("vx.pf.docType")} className={`${SELECT} sm:col-span-2`} value={d.type} onChange={(e) => setD({ ...d, type: e.target.value })} data-testid="gov-doc-type">{DOC_TYPES.map((k) => <option key={k} value={k}>{t(`vx.gov.doc.${k}`)}</option>)}</select>
        <Input aria-label={t("vx.pf.docUrl")} placeholder="https://…" className="sm:col-span-3" value={d.url} onChange={(e) => setD({ ...d, url: e.target.value })} data-testid="gov-doc-url" />
        <Button className="hg-btn h-10 rounded-full" onClick={add} disabled={busy || !d.url.trim()} data-testid="gov-doc-add"><Plus size={14} /> {t("vx.add")}</Button>
      </div>
      <p className="mt-2 text-xs text-muted2">{t("vx.gov.docsPrivacy")}</p>
    </SectionCard>
  );
}

function Verification() {
  const { t } = useI18n();
  const [v, error] = useGet("/vendor/me/verification");
  return (
    <SectionCard title={t("vx.gov.verification")} icon={ShieldCheck} testid="gov-verification">
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      {v && <><div className="flex flex-wrap gap-2"><Pill tone={v.mobile.verified ? "ok" : "muted"}>{t("vx.gov.mobile")}: {v.mobile.verified ? t("vx.gov.verified") : t("vx.gov.notVerified")}</Pill><Pill tone={v.email.verified ? "ok" : "muted"}>{t("vx.gov.email")}: {v.email.verified ? t("vx.gov.verified") : t("vx.gov.notVerified")}</Pill></div>
        {v.note && <p className="mt-2 text-xs text-muted2" data-testid="gov-verification-note">{t("vx.gov.verifyNote")}</p>}</>}
    </SectionCard>
  );
}

function BankChange() {
  const { t, lang } = useI18n();
  const [list, , load] = useGet("/vendor/me/bank-change");
  const [f, setF] = useState({ bank_account_name: "", bank_account: "", ifsc: "", reason: "" });
  const [run, busy] = useAction();
  const ok = f.bank_account_name.trim().length >= 2 && /^[0-9A-Za-z]{6,24}$/.test(f.bank_account) && /^[A-Za-z]{4}0[A-Za-z0-9]{6}$/.test(f.ifsc) && f.reason.trim().length >= 5;
  const submit = () => run(async () => { await API.post("/vendor/me/bank-change", f); setF({ bank_account_name: "", bank_account: "", ifsc: "", reason: "" }); load(); }, { success: t("vx.gov.bankSent") });
  const pending = list?.items?.some((x) => x.status === "pending");
  return (
    <SectionCard title={t("vx.gov.bankChange")} icon={Landmark} testid="gov-bank">
      <p className="mb-3 text-xs text-muted2">{t("vx.gov.bankHelp")}</p>
      {(list?.items || []).map((x) => <div key={x.id} className="hg-tile mb-2 flex flex-wrap items-center gap-2 p-2.5 text-sm"><Pill tone={x.status === "approved" ? "ok" : x.status === "rejected" ? "bad" : "warn"}>{t(`vx.set.${x.status === "pending" ? "requested" : x.status}`)}</Pill><span className="font-mono text-xs text-ink">{x.payload.bank_account} · {x.payload.ifsc}</span><span className="text-xs text-muted2">{fmtDateTime(x.created_at, lang)}</span>{x.admin_note && <span className="w-full text-xs text-muted2">{x.admin_note}</span>}</div>)}
      {!pending && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("vp.bankName")} htmlFor="bc-name"><Input id="bc-name" value={f.bank_account_name} onChange={(e) => setF({ ...f, bank_account_name: e.target.value })} data-testid="bc-name" /></Field>
          <Field label={t("vp.bankAccount")} htmlFor="bc-acc"><Input id="bc-acc" value={f.bank_account} inputMode="numeric" autoComplete="off" onChange={(e) => setF({ ...f, bank_account: e.target.value })} data-testid="bc-acc" /></Field>
          <Field label="IFSC" htmlFor="bc-ifsc"><Input id="bc-ifsc" value={f.ifsc} className="uppercase" onChange={(e) => setF({ ...f, ifsc: e.target.value })} data-testid="bc-ifsc" /></Field>
          <Field label={t("vx.reason")} htmlFor="bc-reason"><Input id="bc-reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} data-testid="bc-reason" /></Field>
          <div className="sm:col-span-2"><Button className="hg-btn h-10 rounded-full" disabled={busy || !ok} onClick={submit} data-testid="bc-submit">{t("vx.gov.requestChange")}</Button></div>
        </div>)}
    </SectionCard>
  );
}

export function Governance({ approved }) {
  return (
    <div className="space-y-4" data-testid="governance">
      <History_ />
      <Documents />
      <Verification />
      {approved && <BankChange />}
    </div>
  );
}
