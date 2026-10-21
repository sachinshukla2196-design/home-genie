import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Wallet as WalletIcon, ArrowUpRight, ArrowDownRight, Banknote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function Wallet() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [w, setW] = useState(null);
  const [txns, setTxns] = useState(null);
  const money = (v) => `${Number(v || 0).toLocaleString("en-IN")} pts`;

  useEffect(() => {
    API.get("/wallet").then(({ data }) => setW(data)).catch(() => {});
    API.get("/wallet/transactions").then(({ data }) => setTxns(data)).catch(() => setTxns([]));
  }, []);

  if (!w) return <Skeleton className="h-48 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("wallet.title")}</h1>
        <Button onClick={() => navigate("/app/withdrawals")} className="btn-grad rounded-full" data-testid="wallet-withdraw-btn"><Banknote size={16} className="mr-1.5" /> {t("wallet.withdraw")}</Button>
      </div>

      {/* Premium wallet card */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-3xl bg-forest p-7 text-white shadow-lift" data-testid="wallet-card">
        <div className="absolute -right-8 -top-8 h-40 w-40 rounded-full bg-gold/20 blur-2xl" />
        <div className="relative">
          <div className="text-sm text-white/60">{t("wallet.available")}</div>
          <div className="mt-1 font-display text-4xl font-semibold text-gold">{money(w.available_balance)}</div>
          <div className="mt-6 grid grid-cols-3 gap-4 text-sm">
            <div><div className="text-white/60">{t("wallet.pending")}</div><div className="mt-0.5 font-semibold">{money(w.pending_balance)}</div></div>
            <div><div className="text-white/60">{t("wallet.earned")}</div><div className="mt-0.5 font-semibold">{money(w.total_earned)}</div></div>
            <div><div className="text-white/60">{t("wallet.withdrawn")}</div><div className="mt-0.5 font-semibold">{money(w.total_withdrawn)}</div></div>
          </div>
        </div>
      </motion.div>

      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <h3 className="mb-4 font-display text-lg font-medium text-ink">{t("wallet.transactions")}</h3>
        {!txns ? <Skeleton className="h-32" /> : txns.length === 0 ? <EmptyState icon={WalletIcon} title={t("empty.wallet")} testid="wallet-empty" /> : (
          <div className="space-y-2">
            {txns.map((tx) => (
              <div key={tx.id} className="flex items-center justify-between rounded-lg border border-brand-50 p-3" data-testid={`txn-${tx.id}`}>
                <div className="flex items-center gap-3">
                  <div className={`flex h-9 w-9 items-center justify-center rounded-full ${tx.direction === "credit" ? "bg-brand-50 text-brand" : "bg-danger/10 text-danger"}`}>
                    {tx.direction === "credit" ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                  </div>
                  <div><div className="text-sm font-medium text-ink">{tx.description || tx.type.replace(/_/g, " ")}</div><div className="text-xs text-muted2">{(tx.created_at || "").slice(0, 16).replace("T", " ")} · {tx.status}</div></div>
                </div>
                <div className={`font-display font-semibold ${tx.direction === "credit" ? "text-brand" : "text-danger"}`}>{tx.direction === "credit" ? "+" : "-"}{money(tx.amount)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
