import React, { useEffect, useState } from "react";
import { KeyRound, LogOut } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const ADMIN_ROLES = ["super_admin", "admin", "accounts_admin", "support_admin"];

/** Shown instead of any signed-in page after HOME GENIES reset this account's password (user.must_change_password).
 *  The backend refuses every other request until the password is changed, so this is the only thing the account can do. */
export function ForcePasswordChange() {
  const { user, refresh, logout } = useAuth();
  const [f, setF] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState(false);
  const [otp, setOtp] = useState("");
  const [codeSent, setCodeSent] = useState(false);
  const needOtp = !!user?.password_change_otp_required;
  // The login response does not carry this flag; /auth/me does. Load it once so the code step is shown when required.
  useEffect(() => { if (user && user.password_change_otp_required === undefined) refresh(); }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  const sendCode = async () => {
    setBusy(true);
    try { const { data } = await API.post("/auth/forced-change/send-otp"); setCodeSent(true); toast.success(`Code sent to ${data.to}`); }
    catch (err) { toast.error(apiError(err)); } finally { setBusy(false); }
  };
  const isAdmin = ADMIN_ROLES.includes(user?.role);
  const ok = f.current && f.next.length >= 8 && /[A-Za-z]/.test(f.next) && /\d/.test(f.next) && f.next === f.confirm && f.next !== f.current && (!needOtp || otp.length === 6);

  const submit = async (e) => {
    e.preventDefault();
    if (!ok || busy) return;
    setBusy(true);
    try {
      const { data } = await API.put("/auth/change-password", { current_password: f.current, new_password: f.next, otp });
      if (data.token) localStorage.setItem("anj_token", data.token);
      toast.success("Password changed");
      await refresh();
    } catch (err) { toast.error(apiError(err)); } finally { setBusy(false); }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-4" data-testid="force-password-change">
      <form onSubmit={submit} className="hg-card w-full max-w-md space-y-4 rounded-3xl p-6" autoComplete="off">
        <div className="flex items-center gap-3">
          <span className="hg-icon-chip !h-10 !w-10 shrink-0 !rounded-xl !bg-hg-gold/15 !text-hg-gold"><KeyRound size={18} aria-hidden /></span>
          <h1 className="font-display text-xl font-semibold text-ink">Choose a new password</h1>
        </div>
        <p className="text-sm text-muted2">HOME GENIES reset your password. Enter the temporary password you were given, then choose your own new password to continue.</p>
        <label className="block text-sm text-ink">Temporary password
          <Input type="password" autoComplete="current-password" value={f.current} onChange={(e) => setF({ ...f, current: e.target.value })} className="mt-1.5" data-testid="fpc-current" />
        </label>
        <label className="block text-sm text-ink">New password
          <Input type="password" autoComplete="new-password" value={f.next} onChange={(e) => setF({ ...f, next: e.target.value })} className="mt-1.5" data-testid="fpc-new" />
          <span className="mt-1 block text-xs text-muted2">{isAdmin ? "Admin accounts: 14+ characters with upper and lower case, a digit and a symbol." : "At least 8 characters with letters and numbers."}</span>
        </label>
        <label className="block text-sm text-ink">Confirm new password
          <Input type="password" autoComplete="new-password" value={f.confirm} onChange={(e) => setF({ ...f, confirm: e.target.value })} className="mt-1.5" data-testid="fpc-confirm" />
          {f.confirm && f.confirm !== f.next ? <span className="mt-1 block text-xs text-danger">The passwords do not match.</span> : null}
        </label>
        {needOtp && (
          <div className="space-y-2 rounded-2xl p-3 ring-1 ring-hg-gold/30" data-testid="fpc-otp-block">
            <p className="text-xs text-muted2">For your security we also need a code sent to your registered mobile number.</p>
            <div className="flex flex-wrap items-center gap-2">
              <Input value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, "").slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" className="h-10 w-36" data-testid="fpc-otp" />
              <Button type="button" variant="outline" onClick={sendCode} disabled={busy} className="h-10 rounded-full px-4" data-testid="fpc-send-code">{codeSent ? "Send again" : "Send code"}</Button>
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <Button type="button" variant="outline" onClick={logout} className="h-11 rounded-full px-5" data-testid="fpc-logout"><LogOut size={15} className="mr-1.5" aria-hidden /> Sign out</Button>
          <Button type="submit" disabled={!ok || busy} className="hg-btn h-11 rounded-full px-6" data-testid="fpc-submit">{busy ? "Saving…" : "Save new password"}</Button>
        </div>
      </form>
    </div>
  );
}
