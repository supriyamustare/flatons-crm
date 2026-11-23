import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Plus, Trash2 } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { inr } from "../../hooks/useLedger";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const STEPS = [["requested", "Requested"], ["reviewed", "Legal and commercial review"], ["settlement_proposed", "Settlement calculated"], ["approved", "Approved"],
  ["communicated", "Letter sent"], ["closed", "Closed"]] as const;

export function CancellationTab({ caseId }: { caseId: number }) {
  const key = ["cancellation", caseId];
  const q = useQuery({ queryKey: key, queryFn: async () => (await api.get<Any>(`/post-sales/cases/${caseId}/cancellation`)).data });
  const docs = useQuery({ queryKey: ["case-documents", caseId], queryFn: async () => (await api.get<Any>(`/post-sales/cases/${caseId}/documents`)).data });
  const qc = useQueryClient(); const toast = useToast();
  const act = useMutation({ mutationFn: async ({ path, body, method = "post" }: { path: string; body?: unknown; method?: "post" | "put" }) =>
    (method === "put" ? await api.put(`/post-sales/cases/${caseId}/cancellation${path}`, body) : await api.post(`/post-sales/cases/${caseId}/cancellation${path}`, body)).data,
    onSuccess: (d) => { qc.setQueryData(key, d); void qc.invalidateQueries({ queryKey: ["case", caseId] }); } });
  const [dlg, setDlg] = useState<null | string>(null);
  const [f, setF] = useState<Record<string, Any>>({});
  const [ded, setDed] = useState<{ label: string; amount: string; basis: string }[]>([]);
  const go = (path: string, body: unknown, msg: string, method: "post" | "put" = "post") => act.mutate({ path, body, method }, { onSuccess: () => { toast(msg); setDlg(null); } });
  const open = (d: string, init: Record<string, Any> = {}) => { act.reset(); setF(init); setDlg(d); };
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const s = q.data; const c = s.cancellation; const pos = s.position;
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const Position = () => (
    <dl aria-label="Money position" className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-5">
      {([["Received (confirmed)", inr(pos.received)], ["Own funds", inr(pos.received_own)], ["Loan disbursed", inr(pos.loan_disbursed)], ["Outstanding demands", inr(pos.outstanding_demands)],
        ["Open tickets", pos.open_tickets.length ? pos.open_tickets.join(", ") : "None"]] as const).map(([l, v]) =>
        <div key={l} className="rounded-lg bg-paper p-2"><dt className="text-xs text-muted">{l}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>)}
    </dl>);
  const History = () => s.history.length > 0 ? <p className="text-xs text-muted">Earlier requests: {s.history.map((h: Any) => `${h.number} (${h.status}: ${h.reason})`).join("; ")}</p> : null;

  if (!c) return (
    <section role="tabpanel" aria-label="Cancellation" className="space-y-3 rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <p>No cancellation in progress. A cancellation goes through review, settlement and approvals; nothing is erased, and the unit is released only after approval.</p>
      <Position /><History />
      {s.can_request && <Button variant="secondary" onClick={() => open("request", { initiated_by: "customer", reason_code: "customer_request", reason: "", request_date: today(), effective_date: "", docs: [] })}>Record a cancellation request</Button>}
      {dlg === "request" && <Modal title="Cancellation request" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); go("", { initiated_by: f.initiated_by, reason_code: f.reason_code, reason: f.reason.trim(),
          request_date: f.request_date, effective_date: f.effective_date || null, supporting_document_ids: f.docs }, "Cancellation request recorded"); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          <div className="grid grid-cols-2 gap-3">
            <SelectInput label="Initiated by" value={f.initiated_by} onChange={set("initiated_by")}><option value="customer">The customer</option><option value="developer">The developer (termination)</option></SelectInput>
            <SelectInput label="Reason" value={f.reason_code} onChange={set("reason_code")}>{Object.entries(s.reasons).map(([k, v]) => <option key={k} value={k}>{String(v)}</option>)}</SelectInput>
            <TextInput label="Request date" type="date" max={today()} value={f.request_date} onChange={set("request_date")} />
            <TextInput label="Effective date (optional)" type="date" min={f.request_date} value={f.effective_date} onChange={set("effective_date")} />
          </div>
          <TextArea label="Details" value={f.reason} onChange={set("reason")} rows={3} maxLength={2000} />
          <fieldset className="text-sm"><legend className="mb-1 font-medium">Supporting documents (from the customer folder)</legend>
            {(docs.data?.documents ?? []).length === 0 ? <p className="text-xs text-muted">Upload the customer’s letter or email under Documents first, then tick it here.</p> :
              (docs.data.documents as Any[]).map((d) => <label key={d.id} className="flex min-h-8 items-center gap-2"><input type="checkbox" className="size-4 accent-forest-900" checked={f.docs.includes(d.id)}
                onChange={() => setF({ ...f, docs: f.docs.includes(d.id) ? f.docs.filter((x: number) => x !== d.id) : [...f.docs, d.id] })} />{d.title} ({d.doc_no ?? `DOC-${d.id}`})</label>)}</fieldset>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={(f.reason ?? "").trim().length < 3}>Record request</Button></div>
        </form></Modal>}
    </section>);

  const can = c.can; const st = c.settlement; const idx = STEPS.findIndex(([k]) => k === c.status);
  const appr = Object.fromEntries((c.approvals ?? []).map((a: Any) => [a.kind, a]));
  return (
    <section role="tabpanel" aria-label="Cancellation" className="space-y-4">
      {act.isError && !dlg && <Alert>{errorMessage(act.error)}</Alert>}
      <div className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{c.number}: {c.reason_label} <Badge tone={c.status === "closed" ? "neutral" : "gold"}>{c.status.replace(/_/g, " ")}</Badge></h3>
          <a href={`/cancellation-letter/${caseId}`} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center rounded-lg px-3 ring-1 ring-line hover:bg-forest-50">Cancellation letter</a></div>
        <p className="mt-1">{c.reason}</p>
        <p className="text-xs text-muted">Initiated by the {c.initiated_by} · requested {c.request_date}{c.effective_date ? ` · effective ${c.effective_date}` : ""}{c.contract_clause ? ` · ${c.contract_clause}` : ""}</p>
        <ol aria-label="Steps" className="mt-3 flex flex-wrap gap-1.5 text-xs">{STEPS.map(([k, l], i) => <li key={k} className={cx("flex items-center gap-1 rounded-full px-2.5 py-1", i <= idx ? "bg-forest-50 text-forest-900" : "bg-paper text-muted")}>{i <= idx && <Check className="size-3" aria-hidden />}{l}</li>)}</ol>
      </div>
      <Position />
      <section aria-label="Reviews" className="grid gap-2 rounded-xl bg-white p-4 text-sm ring-1 ring-line sm:grid-cols-2">
        {(["legal", "commercial"] as const).map((k) => { const r = c[`${k}_review`]; return <div key={k}><p className="font-medium">{k === "legal" ? "Legal review" : "Commercial review"}</p>
          {r ? <p className="text-xs">{r.by_name}, {formatDateTime(r.at)}: {r.note}</p> : can[`${k}_review`] ? <Button variant="ghost" onClick={() => open(k, { note: "", contract_clause: "" })}>Record {k} review</Button> : <p className="text-xs text-muted">Waiting</p>}</div>; })}
      </section>
      <section aria-label="Settlement" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Settlement</h3>
          {can.settlement && <Button variant="secondary" onClick={() => { setDed((st?.deductions ?? []).map((d: Any) => ({ ...d, amount: String(d.amount) }))); open("settlement", { note: st?.note ?? "" }); }}>{st ? "Revise settlement" : "Calculate settlement"}</Button>}</div>
        {st ? <>
          <table className="mt-2 w-full text-sm"><caption className="sr-only">Deductions</caption><tbody>
            <tr className="border-b border-line"><th scope="row" className="py-1 text-left font-normal">Received (confirmed receipts)</th><td className="text-right tabular-nums">{inr(st.snapshot.received)}</td></tr>
            {st.deductions.map((d: Any, i: number) => <tr key={i}><th scope="row" className="py-1 text-left font-normal">Less: {d.label}<span className="block text-xs text-muted">{d.basis}</span></th><td className="text-right tabular-nums">({inr(d.amount)})</td></tr>)}
            <tr className="border-t border-line font-semibold"><th scope="row" className="py-1 text-left">{st.balance_due_from_customer > 0 ? "Payable by the customer" : "Refund"}</th>
              <td className="text-right tabular-nums">{inr(st.balance_due_from_customer > 0 ? st.balance_due_from_customer : st.refund)}</td></tr></tbody></table>
          <p className="mt-1 text-xs text-muted">Prepared by {st.prepared_by}, {formatDateTime(st.at)}{st.note ? `: ${st.note}` : ""}</p>
          <ul className="mt-2 space-y-1 text-xs">{(["finance", "management"] as const).map((k) => <li key={k}>{k === "finance" ? "Finance check" : "Management approval"}: {appr[k] ? <b>{appr[k].by_name}, {formatDateTime(appr[k].at)}</b> : "waiting"}</li>)}</ul>
          <div className="mt-2 flex flex-wrap gap-2">
            {can.approve_finance && <Button onClick={() => go("/approve/finance", {}, "Settlement checked")}>Approve (finance check)</Button>}
            {can.approve_management && <Button onClick={() => go("/approve/management", {}, "Cancellation approved")}>Approve (management)</Button>}
            {can.reject && <Button variant="ghost" onClick={() => open("reject", { reason: "" })}>Reject</Button>}
          </div></> : <p className="mt-1 text-xs text-muted">{c.status === "requested" ? "Calculated by finance after the legal and commercial reviews." : "Not yet calculated."}</p>}
      </section>
      {["approved", "communicated", "closed"].includes(c.status) && <section aria-label="After approval" className="space-y-2 rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <p>Letter to the customer: {c.communication ? <b>sent {c.communication.on} by {c.communication.via}</b> : can.communicate ? <Button variant="ghost" onClick={() => open("communicate", { on: today(), via: "email" })}>Record letter sent</Button> : "not yet"}</p>
        {st.refund > 0 && <>
          <p>Refund account: {c.refund_bank ? <>{c.refund_bank.payee}, {c.refund_bank.bank} {c.refund_bank.account_masked} ({c.refund_bank.ifsc}), checked by {c.refund_bank.method.replace("_", " ")}
            {c.refund_bank.verified_by_name ? <b> · verified by {c.refund_bank.verified_by_name}</b> : " · waiting for a second person to verify"}</> : "not yet recorded"}
            {can.bank && <> <Button variant="ghost" onClick={() => open("bank", { payee: "", bank: "", account_number: "", ifsc: "", method: "cancelled_cheque" })}>Record account</Button></>}
            {can.verify_bank && <> <Button variant="ghost" onClick={() => go("/refund-bank/verify", undefined, "Refund account verified")}>Verify account</Button></>}</p>
          <p>Refund payment: {c.refund_payment ? <>{inr(c.refund_payment.amount)} on {c.refund_payment.paid_on}, UTR {c.refund_payment.utr}{c.refund_payment.reconciled_by_name ? <b> · reconciled by {c.refund_payment.reconciled_by_name}</b> : " · waiting for reconciliation"}</> : "not yet paid"}
            {can.pay && <> <Button variant="ghost" onClick={() => open("pay", { paid_on: today(), amount: String(st.refund), utr: "" })}>Record refund paid</Button></>}
            {can.reconcile && <> <Button variant="ghost" onClick={() => go("/refund-payment/reconcile", undefined, "Refund reconciled")}>Reconcile</Button></>}</p></>}
        <p>Unit release: {c.release ? <b>released by {c.release.by_name}, {formatDateTime(c.release.at)}</b> : can.release ? <Button variant="secondary" onClick={() => open("release")}>Approve unit release…</Button> : "waiting"}</p>
        <p className="text-xs text-muted">The final statement of account stays available on the Ledger tab; nothing is erased.</p>
        {can.close && <Button onClick={() => go("/close", undefined, "Cancellation closed; the account is archived")}>Close and archive</Button>}
        {c.closed_at && <p><Badge tone="neutral">Closed {formatDateTime(c.closed_at)}</Badge></p>}
      </section>}
      {can.withdraw && <Button variant="ghost" onClick={() => open("withdraw", { reason: "" })}>Customer withdrew the request…</Button>}
      <History />
      {dlg && <Modal title={{ legal: "Legal review", commercial: "Commercial review", settlement: "Settlement", reject: "Reject the settlement", withdraw: "Withdraw the request", communicate: "Cancellation letter sent",
        bank: "Refund account", pay: "Refund paid", release: "Release the unit" }[dlg] ?? ""} onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
          if (dlg === "legal" || dlg === "commercial") go(`/review/${dlg}`, { note: f.note.trim(), contract_clause: f.contract_clause?.trim() || null }, "Review recorded");
          if (dlg === "settlement") go("/settlement", { deductions: ded.filter((d) => d.label.trim()).map((d) => ({ label: d.label.trim(), amount: Number(d.amount), basis: d.basis.trim() })), note: f.note.trim() || null }, "Settlement saved", "put");
          if (dlg === "reject") go("/reject", { reason: f.reason.trim() }, "Settlement rejected");
          if (dlg === "withdraw") go("/withdraw", { reason: f.reason.trim() }, "Request withdrawn");
          if (dlg === "communicate") go("/communicated", { on: f.on, via: f.via }, "Letter recorded as sent");
          if (dlg === "bank") go("/refund-bank", { ...f, ifsc: String(f.ifsc).toUpperCase().trim(), account_number: String(f.account_number).trim() }, "Refund account recorded", "put");
          if (dlg === "pay") go("/refund-payment", { paid_on: f.paid_on, amount: Number(f.amount), utr: f.utr.trim() }, "Refund payment recorded");
          if (dlg === "release") go("/release", undefined, "Unit released; the booking is cancelled"); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          {(dlg === "legal" || dlg === "commercial") && <>{dlg === "legal" && <TextInput label="Applicable contract clause" value={f.contract_clause} onChange={set("contract_clause")} maxLength={200} />}
            <TextArea label="Review" value={f.note} onChange={set("note")} rows={3} maxLength={2000} /></>}
          {dlg === "settlement" && <>
            <p className="text-xs text-muted">Received (confirmed): {inr(pos.received)}. Each deduction needs its basis (clause or calculation).</p>
            {ded.map((d, i) => <div key={i} className="grid grid-cols-[1fr_8rem_auto] items-end gap-2">
              <TextInput label={`Deduction ${i + 1}`} value={d.label} onChange={(e) => setDed(ded.map((x, j) => j === i ? { ...x, label: e.target.value } : x))} />
              <TextInput label="Amount (₹)" type="number" min={1} value={d.amount} onChange={(e) => setDed(ded.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))} />
              <Button type="button" variant="ghost" aria-label={`Remove deduction ${i + 1}`} onClick={() => setDed(ded.filter((_, j) => j !== i))}><Trash2 className="size-4" aria-hidden /></Button>
              <div className="col-span-3"><TextInput label={`Basis for deduction ${i + 1}`} value={d.basis} onChange={(e) => setDed(ded.map((x, j) => j === i ? { ...x, basis: e.target.value } : x))} /></div></div>)}
            <Button type="button" variant="ghost" onClick={() => setDed([...ded, { label: "", amount: "", basis: "" }])}><Plus className="size-4" aria-hidden />Add deduction</Button>
            <p className="font-medium">Refund: {inr(Math.max(0, pos.received - ded.reduce((t, d) => t + (Number(d.amount) || 0), 0)))}</p>
            <TextArea label="Note (optional)" value={f.note} onChange={set("note")} rows={2} maxLength={2000} /></>}
          {(dlg === "reject" || dlg === "withdraw") && <TextArea label="Reason" value={f.reason} onChange={set("reason")} rows={2} maxLength={1000} />}
          {dlg === "communicate" && <div className="grid grid-cols-2 gap-3"><TextInput label="Sent on" type="date" max={today()} value={f.on} onChange={set("on")} />
            <SelectInput label="Sent by" value={f.via} onChange={set("via")}>{["email", "courier", "hand", "whatsapp"].map((x) => <option key={x} value={x}>{x}</option>)}</SelectInput></div>}
          {dlg === "bank" && <div className="grid grid-cols-2 gap-3">
            <TextInput label="Payee name" value={f.payee} onChange={set("payee")} maxLength={150} /><TextInput label="Bank" value={f.bank} onChange={set("bank")} maxLength={150} />
            <TextInput label="Account number" inputMode="numeric" value={f.account_number} onChange={set("account_number")} maxLength={18} /><TextInput label="IFSC" value={f.ifsc} onChange={set("ifsc")} maxLength={11} />
            <SelectInput label="Verified using" value={f.method} onChange={set("method")}><option value="cancelled_cheque">Cancelled cheque</option><option value="bank_letter">Bank letter</option><option value="penny_drop">Penny drop</option><option value="passbook">Passbook</option></SelectInput>
            <p className="col-span-2 text-xs text-muted">Stored encrypted; a finance approver verifies it before any payment.</p></div>}
          {dlg === "pay" && <div className="grid grid-cols-2 gap-3"><TextInput label="Paid on" type="date" max={today()} value={f.paid_on} onChange={set("paid_on")} />
            <TextInput label="Amount (₹)" type="number" value={f.amount} onChange={set("amount")} hint={`Must be the approved ${inr(st.refund)}`} />
            <TextInput label="UTR / reference" value={f.utr} onChange={set("utr")} maxLength={60} /></div>}
          {dlg === "release" && <p className="text-sm">This cancels the booking and makes the flat available for sale again. Receipts, demands, the agreement and all documents stay on record.</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending}>Save</Button></div>
        </form></Modal>}
    </section>
  );
}
