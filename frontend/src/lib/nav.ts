import {
  BadgeIndianRupee, BarChart3, Building2, CalendarCheck, ClipboardCheck, Columns3, Contact, Handshake, Inbox, LayoutDashboard, MapPin, Megaphone, Phone, PlugZap, UserRound, Users, type LucideIcon,
} from "lucide-react";
import type { Role } from "./types";
import { LEAD_READERS, POSTSALES_ROLES } from "./types";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  /** Roles that can see this item. Omit for everyone. */
  roles?: Role[];
  /** In the phone bottom bar. Everything else goes under "More" on phones. */
  /** In the phone's bottom bar: for everyone (true) or only for these roles. */
  mobile?: boolean | Role[];
  /** Shows a live count next to the item. */
  badge?: "inbox";
}

const SALES: Role[] = ["admin", "manager", "executive"];

// New modules are added here as each sprint ships.
export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, mobile: true },
  { to: "/post-sales", label: "Post-sales", icon: ClipboardCheck, roles: POSTSALES_ROLES, mobile: POSTSALES_ROLES.filter((r) => r !== "admin") },
  { to: "/leads", label: "Leads", icon: Contact, roles: LEAD_READERS, mobile: true },
  { to: "/inbox", label: "Enquiries", icon: Inbox, roles: ["admin", "manager"], mobile: true, badge: "inbox" },
  { to: "/follow-ups", label: "Follow-ups", icon: CalendarCheck, roles: SALES, mobile: true },
  { to: "/pipeline", label: "Pipeline", icon: Columns3, roles: SALES },
  { to: "/bookings", label: "Bookings", icon: BadgeIndianRupee },
  { to: "/channel-partners", label: "Channel partners", icon: Handshake, roles: SALES },
  { to: "/visits", label: "Site visits", icon: MapPin, roles: SALES, mobile: true },
  { to: "/calls", label: "Calls", icon: Phone, roles: SALES },
  { to: "/reports", label: "Reports", icon: BarChart3, roles: SALES },
  { to: "/marketing", label: "Marketing", icon: Megaphone, roles: ["admin", "manager"] },
  { to: "/projects", label: "Projects", icon: Building2 },
  { to: "/connections", label: "Connections", icon: PlugZap, roles: ["admin"] },
  { to: "/users", label: "Users", icon: Users, roles: ["admin"] },
  { to: "/account", label: "My account", icon: UserRound },
];

export function navFor(role: Role): NavItem[] {
  return NAV_ITEMS.filter((item) => !item.roles || item.roles.includes(role));
}

/** Phone bottom bar: the main items, with the rest grouped under "More". */
export function mobileNavFor(role: Role): { bar: NavItem[]; more: NavItem[] } {
  const items = navFor(role);
  const inBar = (i: NavItem) => i.mobile === true || (Array.isArray(i.mobile) && i.mobile.includes(role));
  return { bar: items.filter(inBar), more: items.filter((i) => !inBar(i)) };
}
