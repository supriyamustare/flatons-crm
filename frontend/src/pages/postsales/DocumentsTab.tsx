import { useState } from "react";
import type { FormEvent } from "react";
import { FileText, History, Upload } from "lucide-react";
import { Alert, Badge, Button, Modal, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { APPROVAL, VERIFICATION, useDocAction, useFolder } from "../../hooks/useCaseDocs";
import type { CaseDoc, Folder } from "../../hooks/useCaseDocs";
import { errorMessage, formatDateTime } from "../../lib/api";

const kb = (n: number) => (n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

function UploadDialog({ caseId, category, label, replacing, onClose }: { caseId: number; category: string; label: string; replacing?: CaseDoc; onClose: () => void }) {
  const act = useDocAction(caseId); const toast = useToast();
  const [f, setF] = useState({ doc_type: replacing?.doc_type ?? "", title: replacing?.title ?? "", doc_number: replacing?.doc_number ?? "", doc_date: "", expiry_date: "",
    linked_ref: replacing?.linked_ref ?? "", version_reason: "" });
  const [file, setFile] = useState<File | null>(null);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault(); if (!file) return;
    const form = new FormData(); form.append("category", category); form.append("file", file);
    for (const [k, v] of Object.entries(f)) if (v.trim()) form.append(k, v.trim());
    if (replacing) form.append("replaces_id", String(replacing.id));
    act.mutate({ path: `/post-sales/cases/${caseId}/documents`, body: form }, { onSuccess: () => { toast(replacing ? `New version of ${replacing.title} uploaded for review` : "Document uploaded for review"); onClose(); } });
  };
  const ok = file && f.doc_type.trim().length >= 2 && f.title.trim().length >= 2 && (!replacing || f.version_reason.trim().length >= 3);
  return (
    <Modal title={replacing ? `New version: ${replacing.title}` : `Upload to ${label}`} onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        {replacing && <TextArea label="Reason for the new version" value={f.version_reason} onChange={set("version_reason")} rows={2} maxLength={500} autoFocus />}
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Document type" value={f.doc_type} onChange={set("doc_type")} maxLength={120} placeholder="e.g. Allotment letter" />
          <TextInput label="Title" value={f.title} onChange={set("title")} maxLength={200} />
          <TextInput label="Document number (optional)" value={f.doc_number} onChange={set("doc_number")} maxLength={80} />
          <TextInput label="Document date (optional)" type="date" value={f.doc_date} max={today()} onChange={set("doc_date")} />
          <TextInput label="Valid until (optional)" type="date" value={f.expiry_date} onChange={set("expiry_date")} />
          <TextInput label="Linked reference (optional)" value={f.linked_ref} onChange={set("linked_ref")} maxLength={80} placeholder="e.g. DMD-00001" />
        </div>
        <div className="space-y-1.5"><label htmlFor="doc-file" className="block text-sm font-medium">File</label>
          <input id="doc-file" type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" />
          <p className="text-xs text-muted">PDF, JPG or PNG, up to 20 MB. It goes for review before it counts as approved.</p></div>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={!ok}>Upload</Button></div>
      </form>
    </Modal>
  );
}

function DocCard({ d, older, caseId, onReplace }: { d: CaseDoc; older: CaseDoc[]; caseId: number; onReplace: () => void }) {
  const act = useDocAction(caseId); const toast = useToast();
  const [reason, setReason] = useState<null | "reject" | "withdraw">(null); const [text, setText] = useState(""); const [hist, setHist] = useState(false);
  const tone = d.approval === "released" || d.approval === "approved" ? "neutral" : d.approval === "under_approval" ? "gold" : "muted";
  return (
    <li className="rounded-xl bg-white p-4 ring-1 ring-line">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{d.title} <span className="font-normal text-muted">({d.doc_no}{d.version > 1 ? `, version ${d.version}` : ""})</span></p>
          <p className="mt-0.5 flex flex-wrap gap-1"><Badge tone={tone as "neutral" | "gold" | "muted"}>{APPROVAL[d.approval]}</Badge> <Badge tone={d.verification === "verified" ? "neutral" : "muted"}>{VERIFICATION[d.verification]}</Badge>
            {d.visibility === "customer" && <Badge tone="neutral">Customer can see</Badge>}</p>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-muted sm:grid-cols-3">
            <div><dt className="inline">Type: </dt><dd className="inline text-ink">{d.doc_type}</dd></div>
            {d.doc_number && <div><dt className="inline">Number: </dt><dd className="inline text-ink">{d.doc_number}</dd></div>}
            {d.doc_date && <div><dt className="inline">Dated: </dt><dd className="inline text-ink">{d.doc_date}</dd></div>}
            {d.expiry_date && <div><dt className="inline">Valid until: </dt><dd className="inline text-ink">{d.expiry_date}</dd></div>}
            {d.linked_ref && <div><dt className="inline">Linked: </dt><dd className="inline text-ink">{d.linked_ref}</dd></div>}
            <div><dt className="inline">Uploaded: </dt><dd className="inline text-ink">{d.uploaded_by?.full_name ?? "—"}, {formatDateTime(d.uploaded_at)}</dd></div>
            {d.reviewed_by && <div><dt className="inline">Reviewed: </dt><dd className="inline text-ink">{d.reviewed_by.full_name}</dd></div>}
            <div><dt className="inline">File: </dt><dd className="inline text-ink">{d.file_name}, {kb(d.file_size)}</dd></div>
            <div title={d.sha256}><dt className="inline">Fingerprint: </dt><dd className="inline font-mono text-ink">{d.sha256.slice(0, 12)}…</dd></div>
          </dl>
          {d.version_reason && <p className="mt-1 text-xs">Why this version: {d.version_reason}</p>}
          {d.status_reason && <p className="mt-1 text-xs text-danger">{d.approval === "rejected" ? "Rejected" : "Withdrawn"}: {d.status_reason}</p>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          <a href={d.url} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-sm ring-1 ring-line hover:bg-forest-50"><FileText className="size-4" aria-hidden />View</a>
          {d.can_review && <><Button variant="secondary" loading={act.isPending} onClick={() => act.mutate({ path: `/post-sales/documents/${d.id}/approve` }, { onSuccess: () => toast(`${d.title} approved`) })}>Approve</Button>
            <Button variant="ghost" onClick={() => setReason("reject")}>Reject</Button></>}
          {d.approval === "under_approval" && !d.can_review && <span className="self-center text-xs text-muted">Waiting for a reviewer (not the uploader)</span>}
          {d.can_release && <Button loading={act.isPending} onClick={() => act.mutate({ path: `/post-sales/documents/${d.id}/release` }, { onSuccess: () => toast(`${d.title} released to the customer`) })}>Release to customer</Button>}
          {d.can_withdraw && <Button variant="ghost" onClick={() => setReason("withdraw")}>Withdraw</Button>}
          {d.can_replace && <Button variant="ghost" onClick={onReplace}>New version</Button>}
          {older.length > 0 && <Button variant="ghost" aria-expanded={hist} onClick={() => setHist(!hist)}><History className="size-4" aria-hidden />History ({older.length})</Button>}
        </div>
      </div>
      {act.isError && <div className="mt-2"><Alert>{errorMessage(act.error)}</Alert></div>}
      {hist && <ol className="mt-3 space-y-1 border-t border-line pt-2 text-xs" aria-label={`Earlier versions of ${d.title}`}>
        {older.map((o) => <li key={o.id}><a href={o.url} target="_blank" rel="noopener" className="text-forest-800 underline">{o.doc_no} version {o.version}</a> · {APPROVAL[o.approval]} · {formatDateTime(o.uploaded_at)}{o.status_reason ? ` · ${o.status_reason}` : ""}</li>)}</ol>}
      {reason && (
        <Modal title={reason === "reject" ? `Reject ${d.title}` : `Withdraw ${d.title}`} onClose={() => setReason(null)}>
          <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ path: `/post-sales/documents/${d.id}/${reason}`, body: { reason: text.trim() } },
            { onSuccess: () => { toast(reason === "reject" ? `${d.title} rejected` : `${d.title} withdrawn`); setReason(null); setText(""); } }); }}>
            {reason === "withdraw" && d.visibility === "customer" && <p className="text-sm">The customer will no longer see this document.</p>}
            <TextArea label="Reason" value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={500} autoFocus />
            <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setReason(null)}>Cancel</Button>
              <Button type="submit" variant="danger" loading={act.isPending} disabled={text.trim().length < 3}>{reason === "reject" ? "Reject" : "Withdraw"}</Button></div>
          </form>
        </Modal>
      )}
    </li>
  );
}

export function DocumentsTab({ caseId }: { caseId: number }) {
  const q = useFolder(caseId);
  const [sel, setSel] = useState<string | null>(null);
  const [upload, setUpload] = useState<null | { replacing?: CaseDoc }>(null);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const f: Folder = q.data;
  const cat = f.categories.find((c) => c.key === sel) ?? f.categories[0];
  if (!cat) return null;
  const live = f.documents.filter((d) => d.category === cat.key && !d.superseded);
  const olderOf = (d: CaseDoc) => { const out: CaseDoc[] = []; let s = d.supersedes; while (s) { const o = f.documents.find((x) => x.doc_no === s); if (!o) break; out.push(o); s = o.supersedes; } return out; };
  const system = f.system.filter((s) => s.category === cat.key);
  return (
    <section role="tabpanel" aria-label="Documents" className="grid gap-4 md:grid-cols-[16rem_1fr]">
      <nav aria-label="Folders" className="self-start rounded-xl bg-white p-2 ring-1 ring-line">
        <ul className="space-y-0.5">{f.categories.map((c) => (
          <li key={c.key}><button type="button" aria-current={c.key === cat.key ? "true" : undefined} onClick={() => setSel(c.key)}
            className={cx("flex min-h-10 w-full items-center justify-between rounded-lg px-3 text-left text-sm", c.key === cat.key ? "bg-forest-900 text-white" : "hover:bg-forest-50")}>
            <span>{c.label}</span><span className={cx("tabular-nums text-xs", c.key === cat.key ? "text-forest-100" : "text-muted")}>{c.count}</span></button></li>))}</ul>
      </nav>
      <div className="min-w-0 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{cat.label}</h3>
          {cat.can_upload && <Button onClick={() => setUpload({})}><Upload className="size-4" aria-hidden />Upload</Button>}</div>
        {system.length > 0 && <ul aria-label="Generated by the CRM" className="space-y-1.5">{system.map((s, i) => (
          <li key={i} className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-paper px-4 py-2.5 text-sm ring-1 ring-line">
            <span><b>{s.title}</b> <span className="text-muted">{s.kind}{s.number ? ` · ${s.number}` : ""}{s.date ? ` · ${s.date}` : ""}</span> <Badge tone="muted">Generated</Badge></span>
            <a href={s.url} target="_blank" rel="noopener" className="text-forest-800 underline">Open</a></li>))}</ul>}
        {live.length === 0 && system.length === 0 && <p className="rounded-xl border border-dashed border-line bg-white px-6 py-8 text-center text-sm text-muted">Nothing in this folder yet.</p>}
        <ul className="space-y-3">{live.map((d) => <DocCard key={d.id} d={d} older={olderOf(d)} caseId={caseId} onReplace={() => setUpload({ replacing: d })} />)}</ul>
      </div>
      {upload && <UploadDialog caseId={caseId} category={cat.key} label={cat.label} replacing={upload.replacing} onClose={() => setUpload(null)} />}
    </section>
  );
}
