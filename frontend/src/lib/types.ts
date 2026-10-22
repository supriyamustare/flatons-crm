export type Role = "admin" | "manager" | "executive" | "docs";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export const ROLES: Role[] = ["admin", "manager", "executive", "docs"];

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  manager: "Manager",
  executive: "Sales executive",
  docs: "Documents",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  admin: "Full access, including users and settings",
  manager: "Oversees leads, pipeline and the sales team",
  executive: "Works their own leads, calls and site visits",
  docs: "Prepares welcome letters and payment demands",
};
