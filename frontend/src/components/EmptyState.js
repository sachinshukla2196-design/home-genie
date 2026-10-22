import React from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";

export function EmptyState({ icon: Icon, title, desc, ctaLabel, onCta, testid }) {
  return (
    <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.35 }}
      className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-brand/20 bg-white/60 px-6 py-14 text-center" data-testid={testid}>
      {Icon && (
        <div className="relative mb-4">
          <span className="absolute inset-0 rounded-full bg-hg-violet/30 blur-xl" />
          <div className="hg-icon-chip hg-float-slow relative !h-16 !w-16 !rounded-2xl"><Icon size={28} /></div>
        </div>
      )}
      <h3 className="font-display text-lg font-medium text-ink">{title}</h3>
      {desc && <p className="mt-1 max-w-sm text-sm text-muted2">{desc}</p>}
      {ctaLabel && (
        <Button onClick={onCta} className="hg-btn mt-5 h-11 rounded-full px-6" data-testid="empty-cta">
          {ctaLabel}
        </Button>
      )}
    </motion.div>
  );
}
