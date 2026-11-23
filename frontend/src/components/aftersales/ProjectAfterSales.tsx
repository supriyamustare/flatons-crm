import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { Alert, Badge, Button, SelectInput, TextArea, TextInput } from "../ui";
import { useToast } from "../Toast";
import { DefectCard, RaiseDefect } from "./DefectCard";
import { api, errorMessage } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type W = { id?: number; name: string; category: string; provider: string; period_months: string; starts_from: string; basis: string; active?: boolean };
const CATS = ["civil", "structural", "waterproofing", "electrical", "plumbing", "finishing", "fittings", "equipment", "other"];

export function ProjectAfterSales({ projectId }: { projectId: number }) {
  const key = ["project-after-sales", projectId];
  const q = useQuery({ queryKey: key, queryFn: async () => (await api.get<any>(`/projects/${projectId}/after-sales`)).data });
  const common = useQuery({ queryKey: ["defects", projectId], queryFn: async () => ((await api.get<any[]>("/defects", { params: { project_id: projectId } })).data).filter((d) => !d.case_id) });
  const qc = useQueryClient(); const toast = useToast();
  const [ws, setWs] = useState<W[] | null>(null); const [fm, setFm] = useState<Record<string, any> | null>(null); const [raise, setRaise] = useState(false);
  const saveW = useMutation({ mutationFn: async (items: W[]) => (await api.put(`/projects/${projectId}/warranties`, items.map((w) => ({ ...(w.id ? { id: w.id } : {}), name: w.name.trim(), category: w.category,
    provider: w.provider.trim() || null, period_months: Number(w.period_months), starts_from: w.starts_from, basis: w.basis.trim() || null, active: w.active ?? true })))).data,
    onSuccess: (d) => { qc.setQueryData(key, d); setWs(null); toast("Warranty terms saved"); } });
  const saveF = useMutation({ mutationFn: async (b: Record<string, any>) => (await api.put(`/projects/${projectId}/facility-handover`, b)).data,
    onSuccess: (d) => { qc.setQueryData(key, d); setFm(null); toast("Facility handover saved"); } });
  if (!q.data) return null;
  const d = q.data; const edit = d.can_edit;
  const rows: W[] = ws ?? d.warranties.map((w: any) => ({ ...w, provider: w.provider ?? "", basis: w.basis ?? "", period_months: String(w.period_months) }));
  const f = fm ?? d.facility ?? {};
  const setW = (i: number, k: keyof W, v: string) => setWs(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  return (
    <section id="after-sales" aria-labelledby="as-h" className="relative z-30 -mx-4 mt-4 space-y-4 bg-paper px-4 pt-4">
      <h2 id="as-h" className="font-display text-xl text-forest-900">After-sales</h2>
      <section aria-label="Warranty terms" className="overflow-x-auto rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <h3 className="mb-1 font-semibold">Warranty and defect-liability terms</h3>
        <p className="mb-2 text-xs text-muted">Set each term from the agreement, the product warranty or the law; there’s no single default. Terms already used by a defect are deactivated, not deleted.</p>
        {saveW.isError && <Alert>{errorMessage(saveW.error)}</Alert>}
        <fieldset disabled={!edit} className="space-y-2">
          {rows.map((w, i) => <div key={w.id ?? `n${i}`} className="grid grid-cols-2 items-end gap-2 rounded-lg bg-paper p-2 sm:grid-cols-[2fr_1fr_1fr_7rem_8rem_2fr_auto]">
            <TextInput label={`Term ${i + 1}`} value={w.name} onChange={(e) => setW(i, "name", e.target.value)} />
            <SelectInput label="Category" value={w.category} onChange={(e) => setW(i, "category", e.target.value)}>{CATS.map((c) => <option key={c} value={c}>{c}</option>)}</SelectInput>
            <TextInput label="Provider" value={w.provider} onChange={(e) => setW(i, "provider", e.target.value)} />
            <TextInput label="Months" type="number" min={1} value={w.period_months} onChange={(e) => setW(i, "period_months", e.target.value)} />
            <SelectInput label="Runs from" value={w.starts_from} onChange={(e) => setW(i, "starts_from", e.target.value)}><option value="possession">Possession</option><option value="completion">Completion</option><option value="purchase">Purchase</option></SelectInput>
            <TextInput label="Basis" value={w.basis} onChange={(e) => setW(i, "basis", e.target.value)} placeholder="Clause / warranty card / law" />
            {edit && <Button type="button" variant="ghost" aria-label={`Remove term ${i + 1}`} onClick={() => setWs(rows.filter((_, j) => j !== i))}><Trash2 className="size-4" aria-hidden /></Button>}
            {w.active === false && <Badge tone="muted">Inactive</Badge>}</div>)}
        </fieldset>
        {edit && <div className="mt-2 flex gap-2"><Button variant="ghost" onClick={() => setWs([...rows, { name: "", category: "structural", provider: "", period_months: "60", starts_from: "possession", basis: "" }])}><Plus className="size-4" aria-hidden />Add term</Button>
          {ws && <Button loading={saveW.isPending} disabled={rows.some((r) => r.name.trim().length < 2 || !(Number(r.period_months) > 0))} onClick={() => saveW.mutate(rows)}>Save terms</Button>}</div>}
      </section>
      <form aria-label="Facility handover" className="space-y-2 rounded-xl bg-white p-4 text-sm ring-1 ring-line" onSubmit={(e: FormEvent) => { e.preventDefault();
        saveF.mutate(Object.fromEntries(["maintenance_start", "maintenance_contacts", "facilities", "manuals", "utilities", "records_handed_to", "records_handed_on", "customer_guidance"].map((k) => [k, f[k] || null]))); }}>
        <h3 className="font-semibold">Maintenance and facility-management handover</h3>
        <p className="text-xs text-muted">Kept separate from society or facility-management accounting.</p>
        {saveF.isError && <Alert>{errorMessage(saveF.error)}</Alert>}
        <fieldset disabled={!edit} className="grid gap-2 sm:grid-cols-2">
          <TextInput label="Maintenance starts on" type="date" value={f.maintenance_start ?? ""} onChange={(e) => setFm({ ...f, maintenance_start: e.target.value })} />
          <TextInput label="Maintenance contacts" value={f.maintenance_contacts ?? ""} onChange={(e) => setFm({ ...f, maintenance_contacts: e.target.value })} />
          <TextArea label="Common areas and facilities" value={f.facilities ?? ""} onChange={(e) => setFm({ ...f, facilities: e.target.value })} rows={2} />
          <TextArea label="Warranties and equipment manuals handed over" value={f.manuals ?? ""} onChange={(e) => setFm({ ...f, manuals: e.target.value })} rows={2} />
          <TextArea label="Utility and service providers" value={f.utilities ?? ""} onChange={(e) => setFm({ ...f, utilities: e.target.value })} rows={2} />
          <TextArea label="Guidance for customers (maintenance payments, service requests, escalation)" value={f.customer_guidance ?? ""} onChange={(e) => setFm({ ...f, customer_guidance: e.target.value })} rows={2} />
          <TextInput label="Project records handed to" value={f.records_handed_to ?? ""} onChange={(e) => setFm({ ...f, records_handed_to: e.target.value })} placeholder="Society / association / facility manager" />
          <TextInput label="Records handed over on" type="date" value={f.records_handed_on ?? ""} onChange={(e) => setFm({ ...f, records_handed_on: e.target.value })} />
        </fieldset>
        {edit && fm && <div className="flex justify-end"><Button type="submit" loading={saveF.isPending}>Save facility handover</Button></div>}
      </form>
      <section aria-label="Common-area defects" className="space-y-2">
        <div className="flex items-center justify-between"><h3 className="font-semibold">Common-area defects</h3><Button variant="ghost" onClick={() => setRaise(true)}><Plus className="size-4" aria-hidden />Record common-area defect</Button></div>
        {(common.data ?? []).length === 0 ? <p className="text-xs text-muted">None recorded.</p> :
          <ul className="space-y-2">{common.data!.map((x) => <DefectCard key={x.id} d={x} onChange={() => { void common.refetch(); void q.refetch(); }} />)}</ul>}
      </section>
      {raise && <RaiseDefect projectId={projectId} warranties={d.warranties} owners={[]} onClose={() => setRaise(false)} onDone={() => { setRaise(false); void common.refetch(); void q.refetch(); }} />}
    </section>
  );
}
