import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Badge, Button, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { inr } from "../../hooks/useLedger";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
/** OCR: own contribution required (a fixed amount) vs the home loan, stage by stage. */
export function OcrTab({ caseId }: { caseId: number }) {
  const key = ["ocr", caseId];
  const q = useQuery({ queryKey: key, queryFn: async () => (await api.get<any>(`/post-sales/cases/${caseId}/ocr`)).data });
  const qc = useQueryClient(); const toast = useToast();
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState({ own_amount: "", note: "", reason: "" });
  const save = useMutation({ mutationFn: async () => (await api.put(`/post-sales/cases/${caseId}/ocr`, { own_amount: Number(f.own_amount), note: f.note.trim() || null, reason: f.reason.trim() || null })).data,
    onSuccess: (d) => { qc.setQueryData(key, d); setEdit(false); toast("Own contribution saved; a finance approver approves it"); } });
  const approve = useMutation({ mutationFn: async () => (await api.post(`/post-sales/cases/${caseId}/ocr/approve`)).data, onSuccess: (d) => { qc.setQueryData(key, d); toast("Own contribution approved"); } });
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const s = q.data; const p = s.plan; const approved = p?.status === "approved";
  const open = () => { setF({ own_amount: p ? String(p.own_amount) : "", note: p?.note ?? "", reason: "" }); save.reset(); setEdit(true); };
  return (
    <section role="tabpanel" aria-label="OCR" className="space-y-4">
      <div className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="font-semibold">Own contribution required (OCR) {p && <Badge tone={approved ? "neutral" : "gold"}>{approved ? "Approved" : "Waiting for approval"}</Badge>}</h3>
          <span className="flex gap-2">{s.can_edit && s.total_payable != null && <Button variant="secondary" onClick={open}>{p ? "Change" : "Set own contribution"}</Button>}
            {s.can_approve && <Button loading={approve.isPending} onClick={() => approve.mutate()}>Approve</Button>}</span>
        </div>
        {p ? <p className="mt-1 text-xs text-muted">Entered by {p.entered_by}{p.approved_by ? `, approved by ${p.approved_by} ${formatDateTime(p.approved_at)}` : ""}{p.note ? ` · ${p.note}` : ""}</p>
          : <p className="mt-1 text-muted">The customer pays a fixed amount from their own funds; the rest of the agreement value comes from the home loan.</p>}
        {approve.isError && <div className="mt-2"><Alert>{errorMessage(approve.error)}</Alert></div>}
      </div>
      {s.warnings.map((w: string) => <Alert key={w}>{w}</Alert>)}
      {p && s.loan_needed != null && <dl aria-label="Funding" className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {([["Own contribution (plan)", p.own_amount], ["Loan needed", s.loan_needed], [`Bank approved${s.lender ? ` (${s.lender})` : ""}`, s.sanctioned], ["Shortfall to pay from own funds", s.shortfall],
          ["Own contribution required", s.own_required], ["Own funds received", s.received_own], ["Received, awaiting confirmation", s.pending_own], ["Own contribution remaining", s.remaining_own],
          ["Own share due now", s.own_due_now], ["Own share overdue", s.own_overdue], ["Stamp duty, registration and other charges (own, not in the loan)", s.charges_own]] as const)
          .map(([l, v]) => <div key={l} className={cx("rounded-lg p-3 ring-1 ring-line", l.startsWith("Shortfall") && (v as number) > 0 || l.endsWith("overdue") && (v as number) > 0 ? "bg-danger-soft" : "bg-white")}>
            <dt className="text-xs text-muted">{l}</dt><dd className="font-semibold tabular-nums">{v == null ? "—" : inr(v as number)}</dd></div>)}
      </dl>}
      {s.stages.length > 0 && <section aria-label="Own share and loan share by stage" className="overflow-x-auto rounded-xl bg-white p-4 ring-1 ring-line">
        <h3 className="mb-2 font-semibold">Own share and loan share by stage</h3>
        <p className="mb-2 text-xs text-muted">The customer’s own share is paid first, from the earliest stages; the loan pays the rest.</p>
        <table className="w-full min-w-[620px] text-sm"><caption className="sr-only">Own share and loan share by stage</caption>
          <thead className="text-xs text-muted"><tr>{["Stage", "Amount", "Own share", "Loan share", "Due", "Own share outstanding"].map((h) => <th key={h} scope="col" className="py-1 text-left font-normal">{h}</th>)}</tr></thead>
          <tbody>{s.stages.map((x: any) => <tr key={x.stage} className={cx("border-t border-line", x.overdue && "bg-danger-soft")}>
            <th scope="row" className="py-1.5 text-left font-normal">{x.stage}</th><td className="tabular-nums">{inr(x.amount)}</td><td className="tabular-nums">{x.own_part ? inr(x.own_part) : "—"}</td>
            <td className="tabular-nums">{x.loan_part ? inr(x.loan_part) : "—"}</td><td>{x.demanded ? (x.due_date ?? "due") : "not yet"}</td>
            <td className="tabular-nums">{x.own_outstanding ? <>{inr(x.own_outstanding)}{x.overdue && <span className="text-danger"> overdue</span>}</> : "—"}</td></tr>)}</tbody></table>
      </section>}
      {s.receipts.length > 0 && <section aria-label="Own-fund receipts" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h3 className="mb-2 font-semibold">Own-fund receipts</h3>
        <ul className="divide-y divide-line">{s.receipts.map((r: any) => <li key={r.receipt_no} className="flex justify-between py-1.5"><span>{r.receipt_no} · {r.date} · {r.mode.toUpperCase()}</span>
          <span className="tabular-nums">{inr(r.amount)} <Badge tone={r.status === "confirmed" ? "neutral" : "gold"}>{r.status === "confirmed" ? "Confirmed" : "Awaiting confirmation"}</Badge></span></li>)}</ul></section>}
      {p?.history?.length > 0 && <details className="rounded-xl bg-white p-4 text-xs ring-1 ring-line"><summary className="cursor-pointer font-medium">Earlier amounts ({p.history.length})</summary>
        <ul className="mt-2 space-y-1">{p.history.map((h: any, i: number) => <li key={i}>{inr(h.own_amount)}, changed by {h.changed_by} {formatDateTime(h.changed_at)}: {h.reason}</li>)}</ul></details>}
      {edit && <form aria-label="Own contribution" className="space-y-3 rounded-xl bg-white p-4 ring-1 ring-line" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <TextInput label="Own contribution (₹, fixed amount)" type="number" min={1} value={f.own_amount} onChange={(e) => setF({ ...f, own_amount: e.target.value })} hint={f.own_amount ? inr(Number(f.own_amount)) : undefined} />
        <TextInput label="Note (optional)" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} maxLength={500} />
        {approved && <TextArea label="Reason for changing the approved amount" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} rows={2} maxLength={500} />}
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setEdit(false)}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!(Number(f.own_amount) > 0) || (approved && f.reason.trim().length < 3)}>Save</Button></div>
      </form>}
    </section>
  );
}
