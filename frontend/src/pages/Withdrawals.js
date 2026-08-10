import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Banknote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const SC = {
  pending: "bg-gold-light text-gold", under_review: "bg-gold-light text-gold", approved: "bg-brand-50 text-brand",
  processing: "bg-blue-50 text-blue-700", paid: "bg-brand-50 text-brand", rejected: "bg-danger/10 text-danger", cancelled: "bg-danger/10 text-danger",
};

export default function Withdrawals() {
  const { t } = useI18n();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [list, setList] = useState(null);
  const [amount, setAmount] = useState("");
  const [loading, setLoading] = useState(false);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  const load = () => API.get("/withdrawals").then(({ data }) => setList(data)).catch(() => setList([]));
  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await API.post("/withdrawals", { amount: parseFloat(amount) });
      toast.success(t("wallet.withdraw"));
      setAmount(""); await load();
    } catch (err) { toast.error(apiError(err)); } finally { setLoading(false); }
  };

  const isGreen = user?.status === "green";

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.withdrawals")}</h1>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="h-fit rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
          <h3 className="font-display text-lg font-medium text-ink">{t("wallet.withdraw")}</h3>
          {!isGreen ? (
            <div className="mt-4 rounded-lg bg-danger/10 px-4 py-3 text-sm text-danger">{t("referral.lockedNote")}</div>
          ) : (
            <form onSubmit={submit} className="mt-4 space-y-4">
              <div><Label className="text-sm text-ink">{t("common.amount")} (₹)</Label><Input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)} required className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid="wd-amount" /></div>
              <Button type="submit" disabled={loading} className="w-full rounded-full bg-forest hover:bg-brand" data-testid="wd-submit"><Banknote size={16} className="mr-1.5" /> {loading ? t("common.loading") : t("cta.submit")}</Button>
              <p className="text-xs text-muted2">KYC must be verified. <button type="button" onClick={() => navigate("/app/kyc")} className="font-medium text-brand hover:underline">{t("nav.kyc")}</button></p>
            </form>
          )}
        </div>

        <div className="lg:col-span-2">
          {!list ? <Skeleton className="h-48 rounded-2xl" /> : list.length === 0 ? (
            <EmptyState icon={Banknote} title={t("empty.income")} testid="wd-empty" />
          ) : (
            <div className="space-y-3">
              {list.map((w) => (
                <div key={w.id} className="flex items-center justify-between rounded-2xl border border-brand-50 bg-white p-5" data-testid={`wd-row-${w.request_number}`}>
                  <div><div className="font-display font-semibold text-ink">{money(w.amount)}</div><div className="text-xs text-muted2">{w.request_number} · {(w.created_at || "").slice(0, 10)}</div>{w.admin_note && <div className="mt-1 text-xs text-muted2">Note: {w.admin_note}</div>}</div>
                  <span className={`rounded-full px-3 py-1 text-xs font-semibold ${SC[w.status] || "bg-muted text-muted2"}`}>{w.status}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
