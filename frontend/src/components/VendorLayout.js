import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, useLocation, Outlet } from "react-router-dom";
import { motion } from "framer-motion";
import { LayoutDashboard, Package, ClipboardList, Store, LogOut, Bell } from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

const NAV = [
  { to: "/vendor", icon: LayoutDashboard, key: "vp.dashboard", needsApproval: true },
  { to: "/vendor/orders", icon: ClipboardList, key: "vp.orders", needsApproval: true },
  { to: "/vendor/products", icon: Package, key: "vp.products", needsApproval: true },
  { to: "/vendor/profile", icon: Store, key: "vp.profile" },
];

const VendorCtx = createContext(null);
/** The signed-in vendor's application record (null until loaded, false if none yet). */
export const useVendor = () => useContext(VendorCtx);

export const VENDOR_STATUS_TONE = {
  draft: "bg-white/10 text-muted2 ring-white/15",
  submitted: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30",
  approved: "bg-hg-success/15 text-hg-success ring-hg-success/30",
  rejected: "bg-danger/10 text-danger ring-danger/30",
  suspended: "bg-danger/10 text-danger ring-danger/30",
};

export function VendorLayout() {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const loc = useLocation();
  const [vendor, setVendor] = useState(null);
  const [unread, setUnread] = useState(0);

  const reload = useCallback(() => API.get("/vendor/me").then(({ data }) => setVendor(data.vendor || false)).catch(() => setVendor(false)), []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    window.scrollTo(0, 0);
    API.get("/notifications").then(({ data }) => setUnread(data.unread)).catch(() => {});
  }, [loc.pathname]);

  const approved = vendor && vendor.status === "approved";
  const nav = NAV.filter((n) => approved || !n.needsApproval);
  const active = (to) => (to === "/vendor" ? loc.pathname === "/vendor" : loc.pathname.startsWith(to));

  return (
    <VendorCtx.Provider value={{ vendor, reload }}>
      <div className="min-h-screen bg-background">
        <aside className="glass-nav fixed inset-y-0 left-0 z-40 hidden w-64 flex-col !border-b-0 border-r border-brand-50 lg:flex">
          <div className="flex h-16 items-center border-b border-brand-50 px-5"><Logo size="sm" /></div>
          <div className="px-5 py-3">
            <span className="inline-flex items-center gap-1.5 rounded-full bg-hg-violet/15 px-2.5 py-1 text-[11px] font-semibold text-hg-lavender ring-1 ring-hg-lavender/25">
              <Store size={12} /> {t("vp.portal")}
            </span>
          </div>
          <nav className="flex-1 space-y-1 px-3" aria-label={t("vp.portal")}>
            {nav.map((i) => {
              const on = active(i.to);
              return (
                <Link key={i.to} to={i.to} aria-current={on ? "page" : undefined} data-testid={`vendor-nav-${i.key.split(".")[1]}`}
                  className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${on ? "bg-brand-50 text-ink" : "text-muted2 hover:bg-brand-50/60 hover:text-ink"}`}>
                  {on && <motion.span layoutId="vendor-side-pill" className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-hg-violet" />}
                  <i.icon size={18} className={on ? "text-hg-lavender" : ""} /> {t(i.key)}
                </Link>
              );
            })}
          </nav>
          <div className="border-t border-brand-50 p-3">
            <button onClick={logout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted2 hover:bg-danger/10 hover:text-danger" data-testid="vendor-logout">
              <LogOut size={18} /> {t("nav.logout")}
            </button>
          </div>
        </aside>

        <div className="lg:pl-64">
          <header className="glass-nav sticky top-0 z-30 px-4 lg:px-8" style={{ top: "env(safe-area-inset-top, 0px)" }}>
            <div className="flex h-16 items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="lg:hidden"><Logo size="sm" showText={false} /></span>
                <div className="min-w-0">
                  <div className="text-xs text-muted2">{t("vp.portal")}</div>
                  <div className="truncate text-sm font-semibold text-ink" data-testid="vendor-business-name">{(vendor && vendor.business_name) || user?.full_name}</div>
                </div>
                {vendor && (
                  <span className={`hidden rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 sm:inline-block ${VENDOR_STATUS_TONE[vendor.status]}`} data-testid="vendor-status">
                    {t(`vp.st.${vendor.status}`)}
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="hg-icon-btn relative" title={t("nav.notifications")}>
                  <Bell size={19} />
                  {unread > 0 && <span className="absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-hg-violet px-1 text-[11px] font-bold text-white">{unread}</span>}
                </span>
                <span className="hg-icon-btn !hidden sm:!inline-flex"><ThemeToggle /></span>
                <LanguageSwitcher />
              </div>
            </div>
            <nav className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-3 lg:hidden" aria-label={t("vp.portal")}>
              {nav.map((i) => {
                const on = active(i.to);
                return (
                  <Link key={i.to} to={i.to} className={`relative whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-medium ${on ? "text-white" : "hg-chip-off"}`}>
                    {on && <motion.span layoutId="vendor-top-pill" className="hg-chip-on absolute inset-0 rounded-full" />}
                    <span className="relative">{t(i.key)}</span>
                  </Link>
                );
              })}
              <button onClick={logout} className="hg-chip-off whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-medium text-danger">{t("nav.logout")}</button>
            </nav>
          </header>

          <motion.main key={loc.pathname} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28 }}
            className="mx-auto min-h-[calc(100vh-4rem)] max-w-6xl px-4 pb-16 pt-6 lg:px-8">
            <Outlet />
          </motion.main>
        </div>
      </div>
    </VendorCtx.Provider>
  );
}
