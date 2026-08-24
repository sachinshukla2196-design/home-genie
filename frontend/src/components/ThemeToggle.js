import React from "react";
import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/context/ThemeContext";

export function ThemeToggle({ dark = false }) {
  const { theme, toggle } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      onClick={toggle}
      aria-label="Toggle theme"
      data-testid="theme-toggle"
      className={`relative rounded-full p-2 transition-all ${
        dark ? "text-white/70 hover:bg-white/10 hover:text-white" : "text-muted2 hover:bg-brand-50 hover:text-forest"
      }`}
    >
      {isDark ? <Sun size={19} /> : <Moon size={19} />}
    </button>
  );
}
