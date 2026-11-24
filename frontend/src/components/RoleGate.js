import React from "react";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { can, rolesText } from "@/lib/roles";

/**
 * Programme 02 / W7: renders its children only for the roles the server allows (lib/roles.js). For any other role it shows a short
 * note instead and does NOT mount the page, so no request is made that the server would refuse. The server remains the authority.
 * (Owner decision P1-08 may choose to hide such entries instead of explaining them; this keeps today's visibility.)
 */
export function RoleGate({ set, what, children, testid = "role-gate" }) {
  const { user } = useAuth();
  if (can(user, set)) return children;
  return <RoleNote set={set} what={what} testid={testid} />;
}

export function RoleNote({ set, what, testid = "role-note" }) {
  return (
    <div role="note" className="hg-card flex items-start gap-3 p-5 text-sm text-ink" data-testid={testid}>
      <ShieldCheck size={18} className="mt-0.5 shrink-0 text-hg-gold" aria-hidden />
      <p>{what ? `${what} is` : "This section is"} available to the {rolesText(set)} only. Your role can see the rest of the admin panel.</p>
    </div>
  );
}
