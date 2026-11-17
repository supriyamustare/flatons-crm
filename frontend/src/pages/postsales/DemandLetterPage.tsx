import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router";
import { Printer } from "lucide-react";
import { ErrorState } from "../../components/ui";
import { inr } from "../../hooks/useLedger";
import { api, errorMessage } from "../../lib/api";

interface Letter {
  demand_no: string; case_code: string; booking_code: string; customer: string; co_applicants: string | null; address: string | null; project: string; unit_no: string;
  agreed_price: number; stage: string; stage_base: number | null; stage_gst: number | null; stage_amount: number; previous_dues: number; total_due: number;
  demanded_on: string; due_date: string; notes: string[]; status: string; draft: boolean; cancelled: boolean; cancel_reason: string | null; version: number;
  developer: { name: string | null; rera: string | null; address: string | null; gstin: string | null; signatory: string | null; designation: string | null };
  bank: { name: string | null; holder: string | null; account: string | null; ifsc: string | null; branch: string | null };
}
const day = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });

/** The demand letter: frozen once approved; DRAFT-marked before that; CANCELLED-stamped if cancelled. Print or save as PDF. */
export function DemandLetterPage() {
  const { caseId, demandId } = useParams();
  const q = useQuery({ queryKey: ["demand-letter", caseId, demandId], queryFn: async () => (await api.get<Letter>(`/post-sales/cases/${caseId}/demands/${demandId}/letter`)).data });
  if (q.isPending) return <p className="p-8 text-muted">Preparing the letter…</p>;
  if (q.isError) return <div className="p-8"><ErrorState message={errorMessage(q.error, "Couldn’t load the letter.")} onRetry={() => void q.refetch()} /></div>;
  const l = q.data; const dev = l.developer; const td = "border border-neutral-300 px-2 py-1"; const num = `${td} text-right tabular-nums`;
  const stamp = l.cancelled ? "CANCELLED" : l.draft ? "DRAFT · NOT FOR ISSUE" : null;
  return (
    <div className="min-h-screen bg-neutral-100 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-3xl items-center justify-between px-4 print:hidden">
        <p className="text-sm text-neutral-600">{l.cancelled ? `Cancelled: ${l.cancel_reason}` : l.draft ? "Draft: becomes final once a finance approver approves it." : "Approved letter (frozen)."}</p>
        <button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white"><Printer className="size-4" aria-hidden />Print</button>
      </div>
      <article aria-label="Demand letter" className="relative mx-auto max-w-3xl overflow-hidden bg-white p-10 text-[13px] leading-relaxed text-black shadow print:max-w-none print:p-0 print:shadow-none">
        {stamp && <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center"><span className="-rotate-[24deg] text-6xl font-bold text-red-600/15">{stamp}</span></div>}
        {stamp && <p className="sr-only">{stamp}</p>}
        <header className="border-b-2 border-black pb-2">
          <p className="text-lg font-bold">{dev.name ?? "—"}</p>
          <p className="text-xs">{dev.address}</p>
          <p className="text-xs">{dev.gstin ? `GSTIN ${dev.gstin}` : ""}{dev.rera ? ` · Project RERA ${dev.rera}` : ""}</p>
        </header>
        <div className="mt-4 flex justify-between text-xs"><span>Ref: {l.demand_no}{l.version > 1 ? ` (replaces an earlier letter)` : ""} · {l.booking_code}</span><span>Date: {day(l.demanded_on)}</span></div>
        <div className="mt-4"><p>To,</p><p className="font-semibold">{l.customer}</p>{l.co_applicants && <p>{l.co_applicants}</p>}<p className="whitespace-pre-line">{l.address}</p></div>
        <p className="mt-4 font-semibold">Subject: Demand for payment: {l.stage}, Unit {l.unit_no}, {l.project}</p>
        <p className="mt-3">Dear {l.customer},</p>
        <p className="mt-2">We are pleased to inform you that the <b>{l.stage}</b> stage of construction has been completed. As per the payment schedule of your booking for Unit {l.unit_no} in {l.project}, the following amount is now due:</p>
        <table className="mt-3 w-full border-collapse"><tbody>
          {l.stage_base != null && <tr><td className={td}>{l.stage} instalment</td><td className={num}>{inr(l.stage_base)}</td></tr>}
          {l.stage_gst != null && <tr><td className={td}>GST on the instalment</td><td className={num}>{inr(l.stage_gst)}</td></tr>}
          <tr><td className={td}>Amount for this stage still payable</td><td className={num}>{inr(l.stage_amount)}</td></tr>
          {l.previous_dues > 0 && <tr><td className={td}>Earlier dues still unpaid</td><td className={num}>{inr(l.previous_dues)}</td></tr>}
          <tr className="font-bold"><td className={td}>Total payable by {day(l.due_date)}</td><td className={num}>{inr(l.total_due)}</td></tr>
        </tbody></table>
        <p className="mt-4 font-semibold">Please pay to:</p>
        <table className="mt-1 w-full border-collapse"><tbody>
          {([["Account name", l.bank.holder], ["Bank", l.bank.name], ["Account number", l.bank.account], ["IFSC", l.bank.ifsc], ["Branch", l.bank.branch]] as const).map(([k, v]) =>
            <tr key={k}><td className={`${td} w-1/3`}>{k}</td><td className={`${td} font-medium`}>{v ?? "—"}</td></tr>)}
        </tbody></table>
        <p className="mt-3">Kindly quote <b>{l.booking_code}</b> with your payment. If you have already paid, please ignore this letter and share the payment details with us.</p>
        {l.notes.length > 0 && <ul className="mt-2 list-disc pl-5 text-xs">{l.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
        <div className="mt-10"><p>For {dev.name ?? "the developer"},</p><div className="mt-10 w-56 border-t border-black pt-1"><p>{dev.signatory}</p><p className="text-xs">{dev.designation}</p></div></div>
      </article>
    </div>
  );
}
