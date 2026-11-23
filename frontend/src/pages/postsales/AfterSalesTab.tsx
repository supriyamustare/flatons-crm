import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Alert, Badge, Button } from "../../components/ui";
import { DefectCard, RaiseDefect } from "../../components/aftersales/DefectCard";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
export function AfterSalesTab({ caseId }: { caseId: number }) {
  const key = ["after-sales", caseId];
  const q = useQuery({ queryKey: key, queryFn: async () => (await api.get<any>(`/post-sales/cases/${caseId}/after-sales`)).data });
  const qc = useQueryClient(); const [open, setOpen] = useState(false);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const s = q.data;
  const refresh = () => void qc.invalidateQueries({ queryKey: key });
  return (
    <section role="tabpanel" aria-label="After-sales" className="space-y-4">
      <div className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        {s.after_sales_since ? <p>With the after-sales team since <b>{formatDateTime(s.after_sales_since)}</b> (possession {s.possession_on}). The full booking, payment, agreement and handover history stays on this case.</p>
          : <p className="text-muted">Possession isn’t handed over yet; the customer moves to after-sales automatically when the handover is completed. Complaints can still be recorded.</p>}
        {(s.guidance || s.maintenance_contacts) && <p className="mt-2 text-xs">Maintenance: {s.maintenance_contacts ?? "—"}{s.guidance ? ` · ${s.guidance}` : ""}</p>}
      </div>
      <section aria-label="Warranty coverage" className="overflow-x-auto rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <h3 className="mb-2 font-semibold">Warranty coverage</h3>
        {s.warranties.length === 0 ? <p className="text-xs text-muted">No warranty terms are set for this project yet (Projects → After-sales).</p> :
          <table className="w-full min-w-[560px]"><caption className="sr-only">Warranty coverage</caption><thead className="text-xs text-muted"><tr>{["Warranty", "Provider", "Period", "From", "Until", ""].map((h) => <th key={h} scope="col" className="py-1 text-left font-normal">{h}</th>)}</tr></thead>
            <tbody>{s.warranties.map((w: any) => <tr key={w.id} className="border-t border-line"><th scope="row" className="py-1.5 text-left font-normal">{w.name}<span className="block text-xs text-muted">{w.basis}</span></th>
              <td>{w.provider ?? "—"}</td><td>{w.period_months} months from {w.starts_from}</td><td>{w.start ?? "—"}</td><td>{w.end ?? "—"}</td>
              <td>{w.in_warranty === true ? <Badge tone="neutral">Covered</Badge> : w.in_warranty === false ? <Badge tone="muted">Expired</Badge> : <Badge tone="muted">Starts at {w.starts_from}</Badge>}</td></tr>)}</tbody></table>}
      </section>
      <section aria-label="Defects" className="space-y-2">
        <div className="flex items-center justify-between"><h3 className="font-semibold">Defects and complaints</h3>{s.can_raise && <Button onClick={() => setOpen(true)}><Plus className="size-4" aria-hidden />Record complaint</Button>}</div>
        {s.defects.length === 0 ? <p className="rounded-xl border border-dashed border-line bg-white px-6 py-6 text-center text-sm text-muted">No defects recorded.</p> :
          <ul className="space-y-2">{s.defects.map((d: any) => <DefectCard key={d.id} d={d} onChange={refresh} />)}</ul>}
      </section>
      {open && <RaiseDefect caseId={caseId} projectId={s.project_id} warranties={s.warranties} owners={s.owners} onClose={() => setOpen(false)} onDone={() => { setOpen(false); refresh(); }} />}
    </section>
  );
}
