import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { RotateCcw, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusBadge } from "@/components/StatusBadge";
import { API, apiError } from "@/lib/api";

const rupees = (v) => `₹${Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const CANCELLABLE = (o) => !["cancelled", "refunded", "delivered", "shipped"].includes(o.status)
  && !(o.fulfilments || []).some((f) => ["dispatched", "delivered", "returned_to_origin"].includes(f.status));
const delivered = (o) => o.status === "delivered" || (o.fulfilments || []).some((f) => f.status === "delivered");

/** Batch 8: the customer's own rights on an order — cancel, return / replacement, and refund status. Everything is decided by
 *  the server (eligibility, return window, quantities already returned); this panel only asks and shows the answer. */
export function OrderSelfService({ order, onChange }) {
  const [returns, setReturns] = useState([]);
  const [open, setOpen] = useState(false);
  const [qty, setQty] = useState({});
  const [kind, setKind] = useState("return");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const load = () => API.get("/returns").then(({ data }) => setReturns(data.filter((r) => r.order_id === order.id))).catch(() => setReturns([]));
  useEffect(() => { load(); }, [order.id]);   // eslint-disable-line react-hooks/exhaustive-deps

  const cancel = async () => {
    const why = window.prompt("Why do you want to cancel this order?", "");
    if (why === null) return;
    setBusy(true);
    try { const { data } = await API.post(`/orders/${order.id}/cancel`, { reason: why.trim() || "Changed my mind" }); toast.success(data.message || "Cancellation recorded"); onChange(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const lines = (order.items || []).filter((li) => li.vendor_id);
  const chosen = Object.entries(qty).filter(([, q]) => q > 0);
  const submitReturn = async () => {
    setBusy(true);
    try {
      const items = chosen.map(([k, q]) => { const li = lines[Number(k)]; return { product_id: li.product_id, variant_sku: li.variant_sku || null, quantity: q }; });
      await API.post(`/orders/${order.id}/returns`, { kind, items, reason: reason.trim(), photos: [] });
      toast.success(kind === "return" ? "Return requested" : "Replacement requested");
      setOpen(false); setQty({}); setReason(""); load(); onChange();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const refunded = Number(order.refunded_amount || 0);
  return (
    <div className="mt-6 space-y-4 border-t border-brand-50 pt-5 print:hidden" data-testid="order-self-service">
      {(refunded > 0 || ["refunded", "partially_refunded"].includes(order.payment_status)) && (
        <p className="text-sm text-ink" data-testid="order-refund-status">Refunded so far: <b>{rupees(refunded)}</b> <StatusBadge status={order.payment_status} /></p>
      )}
      <div className="flex flex-wrap gap-2">
        {CANCELLABLE(order) && <Button variant="outline" onClick={cancel} disabled={busy} className="h-11 rounded-full border-danger/40 px-5 text-danger hover:bg-danger/10" data-testid="order-cancel"><XCircle size={16} className="mr-1.5" /> Cancel order</Button>}
        {delivered(order) && lines.length > 0 && <Button variant="outline" onClick={() => setOpen((x) => !x)} className="h-11 rounded-full px-5" data-testid="order-return-open"><RotateCcw size={16} className="mr-1.5" /> Return or replace</Button>}
      </div>
      {open && (
        <div className="space-y-3 rounded-2xl p-4 ring-1 ring-brand-50" data-testid="order-return-form">
          <div className="flex gap-2" role="radiogroup" aria-label="Return or replacement">
            {[["return", "Return for refund"], ["replacement", "Replacement"]].map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={kind === v} onClick={() => setKind(v)} className={`h-9 rounded-full px-4 text-sm font-semibold ${kind === v ? "hg-chip-on text-white" : "hg-chip-off"}`}>{l}</button>))}
          </div>
          {lines.map((li, i) => (
            <label key={i} className="flex items-center justify-between gap-3 text-sm text-ink">
              <span className="min-w-0 truncate">{li.name}{li.variant ? ` · ${li.variant}` : ""} <span className="text-muted2">(bought {li.quantity})</span></span>
              <Input type="number" min="0" max={li.quantity} value={qty[i] || 0} onChange={(e) => setQty((q) => ({ ...q, [i]: Math.max(0, Math.min(li.quantity, parseInt(e.target.value || "0", 10))) }))} className="h-9 w-20" aria-label={`Quantity of ${li.name} to return`} data-testid={`return-qty-${i}`} />
            </label>
          ))}
          <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="What is wrong? (at least 5 characters)" data-testid="return-reason" />
          <Button onClick={submitReturn} disabled={busy || !chosen.length || reason.trim().length < 5} className="hg-btn h-11 rounded-full px-6" data-testid="return-submit">Submit request</Button>
          <p className="text-xs text-muted2">Requests are accepted within the return window after delivery. Some categories cannot be returned.</p>
        </div>
      )}
      {returns.length > 0 && (
        <div data-testid="order-returns">
          <h4 className="text-sm font-semibold text-ink">Your return requests</h4>
          <ul className="mt-2 space-y-1.5 text-sm">
            {returns.map((r) => <li key={r.id} className="flex flex-wrap items-center gap-2"><span className="font-mono">{r.number}</span><StatusBadge status={r.status} /><span className="text-muted2">{r.kind}{r.suggested_refund ? ` · refund ${rupees(r.suggested_refund)}` : ""}</span></li>)}
          </ul>
        </div>
      )}
    </div>
  );
}
