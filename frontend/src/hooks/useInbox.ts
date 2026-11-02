import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export interface InboxItem {
  id: number; lead_code: string; name: string; mobile: string; source: string; sub_source: string | null;
  project: { id: number; name: string } | null; campaign: { id: number; name: string } | null;
  message: string | null; created_at: string;
}

/** New, unassigned leads. Refreshed every 15 seconds while the page is open. */
export function useInbox() {
  return useQuery({
    queryKey: ["inbox", "list"],
    queryFn: async () => (await api.get<{ count: number; items: InboxItem[] }>("/inbox")).data,
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });
}

/** Count for the menu badge; managers and admins only. */
export function useInboxCount(enabled: boolean) {
  return useQuery({
    queryKey: ["inbox", "count"],
    queryFn: async () => (await api.get<{ count: number }>("/inbox/count")).data.count,
    refetchInterval: 30_000,
    enabled,
  });
}

export function useAssignFromInbox() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ leadId, userId }: { leadId: number; userId: number }) => {
      await api.post(`/leads/${leadId}/assign`, { assigned_to_id: userId });
    },
    onMutate: async ({ leadId }) => {
      // Take it off the list straight away; it comes back if the server refuses.
      await qc.cancelQueries({ queryKey: ["inbox", "list"] });
      const prev = qc.getQueryData<{ count: number; items: InboxItem[] }>(["inbox", "list"]);
      if (prev) qc.setQueryData(["inbox", "list"], { count: prev.count - 1, items: prev.items.filter((i) => i.id !== leadId) });
      return { prev };
    },
    onError: (_e, _v, ctx) => ctx?.prev && qc.setQueryData(["inbox", "list"], ctx.prev),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["inbox"] });
      void qc.invalidateQueries({ queryKey: ["leads"] });
    },
  });
}
