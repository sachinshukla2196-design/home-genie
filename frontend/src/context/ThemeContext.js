import React, { createContext, useContext, useEffect, useState } from "react";

const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  // OWNER DECISION: one theme for every portal (warm cream + chocolate + gold). Dark mode is retired; a stored "dark" preference
  // from the old violet design is ignored so no one is left on the old look.
  const [theme] = useState("light");

  useEffect(() => {
    document.documentElement.classList.remove("dark");
    try { localStorage.setItem("anj_theme", "light"); } catch (e) { /* storage may be unavailable */ }
  }, []);

  const toggle = () => {};

  return <ThemeContext.Provider value={{ theme, toggle }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
