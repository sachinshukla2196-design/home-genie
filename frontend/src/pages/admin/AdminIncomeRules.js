import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { SlidersHorizontal, History, CheckCircle2, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { API, apiError } from "@/lib/api";

const fmtDate = (s) => (s ? new Date(s).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—");

export default function AdminIncomeRules() {
  const [cats, setCats] = useState([]);
  const [note, setNote] = useState("");
  const [edit, setEdit] = useState(null);       // category being edited
  const [form, setForm] = useState({ rate_percent: "", enabled: true, effective_at: "", reason: "" });
  const [review, setReview] = useState(false);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState(null); // {category, versions}

  const load = () => API.get("/admin/income-config").then(({ data }) => { setCats(data.categories || []); setNote(data.note || ""); }).catch((e) => toast.error(apiError(e)));
  useEffect(() => { load(); }, []);

  const openEdit = (c) => {
    setEdit(c);
    setReview(false);
    setForm({
      rate_percent: String(c.current?.rate_percent ?? c.applied_rate ?? c.default_rate),
      enabled: c.current ? !!c.current.enabled : true,
      effective_at: "",
      reason: "",
    });
  };

  const validate = () => {
    const r = parseFloat(form.rate_percent);
    if (isNaN(r) || r < 0 || r > 100) { toast.error("Rate must be between 0 and 100."); return false; }
    if (form.reason.trim().length < 3) { toast.error("Please enter a change reason."); return false; }
    return true;
  };

  const publish = async () => {
    setBusy(true);
    try {
      const { data } = await API.post(`/admin/income-config/${edit.key}`, {
        rate_percent: parseFloat(form.rate_percent),
        enabled: form.enabled,
        effective_at: form.effective_at || null,
        reason: form.reason.trim(),
      });
      toast.success(data.message);
      setEdit(null); setReview(false);
      load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const openHistory = async (c) => {
    try { const { data } = await API.get(`/admin/income-config/${c.key}/history`); setHistory({ ...data, name: c.name }); }
    catch (e) { toast.error(apiError(e)); }
  };

  return (
    <div className="space-y-6" data-testid="admin-income-rules">
      <div>
        <h1 className="font-display text-2xl font-semibold text-ink">Income &amp; Commission Rules</h1>
        <p className="mt-1 text-sm text-muted2">{note}</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {cats.map((c) => (
          <div key={c.key} className="rounded-2xl border border-brand-50 bg-white p-5 shadow-card" data-testid={`rule-card-${c.key}`}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-display text-base font-semibold text-ink">{c.name}</h3>
                <p className="mt-1 text-xs text-muted2">{c.note}</p>
              </div>
              <span className={`shrink-0 rounded-full px-2 py-1 text-xs font-medium ${c.payout_active ? "bg-forest/10 text-forest" : "bg-gold/10 text-gold"}`}>
                {c.payout_active ? "Payout active" : "Config only"}
              </span>
            </div>
            <div className="mt-4 flex items-end justify-between">
              <div>
                <div className="font-display text-3xl font-semibold text-forest" data-testid={`rule-rate-${c.key}`}>{c.applied_rate}%</div>
                <div className="mt-1 text-xs text-muted2">
                  {c.applied_enabled ? "Enabled" : "Disabled"} · v{c.applied_version}
                  {c.current?.effective_at ? ` · eff ${fmtDate(c.current.effective_at)}` : ""}
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" className="gap-1 rounded-full" onClick={() => openHistory(c)} data-testid={`rule-history-${c.key}`}>
                  <History size={14} /> History
                </Button>
                <Button size="sm" className="rounded-full" onClick={() => openEdit(c)} data-testid={`rule-edit-${c.key}`}>Edit</Button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Edit / publish dialog */}
      <Dialog open={!!edit} onOpenChange={(o) => { if (!o) { setEdit(null); setReview(false); } }}>
        <DialogContent data-testid="rule-edit-dialog">
          <DialogHeader><DialogTitle>{edit?.name}</DialogTitle></DialogHeader>
          {edit && !review && (
            <div className="space-y-4">
              {!edit.payout_active && (
                <div className="flex gap-2 rounded-lg bg-gold/10 p-3 text-xs text-gold">
                  <AlertTriangle size={16} className="shrink-0" />
                  Rate is saved for records, but no payout runs for this category until its allocation rule is defined.
                </div>
              )}
              <div>
                <Label className="text-sm">Rate (%)</Label>
                <Input type="number" step="0.01" min="0" max="100" value={form.rate_percent}
                  onChange={(e) => setForm((f) => ({ ...f, rate_percent: e.target.value }))}
                  className="mt-1.5 h-11 rounded-lg" data-testid="rule-input-rate" />
              </div>
              <div className="flex items-center justify-between rounded-lg border border-brand-50 p-3">
                <div><Label className="text-sm">Enabled</Label><p className="text-xs text-muted2">Turn payouts for this category on or off</p></div>
                <Switch checked={form.enabled} onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))} data-testid="rule-switch-enabled" />
              </div>
              <div>
                <Label className="text-sm">Effective from</Label>
                <Input type="datetime-local" value={form.effective_at}
                  onChange={(e) => setForm((f) => ({ ...f, effective_at: e.target.value }))}
                  className="mt-1.5 h-11 rounded-lg" data-testid="rule-input-effective" />
                <p className="mt-1 text-xs text-muted2">Leave blank to apply immediately. Applies only to new transactions from this time.</p>
              </div>
              <div>
                <Label className="text-sm">Change reason</Label>
                <Textarea value={form.reason} onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
                  placeholder="Why is this changing?" className="mt-1.5 rounded-lg" data-testid="rule-input-reason" />
              </div>
            </div>
          )}
          {edit && review && (
            <div className="space-y-3 text-sm" data-testid="rule-review">
              <p className="text-muted2">Please confirm this change:</p>
              <div className="rounded-lg border border-brand-50 p-3">
                <Row k="Category" v={edit.name} />
                <Row k="Rate" v={`${edit.applied_rate}%  →  ${parseFloat(form.rate_percent)}%`} />
                <Row k="Status" v={form.enabled ? "Enabled" : "Disabled"} />
                <Row k="Effective" v={form.effective_at ? fmtDate(form.effective_at) : "Immediately"} />
                <Row k="Reason" v={form.reason.trim()} />
              </div>
              <p className="text-xs text-muted2">Previously-posted commissions are not affected — they keep their original rule version.</p>
            </div>
          )}
          <DialogFooter>
            {!review ? (
              <Button onClick={() => { if (validate()) setReview(true); }} data-testid="rule-review-btn">Review &amp; publish</Button>
            ) : (
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setReview(false)} disabled={busy}>Back</Button>
                <Button onClick={publish} disabled={busy} data-testid="rule-confirm-btn">
                  <CheckCircle2 size={16} className="mr-1" /> {busy ? "Publishing…" : "Confirm publish"}
                </Button>
              </div>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* History dialog */}
      <Dialog open={!!history} onOpenChange={(o) => { if (!o) setHistory(null); }}>
        <DialogContent data-testid="rule-history-dialog">
          <DialogHeader><DialogTitle>{history?.name} — version history</DialogTitle></DialogHeader>
          <div className="max-h-96 space-y-2 overflow-y-auto">
            {(history?.versions || []).length === 0 && <p className="text-sm text-muted2">No published versions yet — the default rate is in effect.</p>}
            {(history?.versions || []).map((v) => (
              <div key={v.version} className="rounded-lg border border-brand-50 p-3 text-sm" data-testid={`history-v${v.version}`}>
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-ink">v{v.version} · {v.rate_percent}% · {v.enabled ? "Enabled" : "Disabled"}</span>
                  <span className="text-xs text-muted2">{fmtDate(v.effective_at)}</span>
                </div>
                <div className="mt-1 text-xs text-muted2">By {v.created_by || "—"} · {fmtDate(v.created_at)} · was {v.old_rate}%</div>
                {v.reason && <div className="mt-1 text-xs text-ink">"{v.reason}"</div>}
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const Row = ({ k, v }) => (
  <div className="flex justify-between gap-4 py-1"><span className="text-muted2">{k}</span><span className="text-right font-medium text-ink">{v}</span></div>
);
