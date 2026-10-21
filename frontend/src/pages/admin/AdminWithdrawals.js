import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Banknote, Check, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { API, apiError } from "@/lib/api";

export default function AdminWithdrawals() {
  const [list, setList] = useState([]);
  const [note, setNote] = useState({});

  const load = () => { API.get("/admin/withdrawals").then(({ data }) => setList(data)).catch(() => {}); };
  useEffect(() => { load(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const act = async (id, status) => {
    try {
      await API.put(`/admin/withdrawals/${id}`, { status, admin_note: note[id] || "" });
      toast.success(`Withdrawal ${status}`);
      load();
    } catch (err) { toast.error(apiError(err)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-withdrawals-page">
      <h1 className="font-display text-2xl font-semibold text-ink">Point Withdrawals</h1>
      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        {list.length === 0 ? (
          <EmptyState icon={Banknote} title="No withdrawal requests" testid="adm-wd-empty" />
        ) : (
          <div className="space-y-3">
            {list.map((r) => (
              <div key={r.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand-50 p-4" data-testid={`adm-wd-${r.request_number}`}>
                <div>
                  <div className="font-medium text-ink">{r.request_number} · {r.distributor_id}</div>
                  <div className="text-xs capitalize text-muted2">{(r.created_at || "").slice(0, 10)} · {r.status}</div>
                </div>
                <div className="font-display font-semibold text-forest">{Number(r.amount).toLocaleString("en-IN")} pts</div>
                {r.status === "pending" && (
                  <div className="flex flex-wrap items-center gap-2">
                    <Input placeholder="Note (optional)" value={note[r.id] || ""} onChange={(e) => setNote((n) => ({ ...n, [r.id]: e.target.value }))}
                      className="h-9 w-40 rounded-lg" data-testid={`adm-wd-note-${r.request_number}`} />
                    <Button size="sm" onClick={() => act(r.id, "paid")} className="btn-grad rounded-full" data-testid={`adm-wd-pay-${r.request_number}`}>
                      <Check size={14} className="mr-1" /> Mark paid
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => act(r.id, "rejected")} className="rounded-full border-danger/30 text-danger" data-testid={`adm-wd-reject-${r.request_number}`}>
                      <X size={14} className="mr-1" /> Reject
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
