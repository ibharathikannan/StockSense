import { LayoutDashboard, ShieldCheck, UserCircle, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Item is hidden unless the user holds this permission. Omit for "any signed-in user". */
  permission?: string;
}

// Add a line here when you add a module (and a permission in backend/app/core/permissions.py).
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard },
  { label: "Users", href: "/users", icon: Users, permission: "users:read" },
  { label: "Roles", href: "/roles", icon: ShieldCheck, permission: "roles:read" },
  { label: "My profile", href: "/profile", icon: UserCircle },
];
