import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { AlertTriangle, Download, FileBarChart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";
import { downloadCsv } from "@/components/vendor/kit";

const REPORTS = ["registrations", "sales", "orders", "payments", "referrals", "wallet"];
// Programme 02 / W4: the same roles the server allows to export (admin_order_ops.EXPORT_ROLES). The server is the authority;
// hiding the button only avoids offering an action that would be refused.
const EXPORT_ROLES = ["super_admin", "admin", "accounts_admin"];

export default function AdminReports() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [report, setReport] = useState("registrations");
  const [range, setRange] = useState({ date_from: "", date_to: "" });
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const canExport = EXPORT_ROLES.includes(user?.role);
  const params = Object.fromEntries(Object.entries(range).filter(([, v]) => v));

  useEffect(() => {
    let live = true;
    setData(null); setError(null);
    API.get(`/admin/reports/${report}`, { params: Object.fromEntries(Object.entries(range).filter(([, v]) => v)) })
      .then(({ data }) => { if (live) setData(data); })
      .catch((e) => { if (live) setError(apiError(e)); });          // an error is shown as an error, never as "no data"
    return () => { live = false; };
  }, [report, range]);

  const exportCsv = async () => {
    setBusy(true);
    try {
      await downloadCsv(`/admin/reports/${report}/export`, `${report}_report.csv`, params);
    } catch (e) {
      toast.error(apiError(e));                                       // refused / too large / failed: nothing was downloaded
    } finally {
      setBusy(false);
    }
  };
  const setDate = (k) => (e) => setRange({ ...range, [k]: e.target.value });

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.reports")} icon={FileBarChart} actions={canExport ? <>
        <Button onClick={exportCsv} disabled={busy || !!error} className="hg-btn h-11 rounded-full px-6" data-testid="export-report"><Download size={15} className="mr-1.5" /> {t("cta.export")}</Button>
      </> : null} />
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
        {REPORTS.map((r) => {
          const on = report === r;
          return (
            <button key={r} onClick={() => setReport(r)} data-testid={`report-tab-${r}`} aria-pressed={on}
              className={`relative shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium capitalize transition-colors ${on ? "text-white" : "hg-chip-off"}`}>
              {on && <motion.span layoutId="admin-reports-tab" className="hg-chip-on absolute inset-0 rounded-full" transition={{ type: "spring", stiffness: 480, damping: 34 }} />}
              <span className="relative">{r}</span>
            </button>
          );
        })}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted2">From <Input type="date" value={range.date_from} onChange={setDate("date_from")} className="h-10 rounded-xl" data-testid="report-from" /></label>
        <label className="flex items-center gap-2 text-xs text-muted2">To <Input type="date" value={range.date_to} onChange={setDate("date_to")} className="h-10 rounded-xl" data-testid="report-to" /></label>
        {data && !error && (
          <p className="text-xs text-muted2" data-testid="report-count">
            {data.truncated ? `Showing the newest ${data.rows.length.toLocaleString("en-IN")} of ${data.total.toLocaleString("en-IN")} rows. Choose dates to narrow the report.`
              : `${(data.total ?? data.rows.length).toLocaleString("en-IN")} rows`}
            {data.masked?.length ? ` · ${data.masked.join(", ").replace(/_/g, " ")} masked` : ""}
          </p>
        )}
      </div>
      {error ? (
        <div role="alert" className="hg-card flex flex-col items-center gap-3 p-8 text-center" data-testid="report-error">
          <AlertTriangle className="text-danger" /><p className="text-sm text-ink">{error}</p>
        </div>
      ) : !data ? (
        <div className="hg-card space-y-3 p-5 sm:p-6">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10 rounded-xl" />)}</div>
      ) : data.rows.length === 0 ? <EmptyState icon={FileBarChart} title="No data for this report" testid="report-empty" /> : (
        <div className="hg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2">{data.fields.map((f) => <th key={f} className="whitespace-nowrap px-4 py-3 font-semibold">{f.replace(/_/g, " ")}</th>)}</tr></thead>
              <tbody>
                {data.rows.slice(0, 200).map((row, i) => (
                  <tr key={row.id || row.session_id || row.order_number || row.request_number || `row-${i}`} className="border-t border-brand-50 transition-colors hover:bg-brand-50/60" data-testid={`report-row-${i}`}>
                    {data.fields.map((f) => <td key={f} className="whitespace-nowrap px-4 py-3 text-ink">{String(row[f] ?? "—").slice(0, 40)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
