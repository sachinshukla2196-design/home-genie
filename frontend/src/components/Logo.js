import React from "react";

/**
 * HOME GENIES brand mark.
 * variant: "full" (lamp + wordmark) | "icon" (lamp only) | "wordmark" (text only)
 * dark: render for dark/royal backgrounds.
 */
export function Logo({ size = "md", dark = false, showText = true, variant, className = "" }) {
  const h = size === "sm" ? 34 : size === "lg" ? 60 : 44;
  const v = variant || (showText ? "full" : "icon");
  const textSize = Math.max(13, Math.round(h * 0.37));

  const Lamp = (
    <img
      src="/brand/logo-icon.png"
      alt=""
      aria-hidden="true"
      style={{ height: h, width: h }}
      className="shrink-0 rounded-xl object-cover shadow-sm ring-1 ring-hg-violet/40"
    />
  );

  const Wordmark = (
    <span className="whitespace-nowrap leading-none" style={{ fontSize: textSize }}>
      <span className={`font-display font-bold tracking-tight ${dark ? "text-white" : "text-[#1B1024] dark:text-white"}`}>HOME</span>
      <span className="bg-gradient-to-b from-[#E9A8F7] via-hg-lavender to-[#9333EA] bg-clip-text font-display font-bold tracking-tight text-transparent"> GENIES</span>
    </span>
  );

  return (
    <div className={`inline-flex w-fit shrink-0 items-center gap-2.5 ${className}`} data-testid="brand-logo">
      {v !== "wordmark" && Lamp}
      {v !== "icon" && Wordmark}
    </div>
  );
}

export function LogoHero({ className = "" }) {
  return (
    <img
      src="/brand/logo-icon.png"
      alt="HOME GENIES — a genie of the home"
      className={`rounded-2xl object-cover ${className}`}
      data-testid="brand-logo-hero"
    />
  );
}
