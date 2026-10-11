import React, { useState, useEffect } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { API, apiError } from "@/lib/api";

const money = (v) => `₹${Number(v || 0).toLocaleString("en-IN")}`;
const thisMonth = () => new Date().toISOString().slice(0, 7);

export default function AdminMonthlyIncome() {
  const [month, setMonth] = useState(thisMonth());
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rules, setRules] = useState([]);

  useEffect(() => {
    API.get("/admin/income-rules")
      .then(({ data }) => setRules(data.rules || []))
      .catch(() => {});
  }, []);

  const preview = async () => {
    setBusy(true);
    try {
      const { data } = await API.get(`/admin/monthly-income/preview?month=${month}`);
      setData(data);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const distribute = async () => {
    if (!window.confirm(`Distribute the ${month} Monthly Fixed Income pool equally to all GREEN IDs? This is one-time per month.`)) return;
    setBusy(true);
    try {
      const { data } = await API.post("/admin/monthly-income/distribute", { month });
      setData(data);
      toast.success(data.message);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const Stat = ({ label, value, testid }) => (
    <div className="rounded-xl border border-brand-50 bg-white p-4" data-testid={testid}>
      <div className="text-xs font-medium uppercase tracking-wide text-muted2">{label}</div>
      <div className="mt-1 font-display text-xl font-semibold text-ink">{value}</div>
    </div>
  );

  const done = data && (data.status === "completed" || data.status === "no_eligible");

  return (
    <div className="space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">Monthly Fixed Income (1% Pool)</h1>
      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm text-ink">Month
            <input type="month" value={month} onChange={(e) => setMonth(e.target.value)} className="mt-1 block h-11 rounded-lg border border-brand-50 px-3 focus:outline-none focus:ring-2 focus:ring-brand" data-testid="mfi-month" />
          </label>
          <Button onClick={preview} disabled={busy} variant="outline" className="rounded-full" data-testid="mfi-preview-btn">{busy ? "…" : "Preview"}</Button>
          <Button onClick={distribute} disabled={busy || (data && data.status === "completed")} className="rounded-full bg-forest hover:bg-brand" data-testid="mfi-distribute-btn">
            {data && data.status === "completed" ? "Already Distributed" : "Distribute Pool"}
          </Button>
        </div>
        <p className="mt-3 text-xs text-muted2">Pool = 1% of the month's eligible product-sales turnover (subtotal excl GST), split equally among all GREEN IDs. One-time per month; re-running never double-credits.</p>
      </div>

      {data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4" data-testid="mfi-results">
          <Stat label="Turnover (excl GST)" value={money(data.turnover)} testid="mfi-turnover" />
          <Stat label="1% Pool" value={money(data.pool)} testid="mfi-pool" />
          <Stat label="Eligible GREEN IDs" value={data.eligible_green_ids} testid="mfi-green-count" />
          <Stat label="Per-ID Allocation" value={money(data.per_id_allocation)} testid="mfi-per-id" />
          <Stat label="Total Distributed" value={money(data.total_distributed)} testid="mfi-distributed" />
          <Stat label="Rounding Residual" value={money(data.rounding_residual)} testid="mfi-residual" />
          <Stat label="Status" value={<span className={done ? "text-forest" : "text-gold"}>{data.status}</span>} testid="mfi-status" />
          {data.processed_at && <Stat label="Processed At" value={String(data.processed_at).slice(0, 10)} testid="mfi-processed-at" />}
        </div>
      )}

      <div className="rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="additional-income-rules">
        <h2 className="font-display text-lg font-semibold text-ink">Additional Income Rules (Rule 6)</h2>
        <p className="mt-1 text-xs text-muted2">Rates are locked. Payouts are NOT active until the business supplies the missing calculation bases, clearance thresholds and payout periods.</p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-brand-50 text-xs uppercase tracking-wide text-muted2">
                <th className="py-2 pr-3">Income</th>
                <th className="py-2 pr-3">Rate</th>
                <th className="py-2 pr-3">Trigger</th>
                <th className="py-2 pr-3">Recipient</th>
                <th className="py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.key} className="border-b border-brand-50/60 align-top" data-testid={`income-rule-${r.key}`}>
                  <td className="py-3 pr-3 font-medium text-ink">{r.name}</td>
                  <td className="py-3 pr-3 font-semibold text-forest">{r.rate_percent}%</td>
                  <td className="py-3 pr-3 text-muted2">{r.trigger}</td>
                  <td className="py-3 pr-3 text-muted2">{r.recipient || "—"}</td>
                  <td className="py-3">
                    <span className="rounded-full bg-gold/10 px-2 py-1 text-xs font-medium text-gold">Pending business clarification</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
