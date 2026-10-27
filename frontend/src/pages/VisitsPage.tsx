import { useState } from "react";
import { Plus } from "lucide-react";
import { ScheduleVisitDialog, VisitOutcomeDialog } from "../components/visits/VisitDialogs";
import { VisitItem } from "../components/visits/VisitItem";
import { Button, ErrorState, PageHeader, SelectInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useAssignableUsers, useProjects } from "../hooks/useLeads";
import { useVisits } from "../hooks/useVisits";
import type { VisitQuery } from "../hooks/useVisits";
import { errorMessage } from "../lib/api";
import type { Visit, VisitView } from "../lib/visits";

const VIEWS: { key: VisitView; label: string }[] = [
  { key: "upcoming", label: "Scheduled" },
  { key: "completed", label: "Completed" },
  { key: "missed", label: "No-shows and cancelled" },
];

const EMPTY: Record<VisitView, string> = {
  upcoming: "No visits scheduled.",
  completed: "Completed visits will appear here.",
  missed: "No missed or cancelled visits.",
};

export function VisitsPage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const projects = useProjects();
  const people = useAssignableUsers(isManager);
  const [view, setView] = useState<VisitView>("upcoming");
  const [projectId, setProjectId] = useState("");
  const [person, setPerson] = useState("");
  const [page, setPage] = useState(1);
  const [updating, setUpdating] = useState<Visit | null>(null);
  const [scheduling, setScheduling] = useState(false);

  const query: VisitQuery = {
    view, page,
    project_id: projectId ? Number(projectId) : undefined,
    mine: person === "me" || undefined,
    host_id: person && person !== "me" ? Number(person) : undefined,
  };
  const visits = useVisits(query);
  const counts = visits.data?.counts;
  const total = visits.data?.total ?? 0;
  const pageSize = visits.data?.page_size ?? 50;

  return (
    <>
      <PageHeader
        title="Site visits"
        action={<Button onClick={() => setScheduling(true)}><Plus className="size-4" aria-hidden />Schedule visit</Button>}
      />

      <div role="tablist" aria-label="Visit views" className="mb-4 flex gap-1 rounded-xl bg-white p-1 ring-1 ring-line">
        {VIEWS.map(({ key, label }) => {
          const n = key === "upcoming" ? counts?.upcoming : undefined;
          return (
            <button key={key} role="tab" aria-selected={view === key} aria-label={n ? `${label}, ${n}` : label}
              onClick={() => { setView(key); setPage(1); }}
              className={cx("flex min-h-11 flex-auto items-center justify-center gap-1 rounded-lg px-2 text-[13px] sm:flex-1 sm:px-3 sm:text-sm",
                view === key ? "bg-forest-900 text-white" : "text-ink hover:bg-forest-50")}>
              {key === "missed" ? <><span className="sm:hidden">Missed</span><span className="hidden sm:inline">{label}</span></> : label}
              {n ? <span aria-hidden className={cx("rounded-full px-1.5 text-xs font-semibold", view === key ? "bg-white/20" : "bg-forest-50 text-forest-800")}>{n}</span> : null}
            </button>
          );
        })}
      </div>

      {counts && counts.needs_update > 0 && view === "upcoming" && (
        <p className="mb-4 rounded-lg bg-gold-100 px-3 py-2 text-sm text-ink">
          {counts.needs_update} visit{counts.needs_update === 1 ? " has" : "s have"} passed without an update.
        </p>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:max-w-xl">
        <SelectInput label="Project" value={projectId} onChange={(e) => { setProjectId(e.target.value); setPage(1); }}>
          <option value="">All projects</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        {isManager && (
          <SelectInput label="Host" value={person} onChange={(e) => { setPerson(e.target.value); setPage(1); }}>
            <option value="">Everyone</option>
            <option value="me">Me</option>
            {people.data?.filter((p) => p.id !== me.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </SelectInput>
        )}
      </div>

      {visits.isPending && <div className="space-y-2">{[0, 1].map((i) => <div key={i} className="h-28 animate-pulse rounded-xl bg-white" />)}</div>}
      {visits.isError && <ErrorState message={errorMessage(visits.error, "Couldn’t load visits.")} onRetry={() => void visits.refetch()} />}
      {visits.isSuccess && total === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <p className="font-display text-xl text-forest-900">{EMPTY[view]}</p>
          {view === "upcoming" && (
            <Button className="mt-5" onClick={() => setScheduling(true)}><Plus className="size-4" aria-hidden />Schedule a visit</Button>
          )}
        </div>
      )}
      {visits.isSuccess && total > 0 && (
        <ul className={`space-y-2 ${visits.isPlaceholderData ? "opacity-60" : ""}`}>
          {visits.data.items.map((v) => (
            <VisitItem key={v.id} visit={v} onUpdate={() => setUpdating(v)}
              canAct={isManager || v.host?.id === me.id || me.role === "executive"} />
          ))}
        </ul>
      )}
      {total > pageSize && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted">
          <span>{(page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)} of {total}</span>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <Button variant="secondary" disabled={page * pageSize >= total} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </div>
      )}
      {updating && <VisitOutcomeDialog visit={updating} onClose={() => setUpdating(null)} />}
      {scheduling && <ScheduleVisitDialog onClose={() => setScheduling(false)} />}
    </>
  );
}
