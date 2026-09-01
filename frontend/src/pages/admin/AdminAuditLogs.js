import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { ScrollText, Trash2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
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

  if (!logs) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.audit")}</h1>
        {isSuper && logs.length > 0 && (
          <button onClick={clearLogs} disabled={busy} className="inline-flex items-center gap-1.5 rounded-full border border-danger/40 px-4 py-2 text-xs font-semibold text-danger transition-all hover:bg-danger/10 disabled:opacity-50" data-testid="clear-audit-logs-btn">
            <Trash2 size={14} /> {busy ? "Deleting…" : "Delete All Logs"}
          </button>
        )}
      </div>
      {logs.length === 0 ? <EmptyState icon={ScrollText} title="No audit logs yet" testid="audit-empty" /> : (
        <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
          <table className="w-full text-sm">
            <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-3">Action</th><th className="p-3">Entity</th><th className="p-3">User</th><th className="p-3">IP</th><th className="p-3">Time</th></tr></thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id} className="border-b border-brand-50/60" data-testid={`audit-${l.id}`}>
                  <td className="p-3 font-medium text-forest">{l.action}</td>
                  <td className="p-3 text-ink">{l.entity} <span className="text-muted2">{(l.entity_id || "").slice(0, 8)}</span></td>
                  <td className="p-3 text-muted2">{l.user_email || "system"}</td>
                  <td className="p-3 text-muted2">{(l.ip || "").split(",")[0]}</td>
                  <td className="p-3 text-muted2">{(l.created_at || "").slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
