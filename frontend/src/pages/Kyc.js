import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck, CheckCircle2, Clock, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useI18n } from "@/context/I18nContext";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const STATUS_UI = {
  verified: { icon: CheckCircle2, cls: "bg-brand-50 text-brand", key: "kyc.verified" },
  pending: { icon: Clock, cls: "bg-gold-light text-gold", key: "kyc.pending" },
  rejected: { icon: XCircle, cls: "bg-danger/10 text-danger", key: "kyc.rejected" },
  not_started: { icon: ShieldCheck, cls: "bg-muted text-muted2", key: "kyc.notStarted" },
};

export default function Kyc() {
  const { t } = useI18n();
  const { refresh } = useAuth();
  const [kyc, setKyc] = useState(null);
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState({ pan: "", aadhaar: "", account_holder_name: "", bank_account: "", ifsc: "", bank_name: "" });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const load = () => API.get("/kyc").then(({ data }) => setKyc(data)).catch(() => setKyc({ status: "not_started" }));
  useEffect(() => { load(); }, []);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await API.post("/kyc", form);
      toast.success(t("kyc.pending"));
      await load(); await refresh();
    } catch (err) { toast.error(apiError(err)); } finally { setLoading(false); }
  };

  if (!kyc) return <Skeleton className="h-96 rounded-2xl" />;
  const ui = STATUS_UI[kyc.status] || STATUS_UI.not_started;
  const StatusIcon = ui.icon;
  const editable = kyc.status === "not_started" || kyc.status === "rejected";

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-2xl font-semibold text-ink">{t("kyc.title")}</h1>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${ui.cls}`} data-testid="kyc-status-badge"><StatusIcon size={14} /> {t(ui.key)}</span>
      </div>

      {kyc.status === "rejected" && kyc.rejection_reason && (
        <div className="rounded-xl bg-danger/10 px-4 py-3 text-sm text-danger">Rejected: {kyc.rejection_reason}</div>
      )}

      {!editable ? (
        <div className="space-y-3 rounded-2xl border border-brand-50 bg-white p-6 shadow-card" data-testid="kyc-submitted">
          <Info label={t("kyc.pan")} value={kyc.pan} />
          <Info label={t("kyc.aadhaar")} value={kyc.aadhaar} />
          <Info label={t("kyc.holder")} value={kyc.account_holder_name} />
          <Info label={t("kyc.bank")} value={kyc.bank_account} />
          <Info label={t("kyc.ifsc")} value={kyc.ifsc} />
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-4 rounded-2xl border border-brand-50 bg-white p-6 shadow-card">
          <div className="grid gap-4 sm:grid-cols-2">
            <F label={t("kyc.pan")} value={form.pan} onChange={set("pan")} req testid="kyc-pan" />
            <F label={t("kyc.aadhaar")} value={form.aadhaar} onChange={set("aadhaar")} req testid="kyc-aadhaar" />
          </div>
          <F label={t("kyc.holder")} value={form.account_holder_name} onChange={set("account_holder_name")} req testid="kyc-holder" />
          <div className="grid gap-4 sm:grid-cols-2">
            <F label={t("kyc.bank")} value={form.bank_account} onChange={set("bank_account")} req testid="kyc-bank" />
            <F label={t("kyc.ifsc")} value={form.ifsc} onChange={set("ifsc")} req testid="kyc-ifsc" />
          </div>
          <F label={t("kyc.bankName")} value={form.bank_name} onChange={set("bank_name")} testid="kyc-bankname" />
          <Button type="submit" disabled={loading} className="w-full rounded-full bg-forest hover:bg-brand" data-testid="kyc-submit">{loading ? t("common.loading") : t("cta.submit")}</Button>
        </form>
      )}
    </div>
  );
}

function F({ label, value, onChange, req, testid }) {
  return <div><Label className="text-sm text-ink">{label}</Label><Input value={value} onChange={onChange} required={req} className="mt-1.5 h-11 rounded-lg focus-visible:ring-brand" data-testid={testid} /></div>;
}
function Info({ label, value }) {
  return <div className="flex justify-between border-b border-brand-50/60 pb-2 text-sm"><span className="text-muted2">{label}</span><span className="font-medium text-ink">{value || "—"}</span></div>;
}
