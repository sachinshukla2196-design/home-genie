import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Briefcase, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

/** OPS-02: one place for the operational queues that previously had no screen. Every tab reads and acts on the real API;
 *  the server enforces every rule (roles, maker-checker, eligibility). Buttons a role cannot use are hidden as a convenience. */
const FINANCE = ["super_admin", "accounts_admin"];
const rupees = (p) => (p == null ? "—" : `₹${(Number(p) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const rs = (v) => (v == null ? "—" : `₹${Number(v).toLocaleString("en-IN")}`);
const day = (s) => (s || "").slice(0, 10);
const ask = (q, def = "") => { const v = window.prompt(q, def); return v === null ? null : v.trim(); };

function useList(url, params) {
  const [state, setState] = useState({ rows: null, error: "" });
  const key = JSON.stringify(params || {});
  const load = useCallback(() => {
    setState({ rows: null, error: "" });
    API.get(url, { params: JSON.parse(key) })
      .then(({ data }) => setState({ rows: Array.isArray(data) ? data : data.items || [], error: "", extra: data }))
      .catch((e) => setState({ rows: [], error: apiError(e) }));
  }, [url, key]);
  useEffect(() => { load(); }, [load]);
  return [state, load];
}

function Table({ state, columns, empty, testid }) {
  if (!state.rows) return <Skeleton className="h-32 rounded-2xl" />;
  if (state.error) return <p className="text-sm text-danger" data-testid={`${testid}-error`}>{state.error}</p>;
  if (!state.rows.length) return <p className="text-sm text-muted2" data-testid={`${testid}-empty`}>{empty}</p>;
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-6" data-testid={testid}>
      <table className="w-full min-w-[720px] text-sm">
        <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2">{columns.map((c) => <th key={c.h} className="px-3 py-2 first:pl-5 last:pr-5 sm:first:pl-6 sm:last:pr-6">{c.h}</th>)}</tr></thead>
        <tbody>{state.rows.map((r, i) => (
          <tr key={r.id || r.session_id || i} className="border-t border-brand-50 align-top">
            {columns.map((c) => <td key={c.h} className="px-3 py-3 first:pl-5 last:pr-5 sm:first:pl-6 sm:last:pr-6">{c.r(r)}</td>)}
          </tr>))}
        </tbody>
      </table>
    </div>
  );
}

const Act = ({ onClick, children, danger, testid }) => (
  <button type="button" onClick={onClick} data-testid={testid}
    className={`mr-2 mt-1 inline-flex h-9 items-center rounded-full px-3 text-xs font-semibold ring-1 transition ${danger ? "text-danger ring-danger/40 hover:bg-danger/10" : "text-ink ring-brand-50 hover:bg-brand-50"}`}>{children}</button>
);

async function run(fn, ok, reload) {
  try { await fn(); toast.success(ok); reload(); } catch (e) { toast.error(apiError(e)); }
}

function Approvals({ fin }) {
  const [s, reload] = useList("/admin/finance/approvals", { status: "pending" });
  if (!fin) return <p className="text-sm text-muted2">Finance administrators only.</p>;
  return <Table testid="ops-approvals" state={s} empty="Nothing waiting for a second approval." columns={[
    { h: "Action", r: (a) => <><b>{a.label}</b><div className="text-xs text-muted2">{day(a.created_at)}</div></> },
    { h: "Details", r: (a) => <span className="font-mono text-xs">{Object.entries(a.summary || {}).map(([k, v]) => `${k}: ${v}`).join(" · ")}</span> },
    { h: "Reason", r: (a) => a.reason },
    { h: "", r: (a) => <>
      <Act testid={`appr-ok-${a.id}`} onClick={() => run(() => API.post(`/admin/finance/approvals/${encodeURIComponent(a.id)}/approve`, { note: "" }), "Approved and applied", reload)}>Approve</Act>
      <Act danger onClick={() => { const n = ask("Reason for rejecting (at least 5 characters):"); if (n !== null) run(() => API.post(`/admin/finance/approvals/${encodeURIComponent(a.id)}/reject`, { note: n }), "Rejected", reload); }}>Reject</Act>
    </> },
  ]} />;
}

function Refunds({ fin }) {
  const [state, setStateName] = useState("open");
  const [s, reload] = useList("/admin/refund-cases", { state });
  const act = (c, body, ok) => run(() => API.post(`/admin/refund-cases/${c.id}/action`, body), ok, reload);
  return <>
    <div className="mb-3 flex flex-wrap gap-2">{["open", "awaiting_review", "initiated", "confirmed", "failed", "resolved"].map((x) =>
      <button key={x} onClick={() => setStateName(x)} className={`h-9 rounded-full px-4 text-xs font-semibold capitalize ${state === x ? "hg-chip-on text-white" : "hg-chip-off"}`}>{x.replace("_", " ")}</button>)}</div>
    <Table testid="ops-refunds" state={s} empty="No refund cases here." columns={[
      { h: "Case", r: (c) => <><b className="font-mono">{c.number}</b><div className="text-xs text-muted2">{c.kind} · order {c.order_number || c.order_id?.slice(0, 8)}</div></> },
      { h: "Amount", r: (c) => rupees(c.amount_paise) },
      { h: "Status", r: (c) => <StatusBadge status={c.status} /> },
      { h: "", r: (c) => <>
        {["awaiting_review", "failed"].includes(c.status) && <Act onClick={() => { const m = ask("Refund method (e.g. upi, bank, gateway):", "upi"); if (m) act(c, { action: c.status === "failed" ? "retry" : "initiate", method: m }, "Refund initiated"); }}>Initiate</Act>}
        {fin && c.status === "initiated" && <Act onClick={() => { const ref = ask("Refund reference (UTR / gateway refund id):"); if (!ref) return; const note = ask("How you verified it (at least 10 characters):", "Verified in bank statement"); if (note) act(c, { action: "confirm", reference: ref, confirmation_type: "manual_reconciliation", note }, "Refund confirmed"); }}>Confirm (other admin)</Act>}
        {c.status === "initiated" && <Act danger onClick={() => { const n = ask("Why did the refund fail?"); if (n) act(c, { action: "fail", note: n }, "Marked failed"); }}>Failed</Act>}
        {fin && ["confirmed", "awaiting_review"].includes(c.status) && <Act onClick={() => { const n = ask("Closing note:"); if (n) act(c, { action: "resolve", note: n }, "Case closed"); }}>Close</Act>}
      </> },
    ]} />
  </>;
}

function Returns() {
  const [s, reload] = useList("/admin/returns", { status: "contested" });
  return <Table testid="ops-returns" state={s} empty="No contested returns need a decision." columns={[
    { h: "Return", r: (r) => <><b className="font-mono">{r.number}</b><div className="text-xs text-muted2">{r.kind} · {day(r.created_at)}</div></> },
    { h: "Reason", r: (r) => r.reason || "—" },
    { h: "Status", r: (r) => <StatusBadge status={r.status} /> },
    { h: "", r: (r) => <>
      <Act onClick={() => { const n = ask("Note for approving this return (at least 5 characters):"); if (n) run(() => API.post(`/admin/returns/${r.id}/decision`, { decision: "approve", note: n }), "Return approved", reload); }}>Approve</Act>
      <Act danger onClick={() => { const n = ask("Reason for rejecting (at least 5 characters):"); if (n) run(() => API.post(`/admin/returns/${r.id}/decision`, { decision: "reject", note: n }), "Return rejected", reload); }}>Reject</Act>
    </> },
  ]} />;
}

function Settlements({ fin }) {
  const [bal, reloadBal] = useList("/admin/finance/vendors", {});
  const [s, reload] = useList("/admin/finance/settlements", {});
  const both = () => { reload(); reloadBal(); };
  const act = (st, body, ok) => run(() => API.post(`/admin/finance/settlements/${st.id}/action`, body), ok, both);
  return <>
    <h3 className="mb-2 font-display text-base font-semibold text-ink">Vendor balances</h3>
    <p className="mb-3 text-xs text-muted2">Only money from orders delivered, past the return window and free of open returns, refunds or payment issues is available.</p>
    <Table testid="ops-balances" state={bal} empty="No vendors with balances." columns={[
      { h: "Vendor", r: (v) => <><b>{v.business_name}</b><div className="text-xs text-muted2">{v.vendor_code}</div></> },
      { h: "Available", r: (v) => rupees(v.balances?.available_for_settlement_paise) },
      { h: "Waiting for eligibility", r: (v) => rupees(v.balances?.awaiting_eligibility_paise) },
      { h: "In progress", r: (v) => rupees(v.balances?.settlement_in_progress_paise) },
      { h: "", r: (v) => fin && (v.balances?.available_for_settlement_paise || 0) > 0 && <Act onClick={() => run(() => API.post("/admin/finance/settlements", { vendor_id: v.id }), "Settlement requested", both)}>Request settlement</Act> },
    ]} />
    <h3 className="mb-2 mt-6 font-display text-base font-semibold text-ink">Settlements</h3>
    <Table testid="ops-settlements" state={s} empty="No settlements yet." columns={[
      { h: "Settlement", r: (st) => <><b className="font-mono">{st.number || st.id.slice(0, 8)}</b><div className="text-xs text-muted2">{day(st.created_at)}</div></> },
      { h: "Amount", r: (st) => rupees(st.amount_paise) },
      { h: "Status", r: (st) => <StatusBadge status={st.status} /> },
      { h: "", r: (st) => fin && <>
        {st.status === "requested" && <Act onClick={() => act(st, { action: "approve" }, "Approved")}>Approve (not the requester)</Act>}
        {st.status === "approved" && <Act onClick={() => { const ref = ask("Payout reference (UTR / transfer id):"); if (ref) act(st, { action: "mark_paid", reference: ref }, "Marked paid"); }}>Mark paid (not the approver)</Act>}
        {["requested", "approved"].includes(st.status) && <Act danger onClick={() => { const n = ask("Reason (at least 5 characters):"); if (n) act(st, { action: st.status === "requested" ? "reject" : "fail", note: n }, "Updated"); }}>{st.status === "requested" ? "Reject" : "Failed"}</Act>}
      </> },
    ]} />
  </>;
}

function Cod({ fin }) {
  const [s, reload] = useList("/admin/finance/cod-discrepancies", {});
  const resolve = (o, resolution) => {
    const amt = ask(`Amount actually collected for ${o.order_number} (₹):`); if (!amt) return;
    const evref = ask("Evidence reference (courier / provider confirmation id):"); if (!evref) return;
    const reason = ask("Reason / finding:"); if (!reason) return;
    run(() => API.post(`/admin/finance/cod-discrepancies/${o.id}/resolve`, { resolution, collected_amount: Number(amt), evidence_type: "courier_confirmation", evidence_reference: evref, reason }), "Resolved", reload);
  };
  return <Table testid="ops-cod" state={s} empty="No COD orders are held for a discrepancy." columns={[
    { h: "Order", r: (o) => <b className="font-mono">{o.order_number}</b> },
    { h: "Expected", r: (o) => rupees(o.cod_discrepancy?.expected_paise) },
    { h: "Collected", r: (o) => rupees(o.cod_discrepancy?.collected_paise) },
    { h: "", r: (o) => fin && <><Act onClick={() => resolve(o, "confirm_full")}>Full amount found</Act><Act onClick={() => resolve(o, "accept_short")}>Accept short</Act></> },
  ]} />;
}

function Duplicates({ fin }) {
  const [s, reload] = useList("/admin/payments/duplicates", {});
  if (!fin) return <p className="text-sm text-muted2">Finance administrators only.</p>;
  return <Table testid="ops-duplicates" state={s} empty="No duplicate payments waiting for a refund." columns={[
    { h: "Order", r: (d) => <b className="font-mono">{d.order_number}</b> },
    { h: "Payment", r: (d) => <span className="font-mono text-xs">{d.provider} · {d.session_id}</span> },
    { h: "Amount", r: (d) => rs(d.amount) },
    { h: "Why", r: (d) => d.reason },
    { h: "", r: (d) => <Act onClick={() => { const ref = ask("Gateway refund reference:"); if (ref) run(() => API.post(`/admin/payments/duplicates/${d.order_id}/refunded`, { session_id: d.session_id, reference: ref }), "Refund recorded", reload); }}>Record refund</Act> },
  ]} />;
}

function BankChanges({ fin }) {
  const [s, reload] = useList("/admin/vendor-change-requests", { status: "pending" });
  const decide = (r, decision) => { const n = ask(`Note for ${decision === "approve" ? "approving" : "rejecting"}:`, decision === "approve" ? "Bank proof checked" : ""); if (n !== null) run(() => API.post(`/admin/vendor-change-requests/${r.id}/decision`, { decision, note: n }), decision === "approve" ? "Approved" : "Rejected", reload); };
  return <Table testid="ops-bank" state={s} empty="No vendor bank-change requests are waiting." columns={[
    { h: "Vendor", r: (r) => <><b>{r.vendor?.business_name || r.vendor_id?.slice(0, 8)}</b><div className="text-xs text-muted2">{day(r.created_at)}</div></> },
    { h: "Current", r: (r) => <span className="font-mono text-xs">{r.vendor?.current_bank_account || "—"} · {r.vendor?.current_ifsc || "—"}</span> },
    { h: "Requested", r: (r) => <span className="font-mono text-xs">{r.payload?.bank_account || "—"} · {r.payload?.ifsc || "—"}{r.payload?.bank_account_name ? ` · ${r.payload.bank_account_name}` : ""}</span> },
    { h: "", r: (r) => fin && <><Act onClick={() => decide(r, "approve")}>Approve</Act><Act danger onClick={() => decide(r, "reject")}>Reject</Act></> },
  ]} />;
}

function Support() {
  const [s, reload] = useList("/admin/support/tickets", { status: "open" });
  return <Table testid="ops-support" state={s} empty="No open support tickets." columns={[
    { h: "Ticket", r: (t) => <><b className="font-mono">{t.number || t.id.slice(0, 8)}</b><div className="text-xs text-muted2">{t.category} · {day(t.created_at)}</div></> },
    { h: "Subject", r: (t) => t.subject },
    { h: "Status", r: (t) => <StatusBadge status={t.status} /> },
    { h: "", r: (t) => <Act onClick={() => { const b = ask(`Reply to "${t.subject}":`); if (b) run(() => API.post(`/admin/support/tickets/${t.id}/reply`, { body: b }), "Reply sent", reload); }}>Reply</Act> },
  ]} />;
}

const TABS = [["approvals", "Approvals"], ["refunds", "Refunds"], ["returns", "Returns"], ["settlements", "Settlements"], ["cod", "COD"],
  ["duplicates", "Duplicate payments"], ["bank", "Bank changes"], ["support", "Support"]];

export default function AdminOperations() {
  const { user } = useAuth();
  const fin = FINANCE.includes(user?.role);
  const [tab, setTab] = useState("approvals");
  const [nonce, setNonce] = useState(0);
  const View = { approvals: Approvals, refunds: Refunds, returns: Returns, settlements: Settlements, cod: Cod, duplicates: Duplicates, bank: BankChanges, support: Support }[tab];
  return (
    <div className="space-y-5">
      <PageHeader title="Operations" icon={Briefcase} subtitle="Refunds, returns, settlements, COD, payments, bank changes and support in one place."
        actions={<Button variant="outline" onClick={() => setNonce((n) => n + 1)} className="h-10 rounded-full px-4" data-testid="ops-refresh"><RefreshCw size={14} className="mr-1.5" /> Refresh</Button>} />
      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} data-testid={`ops-tab-${k}`}
          className={`h-10 rounded-full px-5 text-sm font-semibold ${tab === k ? "hg-chip-on text-white" : "hg-chip-off"}`}>{label}</button>)}
      </div>
      <SectionCard><View key={`${tab}-${nonce}`} fin={fin} /></SectionCard>
    </div>
  );
}
