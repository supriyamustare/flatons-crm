import type { ReactNode } from "react";
import { Link } from "react-router";
import { CalendarCheck, Handshake, MapPin, Phone } from "lucide-react";
import { Badge, cx } from "../ui";
import type { LeadTab, Overview, Trend } from "../../hooks/useOverview";
import { formatDateTime } from "../../lib/api";
import { SOURCE_LABELS, STATUS_LABELS, formatMobile, formatRupees } from "../../lib/leads";

const n = (v: number) => v.toLocaleString("en-IN");
const rate = (r: number | null) => (r === null ? "N/A" : `${Math.round(r * 1000) / 10}%`);

/** "Twenty-seven days into October: 17 deals are in closing and 173 fresh leads are waiting on first contact." */
export function summaryLine(o: Overview): string {
  const d = new Date(o.today + "T00:00:00");
  const month = d.toLocaleDateString("en-IN", { month: "long" });
  const deals = o.in_closing === 1 ? "1 deal is" : `${n(o.in_closing)} deals are`;
  const fresh = o.fresh_waiting === 1 ? "1 fresh lead is" : `${n(o.fresh_waiting)} fresh leads are`;
  return `Day ${d.getDate()} of ${month}: ${deals} in closing and ${fresh} waiting on first contact.`;
}

function Tile({ icon, label, value, hint, to, tone }: { icon: ReactNode; label: string; value: number; hint?: string; to: string; tone: string }) {
  return (
    <Link to={to} aria-label={`${label}: ${value}${hint ? `, ${hint}` : ""}`}
      className={cx("rounded-xl p-4 ring-1 ring-line transition hover:shadow-sm focus-visible:ring-2 focus-visible:ring-forest-700", tone)}>
      <p className="flex items-center gap-2 text-sm text-ink">{icon}{label}</p>
      <p className="mt-1 font-display text-3xl text-forest-900 tabular-nums">{n(value)}</p>
      {hint && <p className="text-xs text-danger">{hint}</p>}
    </Link>
  );
}

function WeekMonthBox({ label, wm, money = false }: { label: string; wm: { week: number; month: number }; money?: boolean }) {
  const f = (v: number) => (money ? formatRupees(v) : n(v));
  return (
    <div>
      <p className="mb-1.5 text-sm font-medium">{label}</p>
      <dl className="grid grid-cols-2 overflow-hidden rounded-lg ring-1 ring-line">
        <div className="bg-white p-2.5"><dt className="text-xs text-muted">This week</dt><dd className="text-lg font-semibold tabular-nums">{f(wm.week)}</dd></div>
        <div className="border-l border-line bg-white p-2.5"><dt className="text-xs text-muted">This month</dt><dd className="text-lg font-semibold tabular-nums">{f(wm.month)}</dd></div>
      </dl>
    </div>
  );
}

/** Tiny line of the last 30 days. Decorative: the numbers are next to it. */
function Sparkline({ values, color }: { values: number[]; color: string }) {
  const max = Math.max(1, ...values);
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${28 - (v / max) * 24}`).join(" ");
  return (
    <svg viewBox="0 0 100 30" preserveAspectRatio="none" className="h-8 w-24" aria-hidden>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  );
}

function Change({ pct }: { pct: number | null }) {
  if (pct === null) return <Badge tone="muted">new</Badge>;
  const up = pct >= 0;
  return (
    <span className={cx("rounded-full px-1.5 py-0.5 text-xs font-semibold", up ? "bg-forest-50 text-forest-800" : "bg-danger-soft text-danger")}>
      {up ? "+" : "−"}{Math.abs(pct)}%<span className="sr-only"> vs the same days last month</span>
    </span>
  );
}

function PerfCard({ label, t, money = false, color, extra }: { label: string; t: Trend; money?: boolean; color: string; extra?: string }) {
  const f = (v: number) => (money ? formatRupees(v) : n(v));
  return (
    <div className="rounded-xl bg-white p-4 ring-1 ring-line">
      <p className="text-sm text-muted">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-2">
        <div>
          <p className="flex items-center gap-2 font-display text-2xl text-forest-900 tabular-nums">{f(t.month)} <Change pct={t.change_pct} /></p>
          <p className="text-xs text-muted">This month · last month by today: {f(t.last_month)}{extra ? ` · ${extra}` : ""}</p>
        </div>
        <Sparkline values={t.daily} color={color} />
      </div>
    </div>
  );
}

const TABS: { key: LeadTab; label: string; empty: string }[] = [
  { key: "fresh", label: "Fresh", empty: "No new leads waiting for a first call." },
  { key: "today", label: "Due today", empty: "No follow-ups due today." },
  { key: "visit", label: "Visit booked", empty: "No upcoming site visits." },
  { key: "closing", label: "Closing", empty: "No leads in negotiation." },
  { key: "reengage", label: "Re-engage", empty: "Nobody has gone quiet for a week." },
];

export function OverviewSections({ o, tab, onTab, isPerson }: { o: Overview; tab: LeadTab; onTab: (t: LeadTab) => void; isPerson: boolean }) {
  const p = o.performance;
  const m = o.this_month;
  return (
    <>
      <section aria-label="Today" className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Tile icon={<CalendarCheck className="size-4 text-forest-700" aria-hidden />} label="Follow-ups due" value={o.followups_due}
          hint={o.followups_overdue ? `${n(o.followups_overdue)} overdue` : undefined} to="/follow-ups" tone="bg-forest-50/70" />
        <Tile icon={<MapPin className="size-4 text-forest-700" aria-hidden />} label="Visits today" value={o.visits_today} to="/visits" tone="bg-white" />
        <Tile icon={<Handshake className="size-4 text-gold-600" aria-hidden />} label="In closing" value={o.in_closing} to="/pipeline" tone="bg-gold-100/60" />
      </section>

      <section aria-label="This week and this month" className="mt-4 grid grid-cols-1 gap-4 rounded-xl bg-paper p-4 ring-1 ring-line sm:grid-cols-3">
        <WeekMonthBox label="Site visits completed" wm={o.visits_completed} />
        <WeekMonthBox label="Sales closed" wm={o.sales_closed} />
        <WeekMonthBox label="Sales value" wm={o.sales_revenue} money />
      </section>

      <section aria-labelledby="perf-h" className="mt-6">
        <h2 id="perf-h" className="mb-3 font-semibold">Performance{o.person ? `: ${o.person.full_name}` : ""}</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <PerfCard label={isPerson ? "Enquiries assigned" : "Enquiries"} t={p.enquiries} color="#235a3e" />
          <PerfCard label="Site visits done" t={p.site_visits} color="#2f7a52" />
          <PerfCard label="Sales (bookings)" t={p.sales} color="#c9a13b" />
          {p.spend
            ? <PerfCard label="Marketing spend" t={p.spend} money color="#b45309"
                extra={p.cost_per_sale === null ? "cost per sale: N/A" : `cost per sale ${formatRupees(p.cost_per_sale)}`} />
            : <PerfCard label="Calls" t={p.calls} color="#235a3e" />}
        </div>
      </section>

      <div className="mt-6 grid gap-6 2xl:grid-cols-[1fr_20rem]">
        <section aria-labelledby="month-h" className="rounded-xl bg-white p-4 ring-1 ring-line 2xl:order-2">
          <h2 id="month-h" className="mb-3 font-semibold">This month</h2>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6 2xl:grid-cols-2">
            {([
              ["New leads", n(m.new_leads), "bg-forest-50/70", "/leads"],
              ["Active", n(m.active), "bg-forest-50/70", "/leads"],
              ["Qualified or further", n(m.qualified), "bg-paper", "/pipeline"],
              ["Unassigned", n(m.unassigned), m.unassigned ? "bg-gold-100/60" : "bg-paper", isPerson ? "" : "/inbox"],
              ["Active rate", rate(m.active_rate), "bg-paper", ""],
              ["Win rate", rate(m.win_rate), "bg-paper", ""],
            ] as const).map(([label, value, tone, to]) => {
              const inner = <><dt className="text-xs text-muted">{label}</dt><dd className="text-xl font-semibold text-forest-900 tabular-nums">{value}</dd></>;
              return to
                ? <Link key={label} to={to} className={cx("rounded-lg p-3 hover:ring-1 hover:ring-line", tone)}>{inner}</Link>
                : <div key={label} className={cx("rounded-lg p-3", tone)}>{inner}</div>;
            })}
          </dl>
          <details className="mt-3 text-xs text-muted">
            <summary className="cursor-pointer">What these mean</summary>
            <p className="mt-1">Active: open leads worked on this month (active rate = active ÷ all open leads). Qualified or further: this month’s leads now at Qualified or a later stage. Unassigned: waiting in New enquiries. Win rate: of leads closed this month, the share booked.</p>
          </details>
        </section>
        <section aria-labelledby="leads-h" className="min-w-0 rounded-xl bg-white ring-1 ring-line 2xl:order-1">
          <div className="flex flex-wrap items-center justify-between gap-2 px-4 pt-4">
            <h2 id="leads-h" className="font-semibold">Leads to work on</h2>
            <Link to="/leads" className="text-sm font-medium text-forest-800 hover:underline">View all leads →</Link>
          </div>
          <div role="tablist" aria-label="Lead lists" className="mt-3 flex gap-1 overflow-x-auto border-b border-line px-2">
            {TABS.map((t) => (
              <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => onTab(t.key)}
                className={cx("min-h-11 shrink-0 border-b-2 px-3 text-sm whitespace-nowrap",
                  tab === t.key ? "border-forest-800 font-medium text-forest-900" : "border-transparent text-muted hover:text-ink")}>
                {t.label} <span className="ml-0.5 rounded-full bg-paper px-1.5 text-xs tabular-nums">{n(o.tab_counts[t.key])}</span>
              </button>
            ))}
          </div>
          {o.leads.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-muted">{TABS.find((t) => t.key === tab)?.empty}</p>
          ) : (
            <>
              <ul className="divide-y divide-line md:hidden">
                {o.leads.map((l) => (
                  <li key={l.id} className="flex items-start justify-between gap-3 px-4 py-3">
                    <div className="min-w-0">
                      <Link to={`/leads/${l.id}`} className="font-medium text-forest-900 hover:underline">{l.name}</Link>
                      <p className="text-xs text-muted">{SOURCE_LABELS[l.source]} · {STATUS_LABELS[l.status]}{l.owner ? ` · ${l.owner.full_name}` : " · Unassigned"}</p>
                      {l.next_at && <p className="text-xs">{l.next_action}: {formatDateTime(l.next_at)}</p>}
                    </div>
                    <a href={`tel:${l.mobile}`} aria-label={`Call ${l.name}`} className="grid size-10 shrink-0 place-items-center rounded-lg ring-1 ring-line"><Phone className="size-4" /></a>
                  </li>
                ))}
              </ul>
              <div className="hidden overflow-x-auto md:block">
                <table className="w-full text-sm" aria-labelledby="leads-h">
                  <thead className="text-xs text-muted"><tr>
                    {["Customer", "Mobile", "Source", "Next", "Status", "Owner"].map((h) => <th key={h} scope="col" className="px-4 py-2 text-left font-normal">{h}</th>)}
                  </tr></thead>
                  <tbody>{o.leads.map((l) => (
                    <tr key={l.id} className="border-t border-line">
                      <th scope="row" className="px-4 py-2.5 text-left font-normal">
                        <Link to={`/leads/${l.id}`} className="font-medium whitespace-nowrap text-forest-900 hover:underline">{l.name}</Link>
                        {l.city && <span className="block text-xs text-muted">{l.city}</span>}
                      </th>
                      <td className="px-4 py-2.5 whitespace-nowrap"><a href={`tel:${l.mobile}`} className="hover:underline">{formatMobile(l.mobile)}</a></td>
                      <td className="px-4 py-2.5">{SOURCE_LABELS[l.source]}</td>
                      <td className="px-4 py-2.5 whitespace-nowrap">{l.next_at ? <>{formatDateTime(l.next_at)}<span className="block text-xs text-muted">{l.next_action}</span></> : <span className="text-muted">Not planned</span>}</td>
                      <td className="px-4 py-2.5"><Badge>{STATUS_LABELS[l.status]}</Badge></td>
                      <td className="px-4 py-2.5">{l.owner?.full_name ?? <span className="text-gold-600">Unassigned</span>}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            </>
          )}
        </section>

      </div>
    </>
  );
}
