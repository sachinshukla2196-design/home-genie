import React, { createContext, useContext, useEffect, useState } from "react";
import { translations } from "@/i18n/translations";

const I18nContext = createContext(null);

export function I18nProvider({ children }) {
  const [lang, setLangState] = useState(() => localStorage.getItem("anj_lang") || "en");

  const setLang = (l) => {
    setLangState(l);
    localStorage.setItem("anj_lang", l);
  };

  useEffect(() => {
    document.documentElement.lang = lang;
    document.body.classList.toggle("lang-hi", lang === "hi");
  }, [lang]);

  // t("key") or t("key", { n: 3 }) -> replaces {n} in the text (existing calls without variables are unchanged)
  const t = (key, vars) => {
    const s = (translations[lang] && translations[lang][key]) || translations.en[key] || key;
    return vars ? s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined || vars[k] === null ? "" : String(vars[k]))) : s;
  };

  return (
    <I18nContext.Provider value={{ lang, setLang, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export const useI18n = () => useContext(I18nContext);
