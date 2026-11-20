import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput } from "../ui";
import { useToast } from "../Toast";
import { useCurrentUser } from "../../hooks/useAuth";
import { useMilestones, useProjectUpdates } from "../../hooks/useDemands";
import type { ProjectUpdate } from "../../hooks/useDemands";
import { api, errorMessage, formatDateTime } from "../../lib/api";

const AUTHORS = ["admin", "crm_manager", "project_manager", "postsales_exec"];
const LABEL = { draft: "Returned for changes", pending_approval: "Waiting for approval", published: "Published" } as const;

/** Customer-facing updates: written, approved by someone else, published; corrections keep the earlier wording. */
export function ProjectUpdates({ projectId }: { projectId: number }) {
  const me = useCurrentUser();
  const q = useProjectUpdates(projectId, true);
  const ms = useMilestones(projectId, true);
  const qc = useQueryClient(); const toast = useToast();
  const [dlg, setDlg] = useState<null | { mode: "write" } | { mode: "edit" | "correct" | "return"; u: ProjectUpdate }>(null);
  const [f, setF] = useState({ title: "", body: "", milestone_id: "", reason: "" });
  const [photos, setPhotos] = useState<File[]>([]);
  const act = useMutation({
    mutationFn: async ({ method, path, body }: { method: "post" | "put"; path: string; body?: unknown }) => (method === "put" ? await api.put(path, body) : await api.post(path, body)).data,
    onSuccess: (data) => { qc.setQueryData(["project-updates", projectId], data); },
  });
  const done = (msg: string) => ({ onSuccess: () => { toast(msg); setDlg(null); } });
  const open = (d: NonNullable<typeof dlg>) => { setF({ title: "u" in d ? d.u.title : "", body: "u" in d ? d.u.body : "", milestone_id: "", reason: "" }); setPhotos([]); act.reset(); setDlg(d); };
  if (!q.data) return null;
  const submit = (e: FormEvent) => {
    e.preventDefault(); if (!dlg) return;
    if (dlg.mode === "write") {
      const fd = new FormData(); fd.append("title", f.title.trim()); fd.append("body", f.body.trim()); if (f.milestone_id) fd.append("milestone_id", f.milestone_id);
      photos.forEach((p) => fd.append("photos", p));
      act.mutate({ method: "post", path: `/projects/${projectId}/updates`, body: fd }, done("Update written; waiting for approval"));
    } else if (dlg.mode === "edit") act.mutate({ method: "put", path: `/project-updates/${dlg.u.id}`, body: { title: f.title.trim(), body: f.body.trim() } }, done("Update saved and sent for approval"));
    else if (dlg.mode === "correct") act.mutate({ method: "post", path: `/project-updates/${dlg.u.id}/correct`, body: { title: f.title.trim(), body: f.body.trim(), reason: f.reason.trim() } }, done("Correction published; the earlier wording is kept"));
    else act.mutate({ method: "post", path: `/project-updates/${dlg.u.id}/return`, body: { reason: f.reason.trim() } }, done("Returned to the author"));
  };
  const needsText = dlg && dlg.mode !== "return"; const needsReason = dlg && (dlg.mode === "correct" || dlg.mode === "return");
  const ok = (!needsText || (f.title.trim().length >= 3 && f.body.trim().length >= 10)) && (!needsReason || f.reason.trim().length >= 3);
  return (
    <section id="updates" aria-labelledby="pu-h" className="mt-8">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="pu-h" className="font-display text-xl text-forest-900">Project updates for customers</h2>
        {AUTHORS.includes(me.role) && <Button onClick={() => open({ mode: "write" })}><Plus className="size-4" aria-hidden />Write update</Button>}
      </div>
      <p className="mb-3 text-xs text-muted">Published updates appear in the customer portal (when it opens). Someone other than the author approves each one; corrections keep the earlier wording.</p>
      {q.data.length === 0 ? <p className="rounded-xl border border-dashed border-line bg-white px-6 py-6 text-center text-sm text-muted">No updates yet.</p> : (
        <ul className="space-y-3">{q.data.map((u) => (
          <li key={u.id} className="rounded-xl bg-white p-4 ring-1 ring-line">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="font-semibold">{u.title} <Badge tone={u.status === "published" ? "neutral" : "gold"}>{LABEL[u.status]}</Badge></p>
                <p className="mt-1 whitespace-pre-wrap text-sm">{u.body}</p>
                {u.photos.length > 0 && <p className="mt-1 flex flex-wrap gap-2 text-xs">{u.photos.map((p) => <a key={p.id} href={p.url} target="_blank" rel="noopener" className="text-forest-800 underline">{p.file_name}</a>)}</p>}
                <p className="mt-1 text-xs text-muted">By {u.author ?? "—"}{u.milestone ? ` · about ${u.milestone}` : ""}{u.published_at ? ` · published ${formatDateTime(u.published_at)} by ${u.published_by}` : ""}</p>
                {u.returned_reason && u.status === "draft" && <p className="text-xs text-danger">Returned: {u.returned_reason}</p>}
                {u.corrections.length > 0 && <details className="mt-1 text-xs"><summary className="cursor-pointer text-forest-800">Corrections ({u.corrections.length})</summary>
                  <ol className="mt-1 space-y-1">{u.corrections.map((c, i) => <li key={i}>{formatDateTime(c.at)} by {c.by ?? "—"}: {c.reason}. Earlier wording: “{c.previous_title}: {c.previous_body}”</li>)}</ol></details>}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {u.can_publish && <><Button loading={act.isPending} onClick={() => act.mutate({ method: "post", path: `/project-updates/${u.id}/publish` }, { onSuccess: () => toast(`“${u.title}” published`) })}>Publish</Button>
                  <Button variant="secondary" onClick={() => open({ mode: "return", u })}>Return</Button></>}
                {u.status === "pending_approval" && !u.can_publish && <span className="self-center text-xs text-muted">Someone other than the author publishes</span>}
                {u.can_edit && <Button variant="ghost" onClick={() => open({ mode: "edit", u })}>Edit</Button>}
                {u.can_correct && <Button variant="ghost" onClick={() => open({ mode: "correct", u })}>Correct</Button>}
              </div>
            </div>
          </li>))}</ul>
      )}
      {dlg && <Modal title={{ write: "Write a customer update", edit: "Edit the update", correct: "Correct the published update", return: "Return to the author" }[dlg.mode]} onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={submit}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          {needsText && <>
            <TextInput label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} maxLength={200} />
            <TextArea label="Update for customers" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} rows={5} maxLength={5000} hint="Plain, customer-friendly wording. No internal details or dates you can’t commit to." />
          </>}
          {dlg.mode === "write" && <>
            <SelectInput label="About milestone (optional)" value={f.milestone_id} onChange={(e) => setF({ ...f, milestone_id: e.target.value })}><option value="">—</option>
              {(ms.data ?? []).filter((m) => m.id != null).map((m) => <option key={m.id!} value={m.id!}>{m.name}</option>)}</SelectInput>
            <div className="space-y-1.5"><label htmlFor="pu-photos" className="block text-sm font-medium">Photos for customers (optional)</label>
              <input id="pu-photos" type="file" multiple accept=".jpg,.jpeg,.png" onChange={(e) => setPhotos(Array.from(e.target.files ?? []).slice(0, 8))}
                className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" /></div>
          </>}
          {needsReason && <TextArea label={dlg.mode === "correct" ? "Reason for the correction" : "What should change?"} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} rows={2} maxLength={500} />}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button>
            <Button type="submit" loading={act.isPending} disabled={!ok}>{{ write: "Send for approval", edit: "Save and send for approval", correct: "Publish correction", return: "Return" }[dlg.mode]}</Button></div>
        </form></Modal>}
    </section>
  );
}
