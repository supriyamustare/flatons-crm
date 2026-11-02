import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../ui";
import { DueTimeField } from "../tasks/TaskDialogs";
import { useLogCall } from "../../hooks/useCalls";
import { errorMessage } from "../../lib/api";
import { CONNECTED, NOT_CONNECTED, OUTCOME_LABELS } from "../../lib/calls";
import type { CallDirection, CallOutcome } from "../../lib/calls";
import { TASK_TYPES, TASK_TYPE_LABELS, duePresets, localInputToIso, toLocalInput } from "../../lib/tasks";
import type { Task, TaskType } from "../../lib/tasks";

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
      className={cx("min-h-10 rounded-full px-3 text-sm ring-1",
        on ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line hover:bg-forest-50")}>
      {children}
    </button>
  );
}

/** Log a call. Opened from a follow-up, it can close that follow-up in the same step. */
export function LogCallDialog({ lead, task, onClose }: {
  lead: { id: number; name: string };
  task?: Task;
  onClose: () => void;
}) {
  const log = useLogCall();
  const [direction, setDirection] = useState<CallDirection>("outgoing");
  const [outcome, setOutcome] = useState<CallOutcome | null>(null);
  const [minutes, setMinutes] = useState("");
  const [notes, setNotes] = useState("");
  const [closeTask, setCloseTask] = useState(Boolean(task));
  const [nextOn, setNextOn] = useState(false);
  const [nextAt, setNextAt] = useState(() => toLocalInput(duePresets()[1].value));
  const [nextType, setNextType] = useState<TaskType>("call");
  const connected = outcome !== null && CONNECTED.includes(outcome);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!outcome) return;
    const mins = Number(minutes);
    log.mutate(
      {
        lead_id: lead.id, outcome, direction,
        duration_sec: connected && minutes && mins >= 0 ? Math.round(mins * 60) : undefined,
        notes: notes.trim() || undefined,
        follow_up_at: nextOn ? localInputToIso(nextAt) : undefined,
        follow_up_type: nextOn ? nextType : undefined,
        complete_task_id: task && closeTask ? task.id : undefined,
      },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal title={`Log call with ${lead.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-5" noValidate>
        {log.isError && <Alert>{errorMessage(log.error)}</Alert>}

        <div className="flex gap-2" role="group" aria-label="Direction">
          <Chip on={direction === "outgoing"} onClick={() => setDirection("outgoing")}>I called</Chip>
          <Chip on={direction === "incoming"} onClick={() => setDirection("incoming")}>They called</Chip>
        </div>

        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">How did it go?</legend>
          <p className="text-xs text-muted">Spoke to them</p>
          <div className="flex flex-wrap gap-2">
            {CONNECTED.map((o) => <Chip key={o} on={outcome === o} onClick={() => setOutcome(o)}>{OUTCOME_LABELS[o]}</Chip>)}
          </div>
          <p className="pt-1 text-xs text-muted">Didn’t connect</p>
          <div className="flex flex-wrap gap-2">
            {NOT_CONNECTED.map((o) => <Chip key={o} on={outcome === o} onClick={() => setOutcome(o)}>{OUTCOME_LABELS[o]}</Chip>)}
          </div>
        </fieldset>

        {connected && (
          <TextInput label="Duration in minutes (optional)" type="number" inputMode="decimal" min={0} max={240} step="0.5"
            value={minutes} onChange={(e) => setMinutes(e.target.value)} placeholder="e.g. 4" />
        )}
        <TextArea label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder={connected ? "What did they say?" : "e.g. Rang twice, will try in the evening"} maxLength={5000} />

        <div className="space-y-3 rounded-lg bg-paper p-3">
          <label className="flex min-h-10 items-center gap-3 text-sm font-medium">
            <input type="checkbox" className="size-5 accent-forest-900" checked={nextOn} onChange={(e) => setNextOn(e.target.checked)} />
            Plan the next follow-up
          </label>
          {nextOn && (
            <>
              <DueTimeField label="When" value={nextAt} onChange={setNextAt} />
              <SelectInput label="Type" value={nextType} onChange={(e) => setNextType(e.target.value as TaskType)}>
                {TASK_TYPES.map((t) => <option key={t} value={t}>{TASK_TYPE_LABELS[t]}</option>)}
              </SelectInput>
            </>
          )}
          {task && (
            <label className="flex min-h-10 items-center gap-3 text-sm">
              <input type="checkbox" className="size-5 accent-forest-900" checked={closeTask} onChange={(e) => setCloseTask(e.target.checked)} />
              Mark this follow-up as done
            </label>
          )}
        </div>

        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={log.isPending} disabled={!outcome}>Save call</Button>
        </div>
      </form>
    </Modal>
  );
}
