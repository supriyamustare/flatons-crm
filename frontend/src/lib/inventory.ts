import type { UserBrief } from "./types";

export type ProjectType = "developer" | "resale";
export type ProjectStatus = "pre_launch" | "under_construction" | "ready_to_move" | "sold_out";
export type UnitType = "1bhk" | "2bhk" | "3bhk" | "4bhk" | "studio" | "shop" | "office";
export type UnitStatus = "available" | "on_hold" | "booked" | "sold" | "withdrawn";

export interface Developer { id: number; name: string }

export interface UnitCounts {
  total: number; available: number; on_hold: number; booked: number; sold: number; withdrawn: number;
}

export interface ProjectFull {
  id: number;
  name: string;
  is_active: boolean;
  project_type: ProjectType;
  status: ProjectStatus;
  developer: Developer | null;
  location: string | null;
  description: string | null;
  commission_pct: string | null;
  created_at: string;
  units?: UnitCounts;
}

export interface Unit {
  id: number;
  project_id: number;
  building_id: number | null;
  floor_id: number | null;
  floor_number: number | null;
  unit_no: string;
  unit_type: UnitType;
  carpet_sqft: string | null;
  builtup_sqft: string | null;
  base_price: number | null;
  current_asking_price: number | null;
  address_note: string | null;
  status: UnitStatus;
  hold_expired: boolean;
  held_by: UserBrief | null;
  held_for: { id: number; name: string; lead_code: string } | null;
  held_at: string | null;
  hold_expires_at: string | null;
  hold_note: string | null;
  booking_id?: number | null;
  rate_psf?: string | null;
}

export interface FloorRow { id: number; number: number; units: Unit[] }
export interface BuildingTree { id: number; name: string; sort_order: number; counts: UnitCounts; floors: FloorRow[] }
export interface Inventory { project: ProjectFull; counts: UnitCounts; buildings: BuildingTree[]; listings: Unit[] }

export const PROJECT_TYPE_LABELS: Record<ProjectType, string> = { developer: "Developer project", resale: "Resale" };
export const PROJECT_STATUS_LABELS: Record<ProjectStatus, string> = {
  pre_launch: "Pre-launch", under_construction: "Under construction", ready_to_move: "Ready to move", sold_out: "Sold out",
};
export const UNIT_TYPES: UnitType[] = ["1bhk", "2bhk", "3bhk", "4bhk", "studio", "shop", "office"];
export const UNIT_TYPE_LABELS: Record<UnitType, string> = {
  "1bhk": "1 BHK", "2bhk": "2 BHK", "3bhk": "3 BHK", "4bhk": "4 BHK", studio: "Studio", shop: "Shop", office: "Office",
};
export const UNIT_STATUSES: UnitStatus[] = ["available", "on_hold", "booked", "sold", "withdrawn"];
export const UNIT_STATUS_LABELS: Record<UnitStatus, string> = {
  available: "Available", on_hold: "On hold", booked: "Booked", sold: "Sold", withdrawn: "Withdrawn",
};

/** Grid cell styles. Colour plus a second cue (pattern, border, strike) so status never
 *  depends on colour alone. Available=green, Booked=gold, On hold=amber, Sold=grey, Withdrawn=struck. */
export const UNIT_CELL: Record<UnitStatus, string> = {
  available: "bg-emerald-100 text-emerald-950 ring-emerald-300 hover:bg-emerald-200",
  booked: "bg-gold-500 text-forest-950 ring-gold-600 font-semibold",
  on_hold: "unit-hold text-amber-950 ring-amber-400 border-dashed",
  sold: "bg-stone-300 text-stone-700 ring-stone-400",
  withdrawn: "bg-white text-muted ring-line line-through",
};

/** Short status mark shown in each cell for non-colour reading. */
export const UNIT_MARK: Record<UnitStatus, string> = {
  available: "", on_hold: "H", booked: "B", sold: "S", withdrawn: "",
};

export function floorLabel(n: number): string {
  if (n === 0) return "Ground";
  if (n < 0) return `Basement ${-n}`;
  return `Floor ${n}`;
}

export function unitSpokenLabel(u: Unit): string {
  const status = u.hold_expired ? "On hold (expired)" : UNIT_STATUS_LABELS[u.status];
  return `Unit ${u.unit_no}, ${UNIT_TYPE_LABELS[u.unit_type]}, ${status}`;
}

export function formatArea(sqft: string | null): string {
  if (!sqft) return "—";
  return `${Number(sqft).toLocaleString("en-IN")} sq ft`;
}
