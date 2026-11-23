import React, { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard } from "@/components/PageHeader";
import { API, apiError } from "@/lib/api";

const rupees = (p) => `₹${(Number(p || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const TYPE = { COMMISSION_DIRECT: "Direct sale", COMMISSION_REFERRAL: "Referral", COMMISSION_TEAM: "Team" };
const HOLD = {
  not_delivered: "Waiting for delivery", return_window_open: "Return window still open", open_return_or_refund: "Return or refund in progress",
  cancelled: "Order cancelled", refund_due: "Refund pending on the order", duplicate_payment_refund_due: "Payment issue being resolved",
  order_missing: "Order not found",
};

/** The commission's real financial state (Batch 12, audit C-15) - never the member's red/green status. */
export function commissionState(r) {
  if (r.status === "REVERSED") return { label: "Reversed", tone: "bg-danger/10 text-danger ring-danger/25" };
  if (r.released_at) return { label: r.reversed_paise > 0 ? "Released (part reversed)" : "Released", tone: "bg-hg-success/15 text-hg-success ring-hg-success/30" };
  if (r.status === "HELD") return { label: "On hold", tone: "bg-danger/10 text-danger ring-danger/25" };
  if (r.held_because) return { label: "Waiting", tone: "bg-hg-gold/15 text-hg-gold ring-hg-gold/30" };
  return { label: "Due for release", tone: "bg-hg-violet/15 text-hg-violet ring-hg-lavender/30" };
}

function note(r) {
  if (r.status === "REVERSED" || r.reversed_paise > 0) {
    const why = (r.reversal_reasons || []).join("; ") || "Order cancelled or refunded";
    if (r.status === "REVERSED") return `Reversed: ${why}`;
    if (!r.released_at) return `${rupees(r.reversed_paise)} reversed (${why}). ${HOLD[r.held_because] || ""}`.trim();
    return `${rupees(r.reversed_paise)} reversed (${why})`;
  }
  if (r.released_at) return `Released ${r.released_at.slice(0, 10)}`;
  return HOLD[r.held_because] || "Will be released in the next daily run";
}

const basis = (r) => (r.base_paise != null && r.percent != null ? `${r.percent}% of ${rupees(r.base_paise)}` : "—");

function Chip({ r }) {
  const s = commissionState(r);
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ring-1 ${s.tone}`} data-testid="commission-state">{s.label}</span>;
}

/** Batch 5 / 12: the member's commission statement (GET /api/commissions/statement). Commission becomes payable after delivery
 *  and the return window (owner decision 2); every line shows its basis, its real state and why it is held or reversed. */
export function CommissionStatement() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState("");
  useEffect(() => { API.get("/commissions/statement").then(({ data }) => setD(data)).catch((e) => setErr(apiError(e))); }, []);
  return (
    <SectionCard title="Commission statement" icon={ScrollText} testid="commission-statement">
      {err ? <p className="text-sm text-danger">{err}</p> : !d ? <Skeleton className="h-24 rounded-2xl" /> : (
        <>
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {[["Earned", d.earned_paise], ["Released", d.released_paise], ["Waiting", d.pending_paise], ["Reversed", d.reversed_paise]].map(([l, v]) => (
              <div key={l} className="hg-tile rounded-xl p-3"><div className="text-xs text-muted2">{l}</div><div className="font-display text-lg font-semibold tabular-nums text-ink">{rupees(v)}</div></div>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted2">Commission is paid on genuine sales only. It is calculated on the price before GST and becomes available after the order is delivered and the return window has passed. Cancelled or returned sales are reversed.</p>
          {d.items.length === 0 ? <p className="mt-4 text-sm text-muted2">No commissions yet. Share products from the shop to start earning.</p> : (
            <>
              {/* phones: one card per line, so the reason is always visible */}
              <div className="mt-4 space-y-2.5 sm:hidden" data-testid="commission-cards">
                {d.items.map((r) => (
                  <div key={r.id} className="hg-tile rounded-xl p-3.5 text-sm">
                    <div className="flex items-center justify-between gap-2"><span className="font-mono font-medium text-ink">{r.order_number}</span><Chip r={r} /></div>
                    <div className="mt-1.5 flex items-center justify-between gap-2 text-muted2"><span>{TYPE[r.type] || r.type} · {basis(r)}</span>
                      <span className="font-display font-semibold tabular-nums text-ink">{rupees(r.net_paise)}</span></div>
                    <div className="mt-1.5 text-xs text-muted2">{note(r)}</div>
                  </div>
                ))}
              </div>
              <div className="-mx-5 mt-4 hidden overflow-x-auto sm:-mx-6 sm:block">
                <table className="w-full min-w-[680px] text-sm">
                  <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className="px-5 py-2 sm:px-6">Order</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Basis</th><th className="px-3 py-2">Amount</th><th className="px-3 py-2">Status</th><th className="px-5 py-2 sm:px-6">Details</th></tr></thead>
                  <tbody>{d.items.map((r) => (
                    <tr key={r.id} className="border-t border-brand-50 align-top">
                      <td className="px-5 py-2.5 font-mono sm:px-6">{r.order_number}</td>
                      <td className="px-3 py-2.5">{TYPE[r.type] || r.type}</td>
                      <td className="px-3 py-2.5 text-muted2">{basis(r)}</td>
                      <td className="px-3 py-2.5 tabular-nums">{rupees(r.net_paise)}</td>
                      <td className="px-3 py-2.5"><Chip r={r} /></td>
                      <td className="px-5 py-2.5 text-xs text-muted2 sm:px-6">{note(r)}</td>
                    </tr>))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </SectionCard>
  );
}
