import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../ui";
import {
  useCreateBuilding, useCreateProject, useCreateUnit, useDeleteUnit, useDevelopers, useGenerateUnits,
  useUpdateProject, useUpdateUnit,
} from "../../hooks/useInventory";
import type { UnitInput } from "../../hooks/useInventory";
import { errorMessage } from "../../lib/api";
import {
  PROJECT_STATUS_LABELS, PROJECT_TYPE_LABELS, UNIT_TYPES, UNIT_TYPE_LABELS, floorLabel,
} from "../../lib/inventory";
import type { BuildingTree, ProjectFull, ProjectStatus, ProjectType, Unit, UnitType } from "../../lib/inventory";

function Actions({ onCancel, label, loading, disabled }: { onCancel: () => void; label: string; loading: boolean; disabled?: boolean }) {
  return (
    <div className="flex flex-col-reverse gap-2 pt-2 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      <Button type="submit" loading={loading} disabled={disabled}>{label}</Button>
    </div>
  );
}

const num = (v: string): number | undefined => (v.trim() === "" ? undefined : Number(v));
const lakhToRupees = (v: string): number | undefined => (v.trim() === "" ? undefined : Math.round(Number(v) * 100_000));

export function ProjectFormDialog({ project, onClose, onSaved }: {
  project?: ProjectFull; onClose: () => void; onSaved?: (p: ProjectFull) => void;
}) {
  const developers = useDevelopers();
  const create = useCreateProject();
  const update = useUpdateProject();
  const m = project ? update : create;
  const [name, setName] = useState(project?.name ?? "");
  const [type, setType] = useState<ProjectType>(project?.project_type ?? "developer");
  const [devChoice, setDevChoice] = useState(project?.developer ? String(project.developer.id) : "");
  const [newDev, setNewDev] = useState("");
  const [status, setStatus] = useState<ProjectStatus>(project?.status ?? "under_construction");
  const [location, setLocation] = useState(project?.location ?? "");
  const [description, setDescription] = useState(project?.description ?? "");
  const [commission, setCommission] = useState(project?.commission_pct ? String(Number(project.commission_pct)) : "");
  const pct = commission.trim() === "" ? null : Number(commission);
  const pctOk = pct === null || (Number.isFinite(pct) && pct >= 0 && pct <= 100);

  const typingNew = devChoice === "new";
  const devOk = type === "resale" || (typingNew ? newDev.trim() !== "" : devChoice !== "");

  function submit(e: FormEvent) {
    e.preventDefault();
    const body = {
      name: name.trim(), project_type: type, status,
      location: location.trim() || null, description: description.trim() || null, commission_pct: pct,
      ...(type === "developer" ? (typingNew ? { developer_name: newDev.trim() } : { developer_id: Number(devChoice) }) : {}),
    };
    const done = { onSuccess: (p: ProjectFull) => { onSaved?.(p); onClose(); } };
    if (project) update.mutate({ id: project.id, ...body }, done);
    else create.mutate(body, done);
  }

  return (
    <Modal title={project ? `Edit ${project.name}` : "New project"} onClose={onClose}>
      <form onSubmit={submit} className="space-y-4" noValidate>
        {m.isError && <Alert>{errorMessage(m.error)}</Alert>}
        <TextInput label="Project name" value={name} onChange={(e) => setName(e.target.value)} required autoFocus maxLength={150} />
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">What is it?</legend>
          <div className="grid grid-cols-2 gap-2">
            {(["developer", "resale"] as const).map((t) => (
              <button key={t} type="button" aria-pressed={type === t} onClick={() => setType(t)}
                className={cx("min-h-11 rounded-lg px-3 text-sm ring-1", type === t ? "bg-forest-900 text-white ring-forest-900" : "bg-white ring-line")}>
                {PROJECT_TYPE_LABELS[t]}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted">
            {type === "developer" ? "A builder’s new project that Flatons sells. Has buildings, floors and units." : "Existing homes Flatons sells for their owners. Units are listed individually, without a building grid."}
          </p>
        </fieldset>
        {type === "developer" && (
          <>
            <SelectInput label="Developer" value={devChoice} onChange={(e) => setDevChoice(e.target.value)}>
              <option value="" disabled>Choose the developer</option>
              {developers.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              <option value="new">+ Add a new developer</option>
            </SelectInput>
            {typingNew && <TextInput label="New developer name" value={newDev} onChange={(e) => setNewDev(e.target.value)} maxLength={150} />}
          </>
        )}
        <SelectInput label="Status" value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}>
          {(Object.keys(PROJECT_STATUS_LABELS) as ProjectStatus[]).map((s) => <option key={s} value={s}>{PROJECT_STATUS_LABELS[s]}</option>)}
        </SelectInput>
        <TextInput label="Location (optional)" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="e.g. Baner, Pune" maxLength={200} />
        <TextInput label="Flatons commission %" type="number" inputMode="decimal" min={0} max={100} step="0.25" value={commission}
          onChange={(e) => setCommission(e.target.value)} placeholder="e.g. 2"
          hint={pctOk ? "Commission or brokerage on each deal; used for the dashboard’s estimated revenue" : "Enter a number from 0 to 100"} />
        <TextArea label="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} />
        {project && (
          <label className="flex items-center gap-3 text-sm">
            <input type="checkbox" className="size-5 accent-forest-900" checked={project.is_active}
              onChange={(e) => update.mutate({ id: project.id, is_active: e.target.checked })} />
            Active (inactive projects are hidden from lead and visit forms)
          </label>
        )}
        <Actions onCancel={onClose} label={project ? "Save" : "Create project"} loading={m.isPending} disabled={!name.trim() || !devOk || !pctOk} />
      </form>
    </Modal>
  );
}

export function BuildingDialog({ projectId, onClose, onCreated }: { projectId: number; onClose: () => void; onCreated: (id: number) => void }) {
  const create = useCreateBuilding();
  const [name, setName] = useState("");
  return (
    <Modal title="Add a building" onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e) => {
        e.preventDefault();
        create.mutate({ projectId, name: name.trim() }, { onSuccess: (b) => { onCreated(b.id); onClose(); } });
      }}>
        {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
        <TextInput label="Building name" value={name} onChange={(e) => setName(e.target.value)} autoFocus placeholder="e.g. A Wing, Tower 1" maxLength={100} />
        <Actions onCancel={onClose} label="Add building" loading={create.isPending} disabled={!name.trim()} />
      </form>
    </Modal>
  );
}

function unitNo(floor: number, pos: number): string {
  const p = String(pos).padStart(2, "0");
  if (floor === 0) return `G${p}`;
  if (floor < 0) return `B${-floor}-${p}`;
  return `${floor}${p}`;
}

export function GenerateDialog({ building, onClose }: { building: BuildingTree; onClose: () => void }) {
  const gen = useGenerateUnits();
  const top = building.floors[0]?.number;
  const [from, setFrom] = useState(top !== undefined ? String(top + 1) : "1");
  const [to, setTo] = useState(top !== undefined ? String(top + 4) : "4");
  const [perFloor, setPerFloor] = useState("4");
  const [type, setType] = useState<UnitType>("2bhk");
  const [carpet, setCarpet] = useState("");
  const [builtup, setBuiltup] = useState("");
  const [price, setPrice] = useState("");
  const f = Number(from), t = Number(to), n = Number(perFloor);
  const valid = Number.isInteger(f) && Number.isInteger(t) && t >= f && n >= 1 && n <= 20 && (t - f + 1) * n <= 600;
  const total = valid ? (t - f + 1) * n : 0;

  return (
    <Modal title={`Add floors and units to ${building.name}`} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e) => {
        e.preventDefault();
        gen.mutate({ buildingId: building.id, floor_from: f, floor_to: t, units_per_floor: n, unit_type: type,
          carpet_sqft: num(carpet), builtup_sqft: num(builtup), base_price: lakhToRupees(price) }, { onSuccess: onClose });
      }}>
        {gen.isError && <Alert>{errorMessage(gen.error)}</Alert>}
        <div className="grid grid-cols-3 gap-3">
          <TextInput label="From floor" type="number" inputMode="numeric" value={from} onChange={(e) => setFrom(e.target.value)} hint="0 = ground" />
          <TextInput label="To floor" type="number" inputMode="numeric" value={to} onChange={(e) => setTo(e.target.value)} />
          <TextInput label="Units per floor" type="number" inputMode="numeric" min={1} max={20} value={perFloor} onChange={(e) => setPerFloor(e.target.value)} />
        </div>
        <SelectInput label="Unit type" value={type} onChange={(e) => setType(e.target.value as UnitType)}>
          {UNIT_TYPES.map((u) => <option key={u} value={u}>{UNIT_TYPE_LABELS[u]}</option>)}
        </SelectInput>
        <div className="grid grid-cols-3 gap-3">
          <TextInput label="Carpet sq ft" type="number" inputMode="decimal" value={carpet} onChange={(e) => setCarpet(e.target.value)} />
          <TextInput label="Built-up sq ft" type="number" inputMode="decimal" value={builtup} onChange={(e) => setBuiltup(e.target.value)} />
          <TextInput label="Price (₹ lakh)" type="number" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} />
        </div>
        <p className="rounded-lg bg-paper p-3 text-sm" aria-live="polite">
          {valid
            ? <>Creates <b>{total} units</b>: {floorLabel(f).toLowerCase()} {unitNo(f, 1)}–{unitNo(f, n)} up to {floorLabel(t).toLowerCase()} {unitNo(t, 1)}–{unitNo(t, n)}. You can change individual units afterwards.</>
            : "Check the floors (the top floor can’t be below the first) and use 1–20 units per floor, up to 600 units at once."}
        </p>
        <Actions onCancel={onClose} label={valid ? `Create ${total} units` : "Create units"} loading={gen.isPending} disabled={!valid} />
      </form>
    </Modal>
  );
}

export function UnitFormDialog({ projectId, unit, floors, onClose }: {
  projectId: number; unit?: Unit; floors?: { id: number; label: string }[]; onClose: () => void;
}) {
  const create = useCreateUnit();
  const update = useUpdateUnit();
  const del = useDeleteUnit();
  const m = unit ? update : create;
  const [no, setNo] = useState(unit?.unit_no ?? "");
  const [floorId, setFloorId] = useState(unit?.floor_id ? String(unit.floor_id) : "");
  const [type, setType] = useState<UnitType>(unit?.unit_type ?? "2bhk");
  const [carpet, setCarpet] = useState(unit?.carpet_sqft ?? "");
  const [builtup, setBuiltup] = useState(unit?.builtup_sqft ?? "");
  const [base, setBase] = useState(unit?.base_price ? String(unit.base_price / 100_000) : "");
  const [asking, setAsking] = useState(unit?.current_asking_price ? String(unit.current_asking_price / 100_000) : "");
  const [where, setWhere] = useState(unit?.address_note ?? "");
  const [status, setStatus] = useState<UnitInput["status"] | "">(
    unit && ["available", "withdrawn", "sold"].includes(unit.status) ? (unit.status as UnitInput["status"]) : "");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const locked = unit && (unit.status === "on_hold" || unit.status === "booked");

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: UnitInput = {
      unit_no: no.trim(), unit_type: type,
      carpet_sqft: num(String(carpet)) ?? null, builtup_sqft: num(String(builtup)) ?? null,
      base_price: lakhToRupees(base) ?? null, current_asking_price: lakhToRupees(asking) ?? null,
      address_note: where.trim() || null,
    };
    if (unit) {
      if (status && status !== unit.status) body.status = status;
      update.mutate({ id: unit.id, ...body }, { onSuccess: onClose });
    } else {
      create.mutate({ projectId, ...body, floor_id: floorId ? Number(floorId) : undefined }, { onSuccess: onClose });
    }
  }

  return (
    <Modal title={unit ? `Edit unit ${unit.unit_no}` : "Add a unit"} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={submit}>
        {(m.isError || del.isError) && <Alert>{errorMessage(m.error ?? del.error)}</Alert>}
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Unit number" value={no} onChange={(e) => setNo(e.target.value)} maxLength={20} autoFocus={!unit} />
          <SelectInput label="Type" value={type} onChange={(e) => setType(e.target.value as UnitType)}>
            {UNIT_TYPES.map((u) => <option key={u} value={u}>{UNIT_TYPE_LABELS[u]}</option>)}
          </SelectInput>
        </div>
        {!unit && floors && (
          <SelectInput label="Floor" value={floorId} onChange={(e) => setFloorId(e.target.value)}>
            <option value="" disabled>Choose a floor</option>
            {floors.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
          </SelectInput>
        )}
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Carpet sq ft" type="number" inputMode="decimal" value={carpet} onChange={(e) => setCarpet(e.target.value)} />
          <TextInput label="Built-up sq ft" type="number" inputMode="decimal" value={builtup} onChange={(e) => setBuiltup(e.target.value)} />
          <TextInput label="Base price (₹ lakh)" type="number" inputMode="decimal" value={base} onChange={(e) => setBase(e.target.value)} />
          <TextInput label="Asking price (₹ lakh)" type="number" inputMode="decimal" value={asking} onChange={(e) => setAsking(e.target.value)} />
        </div>
        {!floors && <TextInput label="Where (optional)" value={where} onChange={(e) => setWhere(e.target.value)} placeholder="e.g. Sai Residency, 7th floor" maxLength={200} />}
        {unit && (
          locked
            ? <p className="text-sm text-muted">This unit is {unit.status.replace("_", " ")}; its status changes through that process.</p>
            : (
              <SelectInput label="Status" value={status} onChange={(e) => setStatus(e.target.value as UnitInput["status"])}>
                <option value="available">Available</option>
                <option value="withdrawn">Withdrawn (not for sale)</option>
                <option value="sold">Sold</option>
              </SelectInput>
            )
        )}
        <Actions onCancel={onClose} label={unit ? "Save" : "Add unit"} loading={m.isPending} disabled={!no.trim() || (!unit && floors !== undefined && !floorId)} />
        {unit && !locked && unit.status !== "sold" && (
          <div className="border-t border-line pt-4">
            {confirmDelete ? (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>Delete unit {unit.unit_no} permanently?</span>
                <Button type="button" variant="danger" loading={del.isPending} onClick={() => del.mutate(unit.id, { onSuccess: onClose })}>Delete</Button>
                <Button type="button" variant="secondary" onClick={() => setConfirmDelete(false)}>Keep</Button>
              </div>
            ) : (
              <Button type="button" variant="ghost" className="text-danger" onClick={() => setConfirmDelete(true)}>Delete unit</Button>
            )}
          </div>
        )}
      </form>
    </Modal>
  );
}
