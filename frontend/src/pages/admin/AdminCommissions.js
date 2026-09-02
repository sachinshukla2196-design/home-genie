import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Share2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function AdminCommissions() {
  const { t } = useI18n();
  const [list, setList] = useState(null);
  const [busy, setBusy] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  const load = () => API.get("/admin/commissions").then(({ data }) => setList(data)).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const act = async (c, action) => {
    if (!window.confirm(`${action === "release" ? "Release" : "Hold"} commission of ${money(c.amount)} to ${c.sponsor_distributor_id}?`)) return;
    setBusy(c.id);
    try {
      const { data } = await API.put(`/admin/commissions/${c.id}/status`, { action });
      setList((l) => l.map((x) => (x.id === c.id ? { ...x, status: data.status } : x)));
      toast.success(action === "release" ? "Payment released" : "Payment held");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(null); }
  };

  if (!list) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.commissions")}</h1>
      {list.length === 0 ? <EmptyState icon={Share2} title={t("empty.income")} testid="admin-comm-empty" /> : (
        <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">Sponsor</th><th className="p-4">Referred</th><th className="p-4">{t("common.type")}</th><th className="p-4 text-right">{t("common.amount")}</th><th className="p-4">{t("common.status")}</th><th className="p-4">{t("common.date")}</th><th className="p-4">Action</th></tr></thead>
            <tbody>
              {list.map((c) => (
                <tr key={c.id} className="border-b border-brand-50/60" data-testid={`admin-comm-${c.id}`}>
                  <td className="p-4 font-medium text-forest">{c.sponsor_distributor_id}</td>
                  <td className="p-4 text-ink">{c.referred_distributor_id}</td>
                  <td className="p-4 text-muted2">{c.type.replace(/_/g, " ")}</td>
                  <td className="p-4 text-right font-medium text-brand">+{money(c.amount)}</td>
                  <td className="p-4"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${c.status === "HELD" ? "bg-danger/10 text-danger" : c.status === "RELEASED" ? "bg-brand-50 text-brand" : "bg-gold-light text-gold"}`}>{c.status}</span></td>
                  <td className="p-4 text-muted2">{(c.created_at || "").slice(0, 10)}</td>
                  <td className="p-4">
                    <div className="flex gap-2">
                      <button onClick={() => act(c, "release")} disabled={busy === c.id || c.status === "RELEASED"} className="rounded-full bg-forest px-3 py-1 text-xs font-semibold text-white hover:bg-brand disabled:opacity-50" data-testid={`release-${c.id}`}>Release</button>
                      <button onClick={() => act(c, "hold")} disabled={busy === c.id || c.status === "HELD"} className="rounded-full border border-gold/40 px-3 py-1 text-xs font-semibold text-gold hover:bg-gold-light/50 disabled:opacity-50" data-testid={`hold-${c.id}`}>Hold</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
