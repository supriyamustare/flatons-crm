import { useState } from "react";
import type { FormEvent } from "react";
import { Check, FileText, X } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { STEPS, useAgreement, useAgreementAction } from "../../hooks/useAgreement";
import type { Agreement } from "../../hooks/useAgreement";
import { inr } from "../../hooks/useLedger";
import { errorMessage, formatDateTime } from "../../lib/api";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

function Checklist({ title, items }: { title: string; items: { item: string; ok: boolean; detail?: string | null }[] }) {
  return (
    <section aria-label={title} className="rounded-xl bg-white p-4 ring-1 ring-line">
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ul className="space-y-1.5 text-sm">{items.map((c) => (
        <li key={c.item} className="flex items-start gap-2">
          {c.ok ? <Check className="mt-0.5 size-4 shrink-0 text-forest-700" aria-hidden /> : <X className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />}
          <span>{c.item}<span className="sr-only">{c.ok ? ": done" : ": not yet"}</span>{c.detail && <span className="block text-xs text-muted">{c.detail}</span>}</span>
        </li>))}</ul>
    </section>
  );
}

function Execution({ a, caseId, canEdit }: { a: Agreement; caseId: number; canEdit: boolean }) {
  const act = useAgreementAction(caseId); const toast = useToast();
  const local = (iso: string | null) => (iso ? new Date(iso).toLocaleString("sv-SE", { timeZone: "Asia/Kolkata" }).slice(0, 16).replace(" ", "T") : "");
  const [f, setF] = useState({ stamp_duty_amount: String(a.stamp_duty_amount ?? ""), stamp_duty_paid_on: a.stamp_duty_paid_on ?? "", stamp_duty_ref: a.stamp_duty_ref ?? "",
    registration_fee_amount: String(a.registration_fee_amount ?? ""), registration_fee_paid_on: a.registration_fee_paid_on ?? "", registration_fee_ref: a.registration_fee_ref ?? "",
    appointment_at: local(a.appointment_at), sro_office: a.sro_office ?? "", id_docs_ready: a.id_docs_ready, signing_note: a.signing_note ?? "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const v = (x: string) => x.trim() || null;
  const save = (e: FormEvent) => { e.preventDefault();
    act.mutate({ method: "put", path: "/execution", body: { stamp_duty_amount: f.stamp_duty_amount ? Number(f.stamp_duty_amount) : null, stamp_duty_paid_on: f.stamp_duty_paid_on || null,
      stamp_duty_ref: v(f.stamp_duty_ref), registration_fee_amount: f.registration_fee_amount ? Number(f.registration_fee_amount) : null, registration_fee_paid_on: f.registration_fee_paid_on || null,
      registration_fee_ref: v(f.registration_fee_ref), appointment_at: f.appointment_at ? new Date(f.appointment_at + ":00+05:30").toISOString() : null, sro_office: v(f.sro_office),
      id_docs_ready: f.id_docs_ready, signing_note: v(f.signing_note) } }, { onSuccess: () => toast("Execution details saved") }); };
  return (
    <form onSubmit={save} aria-label="Execution preparation" className="space-y-3 rounded-xl bg-white p-4 ring-1 ring-line">
      <h3 className="font-semibold">Execution preparation</h3>
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      <fieldset disabled={!canEdit} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <TextInput label="Stamp duty (₹)" inputMode="numeric" value={f.stamp_duty_amount} onChange={set("stamp_duty_amount")} />
          <TextInput label="Stamp duty paid on" type="date" max={today()} value={f.stamp_duty_paid_on} onChange={set("stamp_duty_paid_on")} />
          <TextInput label="Stamp duty reference" value={f.stamp_duty_ref} onChange={set("stamp_duty_ref")} maxLength={80} placeholder="e.g. GRAS challan no." />
          <TextInput label="Registration fee (₹)" inputMode="numeric" value={f.registration_fee_amount} onChange={set("registration_fee_amount")} />
          <TextInput label="Registration fee paid on" type="date" max={today()} value={f.registration_fee_paid_on} onChange={set("registration_fee_paid_on")} />
          <TextInput label="Registration fee reference" value={f.registration_fee_ref} onChange={set("registration_fee_ref")} maxLength={80} />
          <TextInput label="Registration appointment" type="datetime-local" value={f.appointment_at} onChange={set("appointment_at")} />
          <TextInput label="Sub-registrar office" value={f.sro_office} onChange={set("sro_office")} maxLength={150} placeholder="e.g. Haveli 1, Pune" />
        </div>
        <label className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={f.id_docs_ready} onChange={(e) => setF({ ...f, id_docs_ready: e.target.checked })} />
          Identity documents ready for all purchasers and witnesses</label>
        <TextArea label="Signing arrangements" value={f.signing_note} onChange={set("signing_note")} rows={2} maxLength={2000} placeholder="Who attends, witnesses, power of attorney…" />
        {canEdit && <div className="flex justify-end"><Button type="submit" loading={act.isPending}>Save execution details</Button></div>}
      </fieldset>
    </form>
  );
}

export function AgreementTab({ caseId }: { caseId: number }) {
  const q = useAgreement(caseId); const act = useAgreementAction(caseId); const toast = useToast();
  const [dlg, setDlg] = useState<null | "changes" | "share" | "register" | "cancel" | "final">(null);
  const [reason, setReason] = useState(""); const [method, setMethod] = useState("email"); const [file, setFile] = useState<File | null>(null);
  const [reg, setReg] = useState({ executed_on: today(), registration_no: "", registered_on: today(), sro_office: "" });
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const { agreement: a, conditions, checks, can, history } = q.data;
  const go = (path: string, msg: string, body?: unknown) => act.mutate({ path, body }, { onSuccess: () => { toast(msg); setDlg(null); setReason(""); } });
  const stepIdx = a ? Math.max(0, STEPS.findIndex(([k]) => k === (a.status === "changes_requested" ? "drafted" : a.status))) : -1;
  return (
    <section role="tabpanel" aria-label="Agreement" className="space-y-4">
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {!a ? (<>
        <Checklist title="Ready to start the agreement?" items={conditions} />
        {can.initiate ? <Button onClick={() => go("/initiate", "Agreement started")}>Start agreement</Button>
          : <p className="text-sm text-muted">The agreement can start once every condition above is met. The conditions are set per project.</p>}
      </>) : (<>
        <div className="rounded-xl bg-white p-4 ring-1 ring-line">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-semibold">{a.agreement_no} {a.status === "completed" ? <Badge tone="neutral">Released to customer</Badge> : a.status === "changes_requested" ? <Badge tone="gold">Changes requested</Badge> : null}
              {a.version > 0 && <span className="font-normal text-muted"> · draft version {a.version}</span>}</p>
            <div className="flex flex-wrap gap-2">
              {a.draft && <a href={`/agreement-draft/${caseId}`} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-sm ring-1 ring-line hover:bg-forest-50"><FileText className="size-4" aria-hidden />View draft</a>}
              {can.cancel && <Button variant="ghost" onClick={() => setDlg("cancel")}>Cancel agreement…</Button>}
            </div>
          </div>
          <ol aria-label="Agreement progress" className="mt-3 flex flex-wrap gap-1.5 text-xs">{STEPS.map(([k, label], i) => (
            <li key={k} aria-current={i === stepIdx ? "step" : undefined} className={cx("rounded-full px-2.5 py-1", i < stepIdx ? "bg-forest-100 text-forest-900" : i === stepIdx ? "bg-forest-900 text-white" : "bg-paper text-muted")}>
              {i < stepIdx && <Check className="mr-0.5 inline size-3" aria-hidden />}{label}</li>))}</ol>
          {a.changes_note && a.status === "changes_requested" && <div className="mt-3"><Alert>Changes requested: {a.changes_note}</Alert></div>}
        </div>
        {(a.status === "initiated" || a.status === "data_verified" || a.status === "changes_requested") && <Checklist title="Data checks" items={checks} />}
        <div className="flex flex-wrap gap-2">
          {can.verify && <Button onClick={() => go("/verify", "Data verified")}>Confirm data verified</Button>}
          {can.generate && <Button onClick={() => go("/generate", "Draft generated from the template")}>{a.version ? "Generate new draft version" : "Generate draft"}</Button>}
          {can.submit && <Button onClick={() => go("/submit", "Sent to legal and finance for review")}>Send for internal review</Button>}
        </div>
        {a.draft?.placeholder_clauses && <Alert>The project’s agreement clauses are still placeholders. Legal must replace them with the approved wording (Projects → Cost sheet settings → Agreement) before the customer sees a draft.</Alert>}
        {a.status === "internal_review" && (
          <div className="space-y-3 rounded-xl bg-white p-4 text-sm ring-1 ring-line">
            <h3 className="font-semibold">Internal review (version {a.version})</h3>
            <p>Legal: {a.legal_approved_by ? <><Check className="inline size-4 text-forest-700" aria-hidden /> approved by {a.legal_approved_by.full_name}, {formatDateTime(a.legal_approved_at!)}</> : "waiting"}</p>
            <p>Finance: {a.finance_approved_by ? <><Check className="inline size-4 text-forest-700" aria-hidden /> approved by {a.finance_approved_by.full_name}, {formatDateTime(a.finance_approved_at!)}</> : "waiting"}</p>
            <div className="flex flex-wrap gap-2">
              {(can.approve_legal || can.approve_finance) && <Button onClick={() => go("/approve", "Approval recorded")}>Approve{can.approve_legal && !can.approve_finance ? " (legal)" : !can.approve_legal && can.approve_finance ? " (finance)" : ""}</Button>}
              {can.request_changes && <Button variant="secondary" onClick={() => setDlg("changes")}>Request changes</Button>}
              {can.share && <Button onClick={() => setDlg("share")}>Share with customer</Button>}
            </div>
          </div>
        )}
        {a.status === "customer_review" && (
          <div className="space-y-3 rounded-xl bg-white p-4 text-sm ring-1 ring-line">
            <h3 className="font-semibold">Customer review</h3>
            <p>Shared on {a.shared_on} by {a.share_method}.</p>
            <div className="flex flex-wrap gap-2">
              {can.customer_accept && <Button onClick={() => go("/customer-accepted", "Customer accepted the draft")}>Customer accepted</Button>}
              {can.request_changes && <Button variant="secondary" onClick={() => setDlg("changes")}>Customer requested changes</Button>}
            </div>
          </div>
        )}
        {["execution_prep", "registered", "final_uploaded", "completed"].includes(a.status) && <Execution key={a.status} a={a} caseId={caseId} canEdit={!!can.prepare} />}
        {can.register && <Button onClick={() => setDlg("register")}>Record signing and registration</Button>}
        {a.registration_no && <p className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">Executed {a.executed_on} · registered {a.registered_on} as <b>{a.registration_no}</b>{a.sro_office ? ` at ${a.sro_office}` : ""}.</p>}
        {can.upload_final && <Button onClick={() => setDlg("final")}>Upload signed agreement</Button>}
        {a.final_document && <p className="text-sm">Signed agreement: <a href={a.final_document.url} target="_blank" rel="noopener" className="text-forest-800 underline">{a.final_document.doc_no}</a> in 03 Agreements &amp; Legal · {a.final_document.approval === "released" ? "released to the customer" : a.final_document.approval === "under_approval" ? "waiting for review in Documents, then release" : a.final_document.approval}</p>}
      </>)}
      {history.length > 0 && <p className="text-xs text-muted">Cancelled earlier: {history.map((h) => `${h.agreement_no} (${h.cancel_reason})`).join("; ")}</p>}
      {dlg === "changes" && <Modal title="Request changes" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go("/request-changes", "Sent back for changes", { reason: reason.trim() }); }}>
          <TextArea label="What must change?" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={1000} autoFocus />
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={reason.trim().length < 3}>Request changes</Button></div>
        </form></Modal>}
      {dlg === "share" && <Modal title="Share the draft with the customer" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go("/share", "Draft shared with the customer", { method }); }}>
          <SelectInput label="Shared by" value={method} onChange={(e) => setMethod(e.target.value)}>
            {[["email", "Email"], ["hand", "Handed over"], ["courier", "Courier"], ["whatsapp", "WhatsApp"], ["other", "Other"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</SelectInput>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending}>Record as shared</Button></div>
        </form></Modal>}
      {dlg === "register" && <Modal title="Signing and registration" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go("/register", "Registration recorded", { ...reg, sro_office: reg.sro_office.trim() || null }); }}>
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Executed on" type="date" max={today()} value={reg.executed_on} onChange={(e) => setReg({ ...reg, executed_on: e.target.value })} />
            <TextInput label="Registered on" type="date" max={today()} value={reg.registered_on} onChange={(e) => setReg({ ...reg, registered_on: e.target.value })} />
            <TextInput label="Registration number" value={reg.registration_no} onChange={(e) => setReg({ ...reg, registration_no: e.target.value })} maxLength={80} placeholder="Document no. from the sub-registrar" />
            <TextInput label="Sub-registrar office" value={reg.sro_office} onChange={(e) => setReg({ ...reg, sro_office: e.target.value })} maxLength={150} />
          </div>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={reg.registration_no.trim().length < 3}>Record registration</Button></div>
        </form></Modal>}
      {dlg === "final" && <Modal title="Upload the signed agreement" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (!file) return; const fd = new FormData(); fd.append("file", file); go("/final", "Signed agreement uploaded to 03 Agreements & Legal for review", fd); }}>
          <div className="space-y-1.5"><label htmlFor="final-file" className="block text-sm font-medium">Signed and registered agreement (PDF)</label>
            <input id="final-file" type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" /></div>
          <p className="text-xs text-muted">It goes into the customer folder (03), linked to this agreement, for review and release.</p>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={!file}>Upload</Button></div>
        </form></Modal>}
      {dlg === "cancel" && <Modal title="Cancel the agreement" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); go("/cancel", "Agreement cancelled", { reason: reason.trim() }); }}>
          <p className="text-sm">It stays on record with your reason; a new agreement can then be started.</p>
          <TextArea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={1000} autoFocus />
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Back</Button><Button type="submit" variant="danger" loading={act.isPending} disabled={reason.trim().length < 3}>Cancel agreement</Button></div>
        </form></Modal>}
      {a?.stamp_duty_amount != null && <span className="sr-only">Stamp duty {inr(a.stamp_duty_amount)}</span>}
    </section>
  );
}
