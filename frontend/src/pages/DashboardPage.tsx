import { useState } from "react";
import { Link } from "react-router";
import { describeActivity } from "../components/leads/ActivityText";
import { BusinessSection, RANGES, TeamPerformance, greeting, rangeLabel } from "../components/dashboard/ManagerSections";
import { InsightsSections } from "../components/dashboard/Insights";
import { OverviewSections, summaryLine } from "../components/dashboard/Overview";
import { ErrorState, PageHeader, TextInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useDashboard } from "../hooks/useDashboard";
import type { Dashboard, DashboardQuery, RangeKey } from "../hooks/useDashboard";
import { useInsights } from "../hooks/useInsights";
import { useOverview } from "../hooks/useOverview";
import type { LeadTab } from "../hooks/useOverview";
import { errorMessage, formatDateTime } from "../lib/api";
import { ROLE_LABELS } from "../lib/types";

const initials = (name: string) => name.split(" ").map((p) => p[0]).slice(0, 2).join("").toUpperCase();

/** Who the top of the dashboard is about: the whole team, or one person. */
function PersonPicker({ people, value, onChange }: { people: { id: number; full_name: string }[]; value: number | null; onChange: (id: number | null) => void }) {
  const chip = (id: number | null, label: string, short: string) => (
    <button key={id ?? "all"} type="button" aria-pressed={value === id} onClick={() => onChange(id)}
      className="flex w-16 shrink-0 flex-col items-center gap-1 rounded-lg py-1 text-xs focus-visible:ring-2 focus-visible:ring-forest-700">
      <span aria-hidden className={cx("grid size-11 place-items-center rounded-full text-sm font-semibold ring-2 transition",
        value === id ? "bg-forest-900 text-white ring-gold-500" : "bg-forest-50 text-forest-900 ring-transparent hover:ring-line")}>{short}</span>
      <span className={cx("w-full truncate text-center", value === id ? "font-semibold text-forest-900" : "text-muted")}>{label}</span>
    </button>
  );
  return (
    <div role="group" aria-label="Show figures for" className="-mx-1 mb-5 flex gap-1 overflow-x-auto px-1 pb-1">
      {chip(null, "All team", "All")}
      {people.map((p) => chip(p.id, p.full_name.split(" ")[0], initials(p.full_name)))}
    </div>
  );
}

function ActivityFeed({ items }: { items: Dashboard["activity"] }) {
  return (
    <section className="mt-6 rounded-xl border border-line bg-white p-5" aria-labelledby="feed-h">
      <h2 id="feed-h" className="mb-4 font-semibold">Recent activity</h2>
      {items.length === 0 ? (
        <p className="text-sm text-muted">Nothing yet. Calls, notes and visits will show up here.</p>
      ) : (
        <ol className="space-y-3">
          {items.map((a) => (
            <li key={a.id} className="text-sm">
              <Link to={`/leads/${a.lead_id}`} className="font-medium text-forest-800 hover:underline">{a.lead_name}</Link>
              <span className="text-ink">: {describeActivity(a)}</span>
              <span className="block text-xs text-muted">{a.actor?.full_name ?? "System"}, {formatDateTime(a.created_at)}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export function DashboardPage() {
  const me = useCurrentUser();
  const firstName = me.full_name.split(" ")[0];
  const isManager = me.role === "admin" || me.role === "manager";
  const isSales = me.role !== "docs";
  const [person, setPerson] = useState<number | null>(null);
  const [tab, setTab] = useState<LeadTab>("fresh");
  const [range, setRange] = useState<RangeKey>("30d");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const overview = useOverview(isManager ? person : null, tab);
  const insights = useInsights(isManager ? person : null);
  const customReady = range !== "custom" || Boolean(from && to && from <= to);
  const query: DashboardQuery = range === "custom" ? { range, date_from: from, date_to: to } : { range };
  // Business, team table and activity feed (managers: team-wide; executives: their own feed)
  const dash = useDashboard(isManager ? "team" : "mine", isManager ? query : { range: "7d" }, isSales && customReady);

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

  const o = overview.data;
  const d = dash.data;
  return (
    <>
      <PageHeader title={`${greeting()}, ${firstName}`}
        description={o ? summaryLine(o) : isManager ? "Whole team" : "Your work"} />

      {isManager && o && <PersonPicker people={o.people} value={person} onChange={setPerson} />}
      {overview.isPending && <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="h-28 animate-pulse rounded-xl bg-white" />)}</div>}
      {overview.isError && <ErrorState message={errorMessage(overview.error, "Couldn’t load the dashboard.")} onRetry={() => void overview.refetch()} />}
      {o && (
        <div className={cx(overview.isPlaceholderData && "opacity-60 transition-opacity")}>
          <OverviewSections o={o} tab={tab} onTab={setTab} isPerson={o.scope === "person"} />
        </div>
      )}
      {insights.data && (
        <div className={cx(insights.isPlaceholderData && "opacity-60 transition-opacity")}>
          <InsightsSections ins={insights.data} />
        </div>
      )}

      {isManager && (
        <section aria-labelledby="biz-team-h" className="mt-8 border-t border-line pt-6">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 id="biz-team-h" className="font-display text-xl text-forest-900">Business and team</h2>
              {d && <p className="text-sm text-muted">{rangeLabel(d)}</p>}
            </div>
            <div className="flex flex-wrap items-end gap-2">
              <div className="flex rounded-lg bg-white p-1 ring-1 ring-line" role="group" aria-label="Period">
                {RANGES.map((r) => (
                  <button key={r.key} type="button" aria-pressed={range === r.key} onClick={() => setRange(r.key)}
                    className={cx("min-h-9 rounded-md px-3 text-sm", range === r.key ? "bg-forest-900 text-white" : "")}>{r.label}</button>
                ))}
              </div>
              {range === "custom" && (<>
                <div className="w-40"><TextInput label="From" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></div>
                <div className="w-40"><TextInput label="To" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></div>
              </>)}
            </div>
          </div>
          {dash.isError && <ErrorState message={errorMessage(dash.error, "Couldn’t load business figures.")} onRetry={() => void dash.refetch()} />}
          {d?.business && <BusinessSection b={d.business} isAdmin={me.role === "admin"} />}
          {d?.team && <TeamPerformance team={d.team} periodLabel={rangeLabel(d)} />}
        </section>
      )}

      {d && <ActivityFeed items={d.activity} />}
    </>
  );
}
