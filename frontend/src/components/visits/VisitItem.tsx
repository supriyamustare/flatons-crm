import { Link } from "react-router";
import { CircleAlert, MapPin } from "lucide-react";
import { Badge, Button, cx } from "../ui";
import { formatDue } from "../../lib/tasks";
import { INTEREST_LABELS, VISIT_SOURCE_LABELS, VISIT_STATUS_LABELS } from "../../lib/visits";
import type { Visit } from "../../lib/visits";

export function VisitItem({ visit, canAct, showLead = true, onUpdate }: {
  visit: Visit; canAct: boolean; showLead?: boolean; onUpdate: () => void;
}) {
  const open = visit.status === "scheduled";
  const tone = visit.status === "completed" ? "neutral" : visit.status === "scheduled" ? "gold" : "muted";
  return (
    <li className={cx("rounded-xl border bg-white p-4", visit.needs_update ? "border-gold-300" : "border-line")}>
      <div className="flex items-start gap-3">
        <span aria-hidden className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-forest-50 text-forest-800">
          <MapPin className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <p className="text-sm">
              {showLead ? (
                <Link to={`/leads/${visit.lead.id}`} className="font-medium text-forest-800 hover:underline">{visit.lead.name}</Link>
              ) : <span className="font-medium">Site visit</span>}
              <span className="text-muted"> at {visit.project.name}</span>
            </p>
            <Badge tone={tone}>{VISIT_STATUS_LABELS[visit.status]}</Badge>
          </div>
          <p className="text-sm text-muted">
            {formatDue(visit.scheduled_at)}
            {visit.host && <> · {visit.host.full_name}</>}
            {visit.reschedule_count > 0 && <> · moved {visit.reschedule_count}×</>}
          </p>
          <p className="text-xs text-muted">{VISIT_SOURCE_LABELS[visit.visit_source]}</p>
          {visit.needs_update && (
            <p className="mt-2 flex items-center gap-1.5 text-sm font-medium text-gold-600">
              <CircleAlert className="size-4" aria-hidden /> Time has passed. Record how it went.
            </p>
          )}
          {visit.notes && open && <p className="mt-1.5 text-sm whitespace-pre-wrap">{visit.notes}</p>}
          {visit.feedback && <p className="mt-1.5 rounded-lg bg-paper px-3 py-2 text-sm whitespace-pre-wrap">{visit.feedback}</p>}
          {visit.interest_level && <p className="mt-1 text-xs text-muted">Interest: {INTEREST_LABELS[visit.interest_level]}</p>}
          {visit.next_action && <p className="text-xs text-muted">Next: {visit.next_action}</p>}
          {visit.cancellation_reason && <p className="mt-1 text-sm text-muted">Reason: {visit.cancellation_reason}</p>}
        </div>
      </div>
      {open && canAct && (
        <div className="mt-3 sm:pl-12">
          <Button variant="secondary" onClick={onUpdate} aria-label={`Update visit with ${visit.lead.name}`}>Update visit</Button>
        </div>
      )}
    </li>
  );
}
