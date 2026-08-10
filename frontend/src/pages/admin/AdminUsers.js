import React, { useEffect, useState } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function AdminUsers() {
  const { t } = useI18n();
  const [users, setUsers] = useState(null);
  const [filter, setFilter] = useState("");

  useEffect(() => { API.get("/admin/users").then(({ data }) => setUsers(data)).catch(() => setUsers([])); }, []);
  if (!users) return <Skeleton className="h-96 rounded-2xl" />;

  const filtered = users.filter((u) => !filter || u.full_name?.toLowerCase().includes(filter.toLowerCase()) || u.distributor_id?.toLowerCase().includes(filter.toLowerCase()) || u.email?.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.users")}</h1>
        <input placeholder={t("common.search")} value={filter} onChange={(e) => setFilter(e.target.value)} className="h-10 w-64 rounded-full border border-brand-50 bg-white px-4 text-sm focus:outline-none focus:ring-2 focus:ring-brand" data-testid="user-search" />
      </div>
      <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">ID</th><th className="p-4">{t("common.name")}</th><th className="p-4">{t("auth.email")}</th><th className="p-4">{t("common.status")}</th><th className="p-4">Sponsor</th><th className="p-4">KYC</th><th className="p-4">Joined</th></tr></thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} className="border-b border-brand-50/60" data-testid={`admin-user-${u.distributor_id}`}>
                <td className="p-4 font-medium text-forest">{u.distributor_id}</td>
                <td className="p-4 text-ink">{u.full_name}</td>
                <td className="p-4 text-muted2">{u.email}</td>
                <td className="p-4"><StatusBadge status={u.status} size="sm" /></td>
                <td className="p-4 text-muted2">{u.sponsor_id || "—"}</td>
                <td className="p-4 capitalize text-muted2">{(u.kyc_status || "").replace("_", " ")}</td>
                <td className="p-4 text-muted2">{(u.created_at || "").slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
