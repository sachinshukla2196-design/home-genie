import React, { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ArrowLeft, ClipboardList, Download, Loader2, Package, Search, Truck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { API, apiError } from "@/lib/api";
import { downloadCsv } from "@/components/vendor/kit";
import { useAuth } from "@/context/AuthContext";

const rupees = (p) => `₹${(Number(p || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const SELECT = "h-10 rounded-xl bg-white px-3 text-sm text-ink ring-1 ring-brand-100 dark:bg-white/5 dark:ring-white/15";
const PAY = ["", "pending", "claimed", "paid", "partially_refunded", "refunded", "cod_pending", "cod_discrepancy", "claim_expired"];
const ST = ["", "pending", "processing", "shipped", "delivered", "cancelled", "refunded"];
const FUL = ["", "new", "accepted", "packed", "dispatched", "delivered", "rejected", "cancelled", "delivery_failed", "returned_to_origin"];
const label = (s) => (s ? s.replace(/_/g, " ") : "any");

/** Batch 14: one Orders area. "All orders" is the authoritative list; the other tabs are working queues on the same orders. */
export function OrdersTabs({ active }) {
  const { user } = useAuth();
  const finance = ["super_admin", "accounts_admin"].includes(user?.role);
  const tabs = [["all", "All orders", "/admin/orders"], ["exceptions", "Payment exceptions", "/admin/orders/exceptions"],
    ...(finance ? [["events", "Payment events", "/admin/orders/events"]] : [])];
  return (
    <nav className="flex flex-wrap gap-2" aria-label="Orders sections" data-testid="orders-tabs">
      {tabs.map(([k, l, to]) => <Link key={k} to={to} aria-current={active === k ? "page" : undefined}
        className={`inline-flex h-10 items-center rounded-full px-5 text-sm font-semibold ${active === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{l}</Link>)}
    </nav>
  );
}

/** Batch 13, Phase 9 (ADM-06): order lookup with server-side filters, sorting, paging and an authorised export. */
export default function AdminOrderOps() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [f, setF] = useState({ q: "", payment_status: "", status: "", fulfilment: "", method: "", refund: "", frm: "", to: "", sort: "created:desc" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [d, setD] = useState(null);
  const params = useCallback(() => {
    const [sort, order] = f.sort.split(":");
    const p = { ...f, q: f.q || undefined, sort, order, page, page_size: 20 };
    Object.keys(p).forEach((k) => (p[k] === "" ? delete p[k] : null));
    return p;
  }, [f, page]);
  useEffect(() => { setD(null); API.get("/admin/order-ops/orders", { params: params() }).then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))); }, [params]);
  const set = (k) => (e) => { setPage(1); setF({ ...f, [k]: e.target.value }); };
  const canExport = ["super_admin", "admin", "accounts_admin"].includes(user?.role);

  return (
    <div className="space-y-5">
      <OrdersTabs active="all" />
      <PageHeader title="Orders" subtitle="Find any order and see every vendor's part, payment, return, refund and commission." icon={ClipboardList}
        actions={canExport && <Button variant="outline" className="h-11 rounded-full" onClick={() => { const p = params(); delete p.page; delete p.page_size; delete p.sort; delete p.order; downloadCsv("/admin/order-ops/orders.csv", "orders.csv", p).catch((e) => toast.error(apiError(e))); }}><Download size={15} /> Export CSV</Button>} />
      <form className="hg-card grid gap-2 p-4 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => { e.preventDefault(); setPage(1); setF({ ...f, q }); }}>
        <div className="flex gap-2 sm:col-span-2"><Input aria-label="Search orders" placeholder="Order number, customer name, mobile or account ID" value={q} onChange={(e) => setQ(e.target.value)} className="h-10 rounded-xl" data-testid="oo-search" />
          <Button type="submit" className="hg-btn h-10 rounded-full"><Search size={15} /></Button></div>
        <select aria-label="Payment status" className={SELECT} value={f.payment_status} onChange={set("payment_status")}>{PAY.map((x) => <option key={x} value={x}>Payment: {label(x)}</option>)}</select>
        <select aria-label="Order status" className={SELECT} value={f.status} onChange={set("status")}>{ST.map((x) => <option key={x} value={x}>Order: {label(x)}</option>)}</select>
        <select aria-label="Fulfilment status" className={SELECT} value={f.fulfilment} onChange={set("fulfilment")}>{FUL.map((x) => <option key={x} value={x}>Vendor step: {label(x)}</option>)}</select>
        <select aria-label="Payment method" className={SELECT} value={f.method} onChange={set("method")}><option value="">Method: any</option><option value="online">Prepaid</option><option value="cod">Cash on delivery</option></select>
        <select aria-label="Refund" className={SELECT} value={f.refund} onChange={set("refund")}><option value="">Refund: any</option><option value="none">No refund</option><option value="partial">Partly refunded</option><option value="full">Fully refunded</option><option value="open_case">Open refund case</option></select>
        <select aria-label="Sort" className={SELECT} value={f.sort} onChange={set("sort")}><option value="created:desc">Newest first</option><option value="created:asc">Oldest first</option><option value="total:desc">Highest total</option><option value="total:asc">Lowest total</option></select>
        <label className="flex items-center gap-2 text-xs text-muted2">From <Input type="date" value={f.frm} onChange={set("frm")} className="h-10 rounded-xl" /></label>
        <label className="flex items-center gap-2 text-xs text-muted2">To <Input type="date" value={f.to} onChange={set("to")} className="h-10 rounded-xl" /></label>
      </form>
      {!d ? <Loader2 className="animate-spin text-muted2" /> : d.items.length === 0 ? <p className="text-sm text-muted2">No orders match.</p> : (
        <>
          <ul className="space-y-2" data-testid="oo-list">
            {d.items.map((o) => (
              <li key={o.id}><button onClick={() => navigate(`/admin/orders/${o.id}`)} className="hg-card flex w-full flex-wrap items-center justify-between gap-2 p-3 text-left text-sm hover:bg-brand-50/50">
                <span className="min-w-0"><span className="font-mono font-semibold text-ink">{o.order_number}</span> <span className="text-xs text-muted2">· {(o.created_at || "").slice(0, 10)} · {o.customer.name} {o.customer.mobile}</span>
                  <span className="block text-xs text-muted2">{o.fulfilment.map((x) => `${x.vendor_name || "Vendor"}: ${label(x.status)}`).join(" · ") || "Platform goods"}</span></span>
                <span className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-[11px] font-semibold">{label(o.payment_status)}</span>
                  <span className="rounded-full bg-brand-50 px-2.5 py-0.5 text-[11px] font-semibold">{label(o.status)}</span>
                  {o.flags.map((fl) => <span key={fl} className="rounded-full bg-danger/10 px-2.5 py-0.5 text-[11px] font-semibold text-danger">{label(fl)}</span>)}
                  <span className="font-semibold tabular-nums">{rupees(o.total_paise)}</span></span>
              </button></li>
            ))}
          </ul>
          <div className="flex items-center justify-end gap-2 text-sm"><span className="mr-auto text-muted2">{d.total} orders</span>
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-full">Previous</Button>
            <span className="text-muted2">{page} / {d.pages}</span>
            <Button variant="outline" size="sm" disabled={page >= d.pages} onClick={() => setPage(page + 1)} className="rounded-full">Next</Button></div>
        </>
      )}
    </div>
  );
}

function Row({ k, v }) { return <div className="flex justify-between gap-3 py-1 text-sm"><dt className="text-muted2">{k}</dt><dd className="text-right tabular-nums text-ink">{v ?? "—"}</dd></div>; }

/** /admin/orders/:id — every source for one order. Money actions stay on their own endpoints (Orders page and Operations). */
export function AdminOrderDetail() {
  const { id } = useParams();
  const [d, setD] = useState(null);
  const [st, setSt] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => API.get(`/admin/order-ops/orders/${id}`).then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))), [id]);
  useEffect(() => { load(); }, [load]);
  const changeStatus = async () => {
    setBusy(true);
    try { await API.put(`/admin/orders/${id}/status`, { status: st, reason }); toast.success("Status changed and recorded."); setSt(""); setReason(""); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  if (!d) return <Loader2 className="animate-spin text-muted2" />;
  const o = d.order;
  return (
    <div className="space-y-5" data-testid="order-detail">
      <Link to="/admin/orders" className="inline-flex items-center gap-1 text-xs text-muted2 hover:text-ink"><ArrowLeft size={13} /> Orders</Link>
      <PageHeader title={o.order_number} subtitle={`${(o.created_at || "").slice(0, 16).replace("T", " ")} UTC · ${o.payment_method === "cod" ? "Cash on delivery" : "Prepaid"} · payment ${label(o.payment_status)} · order ${label(o.status)}`} icon={Package} />
      <PaymentActions o={o} vendors={d.vendors} />
      <div className="grid gap-5 lg:grid-cols-3">
        <SectionCard title="Money" className="min-w-0">
          <dl>
            <Row k="Goods (GST included)" v={rupees(o.items_total_paise ?? o.total_paise - (o.cod_fee_paise || 0))} />
            <Row k="GST contained" v={o.gst_amount != null ? `₹${o.gst_amount}` : null} />
            <Row k="COD fee" v={rupees(o.cod_fee_paise || 0)} />
            <Row k="Total" v={rupees(o.total_paise)} />
            <Row k="Refunded" v={rupees(o.refunded_paise || 0)} />
            <Row k="Payment reference" v={o.payment_reference} />
            <Row k="Invoice" v={o.invoice_number} />
            {o.duplicate_payments?.length > 0 && <Row k="Duplicate captures" v={o.duplicate_payments.map((x) => x.status).join(", ")} />}
            {o.cod_discrepancy && <Row k="COD discrepancy" v={label(o.cod_discrepancy.status)} />}
          </dl>
        </SectionCard>
        <SectionCard title="Customer and delivery address" className="min-w-0">
          <dl>
            <Row k="Customer" v={`${d.customer.name || ""} (${d.customer.account_id || "—"})`} />
            <Row k="Mobile" v={d.customer.mobile} /><Row k="E-mail" v={d.customer.email} />
            {d.customer.masked && <p className="text-xs text-muted2">Contact masked for your role.</p>}
          </dl>
          <p className="mt-2 text-sm text-ink">{d.address?.full_name}, {[d.address?.line1, d.address?.line2, d.address?.landmark, d.address?.city, d.address?.state, d.address?.pincode].filter(Boolean).join(", ")} · {d.address?.mobile}</p>
          <p className="mt-1 text-xs text-muted2">Snapshot taken when the order was placed.</p>
          {d.seller && <p className="mt-2 text-xs text-muted2">Attributed to HomeGenie {d.seller.distributor_id}</p>}
        </SectionCard>
        <SectionCard title="Delivery and payouts" icon={Truck} className="min-w-0">
          <dl>
            <Row k="Whole order delivered" v={d.delivery.order_delivered_at ? d.delivery.order_delivered_at.slice(0, 10) : "Not yet"} />
            <Row k="Commission payable?" v={d.delivery.order_payout_block ? label(d.delivery.order_payout_block) : "Yes"} />
          </dl>
          <p className="mt-2 text-xs text-muted2">{d.delivery.note}</p>
          {o.status_set_by_admin && <p className="mt-2 text-xs text-hg-gold">An admin set the order status to {o.status_set_by_admin.status} on {o.status_set_by_admin.at?.slice(0, 10)} (not a delivery record).</p>}
        </SectionCard>
      </div>
      <SectionCard title="Items" className="min-w-0">
        <div className="-mx-1 overflow-x-auto"><table className="w-full min-w-[560px] text-sm">
          <thead><tr className="text-left text-xs uppercase text-muted2"><th className="px-2 py-1.5">Item</th><th className="px-2">Vendor</th><th className="px-2">Qty</th><th className="px-2">Price</th><th className="px-2">Taxable</th><th className="px-2">GST</th><th className="px-2">Line total</th></tr></thead>
          <tbody>{(o.items || []).map((li, i) => (
            <tr key={i} className="border-t border-brand-50"><td className="px-2 py-2">{li.name}{li.variant ? ` · ${li.variant}` : ""}<div className="font-mono text-xs text-muted2">{li.variant_sku || li.sku}</div></td>
              <td className="px-2">{li.vendor_name || "HOME GENIES"}</td><td className="px-2">{li.quantity}</td><td className="px-2">₹{li.price}</td>
              <td className="px-2">{li.taxable_paise != null ? rupees(li.taxable_paise) : "—"}</td><td className="px-2">{li.gst_paise != null ? `${rupees(li.gst_paise)} (${li.gst_rate}%)` : "—"}</td>
              <td className="px-2 font-semibold">{rupees(li.total_paise)}</td></tr>))}</tbody></table></div>
      </SectionCard>
      {d.vendors.map((v) => (
        <SectionCard key={v.vendor_id} title={`${v.vendor_name || "Vendor"} — ${label(v.status)}`} icon={Truck} className="min-w-0" testid="od-vendor">
          <div className="grid gap-4 md:grid-cols-2">
            <div><dl><Row k="Goods" v={rupees(v.goods_paise)} /><Row k="Delivered" v={v.delivered_at ? v.delivered_at.slice(0, 10) : "Not yet"} />
              <Row k="Delivery evidence" v={v.delivery_evidence} /><Row k="Tracking" v={[v.carrier, v.tracking_number].filter(Boolean).join(" ")} />
              <Row k="Vendor payable now?" v={v.payout_block ? label(v.payout_block) : "Yes"} /><Row k="Ledger net" v={rupees(v.ledger_net_paise)} /></dl></div>
            <ol className="space-y-1 text-xs">{v.timeline.map((e, i) => <li key={i} className="flex gap-2"><span className="text-muted2">{(e.at || "").slice(0, 16).replace("T", " ")}</span><span className="font-semibold">{label(e.status)}</span><span className="text-muted2">{e.note}</span></li>)}</ol>
          </div>
          {v.ledger.length > 0 && <div className="mt-3 text-xs text-muted2">Ledger: {v.ledger.map((e) => `${label(e.type)} ${rupees(e.amount_paise)}`).join(" · ")}</div>}
        </SectionCard>
      ))}
      <div className="grid gap-5 lg:grid-cols-2">
        <SectionCard title="Payments" className="min-w-0">{d.payments.length === 0 ? <p className="text-sm text-muted2">No payment attempts.</p> :
          <ul className="space-y-1 text-sm">{d.payments.map((p) => <li key={p.session_id} className="flex justify-between gap-2"><span className="truncate font-mono text-xs">{p.provider || "gateway"} {p.session_id}</span><span>{label(p.payment_status)} · ₹{p.amount}</span></li>)}</ul>}
          <p className="mt-2 text-xs text-muted2">Gateway webhooks are recorded per event, not per order, so they are not listed here.</p></SectionCard>
        <SectionCard title="Commission" className="min-w-0">{d.commissions.length === 0 ? <p className="text-sm text-muted2">No commission on this order.</p> :
          <ul className="space-y-1 text-sm">{d.commissions.map((c) => <li key={c.id} className="flex justify-between gap-2"><span>{c.member} · {label(c.type)}</span><span>{rupees(c.amount_paise)}{c.reversed_paise ? ` (−${rupees(c.reversed_paise)})` : ""} · {label(c.status)}</span></li>)}</ul>}</SectionCard>
        <SectionCard title="Returns" className="min-w-0">{d.returns.length === 0 ? <p className="text-sm text-muted2">No returns.</p> :
          <ul className="space-y-1 text-sm">{d.returns.map((r) => <li key={r.id} className="flex justify-between gap-2"><span>{r.number || r.id.slice(0, 8)} · {r.kind}</span><span>{label(r.status)}</span></li>)}</ul>}</SectionCard>
        <SectionCard title="Refund cases" className="min-w-0">{d.refund_cases.length === 0 ? <p className="text-sm text-muted2">No refund cases.</p> :
          <ul className="space-y-1 text-sm">{d.refund_cases.map((r) => <li key={r.id} className="flex justify-between gap-2"><span>{r.number} · {label(r.kind)}</span><span>{rupees(r.amount_paise)} · {label(r.status)}</span></li>)}</ul>}
          <Link to="/admin/operations" className="mt-2 inline-block text-xs font-medium underline">Handle refunds in Operations</Link></SectionCard>
      </div>
      <SectionCard title="Change order status" className="min-w-0">
        <p className="text-xs text-muted2">For vendor goods, delivery is recorded by the vendor; changing the status here is recorded with your reason and does not make money payable.</p>
        <div className="mt-3 grid gap-2 sm:grid-cols-[200px_1fr_auto]">
          <select aria-label="New status" className={SELECT} value={st} onChange={(e) => setSt(e.target.value)}><option value="">Choose…</option>{ST.filter(Boolean).map((x) => <option key={x} value={x}>{label(x)}</option>)}</select>
          <Textarea rows={1} placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" />
          <Button onClick={changeStatus} disabled={busy || !st || reason.trim().length < 5} className="hg-btn rounded-full">Change</Button>
        </div>
      </SectionCard>
      <SectionCard title="History" className="min-w-0">
        <ol className="space-y-1 text-xs">{d.audit.map((a, i) => <li key={i} className="flex flex-wrap gap-2"><span className="text-muted2">{(a.created_at || "").slice(0, 16).replace("T", " ")}</span><span className="font-semibold">{label(a.action)}</span><span className="text-muted2">{a.user_email || ""} {a.new_value?.reason ? `— ${a.new_value.reason}` : ""}</span></li>)}</ol>
      </SectionCard>
    </div>
  );
}


/** Batch 14: what this order needs from finance / operations, linking to the one place each action is done (no duplicate actions). */
function PaymentActions({ o, vendors }) {
  const items = [];
  const q = encodeURIComponent(o.order_number);
  if (o.payment_status === "claimed") items.push(["The customer says they paid by UPI. Finance confirms it with the bank reference and the exact amount.", `/admin/orders/exceptions?tab=claimed&q=${q}`, "Confirm or reject the UPI payment"]);
  if (o.payment_status === "cod_pending" && o.status !== "cancelled") items.push([vendors.every((v) => ["delivered", "rejected", "cancelled", "returned_to_origin"].includes(v.status)) ? "Cash on delivery: record the collection with courier evidence." : "Cash on delivery: collection is recorded after the vendor delivers.", `/admin/orders/exceptions?tab=cod&q=${q}`, "Open cash on delivery"]);
  if (o.payment_status === "cod_discrepancy") items.push(["The collected cash differed from the expected amount; finance reviews it.", "/admin/operations", "Review COD discrepancy"]);
  if (o.needs_refund || o.refund_due_cancel) items.push(["This paid order cannot be fulfilled and must be refunded.", "/admin/operations", "Open refunds"]);
  if ((o.duplicate_payments || []).some((x) => x.status === "refund_due")) items.push(["A second payment was captured and must be returned.", "/admin/operations", "Open duplicate payments"]);
  if (!items.length) return null;
  return (
    <div className="hg-card border border-hg-gold/40 p-4" data-testid="od-actions">
      <div className="text-sm font-semibold text-ink">Action needed</div>
      <ul className="mt-2 space-y-2">{items.map(([text, to, cta]) => (
        <li key={cta} className="flex flex-wrap items-center justify-between gap-2 text-sm"><span className="text-muted2">{text}</span>
          <Link to={to} className="hg-btn inline-flex h-9 items-center rounded-full px-4 text-xs font-semibold text-white">{cta}</Link></li>))}</ul>
    </div>
  );
}

const EV_TONE = { processed: "bg-hg-success/15 text-hg-success", failed: "bg-danger/10 text-danger", rejected: "bg-danger/10 text-danger",
  unmatched: "bg-hg-gold/15 text-hg-gold", processing: "bg-hg-gold/15 text-hg-gold", ignored: "bg-brand-50 text-muted2" };

/** Batch 14: payment gateway events (finance only). Failed or stuck events can be retried; final outcomes cannot. */
export function AdminPaymentEvents() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [d, setD] = useState(null);
  const load = useCallback(() => API.get("/admin/payment-events", { params: { status: status || undefined, page, page_size: 20 } })
    .then(({ data }) => setD(data)).catch((e) => toast.error(apiError(e))), [status, page]);
  useEffect(() => { setD(null); load(); }, [load]);
  const retry = async (id) => {
    try { const { data } = await API.post(`/admin/payment-events/${encodeURIComponent(id)}/retry`); toast.success(`Retried: ${label(data.status)}${data.reason ? ` — ${data.reason}` : ""}`); load(); }
    catch (e) { toast.error(apiError(e)); }
  };
  return (
    <div className="space-y-5">
      <OrdersTabs active="events" />
      <PageHeader title="Payment events" subtitle="Every payment notification from the gateway: what it matched, whether it was applied, and why not." icon={ClipboardList} />
      {d && <div className="flex flex-wrap gap-2 text-sm">{Object.entries(d.attention).map(([k, v]) => <span key={k} className={`rounded-full px-3 py-1 ${v ? EV_TONE[k] : "bg-brand-50 text-muted2"}`}>{label(k)}: {v}</span>)}</div>}
      <select aria-label="Status" className={SELECT} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
        {["", "failed", "rejected", "unmatched", "processing", "processed", "ignored"].map((x) => <option key={x} value={x}>Status: {x ? label(x) : "all"}</option>)}
      </select>
      {!d ? <Loader2 className="animate-spin text-muted2" /> : d.items.length === 0 ? <p className="text-sm text-muted2">No payment events{status ? ` with status ${label(status)}` : ""}.</p> : (
        <ul className="space-y-2" data-testid="pe-list">
          {d.items.map((e) => (
            <li key={e.event_id} className="hg-card flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
              <span className="min-w-0"><span className="font-mono text-xs text-ink">{e.event_id}</span> <span className="text-xs text-muted2">· {e.type} · {(e.created_at || "").slice(0, 16).replace("T", " ")}</span>
                <span className="block text-xs text-muted2">{e.reason || "—"}{e.amount_paise != null ? ` · ${rupees(e.amount_paise)} ${e.currency || ""}` : ""}</span></span>
              <span className="flex items-center gap-2">
                <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${EV_TONE[e.status] || ""}`}>{label(e.status)}</span>
                {e.order_id && <Link to={`/admin/orders/${e.order_id}`} className="text-xs font-medium underline">Order</Link>}
                {["failed", "processing"].includes(e.status) && <Button size="sm" variant="outline" className="rounded-full" onClick={() => retry(e.event_id)} data-testid="pe-retry">Retry</Button>}
              </span>
            </li>
          ))}
        </ul>
      )}
      {d && d.pages > 1 && <div className="flex justify-end gap-2 text-sm"><Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)} className="rounded-full">Previous</Button>
        <span className="text-muted2">{page} / {d.pages}</span><Button variant="outline" size="sm" disabled={page >= d.pages} onClick={() => setPage(page + 1)} className="rounded-full">Next</Button></div>}
    </div>
  );
}
