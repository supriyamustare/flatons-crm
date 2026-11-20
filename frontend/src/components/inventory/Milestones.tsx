import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText } from "lucide-react";
import { Alert, Badge, Button, Modal, TextArea, TextInput } from "../ui";
import { useToast } from "../Toast";
import { useMilestones } from "../../hooks/useDemands";
import { useCurrentUser } from "../../hooks/useAuth";
import type { Milestone } from "../../hooks/useDemands";
import { api, errorMessage, formatDateTime } from "../../lib/api";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

function ProgressDialog({ projectId, m, onClose }: { projectId: number; m: Milestone; onClose: () => void }) {
  const qc = useQueryClient(); const toast = useToast();
  const [f, setF] = useState({ percent: String(m.percent_complete ?? ""), planned: m.planned_on ?? "", phase: m.phase ?? "", tower: m.building_label ?? "", delayed: !!m.delay_reason,
    reason: m.delay_reason ?? "", revised: m.revised_expected_on ?? "", note: "" });
  const [files, setFiles] = useState<File[]>([]);
  const send = useMutation({
    mutationFn: async () => {
      const form = new FormData(); form.append("name", m.name);
      if (f.percent !== "") form.append("percent_complete", f.percent); if (f.planned) form.append("planned_on", f.planned);
      if (f.phase.trim()) form.append("phase", f.phase.trim()); if (f.tower.trim()) form.append("building_label", f.tower.trim());
      if (f.delayed && f.reason.trim()) { form.append("delay_reason", f.reason.trim()); form.append("revised_expected_on", f.revised); }
      if (f.note.trim()) form.append("note", f.note.trim()); files.forEach((x) => form.append("files", x));
      return (await api.post(`/projects/${projectId}/milestones/progress`, form)).data;
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["milestones", projectId] }); toast(`Progress recorded for ${m.name}`); onClose(); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const delayOk = !f.delayed || (f.reason.trim().length >= 3 && !!f.revised);
  return (
    <Modal title={`Update progress: ${m.name}`} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); send.mutate(); }}>
        {send.isError && <Alert>{errorMessage(send.error)}</Alert>}
        <p className="text-xs text-muted">Progress is for tracking and customer updates. It never raises a demand; only verified completion does.</p>
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Percentage complete" type="number" min={0} max={100} value={f.percent} onChange={set("percent")} />
          <TextInput label="Planned completion" type="date" value={f.planned} onChange={set("planned")} />
          <TextInput label="Phase" value={f.phase} onChange={set("phase")} maxLength={80} />
          <TextInput label="Tower / building" value={f.tower} onChange={set("tower")} maxLength={80} />
        </div>
        <label className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={f.delayed} onChange={(e) => setF({ ...f, delayed: e.target.checked })} />Delayed</label>
        {f.delayed && <div className="grid grid-cols-2 gap-3 rounded-lg bg-gold-100/50 p-3">
          <TextInput label="Delay reason" value={f.reason} onChange={set("reason")} maxLength={500} />
          <TextInput label="Revised expected date" type="date" value={f.revised} onChange={set("revised")} /></div>}
        <TextArea label="Note (optional)" value={f.note} onChange={set("note")} rows={2} maxLength={2000} />
        <div className="space-y-1.5"><label htmlFor="prog-files" className="block text-sm font-medium">Photos (optional)</label>
          <input id="prog-files" type="file" multiple accept=".jpg,.jpeg,.png,.pdf" onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 10))}
            className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" /></div>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={send.isPending} disabled={!delayOk}>Save progress</Button></div>
      </form>
    </Modal>
  );
}

function ReportDialog({ projectId, m, onClose }: { projectId: number; m: Milestone; onClose: () => void }) {
  const qc = useQueryClient(); const toast = useToast();
  const [when, setWhen] = useState(today()); const [note, setNote] = useState(""); const [files, setFiles] = useState<File[]>([]);
  const send = useMutation({
    mutationFn: async () => {
      const form = new FormData(); form.append("name", m.name); form.append("completed_on", when); if (note.trim()) form.append("note", note.trim());
      files.forEach((f) => form.append("files", f));
      return (await api.post(`/projects/${projectId}/milestones/report`, form)).data;
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["milestones", projectId] }); toast(`${m.name} reported complete; waiting for verification`); onClose(); },
  });
  return (
    <Modal title={`Report complete: ${m.name}`} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); send.mutate(); }}>
        {send.isError && <Alert>{errorMessage(send.error)}</Alert>}
        {m.returned_reason && <Alert>Returned earlier: {m.returned_reason}</Alert>}
        <TextInput label="Completed on" type="date" value={when} max={today()} onChange={(e) => setWhen(e.target.value)} />
        <div className="space-y-1.5"><label htmlFor="ev-files" className="block text-sm font-medium">Evidence (photos or certificates)</label>
          <input id="ev-files" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 10))}
            className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" />
          <p className="text-xs text-muted">1 to 10 files: PDF, JPG or PNG, up to 15 MB each.</p></div>
        <TextArea label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={send.isPending} disabled={!files.length || !when}>Report complete</Button></div>
      </form>
    </Modal>
  );
}

/** Construction milestones (post-sales): reported with evidence, verified by someone else; verifying demands the stage. */
export function ProjectMilestones({ projectId }: { projectId: number }) {
  const q = useMilestones(projectId, true);
  const location = useLocation();
  const qc = useQueryClient(); const toast = useToast();
  const [reporting, setReporting] = useState<Milestone | null>(null);
  const [progressing, setProgressing] = useState<Milestone | null>(null);
  const [impactFor, setImpactFor] = useState<Milestone | null>(null);
  const [impact, setImpact] = useState("");
  const me = useCurrentUser();
  const canImpact = ["admin", "project_manager", "crm_manager"].includes(me.role);
  const impactAct = useMutation({
    mutationFn: async (m: Milestone) => (await api.post(`/projects/${projectId}/milestones/${m.id}${impactFor?.id === m.id ? "/impact" : "/impact/approve"}`, impactFor?.id === m.id ? { impact: impact.trim() } : undefined)).data,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["milestones", projectId] }); toast(impactFor ? "Schedule impact recorded; waiting for approval" : "Schedule impact approved"); setImpactFor(null); },
  });
  const [returning, setReturning] = useState<Milestone | null>(null);
  const [reason, setReason] = useState("");
  const act = useMutation({
    mutationFn: async ({ m, kind }: { m: Milestone; kind: "verify" | "return" }) =>
      (await api.post(`/projects/${projectId}/milestones/${m.id}/${kind}`, kind === "return" ? { reason: reason.trim() } : undefined)).data as
        { cases?: number; demands?: number; ledgers_not_approved?: number; due_date?: string },
    onSuccess: (r, { m, kind }) => {
      void qc.invalidateQueries({ queryKey: ["milestones", projectId] });
      if (kind === "verify") toast(`${m.name} verified: ${r.cases ?? 0} bookings demanded (due ${r.due_date}), ${r.demands ?? 0} draft demands${r.ledgers_not_approved ? `; ${r.ledgers_not_approved} ledgers not yet approved` : ""}`);
      else { toast(`${m.name} returned`); setReturning(null); setReason(""); }
    },
  });
  // Opened from a notification (/projects/1#milestones): scroll here once the list has loaded
  useEffect(() => {
    if (q.data && location.hash === "#milestones") document.getElementById("milestones")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [q.data, location.hash]);
  if (!q.data) return null;
  const tone = (s: Milestone["status"]) => (s === "verified" ? "neutral" : s === "reported" ? "gold" : "muted") as "neutral" | "gold" | "muted";
  return (
    <section id="milestones" aria-labelledby="ms-h" className="relative z-30 -mx-4 mt-4 bg-paper px-4 pt-4">
      <h2 id="ms-h" className="mb-3 font-display text-xl text-forest-900">Construction milestones</h2>
      {act.isError && <div className="mb-2"><Alert>{errorMessage(act.error)}</Alert></div>}
      <ul className="divide-y divide-line rounded-xl bg-white ring-1 ring-line">
        {q.data.map((m) => (
          <li key={m.name} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <div className="min-w-0">
              <p className="font-medium">{m.status === "verified" && <CheckCircle2 className="mr-1 inline size-4 text-forest-700" aria-hidden />}{m.name} <Badge tone={tone(m.status)}>{m.status === "planned" ? "Planned" : m.status === "reported" ? "Waiting for verification" : "Verified"}</Badge></p>
              {m.completed_on && <p className="text-xs text-muted">Completed {m.completed_on}{m.reported_by ? ` · reported by ${m.reported_by.full_name}` : ""}{m.verified_by ? ` · verified by ${m.verified_by.full_name}${m.verified_at ? `, ${formatDateTime(m.verified_at)}` : ""}` : ""}</p>}
              {m.returned_reason && m.status === "planned" && <p className="text-xs text-danger">Returned: {m.returned_reason}</p>}
              {(m.percent_complete != null || m.planned_on || m.phase || m.building_label) && <p className="text-xs text-muted">
                {m.percent_complete != null && <>{m.percent_complete}% complete</>}{m.planned_on && <> · planned {m.planned_on}</>}{m.phase && <> · {m.phase}</>}{m.building_label && <> · {m.building_label}</>}{m.responsible_pm && <> · PM {m.responsible_pm.full_name}</>}</p>}
              {m.percent_complete != null && m.status !== "verified" && <div className="mt-1 h-1.5 w-40 rounded-full bg-paper" role="progressbar" aria-label={`${m.name} progress`} aria-valuenow={m.percent_complete} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-1.5 rounded-full bg-forest-700" style={{ width: `${m.percent_complete}%` }} /></div>}
              {m.delay_reason && m.status !== "verified" && <p className="text-xs text-danger">Delayed: {m.delay_reason}. Now expected {m.revised_expected_on}</p>}
              {m.schedule_impact && <p className="text-xs">Schedule impact: {m.schedule_impact} <Badge tone={m.impact_approved_by ? "neutral" : "gold"}>{m.impact_approved_by ? `Approved by ${m.impact_approved_by.full_name}` : "Waiting for approval"}</Badge></p>}
              {(m.progress?.length ?? 0) > 0 && <details className="mt-1 text-xs"><summary className="cursor-pointer text-forest-800">Progress history ({m.progress!.length})</summary>
                <ol className="mt-1 space-y-1">{m.progress!.map((p) => <li key={p.id}>{formatDateTime(p.at)} · {p.by ?? "—"}: {p.percent_complete != null ? `${p.percent_complete}%` : ""}{p.delay_reason ? ` · delayed (${p.delay_reason}), now ${p.revised_expected_on}` : ""}{p.note ? ` · ${p.note}` : ""}
                  {p.photos.map((ph) => <a key={ph.id} href={ph.url} target="_blank" rel="noopener" className="ml-1 text-forest-800 underline">{ph.file_name}</a>)}</li>)}</ol></details>}
              {m.evidence.length > 0 && <p className="mt-1 flex flex-wrap gap-2 text-xs">{m.evidence.map((e) => <a key={e.id} href={e.url} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-forest-800 underline"><FileText className="size-3.5" aria-hidden />{e.file_name}</a>)}</p>}
            </div>
            <div className="flex gap-2">
              {m.can_report && m.status !== "verified" && <Button variant="ghost" onClick={() => setProgressing(m)}>Update progress</Button>}
              {m.can_report && <Button variant="ghost" onClick={() => setReporting(m)}>{m.status === "reported" ? "Add evidence" : "Report complete"}</Button>}
              {m.id != null && canImpact && m.delay_reason && !m.schedule_impact && <Button variant="ghost" onClick={() => { setImpactFor(m); setImpact(""); }}>Record impact</Button>}
              {m.can_approve_impact && <Button variant="secondary" loading={act.isPending} onClick={() => impactAct.mutate(m)}>Approve impact</Button>}
              {m.can_verify && <><Button variant="secondary" loading={act.isPending} onClick={() => act.mutate({ m, kind: "verify" })}>Verify</Button>
                <Button variant="ghost" onClick={() => setReturning(m)}>Return</Button></>}
              {m.status === "reported" && !m.can_verify && <span className="self-center text-xs text-muted">Someone other than the reporter verifies</span>}
            </div>
          </li>
        ))}
      </ul>
      {progressing && <ProgressDialog projectId={projectId} m={progressing} onClose={() => setProgressing(null)} />}
      {impactFor && (
        <Modal title={`Schedule impact: ${impactFor.name}`} onClose={() => setImpactFor(null)}>
          <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); impactAct.mutate(impactFor); }}>
            {impactAct.isError && <Alert>{errorMessage(impactAct.error)}</Alert>}
            <TextArea label="Impact on demands or the possession schedule" value={impact} onChange={(e) => setImpact(e.target.value)} rows={3} maxLength={2000} autoFocus />
            <p className="text-xs text-muted">A CRM manager (not you) approves it before it’s relied on.</p>
            <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setImpactFor(null)}>Cancel</Button><Button type="submit" loading={impactAct.isPending} disabled={impact.trim().length < 3}>Record impact</Button></div>
          </form>
        </Modal>
      )}
      {reporting && <ReportDialog projectId={projectId} m={reporting} onClose={() => setReporting(null)} />}
      {returning && (
        <Modal title={`Return ${returning.name}`} onClose={() => setReturning(null)}>
          <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ m: returning, kind: "return" }); }}>
            <TextArea label="What's missing?" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} autoFocus />
            <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setReturning(null)}>Cancel</Button>
              <Button type="submit" loading={act.isPending} disabled={reason.trim().length < 3}>Return</Button></div>
          </form>
        </Modal>
      )}
    </section>
  );
}
