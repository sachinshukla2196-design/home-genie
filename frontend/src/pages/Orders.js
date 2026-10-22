import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Package, ChevronRight } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { Stagger, StaggerItem } from "@/components/motion";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

const STATUS_COLORS = {
  paid: "bg-hg-success/15 text-hg-success ring-hg-success/30",
  processing: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30",
  shipped: "bg-hg-violet/15 text-hg-violet ring-hg-lavender/30 dark:text-hg-lavender",
  delivered: "bg-hg-success/15 text-hg-success ring-hg-success/30",
  payment_pending: "bg-danger/10 text-danger ring-danger/25",
  cancelled: "bg-danger/10 text-danger ring-danger/25",
};

export default function Orders() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [orders, setOrders] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  useEffect(() => { API.get("/orders").then(({ data }) => setOrders(data)).catch(() => setOrders([])); }, []);

  if (!orders) return <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}</div>;

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.orders")} icon={Package} />
      {orders.length === 0 ? (
        <EmptyState icon={Package} title={t("empty.orders")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="orders-empty" />
      ) : (
        <Stagger className="space-y-3">
          {orders.map((o) => (
            <StaggerItem key={o.id}>
              <motion.button whileHover={{ y: -2 }} whileTap={{ scale: 0.99 }} onClick={() => navigate(`/app/orders/${o.id}`)} data-testid={`order-row-${o.order_number}`}
                className="hg-card hg-lift group flex w-full items-center gap-3 p-4 text-left sm:gap-4 sm:p-5">
                <span className="hg-icon-chip hidden shrink-0 sm:inline-flex"><Package size={20} /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
                    <span className="truncate font-display font-semibold text-ink">{o.order_number}</span>
                    <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${STATUS_COLORS[o.status] || "bg-brand-50 text-muted2 ring-brand-50"}`}>{o.status}</span>
                    {o.payment_method === "cod" && <span className="rounded-full bg-hg-gold/15 px-2.5 py-0.5 text-[11px] font-semibold text-hg-gold ring-1 ring-hg-gold/30" data-testid={`cod-tag-${o.order_number}`}>{o.payment_status === "paid" ? t("order.cod") : t("order.codPending")}</span>}
                  </div>
                  <div className="mt-1 text-sm text-muted2">{(o.created_at || "").slice(0, 10)} · {o.items.length} {t("order.items")}</div>
                </div>
                <div className="shrink-0 font-display text-lg font-semibold tabular-nums text-hg-violet dark:text-hg-lavender">{money(o.total)}</div>
                <ChevronRight size={18} className="hidden shrink-0 text-muted2 transition-transform group-hover:translate-x-0.5 sm:block" />
              </motion.button>
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}
