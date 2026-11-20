import { useState } from "react";
import { Link } from "react-router";
import { Badge, ErrorState, SelectInput, cx } from "../../components/ui";
import { STATUS, slaBadge, useTickets } from "../../hooks/useTickets";
import { formatDateTime } from "../../lib/api";
import { errorMessage } from "../../lib/api";

const VIEWS = [["open", "Open"], ["mine", "Mine"], ["at_risk", "At risk"], ["breached", "Breached"], ["closed", "Closed"]] as const;
const PRI = { urgent: "Urgent", high: "High", normal: "Normal", low: "Low" } as const;

export function ServicePage() {
  const [view, setView] = useState<string>("open");
  const [category, setCategory] = useState(""); const [team, setTeam] = useState("");
  const q = useTickets({ view, category: category || undefined, team: team || undefined });
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="font-display text-2xl text-forest-900 sm:text-3xl">Service</h1>
        <div className="flex gap-2 text-sm"><Link to="/service/reports" className="inline-flex min-h-10 items-center rounded-lg px-3 ring-1 ring-line hover:bg-forest-50">Reports</Link>
          <Link to="/service/settings" className="inline-flex min-h-10 items-center rounded-lg px-3 ring-1 ring-line hover:bg-forest-50">Settings</Link></div>
      </div>
      <div role="tablist" aria-label="Ticket views" className="mb-3 flex flex-wrap gap-1.5">
        {VIEWS.map(([k, l]) => <button key={k} role="tab" aria-selected={view === k} onClick={() => setView(k)}
          className={cx("min-h-10 rounded-full px-4 text-sm", view === k ? "bg-forest-900 text-white" : "bg-white ring-1 ring-line hover:bg-forest-50")}>{l}</button>)}
      </div>
      <div className="mb-4 grid max-w-xl grid-cols-2 gap-3">
        <SelectInput label="Category" value={category} onChange={(e) => setCategory(e.target.value)}><option value="">All categories</option>
          {Object.entries(q.data?.categories ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</SelectInput>
        <SelectInput label="Team" value={team} onChange={(e) => setTeam(e.target.value)}><option value="">All teams</option>
          {Object.entries(q.data?.teams ?? {}).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</SelectInput>
      </div>
      {q.isError ? <ErrorState message={errorMessage(q.error, "Couldn’t load tickets.")} onRetry={() => void q.refetch()} /> : (
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
          <table className="w-full min-w-[820px] text-sm">
            <caption className="sr-only">Tickets</caption>
            <thead className="text-xs text-muted"><tr>{["Ticket", "Customer", "Category", "Priority", "Status", "Owner", "Due"].map((h) => <th key={h} scope="col" className="px-3 py-2 text-left font-normal">{h}</th>)}</tr></thead>
            <tbody>
              {q.isPending && <tr><td colSpan={7} className="px-3 py-6"><div className="h-6 animate-pulse rounded bg-paper" /></td></tr>}
              {q.data?.items.length === 0 && <tr><td colSpan={7} className="px-3 py-8 text-center text-muted">No tickets here.</td></tr>}
              {q.data?.items.map((t) => { const b = slaBadge(t.sla, t.status === "closed"); return (
                <tr key={t.id} className="border-t border-line align-top">
                  <td className="px-3 py-2"><Link to={`/service/${t.id}`} className="font-medium text-forest-900 underline">{t.ticket_no}</Link><span className="block max-w-56 truncate text-xs text-muted">{t.title}</span></td>
                  <td className="px-3 py-2">{t.customer}<span className="block text-xs text-muted">{t.case_code} · {t.unit}</span></td>
                  <td className="px-3 py-2">{t.category_label}<span className="block text-xs text-muted">{t.team_label}</span></td>
                  <td className="px-3 py-2"><Badge tone={t.priority === "urgent" || t.priority === "high" ? "gold" : "muted"}>{PRI[t.priority]}</Badge></td>
                  <td className="px-3 py-2">{STATUS[t.status]}{t.reopened_count > 0 && <span className="block text-xs text-muted">Reopened {t.reopened_count}×</span>}</td>
                  <td className="px-3 py-2">{t.owner?.full_name ?? <span className="text-muted">Unassigned</span>}</td>
                  <td className="px-3 py-2 text-xs">{t.status === "closed" ? `Closed ${formatDateTime(t.closed_at!)}` : formatDateTime(t.sla.resolution_due_at)}{b && <> <Badge tone={b.tone}>{b.text}</Badge></>}</td>
                </tr>); })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
