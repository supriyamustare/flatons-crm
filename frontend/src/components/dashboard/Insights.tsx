import type { ReactNode } from "react";
import { Link } from "react-router";
import { Building2 } from "lucide-react";
import { cx } from "../ui";
import type { Insights } from "../../hooks/useInsights";
import { UNIT_TYPE_LABELS } from "../../lib/inventory";
import { SOURCE_LABELS, formatRupees } from "../../lib/leads";

const n = (v: number) => v.toLocaleString("en-IN");

function Panel({ title, subtitle, action, children, className }: { title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  const id = `p-${title.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <section aria-labelledby={id} className={cx("min-w-0 rounded-xl bg-white p-4 ring-1 ring-line", className)}>
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <div><h2 id={id} className="font-semibold">{title}</h2>{subtitle && <p className="text-xs text-muted">{subtitle}</p>}</div>
        {action}
      </div>
      {children}
    </section>
  );
}

function ProjectInventory({ projects }: { projects: Insights["projects"] }) {
  const withStock = projects.filter((p) => p.total > 0);
  const others = projects.filter((p) => p.total === 0);
  const range = (p: Insights["projects"][number]) =>
    p.price_min === null ? null : p.price_min === p.price_max ? formatRupees(p.price_min) : `${formatRupees(p.price_min)} – ${formatRupees(p.price_max!)}`;
  return (
    <Panel title="Project inventory" subtitle="Units sold, on hold and available" action={<Link to="/projects" className="text-sm font-medium text-forest-800 hover:underline">All projects →</Link>}>
      {withStock.length === 0 && <p className="text-sm text-muted">No inventory added yet. Add buildings and units under Projects.</p>}
      <ul className="space-y-3">
        {withStock.map((p) => {
          const w = (v: number) => `${(v / p.total) * 100}%`;
          return (
            <li key={p.id} className="rounded-lg p-3 ring-1 ring-line">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-forest-50 text-forest-800"><Building2 className="size-4" aria-hidden /></span>
                  <div className="min-w-0">
                    <Link to={`/projects/${p.id}`} className="font-medium text-forest-900 hover:underline">{p.name}</Link>
                    <p className="truncate text-xs text-muted">{[p.unit_types.map((t) => UNIT_TYPE_LABELS[t]).join(", "), p.location].filter(Boolean).join(" · ")}</p>
                  </div>
                </div>
                <div className="text-right text-sm">
                  {range(p) && <p className="font-medium text-forest-800">{range(p)}</p>}
                  {p.bookings_this_month > 0 && <p className="text-xs text-muted">{p.bookings_this_month} booked this month · {formatRupees(p.booked_value_this_month)}</p>}
                </div>
              </div>
              <div className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-paper" role="img"
                aria-label={`${p.name}: ${p.sold} sold, ${p.blocked} on hold, ${p.available} available of ${p.total}`}>
                <span className="bg-forest-700" style={{ width: w(p.sold) }} />
                <span className="bg-gold-500" style={{ width: w(p.blocked) }} />
              </div>
              <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className="flex flex-wrap gap-3">
                  <span><span className="mr-1 inline-block size-2 rounded-full bg-forest-700" aria-hidden />Sold <b>{n(p.sold)}</b></span>
                  <span><span className="mr-1 inline-block size-2 rounded-full bg-gold-500" aria-hidden />On hold <b>{n(p.blocked)}</b></span>
                  <span><span className="mr-1 inline-block size-2 rounded-full bg-line" aria-hidden />Available <b>{n(p.available)}</b></span>
                </span>
                <span className="rounded-full bg-forest-50 px-2 py-0.5 font-semibold text-forest-800">{p.sold_pct ?? 0}% sold</span>
              </div>
            </li>
          );
        })}
      </ul>
      {others.length > 0 && <p className="mt-2 text-xs text-muted">No units added: {others.map((p) => p.name).join(", ")}</p>}
    </Panel>
  );
}

const STATUS_META: Record<string, { label: string; color: string; hint: string }> = {
  working: { label: "Being worked", color: "#235a3e", hint: "activity in the last 7 days" },
  quiet: { label: "Gone quiet", color: "#c9a13b", hint: "no activity for 7+ days" },
  unassigned: { label: "Unassigned", color: "#d97706", hint: "waiting in New enquiries" },
  booked: { label: "Booked", color: "#4f9a6f", hint: "" },
  dead: { label: "Lost or junk", color: "#b8c4bd", hint: "" },
};

function LeadStatus({ ins }: { ins: Insights }) {
  const total = ins.total_leads || 1;
  let offset = 0;
  const r = 40, c = 2 * Math.PI * r;
  return (
    <Panel title="Lead status" subtitle={`${n(ins.total_leads)} leads in total`}>
      <div className="flex flex-wrap items-center gap-4">
        <svg viewBox="0 0 100 100" className="size-32 shrink-0 -rotate-90" aria-hidden>
          <circle cx="50" cy="50" r={r} fill="none" stroke="#eef2ef" strokeWidth="12" />
          {ins.lead_status.filter((s) => s.count).map((s) => {
            const len = (s.count / total) * c;
            const el = <circle key={s.key} cx="50" cy="50" r={r} fill="none" stroke={STATUS_META[s.key].color} strokeWidth="12"
              strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-offset} />;
            offset += len;
            return el;
          })}
        </svg>
        <ul className="min-w-0 flex-1 space-y-1.5 text-sm">
          {ins.lead_status.map((s) => (
            <li key={s.key} className="flex items-center justify-between gap-2" title={STATUS_META[s.key].hint}>
              <span className="flex items-center gap-2"><span className="inline-block size-2.5 rounded-full" style={{ background: STATUS_META[s.key].color }} aria-hidden />{STATUS_META[s.key].label}</span>
              <span className="tabular-nums"><b>{n(s.count)}</b> <span className="text-xs text-muted">{ins.total_leads ? Math.round((s.count / total) * 100) : 0}%</span></span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

const fmtMinutes = (m: number) => (m < 60 ? `${m} min` : m < 1440 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.round(m / 1440)} days`);

function WaitingByOwner({ ins }: { ins: Insights }) {
  const max = Math.max(1, ...ins.waiting_by_owner.map((w) => w.count));
  return (
    <Panel title="Waiting for first contact" subtitle="New leads with no call yet, by owner">
      {ins.first_response_min !== null && (
        <p className="mb-3 rounded-lg bg-paper px-3 py-2 text-xs">Median first response this month: <b>{fmtMinutes(ins.first_response_min)}</b>
          {ins.contacted_within_day_pct !== null && <> · {ins.contacted_within_day_pct}% called within a day</>}</p>
      )}
      {ins.waiting_by_owner.length === 0 ? <p className="text-sm text-muted">Everyone has been contacted.</p> : (
        <ul className="space-y-2 text-sm">
          {ins.waiting_by_owner.map((w) => (
            <li key={w.user?.id ?? "none"} className="grid grid-cols-[7rem_1fr_2rem] items-center gap-2">
              <span className={cx("truncate", !w.user && "text-gold-600")}>{w.user?.full_name ?? "Unassigned"}</span>
              <span className="h-2 overflow-hidden rounded-full bg-paper"><span className="block h-full rounded-full bg-forest-700" style={{ width: `${(w.count / max) * 100}%` }} /></span>
              <b className="text-right tabular-nums">{n(w.count)}</b>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

const SCHEDULE_LABELS: Record<string, string> = {
  site_visit: "Site visits", call: "Calls", whatsapp: "WhatsApp", meeting: "Meetings", email: "Emails", other: "Other follow-ups",
};

function Scheduled({ ins }: { ins: Insights }) {
  const max = Math.max(1, ...ins.scheduled_30d.map((s) => s.count));
  return (
    <Panel title="Scheduled" subtitle="Next 30 days (follow-ups include any overdue)" action={<Link to="/follow-ups" className="text-sm font-medium text-forest-800 hover:underline">Follow-ups →</Link>}>
      <ul className="space-y-2 text-sm">
        {ins.scheduled_30d.map((s) => (
          <li key={s.key} className="grid grid-cols-[7rem_1fr_2rem] items-center gap-2">
            <span>{SCHEDULE_LABELS[s.key] ?? s.key}</span>
            <span className="h-2 overflow-hidden rounded-full bg-paper"><span className={cx("block h-full rounded-full", s.key === "site_visit" ? "bg-gold-500" : "bg-forest-700")} style={{ width: `${(s.count / max) * 100}%` }} /></span>
            <b className="text-right tabular-nums">{n(s.count)}</b>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function MonthBars({ title, months, pick, color }: { title: string; months: Insights["months"]; pick: (m: Insights["months"][number]) => number; color: string }) {
  const vals = months.map(pick);
  const max = Math.max(1, ...vals);
  const peak = vals.indexOf(Math.max(...vals));
  const label = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-IN", { month: "short" });
  return (
    <Panel title={title} subtitle="Last 12 months" action={vals[peak] > 0 ? <span className="text-xs text-forest-800">Peak {n(vals[peak])} in {label(months[peak].month)}</span> : undefined}>
      <div className="flex h-40 items-end gap-1" aria-hidden>
        {months.map((m, i) => (
          <div key={m.month} className="flex h-full flex-1 flex-col items-center justify-end gap-1">
            <span className="text-[10px] text-muted tabular-nums">{vals[i] || ""}</span>
            <span className="w-full max-w-7 rounded-t" style={{ height: `${Math.max(2, (vals[i] / max) * 100)}%`, background: i === peak && vals[i] ? color : `${color}99` }} />
            <span className="text-[10px] text-muted">{label(m.month)}</span>
          </div>
        ))}
      </div>
      <table className="sr-only"><caption>{title}, last 12 months</caption><tbody>
        {months.map((m, i) => <tr key={m.month}><th scope="row">{label(m.month)}</th><td>{vals[i]}</td></tr>)}</tbody></table>
    </Panel>
  );
}

function Sources({ ins }: { ins: Insights }) {
  return (
    <Panel title="Source performance" subtitle="Leads in the last 12 months, and how many are booked">
      {ins.sources.length === 0 ? <p className="text-sm text-muted">No leads yet.</p> : (
        <table className="w-full text-sm">
          <thead className="text-xs text-muted"><tr><th scope="col" className="py-1 text-left font-normal">Source</th><th scope="col" className="py-1 text-right font-normal">Leads</th>
            <th scope="col" className="py-1 text-right font-normal">Sales</th><th scope="col" className="py-1 pl-3 text-left font-normal">Conversion</th></tr></thead>
          <tbody>{ins.sources.map((s) => (
            <tr key={s.source} className="border-t border-line">
              <th scope="row" className="py-2 text-left font-normal">{SOURCE_LABELS[s.source]}</th>
              <td className="py-2 text-right tabular-nums">{n(s.leads)}</td>
              <td className="py-2 text-right tabular-nums">{n(s.sales)}</td>
              <td className="py-2 pl-3"><span className="flex items-center gap-2">
                <span className="h-1.5 w-full max-w-28 overflow-hidden rounded-full bg-paper"><span className="block h-full rounded-full bg-forest-700" style={{ width: `${Math.min(100, (s.conversion ?? 0) * 4)}%` }} /></span>
                <span className="w-12 text-right text-xs tabular-nums">{s.conversion === null ? "N/A" : `${s.conversion}%`}</span></span></td>
            </tr>))}</tbody>
        </table>
      )}
    </Panel>
  );
}

function RecentBookings({ ins }: { ins: Insights }) {
  const day = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short" });
  return (
    <Panel title="Recent bookings" action={<Link to="/bookings" className="text-sm font-medium text-forest-800 hover:underline">All bookings →</Link>}>
      {ins.recent_bookings.length === 0 ? <p className="text-sm text-muted">No bookings recorded yet. Use Book a flat on a lead’s page.</p> : (
        <ul className="divide-y divide-line text-sm">
          {ins.recent_bookings.map((b) => (
            <li key={b.id}><Link to={`/bookings/${b.id}`} className="flex items-start justify-between gap-3 py-2.5 hover:bg-paper">
              <span className="min-w-0"><span className="block font-medium text-forest-900">{b.customer}</span>
                <span className="block truncate text-xs text-muted">{b.project} · Unit {b.unit_no} · {b.sales_exec?.full_name ?? "—"}</span></span>
              <span className="shrink-0 text-right"><b className="block tabular-nums">{formatRupees(b.agreed_price)}</b><span className="text-xs text-muted">{day(b.booking_date)}</span></span>
            </Link></li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

export function InsightsSections({ ins }: { ins: Insights }) {
  return (
    <div className="mt-6 space-y-6">
      <ProjectInventory projects={ins.projects} />
      <div className="grid gap-6 lg:grid-cols-3"><LeadStatus ins={ins} /><WaitingByOwner ins={ins} /><Scheduled ins={ins} /></div>
      <div className="grid gap-6 lg:grid-cols-2">
        <MonthBars title="Leads received" months={ins.months} pick={(m) => m.leads} color="#235a3e" />
        <MonthBars title="Deals closed" months={ins.months} pick={(m) => m.deals} color="#c9a13b" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2"><Sources ins={ins} /><RecentBookings ins={ins} /></div>
    </div>
  );
}
