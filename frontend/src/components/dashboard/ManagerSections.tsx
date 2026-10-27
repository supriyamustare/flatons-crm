import { Link } from "react-router";
import { cx } from "../ui";
import type { Business, Dashboard, RangeKey, TeamMember } from "../../hooks/useDashboard";
import { formatRupees } from "../../lib/leads";

/** Business figures and the per-person table for the manager's Team view (moved from DashboardPage). */
export const RANGES: { key: RangeKey; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "custom", label: "Custom" },
];

export function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export function Kpi({ label, value, hint, to, tone = "plain" }: {
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

export function BusinessSection({ b, isAdmin }: { b: Business; isAdmin: boolean }) {
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

export const pct = (r: number | null) => (r === null ? "N/A" : `${Math.round(r * 100)}%`);

export function TeamPerformance({ team, periodLabel }: { team: TeamMember[]; periodLabel: string }) {
  const report = (id: number) => `/reports?report=staff&person=${id}`;
  return (
    <section aria-labelledby="team-h" className="mb-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="team-h" className="font-semibold">Team performance</h2>
        <p className="text-xs text-muted">{periodLabel}; “calls today” is always today</p>
      </div>
      {team.length === 0 ? (
        <p className="rounded-xl border border-dashed border-line bg-white px-4 py-6 text-center text-sm text-muted">No sales staff yet.</p>
      ) : (
        <>
          {/* Phones: one card per person */}
          <ul className="space-y-2 md:hidden">
            {team.map((m) => (
              <li key={m.user.id} className="rounded-xl bg-white p-4 ring-1 ring-line">
                <Link to={report(m.user.id)} className="font-medium text-forest-900 underline-offset-2 hover:underline">{m.user.full_name}</Link>
                <dl className="mt-2 grid grid-cols-3 gap-x-3 gap-y-2 text-sm">
                  <div><dt className="text-xs text-muted">Calls today</dt><dd className="font-semibold">{m.calls_today}</dd></div>
                  <div><dt className="text-xs text-muted">Calls</dt><dd>{m.calls} <span className="text-xs text-muted">({pct(m.connection_rate)})</span></dd></div>
                  <div><dt className="text-xs text-muted">Visits done</dt><dd>{m.visits_done}</dd></div>
                  <div><dt className="text-xs text-muted">Converted</dt><dd className="font-semibold text-forest-800">{m.converted}</dd></div>
                  <div><dt className="text-xs text-muted">Dead</dt><dd className={cx(m.dead > 0 && "text-danger")}>{m.dead}</dd></div>
                  <div><dt className="text-xs text-muted">Closing rate</dt><dd>{pct(m.closing_rate)}</dd></div>
                  <div><dt className="text-xs text-muted">Open leads</dt><dd>{m.open_leads}</dd></div>
                  <div><dt className="text-xs text-muted">Overdue</dt><dd className={cx(m.overdue > 0 && "font-semibold text-danger")}>{m.overdue}</dd></div>
                </dl>
              </li>
            ))}
          </ul>
          {/* Tablets and up: table */}
          <div className="hidden overflow-x-auto rounded-xl bg-white ring-1 ring-line md:block">
            <table className="w-full text-sm" aria-labelledby="team-h">
              <thead className="text-xs text-muted">
                <tr>
                  {["Person", "Calls today", "Calls", "Connected", "Visits done", "Converted", "Dead", "Closing rate", "Open leads", "Overdue"].map((h, i) => (
                    <th key={h} scope="col" className={cx("px-3 py-2 font-normal whitespace-nowrap", i ? "text-right" : "text-left")}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {team.map((m) => (
                  <tr key={m.user.id} className="border-t border-line">
                    <th scope="row" className="px-3 py-2.5 text-left font-normal">
                      <Link to={report(m.user.id)} className="font-medium text-forest-900 underline-offset-2 hover:underline">{m.user.full_name}</Link>
                    </th>
                    <td className="px-3 py-2.5 text-right font-semibold tabular-nums">{m.calls_today}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{m.calls}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{m.connected} <span className="text-xs text-muted">({pct(m.connection_rate)})</span></td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{m.visits_done}</td>
                    <td className="px-3 py-2.5 text-right font-semibold text-forest-800 tabular-nums">{m.converted}</td>
                    <td className={cx("px-3 py-2.5 text-right tabular-nums", m.dead > 0 && "text-danger")}>{m.dead}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{pct(m.closing_rate)}</td>
                    <td className="px-3 py-2.5 text-right tabular-nums">{m.open_leads}</td>
                    <td className={cx("px-3 py-2.5 text-right tabular-nums", m.overdue > 0 && "font-semibold text-danger")}>{m.overdue}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="mt-2 text-xs text-muted">
            <summary className="cursor-pointer">What these mean</summary>
            <p className="mt-1">Converted: their leads that moved to Booked in the period. Dead: their leads marked Lost or Junk in the period.
              Closing rate: converted ÷ (converted + dead), N/A when none closed. Open leads: assigned to them now and still in progress.
              Overdue: their follow-ups past due right now.</p>
          </details>
        </>
      )}
    </section>
  );
}

export function rangeLabel(d: Dashboard): string {
  const fmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" });
  const a = new Date(d.date_from + "T00:00:00");
  const b = new Date(d.date_to + "T00:00:00");
  return d.date_from === d.date_to ? fmt.format(a) : `${fmt.format(a)} – ${fmt.format(b)}`;
}

