import { ChartNoAxesCombined, Compass, LayoutDashboard, Settings, ShieldCheck, UserCircle, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export type NavGroup = "Research" | "Administration" | "Account";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Sidebar section the item sits under (also shown in the breadcrumb). */
  group: NavGroup;
  /** Item is hidden unless the user holds this permission. Omit for "any signed-in user". */
  permission?: string;
}

/** Sidebar section order. A section with no visible items is not rendered. */
export const NAV_GROUPS: NavGroup[] = ["Research", "Administration", "Account"];

// Add a line here when you add a module (and a permission in backend/app/core/permissions.py).
export const NAV_ITEMS: NavItem[] = [
  { label: "Dashboard", href: "/", icon: LayoutDashboard, group: "Research" },
  { label: "Discover", href: "/discover", icon: Compass, group: "Research" },
  { label: "Forecasts", href: "/forecasts", icon: ChartNoAxesCombined, group: "Research" },
  { label: "Users", href: "/users", icon: Users, group: "Administration", permission: "users:read" },
  { label: "Roles", href: "/roles", icon: ShieldCheck, group: "Administration", permission: "roles:read" },
  { label: "Profile", href: "/profile", icon: UserCircle, group: "Account" },
  { label: "Account settings", href: "/account", icon: Settings, group: "Account" },
];

/** The nav item whose page contains `pathname` (the most specific match wins), if any. */
export function navItemFor(pathname: string): NavItem | undefined {
  return NAV_ITEMS.filter((item) =>
    item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`),
  ).sort((a, b) => b.href.length - a.href.length)[0];
}
