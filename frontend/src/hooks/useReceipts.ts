import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";
import type { ChargeHead, Ledger } from "./useLedger";

export type ReceiptMode = "cheque" | "dd" | "neft" | "rtgs" | "imps" | "upi" | "card" | "cash" | "other";
export type ReceiptStatus = "recorded" | "confirmed" | "bounced" | "reversed";
export interface Match { stage_seq: number | null; charge_head: ChargeHead | null; amount: number }
export interface Receipt {
  id: number; receipt_no: string; amount: number; received_on: string; mode: ReceiptMode; source: "own" | "loan"; payer_name: string | null;
  reference: string | null; bank_name: string | null; notes: string | null; from_booking: boolean; status: ReceiptStatus; matched: number; unapplied: number;
  matches: Match[]; recorded_by: UserBrief | null; recorded_at: string; confirmed_by: UserBrief | null; confirmed_at: string | null;
  void_reason: string | null; voided_at: string | null; can_match: boolean; can_confirm: boolean; can_bounce: boolean; can_reverse: boolean;
}
export interface StageRow { seq: number; name: string; due: string; total: number; paid: number; outstanding: number; is_due: boolean }
export interface HeadRow { head: ChargeHead; label: string; total: number; paid: number; outstanding: number }
export interface Receipts {
  ledger_exists: boolean; receipts: Receipt[]; stages: StageRow[]; other_charges: HeadRow[]; can_record: boolean;
  balances: (NonNullable<Ledger["balances"]> & { unapplied: number; pending_confirmation: number }) | null;
}
export const MODE_LABELS: Record<ReceiptMode, string> = { cheque: "Cheque", dd: "Demand draft", neft: "NEFT", rtgs: "RTGS", imps: "IMPS", upi: "UPI", card: "Card", cash: "Cash", other: "Other" };
export const RECEIPT_STATUS: Record<ReceiptStatus, string> = { recorded: "Waiting for confirmation", confirmed: "Confirmed", bounced: "Bounced", reversed: "Reversed" };

export function useReceipts(caseId: number, enabled = true) {
  return useQuery({ queryKey: ["receipts", caseId], queryFn: async () => (await api.get<Receipts>(`/post-sales/cases/${caseId}/receipts`)).data, enabled });
}
export function useReceiptAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path = "", body, method = "post" }: { path?: string; body?: unknown; method?: "post" | "put" }) =>
      (method === "put" ? await api.put<Receipts>(`/post-sales/cases/${caseId}/receipts${path}`, body) : await api.post<Receipts>(`/post-sales/cases/${caseId}/receipts${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(["receipts", caseId], d); void qc.invalidateQueries({ queryKey: ["ledger", caseId] }); },
  });
}
