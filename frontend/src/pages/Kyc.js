import React, { useEffect, useState } from "react";
import { toast } from "sonner";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader, SectionCard } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { API, apiError } from "@/lib/api";

const EMPTY = { pan: "", aadhaar: "", account_holder_name: "", bank_account: "", ifsc: "", bank_name: "" };
const NOTE = {
  not_started: "Add your identity and bank details. They are needed before points can be withdrawn to your bank.",
  pending: "Your details are being checked by HOME GENIES. You will get a notification when this is done.",
  verified: "Your details are verified. To change your bank account, submit new details; they will be checked again.",
  rejected: "Your details could not be verified. Please correct them and submit again.",
};

/** HG-02: the member submits PAN, Aadhaar and payout bank details (POST /api/kyc). Stored details are only shown masked. */
export default function Kyc() {
  const [info, setInfo] = useState(null);
  const [error, setError] = useState("");
  const [f, setF] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const load = () => API.get("/kyc").then(({ data }) => { setInfo(data); setError(""); }).catch((e) => setError(apiError(e)));
  useEffect(() => { load(); }, []);

  const valid = /^[A-Z]{5}\d{4}[A-Z]$/.test(f.pan) && /^\d{12}$/.test(f.aadhaar) && f.account_holder_name.trim().length >= 2
    && /^\d{6,18}$/.test(f.bank_account) && /^[A-Z]{4}0[A-Z0-9]{6}$/.test(f.ifsc);
  const submit = async (e) => {
    e.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    try { const { data } = await API.post("/kyc", f); toast.success(data.message || "Submitted"); setF(EMPTY); load(); }
    catch (err) { toast.error(apiError(err)); } finally { setBusy(false); }
  };
  const set = (k, upper) => (e) => setF((x) => ({ ...x, [k]: upper ? e.target.value.toUpperCase() : e.target.value }));

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageHeader title="Identity & bank (KYC)" icon={ShieldCheck} subtitle="Needed before points can be paid to your bank account." />
      <SectionCard title="Status" testid="kyc-status">
        {error ? <p className="text-sm text-danger">{error}</p> : !info ? <Skeleton className="h-16 rounded-2xl" /> : (
          <div className="space-y-2 text-sm">
            <div className="flex items-center gap-2"><StatusBadge status={info.status} /></div>
            <p className="text-muted2">{NOTE[info.status] || ""}</p>
            {info.status !== "not_started" && (
              <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                <div><dt className="text-xs text-muted2">PAN</dt><dd className="font-mono text-ink">{info.pan || "—"}</dd></div>
                <div><dt className="text-xs text-muted2">Bank account</dt><dd className="font-mono text-ink">{info.bank_account || "—"}</dd></div>
                {info.rejection_reason && <div className="sm:col-span-2"><dt className="text-xs text-muted2">Reason</dt><dd className="text-danger">{info.rejection_reason}</dd></div>}
              </dl>
            )}
          </div>
        )}
      </SectionCard>
      {info && info.status !== "pending" && (
        <SectionCard title={info.status === "not_started" ? "Submit your details" : "Submit new details"} testid="kyc-form">
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" autoComplete="off">
            <label className="text-sm text-ink">PAN<Input value={f.pan} onChange={set("pan", true)} maxLength={10} className="mt-1.5 font-mono" data-testid="kyc-pan" /></label>
            <label className="text-sm text-ink">Aadhaar number<Input value={f.aadhaar} onChange={(e) => setF((x) => ({ ...x, aadhaar: e.target.value.replace(/\D/g, "").slice(0, 12) }))} inputMode="numeric" className="mt-1.5 font-mono" data-testid="kyc-aadhaar" /></label>
            <label className="text-sm text-ink sm:col-span-2">Account holder name<Input value={f.account_holder_name} onChange={set("account_holder_name")} className="mt-1.5" data-testid="kyc-holder" /></label>
            <label className="text-sm text-ink">Bank account number<Input value={f.bank_account} onChange={(e) => setF((x) => ({ ...x, bank_account: e.target.value.replace(/\D/g, "").slice(0, 18) }))} inputMode="numeric" className="mt-1.5 font-mono" data-testid="kyc-account" /></label>
            <label className="text-sm text-ink">IFSC<Input value={f.ifsc} onChange={set("ifsc", true)} maxLength={11} className="mt-1.5 font-mono" data-testid="kyc-ifsc" /></label>
            <label className="text-sm text-ink sm:col-span-2">Bank name (optional)<Input value={f.bank_name} onChange={set("bank_name")} className="mt-1.5" data-testid="kyc-bank" /></label>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={!valid || busy} className="hg-btn h-11 rounded-full px-6" data-testid="kyc-submit">{busy ? "Submitting…" : "Submit for verification"}</Button>
              <p className="mt-2 text-xs text-muted2">PAN: 10 characters (e.g. ABCDE1234F). IFSC: 11 characters (e.g. SBIN0001234). Your details are stored securely and shown only masked.</p>
            </div>
          </form>
        </SectionCard>
      )}
    </div>
  );
}
