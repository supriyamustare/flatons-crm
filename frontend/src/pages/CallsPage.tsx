import { useState } from "react";
import { Link } from "react-router";
import { PhoneIncoming, PhoneOutgoing } from "lucide-react";
import { Badge, Button, ErrorState, PageHeader, SelectInput } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useCalls } from "../hooks/useCalls";
import type { CallQuery } from "../hooks/useCalls";
import { useAssignableUsers } from "../hooks/useLeads";
import { errorMessage, formatDateTime } from "../lib/api";
import { CONNECTED, NOT_CONNECTED, OUTCOME_LABELS, formatDuration } from "../lib/calls";
import type { CallOutcome } from "../lib/calls";

const PERIODS = { today: "Today", "7d": "Last 7 days", "30d": "Last 30 days", all: "All time" } as const;
type Period = keyof typeof PERIODS;

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function periodRange(p: Period): { date_from?: string; date_to?: string } {
  if (p === "all") return {};
  const today = new Date();
  const from = new Date(today);
  if (p === "7d") from.setDate(from.getDate() - 6);
  if (p === "30d") from.setDate(from.getDate() - 29);
  return { date_from: isoDate(from), date_to: isoDate(today) };
}

export function CallsPage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const people = useAssignableUsers(isManager);
  const [period, setPeriod] = useState<Period>("7d");
  const [outcome, setOutcome] = useState<CallOutcome | "">("");
  const [person, setPerson] = useState("");
  const [page, setPage] = useState(1);

  const query: CallQuery = {
    ...periodRange(period), page,
    outcome: outcome || undefined,
    mine: person === "me" || undefined,
    user_id: person && person !== "me" ? Number(person) : undefined,
  };
  const calls = useCalls(query);
  const total = calls.data?.total ?? 0;
  const pageSize = calls.data?.page_size ?? 50;
  const rate = total ? Math.round(((calls.data?.connected ?? 0) / total) * 100) : null;
  const reset = () => setPage(1);

  return (
    <>
      <PageHeader title="Calls" description={isManager ? "Every logged call across the team" : "Calls you’ve logged"} />

      <div className="mb-4 grid gap-3 sm:grid-cols-3 lg:max-w-3xl">
        <SelectInput label="Period" value={period} onChange={(e) => { setPeriod(e.target.value as Period); reset(); }}>
          {Object.entries(PERIODS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </SelectInput>
        <SelectInput label="Outcome" value={outcome} onChange={(e) => { setOutcome(e.target.value as CallOutcome | ""); reset(); }}>
          <option value="">All outcomes</option>
          <optgroup label="Spoke to them">{CONNECTED.map((o) => <option key={o} value={o}>{OUTCOME_LABELS[o]}</option>)}</optgroup>
          <optgroup label="Didn’t connect">{NOT_CONNECTED.map((o) => <option key={o} value={o}>{OUTCOME_LABELS[o]}</option>)}</optgroup>
        </SelectInput>
        {isManager && (
          <SelectInput label="Who" value={person} onChange={(e) => { setPerson(e.target.value); reset(); }}>
            <option value="">Everyone</option>
            <option value="me">Me</option>
            {people.data?.filter((p) => p.id !== me.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </SelectInput>
        )}
      </div>

      {calls.isSuccess && total > 0 && (
        <p className="mb-3 text-sm text-muted">
          {total} call{total === 1 ? "" : "s"}
          {!outcome && rate !== null && <>, {calls.data.connected} connected ({rate}%)</>}
        </p>
      )}

      {calls.isPending && <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-20 animate-pulse rounded-xl bg-white" />)}</div>}
      {calls.isError && <ErrorState message={errorMessage(calls.error, "Couldn’t load calls.")} onRetry={() => void calls.refetch()} />}
      {calls.isSuccess && total === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <p className="font-display text-xl text-forest-900">No calls in this period</p>
          <p className="mt-1 text-sm text-muted">Log a call from any lead with the Log call button.</p>
        </div>
      )}

      {calls.isSuccess && total > 0 && (
        <ul className={`space-y-2 ${calls.isPlaceholderData ? "opacity-60" : ""}`}>
          {calls.data.items.map((c) => {
            const Icon = c.direction === "incoming" ? PhoneIncoming : PhoneOutgoing;
            return (
              <li key={c.id} className="rounded-xl border border-line bg-white p-4">
                <div className="flex items-start gap-3">
                  <span aria-hidden className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-full bg-forest-50 text-forest-800">
                    <Icon className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <Link to={`/leads/${c.lead.id}`} className="text-sm font-medium text-forest-800 hover:underline">{c.lead.name}</Link>
                      <Badge tone={c.connected ? "neutral" : "muted"}>{OUTCOME_LABELS[c.outcome]}</Badge>
                    </div>
                    <p className="text-sm text-muted">
                      {formatDateTime(c.called_at)}
                      {c.duration_sec ? <> · {formatDuration(c.duration_sec)}</> : null}
                      {isManager && c.user && <> · {c.user.full_name}</>}
                      <span className="sr-only">, {c.direction === "incoming" ? "incoming call" : "outgoing call"}</span>
                    </p>
                    {c.notes && <p className="mt-1.5 text-sm whitespace-pre-wrap">{c.notes}</p>}
                  </div>
                </div>
              </li>
            );
          })}
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
    </>
  );
}
