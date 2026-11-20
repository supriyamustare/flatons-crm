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
  phase?: string | null; building_label?: string | null; planned_on?: string | null; percent_complete?: number | null; responsible_pm?: UserBrief | null;
  delay_reason?: string | null; revised_expected_on?: string | null; schedule_impact?: string | null; impact_recorded_by?: UserBrief | null;
  impact_approved_by?: UserBrief | null; impact_approved_at?: string | null; can_approve_impact?: boolean;
  progress?: { id: number; percent_complete: number | null; planned_on: string | null; revised_expected_on: string | null; delay_reason: string | null; note: string | null;
    at: string; by: string | null; photos: { id: number; file_name: string; url: string }[] }[];
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

export interface ProjectUpdate {
  id: number; title: string; body: string; status: "draft" | "pending_approval" | "published"; milestone: string | null; author: string | null; created_at: string;
  published_at: string | null; published_by: string | null; returned_reason: string | null; photos: { id: number; file_name: string; url: string }[];
  corrections: { at: string; by: string | null; reason: string; previous_title: string; previous_body: string }[]; can_edit: boolean; can_publish: boolean; can_correct: boolean;
}
export function useProjectUpdates(projectId: number, enabled: boolean) {
  return useQuery({ queryKey: ["project-updates", projectId], queryFn: async () => (await api.get<ProjectUpdate[]>(`/projects/${projectId}/updates`)).data, enabled });
}
