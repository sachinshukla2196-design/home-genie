import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Copy, Info, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { useI18n } from "@/context/I18nContext";
import { API, apiError } from "@/lib/api";
import { Pill, ResponsiveTable, StateBlock, fmtDate, useAction } from "@/components/vendor/kit";

const SELECT = "h-10 rounded-xl bg-white/5 px-3 text-sm text-ink ring-1 ring-white/15";
const MOBILE = /^[6-9]\d{9}$/;
const TONE = { active: "ok", invited: "info", suspended: "warn", revoked: "muted" };
const EMPTY = { mobile: "", full_name: "", role: "store_manager", permissions: [] };

/** Owner-only team management: invite (one-time link), change role, suspend, reactivate, resend and revoke. Every rule is enforced by the backend. */
export default function VendorStaff() {
  const { t, lang } = useI18n();
  const [d, setD] = useState(null);
  const [error, setError] = useState(null);
  const [link, setLink] = useState(null);
  const [form, setForm] = useState(EMPTY);
  const [tried, setTried] = useState(false);
  const [roleEdit, setRoleEdit] = useState({});
  const [run, busy] = useAction();

  const load = useCallback(() => {
    setError(null);
    API.get("/vendor/staff").then(({ data }) => setD(data)).catch((e) => setError(apiError(e)));
  }, []);
  useEffect(() => { load(); }, [load]);

  const linkFor = (token) => `${window.location.origin}/vendor/invite?token=${token}`;
  const mobileOk = MOBILE.test(form.mobile.trim());
  const problems = {
    mobile: mobileOk ? null : "vx.staff.errMobile",
    full_name: form.full_name.trim().length < 2 ? "vx.staff.errName" : null,
    permissions: form.role === "custom" && form.permissions.length === 0 ? "vx.staff.errPerms" : null,
  };
  const valid = Object.values(problems).every((p) => !p);

  const invite = (e) => {
    e.preventDefault();
    setTried(true);
    if (!valid || busy) return;
    run(() => API.post("/vendor/staff/invitations", { ...form, mobile: form.mobile.trim(), full_name: form.full_name.trim() }), { success: t("vx.staff.invited") })
      .then((r) => { if (r) { setLink(linkFor(r.data.token)); setForm(EMPTY); setTried(false); load(); } });
  };
  const resend = (m) => run(() => API.post(`/vendor/staff/${m.id}/resend`), { success: t("vx.staff.resent") })
    .then((r) => { if (r) { setLink(linkFor(r.data.token)); load(); } });
  const act = (m, fn, key) => run(fn, { success: t(key) }).then((r) => { if (r) load(); });
  const saveRole = (m) => {
    const role = roleEdit[m.id] || m.role;
    act(m, () => API.put(`/vendor/staff/${m.id}`, { role }), "vx.staff.roleSaved");
  };
  const copy = () => { if (navigator.clipboard && link) navigator.clipboard.writeText(link).then(() => toast.success(t("vx.staff.copied"))).catch(() => toast.error(t("vx.staff.copyFailed"))); };

  if (!d) return <StateBlock loading={!error} error={error} onRetry={load} rows={2} testid="staff" />;

  const roleOptions = Object.keys(d.presets).concat(["custom"]);
  const togglePerm = (p) => setForm({ ...form, permissions: form.permissions.includes(p) ? form.permissions.filter((x) => x !== p) : [...form.permissions, p] });

  const actions = (m) => {
    if (m.status === "revoked") return <span className="text-xs text-muted2">{t("vx.staff.removed")}</span>;
    return (
      <div className="flex flex-wrap items-center gap-2">
        {m.status !== "invited" && (
          <>
            <select aria-label={t("vx.staff.changeRole")} className={SELECT} value={roleEdit[m.id] || m.role} onChange={(e) => setRoleEdit({ ...roleEdit, [m.id]: e.target.value })} data-testid={`staff-role-${m.id}`}>
              {Object.keys(d.presets).map((r) => <option key={r} value={r}>{t(`vx.staff.role.${r}`)}</option>)}
            </select>
            <Button variant="outline" size="sm" className="h-9 rounded-full" disabled={busy || (roleEdit[m.id] || m.role) === m.role} onClick={() => saveRole(m)} data-testid={`staff-save-${m.id}`}>{t("vx.staff.save")}</Button>
          </>
        )}
        {m.status === "invited" && <Button variant="outline" size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => resend(m)} data-testid={`staff-resend-${m.id}`}>{t("vx.staff.resend")}</Button>}
        {m.status === "active" && <Button variant="outline" size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => act(m, () => API.post(`/vendor/staff/${m.id}/suspend`), "vx.staff.suspended")} data-testid={`staff-suspend-${m.id}`}>{t("vx.staff.suspend")}</Button>}
        {m.status === "suspended" && <Button variant="outline" size="sm" className="h-9 rounded-full" disabled={busy} onClick={() => act(m, () => API.post(`/vendor/staff/${m.id}/reactivate`), "vx.staff.reactivated")} data-testid={`staff-reactivate-${m.id}`}>{t("vx.staff.reactivate")}</Button>}
        <Button variant="outline" size="sm" className="h-9 rounded-full border-danger/40 text-danger" disabled={busy} onClick={() => act(m, () => API.delete(`/vendor/staff/${m.id}`), "vx.staff.revokedMsg")} data-testid={`staff-revoke-${m.id}`}>{t("vx.staff.revoke")}</Button>
      </div>
    );
  };

  const columns = [
    { key: "name", label: t("vx.staff.col.name"), render: (s) => <span className="font-medium text-ink">{s.name || "—"}</span> },
    { key: "mobile", label: t("vx.staff.col.mobile"), render: (s) => <span className="tabular-nums">{s.mobile || "—"}</span> },
    { key: "role", label: t("vx.staff.col.role"), render: (s) => t(`vx.staff.role.${s.role}`) },
    { key: "status", label: t("vx.staff.col.status"), render: (s) => <Pill tone={TONE[s.status] || "muted"} testid={`staff-status-${s.id}`}>{t(`vx.staff.st.${s.status}`)}</Pill> },
    { key: "added", label: t("vx.staff.col.added"), render: (s) => <span className="text-xs text-muted2">{fmtDate(s.invited_at, lang)}{s.invite_expires_at ? ` · ${t("vx.staff.expires", { d: fmtDate(s.invite_expires_at, lang) })}` : ""}</span> },
    { key: "actions", label: t("vx.staff.col.actions"), render: actions },
  ];

  return (
    <div className="space-y-6" data-testid="vendor-staff">
      <PageHeader title={t("vx.nav.staff")} subtitle={t("vx.staff.sub")} icon={Users} />
      <p className="flex gap-2 rounded-xl bg-hg-gold/10 p-3 text-xs text-ink ring-1 ring-hg-gold/25" role="note" data-testid="staff-note"><Info size={14} className="mt-0.5 shrink-0" aria-hidden /> {t("vx.staff.note")}</p>

      {link && (
        <SectionCard title={t("vx.staff.linkTitle")} testid="staff-link">
          <p className="text-xs text-muted2">{t("vx.staff.linkNote")}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 truncate rounded-lg bg-white/5 px-3 py-2 text-xs text-ink ring-1 ring-white/15" data-testid="staff-link-url">{link}</code>
            <Button variant="outline" className="h-9 rounded-full" onClick={copy}><Copy size={14} /> {t("vx.staff.copy")}</Button>
            <Button variant="ghost" className="h-9 rounded-full" onClick={() => setLink(null)}>{t("vx.staff.done")}</Button>
          </div>
        </SectionCard>
      )}

      <SectionCard title={t("vx.staff.invite")} icon={Users} testid="staff-invite">
        <form onSubmit={invite} noValidate className="grid gap-4 sm:grid-cols-2" data-testid="staff-form">
          <div>
            <label htmlFor="st-mobile" className="text-sm font-medium text-ink">{t("vx.staff.mobile")}</label>
            <Input id="st-mobile" inputMode="numeric" maxLength={10} value={form.mobile} onChange={(e) => setForm({ ...form, mobile: e.target.value })} className="mt-1.5" data-testid="staff-mobile" />
            {tried && problems.mobile && <p role="alert" className="mt-1 text-xs text-danger">{t(problems.mobile)}</p>}
          </div>
          <div>
            <label htmlFor="st-name" className="text-sm font-medium text-ink">{t("vx.staff.name")}</label>
            <Input id="st-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className="mt-1.5" data-testid="staff-name" />
            {tried && problems.full_name && <p role="alert" className="mt-1 text-xs text-danger">{t(problems.full_name)}</p>}
          </div>
          <div>
            <label htmlFor="st-role" className="text-sm font-medium text-ink">{t("vx.staff.roleLabel")}</label>
            <select id="st-role" className={`${SELECT} mt-1.5 w-full`} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value, permissions: [] })} data-testid="staff-role">
              {roleOptions.map((r) => <option key={r} value={r}>{t(`vx.staff.role.${r}`)}</option>)}
            </select>
            <p className="mt-1 text-xs text-muted2">{t(`vx.staff.desc.${form.role}`)}</p>
          </div>
          {form.role === "custom" && (
            <fieldset className="sm:col-span-2" data-testid="staff-perms">
              <legend className="text-sm font-medium text-ink">{t("vx.staff.perms")}</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                {d.permissions.map((p) => (
                  <label key={p} className="flex items-center gap-2 text-sm text-ink">
                    <input type="checkbox" checked={form.permissions.includes(p)} onChange={() => togglePerm(p)} data-testid={`staff-perm-${p}`} /> {t(`vx.staff.perm.${p}`)}
                  </label>
                ))}
              </div>
              {tried && problems.permissions && <p role="alert" className="mt-1 text-xs text-danger">{t(problems.permissions)}</p>}
            </fieldset>
          )}
          <div className="sm:col-span-2">
            <Button type="submit" disabled={busy} className="hg-btn h-11 rounded-full px-6" data-testid="staff-submit">{t("vx.staff.send")}</Button>
          </div>
        </form>
      </SectionCard>

      <SectionCard title={t("vx.nav.staff")} icon={Users} testid="staff-list">
        {d.staff.length === 0
          ? <p className="hg-tile p-6 text-center text-sm text-muted2" data-testid="staff-empty">{t("vx.staff.none")}</p>
          : <ResponsiveTable columns={columns} rows={d.staff} rowKey={(s) => s.id} caption={t("vx.nav.staff")} testid="staff-table" />}
      </SectionCard>
    </div>
  );
}
