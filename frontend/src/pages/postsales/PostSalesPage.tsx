import { useState } from "react";
import { Link } from "react-router";
import { Badge, ErrorState, PageHeader, cx } from "../../components/ui";
import { CASE_STATUS_LABELS, ONBOARDING_LABELS, useCases } from "../../hooks/usePostSales";
import type { CaseStatus, OnboardingStatus } from "../../hooks/usePostSales";
import { formatRupees } from "../../lib/leads";

const TILES: { label: string; status?: CaseStatus; onboarding?: OnboardingStatus; key: string }[] = [
  { label: "Handover pending", status: "handover_pending", key: "status:handover_pending" },
  { label: "Returned to sales", status: "returned_to_sales", key: "status:returned_to_sales" },
  { label: "Documents pending", status: "accepted", onboarding: "documents_pending", key: "onboarding:documents_pending" },
  { label: "Under review", status: "accepted", onboarding: "under_review", key: "onboarding:under_review" },
  { label: "Clarification required", status: "accepted", onboarding: "clarification_required", key: "onboarding:clarification_required" },
  { label: "KYC approved", status: "accepted", onboarding: "approved", key: "onboarding:approved" },
];

export function statusBadge(c: { status: CaseStatus; onboarding_status: OnboardingStatus }) {
  if (c.status !== "accepted") return <Badge tone={c.status === "handover_pending" ? "gold" : "muted"}>{CASE_STATUS_LABELS[c.status]}</Badge>;
  return <Badge tone={c.onboarding_status === "approved" ? "neutral" : c.onboarding_status === "clarification_required" ? "gold" : "muted"}>{ONBOARDING_LABELS[c.onboarding_status]}</Badge>;
}

export function PostSalesPage() {
  const [filter, setFilter] = useState<{ status?: CaseStatus; onboarding?: OnboardingStatus } | null>(null);
  const [mine, setMine] = useState(false);
  const all = useCases({ mine });
  const list = useCases({ ...(filter ?? {}), mine });
  const counts = all.data?.counts ?? {};
  return (
    <>
      <PageHeader title="Post-sales" description="Every booking handed over from sales: handover, customer details and KYC." />
      <section aria-label="Cases by stage" className="mb-5 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
        {TILES.map((t) => {
          const active = filter?.status === t.status && filter?.onboarding === t.onboarding;
          return (
            <button key={t.key} type="button" aria-pressed={active} onClick={() => setFilter(active ? null : { status: t.status, onboarding: t.onboarding })}
              className={cx("rounded-xl p-3 text-left ring-1 transition", active ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line hover:ring-forest-700")}>
              <span className={cx("block text-xs", active ? "text-forest-100" : "text-muted")}>{t.label}</span>
              <span className="font-display text-2xl tabular-nums">{counts[t.key] ?? 0}</span>
            </button>
          );
        })}
      </section>
      <label className="mb-3 flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={mine} onChange={(e) => setMine(e.target.checked)} />Only cases assigned to me</label>
      {list.isError && <ErrorState message="Couldn’t load cases." onRetry={() => void list.refetch()} />}
      {list.data && list.data.items.length === 0 && <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">No cases here.</p>}
      {list.data && list.data.items.length > 0 && (
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
          <table className="w-full min-w-[760px] text-sm">
            <caption className="sr-only">Post-sales cases</caption>
            <thead className="text-xs text-muted"><tr>{["Case", "Customer", "Unit", "Agreed price", "Stage", "KYC", "Owner"].map((h) => <th key={h} scope="col" className="px-4 py-2 text-left font-normal">{h}</th>)}</tr></thead>
            <tbody>{list.data.items.map((c) => (
              <tr key={c.id} className="border-t border-line">
                <th scope="row" className="px-4 py-3 text-left font-normal"><Link to={`/post-sales/${c.id}`} className="font-medium text-forest-900 hover:underline">{c.case_code}</Link>
                  <span className="block text-xs text-muted">{c.booking_code}</span></th>
                <td className="px-4 py-3">{c.customer}</td>
                <td className="px-4 py-3">{c.project}<span className="block text-xs text-muted">Unit {c.unit_no}</span></td>
                <td className="px-4 py-3 tabular-nums">{formatRupees(c.agreed_price)}</td>
                <td className="px-4 py-3">{statusBadge(c)}</td>
                <td className="px-4 py-3 tabular-nums">{c.kyc_total ? `${c.kyc_done}/${c.kyc_total}` : "—"}</td>
                <td className="px-4 py-3">{c.owner?.full_name ?? <span className="text-gold-600">Unassigned</span>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </>
  );
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
