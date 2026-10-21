import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function AdminSettings() {
  const { t } = useI18n();
  const { user } = useAuth();
  const [s, setS] = useState(null);
  const isSuper = user?.role === "super_admin";
  const set = (k) => (e) => setS((p) => ({ ...p, [k]: e.target?.value ?? e }));

  useEffect(() => { API.get("/admin/settings").then(({ data }) => setS(data)).catch(() => {}); }, []);

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
        <h3 className="font-display font-medium text-ink">Commission & Points</h3>
        <p className="text-xs text-muted2">Percentages apply to the product price before GST, on qualifying sales made through a HomeGenie share link. Recruitment alone never earns commission.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <F label="Direct sales commission %" type="number" value={s.commission_direct_pct} onChange={set("commission_direct_pct")} testid="set-direct-pct" />
          <F label="Permanent referral commission %" type="number" value={s.commission_referral_pct} onChange={set("commission_referral_pct")} testid="set-referral-pct" />
          <F label="Team sales commission %" type="number" value={s.commission_team_pct} onChange={set("commission_team_pct")} testid="set-team-pct" />
          <F label="Return window (days) before points release" type="number" value={s.return_window_days} onChange={set("return_window_days")} testid="set-return-window" />
          <F label="Point value (Rs per point)" type="number" value={s.point_value} onChange={set("point_value")} testid="set-point-value" />
          <F label="GST %" type="number" value={s.gst_percent} onChange={set("gst_percent")} testid="set-gst" />
        </div>
        <label className="flex items-center justify-between rounded-lg border border-brand-50 p-3 text-sm"><span>Allow point withdrawal to bank</span><Switch checked={s.points_withdrawal_enabled} onCheckedChange={(v) => setS((p) => ({ ...p, points_withdrawal_enabled: v }))} data-testid="set-withdraw-enabled" /></label>
        <label className="flex items-center justify-between rounded-lg border border-brand-50 p-3 text-sm"><span>Require identity verification before point withdrawal</span><Switch checked={s.require_kyc_for_withdrawal} onCheckedChange={(v) => setS((p) => ({ ...p, require_kyc_for_withdrawal: v }))} data-testid="set-kyc-req" /></label>
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

    </div>
  );
}

function F({ label, type = "text", value, onChange, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input type={type} value={value ?? ""} onChange={onChange} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} /></div>;
}
