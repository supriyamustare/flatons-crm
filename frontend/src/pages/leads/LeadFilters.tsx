import { useState } from "react";
import { Button, Modal, SelectInput, TextInput, cx } from "../../components/ui";
import { useAssignableUsers, useProjects } from "../../hooks/useLeads";
import { EMPTY_FILTERS, SOURCE_LABELS, SOURCES, STATUS_LABELS, STATUSES } from "../../lib/leads";
import type { LeadFilters, LeadSource, LeadStatus } from "../../lib/leads";

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={cx(
        "min-h-9 rounded-full px-3 text-sm ring-1 transition-colors",
        on ? "bg-forest-900 text-white ring-forest-900" : "bg-white text-ink ring-line hover:bg-forest-50",
      )}
    >
      {children}
    </button>
  );
}

const toggle = <T,>(list: T[], v: T) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

export function FilterDialog({
  value, onApply, onClose, canFilterByPerson,
}: {
  value: LeadFilters; onApply: (f: LeadFilters) => void; onClose: () => void; canFilterByPerson: boolean;
}) {
  const [f, setF] = useState<LeadFilters>(value);
  const projects = useProjects();
  const people = useAssignableUsers(canFilterByPerson);
  const personValue = f.unassigned ? "unassigned" : f.assigned_to_id ? String(f.assigned_to_id) : "";

  return (
    <Modal title="Filter leads" onClose={onClose}>
      <div className="space-y-5">
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Status</legend>
          <div className="flex flex-wrap gap-2">
            {STATUSES.map((s: LeadStatus) => (
              <Chip key={s} on={f.statuses.includes(s)} onClick={() => setF({ ...f, statuses: toggle(f.statuses, s) })}>
                {STATUS_LABELS[s]}
              </Chip>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Source</legend>
          <div className="flex flex-wrap gap-2">
            {SOURCES.map((s: LeadSource) => (
              <Chip key={s} on={f.sources.includes(s)} onClick={() => setF({ ...f, sources: toggle(f.sources, s) })}>
                {SOURCE_LABELS[s]}
              </Chip>
            ))}
          </div>
        </fieldset>
        <SelectInput
          label="Project"
          value={f.project_id ?? ""}
          onChange={(e) => setF({ ...f, project_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">All projects</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        {canFilterByPerson && (
          <SelectInput
            label="Assigned to"
            value={personValue}
            onChange={(e) => {
              const v = e.target.value;
              setF({ ...f, unassigned: v === "unassigned", assigned_to_id: v && v !== "unassigned" ? Number(v) : null });
            }}
          >
            <option value="">Anyone</option>
            <option value="unassigned">Unassigned</option>
            {people.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
          </SelectInput>
        )}
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Created from" type="date" value={f.created_from ?? ""}
            onChange={(e) => setF({ ...f, created_from: e.target.value || null })} />
          <TextInput label="Created to" type="date" value={f.created_to ?? ""}
            onChange={(e) => setF({ ...f, created_to: e.target.value || null })} />
        </div>
        <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-between">
          <Button variant="ghost" onClick={() => setF(EMPTY_FILTERS)}>Clear all</Button>
          <Button onClick={() => { onApply(f); onClose(); }}>Show leads</Button>
        </div>
      </div>
    </Modal>
  );
}
