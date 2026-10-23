import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Duplicate, Lead, LeadDetail, LeadFilters, LeadStatus, Project } from "../lib/leads";
import type { UserBrief } from "../lib/types";

export interface LeadQuery extends LeadFilters {
  sort: "created_at" | "updated_at" | "last_activity_at" | "name";
  order: "asc" | "desc";
  page: number;
  page_size: number;
}

export interface LeadPage {
  items: Lead[];
  total: number;
  page: number;
  page_size: number;
}

export type LeadPayload = Record<string, unknown>;

export function useLeadSearch(query: LeadQuery) {
  return useQuery({
    queryKey: ["leads", "search", query],
    queryFn: async () => (await api.post<LeadPage>("/leads/search", query)).data,
    placeholderData: keepPreviousData,
  });
}

export function useLead(id: number) {
  return useQuery({
    queryKey: ["leads", "detail", id],
    queryFn: async () => (await api.get<LeadDetail>(`/leads/${id}`)).data,
  });
}

/** Every lead change returns the full detail; cache it and refresh lists. */
function useLeadMutation<T>(fn: (vars: T) => Promise<LeadDetail>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (lead) => {
      qc.setQueryData(["leads", "detail", lead.id], lead);
      void qc.invalidateQueries({ queryKey: ["leads", "search"] });
    },
  });
}

export function useCreateLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: LeadPayload) =>
      (await api.post<{ lead: Lead; duplicates: Duplicate[] }>("/leads", body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads", "search"] }),
  });
}

export const useUpdateLead = () =>
  useLeadMutation(async ({ id, changes }: { id: number; changes: LeadPayload }) =>
    (await api.patch<LeadDetail>(`/leads/${id}`, changes)).data);

export const useChangeStatus = () =>
  useLeadMutation(async ({ id, ...body }: { id: number; status: LeadStatus; reason?: string; note?: string }) =>
    (await api.post<LeadDetail>(`/leads/${id}/status`, body)).data);

export const useAddNote = () =>
  useLeadMutation(async ({ id, note }: { id: number; note: string }) =>
    (await api.post<LeadDetail>(`/leads/${id}/notes`, { note })).data);

export const useAssignLead = () =>
  useLeadMutation(async ({ id, assigned_to_id }: { id: number; assigned_to_id: number | null }) =>
    (await api.post<LeadDetail>(`/leads/${id}/assign`, { assigned_to_id })).data);

export function useDeleteLead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.delete(`/leads/${id}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["leads"] }),
  });
}

export async function checkDuplicates(body: {
  mobile?: string; alt_mobile?: string; email?: string; exclude_id?: number;
}): Promise<Duplicate[]> {
  return (await api.post<Duplicate[]>("/leads/duplicates", body)).data;
}

export function useProjects(includeInactive = false) {
  return useQuery({
    queryKey: ["projects", includeInactive],
    queryFn: async () =>
      (await api.get<Project[]>("/projects", { params: includeInactive ? { include_inactive: true } : {} })).data,
    staleTime: 5 * 60_000,
  });
}

export function useSaveProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: { id?: number; name?: string; is_active?: boolean }) =>
      id ? (await api.patch<Project>(`/projects/${id}`, body)).data : (await api.post<Project>("/projects", body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["projects"] }),
  });
}

export function useAssignableUsers(enabled: boolean) {
  return useQuery({
    queryKey: ["users", "assignable"],
    queryFn: async () => (await api.get<UserBrief[]>("/users/assignable")).data,
    enabled,
    staleTime: 5 * 60_000,
  });
}
