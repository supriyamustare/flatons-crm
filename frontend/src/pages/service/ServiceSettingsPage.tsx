import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Alert, Button, ErrorState, SelectInput, TextInput } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { ROLE_LABELS } from "../../lib/types";
import type { Role } from "../../lib/types";
import { api, errorMessage } from "../../lib/api";

interface Settings {
  response_hours: Record<string, number>; resolution_hours: Record<string, number>; at_risk_pct: number; reopen_days: number;
  categories: Record<string, { team: string; needs_confirmation: boolean }>; escalation: { level2_roles: string[]; level3_roles: string[]; level3_after_hours: number };
  labels: Record<string, string>; teams: Record<string, string>; can_edit: boolean;
}
const PRI = [["urgent", "Urgent"], ["high", "High"], ["normal", "Normal"], ["low", "Low"]] as const;
const ESC_ROLES: Role[] = ["crm_manager", "admin", "management", "postsales_exec", "finance_approver", "project_manager", "after_sales"];

export function ServiceSettingsPage() {
  const q = useQuery({ queryKey: ["service-settings"], queryFn: async () => (await api.get<Settings>("/service/settings")).data });
  const qc = useQueryClient(); const toast = useToast();
  const [s, setS] = useState<Settings | null>(null);
  useEffect(() => { if (q.data && !s) setS(q.data); }, [q.data, s]);
  const save = useMutation({ mutationFn: async (b: Settings) => (await api.put<Settings>("/service/settings", { response_hours: b.response_hours, resolution_hours: b.resolution_hours,
    at_risk_pct: b.at_risk_pct, reopen_days: b.reopen_days, categories: b.categories, escalation: b.escalation })).data,
    onSuccess: (d) => { qc.setQueryData(["service-settings"], d); setS(d); toast("Service settings saved; they apply to tickets raised from now on"); } });
  if (q.isError) return <ErrorState message={errorMessage(q.error, "Couldn’t load the settings.")} onRetry={() => void q.refetch()} />;
  if (!s) return <div className="h-64 animate-pulse rounded-xl bg-white" />;
  const ro = !s.can_edit;
  const hours = (k: "response_hours" | "resolution_hours", p: string) => (e: { target: { value: string } }) => setS({ ...s, [k]: { ...s[k], [p]: Number(e.target.value) } });
  const toggleRole = (lvl: "level2_roles" | "level3_roles", r: string) => setS({ ...s, escalation: { ...s.escalation, [lvl]: s.escalation[lvl].includes(r) ? s.escalation[lvl].filter((x) => x !== r) : [...s.escalation[lvl], r] } });
  return (
    <form onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(s); }} className="space-y-5">
      <Link to="/service" className="inline-flex items-center gap-1 text-sm text-forest-800 hover:underline"><ArrowLeft className="size-4" aria-hidden />Service</Link>
      <h1 className="font-display text-2xl text-forest-900">Service settings</h1>
      {ro && <Alert>Only an admin can change these settings.</Alert>}
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <p className="text-sm text-muted">Changes apply to tickets raised from now on; existing tickets keep the targets they were raised with.</p>
      <fieldset disabled={ro} className="space-y-5">
        <section aria-label="Service levels" className="rounded-xl bg-white p-4 ring-1 ring-line">
          <h2 className="mb-2 font-semibold">Targets by priority (hours)</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">{PRI.map(([p, l]) => <div key={p} className="space-y-2 rounded-lg bg-paper p-2">
            <p className="text-sm font-medium">{l}</p>
            <TextInput label={`${l}: first response`} type="number" min={1} value={s.response_hours[p]} onChange={hours("response_hours", p)} />
            <TextInput label={`${l}: resolution`} type="number" min={1} value={s.resolution_hours[p]} onChange={hours("resolution_hours", p)} /></div>)}</div>
          <div className="mt-3 grid max-w-md grid-cols-2 gap-3">
            <TextInput label="At risk when less than (%) left" type="number" min={5} max={75} value={s.at_risk_pct} onChange={(e) => setS({ ...s, at_risk_pct: Number(e.target.value) })} />
            <TextInput label="Reopen period (days)" type="number" min={0} max={90} value={s.reopen_days} onChange={(e) => setS({ ...s, reopen_days: Number(e.target.value) })} />
          </div>
        </section>
        <section aria-label="Category rules" className="overflow-x-auto rounded-xl bg-white p-4 ring-1 ring-line">
          <h2 className="mb-2 font-semibold">Categories</h2>
          <table className="w-full min-w-[560px] text-sm"><caption className="sr-only">Category rules</caption>
            <thead className="text-xs text-muted"><tr><th scope="col" className="py-1 text-left font-normal">Category</th><th scope="col" className="py-1 text-left font-normal">Team</th><th scope="col" className="py-1 text-left font-normal">Needs customer confirmation</th></tr></thead>
            <tbody>{Object.entries(s.categories).map(([c, r]) => <tr key={c} className="border-t border-line">
              <th scope="row" className="py-1.5 pr-3 text-left font-normal">{s.labels[c]}</th>
              <td className="py-1.5 pr-3"><SelectInput label={`${s.labels[c]}: team`} value={r.team} onChange={(e) => setS({ ...s, categories: { ...s.categories, [c]: { ...r, team: e.target.value } } })}>
                {Object.entries(s.teams).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</SelectInput></td>
              <td className="py-1.5"><label className="flex min-h-9 items-center gap-2"><input type="checkbox" className="size-4 accent-forest-900" checked={r.needs_confirmation}
                onChange={(e) => setS({ ...s, categories: { ...s.categories, [c]: { ...r, needs_confirmation: e.target.checked } } })} aria-label={`${s.labels[c]}: needs customer confirmation`} />Yes</label></td>
            </tr>)}</tbody></table>
        </section>
        <section aria-label="Escalation" className="rounded-xl bg-white p-4 ring-1 ring-line">
          <h2 className="mb-1 font-semibold">Escalation</h2>
          <p className="mb-2 text-xs text-muted">Level 1 (at risk, or first response overdue) always goes to the ticket’s owner, or CRM managers if it has none.</p>
          {(["level2_roles", "level3_roles"] as const).map((lvl) => <fieldset key={lvl} className="mb-3"><legend className="text-sm font-medium">{lvl === "level2_roles" ? "Level 2 (resolution target breached): tell" : "Level 3 (breached for longer): tell"}</legend>
            <div className="mt-1 flex flex-wrap gap-3">{ESC_ROLES.map((r) => <label key={r} className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900"
              checked={s.escalation[lvl].includes(r)} onChange={() => toggleRole(lvl, r)} />{ROLE_LABELS[r]}</label>)}</div></fieldset>)}
          <div className="max-w-xs"><TextInput label="Level 3 after breaching by (hours)" type="number" min={1} max={720} value={s.escalation.level3_after_hours}
            onChange={(e) => setS({ ...s, escalation: { ...s.escalation, level3_after_hours: Number(e.target.value) } })} /></div>
        </section>
      </fieldset>
      {!ro && <div className="flex justify-end"><Button type="submit" loading={save.isPending}>Save settings</Button></div>}
    </form>
  );
}
