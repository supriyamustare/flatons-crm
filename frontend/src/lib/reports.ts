import type { Channel } from "./marketing";
import type { UserBrief } from "./types";

export type ReportKind = "calls" | "visits" | "conversion" | "campaigns" | "staff";
export type RangeKey = "today" | "7d" | "30d" | "custom";

interface Period { date_from: string; date_to: string; scope: "team" | "mine" | "person"; definitions: Record<string, string> }

export interface CallRow { user: UserBrief | null; calls: number; connected: number; connection_rate: number | null; talk_minutes: number }
export interface CallsReport extends Period { rows: CallRow[]; totals: CallRow; by_day: { day: string; calls: number; connected: number }[] }

export interface VisitCounts { visits: number; completed: number; no_show: number; cancelled: number; scheduled: number; completion_rate: number | null }
export interface VisitsReport extends Period {
  by_project: (VisitCounts & { project: { id: number; name: string } })[];
  by_source: (VisitCounts & { source: string })[];
  by_person: (VisitCounts & { user: UserBrief | null })[];
  totals: VisitCounts;
}

export interface Funnel { leads: number; visited: number; booked: number; booked_after_visit: number; visit_rate: number | null; visit_to_booking_rate: number | null; conversion_rate: number | null }
export interface ConversionReport extends Period {
  totals: Funnel;
  by_person: (Funnel & { user: UserBrief | null })[];
  by_project: (Funnel & { project: { id: number; name: string } | null })[];
}

export interface CampaignRow { campaign_id: number | null; name: string; channel: Channel | null; spend: number; leads: number; visited: number; booked: number; cost_per_lead: number | null; cost_per_visit: number | null; cost_per_booking: number | null }
export interface CampaignsReport extends Period { rows: CampaignRow[]; totals: CampaignRow; unattributed_leads: number }

export interface StaffRow { user: UserBrief; leads: number; calls: number; connected: number; connection_rate: number | null; visits_completed: number; bookings: number; lead_to_booking_rate: number | null }
export interface StaffReport extends Period { rows: StaffRow[]; totals: StaffRow }

export interface ReportMap { calls: CallsReport; visits: VisitsReport; conversion: ConversionReport; campaigns: CampaignsReport; staff: StaffReport }

/** 0.3684 -> "37%"; null -> "N/A" (nothing to divide by). A missing rate is never shown as 0%. */
export function formatRate(r: number | null): string {
  return r === null ? "N/A" : `${Math.round(r * 100)}%`;
}

export const REPORT_LABELS: Record<ReportKind, string> = {
  calls: "Calls", visits: "Site visits", conversion: "Conversion", campaigns: "Campaigns", staff: "Staff",
};
