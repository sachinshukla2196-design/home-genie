import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Banknote, Clock, CheckCircle2, XCircle, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const ICON = { pending: Clock, approved: CheckCircle2, paid: CheckCircle2, rejected: XCircle };

export default function Withdrawals() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [w, setW] = useState(null);
  const [list, setList] = useState([]);
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => {
    API.get("/wallet").then(({ data }) => setW(data)).catch(() => {});
    API.get("/withdrawals").then(({ data }) => setList(data)).catch(() => {});
  };
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (e) => {
    e.preventDefault();
    const amt = Number(amount);
    if (!amt || amt <= 0) return toast.error(t("withdraw.enterAmount"));
    setBusy(true);
    try {
      await API.post("/withdrawals", { amount: amt });
      toast.success(t("withdraw.submitted"));
      setAmount("");
      load();
    } catch (err) {
      toast.error(apiError(err));
    } finally { setBusy(false); }
  };

  const available = Number(w?.available_balance || 0);

  return (
    <div className="space-y-6" data-testid="withdrawals-page">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("withdraw.title")}</h1>

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
        className="rounded-2xl hg-royal p-6 text-white">
        <div className="text-sm text-white/70">{t("wallet.available")}</div>
        <div className="mt-1 font-display text-4xl font-semibold text-gold" data-testid="wd-available">
          {available.toLocaleString("en-IN")} pts
        </div>
        <p className="mt-2 text-xs text-white/70">{t("wallet.rate")}</p>
      </motion.div>

      {user?.status !== "green" ? (
        <div className="rounded-2xl border border-brand-50 bg-gold-light/40 p-5 text-sm text-ink" data-testid="wd-locked">
          {t("referral.lockedNote")}
        </div>
      ) : (
        <form onSubmit={submit} className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="wd-form">
          <h2 className="font-display text-lg font-medium text-ink">{t("withdraw.request")}</h2>
          <p className="mt-1 text-sm text-muted2">{t("withdraw.note")}</p>
          <div className="mt-4 flex flex-wrap gap-3">
            <Input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)}
              placeholder={t("withdraw.amount")} className="h-11 max-w-[220px] rounded-lg" data-testid="wd-amount" />
            <Button type="submit" disabled={busy} className="btn-grad h-11 rounded-full px-6" data-testid="wd-submit">
              <Banknote size={16} className="mr-1.5" /> {t("withdraw.request")}
            </Button>
          </div>
          <div className="mt-4 flex items-start gap-2 rounded-lg bg-brand-50/50 p-3 text-xs text-muted2">
            <ShieldCheck size={15} className="mt-0.5 shrink-0 text-brand" />
            <span>{t("withdraw.kycNote")}</span>
          </div>
        </form>
      )}

      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <h2 className="font-display text-lg font-medium text-ink">{t("withdraw.history")}</h2>
        {list.length === 0 ? (
          <EmptyState icon={Banknote} title={t("withdraw.empty")} testid="wd-empty" />
        ) : (
          <div className="mt-4 space-y-3">
            {list.map((r) => {
              const Icon = ICON[r.status] || Clock;
              return (
                <div key={r.id} className="flex items-center justify-between rounded-lg border border-brand-50 p-3" data-testid={`wd-row-${r.request_number}`}>
                  <div>
                    <div className="font-medium text-ink">{r.request_number}</div>
                    <div className="text-xs capitalize text-muted2">{(r.created_at || "").slice(0, 10)} · {r.status}</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Icon size={16} className={r.status === "rejected" ? "text-danger" : "text-brand"} />
                    <span className="font-display font-semibold text-forest">{Number(r.amount).toLocaleString("en-IN")} pts</span>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
