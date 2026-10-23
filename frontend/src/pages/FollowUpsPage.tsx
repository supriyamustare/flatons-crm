import { useState } from "react";
import { Plus } from "lucide-react";
import { LogCallDialog } from "../components/calls/LogCallDialog";
import { CompleteTaskDialog, NewTaskDialog, RescheduleDialog } from "../components/tasks/TaskDialogs";
import { TaskItem } from "../components/tasks/TaskItem";
import { Button, ErrorState, PageHeader, SelectInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useAssignableUsers } from "../hooks/useLeads";
import { useTasks } from "../hooks/useTasks";
import type { TaskQuery } from "../hooks/useTasks";
import { errorMessage } from "../lib/api";
import { TASK_TYPES, TASK_TYPE_LABELS, VIEW_LABELS } from "../lib/tasks";
import type { Task, TaskType, TaskView } from "../lib/tasks";

const VIEWS: TaskView[] = ["today", "overdue", "upcoming", "completed"];

const EMPTY_MESSAGES: Record<TaskView, string> = {
  today: "Nothing due today.",
  overdue: "Nothing overdue. Nicely done.",
  upcoming: "No follow-ups planned after today.",
  completed: "Completed follow-ups will appear here.",
};

export function FollowUpsPage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const people = useAssignableUsers(isManager);

  const [view, setView] = useState<TaskView>("today");
  const [type, setType] = useState<TaskType | "">("");
  // Managers: "" = everyone, "me" = mine, or a person's id
  const [person, setPerson] = useState(isManager ? "" : "me");
  const [page, setPage] = useState(1);
  const [dialog, setDialog] = useState<{ kind: "new" } | { kind: "done" | "move" | "call"; task: Task } | null>(null);

  const query: TaskQuery = {
    view, page,
    task_type: type || undefined,
    mine: person === "me" || undefined,
    assigned_to_id: person && person !== "me" ? Number(person) : undefined,
  };
  const tasks = useTasks(query);
  const counts = tasks.data?.counts;
  const total = tasks.data?.total ?? 0;
  const pageSize = tasks.data?.page_size ?? 50;

  const changeView = (v: TaskView) => { setView(v); setPage(1); };

  return (
    <>
      <PageHeader
        title="Follow-ups"
        description={isManager ? undefined : "Your calls, visits and reminders"}
        action={<Button onClick={() => setDialog({ kind: "new" })}><Plus className="size-4" aria-hidden />New follow-up</Button>}
      />

      <div role="tablist" aria-label="Follow-up views" className="mb-4 flex gap-1 rounded-xl bg-white p-1 ring-1 ring-line">
        {VIEWS.map((v) => {
          const n = v === "completed" ? undefined : counts?.[v];
          return (
            <button key={v} role="tab" aria-selected={view === v} onClick={() => changeView(v)}
              aria-label={n ? `${VIEW_LABELS[v]}, ${n}` : VIEW_LABELS[v]}
              className={cx("flex min-h-11 flex-auto items-center justify-center gap-1 rounded-lg px-2 text-[13px] whitespace-nowrap sm:flex-1 sm:gap-1.5 sm:px-3 sm:text-sm",
                view === v ? "bg-forest-900 text-white" : "text-ink hover:bg-forest-50")}>
              {v === "completed" ? (
                <><span className="sm:hidden">Done</span><span className="hidden sm:inline">Completed</span></>
              ) : VIEW_LABELS[v]}
              {n !== undefined && n > 0 && (
                <span aria-hidden className={cx("rounded-full px-1.5 text-xs font-semibold",
                  v === "overdue" ? "bg-danger text-white" : view === v ? "bg-white/20" : "bg-forest-50 text-forest-800")}>
                  {n}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:max-w-xl">
        <SelectInput label="Type" value={type} onChange={(e) => { setType(e.target.value as TaskType | ""); setPage(1); }}>
          <option value="">All types</option>
          {TASK_TYPES.map((t) => <option key={t} value={t}>{TASK_TYPE_LABELS[t]}</option>)}
        </SelectInput>
        {isManager && (
          <SelectInput label="Whose" value={person} onChange={(e) => { setPerson(e.target.value); setPage(1); }}>
            <option value="">Everyone</option>
            <option value="me">Mine</option>
            {people.data?.filter((p) => p.id !== me.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </SelectInput>
        )}
      </div>

      {tasks.isPending && (
        <div className="space-y-2" aria-busy="true" aria-label="Loading follow-ups">
          {[0, 1, 2].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-white" />)}
        </div>
      )}
      {tasks.isError && <ErrorState message={errorMessage(tasks.error, "Couldn’t load follow-ups.")} onRetry={() => void tasks.refetch()} />}

      {tasks.isSuccess && total === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <p className="font-display text-xl text-forest-900">{EMPTY_MESSAGES[view]}</p>
          {view !== "completed" && (
            <p className="mt-1 text-sm text-muted">Add a follow-up from any lead, or with New follow-up above.</p>
          )}
        </div>
      )}

      {tasks.isSuccess && total > 0 && (
        <div className={tasks.isPlaceholderData ? "opacity-60" : ""}>
          <ul className="space-y-2">
            {tasks.data.items.map((t) => (
              <TaskItem key={t.id} task={t} showAssignee={isManager && person !== "me"}
                canAct={isManager || t.assigned_to?.id === me.id}
                onComplete={() => setDialog({ kind: "done", task: t })}
                onReschedule={() => setDialog({ kind: "move", task: t })}
                onCall={() => setDialog({ kind: "call", task: t })} />
            ))}
          </ul>
          {total > pageSize && (
            <div className="mt-4 flex items-center justify-between text-sm text-muted">
              <span>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}</span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
                <Button variant="secondary" disabled={page * pageSize >= total} onClick={() => setPage(page + 1)}>Next</Button>
              </div>
            </div>
          )}
        </div>
      )}

      {dialog?.kind === "new" && <NewTaskDialog onClose={() => setDialog(null)} />}
      {dialog?.kind === "done" && <CompleteTaskDialog task={dialog.task} onClose={() => setDialog(null)} />}
      {dialog?.kind === "move" && <RescheduleDialog task={dialog.task} onClose={() => setDialog(null)} />}
      {dialog?.kind === "call" && <LogCallDialog lead={dialog.task.lead} task={dialog.task} onClose={() => setDialog(null)} />}
    </>
  );
}
