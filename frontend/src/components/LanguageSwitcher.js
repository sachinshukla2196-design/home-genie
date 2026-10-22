import React from "react";
import { useI18n } from "@/context/I18nContext";

export function LanguageSwitcher({ compact = false }) {
  const { lang, setLang } = useI18n();
  return (
    <div
      className="inline-flex items-center rounded-full border border-brand-50 bg-white p-0.5 text-sm"
      data-testid="language-switcher"
    >
      <button
        data-testid="lang-en-btn"
        onClick={() => setLang("en")}
        className={`px-3 py-1 rounded-full transition-all duration-200 ${lang === "en" ? "hg-chip-on" : "text-muted2 hover:text-forest"}`}
      >
        EN
      </button>
      <button
        data-testid="lang-hi-btn"
        onClick={() => setLang("hi")}
        className={`px-3 py-1 rounded-full transition-all duration-200 font-hindi ${lang === "hi" ? "hg-chip-on" : "text-muted2 hover:text-forest"}`}
      >
        हिन्दी
      </button>
    </div>
  );
}
