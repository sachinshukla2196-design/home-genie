import React from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";

/** HomeGenie-only screens (rewards, points wallet, withdrawals, KYC, sharing). A CUSTOMER account has none of these
 *  (owner decision 5); the server refuses them too, this only keeps customers out of screens that cannot work for them. */
export default function MemberOnly({ children }) {
  const { user } = useAuth();
  if (user?.role === "customer") return <Navigate to="/app/dashboard" replace />;
  return children;
}
