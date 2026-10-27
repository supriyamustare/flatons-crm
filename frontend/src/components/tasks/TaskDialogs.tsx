import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Search } from "lucide-react";
import { Alert, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useAssignableUsers, useLeadSearch } from "../../hooks/useLeads";
import { useCompleteTask, useCreateTask, useRescheduleTask } from "../../hooks/useTasks";
import { errorMessage } from "../../lib/api";
import { EMPTY_FILTERS, formatMobile } from "../../lib/leads";
import { TASK_TYPES, TASK_TYPE_LABELS, duePresets, formatDue, localInputToIso, toLocalInput, taskTypeInSentence } from "../../lib/tasks";
import type { Task, TaskType } from "../../lib/tasks";

export interface LeadRef {
  id: number;
  name: string;
  assigned_to_id?: number | null;
  project_id?: number | null;
}

function Actions({ onCancel, submitLabel, loading, disabled }: {
  onCancel: () => void; submitLabel: string; loading: boolean; disabled: boolean;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      <Button type="submit" loading={loading} disabled={disabled}>{submitLabel}</Button>
    </div>
  );
}

/** Date and time with one-tap presets. Times are the user's own (India) time. */
export function DueTimeField({ value, onChange, label = "When" }: { value: string; onChange: (v: string) => void; label?: string }) {
  const presets = duePresets();
  return (
    <div className="space-y-2">
      <TextInput label={label} type="datetime-local" value={value} min={toLocalInput(new Date())}
        onChange={(e) => onChange(e.target.value)} required />
      <div className="flex flex-wrap gap-2" role="group" aria-label="Quick times">
        {presets.map((p) => {
          const v = toLocalInput(p.value);
          return (
            <button key={p.label} type="button" onClick={() => onChange(v)} aria-pressed={value === v}
              className={cx("min-h-9 rounded-full px-3 text-sm ring-1",
                value === v ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line hover:bg-forest-50")}>
              {p.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Pick a lead by name, phone or lead ID (only leads you can see). */
export function LeadPicker({ onPick }: { onPick: (lead: LeadRef) => void }) {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const results = useLeadSearch({
    ...EMPTY_FILTERS, q: debounced || undefined, sort: "last_activity_at", order: "desc", page: 1, page_size: 6,
  });
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium" htmlFor="lead-picker">Lead</label>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <input id="lead-picker" type="search" autoFocus value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Name, phone or lead ID"
          className="block min-h-11 w-full rounded-lg border border-line bg-white pr-3 pl-9 text-base focus:border-forest-700 focus:ring-2 focus:ring-forest-700/20 focus:outline-none md:text-sm" />
      </div>
      <ul className="divide-y divide-line rounded-lg border border-line" aria-label="Matching leads">
        {results.data?.items.map((l) => (
          <li key={l.id}>
            <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left hover:bg-paper"
              onClick={() => onPick({ id: l.id, name: l.name, assigned_to_id: l.assigned_to?.id, project_id: l.project?.id })}>
              <span className="min-w-0 truncate font-medium">{l.name}</span>
              <span className="shrink-0 text-xs text-muted">{formatMobile(l.mobile)}</span>
            </button>
          </li>
        ))}
        {results.isSuccess && results.data.items.length === 0 && (
          <li className="px-3 py-3 text-sm text-muted">No matching leads</li>
        )}
      </ul>
    </div>
  );
}

export function NewTaskDialog({ lead: fixedLead, onClose }: { lead?: LeadRef; onClose: () => void }) {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const create = useCreateTask();
  const people = useAssignableUsers(isManager);
  const [lead, setLead] = useState<LeadRef | null>(fixedLead ?? null);
  const [type, setType] = useState<TaskType>("call");
  const [due, setDue] = useState(() => toLocalInput(duePresets()[1].value));
  const [notes, setNotes] = useState("");
  const [assignee, setAssignee] = useState("");

  useEffect(() => {
    if (isManager && lead && !assignee) setAssignee(String(lead.assigned_to_id ?? me.id));
  }, [isManager, lead, assignee, me.id]);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!lead) return;
    create.mutate(
      {
        lead_id: lead.id, task_type: type, due_at: localInputToIso(due), notes: notes.trim() || undefined,
        assigned_to_id: isManager && assignee ? Number(assignee) : undefined,
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal title={lead ? `Follow-up with ${lead.name}` : "New follow-up"} onClose={onClose}>
      {!lead ? (
        <LeadPicker onPick={setLead} />
      ) : (
        <form onSubmit={submit} className="space-y-4" noValidate>
          {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
          {!fixedLead && (
            <p className="text-sm">
              Lead: <b>{lead.name}</b>{" "}
              <button type="button" className="text-forest-700 underline" onClick={() => setLead(null)}>Change</button>
            </p>
          )}
          <div className="space-y-2">
            <span className="block text-sm font-medium" id="task-type-label">Type</span>
            <div className="flex flex-wrap gap-2" role="group" aria-labelledby="task-type-label">
              {TASK_TYPES.map((t) => (
                <button key={t} type="button" aria-pressed={type === t} onClick={() => setType(t)}
                  className={cx("min-h-9 rounded-full px-3 text-sm ring-1",
                    type === t ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line hover:bg-forest-50")}>
                  {TASK_TYPE_LABELS[t]}
                </button>
              ))}
            </div>
          </div>
          <DueTimeField value={due} onChange={setDue} />
          <TextArea label="What to do (optional)" value={notes} onChange={(e) => setNotes(e.target.value)}
            placeholder="e.g. Share the price sheet and confirm Sunday visit" maxLength={5000} />
          {isManager && (
            <SelectInput label="Assign to" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
              <option value={me.id}>Me ({me.full_name})</option>
              {people.data?.filter((p) => p.id !== me.id).map((p) => (
                <option key={p.id} value={p.id}>{p.full_name}</option>
              ))}
            </SelectInput>
          )}
          <Actions onCancel={onClose} submitLabel="Add follow-up" loading={create.isPending} disabled={!due} />
        </form>
      )}
    </Modal>
  );
}

export function CompleteTaskDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const complete = useCompleteTask();
  const [note, setNote] = useState("");
  return (
    <Modal title={`Complete ${taskTypeInSentence(task.task_type)} with ${task.lead.name}`} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e) => {
        e.preventDefault();
        complete.mutate({ id: task.id, completion_note: note.trim() }, { onSuccess: onClose });
      }}>
        {complete.isError && <Alert>{errorMessage(complete.error)}</Alert>}
        <TextArea label="What happened?" value={note} onChange={(e) => setNote(e.target.value)} autoFocus rows={4}
          placeholder="e.g. Interested in 2 BHK, visiting on Sunday" maxLength={5000} required />
        <p className="text-xs text-muted">This is saved to the lead’s timeline. Need another follow-up? Add it from the lead.</p>
        <Actions onCancel={onClose} submitLabel="Mark done" loading={complete.isPending} disabled={!note.trim()} />
      </form>
    </Modal>
  );
}

export function RescheduleDialog({ task, onClose }: { task: Task; onClose: () => void }) {
  const reschedule = useRescheduleTask();
  const [due, setDue] = useState(() => toLocalInput(duePresets()[1].value));
  const [reason, setReason] = useState("");
  return (
    <Modal title={`Reschedule ${taskTypeInSentence(task.task_type)} with ${task.lead.name}`} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e) => {
        e.preventDefault();
        reschedule.mutate({ id: task.id, due_at: localInputToIso(due), reason: reason.trim() }, { onSuccess: onClose });
      }}>
        {reschedule.isError && <Alert>{errorMessage(reschedule.error)}</Alert>}
        <p className="text-sm text-muted">Currently due {formatDue(task.due_at)}</p>
        <DueTimeField label="New time" value={due} onChange={setDue} />
        <TextInput label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)}
          placeholder="e.g. Customer travelling until Friday" maxLength={255} />
        <Actions onCancel={onClose} submitLabel="Reschedule" loading={reschedule.isPending} disabled={!due} />
      </form>
    </Modal>
  );
}
