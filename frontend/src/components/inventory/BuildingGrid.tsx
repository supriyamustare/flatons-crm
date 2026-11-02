import { cx } from "../ui";
import { UNIT_CELL, UNIT_MARK, UNIT_STATUSES, UNIT_STATUS_LABELS, floorLabel, unitSpokenLabel } from "../../lib/inventory";
import type { BuildingTree, Unit, UnitStatus } from "../../lib/inventory";

const LEGEND_SWATCH: Record<UnitStatus, string> = {
  available: "bg-emerald-100 ring-emerald-300",
  on_hold: "unit-hold ring-amber-400",
  booked: "bg-gold-500 ring-gold-600",
  sold: "bg-stone-300 ring-stone-400",
  withdrawn: "bg-white ring-line",
};

export function StatusLegend({ counts }: { counts?: Record<UnitStatus, number> }) {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-2 text-sm" aria-label="Unit status colours">
      {UNIT_STATUSES.map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <span aria-hidden className={cx("grid size-4 place-items-center rounded text-[9px] font-bold ring-1", LEGEND_SWATCH[s],
            s === "withdrawn" && "line-through")}>{UNIT_MARK[s] || (s === "withdrawn" ? "–" : "")}</span>
          <span>{UNIT_STATUS_LABELS[s]}{counts ? <span className="text-muted"> {counts[s]}</span> : null}</span>
        </li>
      ))}
    </ul>
  );
}

export function UnitCell({ unit, selected, onSelect }: { unit: Unit; selected: boolean; onSelect: () => void }) {
  const status: UnitStatus = unit.hold_expired ? "available" : unit.status;
  return (
    <button type="button" onClick={onSelect} aria-label={unitSpokenLabel(unit)} aria-pressed={selected}
      className={cx("relative flex h-12 min-w-14 flex-1 items-center justify-center rounded-md px-1 text-sm tabular-nums ring-1 transition",
        UNIT_CELL[status], unit.hold_expired && "border-2 border-dashed border-amber-500",
        selected && "ring-3 ring-forest-900 ring-offset-1")}>
      {unit.unit_no}
      {UNIT_MARK[unit.status] && !unit.hold_expired && (
        <span aria-hidden className="absolute top-0.5 right-1 text-[9px] font-bold opacity-70">{UNIT_MARK[unit.status]}</span>
      )}
    </button>
  );
}

/** Floor-by-floor grid, top floor first like the building itself. Scrolls sideways inside its
 *  own box on narrow screens so the page never does. */
export function BuildingGrid({ building, selectedId, onSelect }: {
  building: BuildingTree; selectedId: number | null; onSelect: (u: Unit) => void;
}) {
  if (building.floors.length === 0) {
    return <p className="rounded-xl border border-dashed border-line bg-white p-6 text-center text-sm text-muted">No floors yet.</p>;
  }
  const widest = Math.max(...building.floors.map((f) => f.units.length), 1);
  return (
    <div className="overflow-x-auto rounded-xl border border-line bg-white p-3" role="grid" aria-label={`${building.name} units by floor`}>
      <div className="space-y-1.5" style={{ minWidth: `${widest * 3.75 + 5}rem` }}>
        {building.floors.map((f) => (
          <div key={f.id} role="row" className="flex items-center gap-1.5">
            <span role="rowheader" className="w-16 shrink-0 text-xs text-muted">{floorLabel(f.number)}</span>
            <div className="flex flex-1 gap-1.5">
              {f.units.map((u) => (
                <span role="gridcell" key={u.id} className="flex flex-1">
                  <UnitCell unit={u} selected={selectedId === u.id} onSelect={() => onSelect(u)} />
                </span>
              ))}
              {/* keep columns aligned when a floor has fewer units */}
              {Array.from({ length: widest - f.units.length }, (_, i) => <span key={`pad${i}`} className="flex-1" aria-hidden />)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
