import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Download, FileBarChart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

const REPORTS = ["registrations", "sales", "orders", "payments", "referrals", "wallet"];
const BACKEND = process.env.REACT_APP_BACKEND_URL;

export default function AdminReports() {
  const { t } = useI18n();
  const [report, setReport] = useState("registrations");
  const [data, setData] = useState(null);

  useEffect(() => {
    setData(null);
    API.get(`/admin/reports/${report}`).then(({ data }) => setData(data)).catch(() => setData({ fields: [], rows: [] }));
  }, [report]);

  const exportCsv = async () => {
    const token = localStorage.getItem("anj_token");
    const res = await fetch(`${BACKEND}/api/admin/reports/${report}/export`, { headers: { Authorization: `Bearer ${token}` } });
    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = `${report}_report.csv`; a.click();
  };


  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.reports")} icon={FileBarChart} actions={<>
        <Button onClick={exportCsv} className="hg-btn h-11 rounded-full px-6" data-testid="export-report"><Download size={15} className="mr-1.5" /> {t("cta.export")}</Button>
      </>} />
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
      {!data ? (
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
