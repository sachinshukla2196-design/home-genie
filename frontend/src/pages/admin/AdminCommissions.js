import React, { useEffect, useState } from "react";
import { Share2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function AdminCommissions() {
  const { t } = useI18n();
  const [list, setList] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;
  useEffect(() => { API.get("/admin/commissions").then(({ data }) => setList(data)).catch(() => setList([])); }, []);
  if (!list) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.commissions")}</h1>
      {list.length === 0 ? <EmptyState icon={Share2} title={t("empty.income")} testid="admin-comm-empty" /> : (
        <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">Sponsor</th><th className="p-4">Referred</th><th className="p-4">{t("common.type")}</th><th className="p-4 text-right">{t("common.amount")}</th><th className="p-4">{t("common.status")}</th><th className="p-4">{t("common.date")}</th></tr></thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id} className="border-b border-brand-50/60" data-testid={`admin-comm-${c.id}`}>
                  <td className="p-4 font-medium text-forest">{c.sponsor_distributor_id}</td>
                  <td className="p-4 text-ink">{c.referred_distributor_id}</td>
                  <td className="p-4 text-muted2">{c.type.replace(/_/g, " ")}</td>
                  <td className="p-4 text-right font-medium text-brand">+{money(c.amount)}</td>
                  <td className="p-4"><span className="rounded-full bg-brand-50 px-2 py-0.5 text-xs font-semibold text-brand">{c.status}</span></td>
                  <td className="p-4 text-muted2">{(c.created_at || "").slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
