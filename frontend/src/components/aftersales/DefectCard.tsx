import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../ui";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
export const DEFECT_STATUS: Record<string, string> = { raised: "Complaint raised", acknowledged: "Acknowledged", inspection_scheduled: "Inspection scheduled", diagnosed: "Diagnosed",
  awaiting_customer_approval: "Not covered: awaiting customer approval", responsibility_assigned: "Responsibility assigned", in_rectification: "Rectification in progress",
  quality_check: "Quality check", customer_update: "Customer update", reopened: "Reopened", closed: "Closed" };
const LABEL: Record<string, string> = { acknowledge: "Acknowledge", schedule: "Schedule inspection", diagnose: "Record diagnosis", responsibility: "Assign responsibility",
  customer_approval: "Customer’s decision on the estimate", start: "Start rectification", complete: "Work done", quality: "Quality checked", customer: "Customer’s response" };

export function DefectCard({ d, onChange }: { d: Any; onChange: (d: Any) => void }) {
  const [step, setStep] = useState<string | null>(null);
  const [v, setV] = useState<Record<string, Any>>({});
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const send = async (s: string, data: Record<string, Any>) => {
    setBusy(true); setErr(null);
    try { onChange((await api.post(`/defects/${d.id}/step`, { step: s, data })).data); setStep(null); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  };
  const upload = async (file: File, kind: string) => { const fd = new FormData(); fd.append("file", file); fd.append("kind", kind);
    try { onChange((await api.post(`/defects/${d.id}/files`, fd)).data); } catch (e) { setErr(errorMessage(e)); } };
  const open = (s: string) => { setErr(null); setV({ visit_on: today(), visited_on: today(), on: today(), party: "contractor", covered: "yes", action: "repair", response: "accepted", approved: "yes", target: "" }); setStep(s); };
  const set = (k: string) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const s = d.steps ?? {};
  return (
    <li className={cx("rounded-xl p-4 text-sm ring-1", d.status === "closed" ? "bg-paper ring-line" : d.overdue ? "bg-danger-soft ring-danger/30" : "bg-white ring-line")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold">{d.number} · {d.description} <Badge tone={d.status === "closed" ? "muted" : "gold"}>{DEFECT_STATUS[d.status]}</Badge></p>
          <p className="text-xs text-muted">{d.unit}{d.location ? ` · ${d.location}` : ""} · {d.category}{d.item ? ` · ${d.item}` : ""} · raised {d.complaint_date} by {d.channel} · owner {d.owner ?? "—"}
            {d.target_date && ` · target ${d.target_date}`}{d.overdue && <span className="text-danger"> · overdue</span>}</p>
          {d.warranty && <p className="text-xs">Warranty: {d.warranty.name}{d.warranty.provider ? ` (${d.warranty.provider})` : ""}, {d.warranty_start ?? "?"} to {d.warranty_end ?? "?"}
            {d.in_warranty === true ? <b className="text-forest-800"> · in warranty</b> : d.in_warranty === false ? <b className="text-danger"> · warranty expired</b> : null}</p>}
          <dl className="mt-1 space-y-0.5 text-xs">
            {s.inspection && <div><dt className="inline font-medium">Inspection: </dt><dd className="inline">{s.inspection.visit_on} (customer: {s.inspection.availability})</dd></div>}
            {s.diagnosis && <div><dt className="inline font-medium">Diagnosis: </dt><dd className="inline">visited {s.diagnosis.visited_on}: {s.diagnosis.text}</dd></div>}
            {s.responsibility && <div><dt className="inline font-medium">Responsibility: </dt><dd className="inline">{s.responsibility.party}, {s.responsibility.covered ? "covered" : <>not covered ({s.responsibility.reason}; estimate ₹{s.responsibility.estimate})</>}</dd></div>}
            {s.customer_approval && <div><dt className="inline font-medium">Customer: </dt><dd className="inline">{s.customer_approval.approved ? "approved" : "declined"} the chargeable work on {s.customer_approval.on}</dd></div>}
            {s.rectification && <div><dt className="inline font-medium">Rectification: </dt><dd className="inline">{s.rectification.action} by {s.rectification.contractor}, target {s.rectification.target}</dd></div>}
            {s.completed && <div><dt className="inline font-medium">Work done: </dt><dd className="inline">{s.completed.work}{s.completed.materials ? ` (materials: ${s.completed.materials})` : ""}, {s.completed.by_name}</dd></div>}
            {s.quality && <div><dt className="inline font-medium">Quality check: </dt><dd className="inline">{s.quality.by_name}, {formatDateTime(s.quality.at)}</dd></div>}
            {(s.customer_history ?? []).map((h: Any, i: number) => <div key={i}><dt className="inline font-medium">Customer {h.response}: </dt><dd className="inline">{h.note ?? ""} ({formatDateTime(h.at)})</dd></div>)}
            {d.closure_reason && <div><dt className="inline font-medium">Closed: </dt><dd className="inline">{d.closure_reason}</dd></div>}
          </dl>
          {d.files.length > 0 && <p className="mt-1 flex flex-wrap gap-2 text-xs">{d.files.map((f: Any) => <a key={f.id} href={f.url} target="_blank" rel="noopener" className="text-forest-800 underline">{f.kind}: {f.file_name}</a>)}</p>}
        </div>
        <div className="flex flex-wrap gap-1.5">
          {d.next.map((x: string) => <Button key={x} variant={x === "quality" || x === "customer" ? "primary" : "secondary"} onClick={() => open(x)}>{LABEL[x]}</Button>)}
          {d.status !== "closed" && <label className="inline-flex min-h-10 cursor-pointer items-center rounded-lg px-3 text-sm ring-1 ring-line hover:bg-forest-50">Add photo
            <input type="file" accept=".jpg,.jpeg,.png,.pdf" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f, ["raised", "acknowledged"].includes(d.status) ? "complaint" : ["inspection_scheduled", "diagnosed"].includes(d.status) ? "diagnosis" : "completion"); }} /></label>}
        </div>
      </div>
      {err && !step && <div className="mt-2"><Alert>{err}</Alert></div>}
      {step && <Modal title={`${d.number}: ${LABEL[step]}`} onClose={() => setStep(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
          const data: Record<string, Any> = { ...v, covered: v.covered === "yes", approved: v.approved === "yes", estimate: v.estimate === undefined || v.estimate === "" ? undefined : Number(v.estimate) };
          void send(step, data); }}>
          {err && <Alert>{err}</Alert>}
          {step === "acknowledge" && <TextArea label="Note (optional)" value={v.note ?? ""} onChange={set("note")} rows={2} />}
          {step === "schedule" && <><TextInput label="Visit date" type="date" min={today()} value={v.visit_on} onChange={set("visit_on")} /><TextInput label="Customer’s availability" value={v.availability ?? ""} onChange={set("availability")} placeholder="e.g. weekdays after 5 pm" /></>}
          {step === "diagnose" && <><TextInput label="Actual visit date" type="date" max={today()} value={v.visited_on} onChange={set("visited_on")} /><TextArea label="Diagnosis" value={v.diagnosis ?? ""} onChange={set("diagnosis")} rows={3} /></>}
          {step === "responsibility" && <>
            <SelectInput label="Responsible party" value={v.party} onChange={set("party")}>{["developer", "contractor", "manufacturer", "customer", "society"].map((x) => <option key={x} value={x}>{x}</option>)}</SelectInput>
            <SelectInput label="Covered by warranty?" value={v.covered} onChange={set("covered")}><option value="yes">Yes, covered</option><option value="no">No, not covered (chargeable)</option></SelectInput>
            {v.covered === "no" && <><TextArea label="Why it isn’t covered" value={v.reason ?? ""} onChange={set("reason")} rows={2} /><TextInput label="Estimate for the work (₹)" type="number" min={0} value={v.estimate ?? ""} onChange={set("estimate")} />
              <p className="text-xs text-muted">Attach the supporting evidence (photo or report) first. The work can’t start until the customer approves the estimate.</p></>}</>}
          {step === "customer_approval" && <><SelectInput label="Customer’s decision" value={v.approved} onChange={set("approved")}><option value="yes">Approved the estimate</option><option value="no">Declined</option></SelectInput>
            <TextInput label="Date" type="date" max={today()} value={v.on} onChange={set("on")} /></>}
          {step === "start" && <><SelectInput label="Action" value={v.action} onChange={set("action")}><option value="repair">Repair</option><option value="replace">Replace</option></SelectInput>
            <TextInput label="Contractor or team" value={v.contractor ?? ""} onChange={set("contractor")} /><TextInput label="Rectification target date" type="date" min={today()} value={v.target} onChange={set("target")} /></>}
          {step === "complete" && <><TextArea label="Work done" value={v.work ?? ""} onChange={set("work")} rows={2} /><TextInput label="Spare parts or materials used" value={v.materials ?? ""} onChange={set("materials")} /></>}
          {step === "quality" && <TextArea label="Quality check note (optional)" value={v.note ?? ""} onChange={set("note")} rows={2} />}
          {step === "customer" && <><SelectInput label="Customer’s response" value={v.response} onChange={set("response")}><option value="accepted">Accepted the repair</option><option value="disputed">Disputes the repair</option></SelectInput>
            <TextArea label={v.response === "disputed" ? "What the customer disputes" : "Note (optional)"} value={v.note ?? ""} onChange={set("note")} rows={2} /></>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setStep(null)}>Cancel</Button><Button type="submit" loading={busy}>Save</Button></div>
        </form></Modal>}
    </li>
  );
}

export function RaiseDefect({ caseId, projectId, warranties, owners, onDone, onClose }: { caseId?: number; projectId?: number; warranties: Any[]; owners: { id: number; full_name: string }[]; onDone: () => void; onClose: () => void }) {
  const [v, setV] = useState({ category: "plumbing", description: "", location: "", item: "", channel: "phone", owner_id: "", warranty_item_id: "" });
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  return (
    <Modal title={caseId ? "Record a defect complaint" : "Record a common-area defect"} onClose={onClose}>
      <form className="space-y-3" onSubmit={async (e: FormEvent) => { e.preventDefault(); setBusy(true); setErr(null);
        try { await api.post("/defects", { ...(caseId ? { case_id: caseId } : { project_id: projectId }), category: v.category, description: v.description.trim(), location: v.location.trim() || null,
          item: v.item.trim() || null, channel: v.channel, owner_id: v.owner_id ? Number(v.owner_id) : null, warranty_item_id: v.warranty_item_id ? Number(v.warranty_item_id) : null }); onDone(); }
        catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); } }}>
        {err && <Alert>{err}</Alert>}
        <TextArea label="Complaint" value={v.description} onChange={set("description")} rows={3} />
        <div className="grid grid-cols-2 gap-3">
          <SelectInput label="Category" value={v.category} onChange={set("category")}>{["civil", "structural", "waterproofing", "electrical", "plumbing", "finishing", "fittings", "equipment", "other"].map((x) => <option key={x} value={x}>{x}</option>)}</SelectInput>
          <TextInput label="Where" value={v.location} onChange={set("location")} />
          <TextInput label="Product, fixture or equipment" value={v.item} onChange={set("item")} />
          <SelectInput label="Received by" value={v.channel} onChange={set("channel")}>{["phone", "email", "whatsapp", "walk_in", "letter", "other"].map((x) => <option key={x} value={x}>{x}</option>)}</SelectInput>
          <SelectInput label="Warranty that applies" value={v.warranty_item_id} onChange={set("warranty_item_id")}><option value="">Not sure yet</option>{warranties.filter((w) => w.active !== false).map((w) => <option key={w.id} value={w.id}>{w.name} ({w.period_months} months)</option>)}</SelectInput>
          <SelectInput label="Owner" value={v.owner_id} onChange={set("owner_id")}><option value="">After-sales team</option>{owners.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</SelectInput>
        </div>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={busy} disabled={v.description.trim().length < 2}>Record</Button></div>
      </form>
    </Modal>
  );
}
