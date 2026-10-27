import type { UserBrief } from "./types";

export type VisitStatus = "scheduled" | "completed" | "no_show" | "cancelled";
export type VisitSource = "sales_follow_up" | "walk_in" | "channel_partner" | "referral" | "event" | "other";
export type InterestLevel = "hot" | "warm" | "cold";
export type VisitView = "upcoming" | "completed" | "missed";

export interface Visit {
  id: number;
  lead: { id: number; lead_code: string; name: string; mobile: string };
  project: { id: number; name: string };
  host: UserBrief | null;
  visit_source: VisitSource;
  scheduled_at: string;
  status: VisitStatus;
  needs_update: boolean;
  notes: string | null;
  reschedule_count: number;
  feedback: string | null;
  interest_level: InterestLevel | null;
  next_action: string | null;
  closed_at: string | null;
  cancellation_reason: string | null;
  created_at: string;
}

export interface VisitPage {
  items: Visit[];
  total: number;
  page: number;
  page_size: number;
  counts: { upcoming: number; needs_update: number };
}

export const VISIT_SOURCES: VisitSource[] = ["sales_follow_up", "walk_in", "channel_partner", "referral", "event", "other"];

export const VISIT_SOURCE_LABELS: Record<VisitSource, string> = {
  sales_follow_up: "Sales follow-up",
  walk_in: "Walk-in",
  channel_partner: "Channel partner",
  referral: "Referral",
  event: "Event or expo",
  other: "Other",
};

export const VISIT_STATUS_LABELS: Record<VisitStatus, string> = {
  scheduled: "Scheduled",
  completed: "Completed",
  no_show: "No-show",
  cancelled: "Cancelled",
};

export const INTEREST_LABELS: Record<InterestLevel, string> = {
  hot: "Hot: ready to move",
  warm: "Warm: interested, needs time",
  cold: "Cold: not convinced",
};

/** True once the visit day has arrived (outcomes can be recorded from then). */
export function visitDayReached(iso: string, now = new Date()): boolean {
  const d = new Date(iso);
  const endOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  return d < endOfToday;
}
