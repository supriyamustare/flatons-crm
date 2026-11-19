import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { UserBrief } from "../lib/types";

export interface CalItem {
  id: string; source: "appointment" | "agreement" | "sales_visit"; kind: string; label: string; title: string; customer: string; case_code: string | null;
  starts_at: string; duration_min: number; location: string | null; status: string; confirmed: boolean; owner: string | null; link: string;
}
export interface Apt {
  id: number; apt_no: string; kind: string; label: string; title: string | null; starts_at: string; duration_min: number; location: string | null; owner: UserBrief | null;
  required_docs: string | null; notes: string | null; status: "scheduled" | "attended" | "no_show" | "cancelled" | "rescheduled"; status_reason: string | null;
  confirmed_on: string | null; confirmed_via: string | null; outcome: string | null; follow_up_on: string | null; rescheduled_from: string | null; can_act: boolean;
}
export interface CaseApts { items: Apt[]; owners: UserBrief[]; can_schedule: boolean; kinds: Record<string, string> }
export const STATUS: Record<string, string> = { scheduled: "Scheduled", attended: "Attended", no_show: "Missed", cancelled: "Cancelled", rescheduled: "Rescheduled", completed: "Done" };

export function useCalendar(start: string, days: number, mine: boolean) {
  return useQuery({ queryKey: ["calendar", start, days, mine], queryFn: async () => (await api.get<CalItem[]>("/calendar", { params: { start, days, mine } })).data });
}
export function useCaseApts(caseId: number) {
  return useQuery({ queryKey: ["appointments", caseId], queryFn: async () => (await api.get<CaseApts>(`/post-sales/cases/${caseId}/appointments`)).data });
}
export function useAptAction(caseId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ path, body }: { path: string; body?: unknown }) => (await api.post<CaseApts>(path, body)).data,
    onSuccess: (d) => { qc.setQueryData(["appointments", caseId], d); void qc.invalidateQueries({ queryKey: ["calendar"] }); void qc.invalidateQueries({ queryKey: ["follow-ups-due"] }); },
  });
}
/** Local date-time input value (Asia/Kolkata) -> ISO with +05:30 */
export const istIso = (local: string) => new Date(local + ":00+05:30").toISOString();
export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "Asia/Kolkata" });
export const fmtDay = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" });
