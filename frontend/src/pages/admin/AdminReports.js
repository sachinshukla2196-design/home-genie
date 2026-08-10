import React, { useEffect, useState } from "react";
import { Download, FileBarChart } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

const REPORTS = ["registrations", "activations", "sales", "orders", "payments", "referrals", "commissions", "wallet", "withdrawals"];
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
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.reports")}</h1>
        <Button onClick={exportCsv} className="rounded-full bg-forest hover:bg-brand" data-testid="export-report"><Download size={15} className="mr-1.5" /> {t("cta.export")}</Button>
      </div>
      <div className="flex flex-wrap gap-2">
        {REPORTS.map((r) => (
          <button key={r} onClick={() => setReport(r)} data-testid={`report-tab-${r}`}
            className={`rounded-full px-4 py-1.5 text-sm font-medium capitalize transition-all ${report === r ? "bg-forest text-white" : "border border-brand-50 bg-white text-muted2 hover:text-forest"}`}>{r}</button>
        ))}
      </div>
      {!data ? <Skeleton className="h-96 rounded-2xl" /> : data.rows.length === 0 ? <EmptyState icon={FileBarChart} title="No data for this report" testid="report-empty" /> : (
        <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2">{data.fields.map((f) => <th key={f} className="p-3 capitalize">{f.replace(/_/g, " ")}</th>)}</tr></thead>
            <tbody>
              {data.rows.slice(0, 200).map((row, i) => (
                <tr key={i} className="border-b border-brand-50/60" data-testid={`report-row-${i}`}>
                  {data.fields.map((f) => <td key={f} className="p-3 text-ink">{String(row[f] ?? "—").slice(0, 40)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
