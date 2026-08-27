import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Ticket, Plus, KeyRound, X } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function AdminUsers() {
  const { t } = useI18n();
  const [users, setUsers] = useState(null);
  const [filter, setFilter] = useState("");
  const [codes, setCodes] = useState([]);
  const [reqs, setReqs] = useState([]);
  const [genLoading, setGenLoading] = useState(false);
  const [pwResult, setPwResult] = useState(null); // {full_name, distributor_id, password}
  const [busyId, setBusyId] = useState(null);

  useEffect(() => {
    API.get("/admin/users").then(({ data }) => setUsers(data)).catch(() => setUsers([]));
    API.get("/admin/referral-codes").then(({ data }) => setCodes(data)).catch(() => {});
    API.get("/admin/registration-requests").then(({ data }) => setReqs(data)).catch(() => {});
  }, []);

  const loadReqs = () => API.get("/admin/registration-requests").then(({ data }) => setReqs(data)).catch(() => {});
  const approveReq = async (r) => { try { const { data } = await API.post(`/admin/registration-requests/${r.id}/approve`); toast.success(data.message); loadReqs(); API.get("/admin/users").then(({ data }) => setUsers(data)); } catch (e) { toast.error(apiError(e)); } };
  const rejectReq = async (r) => { if (!window.confirm(`Reject ${r.full_name}?`)) return; try { await API.post(`/admin/registration-requests/${r.id}/reject`); toast.success("Request rejected"); loadReqs(); } catch (e) { toast.error(apiError(e)); } };

  const generate = async () => {
    setGenLoading(true);
    try {
      const { data } = await API.post("/admin/referral-codes");
      setCodes((c) => [data, ...c]);
      toast.success(`Referral code ${data.code} generated`);
    } catch (e) { toast.error(apiError(e)); } finally { setGenLoading(false); }
  };

  const copy = (text) => { navigator.clipboard?.writeText(text); toast.success(`Copied ${text}`); };

  const resetPw = async (u) => {
    setBusyId(u.id);
    try {
      const { data } = await API.post(`/admin/users/${u.id}/reset-password`, {});
      setPwResult(data);
      toast.success("New password generated");
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };

  if (!users) return <Skeleton className="h-96 rounded-2xl" />;

  const filtered = users.filter((u) => !filter || u.full_name?.toLowerCase().includes(filter.toLowerCase()) || u.distributor_id?.toLowerCase().includes(filter.toLowerCase()) || u.email?.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.users")}</h1>
        <input placeholder={t("common.search")} value={filter} onChange={(e) => setFilter(e.target.value)} className="h-10 w-64 rounded-full border border-brand-50 bg-white px-4 text-sm focus:outline-none focus:ring-2 focus:ring-brand" data-testid="user-search" />
      </div>

      {pwResult && (
        <div className="flex items-center justify-between gap-3 rounded-2xl border border-gold/40 bg-gold-light/50 p-4" data-testid="pw-reset-result">
          <div className="text-sm text-ink">
            New password for <b>{pwResult.full_name}</b> ({pwResult.distributor_id}):
            <button onClick={() => copy(pwResult.password)} className="ml-2 inline-flex items-center gap-1.5 rounded-lg bg-white px-2.5 py-1 font-mono font-semibold text-forest shadow-sm hover:shadow" data-testid="pw-reset-value">{pwResult.password} <Copy size={13} /></button>
            <span className="ml-2 text-xs text-muted2">Share this with the distributor. They can log in and change it.</span>
          </div>
          <button onClick={() => setPwResult(null)} className="text-muted2 hover:text-ink" data-testid="pw-reset-dismiss"><X size={18} /></button>
        </div>
      )}

      {/* Registration requests */}
      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="registration-requests-card">
        <h3 className="font-display text-lg font-medium text-ink">Registration Requests</h3>
        <p className="text-xs text-muted2">Approve to generate a Distributor ID (RED, active). No OTP — verify the applicant manually.</p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-3">Name</th><th className="p-3">Mobile</th><th className="p-3">Email</th><th className="p-3">Submitted</th><th className="p-3">Status</th><th className="p-3">Action</th></tr></thead>
            <tbody>
              {reqs.filter((r) => r.status === "pending").length === 0 && <tr><td colSpan={6} className="p-4 text-center text-muted2">No pending requests.</td></tr>}
              {reqs.filter((r) => r.status === "pending").map((r) => (
                <tr key={r.id} className="border-b border-brand-50/60" data-testid={`reg-req-${r.mobile}`}>
                  <td className="p-3 text-ink">{r.full_name}</td>
                  <td className="p-3 font-mono text-muted2">{r.mobile}</td>
                  <td className="p-3 text-muted2">{r.email || "—"}</td>
                  <td className="p-3 text-muted2">{(r.created_at || "").slice(0, 10)}</td>
                  <td className="p-3"><span className="rounded-full bg-gold-light px-2 py-0.5 text-xs font-semibold text-gold">pending</span></td>
                  <td className="p-3">
                    <div className="flex gap-2">
                      <button onClick={() => approveReq(r)} className="rounded-full bg-forest px-3 py-1 text-xs font-semibold text-white hover:bg-brand" data-testid={`approve-${r.mobile}`}>Approve</button>
                      <button onClick={() => rejectReq(r)} className="rounded-full border border-danger/40 px-3 py-1 text-xs font-semibold text-danger hover:bg-danger/10" data-testid={`reject-${r.mobile}`}>Reject</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Referral code generator */}
      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="referral-code-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-forest"><Ticket size={20} /></div>
            <div>
              <h3 className="font-display text-lg font-medium text-ink">Referral Codes</h3>
              <p className="text-xs text-muted2">Generate a code and share it to onboard new distributors (referral is mandatory at signup).</p>
            </div>
          </div>
          <Button onClick={generate} disabled={genLoading} className="rounded-full bg-forest hover:bg-brand" data-testid="generate-referral-code-btn">
            <Plus size={16} className="mr-1.5" /> {genLoading ? "Generating…" : "Generate Code"}
          </Button>
        </div>
        {codes.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {codes.slice(0, 12).map((c) => (
              <button key={c.code} onClick={() => copy(c.code)} className="group inline-flex items-center gap-2 rounded-full border border-brand-50 bg-brand-50/40 px-3 py-1.5 text-sm font-medium text-forest transition-all hover:-translate-y-0.5 hover:shadow-card" data-testid={`referral-code-${c.code}`}>
                <span className="font-mono">{c.code}</span>
                <span className="text-[10px] text-muted2">· {c.uses || 0} used</span>
                <Copy size={13} className="opacity-60 group-hover:opacity-100" />
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
        <table className="w-full text-sm">
          <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">ID</th><th className="p-4">{t("common.name")}</th><th className="p-4">{t("auth.email")}</th><th className="p-4">{t("common.status")}</th><th className="p-4">Sponsor</th><th className="p-4">KYC</th><th className="p-4">Joined</th><th className="p-4">Action</th></tr></thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} className="border-b border-brand-50/60" data-testid={`admin-user-${u.distributor_id}`}>
                <td className="p-4 font-medium text-forest">{u.distributor_id}</td>
                <td className="p-4 text-ink">{u.full_name}</td>
                <td className="p-4 text-muted2">{u.email}</td>
                <td className="p-4"><StatusBadge status={u.status} size="sm" /></td>
                <td className="p-4 text-muted2">{u.sponsor_id || "—"}</td>
                <td className="p-4 capitalize text-muted2">{(u.kyc_status || "").replace("_", " ")}</td>
                <td className="p-4 text-muted2">{(u.created_at || "").slice(0, 10)}</td>
                <td className="p-4">
                  <button onClick={() => resetPw(u)} disabled={busyId === u.id} className="inline-flex items-center gap-1.5 rounded-full border border-forest/25 px-3 py-1.5 text-xs font-semibold text-forest transition-all hover:bg-brand-50 disabled:opacity-50" data-testid={`reset-pw-${u.distributor_id}`}>
                    <KeyRound size={13} /> {busyId === u.id ? "…" : "Reset Password"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
