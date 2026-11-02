import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export type CaseStatus = "handover_pending" | "returned_to_sales" | "accepted" | "cancelled";
export type OnboardingStatus = "not_started" | "otp_verification" | "documents_pending" | "under_review" | "clarification_required" | "approved";
export type OwnershipType = "individual" | "joint" | "company" | "partnership" | "huf" | "trust" | "other";
export type KycDocType = "pan" | "aadhaar" | "passport" | "voter_id" | "driving_licence" | "address_proof" | "photo" | "entity_pan" | "registration_certificate" | "board_resolution" | "other";

export interface CaseSummary {
  id: number; case_code: string; status: CaseStatus; onboarding_status: OnboardingStatus; customer: string; project: string; unit_no: string;
  booking_id: number; booking_code: string; booking_date: string; agreed_price: number; owner: UserBrief | null; sales_exec: UserBrief | null;
  created_at: string; kyc_done: number; kyc_total: number;
}
export interface Profile {
  ownership_type: OwnershipType; legal_name: string | null; entity_name: string | null; date_of_birth: string | null; pan: string | null;
  ownership_pct: string | null; mobile: string | null; email: string | null; correspondence_address: string | null; permanent_address: string | null;
  preferred_language: string | null; contact_email: boolean; contact_sms: boolean; contact_whatsapp: boolean; communication_needs: string | null;
  consent_portal_at: string | null; consent_electronic_at: string | null; consent_data_at: string | null;
  nominee_name: string | null; nominee_relation: string | null; nominee_mobile: string | null;
}
export interface CoApplicant { id: number; name: string; relation: string | null; date_of_birth: string | null; pan: string | null; mobile: string | null; email: string | null; ownership_pct: string | null }
export interface KycDoc { id: number; co_applicant_id: number | null; doc_type: KycDocType; status: string; file_name: string; file_type: string; expiry_date: string | null;
  review_note: string | null; uploaded_at: string; uploaded_by_id: number | null; reviewed_at: string | null; superseded_by_id: number | null }
export interface Requirement { applicant_id: number | null; applicant: string; key: string; label: string; accepted_types: KycDocType[];
  status: "missing" | "pending" | "verified" | "rejected" | "expired"; document_id: number | null }
export interface CaseDetail extends CaseSummary {
  returned_reason: string | null; clarification_reason: string | null; accepted_at: string | null;
  handover: { item: string; ok: boolean; required: boolean }[]; profile: Profile | null; co_applicants: CoApplicant[];
  requirements: Requirement[]; documents: KycDoc[]; profile_problems: string[]; can_edit: boolean; can_view_kyc: boolean;
  history: { at: string; action: string; actor: UserBrief | null; details: Record<string, unknown> | null }[];
}

export const CASE_STATUS_LABELS: Record<CaseStatus, string> = {
  handover_pending: "Handover pending", returned_to_sales: "Returned to sales", accepted: "Accepted", cancelled: "Cancelled",
};
export const ONBOARDING_LABELS: Record<OnboardingStatus, string> = {
  not_started: "Not started", otp_verification: "OTP verification", documents_pending: "Documents pending", under_review: "Under review",
  clarification_required: "Clarification required", approved: "Approved",
};
export const OWNERSHIP_LABELS: Record<OwnershipType, string> = {
  individual: "Individual", joint: "Joint", company: "Company", partnership: "Partnership firm", huf: "HUF", trust: "Trust", other: "Other entity",
};
export const DOC_LABELS: Record<KycDocType, string> = {
  pan: "PAN card", aadhaar: "Aadhaar", passport: "Passport", voter_id: "Voter ID", driving_licence: "Driving licence", address_proof: "Address proof",
  photo: "Photograph", entity_pan: "Entity PAN", registration_certificate: "Registration certificate / deed", board_resolution: "Board resolution / authority letter", other: "Other",
};

export function useCases(q: { status?: CaseStatus | ""; onboarding?: OnboardingStatus | ""; mine?: boolean }) {
  const params = { status: q.status || undefined, onboarding: q.onboarding || undefined, mine: q.mine || undefined };
  return useQuery({
    queryKey: ["post-sales", "list", params],
    queryFn: async () => (await api.get<{ items: CaseSummary[]; total: number; counts: Record<string, number> }>("/post-sales/cases", { params })).data,
    placeholderData: keepPreviousData,
  });
}
export function useCase(id: number) {
  return useQuery({ queryKey: ["post-sales", id], queryFn: async () => (await api.get<CaseDetail>(`/post-sales/cases/${id}`)).data, enabled: id > 0 });
}
export function useCaseAction(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, body, method = "post" }: { path: string; body?: unknown; method?: "post" | "put" }) =>
      (method === "put" ? await api.put<CaseDetail>(path, body) : await api.post<CaseDetail>(path, body)).data,
    onSuccess: (d) => { if (d && typeof d === "object" && "id" in d) qc.setQueryData(["post-sales", id], d); },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["post-sales"] }),
  });
}
export const kycFileUrl = (docId: number) => `/api/post-sales/kyc/${docId}/file`;
