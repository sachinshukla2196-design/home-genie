import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Link, useLocation, Outlet } from "react-router-dom";
import { MotionConfig, motion } from "framer-motion";
import {
  LayoutDashboard, Package, ClipboardList, Store, LogOut, Bell, Boxes, Truck, Undo2, BarChart3, Landmark, Banknote, LifeBuoy, ShieldCheck, Menu, FileBarChart, TrendingUp,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

// Grouped navigation. Every item is always shown: pages for vendors who are not approved yet explain what is pending
// (see VendorGate in App.js) instead of hiding the menu. Data is still protected on the backend.
export const NAV_GROUPS = [
  { key: "vx.nav.g.overview", items: [
    { to: "/vendor/dashboard", icon: LayoutDashboard, key: "vp.dashboard", id: "dashboard" },
    { to: "/vendor/notifications", icon: Bell, key: "vx.nav.notifications", id: "notifications" },
  ] },
  { key: "vx.nav.g.catalogue", items: [
    { to: "/vendor/products", icon: Package, key: "vp.products", id: "products" },
    { to: "/vendor/inventory", icon: Boxes, key: "vx.nav.inventory", id: "inventory" },
  ] },
  { key: "vx.nav.g.orders", items: [
    { to: "/vendor/orders", icon: ClipboardList, key: "vp.orders", id: "orders" },
    { to: "/vendor/shipping", icon: Truck, key: "vx.nav.shipping", id: "shipping" },
  ] },
  { key: "vx.nav.g.growth", items: [
    { to: "/vendor/reports", icon: FileBarChart, key: "vx.nav.report", id: "report" },
    { to: "/vendor/advancement", icon: TrendingUp, key: "vx.nav.advancement", id: "advancement" },
    { to: "/vendor/analytics", icon: BarChart3, key: "vx.nav.analytics", id: "analytics" },
  ] },
  { key: "vx.nav.g.finance", items: [
    { to: "/vendor/earnings", icon: Landmark, key: "vx.nav.earnings", id: "earnings" },
    { to: "/vendor/cod", icon: Banknote, key: "vx.nav.cod", id: "cod" },
  ] },
  { key: "vx.nav.g.account", items: [
    { to: "/vendor/profile", icon: Store, key: "vp.profile", id: "profile" },
    { to: "/vendor/support", icon: LifeBuoy, key: "vx.nav.support", id: "support" },
    { to: "/vendor/security", icon: ShieldCheck, key: "vx.nav.security", id: "security" },
  ] },
];
const BOTTOM = ["dashboard", "orders", "products", "earnings"];

const VendorCtx = createContext(null);
/** The signed-in vendor's application record (null until loaded, false if none yet). */
export const useVendor = () => useContext(VendorCtx);

export const VENDOR_STATUS_TONE = {
  draft: "bg-white/10 text-muted2 ring-white/15",
  submitted: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30",
  under_review: "bg-[#5B7CFF]/15 text-[#8FA6FF] ring-[#8FA6FF]/30",
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
  const [menu, setMenu] = useState(false);

  const reload = useCallback(() => API.get("/vendor/me").then(({ data }) => setVendor(data.vendor || false)).catch(() => setVendor(false)), []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    window.scrollTo(0, 0);
    setMenu(false);
    API.get("/vendor/notifications", { params: { page_size: 1 } }).then(({ data }) => setUnread(data.unread)).catch(() => {});
  }, [loc.pathname]);

  const approved = vendor && vendor.status === "approved";
  const groups = NAV_GROUPS;
  const flat = groups.flatMap((g) => g.items);
  const active = (to) => (to === "/vendor" ? loc.pathname === "/vendor" : loc.pathname.startsWith(to));

  const NavItem = ({ i, compact }) => {
    const on = active(i.to);
    return (
      <Link to={i.to} aria-current={on ? "page" : undefined} data-testid={`vendor-nav-${i.id}`}
        className={`group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-hg-violet ${on ? "bg-brand-50 text-ink" : "text-muted2 hover:bg-brand-50/60 hover:text-ink"} ${compact ? "py-3" : ""}`}>
        {on && !compact && <motion.span layoutId="vendor-side-pill" className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-hg-violet" />}
        <i.icon size={18} className={on ? "text-hg-lavender" : ""} aria-hidden />
        <span className="min-w-0 flex-1 truncate">{t(i.key)}</span>
        {i.id === "notifications" && unread > 0 && <span className="rounded-full bg-hg-violet px-1.5 text-[11px] font-bold text-white" aria-label={t("vx.unread", { n: unread })}>{unread}</span>}
      </Link>
    );
  };

  return (
    <VendorCtx.Provider value={{ vendor, reload, unread }}>
      <MotionConfig reducedMotion="user">
        <div className="min-h-screen bg-background">
          <a href="#vendor-main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-full focus:bg-hg-violet focus:px-4 focus:py-2 focus:text-white">{t("vx.skip")}</a>
          <aside className="glass-nav fixed inset-y-0 left-0 z-40 hidden w-64 flex-col !border-b-0 border-r border-brand-50 lg:flex">
            <div className="flex h-16 items-center border-b border-brand-50 px-5"><Logo size="sm" /></div>
            <div className="px-5 py-3">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-hg-violet/15 px-2.5 py-1 text-[11px] font-semibold text-hg-lavender ring-1 ring-hg-lavender/25">
                <Store size={12} aria-hidden /> {t("vp.portal")}
              </span>
            </div>
            <nav className="flex-1 space-y-4 overflow-y-auto px-3 pb-3" aria-label={t("vp.portal")}>
              {groups.map((g) => (
                <div key={g.key}>
                  <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted2">{t(g.key)}</div>
                  <div className="space-y-0.5">{g.items.map((i) => <NavItem key={i.to} i={i} />)}</div>
                </div>
              ))}
            </nav>
            <div className="border-t border-brand-50 p-3">
              <button onClick={logout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted2 hover:bg-danger/10 hover:text-danger" data-testid="vendor-logout">
                <LogOut size={18} aria-hidden /> {t("nav.logout")}
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
                  {approved && (
                    <Link to="/vendor/notifications" className="hg-icon-btn relative" aria-label={unread ? t("vx.unread", { n: unread }) : t("vx.nav.notifications")} data-testid="vendor-bell">
                      <Bell size={19} aria-hidden />
                      {unread > 0 && <span className="absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-hg-violet px-1 text-[11px] font-bold text-white">{unread}</span>}
                    </Link>
                  )}
                  <span className="hg-icon-btn !hidden sm:!inline-flex"><ThemeToggle /></span>
                  <LanguageSwitcher />
                </div>
              </div>
            </header>

            <motion.main id="vendor-main" tabIndex={-1} key={loc.pathname} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28 }}
              className="mx-auto min-h-[calc(100vh-4rem)] max-w-6xl px-4 pb-28 pt-6 outline-none lg:px-8 lg:pb-16">
              <Outlet />
            </motion.main>
          </div>

          {/* phones: four key destinations + a full menu */}
          <nav className="glass-nav fixed inset-x-0 bottom-0 z-40 flex border-t border-brand-50 lg:hidden" aria-label={t("vp.portal")} style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
            {flat.filter((i) => BOTTOM.includes(i.id)).map((i) => (
              <Link key={i.to} to={i.to} aria-current={active(i.to) ? "page" : undefined} data-testid={`vendor-tab-${i.id}`}
                className={`flex min-h-[3.5rem] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium ${active(i.to) ? "text-hg-lavender" : "text-muted2"}`}>
                <i.icon size={20} aria-hidden /> <span className="max-w-full truncate px-1">{t(i.key)}</span>
              </Link>
            ))}
            <button onClick={() => setMenu(true)} className="flex min-h-[3.5rem] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted2" data-testid="vendor-menu-open" aria-haspopup="dialog">
              <Menu size={20} aria-hidden /> {t("vx.nav.more")}
            </button>
          </nav>
          <Sheet open={menu} onOpenChange={setMenu}>
            <SheetContent side="bottom" className="max-h-[85vh] overflow-y-auto rounded-t-3xl" data-testid="vendor-menu">
              <SheetHeader><SheetTitle>{t("vp.portal")}</SheetTitle></SheetHeader>
              <div className="mt-3 space-y-4">
                {groups.map((g) => (
                  <div key={g.key}>
                    <div className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-muted2">{t(g.key)}</div>
                    <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-2">{g.items.map((i) => <NavItem key={i.to} i={i} compact />)}</div>
                  </div>
                ))}
                <div className="flex items-center justify-between gap-3 border-t border-brand-50 pt-3">
                  <ThemeToggle />
                  <button onClick={logout} className="flex items-center gap-2 rounded-full px-4 py-2 text-sm font-medium text-danger" data-testid="vendor-logout-mobile"><LogOut size={16} aria-hidden /> {t("nav.logout")}</button>
                </div>
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </MotionConfig>
    </VendorCtx.Provider>
  );
}
