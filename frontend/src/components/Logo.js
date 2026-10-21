import React from "react";

export function Logo({ size = "md", dark = false, showText = true }) {
  const h = size === "sm" ? 36 : size === "lg" ? 60 : 46;
  return (
    <div
      className={`inline-flex w-fit shrink-0 items-center self-start ${dark ? "rounded-xl bg-white/95 px-2.5 py-1.5 shadow-sm" : ""}`}
      data-testid="brand-logo"
    >
      <span
        className="font-display font-bold tracking-tight text-brand"
        style={{ fontSize: h * 0.42, lineHeight: 1 }}
      >
        HOME <span className="text-gold">GENIES</span>
      </span>
    </div>
  );
}
