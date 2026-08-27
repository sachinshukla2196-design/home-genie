import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { ShieldCheck, X, BadgeIndianRupee } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const STATUSES = ["payment_pending", "paid", "processing", "packed", "shipped", "delivered", "cancelled", "refunded"];

export default function AdminOrders() {
  const { t } = useI18n();
  const [orders, setOrders] = useState(null);
  const [tab, setTab] = useState("all");
  const [confirmFor, setConfirmFor] = useState(null);
  const [reference, setReference] = useState("");
  const [saving, setSaving] = useState(false);
  const [manual, setManual] = useState({ distributor_id: "", reference: "", note: "" });
  const [manualBusy, setManualBusy] = useState(false);
  const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

  const load = () => API.get("/admin/orders").then(({ data }) => setOrders(data)).catch(() => setOrders([]));
  useEffect(() => { load(); }, []);

  const change = async (id, status) => { try { await API.put(`/admin/orders/${id}/status`, { status }); toast.success(t("cta.save")); load(); } catch (e) { toast.error(apiError(e)); } };

  const submitConfirm = async () => {
    const ref = reference.trim();
    if (!ref) { toast.error("Reference ID is mandatory"); return; }
    setSaving(true);
    try {
      await API.put(`/admin/payments/upi-confirm/${confirmFor.id}`, { reference: ref });
      toast.success(`Payment confirmed & activated · Ref ${ref}`);
      setConfirmFor(null); setReference(""); load();
    } catch (e) { toast.error(apiError(e)); } finally { setSaving(false); }
  };

  const recordManual = async () => {
    const did = manual.distributor_id.trim().toUpperCase();
    const ref = manual.reference.trim();
    if (!did) { toast.error("Enter a Distributor ID"); return; }
    if (!ref) { toast.error("Enter a payment reference / reason"); return; }
    setManualBusy(true);
    try {
      const { data } = await API.post("/admin/payments/manual", { distributor_id: did, reference: ref, note: manual.note.trim() });
      toast.success(data.message || "Payment recorded");
      setManual({ distributor_id: "", reference: "", note: "" });
      setTab("paid");
      load();
    } catch (e) { toast.error(apiError(e)); } finally { setManualBusy(false); }
  };

  if (!orders) return <Skeleton className="h-96 rounded-2xl" />;

  const claimedCount = orders.filter((o) => o.payment_status === "claimed").length;
  const paidOrders = orders.filter((o) => o.payment_status === "paid");
  const upiCollected = paidOrders.reduce((s, o) => s + Number(o.total || 0), 0);
  const shown = tab === "paid" ? paidOrders : orders;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.orders")}</h1>
        <div className="flex gap-3">
          <div className="rounded-xl border border-gold/30 bg-gold-light/40 px-4 py-2" data-testid="stat-upi-pending">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted2">Awaiting confirm</div>
            <div className="font-display text-lg font-semibold text-forest">{claimedCount}</div>
          </div>
          <div className="rounded-xl border border-brand-50 bg-brand-50/50 px-4 py-2" data-testid="stat-upi-collected">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-muted2">Total collected</div>
            <div className="font-display text-lg font-semibold text-forest">{money(upiCollected)}</div>
          </div>
        </div>
      </div>

      {/* Manual payment by Distributor ID */}
      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="manual-payment-card">
        <div className="flex items-center gap-2.5">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-forest"><BadgeIndianRupee size={20} /></div>
          <div>
            <h3 className="font-display text-lg font-medium text-ink">Record Manual Payment</h3>
            <p className="text-xs text-muted2">Enter an existing Distributor ID to mark their payment as PAID (admin/manual). Recorded &amp; audited.</p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div>
            <Label className="text-xs text-muted2">Distributor ID</Label>
            <Input value={manual.distributor_id} onChange={(e) => setManual((m) => ({ ...m, distributor_id: e.target.value }))} placeholder="ANJ000123" className="mt-1 h-10 font-mono uppercase" data-testid="manual-distributor-id" />
          </div>
          <div>
            <Label className="text-xs text-muted2">Reference / UTR</Label>
            <Input value={manual.reference} onChange={(e) => setManual((m) => ({ ...m, reference: e.target.value }))} placeholder="e.g. 4123XXXX / cash" className="mt-1 h-10 font-mono" data-testid="manual-reference" />
          </div>
          <div>
            <Label className="text-xs text-muted2">Note (optional)</Label>
            <Input value={manual.note} onChange={(e) => setManual((m) => ({ ...m, note: e.target.value }))} placeholder="reason" className="mt-1 h-10" data-testid="manual-note" />
          </div>
          <div className="flex items-end">
            <Button onClick={recordManual} disabled={manualBusy} className="h-10 w-full rounded-full bg-forest hover:bg-brand" data-testid="manual-record-btn">{manualBusy ? "Recording…" : "Mark Paid"}</Button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2">
        <button onClick={() => setTab("all")} className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-all ${tab === "all" ? "bg-forest text-white" : "border border-brand-50 text-muted2 hover:text-forest"}`} data-testid="tab-all">All Orders ({orders.length})</button>
        <button onClick={() => setTab("paid")} className={`rounded-full px-4 py-1.5 text-sm font-semibold transition-all ${tab === "paid" ? "bg-forest text-white" : "border border-brand-50 text-muted2 hover:text-forest"}`} data-testid="tab-paid">Paid ({paidOrders.length})</button>
      </div>

      <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card" data-testid={tab === "paid" ? "paid-list" : "orders-list"}>
        <table className="w-full text-sm">
          <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">{t("order.number")}</th><th className="p-4">Distributor</th><th className="p-4 text-right">{t("order.total")}</th><th className="p-4">Payment</th><th className="p-4">Method</th><th className="p-4">Reference ID</th><th className="p-4">{t("order.status")}</th><th className="p-4">Invoice</th></tr></thead>
          <tbody>
            {shown.map((o) => (
              <tr key={o.id} className="border-b border-brand-50/60 transition-colors hover:bg-brand-50/30" data-testid={`admin-order-${o.order_number}`}>
                <td className="p-4 font-medium text-ink">{o.order_number}</td>
                <td className="p-4 font-mono text-forest" data-testid={`order-dist-${o.order_number}`}>{o.distributor_id}</td>
                <td className="p-4 text-right font-medium text-ink">{money(o.total)}</td>
                <td className="p-4"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${o.payment_status === "paid" ? "bg-brand-50 text-brand" : o.payment_status === "claimed" ? "bg-gold-light text-gold" : "bg-danger/10 text-danger"}`}>{o.payment_status}</span>
                  {o.payment_status === "claimed" && <button onClick={() => { setConfirmFor(o); setReference(o.upi_reference || ""); }} className="ml-2 rounded-full bg-forest px-2.5 py-1 text-[11px] font-semibold text-white transition-all hover:bg-brand hover:-translate-y-0.5" data-testid={`upi-confirm-${o.order_number}`}>Confirm UPI</button>}
                </td>
                <td className="p-4 text-xs text-muted2">{o.payment_method || "—"}</td>
                <td className="p-4 font-mono text-xs text-muted2" data-testid={`ref-${o.order_number}`}>{o.payment_reference || o.upi_reference || "—"}</td>
                <td className="p-4">
                  <Select value={o.status} onValueChange={(v) => change(o.id, v)}>
                    <SelectTrigger className="h-8 w-36 text-xs" data-testid={`order-status-${o.order_number}`}><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </td>
                <td className="p-4 text-muted2">{o.invoice_number || "—"}</td>
              </tr>
            ))}
            {shown.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-muted2">No orders here yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <AnimatePresence>
        {confirmFor && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => !saving && setConfirmFor(null)} data-testid="upi-confirm-modal">
            <motion.div initial={{ scale: 0.94, y: 12 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.94, y: 12 }}
              onClick={(e) => e.stopPropagation()} className="w-full max-w-md rounded-2xl border border-brand-50 bg-white p-6 shadow-lift">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-forest"><ShieldCheck size={20} /></div>
                  <div>
                    <h3 className="font-display text-lg font-semibold text-ink">Confirm UPI Payment</h3>
                    <p className="text-xs text-muted2">Order {confirmFor.order_number} · {money(confirmFor.total)}</p>
                  </div>
                </div>
                <button onClick={() => setConfirmFor(null)} className="text-muted2 hover:text-ink" data-testid="close-confirm-modal"><X size={18} /></button>
              </div>
              <div className="mt-5">
                <Label className="text-sm text-ink">Payment Reference ID (UTR / Txn ID) <span className="text-danger">*</span></Label>
                <Input autoFocus value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. 412345678901"
                  className="mt-1.5 h-11 rounded-lg font-mono focus-visible:ring-brand" data-testid="upi-reference-input"
                  onKeyDown={(e) => e.key === "Enter" && submitConfirm()} />
              </div>
              <div className="mt-6 flex gap-3">
                <Button variant="outline" onClick={() => setConfirmFor(null)} className="flex-1 rounded-full" data-testid="cancel-confirm-btn">Cancel</Button>
                <Button onClick={submitConfirm} disabled={saving || !reference.trim()} className="flex-1 rounded-full bg-forest hover:bg-brand" data-testid="submit-confirm-btn">{saving ? "Confirming…" : "Confirm & Activate"}</Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
