import type { UserBrief } from "./types";

export type LeadStatus =
  | "new" | "not_reachable" | "contacted" | "qualified" | "follow_up" | "visit_scheduled"
  | "visit_done" | "revisit" | "negotiation" | "on_hold" | "booked" | "lost" | "junk";
export type LeadSource =
  | "website" | "99acres" | "magicbricks" | "housing" | "social" | "google_ads"
  | "walk_in" | "referral" | "channel_partner" | "print" | "other";
export type Configuration = "1bhk" | "2bhk" | "3bhk" | "4bhk" | "studio" | "shop" | "office" | "plot";
export type Purpose = "self_use" | "investment";
export type Timeline = "immediate" | "within_3_months" | "within_6_months" | "beyond_6_months";

export interface ProjectBrief { id: number; name: string }
export interface Project extends ProjectBrief { is_active: boolean }

export interface Lead {
  id: number;
  lead_code: string;
  name: string;
  mobile: string;
  alt_mobile: string | null;
  email: string | null;
  city: string | null;
  source: LeadSource;
  sub_source: string | null;
  project: ProjectBrief | null;
  campaign?: ProjectBrief | null;
  configuration: Configuration | null;
  budget_min: number | null;
  budget_max: number | null;
  purpose: Purpose | null;
  timeline: Timeline | null;
  assigned_to: UserBrief | null;
  status: LeadStatus;
  lost_reason: string | null;
  estimated_value: number | null;
  remarks: string | null;
  created_by: UserBrief | null;
  last_activity_at: string;
  created_at: string;
  updated_at: string;
}

export interface Activity {
  id: number;
  type: string;
  note: string | null;
  details: Record<string, unknown> | null;
  actor: UserBrief | null;
  created_at: string;
}

export interface LeadDetail extends Lead {
  activities: Activity[];
  can_edit: boolean;
}

export interface Duplicate {
  id: number;
  lead_code: string;
  name: string;
  status: LeadStatus;
  assigned_to_name: string | null;
  matched_on: ("mobile" | "email")[];
  can_view: boolean;
}

export interface LeadFilters {
  q?: string;
  statuses: LeadStatus[];
  sources: LeadSource[];
  project_id: number | null;
  assigned_to_id: number | null;
  unassigned: boolean;
  created_from: string | null;
  created_to: string | null;
}

export const EMPTY_FILTERS: LeadFilters = {
  statuses: [], sources: [], project_id: null, assigned_to_id: null,
  unassigned: false, created_from: null, created_to: null,
};

export const STATUS_LABELS: Record<LeadStatus, string> = {
  new: "New",
  not_reachable: "Not reachable",
  contacted: "Contacted",
  qualified: "Qualified",
  follow_up: "Follow-up",
  visit_scheduled: "Visit scheduled",
  visit_done: "Visit done",
  revisit: "Revisit",
  negotiation: "Negotiation",
  on_hold: "On hold",
  booked: "Booked",
  lost: "Lost",
  junk: "Junk",
};
export const STATUSES = Object.keys(STATUS_LABELS) as LeadStatus[];
export const REASON_REQUIRED: LeadStatus[] = ["lost", "junk"];
export const MANAGER_ONLY: LeadStatus[] = ["booked"];

export const SOURCE_LABELS: Record<LeadSource, string> = {
  website: "Website",
  "99acres": "99acres",
  magicbricks: "MagicBricks",
  housing: "Housing.com",
  social: "Facebook / Instagram",
  google_ads: "Google Ads",
  walk_in: "Walk-in",
  referral: "Referral",
  channel_partner: "Channel partner",
  print: "Hoarding / print",
  other: "Other",
};
export const SOURCES = Object.keys(SOURCE_LABELS) as LeadSource[];

export const CONFIG_LABELS: Record<Configuration, string> = {
  "1bhk": "1 BHK", "2bhk": "2 BHK", "3bhk": "3 BHK", "4bhk": "4 BHK",
  studio: "Studio", shop: "Shop", office: "Office", plot: "Plot",
};
export const PURPOSE_LABELS: Record<Purpose, string> = { self_use: "Self use", investment: "Investment" };
export const TIMELINE_LABELS: Record<Timeline, string> = {
  immediate: "Immediately",
  within_3_months: "Within 3 months",
  within_6_months: "Within 6 months",
  beyond_6_months: "After 6 months",
};

export const FIELD_LABELS: Record<string, string> = {
  name: "name", mobile: "mobile", alt_mobile: "alternate mobile", email: "email", city: "city",
  source: "source", sub_source: "sub-source", project_id: "project", configuration: "configuration",
  budget_min: "minimum budget", budget_max: "maximum budget", purpose: "purpose",
  timeline: "buying timeline", estimated_value: "estimated value", remarks: "remarks",
};

/** Badge colour by stage: gold for new, green while active, grey when parked or closed. */
export function statusTone(s: LeadStatus): "gold" | "neutral" | "muted" | "solid" | "danger" {
  if (s === "new") return "gold";
  if (s === "booked") return "solid";
  if (s === "lost" || s === "junk") return "danger";
  if (s === "on_hold" || s === "not_reachable") return "muted";
  return "neutral";
}

/** ₹45 L, ₹1.25 Cr — how budgets are spoken about in Indian real estate. */
export function formatRupees(n: number | null): string {
  if (n === null) return "—";
  if (n >= 1_00_00_000) return `₹${trim(n / 1_00_00_000)} Cr`;
  if (n >= 1_00_000) return `₹${trim(n / 1_00_000)} L`;
  return `₹${n.toLocaleString("en-IN")}`;
}
const trim = (v: number) => String(Math.round(v * 100) / 100);

export function formatBudget(min: number | null, max: number | null): string {
  if (min === null && max === null) return "—";
  if (min !== null && max !== null) return `${formatRupees(min)} – ${formatRupees(max)}`;
  return min !== null ? `From ${formatRupees(min)}` : `Up to ${formatRupees(max)}`;
}

/** +919876543210 → +91 98765 43210 */
export function formatMobile(m: string | null): string {
  if (!m) return "—";
  const match = /^\+91(\d{5})(\d{5})$/.exec(m);
  return match ? `+91 ${match[1]} ${match[2]}` : m;
}

/** Lakh amounts typed in forms ↔ rupees stored by the API. */
export const lakhToRupees = (v: string): number | null =>
  v.trim() === "" ? null : Math.round(Number(v) * 1_00_000);
export const rupeesToLakh = (v: number | null): string => (v === null ? "" : trim(v / 1_00_000));

export function countActiveFilters(f: LeadFilters): number {
  return (
    (f.statuses.length ? 1 : 0) + (f.sources.length ? 1 : 0) + (f.project_id ? 1 : 0) +
    (f.assigned_to_id || f.unassigned ? 1 : 0) + (f.created_from || f.created_to ? 1 : 0)
  );
}
