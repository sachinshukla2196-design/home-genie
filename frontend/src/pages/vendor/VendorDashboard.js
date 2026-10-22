import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Inbox, PackageCheck, Truck, MapPin, AlertTriangle, Package, Clock, Boxes, IndianRupee, CheckCircle2, ChevronRight, LayoutDashboard } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Stagger, StaggerItem, CountUp, pressable } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";
import { motion } from "framer-motion";

export const FULFIL_TONE = {
  new: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30", accepted: "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/30",
  packed: "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/30", dispatched: "bg-[#5B7CFF]/15 text-[#8FA6FF] ring-[#8FA6FF]/30",
  delivered: "bg-hg-success/15 text-hg-success ring-hg-success/30", delivery_failed: "bg-danger/10 text-danger ring-danger/30",
  rejected: "bg-danger/10 text-danger ring-danger/30", cancelled: "bg-danger/10 text-danger ring-danger/30",
  returned_to_origin: "bg-white/10 text-muted2 ring-white/15",
};
export const inr = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;

export default function VendorDashboard() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [d, setD] = useState(null);
  useEffect(() => { API.get("/vendor/dashboard").then(({ data }) => setD(data)).catch(() => setD(false)); }, []);

  if (d === null) return <div className="space-y-4"><Skeleton className="h-24 rounded-3xl" /><Skeleton className="h-64 rounded-3xl" /></div>;
  if (d === false) return null;

  const queue = [
    { k: "new", label: "vp.q.new", icon: Inbox, tone: "from-[#E0A92E] to-hg-gold", filter: "new" },
    { k: "to_pack", label: "vp.q.pack", icon: PackageCheck, tone: "from-hg-violet to-[#B36BFF]", filter: "accepted" },
    { k: "to_dispatch", label: "vp.q.dispatch", icon: Truck, tone: "from-[#5B7CFF] to-[#8FA6FF]", filter: "packed" },
    { k: "in_transit", label: "vp.q.transit", icon: MapPin, tone: "from-[#2BB98A] to-hg-success", filter: "dispatched" },
    { k: "exceptions", label: "vp.q.exceptions", icon: AlertTriangle, tone: "from-[#D9506A] to-[#FF8BA0]", filter: "delivery_failed" },
  ];

  return (
    <div className="space-y-6" data-testid="vendor-dashboard">
      <PageHeader title={t("vp.dashboard")} subtitle={d.vendor.business_name} icon={LayoutDashboard} />

      {/* Work queue: what needs doing right now */}
      <Stagger className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {queue.map((q) => (
          <StaggerItem as="button" key={q.k} {...pressable} onClick={() => navigate(`/vendor/orders?status=${q.filter}`)}
            className="hg-card hg-lift group p-4 text-left" data-testid={`vq-${q.k}`}>
            <span className={`flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br ${q.tone} text-white shadow-lg`}><q.icon size={18} /></span>
            <div className="mt-3 font-display text-3xl font-bold tabular-nums text-ink"><CountUp value={d.queue[q.k]} /></div>
            <div className="mt-0.5 flex items-center justify-between text-xs font-medium text-muted2">{t(q.label)} <ChevronRight size={14} className="transition-transform group-hover:translate-x-0.5" /></div>
          </StaggerItem>
        ))}
      </Stagger>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard icon={IndianRupee} accent="gold" label={t("vp.k.gross")} value={inr(d.sales.gross_this_month)} index={0} testid="vk-gross" />
        <StatCard icon={CheckCircle2} accent="success" label={t("vp.k.delivered")} value={d.sales.delivered} index={1} testid="vk-delivered" />
        <StatCard icon={Package} accent="brand" label={t("vp.k.live")} value={`${d.products.live} / ${d.products.total}`} index={2} testid="vk-live" />
        <StatCard icon={d.products.low_stock ? Boxes : Clock} accent={d.products.low_stock ? "danger" : "ink"}
          label={d.products.low_stock ? t("vp.k.low") : t("vp.k.pending")} value={d.products.low_stock || d.products.pending_review} index={3} testid="vk-attention" />
      </div>

      <SectionCard title={t("vp.recent")} icon={Inbox}
        action={<button onClick={() => navigate("/vendor/orders")} className="text-sm font-medium text-hg-lavender">{t("cta.viewAll")}</button>}>
        {d.recent.length === 0 ? <p className="hg-tile p-6 text-center text-sm text-muted2">{t("vp.noOrders")}</p> : (
          <div className="space-y-2">
            {d.recent.map((o, i) => (
              <motion.button key={o.id} initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.05 }}
                onClick={() => navigate(`/vendor/orders?open=${o.id}`)}
                className="hg-tile flex w-full items-center justify-between gap-3 p-3 text-left transition-colors hover:bg-brand-50/60">
                <div className="min-w-0">
                  <div className="font-medium text-ink">{o.order_number}</div>
                  <div className="truncate text-xs text-muted2">{o.items.map((li) => `${li.name} ×${li.quantity}`).join(", ")}</div>
                </div>
                <div className="flex shrink-0 items-center gap-3">
                  <span className="hidden font-semibold tabular-nums text-ink sm:inline">{inr(o.items_total)}</span>
                  <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${FULFIL_TONE[o.fulfilment.status]}`}>{t(`vp.f.${o.fulfilment.status}`)}</span>
                </div>
              </motion.button>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
