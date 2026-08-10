import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Package } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { API } from "@/lib/api";

const STATUS_COLORS = {
  paid: "bg-brand-50 text-brand", processing: "bg-gold-light text-gold", shipped: "bg-blue-50 text-blue-700",
  delivered: "bg-brand-50 text-brand", payment_pending: "bg-danger/10 text-danger", cancelled: "bg-danger/10 text-danger",
};

export default function Orders() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [orders, setOrders] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  useEffect(() => { API.get("/orders").then(({ data }) => setOrders(data)).catch(() => setOrders([])); }, []);

  if (!orders) return <div className="space-y-3">{[...Array(4)].map((_, i) => <Skeleton key={i} className="h-20 rounded-xl" />)}</div>;

  return (
    <div>
      <h1 className="mb-6 font-display text-2xl font-semibold text-ink">{t("nav.orders")}</h1>
      {orders.length === 0 ? (
        <EmptyState icon={Package} title={t("empty.orders")} ctaLabel={t("cta.shopNow")} onCta={() => navigate("/app/products")} testid="orders-empty" />
      ) : (
        <div className="space-y-3">
          {orders.map((o) => (
            <button key={o.id} onClick={() => navigate(`/app/orders/${o.id}`)} data-testid={`order-row-${o.order_number}`}
              className="flex w-full items-center justify-between rounded-2xl border border-brand-50 bg-white p-5 text-left hover:shadow-card transition-all">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-display font-semibold text-ink">{o.order_number}</span>
                  <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${STATUS_COLORS[o.status] || "bg-muted text-muted2"}`}>{o.status}</span>
                </div>
                <div className="mt-1 text-sm text-muted2">{(o.created_at || "").slice(0, 10)} · {o.items.length} {t("order.items")}</div>
              </div>
              <div className="font-display text-lg font-semibold text-forest">{money(o.total)}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
