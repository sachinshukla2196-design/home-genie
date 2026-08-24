import React from "react";
import { Link, useLocation, Outlet } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, Users, Package, ShoppingCart, ShieldCheck, Banknote,
  Share2, FileBarChart, Settings, ScrollText, LogOut, Zap,
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
  { to: "/admin/kyc", icon: ShieldCheck, key: "nav.kyc" },
  { to: "/admin/withdrawals", icon: Banknote, key: "nav.withdrawals" },
  { to: "/admin/commissions", icon: Share2, key: "nav.commissions" },
  { to: "/admin/reports", icon: FileBarChart, key: "nav.reports" },
  { to: "/admin/settings", icon: Settings, key: "nav.settings" },
  { to: "/admin/audit", icon: ScrollText, key: "nav.audit" },
];

export function AdminLayout() {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const loc = useLocation();
  const active = (to) => to === "/admin" ? loc.pathname === "/admin" : loc.pathname.startsWith(to);

  return (
    <div className="min-h-screen bg-forest">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-64 flex-col bg-forest text-white lg:flex">
        <div className="flex h-16 items-center gap-2 px-5 border-b border-white/10">
          <Logo size="sm" dark />
        </div>
        <div className="px-5 py-3">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gold/20 px-2.5 py-1 text-[11px] font-semibold text-gold">
            <Zap size={12} /> {t("admin.title")}
          </span>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 no-scrollbar">
          {NAV.map((i) => {
            const Icon = i.icon;
            return (
              <Link key={i.to} to={i.to} data-testid={`admin-nav-${i.key.split(".")[1]}`}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all ${active(i.to) ? "bg-white/12 text-white" : "text-white/60 hover:bg-white/8 hover:text-white"}`}>
                <Icon size={18} />{t(i.key)}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-white/10 p-3">
          <button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-white/60 hover:bg-white/8 hover:text-white" data-testid="admin-logout">
            <LogOut size={18} />{t("nav.logout")}
          </button>
        </div>
      </aside>

      <div className="lg:pl-64">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 bg-forest/95 backdrop-blur px-4 lg:px-8 border-b border-white/10">
          <div className="flex items-center gap-3 text-white lg:hidden"><Logo size="sm" dark /></div>
          <div className="hidden lg:block text-sm text-white/70">{user?.full_name}</div>
          <div className="flex items-center gap-3">
            <ThemeToggle dark />
            <LanguageSwitcher />
            <Avatar className="h-9 w-9 border border-white/20">
              <AvatarImage src={user?.photo} className="object-cover" />
              <AvatarFallback className="bg-gold text-forest text-xs font-bold">{(user?.full_name || "AD").slice(0, 2).toUpperCase()}</AvatarFallback>
            </Avatar>
          </div>
        </header>

        {/* Mobile admin nav */}
        <div className="flex gap-2 overflow-x-auto bg-forest px-4 py-2 no-scrollbar lg:hidden">
          {NAV.map((i) => (
            <Link key={i.to} to={i.to} className={`whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-medium ${active(i.to) ? "bg-white text-forest" : "bg-white/10 text-white/80"}`}>
              {t(i.key)}
            </Link>
          ))}
        </div>

        <AnimatePresence mode="wait">
          <motion.main key={loc.pathname} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }}
            className="min-h-[calc(100vh-4rem)] rounded-t-3xl bg-background px-4 pb-16 pt-6 lg:px-8">
            <Outlet />
          </motion.main>
        </AnimatePresence>
      </div>
    </div>
  );
}
