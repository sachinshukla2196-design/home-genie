import React, { useCallback, useEffect, useState } from "react";
import { Award } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { Pill, StateBlock, fmtDate, useAction } from "@/components/vendor/kit";

const FINANCE_ROLES = ["super_admin", "accounts_admin"];
const METRICS = ["orders", "order_value_paise", "delivered_rate", "cancellation_rate", "return_rate"];
const SELECT = "h-10 rounded-xl bg-white/5 px-3 text-sm text-ink ring-1 ring-white/15";
const TONE = { proposed: "info", review_requested: "warn", approved: "ok", rejected: "bad", expired: "muted" };
const EMPTY_PROG = { key: "", title: "", review_days: "30", benefit_text: "", criteria: [{ metric: "orders", value: "1" }] };

const shown = (metric, v) => (v === null || v === undefined ? "—" : metric === "order_value_paise" ? `₹${(v / 100).toLocaleString("en-IN")}` : metric.endsWith("_rate") ? `${v}%` : v);

/** Admin: advancement-benefit programmes, eligibility over the review window, and proposals. Approval needs a different admin. */
export default function AdminBenefits() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const canManage = FINANCE_ROLES.includes(user?.role);
  const [programmes, setProgrammes] = useState(null);
  const [sel, setSel] = useState(null);
  const [eligible, setEligible] = useState(null);
  const [proposals, setProposals] = useState(null);
  const [error, setError] = useState(null);
  const [prog, setProg] = useState(EMPTY_PROG);
  const [decide, setDecide] = useState({});
  const [run, busy] = useAction();

  const loadProgrammes = useCallback(() => API.get("/admin/benefits/programmes").then(({ data }) => setProgrammes(data.programmes)).catch((e) => setError(apiError(e))), []);
  const loadProposals = useCallback(() => API.get("/admin/benefits/proposals").then(({ data }) => setProposals(data.proposals)).catch((e) => setError(apiError(e))), []);
  useEffect(() => { loadProgrammes(); loadProposals(); }, [loadProgrammes, loadProposals]);
  useEffect(() => {
    if (!sel) return;
    setEligible(null);
    API.get("/admin/benefits/eligibility", { params: { programme_id: sel.id } }).then(({ data }) => setEligible(data)).catch((e) => setError(apiError(e)));
  }, [sel]);

  const createProgramme = (e) => {
    e.preventDefault();
    const body = { ...prog, review_days: Number(prog.review_days), criteria: prog.criteria.map((c) => ({ metric: c.metric, value: Number(c.value) })) };
    run(() => API.post("/admin/benefits/programmes", body), { success: t("bn.created") }).then((r) => { if (r) { setProg(EMPTY_PROG); loadProgrammes(); } });
  };
  const propose = (v) => run(() => API.post("/admin/benefits/proposals", { vendor_id: v.vendor_id, programme_id: sel.id }), { success: t("bn.proposed") })
    .then((r) => { if (r) { loadProposals(); setSel({ ...sel }); } });
  const act = (g, action) => {
    const d = decide[g.id] || {};
    const body = { action, note: d.note || "" };
    if (action === "approve") { body.effective_from = d.effective_from || undefined; body.expires_at = d.expires_at || undefined; }
    run(() => API.post(`/admin/benefits/proposals/${g.id}/decide`, body), { success: t(`bn.done.${action}`) })
      .then((r) => { if (r) { loadProposals(); if (sel) setSel({ ...sel }); } });
  };

  if (error && !programmes) return <StateBlock error={error} testid="bn" />;
  if (!programmes || !proposals) return <StateBlock loading rows={3} testid="bn" />;

  return (
    <div className="space-y-6" data-testid="admin-benefits">
      <PageHeader title={t("bn.title")} subtitle={t("bn.sub")} icon={Award} />
      {!canManage && <p className="rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note">{t("bn.readonly")}</p>}

      <SectionCard title={t("bn.programmes")} testid="bn-programmes">
        {programmes.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="bn-prog-empty">{t("bn.noProgrammes")}</p> : (
          <ul className="grid gap-2 sm:grid-cols-2">
            {programmes.map((p) => (
              <li key={p.id}>
                <button onClick={() => setSel(p)} aria-current={sel?.id === p.id ? "true" : undefined} data-testid={`bn-prog-${p.key}`}
                  className={`hg-tile w-full p-3 text-left text-sm ${sel?.id === p.id ? "ring-2 ring-hg-violet" : ""}`}>
                  <span className="block font-semibold text-ink">{p.title}</span>
                  <span className="block text-xs text-muted2">{p.key} · {t("bn.reviewDays", { n: p.review_days })}</span>
                  <span className="mt-1 block text-xs text-muted2">{p.criteria.map((c) => `${t(`bn.m.${c.metric}`)} ${c.metric.endsWith("cancellation_rate") || c.metric.endsWith("return_rate") ? "≤" : "≥"} ${c.value}`).join(" · ")}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {canManage && (
          <form onSubmit={createProgramme} noValidate className="mt-5 grid gap-3 sm:grid-cols-2" data-testid="bn-form">
            <Input placeholder={t("bn.key")} value={prog.key} onChange={(e) => setProg({ ...prog, key: e.target.value })} data-testid="bn-key" />
            <Input placeholder={t("bn.titleField")} value={prog.title} onChange={(e) => setProg({ ...prog, title: e.target.value })} data-testid="bn-title" />
            <Input type="number" min="1" max="365" placeholder={t("bn.reviewField")} value={prog.review_days} onChange={(e) => setProg({ ...prog, review_days: e.target.value })} data-testid="bn-days" />
            <Input placeholder={t("bn.benefitText")} value={prog.benefit_text} onChange={(e) => setProg({ ...prog, benefit_text: e.target.value })} data-testid="bn-text" />
            {prog.criteria.map((c, i) => (
              <div key={i} className="flex gap-2 sm:col-span-2">
                <select aria-label={t("bn.metric")} className={`${SELECT} flex-1`} value={c.metric} onChange={(e) => setProg({ ...prog, criteria: prog.criteria.map((x, j) => (j === i ? { ...x, metric: e.target.value } : x)) })}>
                  {METRICS.map((m) => <option key={m} value={m}>{t(`bn.m.${m}`)}</option>)}
                </select>
                <Input type="number" min="0" step="0.1" aria-label={t("bn.threshold")} value={c.value} onChange={(e) => setProg({ ...prog, criteria: prog.criteria.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)) })} className="w-32" />
                {prog.criteria.length > 1 && <Button variant="outline" className="h-10 rounded-full" onClick={() => setProg({ ...prog, criteria: prog.criteria.filter((_, j) => j !== i) })}>{t("bn.remove")}</Button>}
              </div>
            ))}
            <div className="flex flex-wrap gap-2 sm:col-span-2">
              {prog.criteria.length < 8 && <Button variant="outline" className="h-10 rounded-full" onClick={() => setProg({ ...prog, criteria: [...prog.criteria, { metric: "orders", value: "1" }] })}>{t("bn.addCriterion")}</Button>}
              <Button type="submit" disabled={busy} className="hg-btn h-10 rounded-full px-6" data-testid="bn-submit">{t("bn.create")}</Button>
            </div>
          </form>
        )}
      </SectionCard>

      {sel && (
        <SectionCard title={t("bn.eligibleFor", { name: sel.title })} testid="bn-eligible">
          {!eligible ? <StateBlock loading rows={2} testid="bn-eligible" /> : (
            <>
              <p className="mb-3 text-xs text-muted2">{t("bn.window", { from: fmtDate(eligible.review_from, lang), to: fmtDate(eligible.review_to, lang) })}</p>
              {eligible.vendors.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2">{t("bn.noVendors")}</p> : (
                <div className="space-y-2">
                  {eligible.vendors.map((v) => (
                    <div key={v.vendor_id} className="hg-tile p-3" data-testid={`bn-vendor-${v.vendor_code}`}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-ink">{v.business_name} <span className="text-xs text-muted2">{v.vendor_code}</span></span>
                        <span className="flex items-center gap-2">
                          <Pill tone={v.eligible ? "ok" : "muted"}>{v.eligible ? t("bn.eligible") : t("bn.notEligible")}</Pill>
                          {v.open_proposal ? <Pill tone="info">{t(`bn.st.${v.open_proposal.status}`)}</Pill>
                            : canManage && <Button size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => propose(v)} data-testid={`bn-propose-${v.vendor_code}`}>{t("bn.propose")}</Button>}
                        </span>
                      </div>
                      <ul className="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                        {v.criteria.map((c) => (
                          <li key={c.metric} className={c.met ? "text-hg-success" : "text-danger"}>
                            {c.met ? "✓" : "✗"} {t(`bn.m.${c.metric}`)}: {shown(c.metric, c.measured)} ({c.rule === "min" ? "≥" : "≤"} {c.required}){c.reason ? ` — ${t("bn.noData")}` : ""}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </SectionCard>
      )}

      <SectionCard title={t("bn.proposals")} testid="bn-proposals">
        {proposals.length === 0 ? <p className="hg-tile p-5 text-center text-sm text-muted2" data-testid="bn-proposals-empty">{t("bn.noProposals")}</p> : (
          <div className="space-y-3">
            {proposals.map((g) => {
              const own = g.proposed_by === user?.id;
              return (
                <div key={g.id} className="hg-tile p-3 text-sm" data-testid={`bn-grant-${g.status}`}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium text-ink">{g.business_name} · {g.programme_key}</span>
                    <Pill tone={TONE[g.status] || "muted"}>{t(`bn.st.${g.status}`)}</Pill>
                  </div>
                  <p className="mt-1 text-xs text-muted2">{t("bn.proposedOn", { d: fmtDate(g.proposed_at, lang) })}{g.effective_from ? ` · ${t("bn.effective", { d: fmtDate(g.effective_from, lang) })}` : ""}{g.expires_at_date ? ` · ${t("bn.expires", { d: fmtDate(g.expires_at_date, lang) })}` : ""}</p>
                  {g.decision_note && <p className="mt-1 text-xs text-ink">{g.decision_note}</p>}
                  {canManage && ["proposed", "review_requested"].includes(g.status) && (
                    <div className="mt-3 flex flex-wrap items-end gap-2">
                      <Input placeholder={t("bn.reasonField")} value={(decide[g.id] || {}).note || ""} onChange={(e) => setDecide({ ...decide, [g.id]: { ...(decide[g.id] || {}), note: e.target.value } })} className="h-9 w-56 text-xs" />
                      <Input type="date" aria-label={t("bn.effectiveField")} value={(decide[g.id] || {}).effective_from || ""} onChange={(e) => setDecide({ ...decide, [g.id]: { ...(decide[g.id] || {}), effective_from: e.target.value } })} className="h-9 w-40 text-xs" />
                      <Input type="date" aria-label={t("bn.expiryField")} value={(decide[g.id] || {}).expires_at || ""} onChange={(e) => setDecide({ ...decide, [g.id]: { ...(decide[g.id] || {}), expires_at: e.target.value } })} className="h-9 w-40 text-xs" />
                      {own
                        ? <span className="text-xs text-muted2" data-testid={`bn-own-${g.id}`}>{t("bn.ownApprove")}</span>
                        : <Button size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => act(g, "approve")} data-testid={`bn-approve-${g.id}`}>{t("bn.approve")}</Button>}
                      <Button size="sm" variant="outline" className="h-9 rounded-full" disabled={busy} onClick={() => act(g, "request_review")}>{t("bn.requestReview")}</Button>
                      <Button size="sm" variant="outline" className="h-9 rounded-full border-danger/40 text-danger" disabled={busy} onClick={() => act(g, "reject")}>{t("bn.reject")}</Button>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
