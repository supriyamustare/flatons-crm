import { Link } from "react-router";
import { Badge, PageHeader } from "../ui";
import { CASE_STATUS_LABELS, ONBOARDING_LABELS, useCases } from "../../hooks/usePostSales";
import type { CaseStatus, OnboardingStatus } from "../../hooks/usePostSales";

/** Shared by the post-sales list, the case page and the dashboard (kept apart so the list page loads on its own). */
export function statusBadge(c: { status: CaseStatus; onboarding_status: OnboardingStatus }) {
  if (c.status !== "accepted") return <Badge tone={c.status === "handover_pending" ? "gold" : "muted"}>{CASE_STATUS_LABELS[c.status]}</Badge>;
  return <Badge tone={c.onboarding_status === "approved" ? "neutral" : c.onboarding_status === "clarification_required" ? "gold" : "muted"}>{ONBOARDING_LABELS[c.onboarding_status]}</Badge>;
}

/** Dashboard for post-sales staff. */
export function PostSalesHome({ name }: { name: string }) {
  const all = useCases({});
  const mine = useCases({ mine: true });
  const c = all.data?.counts ?? {};
  return (
    <>
      <PageHeader title={`Hello, ${name}`} description="Post-sales at a glance" />
      <section aria-label="Post-sales at a glance" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[["Handover pending", c["status:handover_pending"]], ["Under review", c["onboarding:under_review"]], ["Clarification required", c["onboarding:clarification_required"]], ["Assigned to me", mine.data?.total]]
          .map(([label, n]) => (
            <Link key={String(label)} to="/post-sales" className="rounded-xl bg-white p-4 ring-1 ring-line hover:ring-forest-700">
              <p className="text-sm text-muted">{label}</p><p className="font-display text-3xl text-forest-900 tabular-nums">{n ?? 0}</p>
            </Link>))}
      </section>
      <p className="mt-6 text-sm text-muted">Ledger, demands, agreements and the customer portal arrive in the coming post-sales sprints.</p>
    </>
  );
}
