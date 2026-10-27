import {
  BarChart3, Building2, CalendarCheck, Columns3, Contact, LayoutDashboard, MapPin, Megaphone, Phone, UserRound, Users,
  type LucideIcon,
} from "lucide-react";
import type { Role } from "./types";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Roles that can see this item. Omit for everyone. */
  roles?: Role[];
  /** In the phone bottom bar. Everything else goes under "More" on phones. */
  mobile?: boolean;
}

const SALES: Role[] = ["admin", "manager", "executive"];

// New modules are added here as each sprint ships.
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, mobile: true },
  { to: "/leads", label: "Leads", icon: Contact, mobile: true },
  { to: "/follow-ups", label: "Follow-ups", icon: CalendarCheck, roles: SALES, mobile: true },
  { to: "/pipeline", label: "Pipeline", icon: Columns3, roles: SALES },
  { to: "/visits", label: "Site visits", icon: MapPin, roles: SALES, mobile: true },
  { to: "/calls", label: "Calls", icon: Phone, roles: SALES },
  { to: "/reports", label: "Reports", icon: BarChart3, roles: SALES },
  { to: "/marketing", label: "Marketing", icon: Megaphone, roles: ["admin", "manager"] },
  { to: "/projects", label: "Projects", icon: Building2 },
  { to: "/users", label: "Users", icon: Users, roles: ["admin"] },
  { to: "/account", label: "My account", icon: UserRound },
];

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(role));
}

/** Phone bottom bar: the main items, with the rest grouped under "More". */
export function mobileNavFor(role: Role): { bar: NavItem[]; more: NavItem[] } {
  const items = navFor(role);
  return { bar: items.filter((i) => i.mobile), more: items.filter((i) => !i.mobile) };
}
