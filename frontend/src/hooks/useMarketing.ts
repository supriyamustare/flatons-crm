import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { Campaign, Channel, Expense, ExpenseCategory, ExpensePage } from "../lib/marketing";

export function useCampaigns(enabled = true) {
  return useQuery({ queryKey: ["campaigns"], queryFn: async () => (await api.get<Campaign[]>("/campaigns")).data, enabled, staleTime: 60_000 });
}

function useMarketingMutation<V, R>(fn: (v: V) => Promise<R>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["campaigns"] });
      void qc.invalidateQueries({ queryKey: ["expenses"] });
      void qc.invalidateQueries({ queryKey: ["reports"] });
    },
  });
}

export interface CampaignInput { name?: string; channel?: Channel; project_id?: number | null; start_date?: string; end_date?: string | null; description?: string | null }
export const useSaveCampaign = () =>
  useMarketingMutation(async ({ id, ...body }: CampaignInput & { id?: number }) =>
    (id ? await api.patch<Campaign>(`/campaigns/${id}`, body) : await api.post<Campaign>("/campaigns", body)).data);
export const useDeleteCampaign = () => useMarketingMutation(async (id: number) => { await api.delete(`/campaigns/${id}`); });

export interface ExpenseQuery { campaign_id?: number; channel?: Channel; date_from?: string; date_to?: string; page?: number }
export function useExpenses(q: ExpenseQuery) {
  return useQuery({ queryKey: ["expenses", q], queryFn: async () => (await api.get<ExpensePage>("/expenses", { params: q })).data, placeholderData: keepPreviousData });
}

export interface NewExpense { campaign_id: number; spent_on: string; amount: number; category: ExpenseCategory; vendor?: string; notes?: string; receipt?: File | null }
export const useCreateExpense = () =>
  useMarketingMutation(async (e: NewExpense) => {
    const form = new FormData();
    form.append("campaign_id", String(e.campaign_id));
    form.append("spent_on", e.spent_on);
    form.append("amount", String(e.amount));
    form.append("category", e.category);
    if (e.vendor) form.append("vendor", e.vendor);
    if (e.notes) form.append("notes", e.notes);
    if (e.receipt) form.append("receipt", e.receipt);
    return (await api.post<Expense>("/expenses", form)).data;
  });
export const useDeleteExpense = () => useMarketingMutation(async (id: number) => { await api.delete(`/expenses/${id}`); });

/** Receipts are served by the API (with the user's cookies), never from a public folder. */
export const receiptUrl = (id: number) => `/api/expenses/${id}/receipt`;
