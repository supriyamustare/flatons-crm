import { useState } from "react";
import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useCurrentUser } from "../../hooks/useAuth";
import { AGREEMENT, OTHER, STATUS_LABELS, STATUTORY, TRIGGER_LABELS, inr, useLedger, useLedgerAction } from "../../hooks/useLedger";
import type { Charge, ChargeHead, Item, Ledger, Trigger } from "../../hooks/useLedger";
import { errorMessage, formatDateTime } from "../../lib/api";

const num = (v: string) => Math.round(Number(v.replace(/[,₹\s]/g, "")) || 0);

function Balances({ l }: { l: Ledger }) {
  const b = l.balances!; const t = l.totals!;
  const cards: [string, number, string?][] = [
    ["Total outstanding", b.total_outstanding], ["Currently demanded", b.currently_demanded], ["Overdue", b.overdue, b.overdue ? "danger" : undefined],
    ["Own contribution still required", b.own_contribution_required], ["Loan not yet disbursed", b.loan_not_disbursed],
    ["Under dispute", b.under_dispute], ["Other charges (outside the plan)", b.other_charges],
  ];
  return (
    <section aria-label="Balances" className="rounded-xl bg-white p-4 ring-1 ring-line">
      <p className="mb-3 text-sm text-muted">Total payable <b className="text-ink">{inr(t.total_payable)}</b> · received <b className="text-ink">{inr(b.received)}</b>
        <span className="block text-xs">Only confirmed receipts count{b.pending_confirmation ? `; ${inr(b.pending_confirmation)} is waiting for confirmation` : ""}{b.unapplied ? `; ${inr(b.unapplied)} is an advance not yet matched` : ""}.</span></p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {cards.map(([label, n, tone]) => (
          <div key={label} className={cx("rounded-lg p-2.5", tone === "danger" ? "bg-danger-soft" : "bg-paper")}>
            <dt className="text-xs text-muted">{label}</dt><dd className={cx("font-semibold tabular-nums", tone === "danger" && "text-danger")}>{inr(n)}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function ChargesEditor({ l, onClose, caseId }: { l: Ledger; onClose: () => void; caseId: number }) {
  const act = useLedgerAction(caseId); const toast = useToast();
  const [rows, setRows] = useState<Charge[]>(l.charges.map(({ head, label, amount }) => ({ head, label, amount })));
  const heads = Object.keys(l.head_labels) as ChargeHead[];
  return (
    <Modal title="Edit charges" onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ method: "put", path: "/charges", body: rows }, { onSuccess: () => { toast("Charges saved"); onClose(); } }); }}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <p className="text-xs text-muted">Discounts are entered as negative amounts. Remember GST follows the agreement value ({l.gst_pct}%).</p>
        {rows.map((r, i) => (
          <div key={i} className="grid grid-cols-[1fr_1fr_8rem_auto] items-end gap-2">
            <SelectInput label={`Charge ${i + 1} type`} value={r.head} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, head: e.target.value as ChargeHead, label: l.head_labels[e.target.value] } : x)))}>
              {heads.map((h) => <option key={h} value={h}>{l.head_labels[h]}</option>)}
            </SelectInput>
            <TextInput label={`Charge ${i + 1} label`} value={r.label} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} maxLength={120} />
            <TextInput label={`Charge ${i + 1} amount (₹)`} inputMode="numeric" value={String(r.amount)} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, amount: e.target.value === "-" ? 0 : num(e.target.value) * (e.target.value.trim().startsWith("-") ? -1 : 1) } : x)))} />
            <button type="button" aria-label={`Remove ${r.label}`} onClick={() => setRows(rows.filter((_, j) => j !== i))} className="grid size-10 place-items-center rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>
          </div>
        ))}
        <Button type="button" variant="ghost" onClick={() => setRows([...rows, { head: "parking", label: l.head_labels.parking, amount: 0 }])}><Plus className="size-4" aria-hidden />Add charge</Button>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending}>Save charges</Button></div>
      </form>
    </Modal>
  );
}

function ScheduleEditor({ l, onClose, caseId }: { l: Ledger; onClose: () => void; caseId: number }) {
  const act = useLedgerAction(caseId); const toast = useToast();
  const [rows, setRows] = useState<Item[]>(l.schedule.map(({ name, amount, gst, trigger_type, due_date, milestone }) => ({ name, amount, gst, trigger_type, due_date, milestone })));
  const set = (i: number, patch: Partial<Item>) => setRows(rows.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const total = rows.reduce((a, r) => a + r.amount, 0); const gst = rows.reduce((a, r) => a + r.gst, 0);
  return (
    <Modal title="Edit payment schedule" onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ method: "put", path: "/schedule", body: rows }, { onSuccess: () => { toast("Payment schedule saved"); onClose(); } }); }}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <p className={cx("text-sm", total === l.totals!.agreement_value && gst === l.totals!.gst ? "text-forest-800" : "text-danger")}>
          Stages total {inr(total)} of the agreement value {inr(l.totals!.agreement_value)}; GST {inr(gst)} of {inr(l.totals!.gst)}.</p>
        <div className="max-h-[55vh] space-y-2 overflow-y-auto pr-1">
          {rows.map((r, i) => (
            <fieldset key={i} className="grid grid-cols-2 gap-2 rounded-lg bg-paper p-2 sm:grid-cols-[1.4fr_1fr_1fr_1fr_1.2fr_auto]">
              <legend className="sr-only">Stage {i + 1}</legend>
              <TextInput label={`Stage ${i + 1} name`} value={r.name} onChange={(e) => set(i, { name: e.target.value })} maxLength={120} />
              <TextInput label={`Stage ${i + 1} amount (₹)`} inputMode="numeric" value={String(r.amount)} onChange={(e) => set(i, { amount: num(e.target.value) })} />
              <TextInput label={`Stage ${i + 1} GST (₹)`} inputMode="numeric" value={String(r.gst)} onChange={(e) => set(i, { gst: num(e.target.value) })} />
              <SelectInput label={`Stage ${i + 1} due`} value={r.trigger_type} onChange={(e) => set(i, { trigger_type: e.target.value as Trigger })}>
                {(Object.keys(TRIGGER_LABELS) as Trigger[]).map((t) => <option key={t} value={t}>{TRIGGER_LABELS[t]}</option>)}
              </SelectInput>
              {r.trigger_type === "on_date" ? <TextInput label={`Stage ${i + 1} due date`} type="date" value={r.due_date ?? ""} onChange={(e) => set(i, { due_date: e.target.value || null })} />
                : r.trigger_type === "on_milestone" ? <TextInput label={`Stage ${i + 1} milestone`} value={r.milestone ?? ""} onChange={(e) => set(i, { milestone: e.target.value || null })} maxLength={120} />
                : <p className="self-end pb-2 text-xs text-muted">Due on the booking date</p>}
              <button type="button" aria-label={`Remove stage ${r.name}`} onClick={() => setRows(rows.filter((_, j) => j !== i))} className="grid size-10 place-items-center self-end rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>
            </fieldset>
          ))}
        </div>
        <Button type="button" variant="ghost" onClick={() => setRows([...rows, { name: "New stage", amount: 0, gst: 0, trigger_type: "on_milestone", due_date: null, milestone: "" }])}><Plus className="size-4" aria-hidden />Add stage</Button>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending}>Save schedule</Button></div>
      </form>
    </Modal>
  );
}

function FundingEditor({ l, onClose, caseId }: { l: Ledger; onClose: () => void; caseId: number }) {
  const act = useLedgerAction(caseId); const toast = useToast();
  const [loan, setLoan] = useState(String(l.loan_sanctioned || "")); const [lender, setLender] = useState(l.lender ?? ""); const [ref, setRef] = useState(l.loan_reference ?? "");
  return (
    <Modal title="Funding" onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ method: "put", path: "/funding", body: { loan_sanctioned: num(loan), lender: lender.trim() || null, loan_reference: ref.trim() || null } }, { onSuccess: () => { toast("Funding saved"); onClose(); } }); }}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <TextInput label="Loan sanctioned (₹)" inputMode="numeric" value={loan} onChange={(e) => setLoan(e.target.value)} hint="Leave empty if the customer pays from own funds" />
        <TextInput label="Lender" value={lender} onChange={(e) => setLender(e.target.value)} maxLength={150} placeholder="e.g. HDFC Bank" />
        <TextInput label="Loan reference" value={ref} onChange={(e) => setRef(e.target.value)} maxLength={80} />
        <p className="text-sm text-muted">Own contribution: {inr(Math.max(0, l.totals!.total_payable - num(loan)))}</p>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending}>Save funding</Button></div>
      </form>
    </Modal>
  );
}

function ReasonModal({ title, cta, caseId, path, onClose, done }: { title: string; cta: string; caseId: number; path: string; onClose: () => void; done: string }) {
  const act = useLedgerAction(caseId); const toast = useToast(); const [r, setR] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ path, body: { reason: r.trim() } }, { onSuccess: () => { toast(done); onClose(); } }); }}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <TextArea label="Reason" value={r} onChange={(e) => setR(e.target.value)} rows={3} maxLength={500} autoFocus />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={r.trim().length < 3}>{cta}</Button></div>
      </form>
    </Modal>
  );
}

export function LedgerTab({ caseId }: { caseId: number }) {
  const me = useCurrentUser();
  const q = useLedger(caseId, true);
  const act = useLedgerAction(caseId);
  const toast = useToast();
  const [open, setOpen] = useState<null | "charges" | "schedule" | "funding" | "return" | "reopen">(null);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const l = q.data;
  const isChecker = me.role === "admin" || me.role === "finance_approver";
  if (!l.exists) return (
    <section role="tabpanel" aria-label="Ledger" className="rounded-xl bg-white p-5 ring-1 ring-line">
      <p className="text-sm text-muted">No ledger yet. It’s generated from the unit’s cost sheet and the agreed price, then checked and approved by finance.</p>
      {act.isError && <div className="mt-3"><Alert>{errorMessage(act.error)}</Alert></div>}
      {l.can_edit && <Button className="mt-3" loading={act.isPending} onClick={() => act.mutate({ path: "/generate" }, { onSuccess: () => toast("Ledger generated from the cost sheet") })}>Generate ledger</Button>}
    </section>
  );
  const t = l.totals!;
  const group = (label: string, heads: ChargeHead[], total: number) => {
    const rows = l.charges.filter((c) => heads.includes(c.head));
    if (!rows.length) return null;
    return (<tbody key={label} aria-label={label}>
      <tr><th colSpan={2} scope="rowgroup" className="bg-paper px-3 py-1.5 text-left text-xs font-semibold text-muted">{label}</th></tr>
      {rows.map((c, i) => <tr key={i} className="border-t border-line"><td className="px-3 py-1.5">{c.label}</td><td className="px-3 py-1.5 text-right tabular-nums">{inr(c.amount)}</td></tr>)}
      <tr className="border-t border-line font-medium"><td className="px-3 py-1.5">{label.startsWith("GST") ? "Total GST" : `Total ${label.toLowerCase()}`}</td><td className="px-3 py-1.5 text-right tabular-nums">{inr(total)}</td></tr>
    </tbody>);
  };
  return (
    <section role="tabpanel" aria-label="Ledger" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white p-4 ring-1 ring-line">
        <div className="text-sm">
          <Badge tone={l.status === "approved" ? "neutral" : "gold"}>{STATUS_LABELS[l.status!]}</Badge> <span className="text-muted">Version {l.version}</span>
          {l.submitted_by && <span className="block text-xs text-muted">Submitted by {l.submitted_by.full_name}{l.submitted_at ? `, ${formatDateTime(l.submitted_at)}` : ""}</span>}
          {l.approved_by && <span className="block text-xs text-muted">Approved by {l.approved_by.full_name}{l.approved_at ? `, ${formatDateTime(l.approved_at)}` : ""}</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          {l.can_edit && <Button loading={act.isPending} disabled={l.problems.length > 0} onClick={() => act.mutate({ path: "/submit" }, { onSuccess: () => toast("Ledger sent for approval") })}>Submit for approval</Button>}
          {l.can_approve && <>
            <Button loading={act.isPending} onClick={() => act.mutate({ path: "/approve" }, { onSuccess: () => toast("Ledger approved") })}>Approve ledger</Button>
            <Button variant="secondary" onClick={() => setOpen("return")}>Return to finance</Button></>}
          {isChecker && l.status === "approved" && <Button variant="secondary" onClick={() => setOpen("reopen")}>Reopen for changes</Button>}
          {l.status === "pending_approval" && !l.can_approve && isChecker && <span className="self-center text-xs text-muted">Someone other than the submitter must approve</span>}
        </div>
      </div>
      {l.note && <Alert>{l.status === "draft" ? "Note: " : ""}{l.note}</Alert>}
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {l.problems.length > 0 && (
        <div role="alert" className="rounded-xl border border-gold-300 bg-gold-100/60 p-3 text-sm">
          <p className="font-semibold">To fix before approval:</p><ul className="mt-1 list-disc pl-5">{l.problems.map((p) => <li key={p}>{p}</li>)}</ul>
        </div>
      )}
      <Balances l={l} />
      <div className="grid gap-4 lg:grid-cols-[2fr_3fr]">
        <div className="space-y-3">
          <section aria-label="Charges" className="rounded-xl bg-white ring-1 ring-line">
            <div className="flex items-center justify-between px-3 pt-3"><h3 className="font-semibold">Charges</h3>{l.can_edit && <Button variant="ghost" onClick={() => setOpen("charges")}>Edit</Button>}</div>
            <table className="mt-2 w-full text-sm">
              <caption className="sr-only">Charges</caption>
              {group("Agreement value", AGREEMENT, t.agreement_value)}
              {group(`GST (${l.gst_pct}%)`, ["gst"], t.gst)}
              {group("Statutory", STATUTORY, t.statutory)}
              {group("Other charges", OTHER, t.other)}
              <tfoot><tr className="border-t-2 border-ink font-semibold"><td className="px-3 py-2">Total payable</td><td className="px-3 py-2 text-right tabular-nums">{inr(t.total_payable)}</td></tr></tfoot>
            </table>
          </section>
          <section aria-label="Funding" className="rounded-xl bg-white p-3 text-sm ring-1 ring-line">
            <div className="flex items-center justify-between"><h3 className="font-semibold">Funding</h3>{l.can_edit && <Button variant="ghost" onClick={() => setOpen("funding")}>Edit</Button>}</div>
            <p className="mt-1">Loan: {l.loan_sanctioned ? <>{inr(l.loan_sanctioned)} from {l.lender ?? "—"}{l.loan_reference ? ` (${l.loan_reference})` : ""}</> : "none (own funds)"}</p>
            <p>Own contribution: {inr(Math.max(0, t.total_payable - l.loan_sanctioned))}</p>
          </section>
        </div>
        <section aria-label="Payment schedule" className="rounded-xl bg-white ring-1 ring-line">
          <div className="flex items-center justify-between px-3 pt-3"><h3 className="font-semibold">Payment schedule</h3>{l.can_edit && <Button variant="ghost" onClick={() => setOpen("schedule")}>Edit</Button>}</div>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <caption className="sr-only">Payment schedule</caption>
              <thead className="text-xs text-muted"><tr>{["Stage", "Due", "Amount", "GST", "Total"].map((h, i) => <th key={h} scope="col" className={cx("px-3 py-1.5 font-normal", i >= 2 ? "text-right" : "text-left")}>{h}</th>)}</tr></thead>
              <tbody>{l.schedule.map((i) => (
                <tr key={i.seq} className="border-t border-line">
                  <td className="px-3 py-1.5">{i.name}{i.is_due && <> <Badge tone="gold">Due</Badge></>}</td>
                  <td className="px-3 py-1.5 text-xs text-muted">{i.trigger_type === "on_milestone" ? `Milestone: ${i.milestone}` : i.due_date}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{inr(i.amount)}</td><td className="px-3 py-1.5 text-right tabular-nums">{inr(i.gst)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{inr(i.amount + i.gst)}</td>
                </tr>))}</tbody>
              <tfoot><tr className="border-t-2 border-ink font-semibold"><td className="px-3 py-2" colSpan={2}>Total</td><td className="px-3 py-2 text-right tabular-nums">{inr(t.schedule_amount)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{inr(t.schedule_gst)}</td><td className="px-3 py-2 text-right tabular-nums">{inr(t.schedule_amount + t.schedule_gst)}</td></tr></tfoot>
            </table>
          </div>
        </section>
      </div>
      {open === "charges" && <ChargesEditor l={l} caseId={caseId} onClose={() => setOpen(null)} />}
      {open === "schedule" && <ScheduleEditor l={l} caseId={caseId} onClose={() => setOpen(null)} />}
      {open === "funding" && <FundingEditor l={l} caseId={caseId} onClose={() => setOpen(null)} />}
      {open === "return" && <ReasonModal title="Return to finance" cta="Return" caseId={caseId} path="/return" done="Ledger returned to finance" onClose={() => setOpen(null)} />}
      {open === "reopen" && <ReasonModal title="Reopen for changes" cta="Reopen" caseId={caseId} path="/reopen" done="Ledger reopened as a new version" onClose={() => setOpen(null)} />}
    </section>
  );
}
