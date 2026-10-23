import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export interface AppNotification {
  id: number;
  type: string;
  title: string;
  body: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

const KEY = ["notifications"] as const;

/** Polled every minute while the app is open (and refreshed when the tab regains focus). */
export function useNotifications() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () =>
      (await api.get<{ items: AppNotification[]; unread_count: number }>("/notifications")).data,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await api.patch(`/notifications/${id}/read`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}

export function useMarkAllRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await api.post("/notifications/read-all");
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
