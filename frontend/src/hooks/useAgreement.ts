import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export interface Draft {
  agreement_no: string; version: number; date: string; agreement_value: number; gst: number; gst_pct: number; placeholder_clauses: boolean; clauses: string[];
  developer: { name: string | null; address: string | null; gstin: string | null; cin: string | null; signatory: string | null; designation: string | null; rera: string | null };
  purchasers: { name: string | null; pan: string | null; share: number | null; address?: string | null; relation?: string | null; entity?: string | null }[];
  unit: { project: string; location: string | null; building: string | null; floor: number | null; unit_no: string; type: string; carpet_sqft: number | null; saleable_sqft: number | null };
  consideration: { label: string; amount: number }[]; schedule: { name: string; amount: number; gst: number; due: string }[];
}
export interface Agreement {
  id: number; agreement_no: string; status: string; version: number; draft: Draft | null; legal_approved_by: UserBrief | null; legal_approved_at: string | null;
  finance_approved_by: UserBrief | null; finance_approved_at: string | null; changes_note: string | null; shared_on: string | null; share_method: string | null;
  customer_accepted_on: string | null; stamp_duty_amount: number | null; stamp_duty_paid_on: string | null; stamp_duty_ref: string | null;
  registration_fee_amount: number | null; registration_fee_paid_on: string | null; registration_fee_ref: string | null; appointment_at: string | null;
  sro_office: string | null; id_docs_ready: boolean; signing_note: string | null; executed_on: string | null; registration_no: string | null; registered_on: string | null;
  final_document: { id: number; doc_no: string; approval: string; url: string } | null; cancel_reason: string | null; drafted_by_id: number | null;
}
export interface AgreementState {
  agreement: Agreement | null; history: Agreement[]; conditions: { item: string; ok: boolean; detail?: string | null }[];
  checks: { item: string; ok: boolean; detail?: string | null }[]; can: Record<string, boolean>;
}
export const STEPS: [string, string][] = [
  ["initiated", "Initiated"], ["data_verified", "Data verified"], ["drafted", "Drafted"], ["internal_review", "Internal review"], ["customer_review", "Customer review"],
  ["execution_prep", "Execution preparation"], ["registered", "Signed & registered"], ["final_uploaded", "Final uploaded"], ["completed", "Released"],
];

export function useAgreement(caseId: number) {
  return useQuery({ queryKey: ["agreement", caseId], queryFn: async () => (await api.get<AgreementState>(`/post-sales/cases/${caseId}/agreement`)).data });
}
export function useAgreementAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, body, method = "post" }: { path: string; body?: unknown; method?: "post" | "put" }) =>
      (method === "put" ? await api.put<AgreementState>(`/post-sales/cases/${caseId}/agreement${path}`, body) : await api.post<AgreementState>(`/post-sales/cases/${caseId}/agreement${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["agreement", caseId], d); void qc.invalidateQueries({ queryKey: ["case-docs", caseId] }); },
  });
}
