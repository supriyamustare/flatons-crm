import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { Printer } from "lucide-react";
import { ErrorState } from "../../components/ui";
import { useCase } from "../../hooks/usePostSales";
import { api, errorMessage } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
/** The inspection report for the customer: every snag found, its location, severity, owner and target date. */
export function InspectionReportPage() {
  const { caseId, inspectionId } = useParams();
  const c = useCase(Number(caseId));
  const q = useQuery({ queryKey: ["possession", Number(caseId)], queryFn: async () => (await api.get<any>(`/post-sales/cases/${caseId}/possession`)).data });
  if (q.isPending || c.isPending) return <p className="p-8 text-muted">Preparing the report…</p>;
  if (q.isError || c.isError) return <div className="p-8"><ErrorState message={errorMessage(q.error ?? c.error, "Couldn’t load the report.")} onRetry={() => void q.refetch()} /></div>;
  const f = q.data.file; const ins = f?.inspections.find((i: any) => String(i.id) === inspectionId);
  if (!ins) return <p className="p-8 text-muted">Inspection not found.</p>;
  const snags = f.snags.filter((s: any) => String(s.inspection_id) === inspectionId);
  const td = "border border-neutral-300 px-2 py-1 align-top";
  return (
    <div className="min-h-screen bg-neutral-100 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-3xl justify-end px-4 print:hidden"><button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white"><Printer className="size-4" aria-hidden />Print</button></div>
      <article aria-label="Inspection report" className="mx-auto max-w-3xl bg-white p-8 text-[13px] text-black shadow print:max-w-none print:p-0 print:shadow-none">
        <h1 className="text-center text-lg font-bold">UNIT INSPECTION REPORT</h1>
        <p className="mt-1 text-center text-xs">{c.data!.project}, unit {c.data!.unit_no} · {c.data!.customer} · {c.data!.case_code}</p>
        <p className="mt-4">Inspected on <b>{ins.conducted_on ?? "—"}</b>{ins.attendees ? <> with {ins.attendees}</> : null}.</p>
        {ins.notes && <p className="mt-1 whitespace-pre-wrap">{ins.notes}</p>}
        <h2 className="mt-4 font-bold">Items to be rectified ({snags.length})</h2>
        <table className="mt-1 w-full border-collapse"><thead><tr className="bg-neutral-100">{["#", "Location", "Description", "Category", "Severity", "Target date", "Status"].map((h) => <th key={h} className={`${td} text-left`}>{h}</th>)}</tr></thead>
          <tbody>{snags.map((s: any, i: number) => <tr key={s.id}><td className={td}>{i + 1}</td><td className={td}>{s.location ?? "—"}</td><td className={td}>{s.description}</td><td className={td}>{s.category}</td>
            <td className={td}>{s.severity}</td><td className={td}>{s.due_on}</td><td className={td}>{s.status === "closed" ? "Closed" : s.status === "verified" ? "Repaired, awaiting your acceptance" : s.status === "fixed" ? "Repaired, being checked" : "Open"}</td></tr>)}
            {snags.length === 0 && <tr><td className={td} colSpan={7}>No items recorded.</td></tr>}</tbody></table>
        <p className="mt-4 text-xs">We’ll inform you as each item is rectified and verified, and ask you to confirm the repair.</p>
        <div className="mt-12 grid grid-cols-2 gap-10 text-xs"><div className="border-t border-black pt-1">For the developer</div><div className="border-t border-black pt-1">Customer: {c.data!.customer}</div></div>
      </article>
    </div>
  );
}
