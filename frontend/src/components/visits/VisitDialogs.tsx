import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../ui";
import { DueTimeField } from "../tasks/TaskDialogs";
import { useCurrentUser } from "../../hooks/useAuth";
import { useAssignableUsers, useProjects } from "../../hooks/useLeads";
import { useScheduleVisit, useVisitAction } from "../../hooks/useVisits";
import type { VisitAction } from "../../hooks/useVisits";
import { errorMessage } from "../../lib/api";
import { TASK_TYPES, TASK_TYPE_LABELS, duePresets, formatDue, localInputToIso, toLocalInput } from "../../lib/tasks";
import type { TaskType } from "../../lib/tasks";
import { INTEREST_LABELS, VISIT_SOURCES, VISIT_SOURCE_LABELS, visitDayReached } from "../../lib/visits";
import type { InterestLevel, Visit, VisitSource } from "../../lib/visits";

function Actions({ onCancel, submitLabel, loading, disabled, danger = false }: {
  onCancel: () => void; submitLabel: string; loading: boolean; disabled: boolean; danger?: boolean;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onCancel}>Back</Button>
      <Button type="submit" variant={danger ? "danger" : "primary"} loading={loading} disabled={disabled}>{submitLabel}</Button>
    </div>
  );
}

export function ScheduleVisitDialog({ lead, onClose }: {
  lead: { id: number; name: string; project_id?: number | null; assigned_to_id?: number | null };
  onClose: () => void;
}) {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const projects = useProjects();
  const people = useAssignableUsers(isManager);
  const schedule = useScheduleVisit();
  const [projectId, setProjectId] = useState(lead.project_id ? String(lead.project_id) : "");
  const [when, setWhen] = useState(() => toLocalInput(duePresets()[1].value));
  const [source, setSource] = useState<VisitSource>("sales_follow_up");
  const [notes, setNotes] = useState("");
  const [host, setHost] = useState(String(lead.assigned_to_id ?? me.id));

  function submit(e: FormEvent) {
    e.preventDefault();
    schedule.mutate(
      {
        lead_id: lead.id, project_id: Number(projectId), scheduled_at: localInputToIso(when),
        visit_source: source, notes: notes.trim() || undefined,
        host_id: isManager ? Number(host) : undefined,
      },
      { onSuccess: onClose },
    );
  }

  const noProjects = projects.isSuccess && projects.data.length === 0;
  return (
    <Modal title={`Site visit for ${lead.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {schedule.isError && <Alert>{errorMessage(schedule.error)}</Alert>}
        {noProjects && <Alert>No projects yet. An admin needs to add one under Projects first.</Alert>}
        <SelectInput label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)} required>
          <option value="" disabled>Choose a project</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        <DueTimeField label="Date and time" value={when} onChange={setWhen} />
        <SelectInput label="How this visit came about" value={source} onChange={(e) => setSource(e.target.value as VisitSource)}>
          {VISIT_SOURCES.map((s) => <option key={s} value={s}>{VISIT_SOURCE_LABELS[s]}</option>)}
        </SelectInput>
        {isManager && (
          <SelectInput label="Who will show the site" value={host} onChange={(e) => setHost(e.target.value)}>
            <option value={me.id}>Me ({me.full_name})</option>
            {people.data?.filter((p) => p.id !== me.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </SelectInput>
        )}
        <TextArea label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder="e.g. Coming with parents, wants to see sample flat" maxLength={5000} />
        <Actions onCancel={onClose} submitLabel="Schedule visit" loading={schedule.isPending} disabled={!projectId || !when} />
      </form>
    </Modal>
  );
}

type Mode = "complete" | "no-show" | "reschedule" | "cancel";
const MODE_LABELS: Record<Mode, string> = {
  complete: "It happened",
  "no-show": "They didn’t come",
  reschedule: "Change date",
  cancel: "Cancel visit",
};

export function VisitOutcomeDialog({ visit, onClose }: { visit: Visit; onClose: () => void }) {
  const action = useVisitAction();
  const dayReached = visitDayReached(visit.scheduled_at);
  const [mode, setMode] = useState<Mode>(dayReached ? "complete" : "reschedule");
  const [feedback, setFeedback] = useState("");
  const [interest, setInterest] = useState<InterestLevel | null>(null);
  const [nextAction, setNextAction] = useState("");
  const [nextOn, setNextOn] = useState(true);
  const [nextAt, setNextAt] = useState(() => toLocalInput(duePresets()[1].value));
  const [nextType, setNextType] = useState<TaskType>("call");
  const [when, setWhen] = useState(() => toLocalInput(duePresets()[2].value));
  const [text, setText] = useState("");

  function submit(e: FormEvent) {
    e.preventDefault();
    let a: VisitAction;
    if (mode === "complete") {
      if (!interest) return;
      a = {
        kind: "complete", feedback: feedback.trim(), interest_level: interest,
        next_action: nextAction.trim() || undefined,
        follow_up_at: nextOn ? localInputToIso(nextAt) : undefined, follow_up_type: nextOn ? nextType : undefined,
      };
    } else if (mode === "reschedule") a = { kind: "reschedule", scheduled_at: localInputToIso(when), reason: text.trim() || undefined };
    else if (mode === "no-show") a = { kind: "no-show", note: text.trim() || undefined };
    else a = { kind: "cancel", reason: text.trim() };
    action.mutate({ id: visit.id, action: a }, { onSuccess: onClose });
  }

  const modes: Mode[] = ["complete", "no-show", "reschedule", "cancel"];
  return (
    <Modal title={`Visit: ${visit.lead.name}`} onClose={onClose}>
      <p className="-mt-3 mb-4 text-sm text-muted">{visit.project.name}, {formatDue(visit.scheduled_at)}</p>
      <div className="mb-5 grid grid-cols-2 gap-2" role="group" aria-label="What happened">
        {modes.map((m) => {
          const locked = (m === "complete" || m === "no-show") && !dayReached;
          return (
            <button key={m} type="button" aria-pressed={mode === m} disabled={locked} onClick={() => { setMode(m); setText(""); }}
              className={cx("min-h-11 rounded-lg px-3 text-sm ring-1 disabled:cursor-not-allowed disabled:opacity-40",
                mode === m ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line hover:bg-forest-50")}>
              {MODE_LABELS[m]}
            </button>
          );
        })}
      </div>
      {!dayReached && <p className="mb-4 text-xs text-muted">You can record how it went from the day of the visit.</p>}

      <form onSubmit={submit} className="space-y-4" noValidate>
        {action.isError && <Alert>{errorMessage(action.error)}</Alert>}
        {mode === "complete" && (
          <>
            <TextArea label="How did it go?" value={feedback} onChange={(e) => setFeedback(e.target.value)} rows={3} autoFocus
              placeholder="e.g. Liked the 12th floor 2 BHK, worried about parking" maxLength={5000} required />
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">Interest</legend>
              <div className="grid gap-2">
                {(Object.keys(INTEREST_LABELS) as InterestLevel[]).map((i) => (
                  <button key={i} type="button" aria-pressed={interest === i} onClick={() => setInterest(i)}
                    className={cx("min-h-11 rounded-lg px-3 text-left text-sm ring-1",
                      interest === i ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line hover:bg-forest-50")}>
                    {INTEREST_LABELS[i]}
                  </button>
                ))}
              </div>
            </fieldset>
            <TextInput label="Next step (optional)" value={nextAction} onChange={(e) => setNextAction(e.target.value)}
              placeholder="e.g. Send price sheet for 1203" maxLength={255} />
            <div className="space-y-3 rounded-lg bg-paper p-3">
              <label className="flex min-h-10 items-center gap-3 text-sm font-medium">
                <input type="checkbox" className="size-5 accent-forest-900" checked={nextOn} onChange={(e) => setNextOn(e.target.checked)} />
                Plan a follow-up
              </label>
              {nextOn && (
                <>
                  <DueTimeField label="When" value={nextAt} onChange={setNextAt} />
                  <SelectInput label="Type" value={nextType} onChange={(e) => setNextType(e.target.value as TaskType)}>
                    {TASK_TYPES.map((t) => <option key={t} value={t}>{TASK_TYPE_LABELS[t]}</option>)}
                  </SelectInput>
                </>
              )}
            </div>
            <Actions onCancel={onClose} submitLabel="Save visit" loading={action.isPending} disabled={!feedback.trim() || !interest} />
          </>
        )}
        {mode === "reschedule" && (
          <>
            <DueTimeField label="New date and time" value={when} onChange={setWhen} />
            <TextInput label="Reason (optional)" value={text} onChange={(e) => setText(e.target.value)} maxLength={255} />
            <Actions onCancel={onClose} submitLabel="Save new date" loading={action.isPending} disabled={!when} />
          </>
        )}
        {mode === "no-show" && (
          <>
            <TextInput label="Note (optional)" value={text} onChange={(e) => setText(e.target.value)}
              placeholder="e.g. Phone switched off" maxLength={255} />
            <Actions onCancel={onClose} submitLabel="Mark as no-show" loading={action.isPending} disabled={false} />
          </>
        )}
        {mode === "cancel" && (
          <>
            <TextInput label="Why is it cancelled?" value={text} onChange={(e) => setText(e.target.value)} autoFocus
              placeholder="e.g. Bought elsewhere" maxLength={255} required />
            <Actions onCancel={onClose} submitLabel="Cancel visit" danger loading={action.isPending} disabled={!text.trim()} />
          </>
        )}
      </form>
    </Modal>
  );
}
