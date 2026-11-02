import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Call, CallDirection, CallOutcome, CallPage } from "../lib/calls";
import type { TaskType } from "../lib/tasks";

export interface CallQuery {
  user_id?: number;
  mine?: boolean;
  outcome?: CallOutcome;
  date_from?: string;
  date_to?: string;
  page?: number;
}

export function useCalls(query: CallQuery) {
  return useQuery({
    queryKey: ["calls", query],
    queryFn: async () => (await api.get<CallPage>("/calls", { params: query })).data,
    placeholderData: keepPreviousData,
  });
}

export interface NewCall {
  lead_id: number;
  outcome: CallOutcome;
  direction: CallDirection;
  duration_sec?: number;
  notes?: string;
  follow_up_at?: string;
  follow_up_type?: TaskType;
  complete_task_id?: number;
}

export function useLogCall() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: NewCall) => (await api.post<Call>("/calls", body)).data,
    onSuccess: (call) => {
      void qc.invalidateQueries({ queryKey: ["calls"] });
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void qc.invalidateQueries({ queryKey: ["leads", "detail", call.lead.id] });
      void qc.invalidateQueries({ queryKey: ["leads", "search"] });
    },
  });
}
