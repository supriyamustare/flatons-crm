import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { Alert, Button, Modal, TextArea, TextInput } from "../ui";
import { api, errorMessage } from "../../lib/api";

interface Template {
  developer_name: string | null; site_address: string | null; rera_number: string | null; signatory: string | null;
  gst_pct: number; stamp_duty_pct: number; registration_pct: number; registration_cap: number; legal_charges: number; furnishing_per_sqft: number;
  stages: { name: string; pct: number }[]; notes: string[];
}

/** Admin: the project's cost sheet: details, charges, payment stages and notes. */
export function ProjectCostSheetDialog({ projectId, onClose }: { projectId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const tpl = useQuery({ queryKey: ["cost-template", projectId], queryFn: async () => (await api.get<Template>(`/projects/${projectId}/cost-sheet`)).data });
  const [t, setT] = useState<Template | null>(null);
  const [notes, setNotes] = useState("");
  useEffect(() => { if (tpl.data && !t) { setT(tpl.data); setNotes(tpl.data.notes.join("\n")); } }, [tpl.data, t]);
  const save = useMutation({
    mutationFn: async (body: Template) => (await api.put<Template>(`/projects/${projectId}/cost-sheet`, body)).data,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["cost-template", projectId] }); void qc.invalidateQueries({ queryKey: ["cost-sheet"] }); onClose(); },
  });
  if (!t) return <Modal title="Cost sheet settings" onClose={onClose}><p className="text-sm text-muted">Loading…</p></Modal>;
  const total = Math.round(t.stages.reduce((a, s) => a + (Number(s.pct) || 0), 0) * 100) / 100;
  const n = (k: keyof Template) => (e: React.ChangeEvent<HTMLInputElement>) => setT({ ...t, [k]: Number(e.target.value) });
  const txt = (k: keyof Template) => (e: React.ChangeEvent<HTMLInputElement>) => setT({ ...t, [k]: e.target.value });
  return (
    <Modal title="Cost sheet settings" onClose={onClose}>
      <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate({ ...t, notes: notes.split("\n").map((x) => x.trim()).filter(Boolean) }); }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <TextInput label="Developer name" value={t.developer_name ?? ""} onChange={txt("developer_name")} />
          <TextInput label="Site address" value={t.site_address ?? ""} onChange={txt("site_address")} />
          <TextInput label="RERA registration no." value={t.rera_number ?? ""} onChange={txt("rera_number")} />
          <TextInput label="Signatory (developer side)" value={t.signatory ?? ""} onChange={txt("signatory")} />
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <TextInput label="GST (%)" type="number" step="0.01" value={t.gst_pct} onChange={n("gst_pct")} />
          <TextInput label="Stamp duty (%)" type="number" step="0.01" value={t.stamp_duty_pct} onChange={n("stamp_duty_pct")} />
          <TextInput label="Registration (%)" type="number" step="0.01" value={t.registration_pct} onChange={n("registration_pct")} />
          <TextInput label="Registration max (₹)" type="number" value={t.registration_cap} onChange={n("registration_cap")} />
          <TextInput label="Legal charges (₹)" type="number" value={t.legal_charges} onChange={n("legal_charges")} />
          <TextInput label="Furnishing (₹/sq ft)" type="number" step="0.01" value={t.furnishing_per_sqft} onChange={n("furnishing_per_sqft")} />
        </div>
        <fieldset>
          <legend className="mb-1 text-sm font-semibold">Payment stages <span className={total === 100 ? "text-forest-800" : "text-danger"}>(total {total}%)</span></legend>
          <ul className="space-y-1.5">
            {t.stages.map((st, i) => (
              <li key={i} className="flex items-center gap-2">
                <input aria-label={`Stage ${i + 1} name`} value={st.name} onChange={(e) => setT({ ...t, stages: t.stages.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)) })}
                  className="min-h-10 flex-1 rounded-lg border border-line px-2 text-sm" />
                <input aria-label={`Stage ${i + 1} percent`} type="number" step="0.5" value={st.pct} onChange={(e) => setT({ ...t, stages: t.stages.map((x, j) => (j === i ? { ...x, pct: Number(e.target.value) } : x)) })}
                  className="min-h-10 w-20 rounded-lg border border-line px-2 text-right text-sm" />%
                <button type="button" aria-label={`Remove ${st.name}`} onClick={() => setT({ ...t, stages: t.stages.filter((_, j) => j !== i) })}
                  className="grid size-10 place-items-center rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>
              </li>
            ))}
          </ul>
          <Button type="button" variant="ghost" onClick={() => setT({ ...t, stages: [...t.stages, { name: "New stage", pct: 5 }] })}><Plus className="size-4" aria-hidden />Add stage</Button>
        </fieldset>
        <TextArea label="Notes (one per line)" value={notes} onChange={(e) => setNotes(e.target.value)} rows={6} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={total !== 100}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}
