import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export interface Sla { response_due_at: string; resolution_due_at: string; first_response_at: string | null; response_breached: boolean; resolution_breached: boolean;
  at_risk: boolean; paused: boolean; paused_hours_customer: number; paused_hours_external: number }
export interface TicketRow {
  id: number; ticket_no: string; case_id: number; case_code: string; customer: string; unit: string; category: string; category_label: string; subcategory: string | null;
  title: string; priority: "low" | "normal" | "high" | "urgent"; team: string; team_label: string; status: string; owner: UserBrief | null; created_at: string;
  closed_at: string | null; closure_reason: string | null; reopened_count: number; csat: number | null; sla: Sla;
}
export interface TicketDetail extends TicketRow {
  description: string; channel: string; raised_by: UserBrief | null; resolution: string | null; resolved_at: string | null; customer_confirmed: boolean | null;
  confirmed_at: string | null; csat_comment: string | null; needs_confirmation: boolean; reopen_days: number; owners?: UserBrief[];
  timeline: { id: number; kind: string; internal: boolean; text: string | null; data: Record<string, unknown> | null; by: UserBrief | null; at: string }[];
  attachments: { id: number; file_name: string; purpose: string; url: string }[]; can: Record<string, boolean>;
}
export interface TicketList { items: TicketRow[]; categories: Record<string, string>; teams: Record<string, string> }
export const STATUS: Record<string, string> = { raised: "Raised", assigned: "Assigned", acknowledged: "Acknowledged", in_progress: "In progress",
  waiting_customer: "Waiting for customer", waiting_internal: "Waiting for internal team", waiting_external: "Waiting for third party",
  resolution_proposed: "Resolution proposed", closed: "Closed" };
export const CLOSURE: Record<string, string> = { resolved: "Resolved", duplicate: "Duplicate", not_applicable: "Not applicable", customer_withdrew: "Customer withdrew",
  no_response: "No response from customer", transferred: "Transferred" };

export function useTickets(params: Record<string, string | number | undefined>, enabled = true) {
  return useQuery({ queryKey: ["tickets", params], queryFn: async () => (await api.get<TicketList>("/tickets", { params })).data, enabled });
}
export function useTicket(id: number) {
  return useQuery({ queryKey: ["ticket", id], queryFn: async () => (await api.get<TicketDetail>(`/tickets/${id}`)).data });
}
export function useTicketAction(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: unknown }) => (await api.post<TicketDetail>(`/tickets/${id}${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["ticket", id], d); void qc.invalidateQueries({ queryKey: ["tickets"] }); },
  });
}
export function slaBadge(s: Sla, closed: boolean): { text: string; tone: "gold" | "neutral" | "muted" } | null {
  if (s.resolution_breached && !closed) return { text: "SLA breached", tone: "gold" };
  if (s.response_breached && !s.first_response_at) return { text: "Response overdue", tone: "gold" };
  if (s.paused && !closed) return { text: "SLA paused", tone: "muted" };
  if (s.at_risk) return { text: "At risk", tone: "gold" };
  return null;
}
