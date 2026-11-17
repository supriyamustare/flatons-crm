import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export type LedgerStatus = "draft" | "pending_approval" | "approved";
export type ChargeHead = "base_price" | "floor_rise" | "plc" | "parking" | "amenities" | "discount" | "gst" | "stamp_duty" | "registration"
  | "legal" | "furnishing" | "maintenance_deposit" | "society_formation" | "other";
export type Trigger = "on_booking" | "on_date" | "on_milestone";
export interface Charge { id?: number; head: ChargeHead; label: string; amount: number }
export interface Item { id?: number; seq?: number; name: string; amount: number; gst: number; trigger_type: Trigger; due_date: string | null; milestone: string | null; is_due?: boolean }
export interface Ledger {
  exists: boolean; status: LedgerStatus | null; version: number; gst_pct: number; loan_sanctioned: number; lender: string | null; loan_reference: string | null;
  note: string | null; submitted_by: UserBrief | null; submitted_at: string | null; approved_by: UserBrief | null; approved_at: string | null;
  charges: Charge[]; schedule: Item[]; problems: string[]; can_edit: boolean; can_approve: boolean; head_labels: Record<string, string>;
  totals: { agreement_value: number; gst: number; statutory: number; other: number; total_payable: number; schedule_amount: number; schedule_gst: number } | null;
  balances: { received: number; received_own: number; loan_disbursed: number; total_outstanding: number; currently_demanded: number; overdue: number;
    own_contribution_required: number; loan_not_disbursed: number; under_dispute: number; other_charges: number; unapplied: number; pending_confirmation: number } | null;
}
export const AGREEMENT: ChargeHead[] = ["base_price", "floor_rise", "plc", "parking", "amenities", "discount"];
export const STATUTORY: ChargeHead[] = ["stamp_duty", "registration"];
export const OTHER: ChargeHead[] = ["legal", "furnishing", "maintenance_deposit", "society_formation", "other"];
export const STATUS_LABELS: Record<LedgerStatus, string> = { draft: "Draft", pending_approval: "Waiting for approval", approved: "Approved" };
export const TRIGGER_LABELS: Record<Trigger, string> = { on_booking: "On booking", on_date: "On a date", on_milestone: "On a milestone" };

export function useLedger(caseId: number, enabled: boolean) {
  return useQuery({ queryKey: ["ledger", caseId], queryFn: async () => (await api.get<Ledger>(`/post-sales/cases/${caseId}/ledger`)).data, enabled });
}
export function useLedgerAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, body, method = "post" }: { path: string; body?: unknown; method?: "post" | "put" }) =>
      (method === "put" ? await api.put<Ledger>(`/post-sales/cases/${caseId}/ledger${path}`, body) : await api.post<Ledger>(`/post-sales/cases/${caseId}/ledger${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["ledger", caseId], d); void qc.invalidateQueries({ queryKey: ["post-sales", caseId] }); },
  });
}
export const inr = (n: number) => `${n < 0 ? "−" : ""}₹ ${Math.abs(n).toLocaleString("en-IN")}`;
