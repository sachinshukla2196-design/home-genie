import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { Settings, Percent, Building2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
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

  if (!s) return (
    <div className="mx-auto max-w-4xl space-y-5">
      <PageHeader title={t("nav.settings")} icon={Settings} />
      <Skeleton className="h-80 rounded-[20px]" />
      <Skeleton className="h-56 rounded-[20px]" />
    </div>
  );

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <PageHeader title={t("nav.settings")} icon={Settings} />
      <SectionCard title="Commission & Points" icon={Percent}>
        <p className="-mt-1 mb-4 text-sm text-muted2">Percentages apply to the product price before GST, on qualifying sales made through a HomeGenie share link. Recruitment alone never earns commission.</p>
        <div className="grid gap-4 md:grid-cols-2">
          <F label="Direct sales commission %" type="number" value={s.commission_direct_pct} onChange={set("commission_direct_pct")} testid="set-direct-pct" />
          <F label="Permanent referral commission %" type="number" value={s.commission_referral_pct} onChange={set("commission_referral_pct")} testid="set-referral-pct" />
          <F label="Team sales commission %" type="number" value={s.commission_team_pct} onChange={set("commission_team_pct")} testid="set-team-pct" />
          <F label="Return window (days) before points release" type="number" value={s.return_window_days} onChange={set("return_window_days")} testid="set-return-window" />
          <F label="Point value (Rs per point)" type="number" value={s.point_value} onChange={set("point_value")} testid="set-point-value" />
          <F label="GST %" type="number" value={s.gst_percent} onChange={set("gst_percent")} testid="set-gst" />
        </div>
        <div className="my-5 border-t border-brand-50" />
        <div className="grid gap-4 md:grid-cols-2">
          <F label="Cash handling fee (COD)" type="number" value={s.cod_fee} onChange={set("cod_fee")} testid="set-cod-fee" />
          <F label="Bronze badge — monthly sales" type="number" value={s.badge_t1_sales} onChange={set("badge_t1_sales")} testid="set-badge-1" />
          <F label="Silver badge — monthly sales" type="number" value={s.badge_t2_sales} onChange={set("badge_t2_sales")} testid="set-badge-2" />
          <F label="Gold badge — monthly sales" type="number" value={s.badge_t3_sales} onChange={set("badge_t3_sales")} testid="set-badge-3" />
          <F label="Diamond badge — monthly sales" type="number" value={s.badge_t4_sales} onChange={set("badge_t4_sales")} testid="set-badge-4" />
        </div>
      </SectionCard>
      <SectionCard bodyClassName="space-y-2.5">
        <label className="hg-tile flex cursor-pointer items-center justify-between gap-3 rounded-xl p-3.5 text-sm text-ink"><span className="min-w-0">Cash on delivery available</span><Switch checked={s.cod_enabled} onCheckedChange={(v) => setS((p) => ({ ...p, cod_enabled: v }))} data-testid="set-cod-enabled" /></label>
        <label className="hg-tile flex cursor-pointer items-center justify-between gap-3 rounded-xl p-3.5 text-sm text-ink"><span className="min-w-0">Allow point withdrawal to bank</span><Switch checked={s.points_withdrawal_enabled} onCheckedChange={(v) => setS((p) => ({ ...p, points_withdrawal_enabled: v }))} data-testid="set-withdraw-enabled" /></label>
        <label className="hg-tile flex cursor-pointer items-center justify-between gap-3 rounded-xl p-3.5 text-sm text-ink"><span className="min-w-0">Require identity verification before point withdrawal</span><Switch checked={s.require_kyc_for_withdrawal} onCheckedChange={(v) => setS((p) => ({ ...p, require_kyc_for_withdrawal: v }))} data-testid="set-kyc-req" /></label>
      </SectionCard>
      <SectionCard title="Company Information" icon={Building2}>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="md:col-span-2"><F label="Company Name" value={s.company_name} onChange={set("company_name")} testid="set-company-name" /></div>
          <F label="Email" value={s.company_email} onChange={set("company_email")} testid="set-company-email" />
          <F label="Phone" value={s.company_phone} onChange={set("company_phone")} testid="set-company-phone" />
          <div className="md:col-span-2"><F label="Address" value={s.company_address} onChange={set("company_address")} testid="set-company-address" /></div>
        </div>
      </SectionCard>
      <div className="flex justify-end">
        <Button onClick={save} className="hg-btn h-11 w-full rounded-full px-8 sm:w-auto" data-testid="settings-save"><Save size={16} className="mr-1.5" /> {t("cta.save")}</Button>
      </div>
    </div>
  );
}

function F({ label, type = "text", value, onChange, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input type={type} value={value ?? ""} onChange={onChange} className="mt-1.5" data-testid={testid} /></div>;
}
