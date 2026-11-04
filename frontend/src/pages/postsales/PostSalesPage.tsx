import { useState } from "react";
import { Link } from "react-router";
import { ErrorState, PageHeader, cx } from "../../components/ui";
import { statusBadge } from "../../components/postsales/CaseBits";
import { useCases } from "../../hooks/usePostSales";
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
