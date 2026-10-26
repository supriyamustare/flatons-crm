import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { LeadStatus } from "../lib/leads";
import type { Forecast, PipelineBoard, StageProbability } from "../lib/pipeline";

export interface PipelineQuery {
  project_id?: number;
  assigned_to_id?: number;
  mine?: boolean;
  include_closed?: boolean;
  stale_only?: boolean;
}

export function usePipeline(query: PipelineQuery) {
  return useQuery({
    queryKey: ["pipeline", "board", query],
    queryFn: async () => (await api.get<PipelineBoard>("/pipeline", { params: query })).data,
    placeholderData: keepPreviousData,
  });
}

export function useForecast(query: PipelineQuery) {
  return useQuery({
    queryKey: ["pipeline", "forecast", query],
    queryFn: async () => (await api.get<Forecast>("/pipeline/forecast", { params: query })).data,
    placeholderData: keepPreviousData,
  });
}

export function useStageProbabilities() {
  return useQuery({
    queryKey: ["pipeline", "stages"],
    queryFn: async () => (await api.get<StageProbability[]>("/pipeline/stages")).data,
  });
}

export function useUpdateProbabilities() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (stages: StageProbability[]) => (await api.patch<StageProbability[]>("/pipeline/stages", { stages })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline"] }),
  });
}

export interface MoveLead {
  leadId: number;
  from: LeadStatus;
  to: LeadStatus;
  reason?: string;
}

/** Move a card. The board updates straight away and rolls back if the server says no. */
export function useMoveLead(query: PipelineQuery) {
  const qc = useQueryClient();
  const key = ["pipeline", "board", query];
  return useMutation({
    mutationFn: async ({ leadId, to, reason }: MoveLead) => {
      await api.patch(`/leads/${leadId}/pipeline`, { status: to, reason: reason || undefined });
    },
    onMutate: async ({ leadId, from, to }) => {
      await qc.cancelQueries({ queryKey: key });
      const previous = qc.getQueryData<PipelineBoard>(key);
      if (previous) {
        const card = previous.stages.find((s) => s.stage === from)?.cards.find((c) => c.id === leadId);
        if (card) {
          const moved = { ...card, status: to, days_in_stage: 0 };
          qc.setQueryData<PipelineBoard>(key, {
            ...previous,
            stages: previous.stages.map((s) =>
              s.stage === from ? { ...s, count: s.count - 1, cards: s.cards.filter((c) => c.id !== leadId) }
              : s.stage === to ? { ...s, count: s.count + 1, cards: [moved, ...s.cards] }
              : s),
          });
        }
      }
      return { previous };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.previous) qc.setQueryData(key, ctx.previous);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
      void qc.invalidateQueries({ queryKey: ["leads"] });
      void qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });
}
