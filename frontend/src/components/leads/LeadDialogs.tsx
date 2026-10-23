import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Modal, SelectInput, TextArea, TextInput } from "../ui";
import { useAuth } from "../../hooks/useAuth";
import { useAddNote, useAssignLead, useAssignableUsers, useChangeStatus, useDeleteLead } from "../../hooks/useLeads";
import { errorMessage } from "../../lib/api";
import { MANAGER_ONLY, REASON_REQUIRED, STATUS_LABELS, STATUSES } from "../../lib/leads";
import type { Lead, LeadStatus } from "../../lib/leads";
import { ROLE_LABELS } from "../../lib/types";

type LeadRef = Pick<Lead, "id" | "name" | "status" | "assigned_to">;

function Actions({ onCancel, submitLabel, loading, disabled }: {
  onCancel: () => void; submitLabel: string; loading: boolean; disabled?: boolean;
}) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      <Button type="submit" loading={loading} disabled={disabled}>{submitLabel}</Button>
    </div>
  );
}

export function StatusDialog({ lead, onClose }: { lead: LeadRef; onClose: () => void }) {
  const { user } = useAuth();
  const isManager = user?.role === "admin" || user?.role === "manager";
  const change = useChangeStatus();
  const [status, setStatus] = useState<LeadStatus>(lead.status);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const needsReason = REASON_REQUIRED.includes(status);
  const lockedBooked = !isManager && lead.status === "booked";

  function submit(e: FormEvent) {
    e.preventDefault();
    change.mutate(
      { id: lead.id, status, reason: needsReason ? reason.trim() : undefined, note: note.trim() || undefined },
      { onSuccess: onClose },
    );
  }

  return (
    <Modal title={`Change status for ${lead.name}`} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {change.isError && <Alert>{errorMessage(change.error)}</Alert>}
        {lockedBooked && <Alert>This lead is booked. Only a manager or admin can change its status.</Alert>}
        <SelectInput label="New status" value={status} onChange={(e) => setStatus(e.target.value as LeadStatus)} disabled={lockedBooked}>
          {STATUSES.map((s) => (
            <option key={s} value={s} disabled={!isManager && MANAGER_ONLY.includes(s)}>
              {STATUS_LABELS[s]}{!isManager && MANAGER_ONLY.includes(s) ? " (manager only)" : ""}
            </option>
          ))}
        </SelectInput>
        {needsReason && (
          <TextInput
            label={status === "lost" ? "Why was this lead lost?" : "Why is this lead junk?"}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={status === "lost" ? "e.g. Bought elsewhere, budget mismatch" : "e.g. Wrong number, spam"}
            maxLength={255}
            required
            autoFocus
          />
        )}
        <TextArea label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        <Actions
          onCancel={onClose}
          submitLabel="Change status"
          loading={change.isPending}
          disabled={lockedBooked || status === lead.status || (needsReason && !reason.trim())}
        />
      </form>
    </Modal>
  );
}

export function NoteDialog({ lead, onClose }: { lead: LeadRef; onClose: () => void }) {
  const add = useAddNote();
  const [note, setNote] = useState("");
  return (
    <Modal title={`Add a note for ${lead.name}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate({ id: lead.id, note: note.trim() }, { onSuccess: onClose });
        }}
        className="space-y-4"
        noValidate
      >
        {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
        <TextArea label="Note" value={note} onChange={(e) => setNote(e.target.value)} rows={4} autoFocus maxLength={5000} />
        <Actions onCancel={onClose} submitLabel="Add note" loading={add.isPending} disabled={!note.trim()} />
      </form>
    </Modal>
  );
}

export function AssignDialog({ lead, onClose }: { lead: LeadRef; onClose: () => void }) {
  const users = useAssignableUsers(true);
  const assign = useAssignLead();
  const [value, setValue] = useState(lead.assigned_to ? String(lead.assigned_to.id) : "");
  const current = lead.assigned_to ? String(lead.assigned_to.id) : "";
  return (
    <Modal title={`Assign ${lead.name}`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          assign.mutate({ id: lead.id, assigned_to_id: value ? Number(value) : null }, { onSuccess: onClose });
        }}
        className="space-y-4"
      >
        {(assign.isError || users.isError) && <Alert>{errorMessage(assign.error ?? users.error)}</Alert>}
        <SelectInput label="Assign to" value={value} onChange={(e) => setValue(e.target.value)} disabled={users.isPending}>
          <option value="">Unassigned</option>
          {users.data?.map((u) => (
            <option key={u.id} value={u.id}>
              {u.full_name} ({ROLE_LABELS[u.role]})
            </option>
          ))}
        </SelectInput>
        <Actions onCancel={onClose} submitLabel="Assign" loading={assign.isPending} disabled={value === current} />
      </form>
    </Modal>
  );
}

export function DeleteDialog({ lead, onClose, onDeleted }: { lead: LeadRef; onClose: () => void; onDeleted: () => void }) {
  const del = useDeleteLead();
  return (
    <Modal title={`Delete ${lead.name}?`} onClose={onClose}>
      <div className="space-y-4">
        {del.isError && <Alert>{errorMessage(del.error)}</Alert>}
        <p className="text-sm text-ink">
          The lead will disappear from every list. It stays in the database and can be restored by a developer if needed.
        </p>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(lead.id, { onSuccess: onDeleted })}>
            Delete lead
          </Button>
        </div>
      </div>
    </Modal>
  );
}
