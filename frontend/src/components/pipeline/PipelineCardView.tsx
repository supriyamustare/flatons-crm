import { Link } from "react-router";
import { Clock, GripVertical } from "lucide-react";
import { cx } from "../ui";
import { STATUS_LABELS, formatBudget, formatRupees } from "../../lib/leads";
import type { LeadStatus } from "../../lib/leads";
import { daysInStageLabel } from "../../lib/pipeline";
import type { PipelineCard } from "../../lib/pipeline";

/** One lead on the board. `onMove` gives a no-drag way to change stage (keyboard, touch, screen readers). */
export function PipelineCardView({ card, stages, onMove, dragHandle, dragging = false, showOwner = true }: {
  card: PipelineCard;
  stages: LeadStatus[];
  onMove?: (to: LeadStatus) => void;
  dragHandle?: React.ReactNode;
  dragging?: boolean;
  showOwner?: boolean;
}) {
  const value = card.deal_value;
  return (
    <article aria-label={`${card.name}, ${STATUS_LABELS[card.status]}${card.stale ? ", no activity for over a week" : ""}`}
      className={cx("rounded-lg border bg-white p-3 text-sm shadow-xs",
        card.stale ? "border-amber-400 ring-1 ring-amber-300" : "border-line",
        dragging && "rotate-1 shadow-lg ring-2 ring-forest-700")}>
      <div className="flex items-start gap-1.5">
        {dragHandle}
        <div className="min-w-0 flex-1">
          <Link to={`/leads/${card.id}`} className="block truncate font-medium text-forest-900 hover:underline">{card.name}</Link>
          <p className="truncate text-xs text-muted">{card.project?.name ?? "No project"}</p>
        </div>
      </div>
      <p className="mt-1.5 text-xs">
        {card.budget_min !== null || card.budget_max !== null ? formatBudget(card.budget_min, card.budget_max) : value !== null ? formatRupees(value) : <span className="text-muted">No budget</span>}
      </p>
      <div className="mt-2 flex items-center justify-between gap-2 text-xs text-muted">
        <span className={cx("inline-flex items-center gap-1", card.stale && "font-medium text-amber-700")}>
          <Clock className="size-3.5" aria-hidden />{daysInStageLabel(card.days_in_stage)} in stage{card.stale && " · quiet"}
        </span>
        {showOwner && <span className="truncate">{card.assigned_to?.full_name.split(" ")[0] ?? "Unassigned"}</span>}
      </div>
      {onMove && (
        <select aria-label={`Move ${card.name} to`} value="" onChange={(e) => e.target.value && onMove(e.target.value as LeadStatus)}
          onPointerDown={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}
          className="mt-2 block min-h-9 w-full rounded-md border border-line bg-paper px-2 text-xs">
          <option value="">Move to…</option>
          {stages.filter((s) => s !== card.status).map((s) => <option key={s} value={s}>{STATUS_LABELS[s]}</option>)}
        </select>
      )}
    </article>
  );
}

export function DragGrip(props: React.HTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" {...props} className="-ml-1 grid size-6 shrink-0 cursor-grab place-items-center rounded text-muted hover:bg-paper active:cursor-grabbing">
      <GripVertical className="size-4" aria-hidden />
    </button>
  );
}
