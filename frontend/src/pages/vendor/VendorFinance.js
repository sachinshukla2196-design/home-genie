import React, { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Download, Info, Landmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { Pager } from "@/components/Pager";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Field, Money, Pill, ResponsiveTable, StateBlock, downloadCsv, fmtDateTime, useAction, usePaged } from "@/components/vendor/kit";

const TABS = ["overview", "ledger", "settlements", "statements"];
const LEDGER_TYPES = ["", "SALE_COLLECTED", "SALE_REVERSAL", "REFUND", "ADJUSTMENT", "SETTLEMENT_PAID"];
const ST_TONE = { requested: "warn", approved: "info", paid: "ok", rejected: "muted", failed: "bad" };
const SELECT = "h-10 rounded-full bg-white/5 px-4 text-sm text-ink ring-1 ring-white/15";

function Overview() {
  const { t } = useI18n();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const load = () => { setError(null); API.get("/vendor/finance/summary").then(({ data }) => setD(data)).catch((e) => setError(apiError(e))); };
  useEffect(load, []);
  if (!d) return <StateBlock loading={!error} error={error} onRetry={load} testid="fin" />;
  const b = d.balances;
  const rows = [
    ["eligible", b.eligible_sales_paise, t("vx.fin.eligible"), t("vx.fin.eligibleHint")],
    ["reversals", b.sale_reversals_paise, t("vx.fin.reversals"), t("vx.fin.reversalsHint")],
    ["refunds", b.refunds_paise, t("vx.fin.refunds"), t("vx.fin.refundsHint")],
    ["adjustments", b.adjustments_paise, t("vx.fin.adjustments"), t("vx.fin.adjustmentsHint")],
    ["payable", b.vendor_payable_paise, t("vx.fin.payable"), t("vx.fin.payableHint")],
    ["settled", b.settled_paise, t("vx.fin.settled"), t("vx.fin.settledHint")],
    ["inprogress", b.settlement_in_progress_paise, t("vx.fin.inProgress"), t("vx.fin.inProgressHint")],
    ["pending", b.pending_settlement_paise, t("vx.fin.pending"), t("vx.fin.pendingHint")],
  ];
  return (
    <div className="space-y-4" data-testid="fin-overview">
      <div className="flex gap-2 rounded-2xl bg-hg-gold/10 p-4 text-sm text-ink ring-1 ring-hg-gold/30" role="note" data-testid="fin-provisional"><Info size={16} className="mt-0.5 shrink-0" aria-hidden /> <span>{b.provisional_note ? t("vx.fin.provisional") : ""} {!d.policy.active && d.policy.message}</span></div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {rows.map(([k, v, label, hint]) => (
          <div key={k} className="hg-card p-4" data-testid={`fin-${k}`}>
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted2">{label}</div>
            <Money paise={v} className={`mt-2 block text-2xl font-semibold ${v < 0 ? "text-danger" : "text-ink"}`} />
            <div className="mt-1 text-xs text-muted2">{hint}</div>
          </div>
        ))}
      </div>
      <SectionCard title={t("vx.fin.codTitle")} icon={Landmark} action={<Link to="/vendor/cod" className="text-sm font-medium text-hg-lavender">{t("vx.fin.openCod")}</Link>}>
        <div className="grid gap-3 sm:grid-cols-3">
          {[["delivered_awaiting_cash_paise", "vx.cod.awaitingCash"], ["overdue_paise", "vx.cod.overdue"], ["discrepancy_paise", "vx.cod.discrepancy"]].map(([k, l]) => <div key={k} className="hg-tile p-3"><div className="text-xs text-muted2">{t(l)}</div><Money paise={d.cod[k]} className="text-lg font-semibold text-ink" /></div>)}
        </div>
      </SectionCard>
      <p className="text-xs text-muted2">{t("vx.fin.disputeHelp")} <Link to="/vendor/support?new=settlement" className="text-hg-lavender underline">{t("vx.fin.reportIssue")}</Link></p>
    </div>
  );
}

function Ledger() {
  const { t, lang } = useI18n();
  const [type, setType] = useState("");
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/finance/ledger", { type: type || undefined }, 20);
  const columns = [
    { key: "at", label: t("vx.date"), render: (e) => <span className="text-xs text-muted2">{fmtDateTime(e.posted_at, lang)}</span> },
    { key: "type", label: t("vx.fin.type"), render: (e) => <Pill tone={e.amount_paise < 0 ? "bad" : "ok"}>{t(`vx.led.${e.type}`)}</Pill> },
    { key: "order", label: t("order.number"), render: (e) => e.meta?.order_number || (e.order_id ? e.order_id.slice(0, 8) : "—") },
    { key: "reason", label: t("vx.reason"), hideOnMobile: true, render: (e) => <span className="block max-w-[18rem] truncate text-muted2">{e.reason || "—"}</span> },
    { key: "amt", label: t("vx.amount"), align: "right", render: (e) => <Money paise={e.amount_paise} className={`font-semibold ${e.amount_paise < 0 ? "text-danger" : "text-hg-success"}`} /> },
  ];
  return (
    <div className="space-y-3" data-testid="fin-ledger">
      <div className="flex items-center gap-2"><label htmlFor="led-type" className="text-sm text-muted2">{t("vx.fin.type")}</label>
        <select id="led-type" className={SELECT} value={type} onChange={(e) => setType(e.target.value)} data-testid="led-type">{LEDGER_TYPES.map((x) => <option key={x} value={x}>{x ? t(`vx.led.${x}`) : t("vp.o.all")}</option>)}</select></div>
      <p className="text-xs text-muted2">{t("vx.fin.immutable")}</p>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="led" empty={items && items.length === 0} emptyIcon={Landmark} emptyTitle={t("vx.fin.noEntries")} emptyDesc={t("vx.fin.noEntriesDesc")}>
        <ResponsiveTable columns={columns} rows={items || []} rowTestid={(e) => `led-${e.id}`} caption={t("vx.fin.ledger")} />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="led-pager" />}
    </div>
  );
}

function Settlements() {
  const { t, lang } = useI18n();
  const { data, items, loading, error, page, setPage, reload } = usePaged("/vendor/finance/settlements", {}, 20);
  const columns = [
    { key: "no", label: t("vx.fin.number"), render: (s) => <span className="font-semibold text-ink">{s.number}</span> },
    { key: "at", label: t("vx.date"), render: (s) => <span className="text-xs text-muted2">{fmtDateTime(s.created_at, lang)}</span> },
    { key: "st", label: t("vx.status"), render: (s) => <Pill tone={ST_TONE[s.status]}>{t(`vx.set.${s.status}`)}</Pill> },
    { key: "ref", label: t("vx.fin.reference"), hideOnMobile: true, render: (s) => <span className="font-mono text-xs text-muted2">{s.reference || "—"}</span> },
    { key: "amt", label: t("vx.amount"), align: "right", render: (s) => <Money paise={s.amount_paise} className="font-semibold text-ink" /> },
  ];
  return (
    <div className="space-y-3" data-testid="fin-settlements">
      <p className="text-xs text-muted2" role="note">{t("vx.fin.settleReadonly")}</p>
      <StateBlock loading={loading} error={error} onRetry={reload} testid="set" empty={items && items.length === 0} emptyIcon={Landmark} emptyTitle={t("vx.fin.noSettlements")} emptyDesc={t("vx.fin.noSettlementsDesc")}>
        <ResponsiveTable columns={columns} rows={items || []} rowTestid={(s) => `set-${s.number}`} caption={t("vx.fin.settlements")} />
      </StateBlock>
      {data && <Pager page={page} pages={data.pages} total={data.total} onPage={setPage} t={t} testid="set-pager" />}
    </div>
  );
}

function Statements() {
  const { t } = useI18n();
  const [range, setRange] = useState({ from: "", to: "" });
  const [run, busy] = useAction();
  return (
    <SectionCard title={t("vx.fin.statement")} icon={Download} testid="fin-statements">
      <p className="mb-3 text-sm text-muted2">{t("vx.fin.statementHelp")}</p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("vx.from")} htmlFor="st-from"><input id="st-from" type="date" value={range.from} onChange={(e) => setRange({ ...range, from: e.target.value })} className="h-10 rounded-lg bg-white/5 px-2 text-ink ring-1 ring-white/15" data-testid="st-from" /></Field>
        <Field label={t("vx.to")} htmlFor="st-to"><input id="st-to" type="date" value={range.to} onChange={(e) => setRange({ ...range, to: e.target.value })} className="h-10 rounded-lg bg-white/5 px-2 text-ink ring-1 ring-white/15" data-testid="st-to" /></Field>
        <Button className="hg-btn h-10 rounded-full" disabled={busy} onClick={() => run(() => downloadCsv("/vendor/finance/statement.csv", "vendor-statement.csv", { date_from: range.from || undefined, date_to: range.to || undefined }))} data-testid="st-download"><Download size={15} /> {t("vx.fin.downloadCsv")}</Button>
      </div>
    </SectionCard>
  );
}

export default function VendorFinance() {
  const { t } = useI18n();
  const [sp, setSp] = useSearchParams();
  const tab = TABS.includes(sp.get("tab")) ? sp.get("tab") : "overview";
  return (
    <div className="space-y-5">
      <PageHeader title={t("vx.nav.finance")} subtitle={t("vx.fin.sub")} icon={Landmark} />
      <div className="flex flex-wrap gap-2" role="tablist">{TABS.map((k) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setSp(k === "overview" ? {} : { tab: k })} data-testid={`fin-tab-${k}`}
        className={`rounded-full px-4 py-2 text-sm font-medium ${tab === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{t(`vx.fin.tab.${k}`)}</button>)}</div>
      {tab === "overview" && <Overview />}{tab === "ledger" && <Ledger />}{tab === "settlements" && <Settlements />}{tab === "statements" && <Statements />}
    </div>
  );
}
