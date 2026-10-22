import React, { useEffect, useState, useMemo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { Copy, Ticket, Plus, KeyRound, X, Ban, Trash2, Pencil, Wallet, Users, Search, UserPlus } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";

export default function AdminUsers() {
  const { t } = useI18n();
  const [users, setUsers] = useState(null);
  const [filter, setFilter] = useState("");
  const [codes, setCodes] = useState([]);
  const [reqs, setReqs] = useState([]);
  const [pwReqs, setPwReqs] = useState([]);
  const [genLoading, setGenLoading] = useState(false);
  const [pwResult, setPwResult] = useState(null); // {full_name, distributor_id, password}
  const [busyId, setBusyId] = useState(null);
  const [editUser, setEditUser] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [creditUser, setCreditUser] = useState(null);
  const [creditForm, setCreditForm] = useState({ amount: "", reason: "" });

  useEffect(() => {
    API.get("/admin/users").then(({ data }) => setUsers(data)).catch(() => setUsers([]));
    API.get("/admin/referral-codes").then(({ data }) => setCodes(data)).catch(() => {});
    API.get("/admin/registration-requests").then(({ data }) => setReqs(data)).catch(() => {});
    API.get("/admin/password-reset-requests").then(({ data }) => setPwReqs(data)).catch(() => {});
  }, []);

  const loadPwReqs = () => API.get("/admin/password-reset-requests").then(({ data }) => setPwReqs(data)).catch(() => {});
  const resetForReq = async (r) => {
    setBusyId(r.id);
    try {
      const { data } = await API.post(`/admin/users/${r.user_id}/reset-password`, {});
      setPwResult(data); setPwReqs((l) => l.filter((x) => x.id !== r.id));
      toast.success("New password generated");
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };
  const dismissPwReq = async (r) => {
    try { await API.post(`/admin/password-reset-requests/${r.id}/dismiss`); setPwReqs((l) => l.filter((x) => x.id !== r.id)); toast.success("Request dismissed"); }
    catch (e) { toast.error(apiError(e)); }
  };

  const loadReqs = () => API.get("/admin/registration-requests").then(({ data }) => setReqs(data)).catch(() => {});
  const approveReq = async (r) => { try { const { data } = await API.post(`/admin/registration-requests/${r.id}/approve`); toast.success(data.message); loadReqs(); API.get("/admin/users").then(({ data }) => setUsers(data)); } catch (e) { toast.error(apiError(e)); } };
  const rejectReq = async (r) => { const reason = window.prompt(`Reject ${r.full_name}? Optionally enter a reason:`, ""); if (reason === null) return; try { await API.post(`/admin/registration-requests/${r.id}/reject`, { reason }); toast.success("Request rejected"); loadReqs(); } catch (e) { toast.error(apiError(e)); } };

  const openEdit = (u) => { setEditForm({ full_name: u.full_name || "", email: u.email || "", mobile: u.mobile || "", address: u.address || "", state: u.state || "", city: u.city || "", pincode: u.pincode || "" }); setEditUser(u); };
  const saveEdit = async () => {
    setBusyId(editUser.id);
    try {
      const { data } = await API.put(`/admin/users/${editUser.id}`, editForm);
      setUsers((list) => list.map((x) => (x.id === editUser.id ? { ...x, ...data } : x)));
      toast.success("Profile updated");
      setEditUser(null);
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };

  const openCredit = (u) => { setCreditForm({ amount: "", reason: "" }); setCreditUser(u); };
  const submitCredit = async () => {
    const amt = parseFloat(creditForm.amount);
    if (!amt || amt <= 0) { toast.error("Enter a valid amount greater than 0"); return; }
    setBusyId(creditUser.id);
    try {
      const { data } = await API.post("/admin/wallet/credit", { distributor_id: creditUser.distributor_id, amount: amt, reason: creditForm.reason || "Manual admin credit" });
      toast.success(`${data.message} New balance ₹${data.available_balance}`);
      setCreditUser(null);
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };

  const generate = async () => {
    setGenLoading(true);
    try {
      const { data } = await API.post("/admin/referral-codes");
      setCodes((c) => [data, ...c]);
      toast.success(`Referral code ${data.code} generated`);
    } catch (e) { toast.error(apiError(e)); } finally { setGenLoading(false); }
  };

  const copy = (text) => { navigator.clipboard?.writeText(text); toast.success(`Copied ${text}`); };

  const deleteCode = async (code) => {
    if (!window.confirm(`Delete reference code ${code}?`)) return;
    try {
      await API.delete(`/admin/referral-codes/${code}`);
      setCodes((cs) => cs.filter((x) => x.code !== code));
      toast.success("Reference code deleted");
    } catch (e) { toast.error(apiError(e)); }
  };

  const resetPw = async (u) => {
    setBusyId(u.id);
    try {
      const { data } = await API.post(`/admin/users/${u.id}/reset-password`, {});
      setPwResult(data);
      toast.success("New password generated");
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };

  const toggleBlock = async (u) => {
    const next = !u.blocked;
    if (!window.confirm(`${next ? "Block" : "Unblock"} ${u.full_name} (${u.distributor_id})?`)) return;
    setBusyId(u.id);
    try {
      await API.put(`/admin/users/${u.id}/block`, { blocked: next });
      setUsers((list) => list.map((x) => (x.id === u.id ? { ...x, blocked: next, account_status: next ? "blocked" : "active" } : x)));
      toast.success(next ? "User blocked" : "User unblocked");
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };

  const deleteUser = async (u) => {
    if (!window.confirm(`Permanently DELETE ${u.full_name} (${u.distributor_id})? This removes the user and their wallet and cannot be undone.`)) return;
    setBusyId(u.id);
    try {
      await API.delete(`/admin/users/${u.id}`);
      setUsers((list) => list.filter((x) => x.id !== u.id));
      toast.success("User deleted");
    } catch (e) { toast.error(apiError(e)); } finally { setBusyId(null); }
  };

  const filtered = useMemo(
    () => (users || []).filter((u) => !filter || u.full_name?.toLowerCase().includes(filter.toLowerCase()) || u.distributor_id?.toLowerCase().includes(filter.toLowerCase()) || u.email?.toLowerCase().includes(filter.toLowerCase())),
    [users, filter]
  );

  if (!users) return (
    <div className="space-y-5">
      <PageHeader title={t("nav.users")} icon={Users} />
      <Skeleton className="h-40 rounded-[20px]" />
      <Skeleton className="h-96 rounded-[20px]" />
    </div>
  );

  const pendingReqs = reqs.filter((r) => r.status === "pending");
  const TH = "whitespace-nowrap px-4 py-3 font-semibold";
  const ROW = "border-t border-brand-50 transition-colors hover:bg-brand-50/60";
  const pillBtn = "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50";
  const outlineBtn = `${pillBtn} border border-brand-50 text-ink hover:bg-brand-50`;
  const goldBtn = `${pillBtn} border border-hg-gold/40 text-hg-gold hover:bg-hg-gold/10`;
  const dangerBtn = `${pillBtn} border border-danger/40 text-danger hover:bg-danger/10`;
  const primaryBtn = `${pillBtn} hg-btn text-white`;

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.users")} icon={Users} actions={
        <div className="relative w-full sm:w-72">
          <Search size={16} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-muted2" />
          <Input placeholder={t("common.search")} value={filter} onChange={(e) => setFilter(e.target.value)} aria-label={t("common.search")} className="rounded-full pl-10" data-testid="user-search" />
        </div>
      } />

      <AnimatePresence>
        {pwResult && (
          <motion.div initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.25 }}
            className="hg-card flex items-start justify-between gap-3 p-4 ring-1 ring-hg-gold/30 sm:p-5" data-testid="pw-reset-result">
            <div className="flex min-w-0 items-start gap-3">
              <span className="hg-icon-chip !h-9 !w-9 shrink-0 !rounded-xl !bg-hg-gold/15 !text-hg-gold"><KeyRound size={16} /></span>
              <div className="min-w-0 break-words text-sm text-ink">
                New password for <b>{pwResult.full_name}</b> ({pwResult.distributor_id}):
                <button onClick={() => copy(pwResult.password)} className="ml-2 mt-1 inline-flex items-center gap-1.5 rounded-lg bg-hg-gold/15 px-2.5 py-1 font-mono font-semibold text-hg-gold ring-1 ring-hg-gold/30 transition-colors hover:bg-hg-gold/25" data-testid="pw-reset-value">{pwResult.password} <Copy size={13} /></button>
                <span className="mt-1 block text-xs text-muted2">Share this with the HomeGenie. She can log in and change it.</span>
              </div>
            </div>
            <button onClick={() => setPwResult(null)} aria-label="Dismiss" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted2 transition-colors hover:bg-brand-50 hover:text-ink" data-testid="pw-reset-dismiss"><X size={18} /></button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Password reset requests */}
      {pwReqs.length > 0 && (
        <SectionCard title="Password Reset Requests" icon={KeyRound} testid="password-reset-requests-card" className="ring-1 ring-hg-gold/25">
          <p className="-mt-2 mb-4 text-sm text-muted2">HomeGenies who forgot their password. Reset it and share the new password with her (no OTP/email).</p>
          <div className="space-y-2">
            {pwReqs.map((r) => (
              <div key={r.id} className="hg-tile flex flex-wrap items-center justify-between gap-3 rounded-xl p-3" data-testid={`pw-req-${r.distributor_id}`}>
                <div className="min-w-0 break-words text-sm"><span className="font-mono font-semibold text-hg-lavender">{r.distributor_id}</span> · <span className="text-ink">{r.full_name}</span> · <span className="font-mono text-muted2">{r.mobile}</span><span className="ml-2 text-xs text-muted2">{(r.created_at || "").slice(0, 10)}</span></div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => resetForReq(r)} disabled={busyId === r.id} className={primaryBtn} data-testid={`pw-req-reset-${r.distributor_id}`}>{busyId === r.id ? "…" : "Reset Password"}</button>
                  <button onClick={() => dismissPwReq(r)} className={dangerBtn} data-testid={`pw-req-dismiss-${r.distributor_id}`}>Dismiss</button>
                </div>
              </div>
            ))}
          </div>
        </SectionCard>
      )}

      {/* Registration requests */}
      <SectionCard title="Registration Requests" icon={UserPlus} testid="registration-requests-card"
        action={pendingReqs.length > 0 && <span className="shrink-0 rounded-full bg-hg-gold/15 px-2.5 py-0.5 text-xs font-semibold tabular-nums text-hg-gold ring-1 ring-hg-gold/25">{pendingReqs.length}</span>}>
        <p className="-mt-2 mb-4 text-sm text-muted2">Approve to generate a HomeGenie ID. The selling role is enabled on approval — verify the applicant manually.</p>
        <div className="-mx-5 overflow-x-auto sm:-mx-6">
          <table className="w-full min-w-[640px] text-sm">
            <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className={`${TH} pl-5 sm:pl-6`}>Name</th><th className={TH}>Mobile</th><th className={TH}>Email</th><th className={TH}>Submitted</th><th className={TH}>Status</th><th className={`${TH} pr-5 sm:pr-6`}>Action</th></tr></thead>
            <tbody>
              {pendingReqs.length === 0 && <tr className="border-t border-brand-50"><td colSpan={6} className="px-4 py-8 text-center text-muted2">No pending requests.</td></tr>}
              {pendingReqs.map((r) => (
                <tr key={r.id} className={ROW} data-testid={`reg-req-${r.mobile}`}>
                  <td className="px-4 py-3 pl-5 text-ink sm:pl-6">{r.full_name}</td>
                  <td className="whitespace-nowrap px-4 py-3 font-mono text-muted2">{r.mobile}</td>
                  <td className="max-w-[220px] truncate px-4 py-3 text-muted2">{r.email || "—"}</td>
                  <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted2">{(r.created_at || "").slice(0, 10)}</td>
                  <td className="px-4 py-3"><span className="rounded-full bg-hg-gold/15 px-2.5 py-0.5 text-xs font-semibold text-hg-gold ring-1 ring-hg-gold/25">pending</span></td>
                  <td className="px-4 py-3 pr-5 sm:pr-6">
                    <div className="flex gap-2">
                      <button onClick={() => approveReq(r)} className={primaryBtn} data-testid={`approve-${r.mobile}`}>Approve</button>
                      <button onClick={() => rejectReq(r)} className={dangerBtn} data-testid={`reject-${r.mobile}`}>Reject</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>

      {/* Referral code generator */}
      <SectionCard testid="referral-code-card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className="hg-icon-chip !h-10 !w-10 shrink-0 !rounded-xl"><Ticket size={20} /></span>
            <div className="min-w-0">
              <h3 className="font-display text-lg font-semibold text-ink">Referral Codes</h3>
              <p className="text-sm text-muted2">Generate a code and share it to onboard new HomeGenies.</p>
            </div>
          </div>
          <Button onClick={generate} disabled={genLoading} className="hg-btn h-11 rounded-full px-6" data-testid="generate-referral-code-btn">
            <Plus size={16} className="mr-1.5" /> {genLoading ? "Generating…" : "Generate Code"}
          </Button>
        </div>
        {codes.length > 0 && (
          <div className="mt-5 flex flex-wrap gap-2">
            {codes.slice(0, 12).map((c) => (
              <div key={c.code} className="group inline-flex max-w-full items-center gap-2 rounded-full bg-hg-violet/10 px-3 py-1.5 text-sm font-medium text-hg-lavender ring-1 ring-hg-lavender/20" data-testid={`referral-code-${c.code}`}>
                <button onClick={() => copy(c.code)} className="inline-flex min-w-0 items-center gap-2" title="Copy code" aria-label={`Copy ${c.code}`}>
                  <span className="truncate font-mono">{c.code}{c.is_master ? " ★" : ""}</span>
                  <span className="shrink-0 text-[11px] text-muted2">· {c.uses || 0} used</span>
                  <Copy size={13} className="shrink-0 opacity-60 group-hover:opacity-100" />
                </button>
                {!c.is_master && (
                  <button onClick={() => deleteCode(c.code)} className="shrink-0 text-danger/70 transition-colors hover:text-danger" title="Delete code" aria-label={`Delete ${c.code}`} data-testid={`delete-referral-code-${c.code}`}>
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </SectionCard>

      <div className="hg-card overflow-hidden">
        <div className="overflow-x-auto">
        <table className="w-full min-w-[1080px] text-sm">
          <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2"><th className={TH}>ID</th><th className={TH}>{t("common.name")}</th><th className={TH}>{t("auth.email")}</th><th className={TH}>{t("common.status")}</th><th className={TH}>Referred by</th><th className={TH}>Verification</th><th className={TH}>Joined</th><th className={TH}>Action</th></tr></thead>
          <tbody>
            {filtered.map((u) => (
              <tr key={u.id} className={ROW} data-testid={`admin-user-${u.distributor_id}`}>
                <td className="whitespace-nowrap px-4 py-3 font-mono font-medium text-hg-lavender">{u.distributor_id}</td>
                <td className="px-4 py-3 text-ink">{u.full_name}</td>
                <td className="max-w-[220px] truncate px-4 py-3 text-muted2">{u.email}</td>
                <td className="px-4 py-3"><div className="flex items-center gap-1.5"><StatusBadge status={u.status} size="sm" />{u.blocked && <span className="rounded-full bg-danger/10 px-2.5 py-0.5 text-[11px] font-semibold text-danger ring-1 ring-danger/25" data-testid={`blocked-badge-${u.distributor_id}`}>Blocked</span>}</div></td>
                <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted2">{u.sponsor_id || "—"}</td>
                <td className="px-4 py-3">{u.kyc_status ? <span className="whitespace-nowrap rounded-full bg-hg-violet/10 px-2.5 py-0.5 text-xs font-medium capitalize text-muted2 ring-1 ring-brand-50">{(u.kyc_status || "").replace("_", " ")}</span> : <span className="text-muted2">—</span>}</td>
                <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted2">{(u.created_at || "").slice(0, 10)}</td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => openEdit(u)} disabled={busyId === u.id} className={outlineBtn} data-testid={`edit-user-${u.distributor_id}`}>
                      <Pencil size={13} /> Edit
                    </button>
                    <button onClick={() => resetPw(u)} disabled={busyId === u.id} className={outlineBtn} data-testid={`reset-pw-${u.distributor_id}`}>
                      <KeyRound size={13} /> {busyId === u.id ? "…" : "Reset Password"}
                    </button>
                    <button onClick={() => openCredit(u)} disabled={busyId === u.id} className={goldBtn} data-testid={`credit-user-${u.distributor_id}`}>
                      <Wallet size={13} /> Credit ₹
                    </button>
                    <button onClick={() => toggleBlock(u)} disabled={busyId === u.id} className={u.blocked ? outlineBtn : goldBtn} data-testid={`block-toggle-${u.distributor_id}`}>
                      <Ban size={13} /> {u.blocked ? "Unblock" : "Block"}
                    </button>
                    <button onClick={() => deleteUser(u)} disabled={busyId === u.id} className={dangerBtn} data-testid={`delete-user-${u.distributor_id}`}>
                      <Trash2 size={13} /> Delete
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {editUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" data-testid="edit-user-modal">
          <motion.div initial={{ opacity: 0, scale: 0.96, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ duration: 0.25 }}
            className="hg-glass max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-3xl p-5 sm:p-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="min-w-0 break-words font-display text-lg font-semibold text-ink">Edit profile — {editUser.distributor_id}</h3>
              <button onClick={() => setEditUser(null)} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted2 transition-colors hover:bg-brand-50 hover:text-ink" data-testid="edit-user-close"><X size={18} /></button>
            </div>
            <div className="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {[["full_name", "Full Name"], ["email", "Email"], ["mobile", "Mobile"], ["pincode", "Pincode"], ["state", "State"], ["city", "City"]].map(([k, label]) => (
                <label key={k} className="block text-sm text-ink">
                  {label}
                  <Input value={editForm[k] ?? ""} onChange={(e) => setEditForm((f) => ({ ...f, [k]: e.target.value }))} className="mt-1.5" data-testid={`edit-field-${k}`} />
                </label>
              ))}
              <label className="block text-sm text-ink sm:col-span-2">
                Address
                <Input value={editForm.address ?? ""} onChange={(e) => setEditForm((f) => ({ ...f, address: e.target.value }))} className="mt-1.5" data-testid="edit-field-address" />
              </label>
            </div>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={() => setEditUser(null)} className="h-11 rounded-full border-brand-50 bg-transparent px-5" data-testid="edit-user-cancel">Cancel</Button>
              <Button onClick={saveEdit} disabled={busyId === editUser.id} className="hg-btn h-11 rounded-full px-6" data-testid="edit-user-save">{busyId === editUser.id ? "Saving…" : "Save"}</Button>
            </div>
          </motion.div>
        </div>
      )}
      {creditUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm" data-testid="credit-user-modal">
          <motion.div initial={{ opacity: 0, scale: 0.96, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ duration: 0.25 }}
            className="hg-glass w-full max-w-sm rounded-3xl p-5 sm:p-6">
            <div className="flex items-center justify-between gap-3">
              <h3 className="font-display text-lg font-semibold text-ink">Manual Wallet Credit</h3>
              <button onClick={() => setCreditUser(null)} aria-label="Close" className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-muted2 transition-colors hover:bg-brand-50 hover:text-ink" data-testid="credit-user-close"><X size={18} /></button>
            </div>
            <p className="mt-1 break-words text-sm text-muted2">Credit <b className="font-mono text-hg-lavender">{creditUser.distributor_id}</b> — {creditUser.full_name}. Adds to available balance (MANUAL_ADMIN_CREDIT).</p>
            <label className="mt-5 block text-sm text-ink">Amount (₹)
              <Input type="number" min="1" value={creditForm.amount} onChange={(e) => setCreditForm((f) => ({ ...f, amount: e.target.value }))} className="mt-1.5" data-testid="credit-amount" />
            </label>
            <label className="mt-4 block text-sm text-ink">Reason (optional)
              <Input value={creditForm.reason} onChange={(e) => setCreditForm((f) => ({ ...f, reason: e.target.value }))} placeholder="Manual admin credit" className="mt-1.5" data-testid="credit-reason" />
            </label>
            <div className="mt-6 flex flex-wrap justify-end gap-2">
              <Button variant="outline" onClick={() => setCreditUser(null)} className="h-11 rounded-full border-brand-50 bg-transparent px-5" data-testid="credit-cancel">Cancel</Button>
              <Button onClick={submitCredit} disabled={busyId === creditUser.id} className="hg-btn h-11 rounded-full px-6" data-testid="credit-submit">{busyId === creditUser.id ? "Crediting…" : "Credit"}</Button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
}
