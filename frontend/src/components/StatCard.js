import React from "react";
import { motion } from "framer-motion";

export function StatCard({ icon: Icon, label, value, sub, accent = "brand", index = 0, testid }) {
  const accents = {
    brand: "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/25",
    gold: "bg-hg-gold/15 text-hg-gold ring-hg-gold/25",
    danger: "bg-danger/10 text-danger ring-danger/25",
    ink: "bg-hg-pink/15 text-hg-pink ring-hg-pink/25",
    success: "bg-hg-success/15 text-hg-success ring-hg-success/25",
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, delay: index * 0.06, ease: [0.16, 1, 0.3, 1] }}
      className="hg-card hg-lift relative overflow-hidden p-5"
      data-testid={testid}
    >
      <span className="hg-orb -right-8 -top-10 h-24 w-24 bg-hg-violet/20" />
      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs font-semibold uppercase tracking-[0.08em] text-muted2">{label}</div>
          <div className="mt-2 truncate font-display text-2xl font-semibold tabular-nums text-ink">{value}</div>
          {sub && <div className="mt-1 text-xs text-muted2">{sub}</div>}
        </div>
        {Icon && (
          <div className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-xl ring-1 ${accents[accent] || accents.brand}`}>
            <Icon size={19} />
          </div>
        )}
      </div>
    </motion.div>
  );
}
