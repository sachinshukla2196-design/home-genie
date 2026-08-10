import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const STATUSES = ["payment_pending", "paid", "processing", "packed", "shipped", "delivered", "cancelled", "refunded"];

export default function AdminOrders() {
  const { t } = useI18n();
  const [orders, setOrders] = useState(null);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  const load = () => API.get("/admin/orders").then(({ data }) => setOrders(data)).catch(() => setOrders([]));
  useEffect(() => { load(); }, []);

  const change = async (id, status) => { try { await API.put(`/admin/orders/${id}/status`, { status }); toast.success(t("cta.save")); load(); } catch (e) { toast.error(apiError(e)); } };

  if (!orders) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.orders")}</h1>
      <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">{t("order.number")}</th><th className="p-4">Distributor</th><th className="p-4 text-right">{t("order.total")}</th><th className="p-4">Payment</th><th className="p-4">{t("order.status")}</th><th className="p-4">Invoice</th></tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id} className="border-b border-brand-50/60" data-testid={`admin-order-${o.order_number}`}>
                <td className="p-4 font-medium text-ink">{o.order_number}</td>
                <td className="p-4 text-forest">{o.distributor_id}</td>
                <td className="p-4 text-right font-medium text-ink">{money(o.total)}</td>
                <td className="p-4"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${o.payment_status === "paid" ? "bg-brand-50 text-brand" : "bg-danger/10 text-danger"}`}>{o.payment_status}</span></td>
                <td className="p-4">
                  <Select value={o.status} onValueChange={(v) => change(o.id, v)}>
                    <SelectTrigger className="h-8 w-36 text-xs" data-testid={`order-status-${o.order_number}`}><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </td>
                <td className="p-4 text-muted2">{o.invoice_number || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
