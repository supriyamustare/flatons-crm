import { useParams } from "react-router";
import { Printer } from "lucide-react";
import { ErrorState } from "../../components/ui";
import { useAgreement } from "../../hooks/useAgreement";
import { inr } from "../../hooks/useLedger";
import { errorMessage } from "../../lib/api";

/** The agreement draft built from the approved template. DRAFT-marked until registered. Print or save as PDF. */
export function AgreementDraftPage() {
  const caseId = Number(useParams().caseId);
  const q = useAgreement(caseId);
  if (q.isPending) return <p className="p-8 text-muted">Preparing the draft…</p>;
  if (q.isError) return <div className="p-8"><ErrorState message={errorMessage(q.error, "Couldn’t load the draft.")} onRetry={() => void q.refetch()} /></div>;
  const a = q.data.agreement; const d = a?.draft;
  if (!a || !d) return <p className="p-8 text-muted">There’s no draft yet.</p>;
  const final = ["registered", "final_uploaded", "completed"].includes(a.status);
  const td = "border border-neutral-300 px-2 py-1"; const num = `${td} text-right tabular-nums`;
  return (
    <div className="min-h-screen bg-neutral-100 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-3xl items-center justify-between px-4 print:hidden">
        <p className="text-sm text-neutral-600">{d.placeholder_clauses ? "Contains placeholder clauses: not for the customer until Legal replaces them." : `Draft version ${d.version}`}</p>
        <button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white"><Printer className="size-4" aria-hidden />Print</button>
      </div>
      <article aria-label="Agreement draft" className="relative mx-auto max-w-3xl overflow-hidden bg-white p-10 text-[13px] leading-relaxed text-black shadow print:max-w-none print:p-0 print:shadow-none">
        {!final && <><div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center"><span className="-rotate-[24deg] text-6xl font-bold text-red-600/15">DRAFT v{d.version}</span></div>
          <p className="sr-only">Draft version {d.version}</p></>}
        <h1 className="text-center text-lg font-bold">AGREEMENT FOR SALE</h1>
        <p className="text-center text-xs">{d.agreement_no} · {d.date}</p>
        <h2 className="mt-5 font-bold">Between</h2>
        <p><b>{d.developer.name}</b>, {d.developer.address}{d.developer.gstin ? `, GSTIN ${d.developer.gstin}` : ""}{d.developer.cin ? `, CIN ${d.developer.cin}` : ""}, through its {d.developer.designation} {d.developer.signatory} (“the Developer”)</p>
        <h2 className="mt-3 font-bold">And</h2>
        <ul className="list-disc pl-5">{d.purchasers.map((p, i) => <li key={i}><b>{p.name}</b>{p.pan ? `, PAN ${p.pan}` : ""}{p.share ? `, ${p.share}% share` : ""}{p.relation ? ` (${p.relation})` : ""}{p.address ? `, ${p.address}` : ""}</li>)}</ul>
        <p>(“the Purchaser(s)”)</p>
        <h2 className="mt-4 font-bold">Schedule A: the unit</h2>
        <p>Unit {d.unit.unit_no} ({d.unit.type}){d.unit.floor != null ? `, floor ${d.unit.floor}` : ""}{d.unit.building ? `, ${d.unit.building}` : ""}, {d.unit.project}{d.unit.location ? `, ${d.unit.location}` : ""}. Carpet area {d.unit.carpet_sqft} sq ft; saleable area {d.unit.saleable_sqft} sq ft. Project RERA registration {d.developer.rera}.</p>
        <h2 className="mt-4 font-bold">Schedule B: consideration</h2>
        <table className="mt-1 w-full border-collapse"><tbody>
          {d.consideration.map((c) => <tr key={c.label}><td className={td}>{c.label}</td><td className={num}>{inr(c.amount)}</td></tr>)}
          <tr className="font-bold"><td className={td}>Agreement value</td><td className={num}>{inr(d.agreement_value)}</td></tr>
          <tr><td className={td}>GST at {d.gst_pct}%</td><td className={num}>{inr(d.gst)}</td></tr>
        </tbody></table>
        <h2 className="mt-4 font-bold">Schedule C: payment schedule</h2>
        <table className="mt-1 w-full border-collapse">
          <thead><tr className="bg-neutral-100">{["Stage", "Due", "Amount", "GST"].map((h) => <th key={h} className={`${td} text-left`}>{h}</th>)}</tr></thead>
          <tbody>{d.schedule.map((s) => <tr key={s.name}><td className={td}>{s.name}</td><td className={td}>{s.due}</td><td className={num}>{inr(s.amount)}</td><td className={num}>{inr(s.gst)}</td></tr>)}</tbody>
        </table>
        <h2 className="mt-4 font-bold">Terms</h2>
        <ol className="list-decimal space-y-2 pl-5">{d.clauses.map((c, i) => <li key={i} className={c.includes("[PLACEHOLDER") ? "bg-yellow-100" : undefined}>{c}</li>)}</ol>
        <div className="mt-12 grid grid-cols-2 gap-10 text-xs">
          <div><div className="border-t border-black pt-1">For {d.developer.name}<br />{d.developer.signatory}, {d.developer.designation}</div></div>
          <div><div className="border-t border-black pt-1">Purchaser(s)<br />{d.purchasers.map((p) => p.name).join(", ")}</div></div>
        </div>
      </article>
    </div>
  );
}
