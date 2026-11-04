import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Banknote, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Stagger, StaggerItem } from "@/components/motion";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const STATUS_PILL = {
  pending: "bg-hg-gold/15 text-hg-gold ring-hg-gold/25",
  approved: "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/25",
  paid: "bg-hg-success/15 text-hg-success ring-hg-success/25",
  rejected: "bg-danger/10 text-danger ring-danger/25",
};

const FINANCE_ROLES = ["super_admin", "accounts_admin"];     // the server enforces this; hiding controls is only a convenience
const REQUESTED = ["pending", "under_review"];      // stored as "pending" (legacy "under_review"); shown as "requested"
const label = (st) => (REQUESTED.includes(st) ? "requested" : st);

export default function AdminWithdrawals() {
  const { user } = useAuth();
  const canAct = FINANCE_ROLES.includes(user?.role);
  const [list, setList] = useState([]);
  const [note, setNote] = useState({});
  const [ref, setRef] = useState({});
  const [busy, setBusy] = useState(null);

  const load = () => { API.get("/admin/withdrawals").then(({ data }) => setList(data)).catch(() => {}); };
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // REQUESTED -> approve or reject; APPROVED -> mark paid (different finance user, payout reference) or reject.
  const act = async (r, action) => {
    if (busy) return;
    const body = { action, note: (note[r.id] || "").trim() };
    if (action === "mark_paid") {
      body.payout_reference = (ref[r.id] || "").trim();
      if (body.payout_reference.length < 3) { toast.error("Enter the payout reference (UTR / bank or processor reference)."); return; }
    }
    setBusy(r.id);
    try {
      const { data } = await API.put(`/admin/withdrawals/${r.id}`, body);
      toast.success(data.already ? "Already done" : `Withdrawal ${data.status}`);
      load();
    } catch (err) { toast.error(apiError(err)); } finally { setBusy(null); }
  };

  return (
    <div className="space-y-5" data-testid="admin-withdrawals-page">
      <PageHeader title="Point Withdrawals" icon={Banknote} />
      {list.length === 0 ? (
        <EmptyState icon={Banknote} title="No withdrawal requests" testid="adm-wd-empty" />
      ) : (
        <Stagger className="space-y-3">
          {list.map((r) => (
            <StaggerItem key={r.id} className="hg-card flex flex-col gap-4 p-4 sm:p-5 md:flex-row md:items-center md:justify-between" data-testid={`adm-wd-${r.request_number}`}>
              <div className="flex min-w-0 items-center gap-3">
                <span className="hg-icon-chip !h-10 !w-10 shrink-0 !rounded-xl"><Banknote size={18} /></span>
                <div className="min-w-0">
                  <div className="break-words font-medium text-ink">{r.request_number} · {r.distributor_id}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted2">
                    <span className="tabular-nums">{(r.created_at || "").slice(0, 10)}</span>
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold capitalize ring-1 ${STATUS_PILL[REQUESTED.includes(r.status) ? "pending" : r.status] || "bg-hg-violet/15 text-hg-lavender ring-hg-lavender/25"}`}>{label(r.status)}</span>
                  </div>
                </div>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center md:justify-end">
                <div className="font-display text-lg font-semibold tabular-nums text-hg-gold">{Number(r.amount).toLocaleString("en-IN")} pts</div>
                {(r.approved_by_name || r.paid_by_name || r.rejected_by_name) && (
                  <div className="text-xs text-muted2" data-testid={`adm-wd-trail-${r.request_number}`}>
                    {r.approved_by_name && <div>Approved by {r.approved_by_name}</div>}
                    {r.paid_by_name && <div>Paid by {r.paid_by_name} · ref <span className="font-mono">{r.payout_reference}</span></div>}
                    {r.rejected_by_name && <div>Rejected by {r.rejected_by_name}</div>}
                  </div>
                )}
                {canAct && (REQUESTED.includes(r.status) || r.status === "approved") && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Input placeholder="Note (optional)" value={note[r.id] || ""} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))}
                      className="w-full sm:w-40" data-testid={`adm-wd-note-${r.request_number}`} />
                    {REQUESTED.includes(r.status) && (
                      <Button size="sm" disabled={busy === r.id} onClick={() => act(r, "approve")} className="hg-btn h-10 rounded-full px-4" data-testid={`adm-wd-approve-${r.request_number}`}>
                        <Check size={14} className="mr-1" /> Approve
                      </Button>
                    )}
                    {r.status === "approved" && (
                      <>
                        <Input placeholder="Payout reference (required)" value={ref[r.id] || ""} maxLength={64}
                          onChange={(e) => setRef((x) => ({ ...x, [r.id]: e.target.value }))} className="w-full font-mono sm:w-52" data-testid={`adm-wd-ref-${r.request_number}`} />
                        <Button size="sm" disabled={busy === r.id} onClick={() => act(r, "mark_paid")} className="hg-btn h-10 rounded-full px-4" data-testid={`adm-wd-pay-${r.request_number}`}>
                          <Check size={14} className="mr-1" /> Mark paid
                        </Button>
                      </>
                    )}
                    <Button size="sm" variant="outline" disabled={busy === r.id} onClick={() => act(r, "reject")} className="h-10 rounded-full border-danger/30 bg-transparent px-4 text-danger hover:bg-danger/10 hover:text-danger" data-testid={`adm-wd-reject-${r.request_number}`}>
                      <X size={14} className="mr-1" /> Reject
                    </Button>
                  </div>
                )}
              </div>
            </StaggerItem>
          ))}
        </Stagger>
      )}
    </div>
  );
}
