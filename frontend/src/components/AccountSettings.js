import React, { useState } from "react";
import { toast } from "sonner";
import { KeyRound, UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SectionCard } from "@/components/PageHeader";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

/** Batch 8: a member's or customer's own profile details (PUT /auth/profile) and password (PUT /auth/change-password).
 *  Mobile and email are changed only through their verified flows, never from here. */
export function AccountSettings() {
  const { user, refresh } = useAuth();
  const [p, setP] = useState({ full_name: user?.full_name || "", address: user?.address || "", city: user?.city || "",
                               state: user?.state || "", pincode: user?.pincode || "" });
  const [pw, setPw] = useState({ current: "", next: "", confirm: "" });
  const [busy, setBusy] = useState("");
  const saveProfile = async (e) => {
    e.preventDefault();
    if (p.pincode && !/^\d{6}$/.test(p.pincode)) { toast.error("Pincode must be 6 digits."); return; }
    setBusy("profile");
    try { await API.put("/auth/profile", p); toast.success("Profile saved"); await refresh(); }
    catch (err) { toast.error(apiError(err)); } finally { setBusy(""); }
  };
  const pwOk = pw.current && pw.next.length >= 8 && /[A-Za-z]/.test(pw.next) && /\d/.test(pw.next) && pw.next === pw.confirm && pw.next !== pw.current;
  const changePw = async (e) => {
    e.preventDefault();
    if (!pwOk) return;
    setBusy("pw");
    try {
      const { data } = await API.put("/auth/change-password", { current_password: pw.current, new_password: pw.next });
      if (data.token) localStorage.setItem("anj_token", data.token);         // this session stays; every other one is signed out
      setPw({ current: "", next: "", confirm: "" });
      toast.success("Password changed. Other devices were signed out.");
    } catch (err) { toast.error(apiError(err)); } finally { setBusy(""); }
  };
  const f = (k, label, extra = {}) => (
    <label className="block text-sm text-ink">{label}
      <Input value={p[k]} onChange={(e) => setP((x) => ({ ...x, [k]: e.target.value }))} className="mt-1.5" data-testid={`acct-${k}`} {...extra} />
    </label>
  );
  return (
    <>
      <SectionCard title="Your details" icon={UserRound} testid="account-details">
        <form onSubmit={saveProfile} className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">{f("full_name", "Full name")}</div>
          <div className="sm:col-span-2">{f("address", "Address")}</div>
          {f("city", "City")}{f("state", "State")}{f("pincode", "Pincode", { inputMode: "numeric", maxLength: 6 })}
          <div className="sm:col-span-2 flex flex-wrap items-center gap-3">
            <Button type="submit" disabled={busy === "profile" || p.full_name.trim().length < 2} className="hg-btn h-11 rounded-full px-6" data-testid="acct-save">{busy === "profile" ? "Saving…" : "Save details"}</Button>
            <span className="text-xs text-muted2">Mobile {user?.mobile ? `XXXXXX${String(user.mobile).slice(-4)}` : ""} and email are changed through their own verification.</span>
          </div>
        </form>
      </SectionCard>
      <SectionCard title="Password" icon={KeyRound} testid="account-password">
        <form onSubmit={changePw} className="grid gap-4 sm:grid-cols-3" autoComplete="off">
          <label className="block text-sm text-ink">Current password<Input type="password" autoComplete="current-password" value={pw.current} onChange={(e) => setPw((x) => ({ ...x, current: e.target.value }))} className="mt-1.5" data-testid="acct-pw-current" /></label>
          <label className="block text-sm text-ink">New password<Input type="password" autoComplete="new-password" value={pw.next} onChange={(e) => setPw((x) => ({ ...x, next: e.target.value }))} className="mt-1.5" data-testid="acct-pw-new" /></label>
          <label className="block text-sm text-ink">Confirm<Input type="password" autoComplete="new-password" value={pw.confirm} onChange={(e) => setPw((x) => ({ ...x, confirm: e.target.value }))} className="mt-1.5" data-testid="acct-pw-confirm" /></label>
          <div className="sm:col-span-3"><Button type="submit" disabled={!pwOk || busy === "pw"} className="hg-btn h-11 rounded-full px-6" data-testid="acct-pw-save">{busy === "pw" ? "Saving…" : "Change password"}</Button>
            <p className="mt-1.5 text-xs text-muted2">At least 8 characters with letters and numbers.</p></div>
        </form>
      </SectionCard>
    </>
  );
}
