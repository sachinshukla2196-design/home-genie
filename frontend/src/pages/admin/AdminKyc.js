import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Check, X, Pencil, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function AdminKyc() {
  const { t } = useI18n();
  const [recs, setRecs] = useState(null);
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({});
  const [busy, setBusy] = useState(false);
  const load = () => API.get("/admin/kyc?status=pending").then(({ data }) => setRecs(data)).catch(() => setRecs([]));
  useEffect(() => { load(); }, []);

  const review = async (uid, action) => {
    const reason = action === "reject" ? window.prompt("Rejection reason?") || "Rejected" : "";
    try { await API.put(`/admin/kyc/${uid}`, { action, reason }); toast.success(t("cta.save")); load(); } catch (e) { toast.error(apiError(e)); }
  };

  const openEdit = (k) => { setForm({ pan: k.pan || "", account_holder_name: k.account_holder_name || "", bank_account: k.bank_account || "", ifsc: k.ifsc || "", bank_name: k.bank_name || "" }); setEdit(k); };
  const saveEdit = async () => {
    setBusy(true);
    try { await API.put(`/admin/kyc/${edit.user_id}/edit`, form); toast.success("KYC updated"); setEdit(null); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
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
                    <div className="flex gap-2">
                      <Button onClick={() => openEdit(k)} size="sm" variant="outline" className="h-8 rounded-full border-forest/25 text-forest" data-testid={`kyc-edit-${k.distributor_id}`}><Pencil size={14} /></Button>
                      {k.status === "pending" && (
                        <>
                          <Button onClick={() => review(k.user_id, "verify")} size="sm" className="h-8 rounded-full bg-forest hover:bg-brand" data-testid={`kyc-verify-${k.distributor_id}`}><Check size={14} /></Button>
                          <Button onClick={() => review(k.user_id, "reject")} size="sm" variant="outline" className="h-8 rounded-full border-danger/30 text-danger" data-testid={`kyc-reject-${k.distributor_id}`}><X size={14} /></Button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {edit && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" data-testid="kyc-edit-modal">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <h3 className="font-display text-lg font-medium text-ink">Edit KYC — {edit.distributor_id}</h3>
              <button onClick={() => setEdit(null)} className="text-muted2 hover:text-ink" data-testid="kyc-edit-close"><X size={18} /></button>
            </div>
            <div className="mt-4 space-y-3">
              {[["pan", "PAN"], ["account_holder_name", "Account Holder Name"], ["bank_account", "Bank Account"], ["ifsc", "IFSC"], ["bank_name", "Bank Name"]].map(([k, label]) => (
                <div key={k}>
                  <Label className="text-sm text-ink">{label}</Label>
                  <Input value={form[k] ?? ""} onChange={(e) => setForm((f) => ({ ...f, [k]: e.target.value }))} className="mt-1 h-10" data-testid={`kyc-field-${k}`} />
                </div>
              ))}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <Button onClick={() => setEdit(null)} variant="outline" className="rounded-full" data-testid="kyc-edit-cancel">Cancel</Button>
              <Button onClick={saveEdit} disabled={busy} className="rounded-full bg-forest hover:bg-brand" data-testid="kyc-edit-save">{busy ? "Saving…" : "Save"}</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
