import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { UserCheck, X } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { API, apiError } from "@/lib/api";

const money = (v) => `₹${Number(v).toLocaleString("en-IN")}`;

// HomeGenie activation review. The server decides who is listed (paid online, or COD with fully proven collection, and a
// pre-GST subtotal of at least ₹2,500) and re-checks everything on approval. Approval never pays or replays commission.
export default function AdminActivations() {
  const [data, setData] = useState(null);
  const [pick, setPick] = useState(null);       // { user, order }
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { const { data } = await API.get("/admin/activations"); setData(data); }
    catch (e) { toast.error(apiError(e)); setData({ items: [], min_subtotal: 2500 }); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const open = (user, order) => { setPick({ user, order }); setNote(""); setError(""); };
  const close = () => { if (!busy) setPick(null); };
  const approve = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const { data: r } = await API.post(`/admin/activations/${pick.user.id}/approve`, { order_id: pick.order.order_id, note: note.trim() });
      toast.success(r.already ? "Already active" : "HomeGenie activated");
      setPick(null); load();
    } catch (e) { setError(apiError(e)); } finally { setBusy(false); }
  };

  return (
    <div data-testid="admin-activations">
      <PageHeader title="Activations" subtitle={`Review HomeGenies with a qualifying purchase (pre-GST subtotal of at least ${money(data?.min_subtotal ?? 2500)}).`} icon={UserCheck} />
      <SectionCard title="Awaiting review" bodyClassName="p-0">
        {!data ? <Skeleton className="m-4 h-24" /> : data.items.length === 0 ? (
          <p className="p-5 text-sm text-muted2" data-testid="activations-empty">No HomeGenie is waiting for activation review.</p>
        ) : (
          <ul className="divide-y divide-brand-50">
            {data.items.map(({ user, qualifying_orders }) => (
              <li key={user.id} className="p-4" data-testid={`activation-${user.distributor_id}`}>
                <p className="font-medium text-ink">{user.full_name} <span className="font-mono text-xs text-muted2">{user.distributor_id}</span>
                  <span className="ml-2 rounded-full bg-hg-gold/15 px-2 py-0.5 text-xs text-hg-gold">{user.status}</span></p>
                <div className="mt-2 space-y-2">
                  {qualifying_orders.map((o) => (
                    <div key={o.order_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-brand-50/40 px-3 py-2 text-sm">
                      <span>
                        {o.order_number} · subtotal {money(o.subtotal)} · {o.payment_method?.toUpperCase()} · {o.evidence.kind === "cod_collection"
                          ? `collection ${o.evidence.evidence_type} ${o.evidence.evidence_reference} (recorded, not independently verified)`
                          : "payment confirmed"}
                        {o.paid_at ? ` · ${new Date(o.paid_at).toLocaleDateString("en-IN")}` : ""}
                      </span>
                      <Button size="sm" className="hg-btn rounded-full" onClick={() => open(user, o)} data-testid={`activation-review-${o.order_number}`}>Review & approve</Button>
                    </div>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {pick && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" onClick={close} data-testid="activation-modal">
          <form noValidate onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); approve(); }} className="hg-glass w-full max-w-md rounded-3xl p-5 sm:p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-display text-lg font-semibold text-ink">Activate {pick.user.full_name}</h3>
                <p className="text-xs text-muted2">{pick.user.distributor_id} · order {pick.order.order_number} · subtotal {money(pick.order.subtotal)}</p>
              </div>
              <button type="button" onClick={close} aria-label="Close" className="flex h-9 w-9 items-center justify-center rounded-full text-muted2 hover:bg-brand-50"><X size={18} /></button>
            </div>
            <p className="mt-4 text-sm text-muted2">This sets the account to active (green). It does not pay or replay any commission, including for this order.</p>
            <div className="mt-4">
              <Label className="text-sm text-ink">Note (optional)</Label>
              <Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} className="mt-1.5" data-testid="activation-note" />
            </div>
            {error && <p role="alert" className="mt-3 text-sm text-danger" data-testid="activation-error">{error}</p>}
            <div className="mt-6 flex gap-3">
              <Button type="button" variant="outline" onClick={close} className="h-11 flex-1 rounded-full border-brand-50 bg-transparent">Cancel</Button>
              <Button type="submit" disabled={busy} className="hg-btn h-11 flex-1 rounded-full" data-testid="activation-confirm">{busy ? "Activating…" : "Approve activation"}</Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
