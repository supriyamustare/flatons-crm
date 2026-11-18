import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export interface CaseDoc {
  id: number; doc_no: string; category: string; doc_type: string; title: string; doc_number: string | null; doc_date: string | null; expiry_date: string | null;
  linked_ref: string | null; file_name: string; file_type: string; file_size: number; sha256: string; verification: "pending" | "verified" | "rejected" | "expired";
  approval: "under_approval" | "approved" | "released" | "withdrawn" | "rejected"; visibility: "internal" | "customer"; status_reason: string | null;
  version: number; supersedes: string | null; superseded: boolean; version_reason: string | null; uploaded_by: UserBrief | null; uploaded_at: string;
  reviewed_by: UserBrief | null; reviewed_at: string | null; released_at: string | null; url: string;
  can_review: boolean; can_release: boolean; can_withdraw: boolean; can_replace: boolean;
}
export interface SystemDoc { category: string; title: string; kind: string; number: string | null; date: string | null; status: string; url: string }
export interface Folder { categories: { key: string; label: string; count: number; can_upload: boolean }[]; documents: CaseDoc[]; system: SystemDoc[] }
export const APPROVAL: Record<CaseDoc["approval"], string> = { under_approval: "Under approval", approved: "Approved", released: "Released to customer", withdrawn: "Withdrawn", rejected: "Rejected" };
export const VERIFICATION: Record<CaseDoc["verification"], string> = { pending: "Verification pending", verified: "Verified", rejected: "Rejected", expired: "Expired" };

export function useFolder(caseId: number) {
  return useQuery({ queryKey: ["case-docs", caseId], queryFn: async () => (await api.get<Folder>(`/post-sales/cases/${caseId}/documents`)).data });
}
export function useDocAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: unknown }) => (await api.post<Folder>(path, body)).data,
    onSuccess: (d) => qc.setQueryData(["case-docs", caseId], d),
  });
}
