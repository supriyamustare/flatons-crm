import { useEffect, useMemo, useRef, useState } from "react";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import type { FormEvent } from "react";
import {
  DndContext, DragOverlay, PointerSensor, TouchSensor, closestCenter, pointerWithin, useDraggable, useDroppable,
  useSensor, useSensors,
} from "@dnd-kit/core";
import type { CollisionDetection, DragEndEvent, DragStartEvent } from "@dnd-kit/core";
import { LayoutGrid, List, SlidersHorizontal } from "lucide-react";
import { DragGrip, PipelineCardView } from "../components/pipeline/PipelineCardView";
import { Alert, Button, ErrorState, Modal, PageHeader, SelectInput, TextInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useAssignableUsers, useProjects } from "../hooks/useLeads";
import { useForecast, useMoveLead, usePipeline, useStageProbabilities, useUpdateProbabilities } from "../hooks/usePipeline";
import type { MoveLead, PipelineQuery } from "../hooks/usePipeline";
import { errorMessage } from "../lib/api";
import { STATUSES, STATUS_LABELS, formatRupees } from "../lib/leads";
import type { LeadStatus } from "../lib/leads";
import { FIXED_PROBABILITY, NEEDS_REASON } from "../lib/pipeline";
import type { PipelineBoard, PipelineCard, StageColumn, StageProbability } from "../lib/pipeline";

const isPhone = () => typeof window !== "undefined" && window.matchMedia?.("(max-width: 767px)").matches;

function Money({ v }: { v: number }) {
  return <>{v ? formatRupees(v) : "₹0"}</>;
}

// ---------------------------------------------------------------- board (desktop)

/** Mouse and touch drops land in the column under the pointer (where people aim). */
const findColumn: CollisionDetection = (args) => {
  const underPointer = pointerWithin(args);
  return underPointer.length ? underPointer : closestCenter(args);
};

/** Keyboard moving, handled by the board itself (not by screen geometry, so fast key presses
 *  are never lost): Space picks up, Left/Right choose a column, Space drops, Escape cancels. */
interface KeyboardMove { card: PipelineCard; index: number }

function DraggableCard({ card, stages, onMove, showOwner, picked, onGripKeyDown }: {
  card: PipelineCard; stages: LeadStatus[]; onMove: (to: LeadStatus) => void; showOwner: boolean;
  picked: boolean; onGripKeyDown: (e: ReactKeyboardEvent<HTMLButtonElement>) => void;
}) {
  const { listeners, setNodeRef, isDragging } = useDraggable({ id: card.id, data: { card } });
  return (
    <li ref={setNodeRef} className={cx(isDragging && "opacity-30", picked && "rounded-lg ring-2 ring-gold-500")}>
      <PipelineCardView card={card} stages={stages} onMove={onMove} showOwner={showOwner}
        dragHandle={
          <DragGrip aria-label={`Move ${card.name}: press Space, then the arrow keys`} aria-pressed={picked}
            {...listeners} onKeyDown={onGripKeyDown} />
        } />
    </li>
  );
}

function Column({ col, stages, onMove, showOwner, target, pickedId, onGripKeyDown }: {
  col: StageColumn; stages: LeadStatus[]; onMove: (card: PipelineCard, to: LeadStatus) => void; showOwner: boolean;
  target: boolean; pickedId: number | null; onGripKeyDown: (card: PipelineCard, e: ReactKeyboardEvent<HTMLButtonElement>) => void;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: col.stage });
  return (
    <section ref={setNodeRef} aria-label={`${STATUS_LABELS[col.stage]}, ${col.count} leads`}
      className={cx("flex w-72 shrink-0 flex-col rounded-xl bg-forest-50/60 p-2 ring-1 ring-line transition-colors",
        (isOver || target) && "bg-gold-100 ring-2 ring-gold-500")} data-stage={col.stage}>
      <header className="px-1.5 pt-1 pb-2">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-semibold text-forest-900">{STATUS_LABELS[col.stage]}</h2>
          <span className="text-sm tabular-nums text-muted">{col.count}</span>
        </div>
        <p className="text-xs text-muted">
          <Money v={col.value} /> · weighted <b className="text-ink"><Money v={col.weighted_value} /></b> ({col.probability_pct}%)
        </p>
        {col.stale_count > 0 && <p className="text-xs font-medium text-amber-700">{col.stale_count} quiet for 7+ days</p>}
      </header>
      <ul className="flex min-h-24 flex-1 flex-col gap-2">
        {col.cards.map((c) => (
          <DraggableCard key={c.id} card={c} stages={stages} showOwner={showOwner} onMove={(to) => onMove(c, to)}
            picked={pickedId === c.id} onGripKeyDown={(e) => onGripKeyDown(c, e)} />
        ))}
      </ul>
      {col.has_more && <p className="px-1.5 pt-2 text-xs text-muted">Showing {col.cards.length} of {col.count}, longest in stage first</p>}
    </section>
  );
}

function Board({ board, onMove, showOwner }: {
  board: PipelineBoard; onMove: (card: PipelineCard, to: LeadStatus) => void; showOwner: boolean;
}) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 8 } }),
  );
  const [active, setActive] = useState<PipelineCard | null>(null);
  const [kb, setKb] = useState<KeyboardMove | null>(null);
  const [said, setSaid] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const order = board.stages.map((s) => s.stage);
  const stages = STATUSES;

  // Keep the column being chosen in view
  useEffect(() => {
    if (!kb) return;
    scroller.current?.querySelector(`[data-stage="${order[kb.index]}"]`)?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [kb, order]);

  function onGripKeyDown(card: PipelineCard, e: ReactKeyboardEvent<HTMLButtonElement>) {
    const picked = kb?.card.id === card.id;
    if (!picked && (e.key === " " || e.key === "Enter")) {
      e.preventDefault();
      setKb({ card, index: Math.max(0, order.indexOf(card.status)) });
      setSaid(`Picked up ${card.name}, in ${STATUS_LABELS[card.status]}. Use left and right arrows to choose a stage, Space to drop, Escape to cancel.`);
      return;
    }
    if (!picked || !kb) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const index = Math.min(Math.max(kb.index + (e.key === "ArrowRight" ? 1 : -1), 0), order.length - 1);
      setKb({ ...kb, index });
      setSaid(`Over ${STATUS_LABELS[order[index]]}.`);
    } else if (e.key === " " || e.key === "Enter") {
      e.preventDefault();
      const to = order[kb.index];
      setKb(null);
      if (to !== card.status) {
        setSaid(`Dropped ${card.name} in ${STATUS_LABELS[to]}.`);
        onMove(card, to);
      } else setSaid(`${card.name} stays in ${STATUS_LABELS[to]}.`);
    } else if (e.key === "Escape" || e.key === "Tab") {
      setKb(null);
      setSaid("Move cancelled.");
    }
  }

  function end(e: DragEndEvent) {
    setActive(null);
    const card = e.active.data.current?.card as PipelineCard | undefined;
    const to = e.over?.id as LeadStatus | undefined;
    if (card && to && to !== card.status) onMove(card, to);
  }

  return (
    <DndContext sensors={sensors} collisionDetection={findColumn}
      onDragStart={(e: DragStartEvent) => setActive((e.active.data.current?.card as PipelineCard) ?? null)}
      onDragEnd={end} onDragCancel={() => setActive(null)}>
      <p className="sr-only" aria-live="assertive" role="status">{said}</p>
      <div ref={scroller} className="-mx-4 overflow-x-auto px-4 pb-4 md:-mx-10 md:px-10">
        <div className="flex gap-3">
          {board.stages.map((col, i) => (
            <Column key={col.stage} col={col} stages={stages} onMove={onMove} showOwner={showOwner}
              target={kb !== null && kb.index === i && col.stage !== kb.card.status} pickedId={kb?.card.id ?? null}
              onGripKeyDown={onGripKeyDown} />
          ))}
        </div>
      </div>
      <DragOverlay>{active && <PipelineCardView card={active} stages={[]} dragging showOwner={showOwner} />}</DragOverlay>
    </DndContext>
  );
}

// ---------------------------------------------------------------- list (phones)

function ListView({ board, onMove, showOwner }: {
  board: PipelineBoard; onMove: (card: PipelineCard, to: LeadStatus) => void; showOwner: boolean;
}) {
  const stages = STATUSES;
  return (
    <div className="space-y-3">
      {board.stages.filter((c) => c.count > 0).map((col) => (
        <details key={col.stage} open={col.count <= 6} className="rounded-xl bg-white ring-1 ring-line">
          <summary className="flex min-h-12 cursor-pointer items-center justify-between gap-2 px-4 py-2">
            <span>
              <span className="font-semibold">{STATUS_LABELS[col.stage]}</span>{" "}
              <span className="text-muted">{col.count}</span>
              {col.stale_count > 0 && <span className="ml-2 text-xs font-medium text-amber-700">{col.stale_count} quiet</span>}
            </span>
            <span className="text-xs text-muted"><Money v={col.weighted_value} /> weighted</span>
          </summary>
          <ul className="grid gap-2 px-3 pb-3 sm:grid-cols-2">
            {col.cards.map((c) => (
              <li key={c.id}><PipelineCardView card={c} stages={stages} showOwner={showOwner} onMove={(to) => onMove(c, to)} /></li>
            ))}
          </ul>
          {col.has_more && <p className="px-4 pb-3 text-xs text-muted">Showing {col.cards.length} of {col.count}</p>}
        </details>
      ))}
      {board.stages.every((c) => c.count === 0) && (
        <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">No leads match these filters.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- dialogs

function ReasonDialog({ move, name, onCancel, onConfirm }: {
  move: MoveLead; name: string; onCancel: () => void; onConfirm: (reason: string) => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <Modal title={`Move ${name} to ${STATUS_LABELS[move.to]}`} onClose={onCancel}>
      <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); onConfirm(reason.trim()); }}>
        <TextInput label={move.to === "lost" ? "Why was this lead lost?" : "Why is this lead junk?"} value={reason}
          onChange={(e) => setReason(e.target.value)} autoFocus maxLength={255}
          placeholder={move.to === "lost" ? "e.g. Bought elsewhere" : "e.g. Wrong number"} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button type="submit" disabled={!reason.trim()}>Move lead</Button>
        </div>
      </form>
    </Modal>
  );
}

function ProbabilityDialog({ onClose }: { onClose: () => void }) {
  const stages = useStageProbabilities();
  const save = useUpdateProbabilities();
  const [edits, setEdits] = useState<Record<string, string>>({});
  const rows = stages.data ?? [];
  const value = (s: StageProbability) => edits[s.stage] ?? String(s.probability_pct);
  const valid = rows.every((s) => { const n = Number(value(s)); return Number.isInteger(n) && n >= 0 && n <= 100; });
  return (
    <Modal title="Stage probabilities" onClose={onClose}>
      <p className="-mt-2 mb-4 text-sm text-muted">The chance that a lead in each stage ends in a booking. The weighted forecast multiplies each deal’s value by this.</p>
      <form className="space-y-2" onSubmit={(e) => {
        e.preventDefault();
        save.mutate(rows.filter((s) => !(s.stage in FIXED_PROBABILITY)).map((s) => ({ stage: s.stage, probability_pct: Number(value(s)) })), { onSuccess: onClose });
      }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        {rows.map((s) => {
          const fixed = s.stage in FIXED_PROBABILITY;
          return (
            <label key={s.stage} className="flex items-center justify-between gap-3 text-sm">
              <span>{STATUS_LABELS[s.stage]}</span>
              <span className="flex items-center gap-1">
                <input type="number" min={0} max={100} inputMode="numeric" disabled={fixed} value={value(s)}
                  onChange={(e) => setEdits({ ...edits, [s.stage]: e.target.value })}
                  aria-label={`${STATUS_LABELS[s.stage]} probability`}
                  className="min-h-10 w-20 rounded-lg border border-line px-2 text-right disabled:bg-paper disabled:text-muted" />%
              </span>
            </label>
          );
        })}
        <div className="flex flex-col-reverse gap-2 pt-3 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!valid}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}

// ---------------------------------------------------------------- page

export function PipelinePage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const projects = useProjects();
  const people = useAssignableUsers(isManager);
  const [view, setView] = useState<"board" | "list">(() => (isPhone() ? "list" : "board"));
  const [projectId, setProjectId] = useState("");
  const [person, setPerson] = useState("");
  const [staleOnly, setStaleOnly] = useState(false);
  const [showClosed, setShowClosed] = useState(false);
  const [pending, setPending] = useState<{ move: MoveLead; name: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editingOdds, setEditingOdds] = useState(false);

  const query: PipelineQuery = useMemo(() => ({
    project_id: projectId ? Number(projectId) : undefined,
    mine: person === "me" || undefined,
    assigned_to_id: person && person !== "me" ? Number(person) : undefined,
    stale_only: staleOnly || undefined,
    include_closed: showClosed || undefined,
  }), [projectId, person, staleOnly, showClosed]);
  const board = usePipeline(query);
  const forecast = useForecast(query);
  const move = useMoveLead(query);

  function requestMove(card: PipelineCard, to: LeadStatus) {
    setNotice(null);
    if (to === "booked" && !isManager) {
      setNotice("Only managers and admins can mark a lead as booked.");
      return;
    }
    const m: MoveLead = { leadId: card.id, from: card.status, to };
    if (NEEDS_REASON.includes(to)) setPending({ move: m, name: card.name });
    else move.mutate(m, { onError: (err) => setNotice(errorMessage(err)) });
  }

  const t = board.data?.totals;
  return (
    <>
      <PageHeader title="Pipeline" description={isManager ? "Every open deal, by stage" : "Your deals, by stage"}
        action={
          <div className="flex gap-2">
            {me.role === "admin" && <Button variant="secondary" onClick={() => setEditingOdds(true)}><SlidersHorizontal className="size-4" aria-hidden />Probabilities</Button>}
            <div className="flex rounded-lg bg-white p-1 ring-1 ring-line" role="group" aria-label="View">
              {(["board", "list"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)}
                  className={cx("inline-flex min-h-9 items-center gap-1.5 rounded-md px-3 text-sm", view === v ? "bg-forest-900 text-white" : "text-ink")}>
                  {v === "board" ? <LayoutGrid className="size-4" aria-hidden /> : <List className="size-4" aria-hidden />}
                  {v === "board" ? "Board" : "List"}
                </button>
              ))}
            </div>
          </div>
        } />

      {t && (
        <section aria-label="Forecast" className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <div className="rounded-xl bg-white p-4 ring-1 ring-line"><p className="text-sm text-muted">Open pipeline</p>
            <p className="font-display text-2xl text-forest-900"><Money v={t.open_value} /></p><p className="text-xs text-muted">{t.open_count} leads</p></div>
          <div className="rounded-xl bg-white p-4 ring-1 ring-line"><p className="text-sm text-muted">Weighted forecast</p>
            <p className="font-display text-2xl text-forest-900"><Money v={t.weighted_value} /></p><p className="text-xs text-muted">value × stage probability</p></div>
          <div className="rounded-xl bg-white p-4 ring-1 ring-line"><p className="text-sm text-muted">Booked</p>
            <p className="font-display text-2xl text-forest-900"><Money v={t.booked_value} /></p><p className="text-xs text-muted">{t.booked_count} leads</p></div>
          <div className={cx("rounded-xl bg-white p-4 ring-1", t.stale_count ? "ring-amber-300" : "ring-line")}><p className="text-sm text-muted">Quiet for 7+ days</p>
            <p className={cx("font-display text-2xl", t.stale_count ? "text-amber-700" : "text-forest-900")}>{t.stale_count}</p>
            {t.missing_value_count > 0 && <p className="text-xs text-muted">{t.missing_value_count} open with no value or budget</p>}</div>
        </section>
      )}

      {forecast.data && forecast.data.by_project.length > 0 && (
        <details className="mb-5 rounded-xl bg-white ring-1 ring-line">
          <summary className="min-h-11 cursor-pointer px-4 py-3 text-sm font-medium">Forecast by project{isManager && " and by person"}</summary>
          <div className="grid gap-6 px-4 pb-4 md:grid-cols-2">
            {[{ title: "By project", rows: forecast.data.by_project.map((r) => ({ label: r.project?.name ?? "No project chosen", ...r })) },
              ...(isManager ? [{ title: "By person", rows: forecast.data.by_executive.map((r) => ({ label: r.user?.full_name ?? "Unassigned", ...r })) }] : [])]
              .map(({ title, rows }) => (
                <table key={title} className="w-full text-sm">
                  <caption className="mb-1 text-left font-semibold">{title}</caption>
                  <thead className="text-xs text-muted"><tr><th className="text-left font-normal">Name</th><th className="text-right font-normal">Leads</th><th className="text-right font-normal">Weighted</th></tr></thead>
                  <tbody>{rows.map((r) => (
                    <tr key={r.label} className="border-t border-line"><td className="py-1.5">{r.label}</td><td className="text-right tabular-nums">{r.count}</td>
                      <td className="text-right tabular-nums"><Money v={r.weighted_value} /></td></tr>
                  ))}</tbody>
                </table>
              ))}
          </div>
        </details>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-56"><SelectInput label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">All projects</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput></div>
        {isManager && (
          <div className="w-full sm:w-56"><SelectInput label="Whose leads" value={person} onChange={(e) => setPerson(e.target.value)}>
            <option value="">Everyone</option><option value="me">Mine</option>
            {people.data?.filter((p) => p.id !== me.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </SelectInput></div>
        )}
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={staleOnly} onChange={(e) => setStaleOnly(e.target.checked)} />Only quiet leads</label>
        <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} />Show Lost and Junk</label>
      </div>

      {notice && <div className="mb-4"><Alert>{notice}</Alert></div>}
      {board.isPending && <div className="flex gap-3 overflow-hidden">{[0, 1, 2, 3].map((i) => <div key={i} className="h-72 w-72 shrink-0 animate-pulse rounded-xl bg-white" />)}</div>}
      {board.isError && <ErrorState message={errorMessage(board.error, "Couldn’t load the pipeline.")} onRetry={() => void board.refetch()} />}
      {board.data && (
        <div className={board.isPlaceholderData ? "opacity-60" : ""}>
          {view === "board"
            ? <Board board={board.data} onMove={requestMove} showOwner={isManager} />
            : <ListView board={board.data} onMove={requestMove} showOwner={isManager} />}
        </div>
      )}

      {pending && (
        <ReasonDialog move={pending.move} name={pending.name} onCancel={() => setPending(null)}
          onConfirm={(reason) => { move.mutate({ ...pending.move, reason }, { onError: (err) => setNotice(errorMessage(err)) }); setPending(null); }} />
      )}
      {editingOdds && <ProbabilityDialog onClose={() => setEditingOdds(false)} />}
    </>
  );
}
