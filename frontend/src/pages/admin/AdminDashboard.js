import React, { useEffect, useState } from "react";
import { Users, UserCheck, UserX, Zap, ShoppingCart, IndianRupee, TrendingUp, LayoutDashboard } from "lucide-react";
import { StatCard } from "@/components/StatCard";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

export default function AdminDashboard() {
  const { t } = useI18n();
  const [d, setD] = useState(null);
  useEffect(() => { API.get("/admin/dashboard").then(({ data }) => setD(data)).catch(() => {}); }, []);
  const money = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

  if (!d) return (
    <div className="space-y-5">
      <PageHeader title={t("admin.title")} icon={LayoutDashboard} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[...Array(8)].map((_, i) => <Skeleton key={i} className="h-28 rounded-[20px]" />)}</div>
    </div>
  );
  const s = d.stats;

  return (
    <div className="space-y-5">
      <PageHeader title={t("admin.title")} icon={LayoutDashboard} />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard testid="adm-total-users" icon={Users} accent="brand" label={t("admin.totalUsers")} value={s.total_users} index={0} />
        <StatCard testid="adm-red" icon={UserX} accent="danger" label={t("admin.redUsers")} value={s.red_users} index={1} />
        <StatCard testid="adm-green" icon={UserCheck} accent="success" label={t("admin.greenUsers")} value={s.green_users} index={2} />
        <StatCard testid="adm-today-reg" icon={Zap} accent="gold" label={t("admin.todayReg")} value={s.today_registrations} index={3} />
        <StatCard testid="adm-today-act" icon={Zap} accent="brand" label={t("admin.todayAct")} value={s.today_activations} index={4} />
        <StatCard testid="adm-today-orders" icon={ShoppingCart} accent="ink" label={t("admin.todayOrders")} value={s.today_orders} index={5} />
        <StatCard testid="adm-today-rev" icon={IndianRupee} accent="gold" label={t("admin.todayRevenue")} value={money(s.today_revenue)} index={6} />
        <StatCard testid="adm-total-rev" icon={TrendingUp} accent="brand" label={t("admin.totalRevenue")} value={money(s.total_revenue)} index={7} />
      </div>
    </div>
  );
}
