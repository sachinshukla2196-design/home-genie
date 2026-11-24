/**
 * Programme 02 / W7: one copy, in the frontend, of the role sets the SERVER enforces, so screens neither offer an action nor fire a
 * request that the server will refuse (403). This is a convenience only: every rule is enforced by the backend, which stays the
 * authority. Each set names its backend source; change the backend first, then this file.
 */
export const ROLE_SETS = {
  finance: ["super_admin", "accounts_admin"],              // finance_routes.FINANCE_ROLES, financial_approvals.FINANCE_ROLES, payment_events.FINANCE_ROLES
  exportReports: ["super_admin", "admin", "accounts_admin"], // admin_order_ops.EXPORT_ROLES
  codConfirm: ["admin", "super_admin"],                     // cod_rules.CONFIRM_ROLES
  activationApprover: ["admin", "super_admin"],             // activation_routes.APPROVER_ROLES
  contentEditor: ["super_admin", "admin"],                  // core.require_vendor_admin (merchandising, catalogue decisions, admin product drafts)
  vendorApplications: ["super_admin", "admin", "support_admin"], // vendor_applications.VIEW_ROLES
  superAdmin: ["super_admin"],                              // admin_team.require_super_admin
};

export const ROLE_LABELS = { super_admin: "super admin", admin: "admin", accounts_admin: "accounts admin", support_admin: "support admin" };

export function can(user, set) {
  return !!user && (ROLE_SETS[set] || []).includes(user.role);
}

export function rolesText(set) {
  const r = (ROLE_SETS[set] || []).map((x) => ROLE_LABELS[x] || x);
  return r.length > 1 ? `${r.slice(0, -1).join(", ")} and ${r[r.length - 1]}` : r[0] || "";
}
