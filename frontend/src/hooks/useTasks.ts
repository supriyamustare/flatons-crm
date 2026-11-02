import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Task, TaskPage, TaskType, TaskView } from "../lib/tasks";

export interface TaskQuery {
  view: TaskView;
  task_type?: TaskType;
  assigned_to_id?: number;
  mine?: boolean;
  page?: number;
}

export function useTasks(query: TaskQuery, enabled = true) {
  return useQuery({
    queryKey: ["tasks", "list", query],
    queryFn: async () => (await api.get<TaskPage>("/tasks", { params: query })).data,
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useLeadTasks(leadId: number) {
  return useQuery({
    queryKey: ["tasks", "lead", leadId],
    queryFn: async () => (await api.get<Task[]>(`/leads/${leadId}/tasks`)).data,
  });
}

/** Any task change can affect task lists, the lead's timeline and lead lists (last activity). */
function useTaskMutation<T>(fn: (vars: T) => Promise<Task>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (task) => {
      void qc.invalidateQueries({ queryKey: ["tasks"] });
      void qc.invalidateQueries({ queryKey: ["leads", "detail", task.lead.id] });
      void qc.invalidateQueries({ queryKey: ["leads", "search"] });
    },
  });
}

export interface NewTask {
  lead_id: number;
  task_type: TaskType;
  due_at: string;
  notes?: string;
  assigned_to_id?: number;
}

export function useCreateTask() {
  return useTaskMutation(async (body: NewTask) => (await api.post<Task>("/tasks", body)).data);
}

export function useCompleteTask() {
  return useTaskMutation(
    async ({ id, completion_note }: { id: number; completion_note: string }) =>
      (await api.post<Task>(`/tasks/${id}/complete`, { completion_note })).data,
  );
}

export function useRescheduleTask() {
  return useTaskMutation(
    async ({ id, due_at, reason }: { id: number; due_at: string; reason?: string }) =>
      (await api.post<Task>(`/tasks/${id}/reschedule`, { due_at, reason: reason || undefined })).data,
  );
}
