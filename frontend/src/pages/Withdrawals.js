import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Banknote, Clock, CheckCircle2, XCircle, ShieldCheck, Lock, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { Stagger, StaggerItem, pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const ICON = { pending: Clock, approved: CheckCircle2, paid: CheckCircle2, rejected: XCircle };
const PILL = {
  pending: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30",
  approved: "bg-hg-violet/15 text-hg-violet ring-hg-lavender/30 dark:text-hg-lavender",
  paid: "bg-hg-success/15 text-hg-success ring-hg-success/30",
  rejected: "bg-danger/10 text-danger ring-danger/25",
};

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
    <div className="mx-auto max-w-3xl space-y-5" data-testid="withdrawals-page">
      <PageHeader title={t("withdraw.title")} icon={Banknote} />

      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="hg-hero hg-sheen relative overflow-hidden rounded-3xl p-6 text-white sm:p-7">
        <span className="hg-orb -right-10 -top-12 h-40 w-40 bg-hg-pink/30" />
        <div className="relative">
          <div className="text-sm font-medium uppercase tracking-wider text-white/80">{t("wallet.available")}</div>
          <div className="mt-1 font-display text-4xl font-bold tabular-nums sm:text-5xl" data-testid="wd-available">
            {available.toLocaleString("en-IN")} pts
          </div>
          <p className="mt-2 text-xs text-white/75">{t("wallet.rate")}</p>
        </div>
      </motion.div>

      {user?.status !== "green" ? (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08 }}
          className="hg-card flex items-start gap-3 p-5 text-sm text-ink" data-testid="wd-locked">
          <span className="hg-icon-chip !h-9 !w-9 shrink-0 !rounded-xl !bg-hg-gold/15 !text-hg-gold"><Lock size={17} /></span>
          <span className="pt-1.5">{t("referral.lockedNote")}</span>
        </motion.div>
      ) : (
        <motion.form initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.08, duration: 0.4 }}
          onSubmit={submit} className="hg-card p-5 sm:p-6" data-testid="wd-form">
          <h2 className="flex items-center gap-2.5 font-display text-lg font-semibold text-ink">
            <span className="hg-icon-chip !h-9 !w-9 !rounded-xl"><Banknote size={18} /></span> {t("withdraw.request")}
          </h2>
          <p className="mt-2 text-sm text-muted2">{t("withdraw.note")}</p>
          <div className="mt-4 flex flex-col gap-3 sm:flex-row">
            <Input type="number" min="1" value={amount} onChange={(e) => setAmount(e.target.value)}
              placeholder={t("withdraw.amount")} aria-label={t("withdraw.amount")} className="w-full sm:max-w-[240px]" data-testid="wd-amount" />
            <motion.div {...pressable}>
              <Button type="submit" disabled={busy} className="hg-btn h-11 w-full rounded-full px-6 sm:w-auto" data-testid="wd-submit">
                <Banknote size={16} className="mr-1.5" /> {t("withdraw.request")}
              </Button>
            </motion.div>
          </div>
          <div className="hg-tile mt-4 flex items-start gap-2 p-3 text-xs text-muted2">
            <ShieldCheck size={15} className="mt-0.5 shrink-0 text-hg-violet dark:text-hg-lavender" />
            <span>{t("withdraw.kycNote")}</span>
          </div>
        </motion.form>
      )}

      <SectionCard title={t("withdraw.history")} icon={History}>
        {list.length === 0 ? (
          <EmptyState icon={Banknote} title={t("withdraw.empty")} testid="wd-empty" />
        ) : (
          <Stagger className="space-y-2.5">
            {list.map((r) => {
              const Icon = ICON[r.status] || Clock;
              return (
                <StaggerItem key={r.id} className="hg-tile flex items-center justify-between gap-3 p-3.5" data-testid={`wd-row-${r.request_number}`}>
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${PILL[r.status] || PILL.pending}`}><Icon size={16} /></span>
                    <div className="min-w-0">
                      <div className="truncate font-medium text-ink">{r.request_number}</div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted2">
                        <span>{(r.created_at || "").slice(0, 10)}</span>
                        <span className={`rounded-full px-2.5 py-0.5 font-semibold capitalize ring-1 ${PILL[r.status] || PILL.pending}`}>{r.status}</span>
                      </div>
                    </div>
                  </div>
                  <span className="shrink-0 font-display font-semibold tabular-nums text-ink">{Number(r.amount).toLocaleString("en-IN")} pts</span>
                </StaggerItem>
              );
            })}
          </Stagger>
        )}
      </SectionCard>
    </div>
  );
}
