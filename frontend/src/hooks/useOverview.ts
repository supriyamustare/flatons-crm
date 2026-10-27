import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { LeadSource, LeadStatus } from "../lib/leads";
import type { UserBrief } from "../lib/types";

export type LeadTab = "fresh" | "today" | "visit" | "closing" | "reengage";
export interface WeekMonth { week: number; month: number }
export interface Trend { month: number; last_month: number; change_pct: number | null; daily: number[] }
export interface OverviewLead {
  id: number; lead_code: string; name: string; mobile: string; source: LeadSource; status: LeadStatus;
  city: string | null; next_action: string | null; next_at: string | null; owner: UserBrief | null;
}
export interface Overview {
  scope: "team" | "person"; person: UserBrief | null; today: string;
  in_closing: number; fresh_waiting: number; followups_due: number; followups_overdue: number; visits_today: number;
  visits_completed: WeekMonth; sales_closed: WeekMonth; sales_revenue: WeekMonth;
  performance: { enquiries: Trend; site_visits: Trend; sales: Trend; calls: Trend; spend: Trend | null; cost_per_sale: number | null };
  tab_counts: Record<LeadTab, number>; tab: LeadTab; leads: OverviewLead[];
  this_month: { new_leads: number; active: number; qualified: number; unassigned: number; active_rate: number | null; win_rate: number | null };
  people: UserBrief[];
}

export function useOverview(personId: number | null, tab: LeadTab) {
  return useQuery({
    queryKey: ["dashboard", "overview", personId, tab],
    queryFn: async () => (await api.get<Overview>("/dashboard/overview", { params: { person_id: personId ?? undefined, tab } })).data,
    placeholderData: keepPreviousData,
    refetchInterval: 60_000,
  });
}
