import React, { useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Logo } from "@/components/Logo";
import { useAuth } from "@/context/AuthContext";
import { API, apiError } from "@/lib/api";

const ADMIN_ROLES = ["super_admin", "admin", "accounts_admin", "support_admin"];

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
        navigate(ADMIN_ROLES.includes(data.user.role) ? "/admin" : "/app/dashboard", { replace: true });
      } catch (err) {
        toast.error(apiError(err, "Google sign-in failed."));
        navigate("/login", { replace: true });
      }
    })();
  }, [location.hash, navigate, applyAuth]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background" data-testid="google-auth-callback">
      <div className="animate-pulse"><Logo size="lg" /></div>
    </div>
  );
}
