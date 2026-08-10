import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Users, List, Network, Crown } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

export default function Team() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [view, setView] = useState("matrix");

  useEffect(() => { API.get("/team").then(({ data }) => setData(data)).catch(() => setData({ members: [] })); }, []);
  if (!data) return <Skeleton className="h-64 rounded-2xl" />;

  const members = data.members || [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.team")}</h1>
        <div className="flex items-center gap-3">
          {members.length > 0 && <div className="text-sm text-muted2">{data.total} {t("nav.team").toLowerCase()} · {data.active} active</div>}
          <div className="inline-flex items-center rounded-full border border-brand-50 bg-white p-0.5">
            <button onClick={() => setView("matrix")} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${view === "matrix" ? "bg-forest text-white" : "text-muted2"}`} data-testid="team-view-matrix"><Network size={14} /> Matrix</button>
            <button onClick={() => setView("list")} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${view === "list" ? "bg-forest text-white" : "text-muted2"}`} data-testid="team-view-list"><List size={14} /> List</button>
          </div>
        </div>
      </div>

      {members.length === 0 ? (
        <EmptyState icon={Users} title={t("empty.team")} desc={t("landing.step3d")} testid="team-empty" />
      ) : view === "matrix" ? (
        <MatrixView root={data.root} members={members} />
      ) : (
        <ListView members={members} t={t} />
      )}

      {/* Legend + summary */}
      {members.length > 0 && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <SummaryCard label="Direct Referrals" value={data.total} />
          <SummaryCard label="Active (GREEN)" value={data.active} accent />
          <SummaryCard label="Pending (RED)" value={data.total - data.active} />
          <SummaryCard label="Level" value="1" sub="Phase 1" />
        </div>
      )}
    </div>
  );
}

function MatrixView({ root, members }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-gradient-to-b from-brand-50/40 to-white p-6 shadow-card">
      <div className="flex min-w-max flex-col items-center">
        {/* Root */}
        <NodeCard node={{ ...root, isRoot: true }} index={0} />
        {/* connector */}
        <div className="h-8 w-px bg-brand/30" />
        <div className="relative flex items-start gap-6">
          {/* horizontal line across children */}
          {members.length > 1 && <div className="absolute left-0 right-0 top-0 h-px bg-brand/30" />}
          {members.map((m, i) => (
            <div key={m.distributor_id} className="flex flex-col items-center">
              <div className="h-8 w-px bg-brand/30" />
              <NodeCard node={m} index={i + 1} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function NodeCard({ node, index }) {
  const green = node.status === "green";
  const initials = (node.full_name || "U").split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase();
  return (
    <motion.div
      initial={{ opacity: 0, y: 10, scale: 0.96 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ delay: index * 0.06 }}
      className={`relative w-44 rounded-xl border bg-white p-4 text-center shadow-card ${node.isRoot ? "border-gold ring-1 ring-gold/40" : "border-brand-50"}`}
      data-testid={`node-${node.distributor_id}`}
    >
      {node.isRoot && <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 rounded-full bg-gold px-2 py-0.5 text-[9px] font-bold text-forest"><Crown size={10} className="mr-0.5 inline" />YOU</span>}
      <div className={`mx-auto flex h-12 w-12 items-center justify-center rounded-full font-display text-base font-bold text-white ${green ? "bg-forest" : "bg-danger"}`}>{initials}</div>
      <div className="mt-2 truncate text-sm font-semibold text-ink">{node.full_name}</div>
      <div className="text-xs font-medium text-forest">{node.distributor_id}</div>
      <div className="mt-2 flex items-center justify-center gap-1.5">
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold ${green ? "bg-brand-50 text-brand" : "bg-danger/10 text-danger"}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${green ? "bg-brand" : "bg-danger"}`} />{green ? "GREEN" : "RED"}
        </span>
        {!node.isRoot && node.downline_count > 0 && (
          <span className="rounded-full bg-gold-light px-2 py-0.5 text-[10px] font-semibold text-gold">+{node.downline_count}</span>
        )}
      </div>
    </motion.div>
  );
}

function ListView({ members, t }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-white shadow-card">
      <table className="w-full text-sm">
        <thead><tr className="border-b border-brand-50 text-left text-muted2"><th className="p-4">{t("common.name")}</th><th className="p-4">ID</th><th className="p-4">{t("common.status")}</th><th className="p-4">Downline</th><th className="p-4">Location</th><th className="p-4">Joined</th></tr></thead>
        <tbody>
          {members.map((m) => (
            <tr key={m.distributor_id} className="border-b border-brand-50/60" data-testid={`team-row-${m.distributor_id}`}>
              <td className="p-4 font-medium text-ink">{m.full_name}</td>
              <td className="p-4 text-forest">{m.distributor_id}</td>
              <td className="p-4"><StatusBadge status={m.status} size="sm" /></td>
              <td className="p-4 text-muted2">{m.downline_count ?? 0}</td>
              <td className="p-4 text-muted2">{[m.city, m.state].filter(Boolean).join(", ") || "—"}</td>
              <td className="p-4 text-muted2">{(m.joined_at || "").slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SummaryCard({ label, value, sub, accent }) {
  return (
    <div className="rounded-2xl border border-brand-50 bg-white p-4 shadow-card">
      <div className="text-xs uppercase tracking-wide text-muted2">{label}</div>
      <div className={`mt-1 font-display text-2xl font-semibold ${accent ? "text-brand" : "text-forest"}`}>{value}</div>
      {sub && <div className="text-xs text-muted2">{sub}</div>}
    </div>
  );
}
