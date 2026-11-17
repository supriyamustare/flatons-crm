import { useState } from "react";
import type { FormEvent } from "react";
import { Plus, Printer, Trash2 } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { inr } from "../../hooks/useLedger";
import { MODE_LABELS, statusLabel, useReceiptAction, useReceipts } from "../../hooks/useReceipts";
import type { Match, Receipt, ReceiptMode, Receipts } from "../../hooks/useReceipts";
import { errorMessage, formatDateTime } from "../../lib/api";

const num = (v: string) => Math.round(Number(v.replace(/[,₹\s]/g, "")) || 0);
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
type Row = { target: string; amount: string };

function targets(d: Receipts) {
  return [...d.stages.filter((s) => s.outstanding > 0).map((s) => ({ value: `s:${s.seq}`, label: `${s.name} (unpaid ${inr(s.outstanding)})` })),
    ...d.other_charges.filter((h) => h.outstanding > 0).map((h) => ({ value: `h:${h.head}`, label: `${h.label} (unpaid ${inr(h.outstanding)})` }))];
}
const toMatches = (rows: Row[]): Match[] => rows.filter((r) => r.target && num(r.amount) > 0).map((r) => r.target.startsWith("s:")
  ? { stage_seq: Number(r.target.slice(2)), charge_head: null, amount: num(r.amount) } : { stage_seq: null, charge_head: r.target.slice(2) as Match["charge_head"], amount: num(r.amount) });

function MatchRows({ d, rows, setRows }: { d: Receipts; rows: Row[]; setRows: (r: Row[]) => void }) {
  const opts = targets(d);
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_9rem_auto] items-end gap-2">
          <SelectInput label={`Match ${i + 1} to`} value={r.target} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, target: e.target.value } : x)))}>
            <option value="">Choose a stage or charge</option>
            {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </SelectInput>
          <TextInput label={`Match ${i + 1} amount (₹)`} inputMode="numeric" value={r.amount} onChange={(e) => setRows(rows.map((x, j) => (j === i ? { ...x, amount: e.target.value } : x)))} />
          <button type="button" aria-label={`Remove match ${i + 1}`} onClick={() => setRows(rows.filter((_, j) => j !== i))} className="grid size-10 place-items-center rounded-lg text-muted hover:bg-danger-soft hover:text-danger"><Trash2 className="size-4" /></button>
        </div>
      ))}
      <Button type="button" variant="ghost" onClick={() => setRows([...rows, { target: "", amount: "" }])}><Plus className="size-4" aria-hidden />Add a match</Button>
    </div>
  );
}

function RecordReceipt({ d, caseId, onClose }: { d: Receipts; caseId: number; onClose: () => void }) {
  const act = useReceiptAction(caseId); const toast = useToast();
  const [f, setF] = useState({ amount: "", received_on: today(), mode: "" as ReceiptMode | "", source: "own", reference: "", payer_name: "", bank_name: "", notes: "" });
  const [manual, setManual] = useState(false);
  const [rows, setRows] = useState<Row[]>([{ target: "", amount: "" }]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const amount = num(f.amount);
  const cashTooMuch = f.mode === "cash" && amount >= 200_000;
  const looksCash = f.mode !== "" && f.mode !== "cash" && ["CASH", "BYCASH", "INCASH"].includes(f.reference.toUpperCase().replace(/[^A-Z]/g, ""));
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = (x: string) => x.trim() || null;
    act.mutate({ body: { amount, received_on: f.received_on, mode: f.mode, source: f.source, reference: v(f.reference), payer_name: v(f.payer_name),
      bank_name: v(f.bank_name), notes: v(f.notes), ...(manual ? { matches: toMatches(rows) } : {}) } },
      { onSuccess: () => { toast(`Receipt of ${inr(amount)} recorded; waiting for confirmation`); onClose(); } });
  };
  return (
    <Modal title="Record receipt" onClose={onClose}>
      <form className="space-y-3" onSubmit={submit}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Amount (₹)" inputMode="numeric" value={f.amount} onChange={set("amount")} autoFocus />
          <TextInput label="Received on" type="date" value={f.received_on} max={today()} onChange={set("received_on")} />
          <SelectInput label="Mode" value={f.mode} onChange={set("mode")}>
            <option value="" disabled>Choose how it was paid</option>
            {(Object.keys(MODE_LABELS) as ReceiptMode[]).map((m) => <option key={m} value={m}>{MODE_LABELS[m]}</option>)}
          </SelectInput>
          <SelectInput label="Paid from" value={f.source} onChange={set("source")}>
            <option value="own">Customer’s own funds</option><option value="loan">Loan disbursement</option>
          </SelectInput>
          <TextInput label={f.mode === "cheque" || f.mode === "dd" ? "Cheque / DD number" : f.mode === "cash" ? "Reference (optional)" : f.mode ? "UTR / transaction reference" : "Reference"} value={f.reference} onChange={set("reference")} maxLength={60}
            hint={f.mode === "cash" ? "Optional for cash" : undefined} />
          <TextInput label="Bank" value={f.bank_name} onChange={set("bank_name")} maxLength={150} />
        </div>
        {cashTooMuch && <p role="alert" className="text-sm text-danger">Cash of ₹2,00,000 or more can’t be accepted (Income-tax Act, section 269ST).</p>}
        {looksCash && <p role="alert" className="text-sm text-danger">This looks like a cash payment; choose Cash as the mode.</p>}
        <TextInput label="Paid by" value={f.payer_name} onChange={set("payer_name")} maxLength={150} />
        <fieldset className="space-y-2 rounded-lg bg-paper p-3 text-sm">
          <legend className="font-semibold">Matching</legend>
          <label className="flex min-h-9 items-center gap-2"><input type="radio" name="match" checked={!manual} onChange={() => setManual(false)} className="accent-forest-900" />Oldest unpaid stages first</label>
          <label className="flex min-h-9 items-center gap-2"><input type="radio" name="match" checked={manual} onChange={() => setManual(true)} className="accent-forest-900" />Choose stages or charges</label>
          {manual && <MatchRows d={d} rows={rows} setRows={setRows} />}
          <p className="text-xs text-muted">Anything not matched stays as an advance.</p>
        </fieldset>
        <TextArea label="Notes (optional)" value={f.notes} onChange={set("notes")} rows={2} maxLength={500} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={act.isPending} disabled={amount <= 0 || !f.mode || cashTooMuch || looksCash}>Record receipt</Button></div>
      </form>
    </Modal>
  );
}

function Rematch({ d, r, caseId, onClose }: { d: Receipts; r: Receipt; caseId: number; onClose: () => void }) {
  const act = useReceiptAction(caseId); const toast = useToast();
  const [rows, setRows] = useState<Row[]>(r.matches.map((m) => ({ target: m.stage_seq != null ? `s:${m.stage_seq}` : `h:${m.charge_head}`, amount: String(m.amount) })));
  // this receipt's own matches free up room, so list them even if "fully paid" by it
  const extra = r.matches.map((m) => (m.stage_seq != null ? `s:${m.stage_seq}` : `h:${m.charge_head}`));
  const data: Receipts = { ...d, stages: d.stages.map((s) => (extra.includes(`s:${s.seq}`) ? { ...s, outstanding: Math.max(s.outstanding, 1) } : s)) };
  return (
    <Modal title={`Match ${r.receipt_no} (${inr(r.amount)})`} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ method: "put", path: `/${r.id}/matches`, body: toMatches(rows) }, { onSuccess: () => { toast("Matching saved"); onClose(); } }); }}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <MatchRows d={data} rows={rows} setRows={setRows} />
        <p className="text-sm text-muted">Matched {inr(toMatches(rows).reduce((a, m) => a + m.amount, 0))} of {inr(r.amount)}.</p>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending}>Save matching</Button></div>
      </form>
    </Modal>
  );
}

function VoidDialog({ r, kind, caseId, onClose }: { r: Receipt; kind: "bounce" | "reverse"; caseId: number; onClose: () => void }) {
  const act = useReceiptAction(caseId); const toast = useToast(); const [reason, setReason] = useState("");
  const reject = kind === "reverse" && r.status === "recorded";
  const title = kind === "bounce" ? `Mark ${r.receipt_no} as bounced` : reject ? `Reject ${r.receipt_no}` : `Reverse ${r.receipt_no}`;
  return (
    <Modal title={title} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ path: `/${r.id}/${kind}`, body: { reason: reason.trim() } }, { onSuccess: () => { toast(kind === "bounce" ? "Marked as bounced" : reject ? "Receipt rejected" : "Receipt reversed"); onClose(); } }); }}>
        {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
        <p className="text-sm">{inr(r.amount)} {r.reference ? `(${r.reference})` : ""} will stop counting. It stays on record with your reason.</p>
        <TextArea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} autoFocus placeholder={kind === "bounce" ? "e.g. Insufficient funds" : reject ? "e.g. Was a cheque, entered as NEFT" : "e.g. Entered twice"} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="danger" loading={act.isPending} disabled={reason.trim().length < 3}>{kind === "bounce" ? "Mark bounced" : reject ? "Reject" : "Reverse"}</Button></div>
      </form>
    </Modal>
  );
}

export function ReceiptsTab({ caseId }: { caseId: number }) {
  const q = useReceipts(caseId);
  const act = useReceiptAction(caseId); const toast = useToast();
  const [open, setOpen] = useState<null | { kind: "record" } | { kind: "match" | "bounce" | "reverse"; r: Receipt }>(null);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const d = q.data;
  if (!d.ledger_exists) return <section role="tabpanel" aria-label="Receipts" className="rounded-xl bg-white p-5 text-sm text-muted ring-1 ring-line">Receipts can be recorded once the ledger has been generated (Ledger tab).</section>;
  const b = d.balances!;
  const tone = (s: Receipt["status"]) => (s === "confirmed" ? "neutral" : s === "recorded" ? "gold" : "muted") as "neutral" | "gold" | "muted";
  return (
    <section role="tabpanel" aria-label="Receipts" className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <dl className="grid flex-1 grid-cols-2 gap-2 sm:grid-cols-5">
          {([["Received (confirmed)", b.received], ["Waiting for confirmation", b.pending_confirmation], ["Advance (not matched)", b.unapplied], ["Currently demanded", b.currently_demanded], ["Overdue", b.overdue]] as const).map(([l, n]) => (
            <div key={l} className={cx("rounded-lg p-2.5 ring-1 ring-line", l === "Overdue" && n > 0 ? "bg-danger-soft" : "bg-white")}><dt className="text-xs text-muted">{l}</dt><dd className="font-semibold tabular-nums">{inr(n)}</dd></div>
          ))}
        </dl>
        <div className="flex gap-2">
          <a href={`/statement/${caseId}`} target="_blank" rel="noopener" className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-white px-3 text-sm ring-1 ring-line hover:bg-forest-50"><Printer className="size-4" aria-hidden />Statement of account</a>
          {d.can_record && <Button onClick={() => setOpen({ kind: "record" })}><Plus className="size-4" aria-hidden />Record receipt</Button>}
        </div>
      </div>
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
        <table className="w-full min-w-[760px] text-sm">
          <caption className="sr-only">Receipts</caption>
          <thead className="text-xs text-muted"><tr>{["Receipt", "Mode", "Amount", "Matched", "Status", ""].map((h, i) => <th key={i} scope="col" className={cx("px-3 py-2 font-normal", i === 2 || i === 3 ? "text-right" : "text-left")}>{h}</th>)}</tr></thead>
          <tbody>
            {d.receipts.length === 0 && <tr><td colSpan={6} className="px-3 py-6 text-center text-muted">No receipts yet.</td></tr>}
            {d.receipts.map((r) => (
              <tr key={r.id} className={cx("border-t border-line align-top", (r.status === "bounced" || r.status === "reversed") && "text-muted")}>
                <th scope="row" className="px-3 py-2 text-left font-normal"><span className="font-medium">{r.receipt_no}</span> <span className="text-xs text-muted">{r.received_on}</span>
                  <span className="block text-xs text-muted">{r.source === "loan" ? "Loan disbursement" : "Own funds"}{r.payer_name ? ` · ${r.payer_name}` : ""}{r.from_booking ? " · from the booking" : ""}</span>
                  {r.void_reason && <span className="block text-xs text-danger">{statusLabel(r)}: {r.void_reason}</span>}</th>
                <td className="px-3 py-2">{MODE_LABELS[r.mode]}{r.reference && <span className="block text-xs text-muted">{r.reference}</span>}</td>
                <td className={cx("px-3 py-2 text-right tabular-nums", (r.status === "bounced" || r.status === "reversed") && "line-through")}>{inr(r.amount)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{r.status === "bounced" || r.status === "reversed" ? <span aria-label="Not counted">—</span> : <>{inr(r.matched)}
                  {r.matched < r.amount && <span className="block text-xs text-muted">{inr(r.amount - r.matched)} advance</span>}</>}</td>
                <td className="px-3 py-2"><Badge tone={tone(r.status)}>{statusLabel(r)}</Badge>
                  <span className="block text-xs text-muted">by {r.recorded_by?.full_name ?? "—"}{r.confirmed_by ? `; confirmed by ${r.confirmed_by.full_name}` : ""}</span></td>
                <td className="px-3 py-2"><div className="flex flex-wrap justify-end gap-1">
                  {r.can_match && <Button variant="ghost" onClick={() => setOpen({ kind: "match", r })}>Match</Button>}
                  {r.can_confirm && <Button variant="secondary" loading={act.isPending} onClick={() => act.mutate({ path: `/${r.id}/confirm` }, { onSuccess: () => toast(`${r.receipt_no} confirmed`) })}>Confirm</Button>}
                  {r.status === "recorded" && !r.can_confirm && <span className="self-center text-xs text-muted">Waiting for a finance approver</span>}
                  {r.can_bounce && <Button variant="ghost" onClick={() => setOpen({ kind: "bounce", r })}>Bounced</Button>}
                  {r.can_reverse && <Button variant="ghost" onClick={() => setOpen({ kind: "reverse", r })}>{r.status === "recorded" ? "Reject" : "Reverse"}</Button>}
                </div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
        <table className="w-full min-w-[560px] text-sm">
          <caption className="px-3 pt-3 text-left font-semibold">Stages: paid and outstanding</caption>
          <thead className="text-xs text-muted"><tr>{["Stage", "Due", "Total", "Paid", "Outstanding"].map((h, i) => <th key={h} scope="col" className={cx("px-3 py-1.5 font-normal", i >= 2 ? "text-right" : "text-left")}>{h}</th>)}</tr></thead>
          <tbody>{d.stages.map((s) => (
            <tr key={s.seq} className="border-t border-line"><td className="px-3 py-1.5">{s.name}{s.is_due && s.outstanding > 0 && <> <Badge tone="gold">Due</Badge></>}</td>
              <td className="px-3 py-1.5 text-xs text-muted">{s.due}</td><td className="px-3 py-1.5 text-right tabular-nums">{inr(s.total)}</td>
              <td className="px-3 py-1.5 text-right tabular-nums">{inr(s.paid)}</td><td className="px-3 py-1.5 text-right tabular-nums">{inr(s.outstanding)}</td></tr>))}</tbody>
        </table>
      </div>
      {open?.kind === "record" && <RecordReceipt d={d} caseId={caseId} onClose={() => setOpen(null)} />}
      {open?.kind === "match" && <Rematch d={d} r={open.r} caseId={caseId} onClose={() => setOpen(null)} />}
      {(open?.kind === "bounce" || open?.kind === "reverse") && <VoidDialog r={open.r} kind={open.kind} caseId={caseId} onClose={() => setOpen(null)} />}
      <p className="text-xs text-muted">Recorded {d.receipts.length} receipts. Times shown in IST{d.receipts[0] ? `; latest recorded ${formatDateTime(d.receipts[0].recorded_at)}` : ""}.</p>
    </section>
  );
}
