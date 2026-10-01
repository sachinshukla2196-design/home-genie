import React, { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, Outlet } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import {
  LayoutDashboard, ShoppingBag, Package, Wallet, TrendingUp, Share2, Users,
  ShieldCheck, Banknote, Bell, FileBarChart, User, LifeBuoy, LogOut, Menu, ChevronLeft, MoreHorizontal, ShoppingCart,
} from "lucide-react";
import { Logo } from "@/components/Logo";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ThemeToggle } from "@/components/ThemeToggle";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { useCart } from "@/context/CartContext";
import { API } from "@/lib/api";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";

const NAV = [
  { to: "/app/dashboard", icon: LayoutDashboard, key: "nav.dashboard" },
  { to: "/app/products", icon: ShoppingBag, key: "nav.products" },
  { to: "/app/orders", icon: Package, key: "nav.orders" },
  { to: "/app/wallet", icon: Wallet, key: "nav.wallet" },
  { to: "/app/referral", icon: Share2, key: "nav.referral" },
  { to: "/app/team", icon: Users, key: "nav.team" },
  { to: "/app/kyc", icon: ShieldCheck, key: "nav.kyc" },
  { to: "/app/withdrawals", icon: Banknote, key: "nav.withdrawals" },
  { to: "/app/notifications", icon: Bell, key: "nav.notifications" },
  { to: "/app/profile", icon: User, key: "nav.profile" },
];

const BOTTOM = [
  { to: "/app/dashboard", icon: LayoutDashboard, key: "nav.home" },
  { to: "/app/wallet", icon: TrendingUp, key: "nav.income" },
  { to: "/app/team", icon: Users, key: "nav.team" },
  { to: "/app/orders", icon: Package, key: "nav.orders" },
];

export function AppLayout() {
  const { t } = useI18n();
  const { user, logout } = useAuth();
  const { count } = useCart();
  const loc = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [unread, setUnread] = useState(0);
  const [moreOpen, setMoreOpen] = useState(false);

  useEffect(() => {
    API.get("/notifications").then(({ data }) => setUnread(data.unread)).catch(() => {});
  }, [loc.pathname]);

  const active = (to) => loc.pathname === to;

  const NavItem = ({ item, onClick }) => {
    const Icon = item.icon;
    const isActive = active(item.to);
    return (
      <Link
        to={item.to}
        onClick={onClick}
        data-testid={`nav-${item.key.split(".")[1]}`}
        className={`group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
          isActive ? "bg-brand-50 text-forest" : "text-muted2 hover:bg-brand-50/60 hover:text-forest"
        }`}
      >
        <Icon size={18} className="shrink-0" />
        {!collapsed && <span className="truncate">{t(item.key)}</span>}
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
          {collapsed ? <Logo size="sm" showText={false} /> : <Logo size="sm" />}
          <button onClick={() => setCollapsed(!collapsed)} className="text-muted2 hover:text-forest" data-testid="sidebar-toggle">
            <ChevronLeft size={18} className={`transition-transform ${collapsed ? "rotate-180" : ""}`} />
          </button>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto p-3 no-scrollbar">
          {NAV.map((i) => <NavItem key={i.to} item={i} />)}
        </nav>
        <div className="border-t border-brand-50 p-3">
          <button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium text-muted2 hover:bg-danger/10 hover:text-danger transition-all" data-testid="logout-btn">
            <LogOut size={18} />{!collapsed && t("nav.logout")}
          </button>
        </div>
      </aside>

      {/* Main */}
      <div className={`transition-all duration-300 ${collapsed ? "lg:pl-[76px]" : "lg:pl-64"}`}>
        {/* Header */}
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between gap-3 glass-nav px-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="lg:hidden"><Logo size="sm" showText={false} /></div>
            {user && (
              <div className="hidden sm:flex items-center gap-2">
                <span className="text-sm font-semibold text-forest" data-testid="header-distributor-id">{user.distributor_id}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <ThemeToggle />
            <LanguageSwitcher />
            <Link to="/app/products" className="relative rounded-full p-2 text-muted2 hover:bg-brand-50 hover:text-forest transition-all" data-testid="header-cart">
              <ShoppingCart size={19} />
              {count > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-gold px-1 text-[10px] font-bold text-white">{count}</span>}
            </Link>
            <Link to="/app/notifications" className="relative rounded-full p-2 text-muted2 hover:bg-brand-50 hover:text-forest transition-all" data-testid="header-notifications">
              <Bell size={19} />
              {unread > 0 && <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-bold text-white">{unread}</span>}
            </Link>
            <Link to="/app/profile" data-testid="header-profile">
              <Avatar className="h-9 w-9 border border-brand-50">
                <AvatarImage src={user?.photo} className="object-cover" />
                <AvatarFallback className="bg-forest text-white text-xs font-semibold">
                  {(user?.full_name || "U").slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
            </Link>
          </div>
        </header>

        <AnimatePresence mode="wait">
          <motion.main
            key={loc.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mx-auto max-w-7xl px-4 pb-28 pt-6 lg:px-8 lg:pb-10"
          >
            <Outlet />
          </motion.main>
        </AnimatePresence>
      </div>

      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 right-0 z-40 grid grid-cols-5 border-t border-brand-50 bg-white/95 backdrop-blur-lg lg:hidden" data-testid="mobile-bottom-nav">
        {BOTTOM.map((i) => {
          const Icon = i.icon;
          const isActive = active(i.to);
          return (
            <Link key={i.to} to={i.to} className={`flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium transition-colors ${isActive ? "text-forest" : "text-muted2"}`} data-testid={`bottom-${i.key.split(".")[1]}`}>
              <Icon size={20} />{t(i.key)}
            </Link>
          );
        })}
        <Sheet open={moreOpen} onOpenChange={setMoreOpen}>
          <SheetTrigger asChild>
            <button className="flex flex-col items-center gap-1 py-2.5 text-[11px] font-medium text-muted2" data-testid="bottom-more">
              <MoreHorizontal size={20} />{t("nav.more")}
            </button>
          </SheetTrigger>
          <SheetContent side="bottom" className="rounded-t-2xl">
            <div className="grid grid-cols-3 gap-3 py-4">
              {NAV.map((i) => {
                const Icon = i.icon;
                return (
                  <button key={i.to} onClick={() => { setMoreOpen(false); navigate(i.to); }} className="flex flex-col items-center gap-2 rounded-xl border border-brand-50 p-4 text-xs font-medium text-forest hover:bg-brand-50 transition-all" data-testid={`more-${i.key.split(".")[1]}`}>
                    <Icon size={22} />{t(i.key)}
                  </button>
                );
              })}
              <button onClick={logout} className="flex flex-col items-center gap-2 rounded-xl border border-danger/20 p-4 text-xs font-medium text-danger hover:bg-danger/10 transition-all" data-testid="more-logout">
                <LogOut size={22} />{t("nav.logout")}
              </button>
            </div>
          </SheetContent>
        </Sheet>
      </nav>
    </div>
  );
}
