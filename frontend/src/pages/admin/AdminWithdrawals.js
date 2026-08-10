import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, X, Banknote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function AdminWithdrawals() {
  const { t } = useI18n();
  const [list, setList] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;
  const load = () => API.get("/admin/withdrawals").then(({ data }) => setList(data)).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const act = async (id, action) => {
    const note = window.prompt(`Note for ${action}?`) || "";
    try { await API.put(`/admin/withdrawals/${id}`, { action, note }); toast.success(t("cta.save")); load(); } catch (e) { toast.error(apiError(e)); }
  };

  if (!list) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.withdrawals")}</h1>
      {list.length === 0 ? <EmptyState icon={Banknote} title="No withdrawal requests" testid="admin-wd-empty" /> : (
        <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">Request</th><th className="p-4">Distributor</th><th className="p-4 text-right">{t("common.amount")}</th><th className="p-4">{t("common.status")}</th><th className="p-4">{t("common.actions")}</th></tr></thead>
            <tbody>
              {list.map((w) => (
                <tr key={w.id} className="border-b border-brand-50/60" data-testid={`admin-wd-${w.request_number}`}>
                  <td className="p-4 font-medium text-ink">{w.request_number}</td>
                  <td className="p-4 text-forest">{w.distributor_id}</td>
                  <td className="p-4 text-right font-medium text-ink">{money(w.amount)}</td>
                  <td className="p-4"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${w.status === "paid" || w.status === "approved" ? "bg-brand-50 text-brand" : w.status === "rejected" ? "bg-danger/10 text-danger" : "bg-gold-light text-gold"}`}>{w.status}</span></td>
                  <td className="p-4">
                    {["pending", "under_review", "approved"].includes(w.status) && (
                      <div className="flex gap-2">
                        {w.status !== "approved" && <Button onClick={() => act(w.id, "approve")} size="sm" className="h-8 rounded-full bg-forest hover:bg-brand" data-testid={`wd-approve-${w.request_number}`}>Approve</Button>}
                        <Button onClick={() => act(w.id, "mark_paid")} size="sm" className="h-8 rounded-full bg-gold text-forest hover:bg-gold/90" data-testid={`wd-paid-${w.request_number}`}><Check size={14} className="mr-1" />Paid</Button>
                        <Button onClick={() => act(w.id, "reject")} size="sm" variant="outline" className="h-8 rounded-full border-danger/30 text-danger" data-testid={`wd-reject-${w.request_number}`}><X size={14} /></Button>
                      </div>
                    )}
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
