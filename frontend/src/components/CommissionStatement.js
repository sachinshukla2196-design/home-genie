import React, { useEffect, useState } from "react";
import { ScrollText } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { SectionCard } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { API, apiError } from "@/lib/api";

const rupees = (p) => `₹${(Number(p || 0) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const TYPE = { COMMISSION_DIRECT: "Direct sale", COMMISSION_REFERRAL: "Referral", COMMISSION_TEAM: "Team" };
const HOLD = {
  not_delivered: "Waiting for delivery", return_window_open: "Return window still open", open_return_or_refund: "Return or refund in progress",
  cancelled: "Order cancelled", refund_due: "Refund pending on the order", duplicate_payment_refund_due: "Payment issue being resolved",
};

/** Batch 5: the member's commission statement (GET /api/commissions/statement). Commission becomes payable after delivery
 *  and the return window (owner decision 2); each held line says why. */
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
          <p className="mt-3 text-xs text-muted2">Commission is paid on genuine sales only and becomes available after the order is delivered and the return window has passed. Cancelled or returned sales are reversed.</p>
          {d.items.length === 0 ? <p className="mt-4 text-sm text-muted2">No commissions yet. Share products from the shop to start earning.</p> : (
            <div className="-mx-5 mt-4 overflow-x-auto sm:-mx-6">
              <table className="w-full min-w-[560px] text-sm">
                <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className="px-5 py-2 sm:px-6">Order</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Amount</th><th className="px-3 py-2">Status</th><th className="px-5 py-2 sm:px-6">Note</th></tr></thead>
                <tbody>{d.items.map((r) => (
                  <tr key={r.id} className="border-t border-brand-50">
                    <td className="px-5 py-2.5 font-mono sm:px-6">{r.order_number}</td>
                    <td className="px-3 py-2.5">{TYPE[r.type] || r.type}</td>
                    <td className="px-3 py-2.5 tabular-nums">{rupees(r.net_paise)}{r.reversed_paise > 0 && <span className="ml-1 text-xs text-muted2">({rupees(r.reversed_paise)} reversed)</span>}</td>
                    <td className="px-3 py-2.5"><StatusBadge status={r.released_at ? "released" : (r.status || "").toLowerCase()} /></td>
                    <td className="px-5 py-2.5 text-xs text-muted2 sm:px-6">{r.released_at ? `Released ${r.released_at.slice(0, 10)}` : HOLD[r.held_because] || ""}</td>
                  </tr>))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </SectionCard>
  );
}
