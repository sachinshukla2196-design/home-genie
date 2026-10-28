import React, { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { ShieldCheck, X, BadgeIndianRupee, Trash2, ShoppingCart, Clock, IndianRupee } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

const STATUSES = ["payment_pending", "paid", "processing", "packed", "shipped", "delivered", "cancelled", "refunded"];

const PAY_PILL = (st) => st === "paid"
  ? "bg-hg-success/15 text-hg-success ring-hg-success/25"
  : st === "claimed" || st === "cod_pending" || st === "partially_refunded"
    ? "bg-hg-gold/15 text-hg-gold ring-hg-gold/25"
    : st === "refunded"
      ? "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/25"
      : "bg-danger/10 text-danger ring-danger/25";

const TH = "whitespace-nowrap px-4 py-3 font-semibold";

function OrderTab({ on, onClick, testid, children }) {
  return (
    <button onClick={onClick} data-testid={testid} aria-pressed={on}
      className={`relative shrink-0 whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors ${on ? "text-white" : "hg-chip-off"}`}>
      {on && <motion.span layoutId="admin-orders-tab" className="hg-chip-on absolute inset-0 rounded-full" transition={{ type: "spring", stiffness: 480, damping: 34 }} />}
      <span className="relative">{children}</span>
    </button>
  );
}

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

  const [queue, setQueue] = useState({ items: [], open_count: 0 });
  const load = useCallback(() => {
    API.get("/admin/refund-queue", { params: { page_size: 100 } }).then(({ data }) => setQueue(data)).catch(() => {});
    return API.get("/admin/orders").then(({ data }) => setOrders(data)).catch(() => setOrders([]));
  }, []);
  useEffect(() => { load(); }, [load]);

  const change = async (id, status) => { try { await API.put(`/admin/orders/${id}/status`, { status }); toast.success(t("cta.save")); load(); } catch (e) { toast.error(apiError(e)); } };

  // Collection needs the amount actually received, the evidence type and a reference. Nothing is assumed or pre-filled,
  // and the server repeats every check. A manual exception is held for finance review, not marked paid.
  const EVIDENCE_TYPES = [
    ["courier_confirmation", "Courier confirmation"],
    ["provider_confirmation", "Provider confirmation"],
    ["manual_exception", "Manual exception (held for review)"],
  ];
  const REFERENCE_RE = /^[A-Za-z0-9][A-Za-z0-9 ._/#:-]{2,119}$/;
  const emptyCod = { evidenceType: "courier_confirmation", reference: "", amount: "", note: "" };
  const [codFor, setCodFor] = useState(null);
  const [cod, setCod] = useState(emptyCod);
  const [codBusy, setCodBusy] = useState(false);
  const [codError, setCodError] = useState("");
  const openCod = (o) => { setCod(emptyCod); setCodError(""); setCodFor(o); };
  const closeCod = () => { if (!codBusy) setCodFor(null); };
  const codProblem = () => {
    const amount = Number(cod.amount);
    if (cod.amount.trim() === "" || !Number.isFinite(amount) || amount <= 0) return "Enter the amount actually collected as a positive number.";
    if (!/^\d+(\.\d{1,2})?$/.test(cod.amount.trim())) return "The amount can have at most 2 decimal places.";
    if (!REFERENCE_RE.test(cod.reference.trim())) return "Enter the courier or provider reference (3 to 120 characters: letters, digits, space and . _ / # : -).";
    return "";
  };
  const submitCod = async () => {
    if (codBusy) return;
    const problem = codProblem();
    if (problem) { setCodError(problem); return; }
    setCodBusy(true); setCodError("");
    try {
      const { data } = await API.post(`/orders/${codFor.id}/cod-collected`, {
        amount_collected: Number(cod.amount), evidence_type: cod.evidenceType,
        evidence_reference: cod.reference.trim(), note: cod.note.trim(),
      });
      toast.success(data.discrepancy ? "Recorded as a discrepancy for finance review" : "Cash collection recorded");
      setCodFor(null);
      load();
    } catch (err) { setCodError(apiError(err)); } finally { setCodBusy(false); }
  };

  const refundOrder = async (o) => {
    const remaining = (o.total - (o.refunded_amount || 0)).toFixed(2);
    const amt = window.prompt(`Refund amount for ${o.order_number} (max ₹${remaining}). Leave as is for FULL refund:`, remaining);
    if (amt === null) return;
    const ref = window.prompt("Refund payment reference (UTR / Razorpay refund id) — mandatory:");
    if (!ref || !ref.trim()) { toast.error("Refund reference is mandatory"); return; }
    const cancel = window.confirm("Also mark this order as CANCELLED? (OK = cancelled, Cancel = keep status)");
    try {
      const { data } = await API.post(`/admin/orders/${o.id}/refund`, { amount: Number(amt), reference: ref.trim(), cancel_order: cancel });
      toast.success(`Refunded ₹${data.refund_amount} · ${data.reversed} credit(s) clawed back`);
      load();
    } catch (e) { toast.error(apiError(e)); }
  };

  const deleteOrder = async (o) => {
    if (!window.confirm(`Permanently DELETE order ${o.order_number} (${money(o.total)})? This cannot be undone.`)) return;
    try {
      await API.delete(`/admin/orders/${o.id}`);
      setOrders((list) => list.filter((x) => x.id !== o.id));
      toast.success("Order deleted");
    } catch (e) { toast.error(apiError(e)); }
  };

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
    if (!did) { toast.error("Enter a HomeGenie ID"); return; }
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

  if (!orders) return (
    <div className="space-y-5">
      <PageHeader title={t("nav.orders")} icon={ShoppingCart} />
      <div className="grid gap-4 sm:grid-cols-2">{[0, 1].map((i) => <Skeleton key={i} className="h-28 rounded-[20px]" />)}</div>
      <Skeleton className="h-96 rounded-[20px]" />
    </div>
  );

  const claimedCount = orders.filter((o) => o.payment_status === "claimed").length;
  const paidOrders = orders.filter((o) => o.payment_status === "paid" && !o.needs_refund);   // refund-pending money is not "collected"
  const upiCollected = paidOrders.reduce((s, o) => s + Number(o.total || 0), 0);
  const shown = tab === "refund" ? queue.items : tab === "paid" ? paidOrders : orders;

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.orders")} icon={ShoppingCart} />
      <div className="grid gap-4 sm:grid-cols-2">
        <StatCard testid="stat-upi-pending" icon={Clock} accent="gold" label="Awaiting confirm" value={claimedCount} index={0} />
        <StatCard testid="stat-upi-collected" icon={IndianRupee} accent="success" label="Total collected" value={money(upiCollected)} index={1} />
      </div>

      {/* Manual payment by HomeGenie ID */}
      <SectionCard testid="manual-payment-card">
        <div className="flex items-start gap-3">
          <span className="hg-icon-chip !h-10 !w-10 shrink-0 !rounded-xl"><BadgeIndianRupee size={20} /></span>
          <div className="min-w-0">
            <h3 className="font-display text-lg font-semibold text-ink">Record Manual Payment</h3>
            <p className="mt-0.5 text-sm text-muted2">Enter an existing HomeGenie ID to mark the payment as PAID (admin/manual). Recorded &amp; audited.</p>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div>
            <Label className="text-sm text-ink">HomeGenie ID</Label>
            <Input value={manual.distributor_id} onChange={(e) => setManual((m) => ({ ...m, distributor_id: e.target.value }))} placeholder="HG000123" className="mt-1.5 font-mono uppercase" data-testid="manual-distributor-id" />
          </div>
          <div>
            <Label className="text-sm text-ink">Reference / UTR</Label>
            <Input value={manual.reference} onChange={(e) => setManual((m) => ({ ...m, reference: e.target.value }))} placeholder="e.g. 4123XXXX / cash" className="mt-1.5 font-mono" data-testid="manual-reference" />
          </div>
          <div>
            <Label className="text-sm text-ink">Note (optional)</Label>
            <Input value={manual.note} onChange={(e) => setManual((m) => ({ ...m, note: e.target.value }))} placeholder="reason" className="mt-1.5" data-testid="manual-note" />
          </div>
          <div className="flex items-end">
            <Button onClick={recordManual} disabled={manualBusy} className="hg-btn h-11 w-full rounded-full px-6" data-testid="manual-record-btn">{manualBusy ? "Recording…" : "Mark Paid"}</Button>
          </div>
        </div>
      </SectionCard>

      {/* Tabs */}
      <div className="no-scrollbar -mx-4 flex gap-2 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0">
        <OrderTab on={tab === "all"} onClick={() => setTab("all")} testid="tab-all">All Orders ({orders.length})</OrderTab>
        <OrderTab on={tab === "paid"} onClick={() => setTab("paid")} testid="tab-paid">Paid ({paidOrders.length})</OrderTab>
        <OrderTab on={tab === "refund"} onClick={() => setTab("refund")} testid="tab-refund">Needs refund ({queue.open_count})</OrderTab>
      </div>

      {tab === "refund" && (
        <p className="rounded-2xl bg-hg-gold/10 p-3 text-sm text-ink ring-1 ring-hg-gold/30" data-testid="refund-queue-note">
          These customers paid for an order that had <b>already expired or been cancelled</b> (and could not be restored), so it cannot be
          fulfilled. No invoice or commission was created. Refund each one (oldest first). The vendor cannot see these orders.
        </p>
      )}
      <div className="hg-card overflow-hidden" data-testid={tab === "refund" ? "refund-list" : tab === "paid" ? "paid-list" : "orders-list"}>
        <div className="overflow-x-auto">
        <table className="w-full min-w-[1100px] text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className={TH}>{t("order.number")}</th><th className={TH}>HomeGenie</th><th className={TH}>Date</th><th className={`${TH} text-right`}>{t("order.total")}</th><th className={TH}>Payment</th><th className={TH}>Method</th><th className={TH}>Reference ID</th><th className={TH}>{t("order.status")}</th><th className={TH}>Invoice</th><th className={TH}>Action</th></tr></thead>
          <tbody>
            {shown.map((o) => (
              <tr key={o.id} className="border-t border-brand-50 align-middle transition-colors hover:bg-brand-50/60" data-testid={`admin-order-${o.order_number}`}>
                <td className="whitespace-nowrap px-4 py-3 font-medium text-ink">{o.order_number}</td>
                <td className="px-4 py-3 font-mono text-hg-lavender" data-testid={`order-dist-${o.order_number}`}>{o.distributor_id}<div className="max-w-[160px] truncate font-sans text-xs text-muted2">{o.user_name}</div>
                  {tab === "refund" && <div className="font-sans text-xs text-hg-gold" data-testid={`waiting-${o.order_number}`}>{o.user_mobile} · waiting {o.waiting_hours ?? "?"}h</div>}</td>
                <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted2">{(o.created_at || "").slice(0, 10)}</td>
                <td className="whitespace-nowrap px-4 py-3 text-right font-semibold tabular-nums text-ink">{money(o.total)}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${PAY_PILL(o.payment_status)}`}>{o.payment_status}</span>
                    {o.payment_method === "cod" && o.payment_status === "cod_pending" && <button onClick={() => openCod(o)} className="whitespace-nowrap rounded-full bg-hg-gold px-3 py-1 text-xs font-semibold text-hg-bg transition-transform hover:-translate-y-0.5" data-testid={`cod-collect-${o.order_number}`}>Cash collected</button>}
                    {o.payment_status === "claimed" && <button onClick={() => { setConfirmFor(o); setReference(o.upi_reference || ""); }} className="hg-btn whitespace-nowrap rounded-full px-3 py-1 text-xs font-semibold text-white transition-transform hover:-translate-y-0.5" data-testid={`upi-confirm-${o.order_number}`}>Confirm UPI</button>}
                  </div>
                </td>
                <td className="px-4 py-3 text-xs uppercase text-muted2">{o.payment_method || "—"}</td>
                <td className="px-4 py-3 font-mono text-xs text-muted2" data-testid={`ref-${o.order_number}`}>{o.payment_reference || o.upi_reference || "—"}</td>
                <td className="px-4 py-3">
                  <Select value={o.status} onValueChange={(v) => change(o.id, v)}>
                    <SelectTrigger className="h-9 w-36 rounded-full text-xs" data-testid={`order-status-${o.order_number}`}><SelectValue /></SelectTrigger>
                    <SelectContent>{STATUSES.map((s) => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                  </Select>
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-muted2">{o.invoice_number || "—"}</td>
                <td className="px-4 py-3">
                  {(o.payment_status === "paid" || o.payment_status === "partially_refunded") && (
                    <button onClick={() => refundOrder(o)} className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-hg-gold/50 px-3 py-1.5 text-xs font-semibold text-hg-gold transition-colors hover:bg-hg-gold/10" data-testid={`refund-order-${o.order_number}`}>
                      Refund{o.refunded_amount ? ` (₹${o.refunded_amount} done)` : ""}
                    </button>
                  )}
                  {o.payment_status !== "paid" && o.payment_status !== "partially_refunded" && o.payment_status !== "refunded" && (
                  <button onClick={() => deleteOrder(o)} className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-danger/40 px-3 py-1.5 text-xs font-semibold text-danger transition-colors hover:bg-danger/10" data-testid={`delete-order-${o.order_number}`}>
                    <Trash2 size={13} /> Delete
                  </button>
                  )}
                </td>
              </tr>
            ))}
            {shown.length === 0 && <tr><td colSpan={10} className="px-4 py-12 text-center text-muted2">{tab === "refund" ? "No refunds waiting. 🎉" : "No orders here yet."}</td></tr>}
          </tbody>
        </table>
        </div>
      </div>

      <AnimatePresence>
        {confirmFor && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={() => !saving && setConfirmFor(null)} data-testid="upi-confirm-modal">
            <motion.div initial={{ scale: 0.94, y: 12 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.94, y: 12 }}
              onClick={(e) => e.stopPropagation()} className="hg-glass w-full max-w-md rounded-3xl p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <span className="hg-icon-chip !h-10 !w-10 shrink-0 !rounded-xl"><ShieldCheck size={20} /></span>
                  <div className="min-w-0">
                    <h3 className="font-display text-lg font-semibold text-ink">Confirm UPI Payment</h3>
                    <p className="text-xs text-muted2">Order {confirmFor.order_number} · {money(confirmFor.total)}</p>
                  </div>
                </div>
                <button onClick={() => setConfirmFor(null)} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted2 transition-colors hover:bg-brand-50 hover:text-ink" data-testid="close-confirm-modal"><X size={18} /></button>
              </div>
              <div className="mt-5">
                <Label className="text-sm text-ink">Payment Reference ID (UTR / Txn ID) <span className="text-danger">*</span></Label>
                <Input autoFocus value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. 412345678901"
                  className="mt-1.5 font-mono" data-testid="upi-reference-input"
                  onKeyDown={(e) => e.key === "Enter" && submitConfirm()} />
              </div>
              <div className="mt-6 flex flex-wrap gap-3">
                <Button variant="outline" onClick={() => setConfirmFor(null)} className="h-11 flex-1 rounded-full border-brand-50 bg-transparent" data-testid="cancel-confirm-btn">Cancel</Button>
                <Button onClick={submitConfirm} disabled={saving || !reference.trim()} className="hg-btn h-11 flex-1 rounded-full" data-testid="submit-confirm-btn">{saving ? "Confirming…" : "Confirm & Activate"}</Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {codFor && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={closeCod} data-testid="cod-collect-modal">
            <motion.form initial={{ scale: 0.94, y: 12 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.94, y: 12 }} noValidate
              onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); submitCod(); }}
              className="hg-glass w-full max-w-md rounded-3xl p-5 sm:p-6">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-display text-lg font-semibold text-ink">Record cash collection</h3>
                  <p className="text-xs text-muted2">Order {codFor.order_number} · order total {money(codFor.total)}</p>
                </div>
                <button type="button" onClick={closeCod} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted2 transition-colors hover:bg-brand-50 hover:text-ink" data-testid="close-cod-modal"><X size={18} /></button>
              </div>
              <div className="mt-5 space-y-4">
                <div>
                  <Label className="text-sm text-ink">Evidence type <span className="text-danger">*</span></Label>
                  <Select value={cod.evidenceType} onValueChange={(v) => setCod({ ...cod, evidenceType: v })}>
                    <SelectTrigger className="mt-1.5" data-testid="cod-evidence-type"><SelectValue /></SelectTrigger>
                    <SelectContent>{EVIDENCE_TYPES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-sm text-ink">Courier or provider reference <span className="text-danger">*</span></Label>
                  <Input autoFocus value={cod.reference} onChange={(e) => setCod({ ...cod, reference: e.target.value })} maxLength={120}
                    placeholder="e.g. AWB-1234567" className="mt-1.5 font-mono" data-testid="cod-reference-input" />
                </div>
                <div>
                  <Label className="text-sm text-ink">Amount actually collected (₹) <span className="text-danger">*</span></Label>
                  <Input inputMode="decimal" value={cod.amount} onChange={(e) => setCod({ ...cod, amount: e.target.value })}
                    placeholder="Enter the amount received" className="mt-1.5" data-testid="cod-amount-input" />
                </div>
                <div>
                  <Label className="text-sm text-ink">Note (optional)</Label>
                  <Input value={cod.note} onChange={(e) => setCod({ ...cod, note: e.target.value })} maxLength={300} className="mt-1.5" data-testid="cod-note-input" />
                </div>
                {codError && <p role="alert" className="text-sm text-danger" data-testid="cod-error">{codError}</p>}
              </div>
              <div className="mt-6 flex flex-wrap gap-3">
                <Button type="button" variant="outline" onClick={closeCod} className="h-11 flex-1 rounded-full border-brand-50 bg-transparent" data-testid="cod-cancel-btn">Cancel</Button>
                <Button type="submit" disabled={codBusy} className="hg-btn h-11 flex-1 rounded-full" data-testid="cod-submit-btn">{codBusy ? "Recording…" : "Record collection"}</Button>
              </div>
            </motion.form>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
