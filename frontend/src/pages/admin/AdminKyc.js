import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, CheckCircle2, XCircle, Pencil } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const TABS = ["pending", "verified", "rejected"];
const FINANCE = ["super_admin", "accounts_admin"];       // the server enforces this; hiding the edit button is only a convenience

/** HG-02 / OPS-02: KYC review. Details are masked by the server. A decision applies only to the version the reviewer saw (M2),
 *  and a finance edit sends a verified record back to pending (SEC-06). */
export default function AdminKyc() {
  const { user } = useAuth();
  const isFinance = FINANCE.includes(user?.role);
  const [tab, setTab] = useState("pending");
  const [rows, setRows] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [edit, setEdit] = useState(null);
  const [form, setForm] = useState({ pan: "", account_holder_name: "", bank_account: "", ifsc: "", bank_name: "" });

  const load = useCallback(() => {
    setRows(null);
    API.get("/admin/kyc", { params: { status: tab } }).then(({ data }) => { setRows(data); setError(""); })
      .catch((e) => { setRows([]); setError(apiError(e)); });
  }, [tab]);
  useEffect(() => { load(); }, [load]);

  const decide = async (r, action) => {
    let reason = "";
    if (action === "reject") {
      reason = window.prompt(`Reject KYC of ${r.distributor_id}? The member sees this reason:`, "");
      if (reason === null) return;
      if (reason.trim().length < 5) { toast.error("Give a reason of at least 5 characters."); return; }
    } else if (!window.confirm(`Verify KYC of ${r.distributor_id}? Check the documents outside the app before confirming.`)) return;
    setBusy(r.user_id);
    try {
      await API.put(`/admin/kyc/${r.user_id}`, { action, reason, expected_version: r.version || 0 });
      toast.success(action === "verify" ? "KYC verified" : "KYC rejected"); load();
    } catch (e) { toast.error(apiError(e)); if (e?.response?.status === 409) load(); } finally { setBusy(""); }
  };
  const openEdit = (r) => { setEdit(r); setForm({ pan: "", account_holder_name: r.account_holder_name || "", bank_account: "", ifsc: "", bank_name: r.bank_name || "" }); };
  const saveEdit = async () => {
    const body = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim() !== ""));
    if (!Object.keys(body).length) { toast.error("Enter at least one new value."); return; }
    setBusy(edit.user_id);
    try {
      const { data } = await API.put(`/admin/kyc/${edit.user_id}/edit`, body);
      toast.success(data.verification_reset ? "Saved. The record must be verified again." : "Saved");
      setEdit(null); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };

  return (
    <div className="space-y-5">
      <PageHeader title="KYC review" icon={ShieldCheck} subtitle="Identity and payout bank details submitted by members. All numbers are shown masked." />
      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map((x) => (
          <button key={x} role="tab" aria-selected={tab === x} onClick={() => setTab(x)} data-testid={`kyc-tab-${x}`}
            className={`h-10 rounded-full px-5 text-sm font-semibold capitalize ${tab === x ? "hg-chip-on text-white" : "hg-chip-off"}`}>{x}</button>
        ))}
      </div>
      <SectionCard testid="admin-kyc-list">
        {!rows ? <Skeleton className="h-40 rounded-2xl" /> : error ? <p className="text-sm text-danger">{error}</p> : rows.length === 0 ? (
          <p className="text-sm text-muted2">No {tab} KYC records.</p>
        ) : (
          <div className="-mx-5 overflow-x-auto sm:-mx-6">
            <table className="w-full min-w-[720px] text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2">
                <th className="px-5 py-2 sm:px-6">Member</th><th className="px-3 py-2">PAN</th><th className="px-3 py-2">Bank account</th>
                <th className="px-3 py-2">IFSC</th><th className="px-3 py-2">Status</th><th className="px-5 py-2 text-right sm:px-6">Actions</th>
              </tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.user_id} className="border-t border-brand-50" data-testid={`kyc-row-${r.distributor_id}`}>
                    <td className="px-5 py-3 sm:px-6"><div className="font-mono font-semibold text-ink">{r.distributor_id}</div><div className="text-xs text-muted2">{r.account_holder_name}</div></td>
                    <td className="px-3 py-3 font-mono">{r.pan || "—"}</td>
                    <td className="px-3 py-3 font-mono">{r.bank_account || "—"}</td>
                    <td className="px-3 py-3 font-mono">{r.ifsc || "—"}</td>
                    <td className="px-3 py-3"><StatusBadge status={r.status} /></td>
                    <td className="px-5 py-3 text-right sm:px-6">
                      <div className="inline-flex flex-wrap justify-end gap-2">
                        {r.status !== "verified" && <Button size="sm" disabled={busy === r.user_id} onClick={() => decide(r, "verify")} className="hg-btn h-9 rounded-full px-3" data-testid={`kyc-verify-${r.distributor_id}`}><CheckCircle2 size={14} className="mr-1" /> Verify</Button>}
                        {r.status !== "rejected" && <Button size="sm" variant="outline" disabled={busy === r.user_id} onClick={() => decide(r, "reject")} className="h-9 rounded-full border-danger/40 px-3 text-danger hover:bg-danger/10" data-testid={`kyc-reject-${r.distributor_id}`}><XCircle size={14} className="mr-1" /> Reject</Button>}
                        {isFinance && <Button size="sm" variant="outline" onClick={() => openEdit(r)} className="h-9 rounded-full px-3" data-testid={`kyc-edit-${r.distributor_id}`}><Pencil size={14} className="mr-1" /> Correct</Button>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>
      {edit && (
        <SectionCard title={`Correct KYC — ${edit.distributor_id}`} testid="kyc-edit-form">
          <p className="-mt-1 mb-4 text-sm text-muted2">Leave a field empty to keep it. Any change sends a verified record back to pending; the audit keeps masked old and new values.</p>
          <div className="grid gap-4 sm:grid-cols-2">
            {[["pan", "PAN"], ["account_holder_name", "Account holder name"], ["bank_account", "Bank account number"], ["ifsc", "IFSC"], ["bank_name", "Bank name"]].map(([k, label]) => (
              <label key={k} className="text-sm text-ink">{label}<Input value={form[k]} onChange={(e) => setForm((x) => ({ ...x, [k]: e.target.value }))} className="mt-1.5" data-testid={`kyc-edit-${k}`} /></label>
            ))}
          </div>
          <div className="mt-5 flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setEdit(null)} className="h-11 rounded-full px-5">Cancel</Button>
            <Button onClick={saveEdit} disabled={busy === edit.user_id} className="hg-btn h-11 rounded-full px-6" data-testid="kyc-edit-save">Save correction</Button>
          </div>
        </SectionCard>
      )}
    </div>
  );
}
