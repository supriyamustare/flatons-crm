import { Building2, Contact, LayoutDashboard, UserRound, Users, type LucideIcon, CalendarCheck } from "lucide-react";
import type { Role } from "./types";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Roles that can see this item. Omit for everyone. */
  roles?: Role[];
  /** Shown in the mobile bottom bar (desktop sidebar shows all). */
  mobile?: boolean;
}

// New modules (Leads, Follow-ups, …) are added here as each sprint ships.
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, mobile: true },
  { to: "/leads", label: "Leads", icon: Contact, mobile: true },
  { to: "/follow-ups", label: "Follow-ups", icon: CalendarCheck, roles: ["admin", "manager", "executive"], mobile: true },
  { to: "/projects", label: "Projects", icon: Building2, roles: ["admin"] },
  { to: "/users", label: "Users", icon: Users, roles: ["admin"], mobile: true },
  { to: "/account", label: "My account", icon: UserRound, mobile: true },
];

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(role));
}
