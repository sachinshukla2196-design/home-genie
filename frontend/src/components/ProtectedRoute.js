import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

function FullLoader() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-5 bg-background" role="status" aria-label="Loading">
      <div className="relative">
        <span className="hg-logo-glow absolute inset-0 rounded-full bg-hg-violet/40 blur-2xl" />
        <img src="/brand/logo-icon.png" alt="" className="hg-float relative h-20 w-20 rounded-3xl ring-1 ring-white/15" />
      </div>
      <span className="h-1 w-24 overflow-hidden rounded-full bg-white/10"><span className="hg-progress block h-full w-1/2 animate-[hg-glint_1.2s_ease-in-out_infinite] rounded-full" /></span>
    </div>
  );
}

export function ProtectedRoute({ children, admin = false, vendor = false }) {
  const { user, ready } = useAuth();
  if (!ready) return <FullLoader />;
  if (!user) return <Navigate to="/login" replace />;
  const adminRoles = ["super_admin", "admin", "accounts_admin", "support_admin"];
  if (admin && !adminRoles.includes(user.role)) return <Navigate to="/app/dashboard" replace />;
  if (vendor && user.role !== "vendor") return <Navigate to={adminRoles.includes(user.role) ? "/admin" : "/app/dashboard"} replace />;
  return children;
}
