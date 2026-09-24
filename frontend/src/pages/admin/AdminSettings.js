import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { TreeView } from "@/components/TreeView";
import { API, apiError } from "@/lib/api";

export default function AdminSettings() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [s, setS] = useState(null);
  const [master, setMaster] = useState(null);
  const [tree, setTree] = useState(null);
  const isSuper = user?.role === "super_admin";
  const set = (k) => (e) => setS((p) => ({ ...p, [k]: e.target?.value ?? e }));

  useEffect(() => { API.get("/admin/settings").then(({ data }) => setS(data)).catch(() => {}); }, []);
  useEffect(() => {
    if (user?.role === "super_admin") {
      API.get("/admin/master").then(({ data }) => setMaster(data)).catch(() => {});
      API.get("/admin/tree").then(({ data }) => setTree(data)).catch(() => {});
    }
  }, [user]);

  const toggleMaster = async () => {
    try {
      const { data } = await API.put("/admin/master/status", { active: !master.active });
      setMaster((m) => ({ ...m, active: data.active }));
      toast.success(data.active ? "Master ID activated" : "Master ID deactivated");
    } catch (e) { toast.error(apiError(e)); }
  };
  const masterLink = master ? `${window.location.origin}/register?ref=${master.code}` : "";

  const save = async () => {
    try {
      await API.put("/admin/settings", {
        activation_amount: parseFloat(s.activation_amount), activation_product_sku: s.activation_product_sku,
        referral_commission: parseFloat(s.referral_commission),
        require_kyc_for_withdrawal: s.require_kyc_for_withdrawal, gst_percent: parseFloat(s.gst_percent),
        company_name: s.company_name, company_email: s.company_email, company_phone: s.company_phone, company_address: s.company_address,
      });
      toast.success(t("cta.save"));
    } catch (e) { toast.error(apiError(e)); }
  };

  if (!s) return <Skeleton className="h-96 rounded-2xl" />;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="font-display text-2xl font-semibold text-ink">{t("nav.settings")}</h1>
      <div className="space-y-4 rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <h3 className="font-display font-medium text-ink">Business Rules</h3>
        <div className="grid gap-4 sm:grid-cols-2">
          <F label="Activation Amount (₹)" type="number" value={s.activation_amount} onChange={set("activation_amount")} testid="set-activation-amount" />
          <F label="Activation Product SKU" value={s.activation_product_sku} onChange={set("activation_product_sku")} testid="set-activation-sku" />
          <F label="Referral Commission (₹)" type="number" value={s.referral_commission} onChange={set("referral_commission")} testid="set-referral" />
          <F label="GST %" type="number" value={s.gst_percent} onChange={set("gst_percent")} testid="set-gst" />
        </div>
        <label className="flex items-center justify-between rounded-lg border border-brand-50 p-3 text-sm"><span>Require KYC for withdrawal</span><Switch checked={s.require_kyc_for_withdrawal} onCheckedChange={(v) => setS((p) => ({ ...p, require_kyc_for_withdrawal: v }))} data-testid="set-kyc-req" /></label>
      </div>
      <div className="space-y-4 rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
        <h3 className="font-display font-medium text-ink">Company Information</h3>
        <F label="Company Name" value={s.company_name} onChange={set("company_name")} testid="set-company-name" />
        <div className="grid gap-4 sm:grid-cols-2">
          <F label="Email" value={s.company_email} onChange={set("company_email")} testid="set-company-email" />
          <F label="Phone" value={s.company_phone} onChange={set("company_phone")} testid="set-company-phone" />
        </div>
        <F label="Address" value={s.company_address} onChange={set("company_address")} testid="set-company-address" />
      </div>
      <Button onClick={save} className="rounded-full bg-forest hover:bg-brand" data-testid="settings-save">{t("cta.save")}</Button>

      {isSuper && master && (
        <div className="space-y-3 rounded-2xl border border-gold/40 bg-gold-light/30 p-6" data-testid="master-admin-card">
          <div className="flex items-center justify-between">
            <h3 className="font-display font-medium text-forest">Master Admin / Root</h3>
            <button onClick={toggleMaster} className={`rounded-full px-3 py-1 text-xs font-semibold ${master.active ? "bg-brand-50 text-brand" : "bg-danger/10 text-danger"}`} data-testid="master-status-toggle">{master.active ? "ACTIVE" : "INACTIVE"} · tap to toggle</button>
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div><div className="text-xs text-muted2">Master ID</div><div className="font-mono font-semibold text-forest">{master.code}</div></div>
            <div><div className="text-xs text-muted2">Direct Referrals</div><div className="font-semibold">{master.direct_referrals}</div></div>
            <div><div className="text-xs text-muted2">Network Members</div><div className="font-semibold">{master.network_members}</div></div>
            <div><div className="text-xs text-muted2">Referral Code</div><button onClick={() => { navigator.clipboard?.writeText(master.code); toast.success("Copied"); }} className="font-mono font-semibold text-forest underline" data-testid="master-copy-code">{master.code}</button></div>
          </div>
          <div className="text-xs text-muted2">Referral link: <button onClick={() => { navigator.clipboard?.writeText(masterLink); toast.success("Link copied"); }} className="text-forest underline" data-testid="master-copy-link">{masterLink}</button></div>
          <div className="mt-2 rounded-xl border border-brand-50 bg-white p-3">
            <div className="mb-1 text-xs font-semibold text-muted2">Network Tree (root: MST000001)</div>
            <TreeView tree={tree} testid="admin-network-tree" />
          </div>
        </div>
      )}
    </div>
  );
}

function F({ label, type = "text", value, onChange, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input type={type} value={value ?? ""} onChange={onChange} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} /></div>;
}
