import { UnitFloorPlans } from "./FloorPlans";
import { CostSheetButtons, PriceAndArea, UnitCustomer } from "./UnitSections";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Lock, LockOpen, Pencil, X } from "lucide-react";
import { Alert, Badge, Button, SelectInput, TextInput, cx } from "../ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useLeadSearch } from "../../hooks/useLeads";
import { useHoldUnit, useReleaseUnit } from "../../hooks/useInventory";
import { errorMessage, formatDateTime } from "../../lib/api";
import { UNIT_STATUS_LABELS, UNIT_TYPE_LABELS, floorLabel } from "../../lib/inventory";
import type { Unit } from "../../lib/inventory";
import { EMPTY_FILTERS } from "../../lib/leads";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-line py-2 text-sm last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}

const HOLD_CHOICES = [
  { hours: 24, label: "24 hours" },
  { hours: 48, label: "2 days" },
  { hours: 72, label: "3 days" },
  { hours: 168, label: "1 week" },
];

function HoldForm({ unit, onDone }: { unit: Unit; onDone: () => void }) {
  const hold = useHoldUnit();
  const [hours, setHours] = useState(48);
  const [q, setQ] = useState("");
  const [leadId, setLeadId] = useState("");
  const [note, setNote] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);
  const leads = useLeadSearch({ ...EMPTY_FILTERS, q: debounced || undefined, sort: "last_activity_at", order: "desc", page: 1, page_size: 8 });

  return (
    <form className="space-y-3 rounded-lg bg-paper p-3" onSubmit={(e) => {
      e.preventDefault();
      hold.mutate({ id: unit.id, hours, lead_id: leadId ? Number(leadId) : undefined, note: note.trim() || undefined }, { onSuccess: onDone });
    }}>
      {hold.isError && <Alert>{errorMessage(hold.error)}</Alert>}
      <SelectInput label="Hold for" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
        {HOLD_CHOICES.map((c) => <option key={c.hours} value={c.hours}>{c.label}</option>)}
      </SelectInput>
      <TextInput label="Find the customer (optional)" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone or lead ID" />
      <SelectInput label="Customer" value={leadId} onChange={(e) => setLeadId(e.target.value)}>
        <option value="">No specific customer</option>
        {leads.data?.items.map((l) => <option key={l.id} value={l.id}>{l.name} ({l.lead_code})</option>)}
      </SelectInput>
      <TextInput label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} maxLength={255} placeholder="e.g. Token amount on Monday" />
      <div className="flex gap-2">
        <Button type="submit" loading={hold.isPending}><Lock className="size-4" aria-hidden />Put on hold</Button>
        <Button type="button" variant="secondary" onClick={onDone}>Cancel</Button>
      </div>
    </form>
  );
}

/** Slide-in details for one unit: side panel on desktop, bottom sheet on phones. */
export function UnitPanel({ unit, onClose, onEdit }: { unit: Unit; onClose: () => void; onEdit: () => void }) {
  const me = useCurrentUser();
  const canHold = me.role === "admin" || me.role === "manager";
  const release = useReleaseUnit();
  const [holding, setHolding] = useState(false);
  useEffect(() => setHolding(false), [unit.id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const held = unit.status === "on_hold";
  const holdable = unit.status === "available" || (held && unit.hold_expired);
  const tone = unit.status === "available" ? "neutral" : unit.status === "booked" || held ? "gold" : "muted";

  return (
    <aside role="dialog" aria-modal="false" aria-label={`Unit ${unit.unit_no}`}
      className={cx("fixed inset-x-0 bottom-0 z-40 max-h-[75dvh] overflow-y-auto rounded-t-2xl bg-white p-5 pb-[calc(5.5rem+env(safe-area-inset-bottom))] shadow-2xl ring-1 ring-line",
        "md:inset-x-auto md:top-0 md:right-0 md:bottom-0 md:max-h-none md:w-[26rem] md:rounded-none md:pb-5")}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-sm text-muted">{unit.floor_number !== null ? floorLabel(unit.floor_number) : "Resale listing"}</p>
          <h2 className="font-display text-2xl text-forest-900">Unit {unit.unit_no}</h2>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge tone={tone}>{UNIT_STATUS_LABELS[unit.status]}</Badge>
            {unit.hold_expired && <Badge tone="muted">Hold expired</Badge>}
          </div>
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="-mr-2 grid size-11 place-items-center rounded-lg text-muted hover:bg-paper">
          <X className="size-5" />
        </button>
      </div>

      <dl>
        <Row label="Type">{UNIT_TYPE_LABELS[unit.unit_type]}</Row>
        {unit.address_note && <Row label="Where">{unit.address_note}</Row>}
      </dl>
      <PriceAndArea unit={unit} />
      <UnitCustomer unit={unit} />
      <UnitFloorPlans unitId={unit.id} />
      <CostSheetButtons unit={unit} />

      {held && (
        <div className={cx("mt-4 rounded-lg p-3 text-sm", unit.hold_expired ? "bg-paper" : "bg-amber-50 ring-1 ring-amber-200")}>
          <p className="font-medium">{unit.hold_expired ? "Hold has expired" : "On hold"}</p>
          <p className="text-muted">
            By {unit.held_by?.full_name ?? "someone"}{unit.hold_expires_at && <> until {formatDateTime(unit.hold_expires_at)}</>}
          </p>
          {unit.held_for && (
            <p className="mt-1">For <Link className="font-medium text-forest-800 underline" to={`/leads/${unit.held_for.id}`}>{unit.held_for.name}</Link> ({unit.held_for.lead_code})</p>
          )}
          {unit.hold_note && <p className="mt-1">{unit.hold_note}</p>}
          {unit.hold_expired && <p className="mt-1 text-xs text-muted">It will be released automatically within a few minutes, or anyone can hold it now.</p>}
        </div>
      )}

      {release.isError && <div className="mt-3"><Alert>{errorMessage(release.error)}</Alert></div>}
      <div className="mt-5 space-y-2">
        {canHold && holdable && !holding && (
          <Button className="w-full" onClick={() => setHolding(true)}><Lock className="size-4" aria-hidden />Hold this unit</Button>
        )}
        {canHold && holding && <HoldForm unit={unit} onDone={() => setHolding(false)} />}
        {canHold && held && !holding && (
          <Button className="w-full" variant="secondary" loading={release.isPending} onClick={() => release.mutate(unit.id)}>
            <LockOpen className="size-4" aria-hidden />Release hold
          </Button>
        )}
        {me.role === "admin" && (
          <Button className="w-full" variant="ghost" onClick={onEdit}><Pencil className="size-4" aria-hidden />Edit unit</Button>
        )}
      </div>
    </aside>
  );
}
