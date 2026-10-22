import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import { toast } from "sonner";
import { ShieldCheck, Lock, Eye, EyeOff } from "lucide-react";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Stagger, StaggerItem } from "@/components/motion";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

function SecretField({ label, value, onChange, testid, placeholder }) {
  const [show, setShow] = useState(false);
  return (
    <div>
      <Label className="text-sm text-white/80">{label}</Label>
      <div className="relative mt-1.5">
        <Input
          type={show ? "text" : "password"}
          required
          value={value}
          onChange={onChange}
          placeholder={placeholder}
          className="h-12 rounded-2xl border-white/20 bg-white/[0.08] pr-12 text-white placeholder:text-white/45 focus-visible:ring-hg-lavender"
          data-testid={testid}
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          aria-label={show ? "Hide" : "Show"}
          className="absolute inset-y-0 right-0 flex w-12 items-center justify-center text-white/60 transition-colors hover:text-white"
          data-testid={`${testid}-toggle`}
        >
          <AnimatePresence mode="wait" initial={false}>
            <motion.span key={show ? "off" : "on"} className="block" initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.5, opacity: 0 }} transition={{ duration: 0.15 }}>
              {show ? <EyeOff size={18} /> : <Eye size={18} />}
            </motion.span>
          </AnimatePresence>
        </button>
      </div>
    </div>
  );
}

export default function AdminSecureLogin() {
  const { applyAuth } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await API.post("/auth/admin-login", { username, password });
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
    <div className="hg-royal relative isolate flex min-h-screen items-center justify-center overflow-hidden px-4 py-10" data-testid="admin-secure-login">
      <span aria-hidden="true" className="pointer-events-none absolute -left-24 top-10 -z-10 h-80 w-80 rounded-full bg-hg-violet/35 blur-3xl" />
      <span aria-hidden="true" className="pointer-events-none absolute -bottom-24 -right-16 -z-10 h-80 w-80 rounded-full bg-hg-pink/20 blur-3xl" />
      <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        className="relative w-full max-w-md rounded-[1.75rem] border border-white/15 bg-white/[0.06] p-5 text-white shadow-[0_24px_60px_-20px_rgba(0,0,0,0.6),0_0_80px_-30px_rgba(139,61,255,0.7)] backdrop-blur-xl sm:p-8">
        <Stagger>
          <StaggerItem className="flex items-center justify-between gap-3">
            <Logo size="sm" dark />
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-hg-lavender/15 px-2.5 py-1 text-[11px] font-semibold text-hg-lavender ring-1 ring-hg-lavender/30">
              <ShieldCheck size={12} /> Restricted
            </span>
          </StaggerItem>
          <StaggerItem className="mt-8 flex items-center gap-3">
            <motion.div initial={{ scale: 0.6, rotate: -12 }} animate={{ scale: 1, rotate: 0 }} transition={{ type: "spring", stiffness: 300, damping: 16, delay: 0.15 }}
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-hg-violet/30 text-hg-lavender ring-1 ring-hg-lavender/30"><Lock size={20} /></motion.div>
            <div className="min-w-0">
              <h1 className="font-display text-2xl font-semibold">Admin Control Panel</h1>
              <p className="text-sm text-white/65">Authorized personnel only</p>
            </div>
          </StaggerItem>
          <StaggerItem>
            <form onSubmit={submit} className="mt-8 space-y-4">
              <div>
                <Label className="text-sm text-white/80">Admin Username</Label>
                <Input type="text" required value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin username" className="mt-1.5 h-12 rounded-2xl border-white/20 bg-white/[0.08] text-white placeholder:text-white/45 focus-visible:ring-hg-lavender" data-testid="admin-email" />
              </div>
              <SecretField label="Password" value={password} onChange={(e) => setPassword(e.target.value)} testid="admin-password" placeholder="Your password" />
              <Button type="submit" disabled={loading} className="hg-btn h-12 w-full rounded-2xl text-base font-semibold shadow-[0_12px_28px_-12px_rgba(168,85,247,0.8)] transition-transform hover:-translate-y-0.5 active:scale-[0.98]" data-testid="admin-login-submit">
                {loading ? <span className="inline-flex items-center gap-2"><span className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />Verifying…</span> : "Unlock Admin Panel"}
              </Button>
            </form>
          </StaggerItem>
          <StaggerItem as="p" className="mt-6 text-center text-xs leading-relaxed text-white/50">This is a secured endpoint. All access attempts are logged and audited.</StaggerItem>
        </Stagger>
      </motion.div>
    </div>
  );
}
