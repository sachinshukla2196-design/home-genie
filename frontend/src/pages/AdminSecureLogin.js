import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { ShieldCheck, Lock } from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

export default function AdminSecureLogin() {
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passcode, setPasscode] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await API.post("/auth/admin-login", { email, password, passcode });
      applyAuth(data);
      toast.success("Admin access granted");
      navigate("/admin");
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-forest px-4" data-testid="admin-secure-login">
      <div className="pointer-events-none absolute inset-0 opacity-20" style={{ backgroundImage: "radial-gradient(circle at 20% 20%, rgba(201,162,39,0.4), transparent 40%), radial-gradient(circle at 80% 80%, rgba(23,107,67,0.5), transparent 45%)" }} />
      <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} className="relative w-full max-w-md rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur-xl">
        <div className="flex items-center justify-between">
          <Logo size="sm" dark />
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gold/20 px-2.5 py-1 text-[11px] font-semibold text-gold">
            <ShieldCheck size={12} /> Restricted
          </span>
        </div>
        <div className="mt-8 flex items-center gap-3 text-white">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gold/20 text-gold"><Lock size={20} /></div>
          <div>
            <h1 className="font-display text-2xl font-semibold">Admin Control Panel</h1>
            <p className="text-sm text-white/60">Authorized personnel only</p>
          </div>
        </div>
        <form onSubmit={submit} className="mt-8 space-y-4">
          <div>
            <Label className="text-sm text-white/80">Admin Email</Label>
            <Input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className="mt-1.5 h-11 rounded-lg border-white/25 bg-white/[0.14] text-white placeholder:text-white/50 focus-visible:ring-gold" data-testid="admin-email" />
          </div>
          <div>
            <Label className="text-sm text-white/80">Password</Label>
            <Input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className="mt-1.5 h-11 rounded-lg border-white/25 bg-white/[0.14] text-white placeholder:text-white/50 focus-visible:ring-gold" data-testid="admin-password" />
          </div>
          <div>
            <Label className="text-sm text-white/80">Admin Passcode</Label>
            <Input type="password" required value={passcode} onChange={(e) => setPasscode(e.target.value)} placeholder="Secret passcode" className="mt-1.5 h-11 rounded-lg border-white/25 bg-white/[0.14] text-white placeholder:text-white/50 focus-visible:ring-gold" data-testid="admin-passcode" />
          </div>
          <Button type="submit" disabled={loading} className="h-11 w-full rounded-full btn-gold" data-testid="admin-login-submit">
            {loading ? "Verifying…" : "Unlock Admin Panel"}
          </Button>
        </form>
        <p className="mt-6 text-center text-xs text-white/40">This is a secured endpoint. All access attempts are logged and audited.</p>
      </motion.div>
    </div>
  );
}
