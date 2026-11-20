import { useState } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { ErrorState, TextInput } from "../../components/ui";
import { api, errorMessage } from "../../lib/api";

interface Block { raised: number; closed: number; open: number; first_response_avg_h: number | null; first_response_median_h: number | null; resolution_avg_h: number | null;
  resolution_median_h: number | null; paused_customer_h: number; paused_external_h: number; response_breaches: number; resolution_breaches: number; at_risk_now: number;
  escalated: Record<string, number>; reopened: number; csat_avg: number | null; csat_responses: number; csat_distribution: Record<string, number>; label?: string }
interface Report { start: string; end: string; overall: Block; by_category: Record<string, Block>; by_team: Record<string, Block> }
const ist = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const h = (x: number | null) => (x == null ? "—" : `${x} h`);
const pct = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : "—");

function Table({ title, rows }: { title: string; rows: Record<string, Block> }) {
  return (
    <section aria-label={title} className="overflow-x-auto rounded-xl bg-white p-4 ring-1 ring-line">
      <h2 className="mb-2 font-semibold">{title}</h2>
      <table className="w-full min-w-[760px] text-sm"><caption className="sr-only">{title}</caption>
        <thead className="text-xs text-muted"><tr>{["", "Raised", "Open", "First response (avg)", "Resolution (avg)", "Paused (customer / third party)", "Breaches (response / resolution)", "Reopened", "Satisfaction"].map((x) => <th key={x} scope="col" className="px-2 py-1 text-left font-normal">{x}</th>)}</tr></thead>
        <tbody>{Object.entries(rows).map(([k, b]) => <tr key={k} className="border-t border-line">
          <th scope="row" className="px-2 py-1.5 text-left font-medium">{b.label}</th><td className="px-2">{b.raised}</td><td className="px-2">{b.open}</td>
          <td className="px-2">{h(b.first_response_avg_h)}</td><td className="px-2">{h(b.resolution_avg_h)}</td><td className="px-2">{b.paused_customer_h} h / {b.paused_external_h} h</td>
          <td className="px-2">{b.response_breaches} / {b.resolution_breaches}</td><td className="px-2">{b.reopened}</td><td className="px-2">{b.csat_avg ?? "—"}{b.csat_responses ? ` (${b.csat_responses})` : ""}</td>
        </tr>)}{Object.keys(rows).length === 0 && <tr><td colSpan={9} className="px-2 py-4 text-center text-muted">No tickets in this period.</td></tr>}</tbody></table>
    </section>
  );
}

export function ServiceReportsPage() {
  const [range, setRange] = useState(() => ({ start: ist(new Date(Date.now() - 29 * 864e5)), end: ist(new Date()) }));
  const q = useQuery({ queryKey: ["service-reports", range], queryFn: async () => (await api.get<Report>("/service/reports", { params: range })).data });
  const o = q.data?.overall;
  return (
    <div className="space-y-4">
      <Link to="/service" className="inline-flex items-center gap-1 text-sm text-forest-800 hover:underline"><ArrowLeft className="size-4" aria-hidden />Service</Link>
      <h1 className="font-display text-2xl text-forest-900">Service reports</h1>
      <div className="grid max-w-md grid-cols-2 gap-3">
        <TextInput label="From" type="date" value={range.start} max={range.end} onChange={(e) => setRange({ ...range, start: e.target.value })} />
        <TextInput label="To" type="date" value={range.end} min={range.start} onChange={(e) => setRange({ ...range, end: e.target.value })} />
      </div>
      <p className="text-xs text-muted">Tickets raised in the period. Resolution times exclude time paused waiting for the customer or a third party, which is shown separately.</p>
      {q.isError && <ErrorState message={errorMessage(q.error, "Couldn’t load the report.")} onRetry={() => void q.refetch()} />}
      {o && <>
        <dl aria-label="Summary" className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          {([["Raised", o.raised], ["Still open", o.open], ["First response (avg)", h(o.first_response_avg_h)], ["Resolution (avg)", h(o.resolution_avg_h)],
            ["Response breaches", `${o.response_breaches} (${pct(o.response_breaches, o.raised)})`], ["Resolution breaches", `${o.resolution_breaches} (${pct(o.resolution_breaches, o.raised)})`],
            ["Reopened", `${o.reopened} (${pct(o.reopened, o.raised)})`], ["Satisfaction", o.csat_avg == null ? "—" : `${o.csat_avg} / 5`]] as const).map(([l, v]) => (
            <div key={l} className="rounded-xl bg-white p-3 ring-1 ring-line"><dt className="text-xs text-muted">{l}</dt><dd className="text-lg font-semibold tabular-nums">{v}</dd></div>))}
        </dl>
        <section aria-label="More detail" className="grid gap-3 rounded-xl bg-white p-4 text-sm ring-1 ring-line sm:grid-cols-3">
          <p>Median first response: <b>{h(o.first_response_median_h)}</b><br />Median resolution: <b>{h(o.resolution_median_h)}</b></p>
          <p>Paused waiting for customers: <b>{o.paused_customer_h} h</b><br />Paused waiting for third parties: <b>{o.paused_external_h} h</b><br />At risk now: <b>{o.at_risk_now}</b></p>
          <p>Escalated: level 1 <b>{o.escalated.level1}</b>, level 2 <b>{o.escalated.level2}</b>, level 3 <b>{o.escalated.level3}</b><br />
            Satisfaction scores: {[5, 4, 3, 2, 1].map((n) => `${n}★ ${o.csat_distribution[String(n)]}`).join(" · ")}</p>
        </section>
        <Table title="By category" rows={q.data!.by_category} />
        <Table title="By team" rows={q.data!.by_team} />
      </>}
    </div>
  );
}
