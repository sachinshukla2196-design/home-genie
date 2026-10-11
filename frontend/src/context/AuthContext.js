import React, { createContext, useContext, useEffect, useState } from "react";
import { API } from "@/lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null); // null = loading, false = logged out
  const [ready, setReady] = useState(false);

  const loadMe = async () => {
    const token = localStorage.getItem("anj_token");
    if (!token) { setUser(false); setReady(true); return; }
    try {
      const { data } = await API.get("/auth/me");
      setUser(data);
    } catch {
      localStorage.removeItem("anj_token");
      setUser(false);
    } finally {
      setReady(true);
    }
  };

  useEffect(() => {
    // Returning from Google OAuth: AuthCallback exchanges the session first. Skip /auth/me.
    if (window.location.hash?.includes("session_id=")) { setReady(true); return; }
    loadMe();
  }, []);

  const applyAuth = (data) => {
    localStorage.setItem("anj_token", data.token);
    setUser(data.user);
  };

  const logout = async () => {
    try { await API.post("/auth/logout"); } catch (e) { console.error("logout error", e); }
    localStorage.removeItem("anj_token");
    setUser(false);
  };

  const refresh = loadMe;

  return (
    <AuthContext.Provider value={{ user, ready, applyAuth, logout, refresh, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
