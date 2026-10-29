import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UnitType } from "../lib/inventory";

export interface FloorPlan {
  id: number; project_id: number; floor_id: number | null; floor_number: number | null; unit_type: UnitType | null;
  title: string; file_name: string; file_type: string; url: string; applies_to: string;
}

export function useProjectFloorPlans(projectId: number) {
  return useQuery({ queryKey: ["floor-plans", "project", projectId], queryFn: async () => (await api.get<FloorPlan[]>(`/projects/${projectId}/floor-plans`)).data, enabled: projectId > 0 });
}
export function useUnitFloorPlans(unitId: number) {
  return useQuery({ queryKey: ["floor-plans", "unit", unitId], queryFn: async () => (await api.get<FloorPlan[]>(`/units/${unitId}/floor-plans`)).data, enabled: unitId > 0 });
}
export function useUploadFloorPlan(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { title: string; file: File; floor_id?: number; unit_type?: UnitType }) => {
      const form = new FormData();
      form.append("title", v.title);
      form.append("file", v.file);
      if (v.floor_id) form.append("floor_id", String(v.floor_id));
      if (v.unit_type) form.append("unit_type", v.unit_type);
      return (await api.post<FloorPlan>(`/projects/${projectId}/floor-plans`, form)).data;
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["floor-plans"] }),
  });
}
export function useDeleteFloorPlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => { await api.delete(`/floor-plans/${id}`); },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["floor-plans"] }),
  });
}
