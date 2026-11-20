import React, { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

/** Shown to the account holder while HOME GENIES has PROPOSED a new mobile/email for the account. Nothing changes until the
 *  holder confirms with a code sent to their CURRENT mobile (never to the proposed one), or rejects it. */
export function ContactChangeBanner() {
  const { refresh } = useAuth();
  const [info, setInfo] = useState(null);
  const [otp, setOtp] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { API.get("/auth/contact-change").then(({ data }) => setInfo(data)).catch(() => setInfo(null)); }, []);
  const p = info?.pending;
  if (!p) return null;

  const act = async (fn, ok) => {
    setBusy(true);
    try { await fn(); if (ok) toast.success(ok); } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };
  const send = () => act(async () => { await API.post("/auth/contact-change/send-otp", { request_id: p.id }); setSent(true); }, `Code sent to ${info.otp_to}`);
  const confirm = () => act(async () => { await API.post("/auth/contact-change/confirm", { request_id: p.id, otp }); setInfo(null); await refresh(); }, "Contact details updated");
  const reject = () => act(async () => { await API.post("/auth/contact-change/reject", { request_id: p.id }); setInfo(null); await refresh(); }, "Change rejected");

  return (
    <div className="mx-auto mt-3 w-full max-w-5xl px-4" data-testid="contact-change-banner">
      <div className="hg-card flex flex-col gap-3 rounded-2xl p-4 ring-1 ring-hg-gold/40 sm:p-5">
        <div className="flex items-start gap-3">
          <span className="hg-icon-chip !h-9 !w-9 shrink-0 !rounded-xl !bg-hg-gold/15 !text-hg-gold"><ShieldAlert size={16} aria-hidden /></span>
          <p className="text-sm text-ink">
            HOME GENIES asked to change your {p.fields.map((f) => <span key={f} className="mr-1"><b>{f}</b> to <span className="font-mono">{p.new[f] || "(none)"}</span></span>)}.
            Nothing changes unless you confirm with a code sent to your <b>current</b> mobile {info.otp_to}. If you did not ask for this, reject it.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {!sent ? (
            <Button onClick={send} disabled={busy} className="hg-btn h-10 rounded-full px-5" data-testid="cc-send">Send code</Button>
          ) : (
            <>
              <Input value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" className="h-10 w-36" data-testid="cc-otp" />
              <Button onClick={confirm} disabled={busy || otp.length < 6} className="hg-btn h-10 rounded-full px-5" data-testid="cc-confirm">Confirm change</Button>
            </>
          )}
          <Button variant="outline" onClick={reject} disabled={busy} className="h-10 rounded-full px-5" data-testid="cc-reject">Reject</Button>
        </div>
      </div>
    </div>
  );
}
