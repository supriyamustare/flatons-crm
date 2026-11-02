import type { LeadStatus } from "./leads";
import type { UserBrief } from "./types";

export interface PipelineCard {
  id: number;
  lead_code: string;
  name: string;
  status: LeadStatus;
  project: { id: number; name: string } | null;
  budget_min: number | null;
  budget_max: number | null;
  deal_value: number | null;
  assigned_to: UserBrief | null;
  days_in_stage: number;
  stale: boolean;
  last_activity_at: string;
}

export interface StageColumn {
  stage: LeadStatus;
  probability_pct: number;
  count: number;
  value: number;
  weighted_value: number;
  stale_count: number;
  missing_value_count: number;
  cards: PipelineCard[];
  has_more: boolean;
}

export interface PipelineBoard {
  stale_after_days: number;
  stages: StageColumn[];
  totals: {
    open_count: number; open_value: number; weighted_value: number;
    booked_count: number; booked_value: number; stale_count: number; missing_value_count: number;
  };
}

export interface ForecastRow { count: number; value: number; weighted_value: number }
export interface Forecast {
  by_project: (ForecastRow & { project: { id: number; name: string } | null })[];
  by_executive: (ForecastRow & { user: UserBrief | null })[];
  total: ForecastRow;
}

export interface StageProbability { stage: LeadStatus; probability_pct: number }

/** Stages whose probability is fixed by definition. */
export const FIXED_PROBABILITY: Partial<Record<LeadStatus, number>> = { booked: 100, lost: 0, junk: 0 };
/** Moving into these needs a reason. */
export const NEEDS_REASON: LeadStatus[] = ["lost", "junk"];

export function daysInStageLabel(days: number): string {
  if (days === 0) return "Today";
  return days === 1 ? "1 day" : `${days} days`;
}
