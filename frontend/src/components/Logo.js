import React from "react";
import { Leaf } from "lucide-react";

export function Logo({ size = "md", showText = true, dark = false }) {
  const dim = size === "sm" ? 32 : size === "lg" ? 48 : 40;
  return (
    <div className="flex items-center gap-2.5" data-testid="brand-logo">
      <div
        className="relative flex items-center justify-center rounded-full shrink-0"
        style={{
          width: dim, height: dim,
          background: "linear-gradient(145deg,#176B43,#0B4D2E)",
          boxShadow: "0 0 0 2px #C9A227, 0 4px 12px rgba(11,77,46,0.25)",
        }}
      >
        <Leaf size={dim * 0.5} color="#F6EFD5" strokeWidth={2} />
      </div>
      {showText && (
        <div className="leading-tight">
          <div className={`font-display font-semibold text-[15px] tracking-tight ${dark ? "text-white" : "text-forest"}`}>
            Anjali <span className="text-gold">Herbal Life</span>
          </div>
          <div className={`text-[9px] tracking-[0.18em] uppercase ${dark ? "text-white/60" : "text-muted2"}`}>
            Ayurveda India LLP
          </div>
        </div>
      )}
    </div>
  );
}
