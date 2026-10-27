import { useState } from "react";
import { useSearchParams } from "react-router";
import type { ReactNode } from "react";
import { Download } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ErrorState, PageHeader, SelectInput, TextInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useAssignableUsers, useProjects } from "../hooks/useLeads";
import { exportUrl, useReport } from "../hooks/useReports";
import type { ReportQuery } from "../hooks/useReports";
import { errorMessage } from "../lib/api";
import { formatRupees } from "../lib/leads";
import { CHANNEL_LABELS } from "../lib/marketing";
import { REPORT_LABELS, formatRate } from "../lib/reports";
import type { CallsReport, CampaignsReport, ConversionReport, RangeKey, ReportKind, StaffReport, VisitsReport } from "../lib/reports";
import { VISIT_SOURCE_LABELS } from "../lib/visits";
import type { VisitSource } from "../lib/visits";

const GREEN = "#235a3e";
const GOLD = "#c9a13b";
const RANGES: { key: RangeKey; label: string }[] = [
  { key: "today", label: "Today" }, { key: "7d", label: "Last 7 days" }, { key: "30d", label: "Last 30 days" }, { key: "custom", label: "Custom" },
];
const money = (v: number | null) => (v === null ? "N/A" : formatRupees(v));

/** Simple accessible table: first column is the row header. */
function Table({ caption, head, rows, total }: { caption: string; head: string[]; rows: ReactNode[][]; total?: ReactNode[] }) {
  return (
    <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
      <table className="w-full min-w-[560px] text-sm">
        <caption className="px-4 pt-3 text-left font-semibold">{caption}</caption>
        <thead className="text-xs text-muted"><tr>{head.map((h, i) => <th key={h} scope="col" className={cx("px-3 py-2 font-normal", i ? "text-right" : "text-left")}>{h}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={head.length} className="px-3 py-6 text-center text-muted">Nothing in this period.</td></tr>}
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-line">{r.map((c, j) => j === 0
              ? <th key={j} scope="row" className="px-3 py-2 text-left font-normal">{c}</th>
              : <td key={j} className="px-3 py-2 text-right tabular-nums">{c}</td>)}</tr>
          ))}
          {total && rows.length > 0 && <tr className="border-t-2 border-line font-semibold">{total.map((c, j) => j === 0
            ? <th key={j} scope="row" className="px-3 py-2 text-left">{c}</th> : <td key={j} className="px-3 py-2 text-right tabular-nums">{c}</td>)}</tr>}
        </tbody>
      </table>
    </div>
  );
}

function Chart({ title, children }: { title: string; children: ReactNode }) {
  return (
    <figure className="rounded-xl bg-white p-4 ring-1 ring-line">
      <figcaption className="mb-2 font-semibold">{title}</figcaption>
      <div className="h-64" aria-hidden>{children}</div>
      <p className="sr-only">The same figures are listed in the table below.</p>
    </figure>
  );
}

function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-xl bg-white p-4 ring-1 ring-line">
      <p className="text-sm text-muted">{label}</p><p className="font-display text-2xl text-forest-900">{value}</p>
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

const name = (u: { full_name: string } | null) => u?.full_name ?? "Unassigned";
const short = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });

function CallsView({ r }: { r: CallsReport }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Calls" value={r.totals.calls} /><Stat label="Connected" value={r.totals.connected} />
        <Stat label="Connection rate" value={formatRate(r.totals.connection_rate)} /><Stat label="Talk time" value={`${r.totals.talk_minutes} min`} />
      </div>
      {r.by_day.length > 1 && (
        <Chart title="Calls per day">
          <ResponsiveContainer><LineChart data={r.by_day.map((d) => ({ ...d, day: short(d.day) }))}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d9e1db" /><XAxis dataKey="day" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} />
            <Tooltip /><Legend /><Line type="monotone" dataKey="calls" name="Calls" stroke={GREEN} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="connected" name="Connected" stroke={GOLD} strokeWidth={2} dot={false} />
          </LineChart></ResponsiveContainer>
        </Chart>
      )}
      <Table caption="By person" head={["Person", "Calls", "Connected", "Connection rate", "Talk time (min)"]}
        rows={r.rows.map((x) => [name(x.user), x.calls, x.connected, formatRate(x.connection_rate), x.talk_minutes])}
        total={["Total", r.totals.calls, r.totals.connected, formatRate(r.totals.connection_rate), r.totals.talk_minutes]} />
    </>
  );
}

function VisitsView({ r }: { r: VisitsReport }) {
  const head = ["Visits", "Completed", "No-show", "Cancelled", "Awaiting outcome", "Completion rate"];
  const vals = (x: VisitsReport["totals"]) => [x.visits, x.completed, x.no_show, x.cancelled, x.scheduled, formatRate(x.completion_rate)];
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Visits" value={r.totals.visits} /><Stat label="Completed" value={r.totals.completed} />
        <Stat label="No-shows" value={r.totals.no_show} /><Stat label="Completion rate" value={formatRate(r.totals.completion_rate)} />
      </div>
      {r.by_project.length > 0 && (
        <Chart title="Visits by project">
          <ResponsiveContainer><BarChart data={r.by_project.map((x) => ({ name: x.project.name, Completed: x.completed, "No-show": x.no_show, Other: x.cancelled + x.scheduled }))}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d9e1db" /><XAxis dataKey="name" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} />
            <Tooltip /><Legend /><Bar dataKey="Completed" stackId="a" fill={GREEN} /><Bar dataKey="No-show" stackId="a" fill={GOLD} /><Bar dataKey="Other" stackId="a" fill="#b8c4bd" />
          </BarChart></ResponsiveContainer>
        </Chart>
      )}
      <Table caption="By project" head={["Project", ...head]} rows={r.by_project.map((x) => [x.project.name, ...vals(x)])} total={["Total", ...vals(r.totals)]} />
      <Table caption="By how the visit came about" head={["Source", ...head]} rows={r.by_source.map((x) => [VISIT_SOURCE_LABELS[x.source as VisitSource] ?? x.source, ...vals(x)])} />
      <Table caption="By person" head={["Person", ...head]} rows={r.by_person.map((x) => [name(x.user), ...vals(x)])} />
    </>
  );
}

function ConversionView({ r }: { r: ConversionReport }) {
  const t = r.totals;
  const head = ["Leads", "Visited", "Booked", "Visit rate", "Visit to booking", "Conversion"];
  const vals = (x: ConversionReport["totals"]) => [x.leads, x.visited, x.booked, formatRate(x.visit_rate), formatRate(x.visit_to_booking_rate), formatRate(x.conversion_rate)];
  return (
    <>
      <section aria-label="Funnel" className="grid grid-cols-3 gap-3">
        <Stat label="Leads" value={t.leads} hint="created in the period" />
        <Stat label="Visited" value={t.visited} hint={`${formatRate(t.visit_rate)} of leads`} />
        <Stat label="Booked" value={t.booked} hint={`${formatRate(t.conversion_rate)} of leads`} />
      </section>
      <Chart title="Funnel by person">
        <ResponsiveContainer><BarChart data={r.by_person.map((x) => ({ name: name(x.user), Leads: x.leads, Visited: x.visited, Booked: x.booked }))}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d9e1db" /><XAxis dataKey="name" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} />
          <Tooltip /><Legend /><Bar dataKey="Leads" fill="#b8c4bd" /><Bar dataKey="Visited" fill={GREEN} /><Bar dataKey="Booked" fill={GOLD} />
        </BarChart></ResponsiveContainer>
      </Chart>
      <Table caption="By person" head={["Person", ...head]} rows={r.by_person.map((x) => [name(x.user), ...vals(x)])} total={["Total", ...vals(t)]} />
      <Table caption="By project" head={["Project", ...head]} rows={r.by_project.map((x) => [x.project?.name ?? "No project", ...vals(x)])} />
    </>
  );
}

function CampaignsView({ r }: { r: CampaignsReport }) {
  const t = r.totals;
  return (
    <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Spend" value={formatRupees(t.spend)} /><Stat label="Attributed leads" value={t.leads} hint={`${r.unattributed_leads} other leads had no campaign`} />
        <Stat label="Cost per lead" value={money(t.cost_per_lead)} hint="spend ÷ attributed leads" /><Stat label="Cost per booking" value={money(t.cost_per_booking)} />
      </div>
      {r.rows.length > 0 && (
        <Chart title="Spend and cost per lead by campaign">
          <ResponsiveContainer><BarChart data={r.rows.map((x) => ({ name: x.name.replace(/^Demo: /, ""), Spend: x.spend, "Cost per lead": x.cost_per_lead ?? 0 }))}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d9e1db" /><XAxis dataKey="name" fontSize={11} interval={0} /><YAxis fontSize={12} tickFormatter={(v) => formatRupees(Number(v))} width={70} />
            <Tooltip formatter={(v) => formatRupees(Number(v))} /><Legend /><Bar dataKey="Spend" fill={GREEN} /><Bar dataKey="Cost per lead" fill={GOLD} />
          </BarChart></ResponsiveContainer>
        </Chart>
      )}
      <Table caption="By campaign" head={["Campaign", "Spend", "Leads", "Visited", "Booked", "Cost per lead", "Cost per visit", "Cost per booking"]}
        rows={r.rows.map((x) => [<span key="n">{x.name}<span className="block text-xs text-muted">{x.channel ? CHANNEL_LABELS[x.channel] : ""}</span></span>,
          formatRupees(x.spend), x.leads, x.visited, x.booked, money(x.cost_per_lead), money(x.cost_per_visit), money(x.cost_per_booking)])}
        total={["All campaigns", formatRupees(t.spend), t.leads, t.visited, t.booked, money(t.cost_per_lead), money(t.cost_per_visit), money(t.cost_per_booking)]} />
    </>
  );
}

function StaffView({ r }: { r: StaffReport }) {
  return (
    <>
      <Chart title="Activity by person">
        <ResponsiveContainer><BarChart data={r.rows.map((x) => ({ name: x.user.full_name, Calls: x.calls, "Visits completed": x.visits_completed, Bookings: x.bookings }))}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d9e1db" /><XAxis dataKey="name" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} />
          <Tooltip /><Legend /><Bar dataKey="Calls" fill="#b8c4bd" /><Bar dataKey="Visits completed" fill={GREEN} /><Bar dataKey="Bookings" fill={GOLD} />
        </BarChart></ResponsiveContainer>
      </Chart>
      <Table caption="By person" head={["Person", "Leads", "Calls", "Connected", "Connection rate", "Visits completed", "Bookings", "Lead to booking"]}
        rows={r.rows.map((x) => [x.user.full_name, x.leads, x.calls, x.connected, formatRate(x.connection_rate), x.visits_completed, x.bookings, formatRate(x.lead_to_booking_rate)])}
        total={["Total", r.totals.leads, r.totals.calls, r.totals.connected, formatRate(r.totals.connection_rate), r.totals.visits_completed, r.totals.bookings, formatRate(r.totals.lead_to_booking_rate)]} />
    </>
  );
}

export function ReportsPage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const kinds: ReportKind[] = isManager ? ["calls", "visits", "conversion", "campaigns", "staff"] : ["calls", "visits", "conversion", "staff"];
  // The dashboard links here with ?report=staff&person=ID
  const [params] = useSearchParams();
  const fromLink = params.get("report") as ReportKind | null;
  const [kind, setKind] = useState<ReportKind>(fromLink && kinds.includes(fromLink) ? fromLink : "calls");
  const [range, setRange] = useState<RangeKey>("30d");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [projectId, setProjectId] = useState("");
  const [person, setPerson] = useState(isManager ? (params.get("person") ?? "") : "");
  const projects = useProjects();
  const people = useAssignableUsers(isManager);
  const ready = range !== "custom" || Boolean(from && to && from <= to);
  const q: ReportQuery = {
    range, ...(range === "custom" ? { date_from: from, date_to: to } : {}),
    project_id: projectId ? Number(projectId) : undefined,
    user_id: isManager && person && kind !== "campaigns" ? Number(person) : undefined,
  };
  const rep = useReport(kind, q, ready);
  const d = rep.data;

  return (
    <>
      <PageHeader title="Reports" description={isManager ? "How the team and marketing are doing" : "How your work is going"}
        action={isManager && d ? (
          <a href={exportUrl(kind, q)} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-white px-4 text-sm font-medium ring-1 ring-line hover:bg-forest-50">
            <Download className="size-4" aria-hidden />Download CSV
          </a>) : undefined} />
      <div role="tablist" aria-label="Reports" className="mb-4 flex gap-1 overflow-x-auto rounded-xl bg-white p-1 ring-1 ring-line">
        {kinds.map((k) => (
          <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)}
            className={cx("min-h-11 flex-auto whitespace-nowrap rounded-lg px-3 text-sm", kind === k ? "bg-forest-900 text-white" : "hover:bg-forest-50")}>
            {REPORT_LABELS[k]}
          </button>
        ))}
      </div>
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div className="flex flex-wrap rounded-lg bg-white p-1 ring-1 ring-line" role="group" aria-label="Period">
          {RANGES.map((r) => (
            <button key={r.key} type="button" aria-pressed={range === r.key} onClick={() => setRange(r.key)}
              className={cx("min-h-9 rounded-md px-3 text-sm", range === r.key ? "bg-forest-900 text-white" : "")}>{r.label}</button>
          ))}
        </div>
        {range === "custom" && (<>
          <div className="w-40"><TextInput label="From" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></div>
          <div className="w-40"><TextInput label="To" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></div>
        </>)}
        <div className="w-full sm:w-52"><SelectInput label="Project" value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          <option value="">All projects</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput></div>
        {isManager && kind !== "campaigns" && (
          <div className="w-full sm:w-52"><SelectInput label="Person" value={person} onChange={(e) => setPerson(e.target.value)}>
            <option value="">Everyone</option>{people.data?.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
          </SelectInput></div>
        )}
      </div>
      {!ready && <p className="text-sm text-muted">Choose a start and end date.</p>}
      {rep.isError && <ErrorState message={errorMessage(rep.error, "Couldn’t load the report.")} onRetry={() => void rep.refetch()} />}
      {rep.isPending && ready && <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="h-24 animate-pulse rounded-xl bg-white" />)}</div>}
      {d && (
        <div className={cx("space-y-5", rep.isPlaceholderData && "opacity-60")}>
          <p className="text-sm text-muted">{short(d.date_from)}{d.date_from !== d.date_to ? ` – ${short(d.date_to)}` : ""}{d.scope === "mine" ? " · your own figures" : ""}</p>
          {kind === "calls" && <CallsView r={d as CallsReport} />}
          {kind === "visits" && <VisitsView r={d as VisitsReport} />}
          {kind === "conversion" && <ConversionView r={d as ConversionReport} />}
          {kind === "campaigns" && <CampaignsView r={d as CampaignsReport} />}
          {kind === "staff" && <StaffView r={d as StaffReport} />}
          <details className="rounded-xl bg-white ring-1 ring-line">
            <summary className="min-h-11 cursor-pointer px-4 py-3 text-sm font-medium">How these are calculated</summary>
            <dl className="space-y-2 px-4 pb-4 text-sm">
              {Object.entries(d.definitions).map(([k, v]) => <div key={k}><dt className="font-medium">{k}</dt><dd className="text-muted">{v}</dd></div>)}
              <div><dt className="font-medium">N/A</dt><dd className="text-muted">Shown instead of a percentage or cost when there is nothing to divide by (for example, no calls in the period).</dd></div>
            </dl>
          </details>
        </div>
      )}
    </>
  );
}
