import { Link } from "react-router";
import { Badge, PageHeader } from "../ui";
import { CASE_STATUS_LABELS, ONBOARDING_LABELS, useCases } from "../../hooks/usePostSales";
import { useFollowUpsDue } from "../../hooks/useFollowUps";
import { useCurrentUser } from "../../hooks/useAuth";
import { LEDGER_VIEWERS } from "../../lib/types";
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
      <FollowUpsDue />
    </>
  );
}

/** Who to call today: follow-ups due, promises due today, broken promises (cases I own or followed up). */
function FollowUpsDue() {
  const me = useCurrentUser();
  const q = useFollowUpsDue(LEDGER_VIEWERS.includes(me.role));
  if (!LEDGER_VIEWERS.includes(me.role)) return null;
  return (
    <section aria-label="Follow-ups due" className="mt-6 rounded-xl bg-white p-4 ring-1 ring-line">
      <h2 className="mb-2 font-semibold">Follow-ups due</h2>
      {q.data && q.data.length === 0 && <p className="text-sm text-muted">Nothing due today.</p>}
      <ul className="divide-y divide-line">
        {q.data?.map((x, i) => (
          <li key={i} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <Link to={`/post-sales/${x.case_id}`} className="font-medium text-forest-900 hover:underline">{x.customer} <span className="font-normal text-muted">({x.case_code})</span></Link>
            <span><Badge tone={x.reason === "Promise broken" ? "gold" : "neutral"}>{x.reason}</Badge> <span className="text-muted">{x.on}{x.amount ? ` · ₹ ${x.amount.toLocaleString("en-IN")}` : ""}</span></span>
          </li>
        ))}
      </ul>
    </section>
  );
}
