import React, { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function Team() {
  const { t } = useI18n();
  const [data, setData] = useState(null);
  useEffect(() => { API.get("/team").then(({ data }) => setData(data)).catch(() => setData({ members: [] })); }, []);
  if (!data) return <Skeleton className="h-64 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.team")}</h1>
        {data.members?.length > 0 && <div className="text-sm text-muted2">{data.total} members · {data.active} active</div>}
      </div>
      {!data.members || data.members.length === 0 ? (
        <EmptyState icon={Users} title={t("empty.team")} desc={t("landing.step3d")} testid="team-empty" />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">{t("common.name")}</th><th className="p-4">ID</th><th className="p-4">{t("common.status")}</th><th className="p-4">Location</th><th className="p-4">Joined</th></tr></thead>
            <tbody>
              {data.members.map((m) => (
                <tr key={m.distributor_id} className="border-b border-brand-50/60" data-testid={`team-row-${m.distributor_id}`}>
                  <td className="p-4 font-medium text-ink">{m.full_name}</td>
                  <td className="p-4 text-forest">{m.distributor_id}</td>
                  <td className="p-4"><StatusBadge status={m.status} size="sm" /></td>
                  <td className="p-4 text-muted2">{[m.city, m.state].filter(Boolean).join(", ") || "—"}</td>
                  <td className="p-4 text-muted2">{(m.joined_at || "").slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
