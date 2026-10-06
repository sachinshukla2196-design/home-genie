import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { Users, List, Network, Crown, Layers, ChevronDown, Copy, MessageCircle, Share2 } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API } from "@/lib/api";

const money = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;
// User-facing rank/designation names by depth (backend keeps numeric levels internally).

const RANK_ABBR = { 1: "GD", 2: "BD", 3: "AD", 4: "CD", 5: "PD", 6: "MD", 7: "RD", 8: "DD", 9: "MDD" };

export default function Team() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [view, setView] = useState("levels");

  useEffect(() => { API.get("/team").then(({ data }) => setData(data)).catch(() => setData({ members: [], levels: [] })); }, []);
  if (!data) return <Skeleton className="h-64 rounded-2xl" />;

  const members = data.members || [];
  const levels = data.levels || [];
  const hasTeam = (data.total ?? members.length) > 0;

  const TABS = [
    { id: "levels", label: "Ranks", icon: Layers },
    { id: "matrix", label: "Matrix", icon: Network },
    { id: "list", label: "List", icon: List },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.team")}</h1>
        <div className="flex items-center gap-3">
          {hasTeam && <div className="text-sm text-muted2">{data.total} members · {data.active} active</div>}
          <div className="inline-flex items-center rounded-full border border-brand-50 bg-white p-0.5">
            {TABS.map((tab) => (
              <button key={tab.id} onClick={() => setView(tab.id)} className={`flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all ${view === tab.id ? "bg-forest text-white" : "text-muted2"}`} data-testid={`team-view-${tab.id}`}>
                <tab.icon size={14} /> {tab.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <InviteCard user={user} t={t} />

      {!hasTeam ? (
        <EmptyState icon={Users} title={t("empty.team")} desc={t("landing.step3d")} testid="team-empty" />
      ) : view === "levels" ? (
        <LevelsView levels={levels} />
      ) : view === "matrix" ? (
        <MatrixView root={data.root} members={members} />
      ) : (
        <ListView members={members} t={t} />
      )}

      {hasTeam && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <SummaryCard label="Total Team" value={data.total} />
          <SummaryCard label="Active" value={data.active} accent />
          <SummaryCard label="Total Income" value={money(data.total_income)} />
          <SummaryCard label="Ranks Reached" value={levels.filter((l) => l.count > 0).length} sub="of 9" />
        </div>
      )}
    </div>
  );
}

function InviteCard({ user, t }) {
  const link = `${window.location.origin}/register?ref=${user?.distributor_id || ""}`;
  const text = `Join Anjali Herbal Life Ayurveda with my referral ID ${user?.distributor_id}. Register here: ${link}`;
  const msg = encodeURIComponent(text);
  const copy = () => { navigator.clipboard.writeText(link); toast.success(t("referral.copied") || "Link copied"); };
  return (
    <div className="rounded-2xl border border-brand-50 bg-gradient-to-r from-forest to-brand p-5 text-white shadow-card" data-testid="team-invite-card">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-gold-light"><Share2 size={14} /> Invite &amp; grow your team</div>
          <div className="mt-1 text-sm text-white/85">Your ID: <span className="font-display text-base font-semibold text-white" data-testid="invite-distributor-id">{user?.distributor_id || "—"}</span></div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={copy} size="sm" className="rounded-full bg-white/15 text-white hover:bg-white/25" data-testid="invite-copy-link"><Copy size={14} className="mr-1.5" /> Copy link</Button>
          <a href={`https://wa.me/?text=${msg}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-full bg-white px-4 py-2 text-sm font-medium text-forest hover:bg-white/90" data-testid="invite-whatsapp"><MessageCircle size={15} /> WhatsApp</a>
          <a href={`sms:?body=${msg}`} className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-4 py-2 text-sm font-medium text-white hover:bg-white/25" data-testid="invite-sms"><Share2 size={15} /> SMS</a>
        </div>
      </div>
    </div>
  );
}

function LevelsView({ levels }) {
  const active = levels.filter((l) => l.count > 0);
  const [open, setOpen] = useState(active.length ? active[0].level : null);
  if (!active.length) return null;
  return (
    <div className="space-y-3" data-testid="team-levels">
      {active.map((lvl) => {
        const isOpen = open === lvl.level;
        return (
          <div key={lvl.level} className="overflow-hidden rounded-2xl border border-brand-50 bg-white shadow-card" data-testid={`level-block-${lvl.level}`}>
            <button
              onClick={() => setOpen(isOpen ? null : lvl.level)}
              className="flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-brand-50/40"
              data-testid={`level-toggle-${lvl.level}`}
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-forest font-display text-xs font-bold text-white">{RANK_ABBR[lvl.level] || lvl.level}</span>
              <div className="min-w-0 flex-1">
                <div className="font-display text-base font-semibold text-ink">{RANK_ABBR[lvl.level] || `Level ${lvl.level}`}</div>
                <div className="text-xs text-muted2">{lvl.count} member{lvl.count !== 1 ? "s" : ""} · {lvl.active} active</div>
              </div>
              <div className="text-right">
                <div className="font-display text-sm font-semibold text-brand" data-testid={`level-income-${lvl.level}`}>{money(lvl.income)}</div>
                <div className="text-[10px] uppercase tracking-wide text-muted2">income</div>
              </div>
              <ChevronDown size={18} className={`shrink-0 text-muted2 transition-transform ${isOpen ? "rotate-180" : ""}`} />
            </button>
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden border-t border-brand-50">
                  <div className="divide-y divide-brand-50/60">
                    {lvl.members.map((m) => (
                      <div key={m.distributor_id} className="flex items-center gap-3 px-5 py-3" data-testid={`level-${lvl.level}-member-${m.distributor_id}`}>
                        {m.photo
                          ? <img src={m.photo} alt="" className="h-9 w-9 rounded-full object-cover" />
                          : <div className={`flex h-9 w-9 items-center justify-center rounded-full text-[11px] font-bold text-white ${m.status === "green" ? "bg-forest" : "bg-danger"}`}>{(m.full_name || "U").slice(0, 2).toUpperCase()}</div>}
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-medium text-ink">{m.full_name}</div>
                          <div className="text-xs text-forest">{m.distributor_id}</div>
                        </div>
                        <div className="hidden text-right sm:block">
                          <div className="text-xs font-semibold text-brand">{money(m.income)}</div>
                          <div className="text-[10px] text-muted2">{m.downline_count ?? 0} downline</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </div>
  );
}

function MatrixView({ root, members }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-brand-50 bg-gradient-to-b from-brand-50/40 to-white p-6 shadow-card">
      <div className="flex min-w-max flex-col items-center">
        <NodeCard node={{ ...root, isRoot: true }} index={0} />
        <div className="h-8 w-px bg-brand/30" />
        <div className="relative flex items-start gap-6">
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
      {node.photo
        ? <img src={node.photo} alt="" className={`mx-auto h-12 w-12 rounded-full object-cover ring-2 ${green ? "ring-brand" : "ring-danger"}`} />
        : <div className={`mx-auto flex h-12 w-12 items-center justify-center rounded-full font-display text-base font-bold text-white ${green ? "bg-forest" : "bg-danger"}`}>{initials}</div>}
      <div className="mt-2 truncate text-sm font-semibold text-ink">{node.full_name}</div>
      <div className="text-xs font-medium text-forest">{node.distributor_id}</div>
      {!node.isRoot && node.level && (
        <span className="mt-1.5 inline-flex items-center rounded-full bg-forest px-2 py-0.5 text-[10px] font-bold text-white" data-testid={`node-rank-${node.distributor_id}`}>
          {RANK_ABBR[node.level] || `L${node.level}`}
        </span>
      )}
      <div className="mt-2 flex items-center justify-center gap-1.5">
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
              <td className="p-4">
                <div className="flex items-center gap-2.5">
                  {m.photo
                    ? <img src={m.photo} alt="" className="h-8 w-8 rounded-full object-cover" />
                    : <div className="flex h-8 w-8 items-center justify-center rounded-full bg-forest text-[10px] font-bold text-white">{(m.full_name || "U").slice(0, 2).toUpperCase()}</div>}
                  <span className="font-medium text-ink">{m.full_name}</span>
                </div>
              </td>
              <td className="p-4 text-forest">{m.distributor_id}</td>
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
