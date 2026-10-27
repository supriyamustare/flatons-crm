import { useState } from "react";
import { Link } from "react-router";
import { CalendarClock, Plus } from "lucide-react";
import { describeActivity } from "../components/leads/ActivityText";
import { Alert, ErrorState, PageHeader, TextInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useDashboard } from "../hooks/useDashboard";
import type { Business, Dashboard, DashboardQuery, RangeKey } from "../hooks/useDashboard";
import { errorMessage, formatDateTime } from "../lib/api";
import { STATUSES, STATUS_LABELS, formatRupees } from "../lib/leads";
import { formatDue, taskTypeInSentence } from "../lib/tasks";
import { ROLE_LABELS } from "../lib/types";

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "custom", label: "Custom" },
];

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function Kpi({ label, value, hint, to, tone = "plain" }: {
  label: string; value: number | string; hint?: string; to?: string; tone?: "plain" | "alert";
}) {
  const spoken = `${label}: ${value}${hint ? `, ${hint}` : ""}`;
  const body = (
    <>
      <span className="block text-sm text-muted">{label}</span>
      <span className={cx("mt-1 block font-display text-3xl", tone === "alert" ? "text-danger" : "text-forest-900")}>{value}</span>
      {hint && <span className="mt-0.5 block text-xs text-muted">{hint}</span>}
    </>
  );
  const cls = cx("block rounded-xl border bg-white p-4", tone === "alert" ? "border-danger/40" : "border-line");
  return to ? <Link to={to} aria-label={spoken} className={cx(cls, "hover:border-forest-700")}>{body}</Link> : <div className={cls} aria-label={spoken}>{body}</div>;
}

function BusinessSection({ b, isAdmin }: { b: Business; isAdmin: boolean }) {
  const loss = b.profit < 0;
  return (
    <section aria-labelledby="business-h" className="mb-6">
      <h2 id="business-h" className="mb-3 font-semibold">Business</h2>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <Kpi label="Leads generated" value={b.leads_generated} to="/leads" />
        <Kpi label="Leads booked" value={b.leads_booked}
          hint={b.booking_rate === null ? "Booking rate: N/A" : `${Math.round(b.booking_rate * 100)}% of leads generated`} to="/pipeline" />
        <Kpi label="Commission revenue" value={formatRupees(b.revenue)} hint="estimated, from booked leads" />
        <Kpi label="Marketing expense" value={formatRupees(b.expense)} to="/marketing" />
        <Kpi label={loss ? "Estimated loss" : "Estimated profit"} value={(loss ? "−" : "") + formatRupees(Math.abs(b.profit))}
          hint="revenue − expense" tone={loss ? "alert" : "plain"} />
      </div>
      {b.unvalued_bookings > 0 && (
        <p className="mt-2 text-sm text-gold-600">
          {b.unvalued_bookings} booked {b.unvalued_bookings === 1 ? "lead isn’t" : "leads aren’t"} counted in revenue: no project,
          no commission % on the project, or no value or budget on the lead.
          {isAdmin && <> Set commission % under <Link to="/projects" className="underline">Projects</Link>.</>}
        </p>
      )}
    </section>
  );
}

function rangeLabel(d: Dashboard): string {
  const fmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
  const a = new Date(d.date_from + "T00:00:00");
  const b = new Date(d.date_to + "T00:00:00");
  return d.date_from === d.date_to ? fmt.format(a) : `${fmt.format(a)} – ${fmt.format(b)}`;
}

function StatusBreakdown({ data }: { data: Dashboard["leads_by_status"] }) {
  const rows = STATUSES.map((s) => ({ s, n: data[s] ?? 0 })).filter((r) => r.n > 0);
  const max = Math.max(1, ...rows.map((r) => r.n));
  if (rows.length === 0) return <p className="text-sm text-muted">No leads yet.</p>;
  return (
    <ul className="space-y-2">
      {rows.map(({ s, n }) => (
        <li key={s} className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-2 text-sm">
          <span className="truncate text-muted">{STATUS_LABELS[s]}</span>
          <span className="h-2.5 rounded-full bg-forest-50" aria-hidden>
            <span className="block h-full rounded-full bg-forest-700" style={{ width: `${(n / max) * 100}%` }} />
          </span>
          <span className="text-right tabular-nums">{n}</span>
        </li>
      ))}
    </ul>
  );
}

export function DashboardPage() {
  const me = useCurrentUser();
  const firstName = me.full_name.split(" ")[0];
  const isManager = me.role === "admin" || me.role === "manager";
  const isSales = me.role !== "docs";
  const [scope, setScope] = useState<"team" | "mine">(isManager ? "team" : "mine");
  const [range, setRange] = useState<RangeKey>("7d");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const customReady = range !== "custom" || (from && to && from <= to);
  const query: DashboardQuery = range === "custom" ? { range, date_from: from, date_to: to } : { range };
  const dash = useDashboard(scope, query, isSales && Boolean(customReady));

  if (!isSales) {
    return (
      <>
        <PageHeader title={`${greeting()}, ${firstName}`} description={`Signed in as ${ROLE_LABELS[me.role].toLowerCase()}`} />
        <div className="rounded-xl border border-line bg-white p-6">
          <p className="text-ink">You can look up any lead and its history under <Link to="/leads" className="font-medium text-forest-800 underline">Leads</Link>.</p>
          <p className="mt-2 text-sm text-muted">Welcome letters and payment demands arrive in Phase 3.</p>
        </div>
      </>
    );
  }

  const d = dash.data;
  const k = d?.kpis;
  const noLeads = d && d.kpis.total_leads === 0;

  return (
    <>
      <PageHeader title={`${greeting()}, ${firstName}`}
        description={d ? `${scope === "team" ? "Whole team" : "Your work"}, ${rangeLabel(d)}` : undefined} />

      <div className="mb-5 flex flex-wrap items-center gap-2">
        {isManager && (
          <div className="flex rounded-lg bg-white p-1 ring-1 ring-line" role="group" aria-label="Whose numbers">
            {(["team", "mine"] as const).map((s) => (
              <button key={s} type="button" aria-pressed={scope === s} onClick={() => setScope(s)}
                className={cx("min-h-9 rounded-md px-3 text-sm", scope === s ? "bg-forest-900 text-white" : "text-ink")}>
                {s === "team" ? "Team" : "Mine"}
              </button>
            ))}
          </div>
        )}
        <div className="flex rounded-lg bg-white p-1 ring-1 ring-line" role="group" aria-label="Period">
          {RANGES.map((r) => (
            <button key={r.key} type="button" aria-pressed={range === r.key} onClick={() => setRange(r.key)}
              className={cx("min-h-9 rounded-md px-3 text-sm", range === r.key ? "bg-forest-900 text-white" : "text-ink")}>
              {r.label}
            </button>
          ))}
        </div>
      </div>
      {range === "custom" && (
        <div className="mb-5 grid max-w-md grid-cols-2 gap-3">
          <TextInput label="From" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
          <TextInput label="To" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        </div>
      )}
      {range === "custom" && !customReady && <p className="mb-5 text-sm text-muted">Choose a start and end date.</p>}

      {dash.isError && <ErrorState message={errorMessage(dash.error, "Couldn’t load the dashboard.")} onRetry={() => void dash.refetch()} />}
      {dash.isPending && customReady && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3" aria-busy="true" aria-label="Loading dashboard">
          {Array.from({ length: 6 }, (_, i) => <div key={i} className="h-28 animate-pulse rounded-xl bg-white" />)}
        </div>
      )}

      {noLeads && (
        <div className="mb-6 rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center">
          <p className="font-display text-xl text-forest-900">{scope === "mine" ? "No leads assigned to you yet" : "No leads yet"}</p>
          <p className="mt-1 text-sm text-muted">Your numbers will appear here as soon as you start adding enquiries.</p>
          <Link to="/leads/new" className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white">
            <Plus className="size-4" aria-hidden /> Add a lead
          </Link>
        </div>
      )}

      {d && k && (
        <div className={dash.isPlaceholderData ? "opacity-60 transition-opacity" : ""}>
          {d.business && <BusinessSection b={d.business} isAdmin={me.role === "admin"} />}
          <section aria-label="Key numbers" className="grid grid-cols-2 gap-3 lg:grid-cols-3">
            <Kpi label="New leads" value={k.new_leads} hint={`${k.total_leads} in total`} to="/leads" />
            <Kpi label="Follow-ups due today" value={k.follow_ups_today} to="/follow-ups" />
            <Kpi label="Overdue follow-ups" value={k.overdue_follow_ups} to="/follow-ups" tone={k.overdue_follow_ups ? "alert" : "plain"} />
            <Kpi label="Calls" value={k.calls}
              hint={k.connection_rate === null ? "Connection rate: N/A" : `${k.calls_connected} connected (${Math.round(k.connection_rate * 100)}%)`}
              to="/calls" />
            <Kpi label="Site visits scheduled" value={k.visits_scheduled} to="/visits" />
            <Kpi label="Site visits completed" value={k.visits_completed} to="/visits" />
          </section>

          {(d.overdue.length > 0 || d.visits_needing_update.length > 0) && (
            <section className="mt-6 rounded-xl border border-danger/30 bg-white p-5" aria-labelledby="alerts-h">
              <h2 id="alerts-h" className="mb-3 font-semibold">Needs attention</h2>
              <ul className="divide-y divide-line">
                {d.overdue.map((t) => (
                  <li key={`t${t.id}`} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                    <span>
                      <span className="font-medium text-danger">Overdue</span> {taskTypeInSentence(t.task_type)} with{" "}
                      <Link to={`/leads/${t.lead.id}`} className="font-medium text-forest-800 underline-offset-2 hover:underline">{t.lead.name}</Link>
                      {scope === "team" && t.assigned_to && <span className="text-muted"> · {t.assigned_to.full_name}</span>}
                    </span>
                    <span className="text-muted">{formatDue(t.due_at)}</span>
                  </li>
                ))}
                {d.visits_needing_update.map((v) => (
                  <li key={`v${v.id}`} className="flex flex-wrap items-center justify-between gap-2 py-2.5 text-sm">
                    <span>
                      <CalendarClock className="mr-1 inline size-4 text-gold-600" aria-hidden />
                      Visit with <Link to={`/leads/${v.lead.id}`} className="font-medium text-forest-800 underline-offset-2 hover:underline">{v.lead.name}</Link> needs an outcome
                      {scope === "team" && v.host && <span className="text-muted"> · {v.host.full_name}</span>}
                    </span>
                    <span className="text-muted">{formatDue(v.scheduled_at)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <section className="rounded-xl border border-line bg-white p-5" aria-labelledby="status-h">
              <h2 id="status-h" className="mb-4 font-semibold">Leads by status</h2>
              <StatusBreakdown data={d.leads_by_status} />
            </section>
            <section className="rounded-xl border border-line bg-white p-5" aria-labelledby="feed-h">
              <h2 id="feed-h" className="mb-4 font-semibold">Recent activity</h2>
              {d.activity.length === 0 ? (
                <p className="text-sm text-muted">Nothing yet. Calls, notes and visits will show up here.</p>
              ) : (
                <ol className="space-y-3">
                  {d.activity.map((a) => (
                    <li key={a.id} className="text-sm">
                      <Link to={`/leads/${a.lead_id}`} className="font-medium text-forest-800 hover:underline">{a.lead_name}</Link>
                      <span className="text-ink">: {describeActivity(a)}</span>
                      <span className="block text-xs text-muted">{a.actor?.full_name ?? "System"}, {formatDateTime(a.created_at)}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        </div>
      )}
      {range === "custom" && from && to && from > to && <Alert>The start date must be before the end date.</Alert>}
    </>
  );
}
