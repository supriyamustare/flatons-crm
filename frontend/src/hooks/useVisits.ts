import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { InterestLevel, Visit, VisitPage, VisitSource, VisitView } from "../lib/visits";
import type { TaskType } from "../lib/tasks";

export interface VisitQuery {
  view: VisitView;
  project_id?: number;
  host_id?: number;
  mine?: boolean;
  page?: number;
}

export function useVisits(query: VisitQuery) {
  return useQuery({
    queryKey: ["visits", "list", query],
    queryFn: async () => (await api.get<VisitPage>("/visits", { params: query })).data,
    placeholderData: keepPreviousData,
  });
}

export function useLeadVisits(leadId: number) {
  return useQuery({
    queryKey: ["visits", "lead", leadId],
    queryFn: async () => (await api.get<Visit[]>(`/leads/${leadId}/visits`)).data,
  });
}

/** Visit changes can move the lead's status and add follow-ups, so refresh those too. */
function useVisitMutation<T>(fn: (vars: T) => Promise<Visit>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (visit) => {
      void qc.invalidateQueries({ queryKey: ["visits"] });
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void qc.invalidateQueries({ queryKey: ["leads", "detail", visit.lead.id] });
      void qc.invalidateQueries({ queryKey: ["leads", "search"] });
    },
  });
}

export interface NewVisit {
  lead_id: number;
  project_id: number;
  scheduled_at: string;
  visit_source: VisitSource;
  notes?: string;
  host_id?: number;
}

export function useScheduleVisit() {
  return useVisitMutation(async (body: NewVisit) => (await api.post<Visit>("/visits", body)).data);
}

export type VisitAction =
  | { kind: "complete"; feedback: string; interest_level: InterestLevel; next_action?: string; follow_up_at?: string; follow_up_type?: TaskType }
  | { kind: "reschedule"; scheduled_at: string; reason?: string }
  | { kind: "no-show"; note?: string }
  | { kind: "cancel"; reason: string };

export function useVisitAction() {
  return useVisitMutation(async ({ id, action }: { id: number; action: VisitAction }) => {
    const { kind, ...body } = action;
    return (await api.post<Visit>(`/visits/${id}/${kind}`, body)).data;
  });
}
