import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export type Channel = "call" | "email" | "sms" | "whatsapp" | "visit" | "letter" | "note";
export type Outcome = "reached" | "not_reachable" | "promised" | "disputed" | "says_paid" | "other";
export interface FollowUp {
  id: number; channel: Channel; outcome: Outcome; note: string | null; demand_id: number | null; demand_no: string | null; contacted_on: string;
  promise_date: string | null; promise_amount: number | null; promise_status: "open" | "kept" | "broken" | null; next_follow_up_on: string | null;
  by: UserBrief | null; created_at: string;
}
export interface FollowUps { items: FollowUp[]; outstanding: number; demands: { id: number; demand_no: string; stage_name: string }[]; can_write: boolean }
export interface DueItem { case_id: number; case_code: string; customer: string; reason: string; on: string; amount: number | null }
export const CHANNELS: Record<Channel, string> = { call: "Call", email: "Email", sms: "SMS", whatsapp: "WhatsApp", visit: "Visit", letter: "Letter", note: "Internal note" };
export const OUTCOMES: Record<Outcome, string> = { reached: "Reached", not_reachable: "Not reachable", promised: "Promised to pay", disputed: "Disputes the amount", says_paid: "Says already paid", other: "Other" };

export function useFollowUps(caseId: number) {
  return useQuery({ queryKey: ["follow-ups", caseId], queryFn: async () => (await api.get<FollowUps>(`/post-sales/cases/${caseId}/follow-ups`)).data });
}
export function useAddFollowUp(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: Record<string, unknown>) => (await api.post<FollowUps>(`/post-sales/cases/${caseId}/follow-ups`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["follow-ups", caseId], d); void qc.invalidateQueries({ queryKey: ["follow-ups-due"] }); },
  });
}
export function useFollowUpsDue(enabled: boolean) {
  return useQuery({ queryKey: ["follow-ups-due"], queryFn: async () => (await api.get<DueItem[]>("/post-sales/follow-ups/due")).data, enabled });
}
