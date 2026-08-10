import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { Logo } from "@/components/Logo";

function FullLoader() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <div className="animate-pulse"><Logo size="lg" /></div>
    </div>
  );
}

export function ProtectedRoute({ children, admin = false }) {
  const { user, ready } = useAuth();
  if (!ready) return <FullLoader />;
  if (!user) return <Navigate to="/login" replace />;
  const adminRoles = ["super_admin", "admin", "accounts_admin", "support_admin"];
  if (admin && !adminRoles.includes(user.role)) return <Navigate to="/app/dashboard" replace />;
  return children;
}
