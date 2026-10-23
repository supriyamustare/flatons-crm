import { Link } from "react-router";
import { TriangleAlert } from "lucide-react";
import { Badge } from "../ui";
import { STATUS_LABELS, statusTone } from "../../lib/leads";
import type { Duplicate, LeadStatus } from "../../lib/leads";

export function StatusBadge({ status }: { status: LeadStatus }) {
  return <Badge tone={statusTone(status)}>{STATUS_LABELS[status]}</Badge>;
}

export function DuplicateBanner({ duplicates }: { duplicates: Duplicate[] }) {
  if (duplicates.length === 0) return null;
  return (
    <div role="alert" className="rounded-lg border border-gold-300 bg-gold-100 px-4 py-3 text-sm text-ink">
      <p className="flex items-center gap-2 font-medium">
        <TriangleAlert className="size-4 text-gold-600" aria-hidden />
        {duplicates.length === 1 ? "This may be an existing lead" : "This may match existing leads"}
      </p>
      <ul className="mt-2 space-y-1">
        {duplicates.map((d) => (
          <li key={d.id}>
            {d.can_view ? (
              <Link to={`/leads/${d.id}`} className="font-medium text-forest-800 underline">
                {d.lead_code}
              </Link>
            ) : (
              <span className="font-medium">{d.lead_code}</span>
            )}{" "}
            {d.name}, {STATUS_LABELS[d.status].toLowerCase()}
            {d.assigned_to_name ? `, with ${d.assigned_to_name}` : ", unassigned"} (same{" "}
            {d.matched_on.join(" and ")})
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-muted">You can still save. Check with the owner first to avoid calling the same customer twice.</p>
    </div>
  );
}
