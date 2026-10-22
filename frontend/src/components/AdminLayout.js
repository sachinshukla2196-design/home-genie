import React, { useEffect } from "react";
import { Link, useLocation, Outlet } from "react-router-dom";
import { motion } from "framer-motion";
import {
  LayoutDashboard, Users, Package, ShoppingCart, Banknote,
  FileBarChart, Settings, ScrollText, LogOut, ShieldCheck, Store,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

const NAV = [
  { to: "/admin", icon: LayoutDashboard, key: "nav.dashboard" },
  { to: "/admin/users", icon: Users, key: "nav.users" },
  { to: "/admin/products", icon: Package, key: "nav.products" },
  { to: "/admin/orders", icon: ShoppingCart, key: "nav.orders" },
  { to: "/admin/withdrawals", icon: Banknote, key: "nav.withdrawals" },
  { to: "/admin/vendors", icon: Store, key: "av.title" },
  { to: "/admin/reports", icon: FileBarChart, key: "nav.reports" },
  { to: "/admin/settings", icon: Settings, key: "nav.settings" },
  { to: "/admin/audit", icon: ScrollText, key: "nav.audit" },
];

export function AdminLayout() {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const loc = useLocation();
  const active = (to) => to === "/admin" ? loc.pathname === "/admin" : loc.pathname.startsWith(to);
  const initials = (user?.full_name || "AD").split(" ").filter(Boolean).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

  useEffect(() => { window.scrollTo(0, 0); }, [loc.pathname]);

  return (
    <div className="min-h-screen bg-background">
      {/* Desktop sidebar */}
      <aside className="glass-nav fixed inset-y-0 left-0 z-40 hidden w-64 flex-col !border-b-0 border-r border-brand-50 lg:flex">
        <div className="flex h-16 items-center gap-2 border-b border-brand-50 px-5">
          <Logo size="sm" />
        </div>
        <div className="px-5 py-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-hg-gold/15 px-2.5 py-1 text-[11px] font-semibold text-hg-gold ring-1 ring-hg-gold/25">
            <ShieldCheck size={12} /> {t("admin.title")}
          </span>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 no-scrollbar" aria-label="Admin">
          {NAV.map((i) => {
            const Icon = i.icon;
            const on = active(i.to);
            return (
              <Link key={i.to} to={i.to} data-testid={`admin-nav-${i.key.split(".")[1]}`} aria-current={on ? "page" : undefined}
                className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${on ? "bg-brand-50 text-ink" : "text-muted2 hover:bg-brand-50/60 hover:text-ink"}`}>
                {on && <motion.span layoutId="admin-side-pill" className="absolute left-0 top-1/2 h-6 w-1 -translate-y-1/2 rounded-r-full bg-hg-violet" transition={{ type: "spring", stiffness: 500, damping: 36 }} />}
                <Icon size={18} className={`shrink-0 transition-transform duration-200 group-hover:scale-110 ${on ? "text-hg-lavender" : ""}`} />
                <span className="truncate transition-transform duration-200 group-hover:translate-x-0.5">{t(i.key)}</span>
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-brand-50 p-3">
          <button onClick={logout} className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-muted2 hover:bg-danger/10 hover:text-danger" data-testid="admin-logout">
            <LogOut size={18} />{t("nav.logout")}
          </button>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="glass-nav sticky top-0 z-30 px-4 lg:px-8" style={{ top: "env(safe-area-inset-top, 0px)" }}>
          <div className="flex h-16 items-center justify-between gap-3">
            <div className="lg:hidden"><Logo size="sm" showText={false} /></div>
            <div className="hidden min-w-0 lg:block">
              <div className="text-xs text-muted2">{t("admin.title")}</div>
              <div className="truncate text-sm font-semibold text-ink">{user?.full_name}</div>
            </div>
            <div className="flex items-center gap-2">
              <span className="hg-icon-btn"><ThemeToggle /></span>
              <LanguageSwitcher />
              <Avatar className="h-10 w-10 ring-2 ring-hg-violet/40">
                <AvatarImage src={user?.photo} className="object-cover" />
                <AvatarFallback className="bg-hg-deep text-xs font-bold text-white">{initials}</AvatarFallback>
              </Avatar>
            </div>
          </div>
          {/* Mobile admin nav */}
          <nav className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-3 lg:hidden" aria-label="Admin">
            {NAV.map((i) => {
              const on = active(i.to);
              return (
                <Link key={i.to} to={i.to} aria-current={on ? "page" : undefined}
                  className={`relative whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-medium ${on ? "text-white" : "hg-chip-off"}`}>
                  {on && <motion.span layoutId="admin-top-pill" className="hg-chip-on absolute inset-0 rounded-full" transition={{ type: "spring", stiffness: 480, damping: 34 }} />}
                  <span className="relative">{t(i.key)}</span>
                </Link>
              );
            })}
            <button onClick={logout} className="whitespace-nowrap rounded-full px-3.5 py-1.5 text-xs font-medium text-danger hg-chip-off">{t("nav.logout")}</button>
          </nav>
        </header>
          <motion.main key={loc.pathname} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.28 }}
            className="mx-auto min-h-[calc(100vh-4rem)] max-w-7xl px-4 pb-16 pt-6 lg:px-8">
            <Outlet />
          </motion.main>
      </div>
    </div>
  );
}
