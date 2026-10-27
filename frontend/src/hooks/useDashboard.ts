import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { LeadStatus } from "../lib/leads";
import type { Task } from "../lib/tasks";
import type { UserBrief } from "../lib/types";
import type { Visit } from "../lib/visits";

export type RangeKey = "today" | "7d" | "30d" | "custom";

export interface DashboardQuery {
  range: RangeKey;
  date_from?: string;
  date_to?: string;
}

export interface Kpis {
  total_leads: number;
  new_leads: number;
  follow_ups_today: number;
  overdue_follow_ups: number;
  visits_scheduled: number;
  visits_completed: number;
  calls: number;
  calls_connected: number;
  connection_rate: number | null;
}

export interface FeedItem {
  id: number;
  type: string;
  note: string | null;
  details: Record<string, unknown> | null;
  actor: UserBrief | null;
  lead_id: number;
  lead_name: string;
  lead_code: string;
  created_at: string;
}

/** Company figures (Team view only). */
export interface Business {
  leads_generated: number;
  leads_booked: number;
  booking_rate: number | null;
  revenue: number;
  expense: number;
  profit: number;
  unvalued_bookings: number;
}

export interface Dashboard {
  scope: "team" | "mine";
  date_from: string;
  date_to: string;
  kpis: Kpis;
  leads_by_status: Record<LeadStatus, number>;
  overdue: Task[];
  visits_needing_update: Visit[];
  activity: FeedItem[];
  business: Business | null;
}

export function useDashboard(scope: "team" | "mine", query: DashboardQuery, enabled = true) {
  return useQuery({
    queryKey: ["dashboard", scope, query],
    queryFn: async () =>
      (await api.get<Dashboard>(scope === "team" ? "/dashboard/admin" : "/dashboard/executive", { params: query })).data,
    placeholderData: keepPreviousData,
    enabled,
    refetchInterval: 5 * 60_000,
  });
}
