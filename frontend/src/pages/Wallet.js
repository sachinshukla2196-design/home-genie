import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Wallet as WalletIcon, ArrowUpRight, ArrowDownRight, Banknote, Clock, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { Stagger, StaggerItem, CountUp } from "@/components/motion";
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

  if (!w) return <Skeleton className="h-48 rounded-3xl" />;

  const tiles = [
    { k: "wallet.pending", v: w.pending_balance, icon: Clock, c: "text-hg-gold" },
    { k: "wallet.earned", v: w.total_earned, icon: ArrowUpRight, c: "text-hg-success" },
    { k: "wallet.withdrawn", v: w.total_withdrawn, icon: Banknote, c: "text-hg-lavender" },
  ];

  return (
    <div className="space-y-5">
      <PageHeader title={t("wallet.title")} icon={WalletIcon}
        actions={<Button onClick={() => navigate("/app/withdrawals")} className="hg-btn h-11 rounded-full px-6" data-testid="wallet-withdraw-btn"><Banknote size={16} className="mr-1.5" /> {t("wallet.withdraw")}</Button>} />

      {/* Points hero */}
      <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        className="hg-hero hg-sheen relative overflow-hidden rounded-3xl p-6 sm:p-7" data-testid="wallet-card">
        <span className="hg-orb -right-10 -top-12 h-40 w-40 bg-hg-pink/30" />
        <span className="hg-orb -bottom-16 -left-10 h-40 w-40 bg-hg-violet/40" />
        <div className="relative">
          <div className="text-sm font-medium uppercase tracking-wider text-white/80">{t("wallet.available")}</div>
          <div className="mt-1 flex items-baseline gap-2 font-display font-bold tabular-nums">
            <CountUp value={Number(w.available_balance || 0)} className="text-5xl" />
            <span className="text-lg font-semibold text-white/80">pts</span>
          </div>
          <p className="mt-2 text-xs text-white/75">{t("wallet.rate")}</p>
          <Stagger className="mt-6 grid grid-cols-1 gap-2.5 min-[380px]:grid-cols-3">
            {tiles.map((x) => (
              <StaggerItem key={x.k} className="min-w-0 rounded-2xl bg-white/15 p-3 ring-1 ring-white/20 backdrop-blur-sm">
                <div className="flex items-center gap-1.5 text-xs text-white/75"><x.icon size={13} className="shrink-0" /> <span className="truncate">{t(x.k)}</span></div>
                <div className="mt-1 truncate font-semibold tabular-nums">{money(x.v)}</div>
              </StaggerItem>
            ))}
          </Stagger>
        </div>
      </motion.div>

      <SectionCard title={t("wallet.transactions")} icon={History}>
        {!txns ? <div className="space-y-2.5">{[...Array(3)].map((_, i) => <Skeleton key={i} className="h-16 rounded-2xl" />)}</div> : txns.length === 0 ? <EmptyState icon={WalletIcon} title={t("empty.wallet")} testid="wallet-empty" /> : (
          <Stagger className="space-y-2.5">
            {txns.map((tx) => {
              const credit = tx.direction === "credit";
              return (
                <StaggerItem key={tx.id} className="hg-tile flex items-center justify-between gap-3 p-3.5" data-testid={`txn-${tx.id}`}>
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ring-1 ${credit ? "bg-hg-success/15 text-hg-success ring-hg-success/25" : "bg-danger/10 text-danger ring-danger/25"}`}>
                      {credit ? <ArrowUpRight size={16} /> : <ArrowDownRight size={16} />}
                    </span>
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium text-ink">{tx.description || tx.type.replace(/_/g, " ")}</div>
                      <div className="truncate text-xs text-muted2">{(tx.created_at || "").slice(0, 16).replace("T", " ")} · {tx.status}</div>
                    </div>
                  </div>
                  <div className={`shrink-0 font-display font-semibold tabular-nums ${credit ? "text-hg-success" : "text-danger"}`}>{credit ? "+" : "-"}{money(tx.amount)}</div>
                </StaggerItem>
              );
            })}
          </Stagger>
        )}
      </SectionCard>
    </div>
  );
}
