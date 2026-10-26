import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Developer, Inventory, ProjectFull, ProjectStatus, ProjectType, Unit, UnitStatus, UnitType } from "../lib/inventory";

export function useProjectList(includeInactive = false) {
  return useQuery({
    queryKey: ["projects", "list", includeInactive],
    queryFn: async () =>
      (await api.get<ProjectFull[]>("/projects", { params: includeInactive ? { include_inactive: true } : {} })).data,
  });
}

export function useDevelopers(enabled = true) {
  return useQuery({
    queryKey: ["developers"],
    queryFn: async () => (await api.get<Developer[]>("/developers")).data,
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useInventory(projectId: number) {
  return useQuery({
    queryKey: ["inventory", projectId],
    queryFn: async () => (await api.get<Inventory>(`/projects/${projectId}/inventory`)).data,
    // Someone else may hold a unit; keep the grid reasonably fresh.
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}

/** Any inventory change refreshes the grid and project counts. */
function useInvMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["inventory"] });
      void qc.invalidateQueries({ queryKey: ["projects"] });
      void qc.invalidateQueries({ queryKey: ["developers"] });
    },
  });
}

export interface ProjectInput {
  name?: string;
  project_type?: ProjectType;
  status?: ProjectStatus;
  developer_id?: number;
  developer_name?: string;
  location?: string | null;
  description?: string | null;
  is_active?: boolean;
}

export const useCreateProject = () =>
  useInvMutation(async (body: ProjectInput) => (await api.post<ProjectFull>("/projects", body)).data);

export const useUpdateProject = () =>
  useInvMutation(async ({ id, ...body }: ProjectInput & { id: number }) =>
    (await api.patch<ProjectFull>(`/projects/${id}`, body)).data);

export const useCreateBuilding = () =>
  useInvMutation(async ({ projectId, name }: { projectId: number; name: string }) =>
    (await api.post<{ id: number; name: string }>(`/projects/${projectId}/buildings`, { name })).data);

export interface GenerateInput {
  buildingId: number;
  floor_from: number;
  floor_to: number;
  units_per_floor: number;
  unit_type: UnitType;
  carpet_sqft?: number;
  builtup_sqft?: number;
  base_price?: number;
}

export const useGenerateUnits = () =>
  useInvMutation(async ({ buildingId, ...body }: GenerateInput) =>
    (await api.post<{ created: number }>(`/buildings/${buildingId}/generate`, body)).data);

export interface UnitInput {
  unit_no?: string;
  unit_type?: UnitType;
  floor_id?: number;
  carpet_sqft?: number | null;
  builtup_sqft?: number | null;
  base_price?: number | null;
  current_asking_price?: number | null;
  address_note?: string | null;
  status?: Extract<UnitStatus, "available" | "withdrawn" | "sold">;
}

export const useCreateUnit = () =>
  useInvMutation(async ({ projectId, ...body }: UnitInput & { projectId: number }) =>
    (await api.post<Unit>(`/projects/${projectId}/units`, body)).data);

export const useUpdateUnit = () =>
  useInvMutation(async ({ id, ...body }: UnitInput & { id: number }) => (await api.patch<Unit>(`/units/${id}`, body)).data);

export const useDeleteUnit = () =>
  useInvMutation(async (id: number) => {
    await api.delete(`/units/${id}`);
  });

export const useHoldUnit = () =>
  useInvMutation(async ({ id, ...body }: { id: number; hours: number; lead_id?: number; note?: string }) =>
    (await api.patch<Unit>(`/units/${id}/hold`, body)).data);

export const useReleaseUnit = () =>
  useInvMutation(async (id: number) => (await api.patch<Unit>(`/units/${id}/release`)).data);
