import React, { useCallback, useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Pill, StateBlock, fmtDate, inrP, useAction } from "@/components/vendor/kit";

/** Read-only commercial terms for this vendor. Approved versions can be accepted; nothing here can be edited by the vendor. */
export default function VendorTerms() {
  const { t, lang } = useI18n();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [run, busy] = useAction();
  const load = useCallback(() => {
    setError(null);
    API.get("/vendor/finance/terms").then(({ data }) => setD(data)).catch((e) => setError(apiError(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  if (!d) return <StateBlock loading={!error} error={error} onRetry={load} rows={3} testid="terms" />;

  const cur = d.current;
  // The example uses the vendor's own terms and an illustrative sale of Rs 1,000; it is arithmetic on the agreement, not a forecast.
  const sample = 100000;
  const commission = cur ? Math.min(Math.round(sample * cur.commission_pct / 100), sample) + cur.fixed_fee_paise : null;

  return (
    <div className="space-y-6" data-testid="vendor-terms">
      <PageHeader title={t("vt.title")} subtitle={t("vt.sub")} icon={FileText} />
      <SectionCard title={t("vt.current")} testid="terms-current">
        {!cur ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="terms-none">{t("vt.none")}</p> : (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Field label={t("vt.version")} value={`v${cur.version}`} />
              <Field label={t("vt.commission")} value={`${cur.commission_pct}%`} />
              <Field label={t("vt.fee")} value={inrP(cur.fixed_fee_paise)} />
              <Field label={t("vt.schedule")} value={t(`aa.sched.${cur.settlement_schedule}`)} />
            </div>
            <p className="text-sm text-muted2" data-testid="terms-effective">{t("vt.effectiveFrom", { d: fmtDate(cur.effective_from, lang) })}</p>
            <p className="rounded-xl bg-white/5 p-3 text-sm text-ink" data-testid="terms-example">
              {t("vt.example", { sale: inrP(sample), total: inrP(commission) })}
            </p>
            {cur.notes && <p className="text-sm text-ink">{cur.notes}</p>}
            <p className="text-xs text-muted2">{cur.accepted_at ? t("vt.acceptedOn", { d: fmtDate(cur.accepted_at, lang) }) : t("vt.notAccepted")}</p>
          </div>
        )}
      </SectionCard>

      <SectionCard title={t("vt.history")} testid="terms-history">
        {d.agreements.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="terms-history-empty">{t("vt.noHistory")}</p> : (
          <ul className="space-y-2">
            {d.agreements.map((a) => (
              <li key={a.id} className="hg-tile flex flex-wrap items-center justify-between gap-3 p-3 text-sm" data-testid={`terms-v-${a.version}`}>
                <span className="text-ink">v{a.version} · {a.commission_pct}% · {inrP(a.fixed_fee_paise)} · {fmtDate(a.effective_from, lang)}</span>
                <span className="flex items-center gap-2">
                  {a.is_current && <Pill tone="ok">{t("vt.inForce")}</Pill>}
                  {a.accepted_at ? <Pill tone="info">{t("vt.accepted")}</Pill>
                    : <Button size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => run(() => API.post(`/vendor/finance/terms/${a.id}/accept`), { success: t("vt.acceptedMsg") }).then((r) => { if (r) load(); })} data-testid={`terms-accept-${a.version}`}>{t("vt.accept")}</Button>}
                </span>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

function Field({ label, value }) {
  return (
    <div className="hg-tile p-3">
      <div className="text-xs text-muted2">{label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-ink">{value}</div>
    </div>
  );
}
