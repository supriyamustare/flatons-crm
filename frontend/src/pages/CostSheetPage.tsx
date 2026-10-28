import { useParams } from "react-router";
import { Printer } from "lucide-react";
import { ErrorState } from "../components/ui";
import { useCostSheet } from "../components/inventory/UnitSections";
import { errorMessage } from "../lib/api";
import { PREFERENCE_LABELS } from "../components/bookings/CustomerFields";

const inr = (v: number) => `₹ ${v.toLocaleString("en-IN")}`;
const SQM_PER_SQFT = 0.09290304;

/** The cost sheet as the developer prints it (Habitat PRINT layout). Use the browser's print (or Save as PDF). */
export function CostSheetPage() {
  const unitId = Number(useParams().unitId);
  const sheet = useCostSheet(unitId);
  if (sheet.isPending) return <p className="p-8 text-muted">Preparing the cost sheet…</p>;
  if (sheet.isError) return <div className="p-8"><ErrorState message={errorMessage(sheet.error, "Couldn’t load the cost sheet.")} onRetry={() => void sheet.refetch()} /></div>;
  const s = sheet.data;
  const c = s.customer;
  const td = "border border-neutral-400 px-2 py-1 align-top";
  const num = `${td} text-right tabular-nums whitespace-nowrap`;
  return (
    <div className="min-h-screen bg-neutral-100 py-6 print:bg-white print:py-0">
      <div className="mx-auto mb-4 flex max-w-3xl items-center justify-between px-4 print:hidden">
        <p className="text-sm text-neutral-600">{s.ready ? "Check the details, then print or save as PDF." : `Missing ${s.missing.join(" and ")}: add them under the unit’s Price and area.`}</p>
        <button type="button" onClick={() => window.print()} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white">
          <Printer className="size-4" aria-hidden />Print
        </button>
      </div>
      <article className="mx-auto max-w-3xl bg-white p-8 text-[13px] leading-snug text-black shadow print:max-w-none print:p-0 print:shadow-none" aria-label="Cost sheet">
        <h1 className="mb-3 text-center text-lg font-bold tracking-wide">COST SHEET</h1>
        <table className="w-full border-collapse"><tbody>
          <tr><th className={`${td} w-[55%] text-left font-normal`}>Name of the Project</th><td className={`${td} font-bold`} colSpan={2}>{s.project.toUpperCase()}</td></tr>
          <tr><th className={`${td} text-left font-normal`}>Name of the Developer</th><td className={`${td} font-bold`} colSpan={2}>{s.developer_name.toUpperCase()}</td></tr>
          <tr><th className={`${td} text-left font-normal`}>Site Address</th><td className={td} colSpan={2}>{s.site_address}</td></tr>
          <tr><th className={`${td} text-left font-normal`}>RERA Registration No.</th><td className={td} colSpan={2}>{s.rera_number}</td></tr>
          <tr><th className={`${td} text-left font-normal`}>Type / Wing / Flat #</th><td className={td} colSpan={2}>{s.unit_label}</td></tr>
          <tr><th className={`${td} text-left font-normal`}>Total flat carpet area incl. enclosed balcony, dry balcony and terrace (Sq-Mtr)</th>
            <td className={num} colSpan={2}>{s.chargeable_sqft ? (s.chargeable_sqft * SQM_PER_SQFT).toFixed(2) : ""}</td></tr>
          <tr><th className={`${td} text-left font-normal`}>Total flat carpet area incl. enclosed balcony, dry balcony and terrace (Sq-Ft)</th>
            <td className={num} colSpan={2}>{s.chargeable_sqft?.toFixed(2) ?? ""}</td></tr>
          {s.rate_psf && <tr><th className={`${td} text-left font-normal`}>Rate per Sq-Ft</th><td className={num} colSpan={2}>{inr(s.rate_psf)}</td></tr>}
          <tr className="font-bold"><th className={`${td} text-left`}>COST OF FLAT</th><td className={num}>{inr(s.cost)}</td><td className={num}><span className="block text-[10px] font-normal">GST on cost</span>{inr(s.gst)}</td></tr>
        </tbody></table>

        <table className="mt-4 w-full border-collapse">
          <thead><tr className="bg-neutral-100 font-bold"><th className={`${td} text-left`}>PAYMENT STAGES</th><th className={`${td} text-right`}>AMOUNT</th><th className={`${td} text-right`}>GST {s.gst_pct}%</th></tr></thead>
          <tbody>
            {s.stages.map((st) => <tr key={st.name}><td className={td}>{st.name} {st.pct}%</td><td className={num}>{inr(st.amount)}</td><td className={num}>{inr(st.gst)}</td></tr>)}
            <tr className="font-bold"><td className={td}>TOTAL</td><td className={num}>{inr(s.stages.reduce((a, b) => a + b.amount, 0))}</td><td className={num}>{inr(s.stages.reduce((a, b) => a + b.gst, 0))}</td></tr>
          </tbody>
        </table>

        <table className="mt-4 w-full border-collapse"><tbody>
          <tr><td className={td}>FURNISHING COST{s.furnishing_per_sqft ? ` (₹ ${s.furnishing_per_sqft} per Sq-Ft)` : ""}</td><td className={num}>{inr(s.furnishing)}</td><td className={td}></td></tr>
          <tr><td className={td}>STAMP DUTY @ {s.stamp_duty_pct}%</td><td className={num}>{inr(s.stamp_duty)}</td><td className={td}>On Registration</td></tr>
          <tr><td className={td}>Registration Fees @ {s.registration_pct}% (or {s.registration_cap.toLocaleString("en-IN")} max)</td><td className={num}>{inr(s.registration)}</td><td className={td}>On Registration</td></tr>
          <tr><td className={td}>LEGAL CHARGES</td><td className={num}>{inr(s.legal_charges)}</td><td className={td}>On Registration</td></tr>
          <tr className="font-bold"><td className={td}>TOTAL FEES &amp; GOVERNMENT TAXES</td><td className={num}>{inr(s.fees_total)}</td><td className={td}></td></tr>
          {s.other_charges > 0 && <tr><td className={td}>{s.other_charges_label.toUpperCase()}</td><td className={num}>{inr(s.other_charges)}</td><td className={td}></td></tr>}
          <tr className="bg-neutral-100 text-[15px] font-bold"><td className={td}>GRAND TOTAL</td><td className={num}>{inr(s.grand_total)}</td><td className={td}></td></tr>
        </tbody></table>

        {c && (
          <table className="mt-4 w-full border-collapse"><tbody>
            <tr className="bg-neutral-100 font-bold"><td className={td} colSpan={2}>CUSTOMER ({c.booking_code})</td></tr>
            <tr><td className={`${td} w-[35%]`}>Name</td><td className={td}>{c.name}</td></tr>
            <tr><td className={td}>Applicant name</td><td className={td}>{c.applicant_name ?? ""}</td></tr>
            <tr><td className={td}>Mobile / Email</td><td className={td}>{[c.mobile, c.email].filter(Boolean).join(" / ")}</td></tr>
            <tr><td className={td}>Address</td><td className={td}>{c.address ?? ""}</td></tr>
            <tr><td className={td}>Payment preference</td><td className={td}>{c.payment_preference ? PREFERENCE_LABELS[c.payment_preference] : ""}{c.bank_name ? `: ${c.bank_name}` : ""}</td></tr>
          </tbody></table>
        )}

        {s.notes.length > 0 && (
          <section className="mt-4"><h2 className="font-bold">NOTES</h2>
            <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-[12px]">{s.notes.map((n, i) => <li key={i}>{n}</li>)}</ol>
          </section>
        )}
        <div className="mt-12 grid grid-cols-2 gap-12 text-[13px]">
          <div><div className="border-t border-black pt-1">Client Signature</div><div className="mt-6">Date:</div></div>
          <div><div className="border-t border-black pt-1">{s.signatory || "Developer representative"}</div><div className="mt-6">Date:</div></div>
        </div>
      </article>
    </div>
  );
}
