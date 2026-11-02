import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { Alert, Badge, Button } from "../ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { CASE_STATUS_LABELS, ONBOARDING_LABELS } from "../../hooks/usePostSales";
import type { CaseStatus, OnboardingStatus } from "../../hooks/usePostSales";
import { api, errorMessage } from "../../lib/api";
import { POSTSALES_ROLES } from "../../lib/types";

interface Summary { id: number; case_code: string; status: CaseStatus; onboarding_status: OnboardingStatus; returned_reason: string | null }

/** On a booking: where it is in post-sales; sales can resend a returned handover. */
export function PostSalesStatus({ bookingId, salesExecId }: { bookingId: number; salesExecId: number | null }) {
  const me = useCurrentUser();
  const qc = useQueryClient();
  const allowed = ["manager", "executive", ...POSTSALES_ROLES].includes(me.role);
  const q = useQuery({
    queryKey: ["post-sales", "by-booking", bookingId],
    queryFn: async () => (await api.get<Summary>(`/post-sales/by-booking/${bookingId}`)).data,
    enabled: allowed, retry: false,
  });
  const resend = useMutation({
    mutationFn: async (id: number) => { await api.post(`/post-sales/cases/${id}/resend`); },
    onSettled: () => void qc.invalidateQueries({ queryKey: ["post-sales"] }),
  });
  const s = q.data;
  if (!s) return null;
  const canResend = s.status === "returned_to_sales" && (me.role === "admin" || me.role === "manager" || (me.role === "executive" && salesExecId === me.id));
  return (
    <section aria-label="Post-sales" className="mt-4 rounded-xl bg-white p-5 ring-1 ring-line">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">Post-sales</h2>
        <span className="flex items-center gap-2 text-sm">
          <Badge tone={s.status === "returned_to_sales" ? "gold" : "neutral"}>{CASE_STATUS_LABELS[s.status]}</Badge>
          {s.status === "accepted" && <span className="text-muted">KYC: {ONBOARDING_LABELS[s.onboarding_status]}</span>}
          {POSTSALES_ROLES.includes(me.role) && <Link to={`/post-sales/${s.id}`} className="text-forest-800 underline">{s.case_code}</Link>}
        </span>
      </div>
      {s.status === "returned_to_sales" && (
        <div className="mt-3 space-y-2">
          <Alert>Returned by post-sales: {s.returned_reason}</Alert>
          {resend.isError && <Alert>{errorMessage(resend.error)}</Alert>}
          {canResend && <Button loading={resend.isPending} onClick={() => resend.mutate(s.id)}>I’ve fixed it: resend to post-sales</Button>}
        </div>
      )}
    </section>
  );
}
