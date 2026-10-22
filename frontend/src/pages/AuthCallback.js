import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { useAuth } from "@/context/AuthContext";
import { homeRouteFor } from "@/lib/homeRoute";
import { API, apiError } from "@/lib/api";


// REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
export default function AuthCallback() {
  const location = useLocation();
  const navigate = useNavigate();
  const { applyAuth } = useAuth();
  const processed = useRef(false);

  useEffect(() => {
    if (processed.current) return;
    processed.current = true;

    const params = new URLSearchParams((location.hash || "").replace(/^#/, ""));
    const sessionId = params.get("session_id");
    // Clear the fragment so the token is not left in the URL/history.
    window.history.replaceState(null, "", window.location.pathname);

    if (!sessionId) {
      navigate("/login", { replace: true });
      return;
    }

    (async () => {
      try {
        const { data } = await API.post("/auth/google/session", { session_id: sessionId });
        if (data.mode === "register") {
          toast.message("Let's finish your registration");
          navigate("/register", { replace: true, state: { googleEmail: data.email, googleName: data.name } });
          return;
        }
        applyAuth(data);
        toast.success("Signed in with Google");
        navigate(homeRouteFor(data.user), { replace: true });
      } catch (err) {
        toast.error(apiError(err, "Google sign-in failed."));
        navigate("/login", { replace: true });
      }
    })();
  }, [location.hash, navigate, applyAuth]);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-background px-4" role="status" aria-label="Loading" data-testid="google-auth-callback">
      <motion.div initial={{ scale: 0.7, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 220, damping: 16 }} className="relative">
        <span className="hg-logo-glow absolute inset-0 rounded-full bg-hg-violet/40 blur-2xl" />
        <img src="/brand/logo-icon.png" alt="" className="hg-float relative h-24 w-24 rounded-[1.75rem] ring-1 ring-white/15" />
      </motion.div>
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.15, duration: 0.35 }} className="flex flex-col items-center gap-4">
        <Logo variant="wordmark" />
        <span className="h-1 w-28 overflow-hidden rounded-full bg-hg-violet/15"><span className="hg-progress block h-full w-1/2 animate-[hg-glint_1.2s_ease-in-out_infinite] rounded-full" /></span>
      </motion.div>
    </div>
  );
}
