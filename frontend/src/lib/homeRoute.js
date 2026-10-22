const ADMIN_ROLES = ["super_admin", "admin", "accounts_admin", "support_admin"];

/** Landing page for a signed-in user, by role. */
export function homeRouteFor(user) {
  if (!user) return "/login";
  if (ADMIN_ROLES.includes(user.role)) return "/admin";
  if (user.role === "vendor") return "/vendor";
  return "/app/dashboard";
}
