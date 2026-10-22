import React, { useEffect, useState } from "react";
import { Link, useLocation, Outlet } from "react-router-dom";
import { motion } from "framer-motion";
import {
  LayoutDashboard, ShoppingBag, Package, Coins, Share2, Banknote, Gift, Home,
  Bell, User, LogOut, ChevronLeft, ShoppingCart, Sun, Moon,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { useCart } from "@/context/CartContext";
import { useTheme } from "@/context/ThemeContext";
import { API } from "@/lib/api";

const NAV = [
  { to: "/app/dashboard", icon: LayoutDashboard, key: "nav.dashboard" },
  { to: "/app/products", icon: ShoppingBag, key: "nav.products" },
  { to: "/app/rewards", icon: Gift, key: "nav.rewards" },
  { to: "/app/orders", icon: Package, key: "nav.orders" },
  { to: "/app/wallet", icon: Coins, key: "nav.wallet" },
  { to: "/app/withdrawals", icon: Banknote, key: "nav.withdrawals" },
  { to: "/app/referral", icon: Share2, key: "nav.referral" },
  { to: "/app/notifications", icon: Bell, key: "nav.notifications" },
  { to: "/app/profile", icon: User, key: "nav.profile" },
];

// Mobile bottom bar: two tabs, the raised Rewards button, two tabs.
const BOTTOM_LEFT = [
  { to: "/app/dashboard", icon: Home, key: "nav.home" },
  { to: "/app/products", icon: ShoppingBag, key: "nav.shop" },
];
const BOTTOM_RIGHT = [
  { to: "/app/orders", icon: Package, key: "nav.orders" },
  { to: "/app/profile", icon: User, key: "nav.profile" },
];

const TITLES = [
  ["/app/products", "nav.shop"], ["/app/rewards", "nav.rewards"], ["/app/orders", "nav.orders"],
  ["/app/wallet", "nav.wallet"], ["/app/withdrawals", "nav.withdrawals"], ["/app/referral", "nav.referral"],
  ["/app/notifications", "nav.notifications"], ["/app/profile", "nav.profile"], ["/app/cart", "nav.cart"],
  ["/app/checkout", "nav.checkout"],
];

export function AppLayout() {
  const { t, lang, setLang } = useI18n();
  const { user, logout } = useAuth();
  const { count } = useCart();
  const { theme, toggle } = useTheme();
  const loc = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    API.get("/notifications").then(({ data }) => setUnread(data.unread)).catch(() => {});
    window.scrollTo(0, 0); // each tab opens at its top, like a native app
  }, [loc.pathname]);

  const active = (to) => loc.pathname === to || (to !== "/app/dashboard" && loc.pathname.startsWith(to + "/"));
  const isHome = loc.pathname === "/app/dashboard";
  const titleKey = (TITLES.find(([p]) => loc.pathname.startsWith(p)) || [])[1];

  const NavItem = ({ item }) => {
    const Icon = item.icon;
    const isActive = active(item.to);
    return (
      <Link
        to={item.to}
        data-testid={`nav-${item.key.split(".")[1]}`}
        className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
          isActive ? "bg-brand-50 text-forest" : "text-muted2 hover:bg-brand-50/60 hover:text-forest"
        }`}
      >
        {isActive && <motion.span layoutId="side-pill" className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-hg-violet" transition={{ type: "spring", stiffness: 500, damping: 36 }} />}
        <Icon size={18} className="shrink-0 transition-transform duration-200 group-hover:scale-110" />
        {!collapsed && <span className="truncate transition-transform duration-200 group-hover:translate-x-0.5">{t(item.key)}</span>}
      </Link>
    );
  };

  const Tab = ({ item }) => {
    const Icon = item.icon;
    const on = active(item.to);
    return (
      <Link to={item.to} className={`flex flex-col items-center gap-1.5 pt-3 pb-2 text-xs font-medium transition-colors ${on ? "text-hg-violet" : "text-muted2"}`}
        data-testid={`bottom-${item.key.split(".")[1]}`}>
        <motion.span whileTap={{ scale: 0.85 }} className="relative flex h-10 w-10 items-center justify-center">
          {on && (
            <motion.span layoutId="bottom-pill" className="absolute inset-0 rounded-full bg-hg-violet/20"
              transition={{ type: "spring", stiffness: 500, damping: 34 }} />
          )}
          <motion.span className="relative" animate={{ y: on ? -1 : 0, scale: on ? 1.08 : 1 }} transition={{ type: "spring", stiffness: 400, damping: 22 }}>
            <Icon size={22} />
          </motion.span>
        </motion.span>
        {t(item.key)}
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Desktop Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 hidden flex-col border-r border-brand-50 bg-white lg:flex transition-all duration-300 ${
          collapsed ? "w-[76px]" : "w-64"
        }`}
      >
        <div className="flex h-16 items-center justify-between px-4 border-b border-brand-50">
          {collapsed ? <Logo size="sm" showText={false} /> : <Logo size="sm" dark={theme === "dark"} />}
          <button onClick={() => setCollapsed(!collapsed)} className="text-muted2 hover:text-forest" data-testid="sidebar-toggle">
            <ChevronLeft size={18} className={`transition-transform ${collapsed ? "rotate-180" : ""}`} />
          </button>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto p-3 no-scrollbar">
          {NAV.map((i) => <NavItem key={i.to} item={i} />)}
        </nav>
        <div className="border-t border-brand-50 p-3">
          <button onClick={logout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted2 hover:bg-danger/10 hover:text-danger transition-all" data-testid="logout-btn">
            <LogOut size={18} />{!collapsed && t("nav.logout")}
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className={`transition-all duration-300 ${collapsed ? "lg:pl-[76px]" : "lg:pl-64"}`}>
        <header className="sticky top-0 z-30 glass-nav px-4 lg:px-8" style={{ top: "env(safe-area-inset-top, 0px)" }}>
          <div className="flex h-[72px] items-center justify-between gap-3">
            {/* Mobile shows the page title like the app; desktop keeps the greeting
                because each page renders its own heading there. */}
            <div className={`min-w-0 items-center gap-3 ${isHome || !titleKey ? "flex" : "hidden lg:flex"}`}>
              <span className="lg:hidden"><Logo size="sm" showText={false} /></span>
              <div className="min-w-0">
                <div className="text-sm text-muted2">{t("home.welcome")}</div>
                <div className="truncate bg-gradient-to-r from-hg-lavender to-hg-pink bg-clip-text font-display text-xl font-semibold text-transparent" data-testid="header-user-name">
                  {user?.full_name}
                </div>
              </div>
            </div>
            {!isHome && titleKey && (
              <div className="truncate font-display text-2xl font-semibold text-ink lg:hidden" data-testid="header-title">{t(titleKey)}</div>
            )}
            <div className="flex shrink-0 items-center gap-2">
              <button onClick={() => setLang(lang === "en" ? "hi" : "en")} className="hg-icon-btn font-hindi text-base font-semibold active:scale-90 transition-transform" aria-label="Switch language" data-testid="language-switcher">
                {lang === "en" ? "हि" : "EN"}
              </button>
              <button onClick={toggle} className="hg-icon-btn !hidden sm:!inline-flex" aria-label="Toggle theme" data-testid="theme-toggle">
                {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
              </button>
              <Link to="/app/cart" className="hg-icon-btn relative active:scale-90 transition-transform" aria-label={t("nav.cart")} data-testid="header-cart">
                <ShoppingCart size={20} />
                {count > 0 && <span key={count} className="hg-pop absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-hg-violet px-1 text-[11px] font-bold text-white">{count}</span>}
              </Link>
              <Link to="/app/notifications" className="hg-icon-btn relative active:scale-90 transition-transform" aria-label={t("nav.notifications")} data-testid="header-notifications">
                <Bell size={20} />
                {unread > 0 && <span key={unread} className="hg-pop absolute -right-1.5 -top-1.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-hg-violet px-1 text-[11px] font-bold text-white">{unread}</span>}
              </Link>
            </div>
          </div>
        </header>
          <motion.main
            key={loc.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="hg-main mx-auto max-w-7xl px-4 pb-36 pt-5 lg:px-8 lg:pb-10"
          >
            <Outlet />
          </motion.main>
      </div>

      {/* Mobile bottom nav with the raised Rewards button */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 border-t border-brand-50 bg-white/95 backdrop-blur-lg lg:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }} data-testid="mobile-bottom-nav">
        <div className="grid grid-cols-5 items-end">
          {BOTTOM_LEFT.map((i) => <Tab key={i.to} item={i} />)}
          <Link to="/app/rewards" className="flex flex-col items-center pb-2" data-testid="bottom-rewards">
            <motion.span whileTap={{ scale: 0.9 }} whileHover={{ y: -3 }} transition={{ type: "spring", stiffness: 420, damping: 22 }}
              className={`hg-sheen -mt-8 flex h-[68px] w-[68px] items-center justify-center rounded-[1.4rem] border-4 border-white hg-orange dark:border-hg-bg ${active("/app/rewards") ? "ring-2 ring-hg-gold/60" : "hg-pulse-ring"}`}>
              <motion.span animate={active("/app/rewards") ? { rotate: [0, -12, 10, 0], scale: [1, 1.12, 1] } : {}} transition={{ duration: 0.6 }}>
                <Gift size={30} />
              </motion.span>
            </motion.span>
            <span className={`mt-1.5 text-xs font-semibold ${active("/app/rewards") ? "text-hg-gold" : "text-hg-gold/85"}`}>{t("nav.rewards")}</span>
          </Link>
          {BOTTOM_RIGHT.map((i) => <Tab key={i.to} item={i} />)}
        </div>
      </nav>
    </div>
  );
}
