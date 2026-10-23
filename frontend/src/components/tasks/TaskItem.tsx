import { Link } from "react-router";
import { CalendarClock, Check, Phone } from "lucide-react";
import { Button, cx } from "../ui";
import { formatDateTime } from "../../lib/api";
import { formatMobile } from "../../lib/leads";
import { TASK_TYPE_ICONS, TASK_TYPE_LABELS, formatDue } from "../../lib/tasks";
import type { Task } from "../../lib/tasks";

export function TaskItem({
  task, canAct, showLead = true, showAssignee = false, onComplete, onReschedule,
}: {
  task: Task; canAct: boolean; showLead?: boolean; showAssignee?: boolean;
  onComplete: () => void; onReschedule: () => void;
}) {
  const Icon = TASK_TYPE_ICONS[task.task_type];
  const open = task.status === "pending";
  const label = `${TASK_TYPE_LABELS[task.task_type]} with ${task.lead.name}`;
  return (
    <li className={cx("rounded-xl border bg-white p-4", task.is_overdue ? "border-danger/40 bg-danger-soft/40" : "border-line")}>
      <div className="flex items-start gap-3">
        <span aria-hidden className={cx("mt-0.5 grid size-9 shrink-0 place-items-center rounded-full",
          task.is_overdue ? "bg-danger-soft text-danger" : "bg-forest-50 text-forest-800")}>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm">
            <span className="font-medium">{TASK_TYPE_LABELS[task.task_type]}</span>
            {showLead && (
              <> with <Link to={`/leads/${task.lead.id}`} className="font-medium text-forest-800 underline-offset-2 hover:underline">{task.lead.name}</Link></>
            )}
          </p>
          <p className={cx("text-sm", task.is_overdue ? "font-medium text-danger" : "text-muted")}>
            {open ? <>{task.is_overdue && "Overdue · "}{formatDue(task.due_at)}</>
              : task.status === "completed" ? <>Done {task.completed_at ? formatDateTime(task.completed_at) : ""}</>
              : task.status === "rescheduled" ? <>Rescheduled (was {formatDue(task.due_at)})</> : "Cancelled"}
            {showAssignee && task.assigned_to && <> · {task.assigned_to.full_name}</>}
          </p>
          {task.reschedule_reason && open && <p className="mt-1 text-xs text-muted">Moved: {task.reschedule_reason}</p>}
          {task.notes && <p className="mt-1.5 text-sm whitespace-pre-wrap text-ink">{task.notes}</p>}
          {task.completion_note && (
            <p className="mt-1.5 rounded-lg bg-paper px-3 py-2 text-sm whitespace-pre-wrap">{task.completion_note}</p>
          )}
        </div>
      </div>
      {open && (
        <div className="mt-3 flex flex-wrap gap-2 sm:pl-12">
          <a href={`tel:${task.lead.mobile}`} aria-label={`Call ${task.lead.name} on ${formatMobile(task.lead.mobile)}`}
            className="inline-flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm font-medium text-forest-800 ring-1 ring-line hover:bg-forest-50">
            <Phone className="size-4" aria-hidden /> Call
          </a>
          {canAct && (
            <>
              <Button variant="secondary" onClick={onComplete} aria-label={`Mark ${label} as done`}><Check className="size-4" aria-hidden />Done</Button>
              <Button variant="ghost" onClick={onReschedule} aria-label={`Reschedule ${label}`}><CalendarClock className="size-4" aria-hidden />Reschedule</Button>
            </>
          )}
        </div>
      )}
    </li>
  );
}
