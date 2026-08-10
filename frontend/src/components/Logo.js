import React from "react";

export function Logo({ size = "md", dark = false, showText = true }) {
  const h = size === "sm" ? 36 : size === "lg" ? 60 : 46;
  return (
    <div
      className={`inline-flex items-center ${dark ? "rounded-xl bg-white/95 px-2.5 py-1.5 shadow-sm" : ""}`}
      data-testid="brand-logo"
    >
      <img
        src="/brand-logo.jpg"
        alt="Anjali Herbal Life Ayurveda India LLP"
        style={{ height: h }}
        className="w-auto object-contain"
      />
    </div>
  );
}
