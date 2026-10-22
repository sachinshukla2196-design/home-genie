import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { ScrollText, Trash2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function AdminAuditLogs() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [logs, setLogs] = useState(null);
  const [busy, setBusy] = useState(false);
  const isSuper = user?.role === "super_admin";

  const load = () => API.get("/admin/audit-logs").then(({ data }) => setLogs(data)).catch(() => setLogs([]));
  useEffect(() => { load(); }, []);

  const clearLogs = async () => {
    if (!window.confirm("Permanently delete ALL audit logs? This cannot be undone. A single system event will remain to record this action.")) return;
    setBusy(true);
    try {
      const { data } = await API.delete("/admin/audit-logs");
      toast.success(`Cleared ${data.deleted} audit logs`);
      load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const header = (
    <PageHeader title={t("nav.audit")} icon={ScrollText} actions={isSuper && logs && logs.length > 0 && (
      <button onClick={clearLogs} disabled={busy} className="inline-flex h-10 items-center gap-1.5 rounded-full border border-danger/40 px-4 text-xs font-semibold text-danger transition-colors hover:bg-danger/10 disabled:opacity-50" data-testid="clear-audit-logs-btn">
        <Trash2 size={14} /> {busy ? "Deleting…" : "Delete All Logs"}
      </button>
    )} />
  );

  if (!logs) return (
    <div className="space-y-5">
      {header}
      <div className="hg-card space-y-3 p-5 sm:p-6">{[...Array(6)].map((_, i) => <Skeleton key={i} className="h-10 rounded-xl" />)}</div>
    </div>
  );

  return (
    <div className="space-y-5">
      {header}
      {logs.length === 0 ? <EmptyState icon={ScrollText} title="No audit logs yet" testid="audit-empty" /> : (
        <div className="hg-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted2">
                  <th className="px-4 py-3 font-semibold">Action</th><th className="px-4 py-3 font-semibold">Entity</th><th className="px-4 py-3 font-semibold">User</th><th className="px-4 py-3 font-semibold">IP</th><th className="px-4 py-3 font-semibold">Time</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((l) => (
                  <tr key={l.id} className="border-t border-brand-50 transition-colors hover:bg-brand-50/60" data-testid={`audit-${l.id}`}>
                    <td className="px-4 py-3">
                      <span className="inline-flex rounded-full bg-hg-violet/15 px-2.5 py-0.5 text-xs font-semibold text-hg-lavender ring-1 ring-hg-lavender/25">{l.action}</span>
                    </td>
                    <td className="px-4 py-3 text-ink">{l.entity} <span className="font-mono text-xs text-muted2">{(l.entity_id || "").slice(0, 8)}</span></td>
                    <td className="max-w-[220px] truncate px-4 py-3 text-muted2">{l.user_email || "system"}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted2">{(l.ip || "").split(",")[0]}</td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums text-muted2">{(l.created_at || "").slice(0, 19).replace("T", " ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
