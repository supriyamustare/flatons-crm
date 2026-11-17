import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileText } from "lucide-react";
import { Alert, Badge, Button, Modal, TextArea, TextInput } from "../ui";
import { useToast } from "../Toast";
import { useMilestones } from "../../hooks/useDemands";
import type { Milestone } from "../../hooks/useDemands";
import { api, errorMessage, formatDateTime } from "../../lib/api";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

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
  const qc = useQueryClient(); const toast = useToast();
  const [reporting, setReporting] = useState<Milestone | null>(null);
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
  if (!q.data) return null;
  const tone = (s: Milestone["status"]) => (s === "verified" ? "neutral" : s === "reported" ? "gold" : "muted") as "neutral" | "gold" | "muted";
  return (
    <section id="milestones" aria-labelledby="ms-h" className="mt-8">
      <h2 id="ms-h" className="mb-3 font-display text-xl text-forest-900">Construction milestones</h2>
      {act.isError && <div className="mb-2"><Alert>{errorMessage(act.error)}</Alert></div>}
      <ul className="divide-y divide-line rounded-xl bg-white ring-1 ring-line">
        {q.data.map((m) => (
          <li key={m.name} className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 text-sm">
            <div className="min-w-0">
              <p className="font-medium">{m.status === "verified" && <CheckCircle2 className="mr-1 inline size-4 text-forest-700" aria-hidden />}{m.name} <Badge tone={tone(m.status)}>{m.status === "planned" ? "Planned" : m.status === "reported" ? "Waiting for verification" : "Verified"}</Badge></p>
              {m.completed_on && <p className="text-xs text-muted">Completed {m.completed_on}{m.reported_by ? ` · reported by ${m.reported_by.full_name}` : ""}{m.verified_by ? ` · verified by ${m.verified_by.full_name}${m.verified_at ? `, ${formatDateTime(m.verified_at)}` : ""}` : ""}</p>}
              {m.returned_reason && m.status === "planned" && <p className="text-xs text-danger">Returned: {m.returned_reason}</p>}
              {m.evidence.length > 0 && <p className="mt-1 flex flex-wrap gap-2 text-xs">{m.evidence.map((e) => <a key={e.id} href={e.url} target="_blank" rel="noopener" className="inline-flex items-center gap-1 text-forest-800 underline"><FileText className="size-3.5" aria-hidden />{e.file_name}</a>)}</p>}
            </div>
            <div className="flex gap-2">
              {m.can_report && <Button variant="ghost" onClick={() => setReporting(m)}>{m.status === "reported" ? "Add evidence" : "Report complete"}</Button>}
              {m.can_verify && <><Button variant="secondary" loading={act.isPending} onClick={() => act.mutate({ m, kind: "verify" })}>Verify</Button>
                <Button variant="ghost" onClick={() => setReturning(m)}>Return</Button></>}
              {m.status === "reported" && !m.can_verify && <span className="self-center text-xs text-muted">Someone other than the reporter verifies</span>}
            </div>
          </li>
        ))}
      </ul>
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
