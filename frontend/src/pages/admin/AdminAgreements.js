import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Handshake } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { Pill, StateBlock, fmtDate, inrP, useAction } from "@/components/vendor/kit";

const FINANCE_ROLES = ["super_admin", "accounts_admin"];
const SCHEDULES = ["weekly", "biweekly", "monthly", "on_request"];
const SELECT = "h-10 rounded-xl bg-white/5 px-3 text-sm text-ink ring-1 ring-white/15";
const EMPTY = { commission_pct: "", fee: "0", settlement_schedule: "monthly", effective_from: "", notes: "" };

/** Admin: vendor commercial agreements. Versions are immutable once approved; a change is a new draft. Approval needs a different admin. */
export default function AdminAgreements() {
  const { t, lang } = useI18n();
  const { user } = useAuth();
  const canManage = FINANCE_ROLES.includes(user?.role);
  const [vendors, setVendors] = useState(null);
  const [error, setError] = useState(null);
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(null);
  const [rows, setRows] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [tried, setTried] = useState(false);
  const [run, busy] = useAction();

  useEffect(() => {
    API.get("/admin/vendors").then(({ data }) => setVendors(data)).catch((e) => setError(apiError(e)));
  }, []);
  const loadAgreements = useCallback((vid) => {
    setRows(null);
    API.get(`/admin/finance/vendors/${vid}/agreements`).then(({ data }) => setRows(data.agreements)).catch((e) => setError(apiError(e)));
  }, []);
  useEffect(() => { if (sel) loadAgreements(sel.id); }, [sel, loadAgreements]);

  const pct = Number(form.commission_pct);
  const problems = {
    pct: form.commission_pct !== "" && pct >= 0 && pct <= 100 ? null : "aa.errPct",
    fee: Number(form.fee) >= 0 ? null : "aa.errFee",
    date: /^\d{4}-\d{2}-\d{2}$/.test(form.effective_from) ? null : "aa.errDate",
  };
  const valid = Object.values(problems).every((p) => !p);

  const create = (e) => {
    e.preventDefault();
    setTried(true);
    if (!valid || !canManage) return;
    run(() => API.post(`/admin/finance/vendors/${sel.id}/agreements`, {
      commission_pct: pct, fixed_fee_paise: Math.round(Number(form.fee) * 100), settlement_schedule: form.settlement_schedule,
      effective_from: form.effective_from, notes: form.notes,
    }), { success: t("aa.created") }).then((r) => { if (r) { setForm(EMPTY); setTried(false); loadAgreements(sel.id); } });
  };
  const approve = (a) => run(() => API.post(`/admin/finance/agreements/${a.id}/approve`), { success: t("aa.approvedMsg") })
    .then((r) => { if (r) loadAgreements(sel.id); });

  if (error && !vendors) return <StateBlock error={error} testid="aa" />;
  if (!vendors) return <StateBlock loading rows={2} testid="aa" />;

  const list = vendors.filter((v) => `${v.business_name} ${v.vendor_code}`.toLowerCase().includes(q.trim().toLowerCase()));

  return (
    <div className="space-y-6" data-testid="admin-agreements">
      <PageHeader title={t("aa.title")} subtitle={t("aa.sub")} icon={Handshake} />
      {!canManage && <p className="rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note">{t("aa.readonly")}</p>}
      <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
        <SectionCard title={t("aa.vendors")} testid="aa-vendors">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("aa.search")} className="mb-3" data-testid="aa-search" />
          {list.length === 0 ? <p className="text-sm text-muted2">{t("aa.noVendors")}</p> : (
            <ul className="space-y-1" data-testid="aa-vendor-list">
              {list.map((v) => (
                <li key={v.id}>
                  <button onClick={() => setSel(v)} aria-current={sel?.id === v.id ? "true" : undefined} data-testid={`aa-pick-${v.vendor_code}`}
                    className={`w-full rounded-xl px-3 py-2 text-left text-sm ${sel?.id === v.id ? "bg-brand-50 text-ink" : "text-muted2 hover:bg-brand-50/60"}`}>
                    <span className="block truncate font-medium text-ink">{v.business_name}</span>
                    <span className="text-xs">{v.vendor_code} · {v.status}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </SectionCard>

        <div className="space-y-4">
          {!sel && <p className="hg-tile p-6 text-center text-sm text-muted2" data-testid="aa-pick-first">{t("aa.pick")}</p>}
          {sel && canManage && (
            <SectionCard title={t("aa.new", { name: sel.business_name })} testid="aa-form-card">
              <form onSubmit={create} noValidate className="grid gap-4 sm:grid-cols-2" data-testid="aa-form">
                <div>
                  <label htmlFor="aa-pct" className="text-sm font-medium text-ink">{t("aa.pct")}</label>
                  <Input id="aa-pct" type="number" step="0.01" min="0" max="100" value={form.commission_pct} onChange={(e) => setForm({ ...form, commission_pct: e.target.value })} className="mt-1.5" data-testid="aa-pct" />
                  {tried && problems.pct && <p role="alert" className="mt-1 text-xs text-danger">{t(problems.pct)}</p>}
                </div>
                <div>
                  <label htmlFor="aa-fee" className="text-sm font-medium text-ink">{t("aa.fee")}</label>
                  <Input id="aa-fee" type="number" step="0.01" min="0" value={form.fee} onChange={(e) => setForm({ ...form, fee: e.target.value })} className="mt-1.5" data-testid="aa-fee" />
                  <p className="mt-1 text-xs text-muted2">{t("aa.feeHint")}</p>
                </div>
                <div>
                  <label htmlFor="aa-sched" className="text-sm font-medium text-ink">{t("aa.schedule")}</label>
                  <select id="aa-sched" className={`${SELECT} mt-1.5 w-full`} value={form.settlement_schedule} onChange={(e) => setForm({ ...form, settlement_schedule: e.target.value })} data-testid="aa-schedule">
                    {SCHEDULES.map((s) => <option key={s} value={s}>{t(`aa.sched.${s}`)}</option>)}
                  </select>
                  <p className="mt-1 text-xs text-muted2">{t("aa.scheduleHint")}</p>
                </div>
                <div>
                  <label htmlFor="aa-eff" className="text-sm font-medium text-ink">{t("aa.effective")}</label>
                  <Input id="aa-eff" type="date" value={form.effective_from} onChange={(e) => setForm({ ...form, effective_from: e.target.value })} className="mt-1.5" data-testid="aa-effective" />
                  {tried && problems.date && <p role="alert" className="mt-1 text-xs text-danger">{t(problems.date)}</p>}
                </div>
                <div className="sm:col-span-2">
                  <label htmlFor="aa-notes" className="text-sm font-medium text-ink">{t("aa.notes")}</label>
                  <Input id="aa-notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="mt-1.5" maxLength={500} />
                </div>
                <div className="sm:col-span-2">
                  <Button type="submit" disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="aa-submit">{t("aa.create")}</Button>
                </div>
              </form>
            </SectionCard>
          )}

          {sel && (
            <SectionCard title={t("aa.versions", { name: sel.business_name })} testid="aa-versions">
              {rows === null ? <StateBlock loading rows={2} testid="aa-versions" /> : rows.length === 0 ? (
                <p className="hg-tile p-6 text-center text-sm text-muted2" data-testid="aa-empty">{t("aa.noAgreements")}</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" data-testid="aa-table">
                    <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2">
                      <th className="px-2 py-2">{t("aa.col.version")}</th><th className="px-2 py-2">{t("aa.col.status")}</th>
                      <th className="px-2 py-2">{t("aa.col.commission")}</th><th className="px-2 py-2">{t("aa.col.fee")}</th>
                      <th className="px-2 py-2">{t("aa.col.schedule")}</th><th className="px-2 py-2">{t("aa.col.effective")}</th>
                      <th className="px-2 py-2">{t("aa.col.createdBy")}</th><th className="px-2 py-2">{t("aa.col.approvedBy")}</th>
                      <th className="px-2 py-2">{t("aa.col.accepted")}</th><th className="px-2 py-2" />
                    </tr></thead>
                    <tbody>
                      {rows.map((a) => (
                        <tr key={a.id} className="border-t border-white/10" data-testid={`aa-row-${a.version}`}>
                          <td className="px-2 py-2 font-medium text-ink">v{a.version}</td>
                          <td className="px-2 py-2"><Pill tone={a.status === "approved" ? "ok" : "warn"}>{t(`aa.st.${a.status}`)}</Pill></td>
                          <td className="px-2 py-2 tabular-nums">{a.commission_pct}%</td>
                          <td className="px-2 py-2 tabular-nums">{inrP(a.fixed_fee_paise)}</td>
                          <td className="px-2 py-2">{t(`aa.sched.${a.settlement_schedule}`)}</td>
                          <td className="px-2 py-2">{fmtDate(a.effective_from, lang)}</td>
                          <td className="px-2 py-2 text-xs">{a.created_by_name || "—"}</td>
                          <td className="px-2 py-2 text-xs">{a.approved_by_name ? `${a.approved_by_name} · ${fmtDate(a.approved_at, lang)}` : "—"}</td>
                          <td className="px-2 py-2 text-xs">{a.accepted_at ? fmtDate(a.accepted_at, lang) : t("aa.notAccepted")}</td>
                          <td className="px-2 py-2">
                            {a.status === "draft" && canManage && (
                              a.created_by === user?.id
                                ? <span className="text-xs text-muted2" data-testid={`aa-self-${a.version}`}>{t("aa.selfApprove")}</span>
                                : <Button size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => approve(a)} data-testid={`aa-approve-${a.version}`}>{t("aa.approve")}</Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </SectionCard>
          )}
        </div>
      </div>
    </div>
  );
}
