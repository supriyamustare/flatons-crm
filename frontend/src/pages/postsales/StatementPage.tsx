import { useParams } from "react-router";
import { Printer } from "lucide-react";
import { ErrorState } from "../../components/ui";
import { inr, useLedger } from "../../hooks/useLedger";
import { MODE_LABELS, RECEIPT_STATUS, useReceipts } from "../../hooks/useReceipts";
import { useCase } from "../../hooks/usePostSales";
import { errorMessage } from "../../lib/api";

/** Statement of account: charges, each stage paid and outstanding, every receipt. Print or save as PDF. */
export function StatementPage() {
  const id = Number(useParams().caseId);
  const c = useCase(id); const l = useLedger(id, true); const r = useReceipts(id);
  if (c.isPending || l.isPending || r.isPending) return <p className="p-8 text-muted">Preparing the statement…</p>;
  const err = c.error ?? l.error ?? r.error;
  if (err) return <div className="p-8"><ErrorState message={errorMessage(err, "Couldn’t load the statement.")} onRetry={() => { void c.refetch(); void l.refetch(); void r.refetch(); }} /></div>;
  if (!l.data!.exists) return <p className="p-8 text-muted">There’s no ledger for this case yet.</p>;
  const k = c.data!; const led = l.data!; const rec = r.data!; const t = led.totals!; const b = rec.balances!;
  const td = "border border-neutral-300 px-2 py-1"; const num = `${td} text-right tabular-nums whitespace-nowrap`;
  const date = new Date().toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric", timeZone: "Asia/Kolkata" });
  return (
    <div className="min-h-screen bg-neutral-100 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-3xl justify-end px-4 print:hidden">
        <button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white"><Printer className="size-4" aria-hidden />Print</button>
      </div>
      <article aria-label="Statement of account" className="mx-auto max-w-3xl bg-white p-8 text-[13px] text-black shadow print:max-w-none print:p-0 print:shadow-none">
        <h1 className="text-center text-lg font-bold">STATEMENT OF ACCOUNT</h1>
        <p className="mt-1 text-center text-xs">as on {date}</p>
        <table className="mt-4 w-full border-collapse"><tbody>
          <tr><td className={`${td} w-1/3`}>Customer</td><td className={`${td} font-semibold`}>{k.customer}</td></tr>
          <tr><td className={td}>Project / unit</td><td className={td}>{k.project}, unit {k.unit_no}</td></tr>
          <tr><td className={td}>Booking / case</td><td className={td}>{k.booking_code} (booked {k.booking_date}) · {k.case_code}</td></tr>
          <tr><td className={td}>Funding</td><td className={td}>{led.loan_sanctioned ? `Loan ${inr(led.loan_sanctioned)} from ${led.lender ?? "—"}; own contribution ${inr(Math.max(0, t.total_payable - led.loan_sanctioned))}` : "Own funds"}</td></tr>
        </tbody></table>
        <h2 className="mt-5 font-bold">Summary</h2>
        <table className="mt-1 w-full border-collapse"><tbody>
          {([["Total payable", t.total_payable], ["Received", b.received], ["Total outstanding", b.total_outstanding], ["Currently demanded", b.currently_demanded],
            ["Overdue", b.overdue], ["Advance (not yet matched)", b.unapplied], ["Other charges outstanding", b.other_charges]] as const).map(([lbl, n]) => (
            <tr key={lbl}><td className={td}>{lbl}</td><td className={num}>{inr(n)}</td></tr>))}
        </tbody></table>
        <h2 className="mt-5 font-bold">Payment schedule</h2>
        <table className="mt-1 w-full border-collapse">
          <thead><tr className="bg-neutral-100">{["Stage", "Due", "Amount incl. GST", "Paid", "Outstanding"].map((h) => <th key={h} className={`${td} text-left`}>{h}</th>)}</tr></thead>
          <tbody>{rec.stages.map((s) => <tr key={s.seq}><td className={td}>{s.name}</td><td className={td}>{s.due}</td><td className={num}>{inr(s.total)}</td><td className={num}>{inr(s.paid)}</td><td className={num}>{inr(s.outstanding)}</td></tr>)}
            <tr className="font-bold"><td className={td} colSpan={2}>Total</td><td className={num}>{inr(rec.stages.reduce((a, s) => a + s.total, 0))}</td>
              <td className={num}>{inr(rec.stages.reduce((a, s) => a + s.paid, 0))}</td><td className={num}>{inr(rec.stages.reduce((a, s) => a + s.outstanding, 0))}</td></tr></tbody>
        </table>
        {rec.other_charges.length > 0 && (<>
          <h2 className="mt-5 font-bold">Other charges (outside the payment plan)</h2>
          <table className="mt-1 w-full border-collapse"><tbody>{rec.other_charges.map((h) => <tr key={h.head}><td className={td}>{h.label}</td><td className={num}>{inr(h.total)}</td><td className={num}>paid {inr(h.paid)}</td><td className={num}>due {inr(h.outstanding)}</td></tr>)}</tbody></table>
        </>)}
        <h2 className="mt-5 font-bold">Receipts</h2>
        <table className="mt-1 w-full border-collapse">
          <thead><tr className="bg-neutral-100">{["Receipt", "Date", "Mode / reference", "Amount", "Status"].map((h) => <th key={h} className={`${td} text-left`}>{h}</th>)}</tr></thead>
          <tbody>{[...rec.receipts].reverse().map((x) => (
            <tr key={x.id}><td className={td}>{x.receipt_no}</td><td className={td}>{x.received_on}</td><td className={td}>{MODE_LABELS[x.mode]}{x.reference ? ` ${x.reference}` : ""}{x.source === "loan" ? " (loan)" : ""}</td>
              <td className={num}>{inr(x.amount)}</td><td className={td}>{RECEIPT_STATUS[x.status]}{x.void_reason ? `: ${x.void_reason}` : ""}</td></tr>))}</tbody>
        </table>
        <p className="mt-6 text-[11px] text-neutral-600">Only confirmed receipts count as received. Receipts waiting for confirmation, bounced or reversed are listed for reference. This statement is computer-generated.</p>
      </article>
    </div>
  );
}
