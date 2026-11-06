import React from "react";

/**
 * HOME GENIES brand mark (owner-approved cream / chocolate / gold design): a house sheltering a woman, with a serif wordmark
 * and the "Shop · Share · Sell · Earn" tagline.
 * variant: "full" (icon + wordmark) | "icon" (icon only) | "wordmark" (text only)
 * dark: render for dark (chocolate) backgrounds.
 */
export function HouseMark({ size = 44, dark = false, className = "" }) {
  const stroke = dark ? "#F0D78E" : "#3B2417";
  const fill = dark ? "#F0D78E" : "#5C3A26";
  return (
    <svg viewBox="0 0 64 64" width={size} height={size} className={`shrink-0 ${className}`} aria-hidden="true" focusable="false">
      <path d="M6 30 L32 8 L58 30" fill="none" stroke={stroke} strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M13 26 V55 a3 3 0 0 0 3 3 H48 a3 3 0 0 0 3 -3 V26" fill="none" stroke={stroke} strokeWidth="4" strokeLinecap="round" />
      <rect x="44" y="11" width="6" height="11" rx="1.2" fill={stroke} />
      <circle cx="32" cy="32" r="7" fill={fill} />
      <path d="M18 56 c1.5-10 7.5-15.5 14-15.5 s12.5 5.5 14 15.5 z" fill={fill} />
      <path d="M26 30.5 c1.5-6.5 10.5-8 13.5-1.5" fill="none" stroke={dark ? "#3B2417" : "#C9A13B"} strokeWidth="2.2" strokeLinecap="round" />
    </svg>
  );
}

export function Logo({ size = "md", dark = false, showText = true, variant, className = "", tagline = true }) {
  const h = size === "sm" ? 34 : size === "lg" ? 60 : 44;
  const v = variant || (showText ? "full" : "icon");
  const textSize = Math.max(15, Math.round(h * 0.46));

  const Wordmark = (
    <span className="flex flex-col leading-none">
      <span className={`whitespace-nowrap font-serif font-bold tracking-tight ${dark ? "text-[#FBF1DA]" : "text-[#2B1A10]"}`} style={{ fontSize: textSize }}>
        HOME GENIES<sup className="ml-0.5 align-super text-[0.42em] font-sans font-semibold">®</sup>
      </span>
      {tagline && h >= 40 && (
        <span className={`mt-1 whitespace-nowrap text-[11px] font-medium tracking-wide ${dark ? "text-[#E9D9BC]" : "text-[#5C3A26]"}`}>Shop · Share · Sell · Earn</span>
      )}
    </span>
  );

  return (
    <div className={`inline-flex w-fit shrink-0 items-center gap-2 ${className}`} data-testid="brand-logo">
      {v !== "wordmark" && <HouseMark size={h} dark={dark} />}
      {v !== "icon" && Wordmark}
    </div>
  );
}

export function LogoHero({ className = "" }) {
  return (
    <span className={`inline-flex items-center justify-center rounded-2xl bg-[#FFFDF8] ring-1 ring-[#C9A13B]/40 ${className}`} data-testid="brand-logo-hero">
      <HouseMark size={96} />
    </span>
  );
}
