import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export type DemandStatus = "draft" | "pending_approval" | "approved" | "issued" | "cancelled";
export type IssueMethod = "email" | "hand" | "courier" | "whatsapp" | "other";
export interface Demand {
  id: number; demand_no: string; version: number; stage_seq: number; stage_name: string; stage_amount: number; previous_dues: number; total_due: number;
  demanded_on: string; due_date: string; status: DemandStatus; payment: string; outstanding_now: number; note: string | null; cancel_reason: string | null;
  issue_method: IssueMethod | null; prepared_by: UserBrief | null; submitted_by: UserBrief | null; approved_by: UserBrief | null; issued_by: UserBrief | null;
  issued_at: string | null; supersedes: string | null; can_submit: boolean; can_approve: boolean; can_issue: boolean; can_cancel: boolean;
}
export interface Demands {
  demands: Demand[]; can_create: { seq: number; name: string; outstanding: number }[]; ledger_approved: boolean;
  readiness: { ready: boolean; missing: string[] } | null;
}
export interface Milestone {
  id: number | null; name: string; status: "planned" | "reported" | "verified"; completed_on: string | null; note: string | null; returned_reason: string | null;
  reported_by: UserBrief | null; reported_at: string | null; verified_by: UserBrief | null; verified_at: string | null;
  evidence: { id: number; file_name: string; file_type: string; url: string }[]; can_report: boolean; can_verify: boolean;
}
export const DEMAND_STATUS: Record<DemandStatus, string> = { draft: "Draft", pending_approval: "Waiting for approval", approved: "Approved", issued: "Issued", cancelled: "Cancelled" };
export const ISSUE_LABELS: Record<IssueMethod, string> = { email: "Email", hand: "Handed over", courier: "Courier", whatsapp: "WhatsApp", other: "Other" };

export function useDemands(caseId: number) {
  return useQuery({ queryKey: ["demands", caseId], queryFn: async () => (await api.get<Demands>(`/post-sales/cases/${caseId}/demands`)).data });
}
export function useDemandAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path = "", body }: { path?: string; body?: unknown }) => (await api.post<Demands>(`/post-sales/cases/${caseId}/demands${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["demands", caseId], d); void qc.invalidateQueries({ queryKey: ["ledger", caseId] }); },
  });
}
export function useMilestones(projectId: number, enabled: boolean) {
  return useQuery({ queryKey: ["milestones", projectId], queryFn: async () => (await api.get<Milestone[]>(`/projects/${projectId}/milestones`)).data, enabled });
}
