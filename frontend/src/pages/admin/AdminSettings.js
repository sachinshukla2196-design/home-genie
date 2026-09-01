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
  const [resetting, setResetting] = useState(false);
  const isSuper = user?.role === "super_admin";
  const set = (k) => (e) => setS((p) => ({ ...p, [k]: e.target?.value ?? e }));

  useEffect(() => { API.get("/admin/settings").then(({ data }) => setS(data)).catch(() => {}); }, []);

  const resetBetaData = async () => {
    const typed = window.prompt('WARNING: This permanently deletes ALL distributor/customer & transaction data (users, orders, payments, wallets, referrals, KYC, withdrawals, registration requests).\n\nYour ADMIN accounts, products, settings and Reference IDs are NOT deleted — they are always kept.\n\nThis cannot be undone. Type RESET to confirm.');
    if (typed !== "RESET") { if (typed !== null) toast.error("Confirmation text did not match. Nothing was deleted."); return; }
    setResetting(true);
    try {
      const { data } = await API.post("/admin/maintenance/reset-data", { confirm: "RESET" });
      toast.success(data.message || "Beta data cleared.");
    } catch (e) { toast.error(apiError(e)); } finally { setResetting(false); }
  };

  const save = async () => {
    try {
      await API.put("/admin/settings", {
        activation_amount: parseFloat(s.activation_amount), activation_product_sku: s.activation_product_sku,
        referral_commission: parseFloat(s.referral_commission), withdrawal_minimum: parseFloat(s.withdrawal_minimum),
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
          <F label="Withdrawal Minimum (₹)" type="number" value={s.withdrawal_minimum} onChange={set("withdrawal_minimum")} testid="set-wd-min" />
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

      {isSuper && (
        <div className="space-y-3 rounded-2xl border border-danger/30 bg-danger/5 p-6" data-testid="data-management-card">
          <h3 className="font-display font-medium text-danger">Data Management — Reset BETA Data</h3>
          <p className="text-sm text-muted2">Permanently deletes all distributor / customer and transaction data (users, orders, payments, wallets, referrals, KYC, withdrawals, registration requests). <b>Your admin accounts, products, company settings and Reference IDs are always preserved — never deleted.</b> This cannot be undone.</p>
          <Button onClick={resetBetaData} disabled={resetting} className="rounded-full bg-danger text-white hover:bg-danger/90" data-testid="reset-beta-data-btn">
            {resetting ? "Resetting…" : "Reset BETA Data"}
          </Button>
        </div>
      )}
    </div>
  );
}

function F({ label, type = "text", value, onChange, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input type={type} value={value ?? ""} onChange={onChange} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} /></div>;
}
