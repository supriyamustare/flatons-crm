import { useState } from "react";
import type { FormEvent } from "react";
import { Check, Plus } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { inr } from "../../hooks/useLedger";
import { VSTATES, useLoan, useLoanAction } from "../../hooks/useLoan";
import type { Disb, LoanRow, LoanState, VState } from "../../hooks/useLoan";
import { errorMessage } from "../../lib/api";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const num = (v: string) => Math.round(Number(v.replace(/[,₹\s]/g, "")) || 0);

function DetailsForm({ s, caseId, loan, onDone }: { s: LoanState; caseId: number; loan: LoanRow | null; onDone?: () => void }) {
  const act = useLoanAction(caseId); const toast = useToast();
  const [f, setF] = useState({ lender: loan?.lender ?? "", application_no: loan?.application_no ?? "", consent_on: loan?.consent_on ?? "", applied_amount: String(loan?.applied_amount ?? ""),
    sanctioned_amount: String(loan?.sanctioned_amount ?? ""), sanction_date: loan?.sanction_date ?? "", sanction_valid_until: loan?.sanction_valid_until ?? "",
    rm_name: loan?.rm_name ?? "", rm_phone: loan?.rm_phone ?? "", rm_email: loan?.rm_email ?? "", technical_status: (loan?.technical_status ?? "not_started") as VState,
    legal_status: (loan?.legal_status ?? "not_started") as VState, pending_conditions: loan?.pending_conditions ?? "", owner_id: String(loan?.owner_id ?? ""), next_follow_up_on: loan?.next_follow_up_on ?? "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const v = (x: string) => x.trim() || null;
  const submit = (e: FormEvent) => { e.preventDefault();
    act.mutate({ method: loan ? "put" : "post", body: { lender: f.lender.trim(), application_no: v(f.application_no), consent_on: f.consent_on || null,
      applied_amount: f.applied_amount ? num(f.applied_amount) : null, sanctioned_amount: f.sanctioned_amount ? num(f.sanctioned_amount) : null, sanction_date: f.sanction_date || null,
      sanction_valid_until: f.sanction_valid_until || null, rm_name: v(f.rm_name), rm_phone: v(f.rm_phone), rm_email: v(f.rm_email), technical_status: f.technical_status,
      legal_status: f.legal_status, pending_conditions: v(f.pending_conditions), owner_id: f.owner_id ? Number(f.owner_id) : null, next_follow_up_on: f.next_follow_up_on || null } },
      { onSuccess: () => { toast(loan ? "Loan details saved" : "Loan added"); onDone?.(); } }); };
  const ro = !s.can_edit;
  return (
    <form onSubmit={submit} aria-label="Loan details" className="space-y-3 rounded-xl bg-white p-4 ring-1 ring-line">
      <h3 className="font-semibold">Loan details</h3>
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      <fieldset disabled={ro} className="space-y-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <TextInput label="Bank / lender" value={f.lender} onChange={set("lender")} maxLength={150} />
          <TextInput label="Application number" value={f.application_no} onChange={set("application_no")} maxLength={80} />
          <TextInput label="Customer consent given on" type="date" max={today()} value={f.consent_on} onChange={set("consent_on")} hint="Needed before coordinating with the bank" />
          <TextInput label="Applied amount (₹)" inputMode="numeric" value={f.applied_amount} onChange={set("applied_amount")} />
          <TextInput label="Sanctioned amount (₹)" inputMode="numeric" value={f.sanctioned_amount} onChange={set("sanctioned_amount")} />
          <TextInput label="Sanction date" type="date" max={today()} value={f.sanction_date} onChange={set("sanction_date")} />
          <TextInput label="Sanction valid until" type="date" value={f.sanction_valid_until} onChange={set("sanction_valid_until")} />
          <TextInput label="Bank RM name" value={f.rm_name} onChange={set("rm_name")} maxLength={150} />
          <TextInput label="Bank RM phone" type="tel" value={f.rm_phone} onChange={set("rm_phone")} maxLength={20} />
          <TextInput label="Bank RM email" type="email" value={f.rm_email} onChange={set("rm_email")} maxLength={254} />
          <SelectInput label="Technical verification" value={f.technical_status} onChange={set("technical_status")}>{(Object.keys(VSTATES) as VState[]).map((k) => <option key={k} value={k}>{VSTATES[k]}</option>)}</SelectInput>
          <SelectInput label="Legal verification" value={f.legal_status} onChange={set("legal_status")}>{(Object.keys(VSTATES) as VState[]).map((k) => <option key={k} value={k}>{VSTATES[k]}</option>)}</SelectInput>
          <SelectInput label="Follow-up owner" value={f.owner_id} onChange={set("owner_id")}><option value="">—</option>{s.owners.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</SelectInput>
          <TextInput label="Next follow-up" type="date" min={today()} value={f.next_follow_up_on} onChange={set("next_follow_up_on")} />
        </div>
        <TextArea label="Pending bank conditions" value={f.pending_conditions} onChange={set("pending_conditions")} rows={2} maxLength={2000} />
        {!ro && <div className="flex justify-end"><Button type="submit" loading={act.isPending} disabled={f.lender.trim().length < 2}>{loan ? "Save loan details" : "Add loan"}</Button></div>}
      </fieldset>
    </form>
  );
}

function DisbRow({ d, caseId, s }: { d: Disb; caseId: number; s: LoanState }) {
  const act = useLoanAction(caseId); const toast = useToast();
  const [open, setOpen] = useState<null | "awaited" | "cancel" | "received">(null);
  const [f, setF] = useState({ expected_date: d.expected_date ?? "", reason: d.delay_reason ?? "", actual_date: today(), actual_amount: String(d.expected_amount), utr: "", mode: "neft" });
  const live = d.status === "requested" || d.status === "awaited";
  const label: Record<string, string> = { disbursement_requested: "Requested", disbursement_awaited: "Awaited", funds_received: "Received (receipt to confirm)", reconciled: "Reconciled", cancelled: "Cancelled" };
  return (
    <tr className="border-t border-line align-top">
      <td className="px-3 py-2">{d.request_no ?? "—"}<span className="block text-xs text-muted">{d.request_date}{d.for_stage ? ` · ${d.for_stage}` : ""}</span></td>
      <td className="px-3 py-2 text-right tabular-nums">{inr(d.expected_amount)}<span className="block text-xs text-muted">{d.expected_date ? `by ${d.expected_date}` : ""}</span></td>
      <td className="px-3 py-2"><Badge tone={d.state === "reconciled" ? "neutral" : d.delayed ? "gold" : "muted"}>{label[d.state] ?? d.state}</Badge> {d.delayed && <Badge tone="gold">Delayed</Badge>}
        {d.delay_reason && <span className="block text-xs text-muted">{d.delay_reason}</span>}
        {d.actual_amount != null && <span className="block text-xs">{inr(d.actual_amount)} on {d.actual_date} · UTR {d.utr}{d.receipt_no ? ` · ${d.receipt_no}` : ""}</span>}</td>
      <td className="px-3 py-2"><div className="flex flex-wrap justify-end gap-1">
        {live && s.can_edit && d.status === "requested" && <Button variant="ghost" onClick={() => setOpen("awaited")}>Bank acknowledged</Button>}
        {live && s.can_edit && d.status === "awaited" && <Button variant="ghost" onClick={() => setOpen("awaited")}>Update / delay</Button>}
        {live && s.can_record_funds && <Button variant="secondary" onClick={() => setOpen("received")}>Funds received</Button>}
        {live && s.can_edit && <Button variant="ghost" onClick={() => setOpen("cancel")}>Cancel</Button>}
      </div>
      {open && <Modal title={open === "received" ? "Funds received from the bank" : open === "cancel" ? "Cancel the request" : "Bank acknowledgement"} onClose={() => setOpen(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault();
          if (open === "received") act.mutate({ path: `/disbursements/${d.id}/received`, body: { actual_date: f.actual_date, actual_amount: num(f.actual_amount), utr: f.utr.trim(), mode: f.mode } },
            { onSuccess: () => { toast("Funds recorded; the loan receipt waits for a finance approver"); setOpen(null); } });
          else act.mutate({ method: "put", path: `/disbursements/${d.id}`, body: { status: open === "cancel" ? "cancelled" : "awaited", expected_date: f.expected_date || null, delay_reason: f.reason.trim() || null } },
            { onSuccess: () => { toast(open === "cancel" ? "Disbursement request cancelled" : "Disbursement updated"); setOpen(null); } }); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          {open === "received" ? <>
            <div className="grid grid-cols-2 gap-3">
              <TextInput label="Received on" type="date" max={today()} value={f.actual_date} onChange={(e) => setF({ ...f, actual_date: e.target.value })} />
              <TextInput label="Amount received (₹)" inputMode="numeric" value={f.actual_amount} onChange={(e) => setF({ ...f, actual_amount: e.target.value })} />
              <TextInput label="UTR / reference" value={f.utr} onChange={(e) => setF({ ...f, utr: e.target.value })} maxLength={60} />
              <SelectInput label="Mode" value={f.mode} onChange={(e) => setF({ ...f, mode: e.target.value })}>{["neft", "rtgs", "imps", "cheque", "dd", "other"].map((m) => <option key={m} value={m}>{m.toUpperCase()}</option>)}</SelectInput>
            </div>
            <p className="text-xs text-muted">This creates a loan receipt in Receipts. It counts, and is matched to stages, only once a finance approver confirms it.</p>
          </> : <>
            {open === "awaited" && <TextInput label="Expected date" type="date" value={f.expected_date} onChange={(e) => setF({ ...f, expected_date: e.target.value })} />}
            <TextArea label={open === "cancel" ? "Reason" : "Delay reason (if any)"} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} rows={2} maxLength={500} />
          </>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(null)}>Back</Button>
            <Button type="submit" loading={act.isPending} disabled={open === "received" ? f.utr.trim().length < 4 : open === "cancel" && f.reason.trim().length < 3}>Save</Button></div>
        </form></Modal>}</td>
    </tr>
  );
}

export function LoanTab({ caseId }: { caseId: number }) {
  const q = useLoan(caseId); const act = useLoanAction(caseId); const toast = useToast();
  const [doc, setDoc] = useState(""); const [req, setReq] = useState<null | { amount: string; no: string; stage: string; date: string }>(null);
  const [closing, setClosing] = useState(false); const [reason, setReason] = useState("");
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const s = q.data; const l = s.loan;
  if (!l) return (
    <section role="tabpanel" aria-label="Loan" className="space-y-3">
      <p className="rounded-xl bg-white p-4 text-sm text-muted ring-1 ring-line">No home loan recorded. Add one when the customer is financing through a bank.{s.history.length ? ` Closed earlier: ${s.history.map((h) => `${h.lender} (${h.close_reason})`).join("; ")}.` : ""}</p>
      {s.can_edit && <DetailsForm s={s} caseId={caseId} loan={null} />}
    </section>
  );
  return (
    <section role="tabpanel" aria-label="Loan" className="space-y-4">
      <div className="rounded-xl bg-white p-4 ring-1 ring-line">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold">{l.lender}{l.application_no ? ` · ${l.application_no}` : ""}{l.sanctioned_amount ? <span className="font-normal text-muted"> · sanctioned {inr(l.sanctioned_amount)}, received {inr(l.received_total ?? 0)}, remaining {inr(l.remaining ?? 0)}</span> : null}</p>
          {s.can_edit && <Button variant="ghost" onClick={() => setClosing(true)}>Close loan…</Button>}
        </div>
        <ol aria-label="Loan progress" className="mt-3 flex flex-wrap gap-1.5 text-xs">{s.stages.map((st) => (
          <li key={st.key} aria-current={st.current ? "step" : undefined} className={cx("rounded-full px-2.5 py-1", st.done ? "bg-forest-100 text-forest-900" : st.current ? "bg-forest-900 text-white" : "bg-paper text-muted")}>
            {st.done && <Check className="mr-0.5 inline size-3" aria-hidden />}{st.label}</li>))}</ol>
      </div>
      {s.warnings.map((w) => <Alert key={w}>{w}</Alert>)}
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      <DetailsForm key={JSON.stringify(l)} s={s} caseId={caseId} loan={l} />
      <section aria-label="Documents requested by the bank" className="rounded-xl bg-white p-4 ring-1 ring-line">
        <h3 className="mb-2 font-semibold">Documents requested by the bank</h3>
        <ul className="divide-y divide-line text-sm">{s.doc_requests.map((r) => (
          <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span>{r.name} <span className="text-xs text-muted">requested {r.requested_on}</span></span>
            {r.submitted_on ? <Badge tone="neutral">Submitted {r.submitted_on}</Badge> : s.can_edit ? <Button variant="ghost" onClick={() => act.mutate({ path: `/doc-requests/${r.id}/submitted`, body: {} }, { onSuccess: () => toast(`${r.name} marked submitted`) })}>Mark submitted</Button> : <Badge tone="gold">Pending</Badge>}</li>))}
          {s.doc_requests.length === 0 && <li className="py-2 text-muted">None yet.</li>}</ul>
        {s.can_edit && <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: "/doc-requests", body: { name: doc.trim() } }, { onSuccess: () => { toast("Document request added"); setDoc(""); } }); }}>
          <div className="flex-1"><TextInput label="Document the bank asked for" value={doc} onChange={(e) => setDoc(e.target.value)} maxLength={200} placeholder="e.g. Registered agreement copy" /></div>
          <Button type="submit" variant="secondary" className="self-end" disabled={doc.trim().length < 2}><Plus className="size-4" aria-hidden />Add</Button></form>}
      </section>
      <section aria-label="Disbursements" className="rounded-xl bg-white ring-1 ring-line">
        <div className="flex items-center justify-between px-3 pt-3"><h3 className="font-semibold">Disbursements</h3>
          {s.can_edit && l.sanctioned_amount && <Button variant="secondary" onClick={() => setReq({ amount: "", no: "", stage: "", date: "" })}><Plus className="size-4" aria-hidden />Request disbursement</Button>}</div>
        <div className="mt-2 overflow-x-auto"><table className="w-full min-w-[640px] text-sm"><caption className="sr-only">Disbursements</caption>
          <thead className="text-xs text-muted"><tr>{["Request", "Expected", "Status", ""].map((h, i) => <th key={i} scope="col" className={cx("px-3 py-1.5 font-normal", i === 1 ? "text-right" : "text-left")}>{h}</th>)}</tr></thead>
          <tbody>{s.disbursements.map((d) => <DisbRow key={d.id} d={d} caseId={caseId} s={s} />)}
            {s.disbursements.length === 0 && <tr><td colSpan={4} className="px-3 py-4 text-center text-muted">No disbursements requested yet.</td></tr>}</tbody></table></div>
      </section>
      {req && <Modal title="Request a disbursement" onClose={() => setReq(null)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: "/disbursements", body: { expected_amount: num(req.amount), request_no: req.no.trim() || null, for_stage: req.stage.trim() || null, expected_date: req.date || null } },
          { onSuccess: () => { toast("Disbursement requested"); setReq(null); } }); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Amount (₹)" inputMode="numeric" value={req.amount} onChange={(e) => setReq({ ...req, amount: e.target.value })} />
            <TextInput label="Request number" value={req.no} onChange={(e) => setReq({ ...req, no: e.target.value })} maxLength={80} />
            <TextInput label="For stage or demand" value={req.stage} onChange={(e) => setReq({ ...req, stage: e.target.value })} maxLength={120} placeholder="e.g. Plinth / DMD-00001" />
            <TextInput label="Expected by" type="date" value={req.date} onChange={(e) => setReq({ ...req, date: e.target.value })} />
          </div>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setReq(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={num(req.amount) <= 0}>Request</Button></div>
        </form></Modal>}
      {closing && <Modal title="Close the loan" onClose={() => setClosing(false)}>
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); act.mutate({ path: "/close", body: { reason: reason.trim() } }, { onSuccess: () => { toast("Loan closed"); setClosing(false); setReason(""); } }); }}>
          <TextArea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} autoFocus placeholder="e.g. Fully disbursed / customer switched banks" />
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setClosing(false)}>Back</Button><Button type="submit" variant="danger" loading={act.isPending} disabled={reason.trim().length < 3}>Close loan</Button></div>
        </form></Modal>}
    </section>
  );
}
