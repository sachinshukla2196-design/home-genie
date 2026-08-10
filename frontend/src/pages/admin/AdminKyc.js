import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { ShieldCheck } from "lucide-react";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function AdminKyc() {
  const { t } = useI18n();
  const [recs, setRecs] = useState(null);
  const load = () => API.get("/admin/kyc").then(({ data }) => setRecs(data)).catch(() => setRecs([]));
  useEffect(() => { load(); }, []);

  const review = async (uid, action) => {
    const reason = action === "reject" ? window.prompt("Rejection reason?") || "Rejected" : "";
    try { await API.put(`/admin/kyc/${uid}`, { action, reason }); toast.success(t("cta.save")); load(); } catch (e) { toast.error(apiError(e)); }
  };

  if (!recs) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.kyc")}</h1>
      {recs.length === 0 ? <EmptyState icon={ShieldCheck} title="No KYC records" testid="admin-kyc-empty" /> : (
        <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">Distributor</th><th className="p-4">PAN</th><th className="p-4">Holder</th><th className="p-4">Bank</th><th className="p-4">IFSC</th><th className="p-4">{t("common.status")}</th><th className="p-4">{t("common.actions")}</th></tr></thead>
            <tbody>
              {recs.map((k) => (
                <tr key={k.user_id} className="border-b border-brand-50/60" data-testid={`admin-kyc-${k.distributor_id}`}>
                  <td className="p-4 font-medium text-forest">{k.distributor_id}</td>
                  <td className="p-4 text-muted2">{k.pan}</td>
                  <td className="p-4 text-ink">{k.account_holder_name}</td>
                  <td className="p-4 text-muted2">{k.bank_account}</td>
                  <td className="p-4 text-muted2">{k.ifsc}</td>
                  <td className="p-4"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${k.status === "verified" ? "bg-brand-50 text-brand" : k.status === "rejected" ? "bg-danger/10 text-danger" : "bg-gold-light text-gold"}`}>{k.status}</span></td>
                  <td className="p-4">
                    {k.status === "pending" && (
                      <div className="flex gap-2">
                        <Button onClick={() => review(k.user_id, "verify")} size="sm" className="h-8 rounded-full bg-forest hover:bg-brand" data-testid={`kyc-verify-${k.distributor_id}`}><Check size={14} /></Button>
                        <Button onClick={() => review(k.user_id, "reject")} size="sm" variant="outline" className="h-8 rounded-full border-danger/30 text-danger" data-testid={`kyc-reject-${k.distributor_id}`}><X size={14} /></Button>
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
