export type Role =
  | "admin" | "manager" | "executive" | "docs"
  | "postsales_exec" | "crm_manager" | "finance" | "finance_approver" | "legal" | "project_manager"
  | "site" | "service" | "after_sales" | "management" | "auditor";

/** Roles that work in pre-sales (leads); post-sales roles never see leads. */
export const LEAD_READERS: Role[] = ["admin", "manager", "executive", "docs"];
/** Roles that work on post-sales cases. */
export const POSTSALES_ROLES: Role[] = ["admin", "crm_manager", "postsales_exec", "finance", "finance_approver", "legal",
  "project_manager", "site", "service", "after_sales", "management", "auditor"];
export const CASE_EDITORS: Role[] = ["admin", "crm_manager", "postsales_exec"];
export const KYC_VIEWERS: Role[] = ["admin", "crm_manager", "postsales_exec", "legal", "auditor"];
export const isPostSalesOnly = (r: Role) => POSTSALES_ROLES.includes(r) && r !== "admin";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface UserBrief {
  id: number;
  full_name: string;
  role: Role;
}

export const ROLES: Role[] = ["admin", "manager", "executive", "docs"];

export const ROLE_LABELS: Record<Role, string> = {
  admin: "Admin",
  manager: "Manager",
  executive: "Sales executive",
  docs: "Documents",
  postsales_exec: "Post-sales executive",
  crm_manager: "CRM manager",
  finance: "Finance executive",
  finance_approver: "Finance approver",
  legal: "Legal executive",
  project_manager: "Project manager",
  site: "Site / possession team",
  service: "Customer service",
  after_sales: "After-sales",
  management: "Management",
  auditor: "Auditor",
};

export const ROLE_DESCRIPTIONS: Record<Role, string> = {
  admin: "Full access, including users and settings",
  manager: "Oversees leads, pipeline and the sales team",
  executive: "Works their own leads, calls and site visits",
  docs: "Prepares welcome letters and payment demands",
  postsales_exec: "Handover, customer details, KYC and document follow-up",
  crm_manager: "Allocates and supervises post-sales work and escalations",
  finance: "Receipts and ledger reconciliation",
  finance_approver: "Approves financial adjustments, waivers and refunds",
  legal: "Agreements, legal review and registration",
  project_manager: "Construction milestones and readiness",
  site: "Inspections, snagging and handover",
  service: "Customer service desk",
  after_sales: "Defects and warranties",
  management: "Dashboards and reports",
  auditor: "Read-only access to records",
};
