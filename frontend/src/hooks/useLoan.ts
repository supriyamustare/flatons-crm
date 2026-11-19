import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export type VState = "not_started" | "in_progress" | "query" | "cleared" | "rejected";
export interface LoanRow {
  id: number; lender: string; application_no: string | null; consent_on: string | null; applied_amount: number | null; sanctioned_amount: number | null;
  sanction_date: string | null; sanction_valid_until: string | null; rm_name: string | null; rm_phone: string | null; rm_email: string | null;
  technical_status: VState; legal_status: VState; pending_conditions: string | null; owner_id: number | null; next_follow_up_on: string | null;
  close_reason: string | null; received_total?: number; remaining?: number;
}
export interface Disb {
  id: number; request_no: string | null; request_date: string; for_stage: string | null; expected_amount: number; expected_date: string | null; status: string;
  delay_reason: string | null; actual_date: string | null; actual_amount: number | null; utr: string | null; state: string; delayed: boolean;
  receipt_no: string | null; receipt_status: string | null;
}
export interface LoanState {
  loan: LoanRow | null; history: LoanRow[]; stage: string | null; stages: { key: string; label: string; done: boolean; current: boolean }[];
  doc_requests: { id: number; name: string; requested_on: string; note: string | null; submitted_on: string | null }[]; disbursements: Disb[];
  ledger_loan: number; warnings: string[]; owners: UserBrief[]; can_edit: boolean; can_record_funds: boolean;
}
export const VSTATES: Record<VState, string> = { not_started: "Not started", in_progress: "In progress", query: "Query raised", cleared: "Cleared", rejected: "Rejected" };

export function useLoan(caseId: number) {
  return useQuery({ queryKey: ["loan", caseId], queryFn: async () => (await api.get<LoanState>(`/post-sales/cases/${caseId}/loan`)).data });
}
export function useLoanAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path = "", body, method = "post" }: { path?: string; body?: unknown; method?: "post" | "put" }) =>
      (method === "put" ? await api.put<LoanState>(`/post-sales/cases/${caseId}/loan${path}`, body) : await api.post<LoanState>(`/post-sales/cases/${caseId}/loan${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["loan", caseId], d); for (const k of [["receipts", caseId], ["ledger", caseId]]) void qc.invalidateQueries({ queryKey: k }); },
  });
}
