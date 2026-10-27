import type { ReactNode } from "react";
import { OUTCOME_LABELS, formatDuration } from "../../lib/calls";
import type { CallOutcome } from "../../lib/calls";
import { FIELD_LABELS, STATUS_LABELS } from "../../lib/leads";
import type { LeadStatus } from "../../lib/leads";
import { formatDue, taskTypeInSentence } from "../../lib/tasks";
import type { TaskType } from "../../lib/tasks";
import { INTEREST_LABELS } from "../../lib/visits";
import type { InterestLevel } from "../../lib/visits";

/** Minimal shape shared by lead timeline entries and dashboard feed items. */
export interface ActivityLike {
  type: string;
  details: Record<string, unknown> | null;
}

/** One-line, human description of a timeline entry. Used on the lead page and the dashboard. */
export function describeActivity(a: ActivityLike): ReactNode {
  const d = a.details ?? {};
  switch (a.type) {
    case "created": {
      const dups = d.possible_duplicates as string[] | undefined;
      return <>Created the lead{dups?.length ? <> (possible duplicate of {dups.join(", ")})</> : null}</>;
    }
    case "status_change":
      return (
        <>
          {d.automatic ? <span className="text-muted">Automatically: </span> : null}
          Changed status from <b>{STATUS_LABELS[d.from as LeadStatus]}</b> to <b>{STATUS_LABELS[d.to as LeadStatus]}</b>
          {d.reason ? <>: {String(d.reason)}</> : null}
        </>
      );
    case "assignment": {
      const to = d.to as { name: string } | null;
      const from = d.from as { name: string } | null;
      if (!to) return <>Unassigned the lead{from ? <> from {from.name}</> : null}</>;
      return from ? <>Reassigned from {from.name} to <b>{to.name}</b></> : <>Assigned to <b>{to.name}</b></>;
    }
    case "updated": {
      const fields = Object.keys((d.changes as Record<string, unknown>) ?? {}).map((k) => FIELD_LABELS[k] ?? k);
      return <>Updated {fields.join(", ")}</>;
    }
    case "note":
      return <>Added a note</>;
    case "call_logged":
      return (
        <>
          {d.direction === "incoming" ? "Took a call" : "Called"}: <b>{OUTCOME_LABELS[d.outcome as CallOutcome]}</b>
          {d.duration_sec ? <> ({formatDuration(Number(d.duration_sec))})</> : null}
        </>
      );
    case "visit_scheduled":
      return <>Scheduled a site visit at {String(d.project)} for <b>{formatDue(String(d.scheduled_at))}</b> ({String(d.host)})</>;
    case "visit_completed":
      return <>Site visit done at {String(d.project)}: <b>{INTEREST_LABELS[d.interest_level as InterestLevel].split(":")[0]}</b></>;
    case "visit_rescheduled":
      return <>Moved the site visit to <b>{formatDue(String(d.to))}</b></>;
    case "visit_no_show":
      return <>Customer didn’t come for the site visit</>;
    case "visit_cancelled":
      return <>Cancelled the site visit</>;
    case "task_created":
      return <>Planned a <b>{taskTypeInSentence(d.task_type as TaskType)}</b> for {formatDue(String(d.due_at))}{d.assigned_to ? <> ({String(d.assigned_to)})</> : null}</>;
    case "task_completed":
      return <>Completed a {taskTypeInSentence(d.task_type as TaskType)}{d.was_overdue ? " (late)" : ""}</>;
    case "task_rescheduled":
      return <>Moved a {taskTypeInSentence(d.task_type as TaskType)} from {formatDue(String(d.from))} to <b>{formatDue(String(d.to))}</b></>;
    default:
      return a.type;
  }
}
