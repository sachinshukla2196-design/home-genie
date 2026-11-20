import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { UserCog, UserPlus, Ban, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const ROLE_LABEL = { super_admin: "Super admin", admin: "Admin", accounts_admin: "Accounts admin", support_admin: "Support admin" };
const TEAM_ROLES = ["admin", "accounts_admin", "support_admin"];
const EMPTY = { full_name: "", email: "", mobile: "", role: "support_admin", temporary_password: "", reason: "" };

/** OPS-01: the super admin's team screen. Every action is enforced by the server (admin_team.py, admin block endpoint). */
export default function AdminTeam() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [team, setTeam] = useState(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState("");

  const load = () => API.get("/admin/team").then(({ data }) => { setTeam(data); setError(""); })
    .catch((e) => { setTeam([]); setError(apiError(e)); });
  useEffect(() => { load(); }, []);

  if (user?.role !== "super_admin") {
    return <div className="space-y-5"><PageHeader title={t("nav.adminTeam")} icon={UserCog} /><SectionCard><p className="text-sm text-muted2">Only the super admin can manage the admin team.</p></SectionCard></div>;
  }

  const pwOk = form.temporary_password.length >= 12 && /[A-Za-z]/.test(form.temporary_password) && /\d/.test(form.temporary_password);
  const formOk = form.full_name.trim().length >= 2 && /\S+@\S+\.\S+/.test(form.email) && /^[6-9]\d{9}$/.test(form.mobile) && pwOk && form.reason.trim().length >= 5;
  const create = async () => {
    setBusy("create");
    try {
      const { data } = await API.post("/admin/team", form);
      toast.success(data.message);
      setForm(EMPTY); load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };
  const changeRole = async (m, role) => {
    if (role === m.role) return;
    const reason = window.prompt(`Change ${m.full_name} from ${ROLE_LABEL[m.role]} to ${ROLE_LABEL[role]}. Reason (at least 5 characters):`, "");
    if (reason === null) return;
    setBusy(m.id);
    try { await API.put(`/admin/team/${m.id}/role`, { role, reason }); toast.success("Role changed"); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };
  const toggleBlock = async (m) => {
    const next = !m.blocked;
    if (!window.confirm(`${next ? "Disable" : "Re-enable"} ${m.full_name}? ${next ? "All their sessions stop working at once." : ""}`)) return;
    setBusy(m.id);
    try { await API.put(`/admin/users/${m.id}/block`, { blocked: next }); toast.success(next ? "Admin disabled" : "Admin re-enabled"); load(); }
    catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="space-y-5">
      <PageHeader title={t("nav.adminTeam")} icon={UserCog} subtitle="Add administrators, change their role, or disable them. The super admin account itself is never changed here." />

      <SectionCard title="Team" icon={UserCog} testid="admin-team-list">
        {!team ? <Skeleton className="h-40 rounded-2xl" /> : error ? (
          <p className="text-sm text-danger" data-testid="admin-team-error">{error}</p>
        ) : team.length === 0 ? <p className="text-sm text-muted2">No administrators yet.</p> : (
          <div className="-mx-5 overflow-x-auto sm:-mx-6">
            <table className="w-full min-w-[640px] text-sm">
              <thead><tr className="text-left text-xs uppercase tracking-wide text-muted2">
                <th className="px-5 py-2 sm:px-6">Name</th><th className="px-3 py-2">Sign-in email</th><th className="px-3 py-2">Mobile</th>
                <th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th><th className="px-5 py-2 text-right sm:px-6">Actions</th>
              </tr></thead>
              <tbody>
                {team.map((m) => {
                  const isTeam = TEAM_ROLES.includes(m.role);
                  return (
                    <tr key={m.id} className="border-t border-brand-50" data-testid={`team-row-${m.distributor_id}`}>
                      <td className="px-5 py-3 font-medium text-ink sm:px-6">{m.full_name}{m.id === user.id ? <span className="ml-2 text-xs text-muted2">(you)</span> : null}</td>
                      <td className="px-3 py-3 text-ink">{m.email}</td>
                      <td className="px-3 py-3 font-mono text-muted2">{m.mobile_masked}</td>
                      <td className="px-3 py-3">
                        {isTeam ? (
                          <select value={m.role} disabled={busy === m.id} onChange={(e) => changeRole(m, e.target.value)}
                            className="hgv-input h-9 rounded-full px-3 text-sm" aria-label={`Role of ${m.full_name}`} data-testid={`team-role-${m.distributor_id}`}>
                            {TEAM_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                          </select>
                        ) : <span className="font-semibold text-ink">{ROLE_LABEL[m.role]}</span>}
                      </td>
                      <td className="px-3 py-3"><StatusBadge status={m.blocked ? "blocked" : m.must_change_password ? "pending" : "active"} /></td>
                      <td className="px-5 py-3 text-right sm:px-6">
                        {isTeam && (
                          <button onClick={() => toggleBlock(m)} disabled={busy === m.id}
                            className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold ${m.blocked ? "border-hg-success/40 text-hg-success hover:bg-hg-success/10" : "border-danger/40 text-danger hover:bg-danger/10"}`}
                            data-testid={`team-block-${m.distributor_id}`}>
                            {m.blocked ? <><CheckCircle2 size={13} /> Re-enable</> : <><Ban size={13} /> Disable</>}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <SectionCard title="Add an administrator" icon={UserPlus} testid="admin-team-create">
        <p className="-mt-1 mb-4 text-sm text-muted2">Choose a temporary password and give it to the new admin yourself. They must replace it at first sign-in — when SMS is available, also with a code sent to their own mobile — so you never know their working password.</p>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="text-sm text-ink">Full name<Input value={form.full_name} onChange={set("full_name")} className="mt-1.5" data-testid="team-name" /></label>
          <label className="text-sm text-ink">Sign-in email<Input type="email" value={form.email} onChange={set("email")} className="mt-1.5" data-testid="team-email" /></label>
          <label className="text-sm text-ink">Mobile<Input value={form.mobile} onChange={(e) => setForm((f) => ({ ...f, mobile: e.target.value.replace(/\D/g, "").slice(0, 10) }))} inputMode="numeric" className="mt-1.5" data-testid="team-mobile" /></label>
          <label className="text-sm text-ink">Role
            <select value={form.role} onChange={set("role")} className="hgv-input mt-1.5 h-10 w-full rounded-xl px-3" data-testid="team-role-new">
              {TEAM_ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
            </select>
          </label>
          <label className="text-sm text-ink">Temporary password<Input type="password" autoComplete="new-password" value={form.temporary_password} onChange={set("temporary_password")} className="mt-1.5" data-testid="team-temp" />
            <span className="mt-1 block text-xs text-muted2">At least 12 characters with letters and numbers.</span></label>
          <label className="text-sm text-ink">Reason<Input value={form.reason} onChange={set("reason")} placeholder="e.g. New finance team member" className="mt-1.5" data-testid="team-reason" /></label>
        </div>
        <Button onClick={create} disabled={!formOk || busy === "create"} className="hg-btn mt-5 h-11 rounded-full px-6" data-testid="team-create">{busy === "create" ? "Creating…" : "Create admin account"}</Button>
      </SectionCard>
    </div>
  );
}
