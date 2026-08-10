import React from "react";
import { Button } from "@/components/ui/button";

export function EmptyState({ icon: Icon, title, desc, ctaLabel, onCta, testid }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-brand/20 bg-white/60 px-6 py-14 text-center" data-testid={testid}>
      {Icon && (
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-brand-50 text-brand">
          <Icon size={26} />
        </div>
      )}
      <h3 className="font-display text-lg font-medium text-ink">{title}</h3>
      {desc && <p className="mt-1 max-w-sm text-sm text-muted2">{desc}</p>}
      {ctaLabel && (
        <Button onClick={onCta} className="mt-5 rounded-full bg-forest hover:bg-brand" data-testid="empty-cta">
          {ctaLabel}
        </Button>
      )}
    </div>
  );
}
