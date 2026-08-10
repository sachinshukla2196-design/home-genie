import React from "react";
import { motion } from "framer-motion";

export function StatCard({ icon: Icon, label, value, sub, accent = "brand", index = 0, testid }) {
  const accents = {
    brand: "text-brand bg-brand-50",
    gold: "text-gold bg-gold-light",
    danger: "text-danger bg-danger/10",
    ink: "text-ink bg-muted",
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: index * 0.05 }}
      className="rounded-xl border border-brand-50 bg-white p-5 shadow-card hover:shadow-soft hover:-translate-y-0.5 transition-all duration-200"
      data-testid={testid}
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-[0.08em] text-muted2">{label}</div>
          <div className="mt-2 font-display text-2xl font-semibold text-ink">{value}</div>
          {sub && <div className="mt-1 text-xs text-muted2">{sub}</div>}
        </div>
        {Icon && (
          <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${accents[accent]}`}>
            <Icon size={18} />
          </div>
        )}
      </div>
    </motion.div>
  );
}
