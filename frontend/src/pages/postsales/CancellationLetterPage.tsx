import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { Printer } from "lucide-react";
import { ErrorState } from "../../components/ui";
import { inr } from "../../hooks/useLedger";
import { useCase } from "../../hooks/usePostSales";
import { api, errorMessage } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
/** The approved settlement for the customer: draft-marked until both approvals are given. */
export function CancellationLetterPage() {
  const { caseId } = useParams();
  const c = useCase(Number(caseId));
  const q = useQuery({ queryKey: ["cancellation", Number(caseId)], queryFn: async () => (await api.get<any>(`/post-sales/cases/${caseId}/cancellation`)).data });
  if (q.isPending || c.isPending) return <p className="p-8 text-muted">Preparing the letter…</p>;
  if (q.isError || c.isError) return <div className="p-8"><ErrorState message={errorMessage(q.error ?? c.error, "Couldn’t load the letter.")} onRetry={() => void q.refetch()} /></div>;
  const x = q.data.cancellation; const k = c.data!;
  if (!x || !x.settlement) return <p className="p-8 text-muted">The settlement isn’t calculated yet.</p>;
  const st = x.settlement; const draft = !["approved", "communicated", "closed"].includes(x.status);
  return (
    <div className="min-h-screen bg-neutral-100 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-3xl justify-end px-4 print:hidden"><button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white"><Printer className="size-4" aria-hidden />Print</button></div>
      <article aria-label="Cancellation letter" className="relative mx-auto max-w-3xl bg-white p-8 text-[13px] leading-relaxed text-black shadow print:max-w-none print:p-0 print:shadow-none">
        {draft && <p aria-label="Draft" className="pointer-events-none absolute inset-0 flex items-center justify-center text-7xl font-bold text-red-600/15 [transform:rotate(-30deg)]">DRAFT</p>}
        <p className="text-right">Ref: {x.number}</p>
        <p>To: {k.customer}<br />{k.project}, unit {k.unit_no} ({k.booking_code})</p>
        <h1 className="mt-4 text-center font-bold">CANCELLATION OF BOOKING AND SETTLEMENT</h1>
        <p className="mt-3">With reference to the {x.initiated_by === "customer" ? "request received from you" : "notice issued"} on {x.request_date} ({x.reason_label}), the booking stands cancelled{x.effective_date ? ` with effect from ${x.effective_date}` : ""}{x.contract_clause ? `, under ${x.contract_clause}` : ""}. The settlement is as follows:</p>
        <table className="mt-3 w-full border-collapse"><tbody>
          <tr><td className="border border-neutral-300 px-2 py-1">Amount received from you (confirmed)</td><td className="border border-neutral-300 px-2 py-1 text-right">{inr(st.snapshot.received)}</td></tr>
          {st.deductions.map((d: any, i: number) => <tr key={i}><td className="border border-neutral-300 px-2 py-1">Less: {d.label} <span className="text-xs">({d.basis})</span></td><td className="border border-neutral-300 px-2 py-1 text-right">({inr(d.amount)})</td></tr>)}
          <tr className="font-bold"><td className="border border-neutral-300 px-2 py-1">{st.balance_due_from_customer > 0 ? "Amount payable by you" : "Refund to you"}</td>
            <td className="border border-neutral-300 px-2 py-1 text-right">{inr(st.balance_due_from_customer > 0 ? st.balance_due_from_customer : st.refund)}</td></tr></tbody></table>
        {st.snapshot.loan_disbursed > 0 && <p className="mt-2 text-xs">Of the amount received, {inr(st.snapshot.loan_disbursed)} was disbursed by your lender; the refund will be settled with the lender as required by your loan documents.</p>}
        {st.refund > 0 && <p className="mt-2">The refund will be made to the bank account you provide, after verification.</p>}
        <p className="mt-2">All earlier demands, receipts and documents remain on record and a final statement of account is available on request.</p>
        <div className="mt-12 grid grid-cols-2 gap-10 text-xs"><div className="border-t border-black pt-1">Authorised signatory</div><div className="border-t border-black pt-1">Received: {k.customer}</div></div>
      </article>
    </div>
  );
}
