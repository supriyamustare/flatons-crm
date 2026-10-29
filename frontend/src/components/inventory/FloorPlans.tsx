import { useState } from "react";
import type { FormEvent } from "react";
import { FileText, Plus, Trash2 } from "lucide-react";
import { Alert, Button, Modal, SelectInput, TextInput } from "../ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useDeleteFloorPlan, useProjectFloorPlans, useUnitFloorPlans, useUploadFloorPlan } from "../../hooks/useFloorPlans";
import type { FloorPlan } from "../../hooks/useFloorPlans";
import { errorMessage } from "../../lib/api";
import { UNIT_TYPE_LABELS } from "../../lib/inventory";
import type { UnitType } from "../../lib/inventory";

const MAX = 15 * 1024 * 1024;

function PlanCard({ plan, onDelete }: { plan: FloorPlan; onDelete?: () => void }) {
  const isImage = plan.file_type.startsWith("image/");
  return (
    <li className="overflow-hidden rounded-xl bg-white ring-1 ring-line">
      <a href={plan.url} target="_blank" rel="noopener" className="block bg-paper" aria-label={`Open ${plan.title}`}>
        {isImage
          ? <img src={plan.url} alt="" loading="lazy" className="h-36 w-full object-contain" />
          : <span className="grid h-36 place-items-center text-forest-800"><FileText className="size-10" aria-hidden /><span className="text-xs">PDF</span></span>}
      </a>
      <div className="flex items-start justify-between gap-2 p-3">
        <div className="min-w-0"><p className="truncate text-sm font-medium">{plan.title}</p><p className="text-xs text-muted">{plan.applies_to}</p></div>
        {onDelete && <button type="button" onClick={onDelete} aria-label={`Delete ${plan.title}`} className="grid size-9 shrink-0 place-items-center rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>}
      </div>
    </li>
  );
}

function UploadDialog({ projectId, floors, onClose }: { projectId: number; floors: { id: number; label: string }[]; onClose: () => void }) {
  const upload = useUploadFloorPlan(projectId);
  const [title, setTitle] = useState("");
  const [scope, setScope] = useState("project");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    const [kind, value] = scope.split(":");
    upload.mutate({ title: title.trim(), file, floor_id: kind === "floor" ? Number(value) : undefined, unit_type: kind === "type" ? (value as UnitType) : undefined },
      { onSuccess: onClose });
  };
  return (
    <Modal title="Upload floor plan" onClose={onClose}>
      <form className="space-y-4" onSubmit={submit}>
        {upload.isError && <Alert>{errorMessage(upload.error)}</Alert>}
        <TextInput label="Title" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={150} placeholder="e.g. Typical floor plan, Studio layout" autoFocus />
        <SelectInput label="Applies to" value={scope} onChange={(e) => setScope(e.target.value)} hint="Units show the plans for their floor and their type">
          <option value="project">Whole project (site or master plan)</option>
          <optgroup label="A floor">{floors.map((f) => <option key={f.id} value={`floor:${f.id}`}>{f.label}</option>)}</optgroup>
          <optgroup label="A unit type">{(Object.keys(UNIT_TYPE_LABELS) as UnitType[]).map((t) => <option key={t} value={`type:${t}`}>{UNIT_TYPE_LABELS[t]} units</option>)}</optgroup>
        </SelectInput>
        <div className="space-y-1.5">
          <label htmlFor="plan-file" className="block text-sm font-medium">File</label>
          <input id="plan-file" type="file" accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
            className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3 file:text-forest-900"
            onChange={(e) => { const f = e.target.files?.[0] ?? null; setFileError(f && f.size > MAX ? "Floor plans can be at most 15 MB" : null); setFile(f && f.size <= MAX ? f : null); }} />
          <p className="text-xs text-muted">PDF, JPG or PNG, up to 15 MB.</p>
          {fileError && <p className="text-sm text-danger">{fileError}</p>}
        </div>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={upload.isPending} disabled={!title.trim() || !file}>Upload</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Project page: all floor plans, upload and delete (admins and managers). */
export function ProjectFloorPlans({ projectId, floors }: { projectId: number; floors: { id: number; label: string }[] }) {
  const me = useCurrentUser();
  const canEdit = me.role === "admin" || me.role === "manager";
  const plans = useProjectFloorPlans(projectId);
  const del = useDeleteFloorPlan();
  const [adding, setAdding] = useState(false);
  const [confirm, setConfirm] = useState<FloorPlan | null>(null);
  return (
    <section aria-labelledby="fp-h" className="mt-8">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="fp-h" className="font-display text-xl text-forest-900">Floor plans</h2>
        {canEdit && <Button variant="secondary" onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden />Upload floor plan</Button>}
      </div>
      {plans.data && plans.data.length === 0 && <p className="rounded-xl border border-dashed border-line bg-white px-6 py-8 text-center text-sm text-muted">No floor plans yet.{canEdit && " Upload one for the whole project, a floor, or a unit type."}</p>}
      {plans.data && plans.data.length > 0 && (
        <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {plans.data.map((p) => <PlanCard key={p.id} plan={p} onDelete={canEdit ? () => setConfirm(p) : undefined} />)}
        </ul>
      )}
      {adding && <UploadDialog projectId={projectId} floors={floors} onClose={() => setAdding(false)} />}
      {confirm && (
        <Modal title={`Delete ${confirm.title}?`} onClose={() => setConfirm(null)}>
          {del.isError && <Alert>{errorMessage(del.error)}</Alert>}
          <p className="text-sm">The file is removed for everyone.</p>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setConfirm(null)}>Keep</Button>
            <Button variant="danger" loading={del.isPending} onClick={() => del.mutate(confirm.id, { onSuccess: () => setConfirm(null) })}>Delete</Button>
          </div>
        </Modal>
      )}
    </section>
  );
}

/** Unit panel: the plans for this unit's floor and type. */
export function UnitFloorPlans({ unitId }: { unitId: number }) {
  const plans = useUnitFloorPlans(unitId);
  return (
    <section aria-labelledby="ufp-h" className="mt-4 rounded-lg bg-paper p-3">
      <h3 id="ufp-h" className="text-sm font-semibold">Floor plan</h3>
      {plans.data && plans.data.length === 0 && <p className="mt-1 text-sm text-muted">No floor plan uploaded yet.</p>}
      <ul className="mt-1 space-y-1">
        {plans.data?.map((p) => (
          <li key={p.id}><a href={p.url} target="_blank" rel="noopener" className="inline-flex min-h-9 items-center gap-2 text-sm font-medium text-forest-800 underline">
            <FileText className="size-4" aria-hidden />{p.title}<span className="font-normal text-muted no-underline">({p.applies_to})</span></a></li>
        ))}
      </ul>
    </section>
  );
}
