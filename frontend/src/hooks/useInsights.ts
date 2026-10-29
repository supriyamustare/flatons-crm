import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UnitType } from "../lib/inventory";
import type { LeadSource } from "../lib/leads";
import type { UserBrief } from "../lib/types";

export interface Insights {
  projects: { id: number; name: string; location: string | null; project_type: string; unit_types: UnitType[]; price_min: number | null;
    price_max: number | null; sold: number; agreement_done: number; booked: number; blocked: number; available: number; total: number; sold_pct: number | null;
    bookings_this_month: number; booked_value_this_month: number }[];
  lead_status: { key: "working" | "quiet" | "unassigned" | "booked" | "dead"; count: number }[];
  total_leads: number;
  waiting_by_owner: { user: UserBrief | null; count: number }[];
  scheduled_30d: { key: string; count: number }[];
  months: { month: string; leads: number; deals: number }[];
  sources: { source: LeadSource; leads: number; sales: number; conversion: number | null }[];
  first_response_min: number | null;
  contacted_within_day_pct: number | null;
  recent_bookings: { id: number; booking_code: string; customer: string; project: string; unit_no: string; agreed_price: number;
    booking_date: string; sales_exec: UserBrief | null }[];
}

export function useInsights(personId: number | null) {
  return useQuery({
    queryKey: ["dashboard", "insights", personId],
    queryFn: async () => (await api.get<Insights>("/dashboard/insights", { params: { person_id: personId ?? undefined } })).data,
    placeholderData: keepPreviousData,
    refetchInterval: 120_000,
  });
}
