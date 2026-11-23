import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Badge, ErrorState, SelectInput, TextInput, cx } from "../../components/ui";
import { inr } from "../../hooks/useLedger";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
type Col = [string, string, ("inr" | "date" | "dt" | "pct" | "list")?];
const TABS = [["dashboard", "Dashboard"], ["finance", "Finance"], ["operations", "Operations"], ["history", "History"]] as const;
const FILTERS = ["project_id", "building_id", "owner_id", "booking_from", "booking_to", "period_from", "period_to"] as const;

function cell(v: Any, fmt?: Col[2]) {
  if (v === null || v === undefined || v === "") return "—";
  if (fmt === "inr") return inr(Number(v));
  if (fmt === "dt") return formatDateTime(v);
  if (fmt === "pct") return `${v}%`;
  if (fmt === "list") return (v as string[]).join("; ");
  return String(v);
}

function Report({ id, title, rows, cols, section, params, note }: { id: string; title: string; rows: Any[]; cols: Col[]; section?: "finance" | "operations"; params: Record<string, string>; note?: string }) {
  const exportUrl = section ? `/api/mis/export/${section}/${id}?${new URLSearchParams(params).toString()}` : null;
  return (
    <section id={id} aria-label={title} className="scroll-mt-24 overflow-x-auto rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{title} <span className="font-normal text-muted">({rows.length})</span></h3>
        {exportUrl && rows.length > 0 && <a href={exportUrl} className="inline-flex min-h-9 items-center gap-1 rounded-lg px-3 text-xs ring-1 ring-line hover:bg-forest-50"><Download className="size-3.5" aria-hidden />CSV</a>}
      </div>
      {note && <p className="mb-2 text-xs text-muted">{note}</p>}
      {rows.length === 0 ? <p className="text-xs text-muted">Nothing here.</p> : (
        <table className="w-full min-w-[640px]"><caption className="sr-only">{title}</caption>
          <thead className="text-xs text-muted"><tr>{cols.map(([, l]) => <th key={l} scope="col" className="px-2 py-1 text-left font-normal">{l}</th>)}</tr></thead>
          <tbody>{rows.slice(0, 200).map((r, i) => <tr key={i} className="border-t border-line">{cols.map(([k, , f]) => <td key={k} className={cx("px-2 py-1.5", f === "inr" && "text-right tabular-nums")}>
            {k === "case_code" && r.case_id ? <Link to={`/post-sales/${r.case_id}`} className="text-forest-800 underline">{r.case_code}</Link> : cell(r[k], f)}</td>)}</tr>)}</tbody>
        </table>)}
      {rows.length > 200 && <p className="mt-1 text-xs text-muted">Showing 200 of {rows.length}; export the CSV for all.</p>}
    </section>
  );
}

const WHO: Col[] = [["case_code", "Case"], ["customer", "Customer"], ["project", "Project"], ["unit", "Unit"], ["owner", "CRM owner"]];

export function MisPage() {
  const [sp, setSp] = useSearchParams();
  const tab = (TABS.find(([k]) => k === sp.get("tab"))?.[0] ?? "dashboard") as (typeof TABS)[number][0];
  const params = Object.fromEntries(FILTERS.map((k) => [k, sp.get(k) ?? ""]).filter(([, v]) => v)) as Record<string, string>;
  const setParam = (k: string, v: string) => { const n = new URLSearchParams(sp); if (v) n.set(k, v); else n.delete(k); if (k === "project_id") n.delete("building_id"); setSp(n, { replace: true }); };
  const opts = useQuery({ queryKey: ["mis-options"], queryFn: async () => (await api.get<Any>("/mis/options")).data });
  const q = useQuery({ queryKey: ["mis", tab, params], enabled: tab !== "history",
    queryFn: async () => (await api.get<Any>(tab === "dashboard" ? "/mis/dashboard" : `/mis/reports/${tab}`, { params })).data });
  const hist = useQuery({ queryKey: ["mis-history", params.project_id], enabled: tab === "history",
    queryFn: async () => (await api.get<Any[]>("/mis/snapshots", { params: params.project_id ? { project_id: params.project_id } : {} })).data });
  const [upcoming, setUpcoming] = useState("7");
  useEffect(() => { const h = window.location.hash.slice(1); if (h && q.data) document.getElementById(h)?.scrollIntoView?.(); }, [q.data]);
  const go = (report: string) => { const [t, anchor] = report.split("#"); const n = new URLSearchParams(sp); n.set("tab", t); setSp(n); window.location.hash = anchor; };
  const d = q.data;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h1 className="font-display text-2xl text-forest-900 sm:text-3xl">MIS</h1>
        {d?.as_of && <p className="text-xs text-muted">Live figures as of {d.as_of}. Period figures use the period dates; History shows nightly snapshots.</p>}</div>
      <div role="tablist" aria-label="MIS sections" className="flex flex-wrap gap-1.5">{TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k}
        onClick={() => { const n = new URLSearchParams(sp); n.set("tab", k); setSp(n); }} className={cx("min-h-10 rounded-full px-4 text-sm", tab === k ? "bg-forest-900 text-white" : "bg-white ring-1 ring-line hover:bg-forest-50")}>{l}</button>)}</div>
      <fieldset aria-label="Filters" className="grid grid-cols-2 gap-2 rounded-xl bg-white p-3 ring-1 ring-line sm:grid-cols-4 lg:grid-cols-7">
        <SelectInput label="Project" value={params.project_id ?? ""} onChange={(e) => setParam("project_id", e.target.value)}><option value="">All</option>{(opts.data?.projects ?? []).map((p: Any) => <option key={p.id} value={p.id}>{p.name}</option>)}</SelectInput>
        <SelectInput label="Tower" value={params.building_id ?? ""} onChange={(e) => setParam("building_id", e.target.value)}><option value="">All</option>
          {(opts.data?.buildings ?? []).filter((b: Any) => !params.project_id || String(b.project_id) === params.project_id).map((b: Any) => <option key={b.id} value={b.id}>{b.name}</option>)}</SelectInput>
        <SelectInput label="CRM owner" value={params.owner_id ?? ""} onChange={(e) => setParam("owner_id", e.target.value)}><option value="">All</option>{(opts.data?.owners ?? []).map((u: Any) => <option key={u.id} value={u.id}>{u.name}</option>)}</SelectInput>
        <TextInput label="Booked from" type="date" value={params.booking_from ?? ""} onChange={(e) => setParam("booking_from", e.target.value)} />
        <TextInput label="Booked to" type="date" value={params.booking_to ?? ""} onChange={(e) => setParam("booking_to", e.target.value)} />
        <TextInput label="Period from" type="date" value={params.period_from ?? ""} onChange={(e) => setParam("period_from", e.target.value)} />
        <TextInput label="Period to" type="date" value={params.period_to ?? ""} onChange={(e) => setParam("period_to", e.target.value)} />
      </fieldset>
      {(q.isError || hist.isError) && <ErrorState message={errorMessage(q.error ?? hist.error, "Couldn’t load the figures.")} onRetry={() => void (tab === "history" ? hist.refetch() : q.refetch())} />}
      {tab !== "history" && q.isPending && <div className="h-48 animate-pulse rounded-xl bg-white" />}

      {tab === "dashboard" && d && <>
        <dl aria-label="Headline" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {([["Active customer accounts", d.headline.active_accounts], ["Agreements pending", d.headline.agreements_pending], ["Overdue receivables", inr(d.headline.overdue_receivables)], ["Open service tickets", d.headline.open_tickets]] as const)
            .map(([l, v]) => <div key={l} className="rounded-xl bg-white p-4 ring-1 ring-line"><dt className="text-xs text-muted">{l}</dt><dd className="font-display text-2xl text-forest-900 tabular-nums">{v}</dd></div>)}
        </dl>
        <dl aria-label="Money" className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
          {([["Contract value", inr(d.money.consideration)], ["Outstanding", inr(d.money.outstanding)], ["Collected (confirmed)", inr(d.money.collected)], ["Awaiting confirmation", inr(d.money.awaiting_confirmation)],
            ["Collection efficiency", d.money.collection_efficiency_pct == null ? "—" : `${d.money.collection_efficiency_pct}%`]] as const)
            .map(([l, v]) => <div key={l} className="rounded-lg bg-white p-3 ring-1 ring-line"><dt className="text-xs text-muted">{l}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>)}
        </dl>
        <section aria-label="Exceptions" className="rounded-xl bg-white p-4 ring-1 ring-line">
          <h2 className="mb-2 font-semibold">Needs attention</h2>
          <ul className="divide-y divide-line text-sm">{d.exceptions.map((e: Any) => <li key={e.key}>
            <button type="button" onClick={() => go(e.report)} disabled={!e.count} className={cx("flex w-full items-center justify-between gap-2 py-2 text-left", e.count ? "hover:text-forest-800" : "text-muted")}>
              <span>{e.label}</span><span className="flex items-center gap-2">{e.amount ? <span className="tabular-nums">{inr(e.amount)}</span> : null}<Badge tone={e.count ? "gold" : "muted"}>{e.count}</Badge></span></button></li>)}</ul>
        </section>
        <div className="grid gap-3 md:grid-cols-2">
          <section aria-label="Upcoming dues" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h2 className="mb-2 font-semibold">Falling due</h2>
            <ul>{(["7", "15", "30"] as const).map((n) => <li key={n} className="flex justify-between py-1">Next {n} days <span className="tabular-nums">{d.upcoming[n].count} · {inr(d.upcoming[n].amount)}</span></li>)}</ul></section>
          <section aria-label="Ageing" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h2 className="mb-2 font-semibold">Overdue by age</h2>
            {Object.entries(d.ageing as Record<string, number>).map(([k, v]) => { const max = Math.max(1, ...Object.values(d.ageing as Record<string, number>)); return (
              <div key={k} className="flex items-center gap-2 py-1"><span className="w-16 text-xs">{k} days</span><div className="h-3 flex-1 rounded bg-paper"><div className="h-3 rounded bg-gold-500" style={{ width: `${(100 * v) / max}%` }} /></div>
                <span className="w-28 text-right text-xs tabular-nums">{inr(v)}</span></div>); })}</section>
        </div>
      </>}

      {tab === "finance" && d && <>
        <Report id="projects" title="By project: contract value, demands, collections" section={undefined} params={params} rows={d.projects}
          note="Demands raised and collections use the period dates when set; collection efficiency = collected against amounts due to date."
          cols={[["project", "Project"], ["cases", "Customers"], ["consideration", "Contract value", "inr"], ["demanded", "Demanded", "inr"], ["collected", "Collected (confirmed)", "inr"],
            ["awaiting_confirmation", "Awaiting confirmation", "inr"], ["collection_efficiency_pct", "Collection efficiency", "pct"]]} />
        <Report id="ageing" title="Overdue receivables by age" section="finance" params={params} rows={d.ageing_items.map((r: Any) => ({ ...r, ageing_items: undefined }))}
          cols={[...WHO, ["1-30", "1–30 days", "inr"], ["31-60", "31–60", "inr"], ["61-90", "61–90", "inr"], ["90+", "90+", "inr"], ["overdue", "Total overdue", "inr"]]} />
        <section className="space-y-2"><div className="w-40"><SelectInput label="Falling due within" value={upcoming} onChange={(e) => setUpcoming(e.target.value)}>
          {["7", "15", "30"].map((n) => <option key={n} value={n}>{n} days</option>)}</SelectInput></div>
          <Report id={`upcoming_${upcoming}`} title={`Falling due in the next ${upcoming} days`} section="finance" params={params} rows={d.upcoming[upcoming].items}
            cols={[...WHO, ["stage", "Stage"], ["due_date", "Due"], ["amount", "Amount", "inr"]]} /></section>
        <Report id="customers" title="Customer-wise outstanding" section="finance" params={params} rows={d.customers}
          cols={[...WHO, ["payable", "Payable", "inr"], ["received", "Received", "inr"], ["outstanding", "Outstanding", "inr"], ["overdue", "Overdue", "inr"], ["demanded_not_due", "Demanded, not due", "inr"], ["pending_confirmation", "Awaiting confirmation", "inr"]]} />
        <Report id="own_contribution" title="Own contribution still required" section="finance" params={params} rows={d.own_contribution.items}
          note={`Required ${inr(d.own_contribution.required)} · received from customers ${inr(d.own_contribution.received)}`} cols={[...WHO, ["own_required", "Still required", "inr"]]} />
        <Report id="disbursement_pending" title="Bank disbursement pending" section="finance" params={params} rows={d.disbursement_pending}
          cols={[...WHO, ["lender", "Lender"], ["sanctioned", "Sanctioned", "inr"], ["disbursed", "Disbursed", "inr"], ["not_disbursed", "Not yet disbursed", "inr"], ["open_requests", "Requested, awaited", "inr"], ["oldest_request", "Oldest request"]]} />
        <Report id="unallocated" title="Unallocated receipts (advances)" section="finance" params={params} rows={d.unallocated} cols={[...WHO, ["unapplied", "Unallocated", "inr"]]} />
        <Report id="failed_payments" title="Failed or reversed payments" section="finance" params={params} rows={d.failed_payments}
          cols={[...WHO.slice(0, 4), ["receipt", "Receipt"], ["date", "Date"], ["mode", "Mode"], ["status", "Status"], ["amount", "Amount", "inr"], ["reason", "Reason"]]} />
        <Report id="refunds_pending" title="Refunds pending approval or payment" section="finance" params={params} rows={d.refunds_pending} cols={[...WHO, ["cancellation", "Cancellation"], ["stage", "Stage"], ["refund", "Refund", "inr"]]} />
        <Report id="adjustments" title="Adjustments (cancellation deductions)" section="finance" params={params} rows={d.adjustments} cols={[...WHO.slice(0, 4), ["cancellation", "Cancellation"], ["label", "Deduction"], ["basis", "Basis"], ["amount", "Amount", "inr"]]} />
        <Report id="no_ledger" title="Customers without a ledger yet" section="finance" params={params} rows={d.no_ledger} cols={WHO} />
        <section aria-label="Not available yet" className="rounded-xl bg-paper p-4 text-sm ring-1 ring-line"><h3 className="mb-1 font-semibold">Not available yet</h3>
          <ul className="list-disc space-y-1 pl-5 text-xs">{Object.entries(d.not_available as Record<string, string>).map(([k, v]) => <li key={k}><b>{{ unmatched_bank_transactions: "Unmatched bank transactions", waivers: "Waivers", tax_tds: "Tax and TDS reconciliation" }[k] ?? k}:</b> {v}</li>)}</ul></section>
      </>}

      {tab === "operations" && d && <>
        <Report id="handover_pending" title="Bookings handed over but not accepted" section="operations" params={params} rows={d.handover_pending} cols={[...WHO, ["days", "Days waiting"]]} />
        <Report id="kyc_incomplete" title="Customers with incomplete KYC" section="operations" params={params} rows={d.kyc_incomplete} cols={[...WHO, ["done", "Verified"], ["total", "Required"]]} />
        <Report id="agreements_pending" title="Agreements pending, by stage" section="operations" params={params} rows={d.agreements_pending}
          note={Object.entries(d.agreements_by_stage as Record<string, number>).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")} cols={[...WHO, ["stage", "Stage"], ["days", "Days at stage"]]} />
        <Report id="documents_awaiting_approval" title="Documents awaiting approval" section="operations" params={params} rows={d.documents_awaiting_approval} cols={[...WHO, ["document", "Document"], ["title", "Title"], ["days", "Days"]]} />
        <Report id="documents_not_released" title="Approved for the customer but not released" section="operations" params={params} rows={d.documents_not_released} cols={[...WHO, ["document", "Document"], ["title", "Title"], ["days", "Days"]]} />
        <Report id="overdue_follow_ups" title="Overdue follow-ups" section="operations" params={params} rows={d.overdue_follow_ups} cols={[...WHO, ["due_on", "Was due"], ["days", "Days overdue"]]} />
        <Report id="broken_promises" title="Payment promises missed" section="operations" params={params} rows={d.broken_promises} cols={[...WHO, ["promise_date", "Promised for"], ["promise_amount", "Amount", "inr"]]} />
        <Report id="tickets_by_team" title="Open tickets by team, priority and age" params={params} rows={Object.entries(d.tickets_by_team).map(([team, v]: Any) => ({ team, ...v }))}
          cols={[["team", "Team"], ["total", "Open"], ["urgent", "Urgent"], ["high", "High"], ["normal", "Normal"], ["low", "Low"], ["0-2 days", "0–2 days"], ["3-7 days", "3–7"], ["8-30 days", "8–30"], ["30+ days", "30+"]]} />
        <Report id="sla_breaches" title="SLA breaches" section="operations" params={params} rows={d.sla_breaches} cols={[...WHO.slice(0, 4), ["ticket", "Ticket"], ["title", "Title"], ["team", "Team"], ["priority", "Priority"], ["kind", "Breached"], ["escalation_level", "Escalation"]]} />
        <Report id="requests_awaiting" title="Customer requests awaiting approval or response" section="operations" params={params} rows={d.requests_awaiting} cols={[...WHO.slice(0, 4), ["item", "Item"], ["what", "What"], ["days", "Days"]]} />
        <Report id="possession_ready" title="Units ready for possession" section="operations" params={params} rows={d.possession_ready} cols={[...WHO, ["eligible_since", "Eligible since", "dt"], ["days_waiting", "Days waiting"]]} />
        <Report id="possession_delays" title="Possession delays and reasons" section="operations" params={params} rows={d.possession_delays} cols={[...WHO, ["days_open", "Days open"], ["pending", "Still pending", "list"]]} />
        <Report id="open_snags_defects" title="Open snags and defects" section="operations" params={params} rows={d.open_snags_defects}
          cols={[["case_code", "Case"], ["customer", "Customer"], ["unit", "Unit"], ["kind", "Kind"], ["ref", "Ref"], ["category", "Category"], ["severity", "Severity"], ["status", "Status"], ["due", "Due"]]} />
        <Report id="cancellations" title="Refund and cancellation cases" section="operations" params={params} rows={d.cancellations} cols={[...WHO.slice(0, 4), ["cancellation", "Cancellation"], ["status", "Status"], ["reason", "Reason"], ["refund", "Refund", "inr"], ["days", "Days"]]} />
        <Report id="workload" title="Employee workload and productivity" section="operations" params={params} rows={d.workload}
          note="Tickets closed: in the period when set, otherwise the last 30 days."
          cols={[["user", "Person"], ["role", "Role"], ["cases", "Cases owned"], ["open_tickets", "Open tickets"], ["breached_tickets", "Breached"], ["open_defects", "Open defects"], ["follow_ups_due", "Follow-ups due"], ["tickets_closed", "Tickets closed"]]} />
      </>}

      {tab === "history" && hist.data && <Report id="history" title="Nightly snapshots (as things stood each night)" params={params} rows={hist.data}
        note="Taken every night at 23:30. Choose a project above to see that project only."
        cols={[["taken_on", "Date"], ["active_accounts", "Active accounts"], ["agreements_pending", "Agreements pending"], ["overdue_receivables", "Overdue", "inr"], ["outstanding", "Outstanding", "inr"],
          ["collected", "Collected to date", "inr"], ["collection_efficiency_pct", "Efficiency", "pct"], ["open_tickets", "Open tickets"]]} />}
    </div>
  );
}
