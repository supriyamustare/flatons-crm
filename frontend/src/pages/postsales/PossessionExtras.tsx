import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
type Go = (path: string, body: unknown, msg: string, method?: "post" | "put") => void;
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const SEV = { minor: "muted", major: "gold", critical: "gold" } as const;
const STATUS = { open: "Open", fixed: "Fixed", verified: "Verified (waiting for customer)", closed: "Closed" } as const;

export function StatusAndDates({ f }: { f: Any }) {
  const st = f.possession_status; const d = f.dates;
  return (
    <section aria-label="Possession status" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <p className="font-semibold">Possession status: <Badge tone={st.status === "handover_completed" ? "neutral" : "gold"}>{st.label}</Badge></p>
      {st.pending.length > 0 && <p className="mt-1 flex flex-wrap gap-1 text-xs text-muted">Still pending (in parallel): {st.pending.map((p: Any) => <Badge key={p.key} tone="muted">{p.label}</Badge>)}</p>}
      <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {([["Construction completed", d.construction_completed], ["Possession offered", d.possession_offered], ["Legally eligible", d.legally_eligible], ["Actual possession", d.actual_possession]] as const)
          .map(([l, v]) => <div key={l} className="rounded-lg bg-paper p-2"><dt className="text-xs text-muted">{l}</dt><dd className="font-semibold">{v ?? "—"}</dd></div>)}
      </dl>
    </section>
  );
}

export function Inspections({ f, caseId, can, go }: { f: Any; caseId: number; can: boolean; go: Go }) {
  const [dlg, setDlg] = useState<null | { mode: "add" } | { mode: "share"; id: number }>(null);
  const [v, setV] = useState({ conducted_on: today(), attendees: "", notes: "", report_shared_on: today(), report_shared_via: "email" });
  return (
    <section aria-label="Customer inspections" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <div className="mb-2 flex items-center justify-between"><h3 className="font-semibold">Customer inspections</h3>{can && <Button variant="ghost" onClick={() => setDlg({ mode: "add" })}>Record inspection</Button>}</div>
      {f.inspections.length === 0 ? <p className="text-xs text-muted">No inspection yet. Schedule one under Appointments (Customer inspection), then record it here.</p> :
        <ul className="space-y-2">{f.inspections.map((i: Any) => <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-paper p-2">
          <span>Inspected {i.conducted_on ?? "—"}{i.attendees ? ` · ${i.attendees}` : ""}{i.notes && <span className="block text-xs text-muted">{i.notes}</span>}
            <span className="block text-xs">{i.report_shared_on ? `Report shared ${i.report_shared_on} by ${i.report_shared_via}` : "Report not yet shared"}</span></span>
          <span className="flex gap-1"><a href={`/inspection-report/${caseId}/${i.id}`} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center rounded-lg px-3 ring-1 ring-line hover:bg-forest-50">Inspection report</a>
            {can && !i.report_shared_on && <Button variant="ghost" onClick={() => setDlg({ mode: "share", id: i.id })}>Report shared</Button>}</span></li>)}</ul>}
      {dlg && <Modal title={dlg.mode === "add" ? "Record a customer inspection" : "Inspection report shared"} onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
          if (dlg.mode === "add") go("/inspections", { conducted_on: v.conducted_on, attendees: v.attendees.trim() || null, notes: v.notes.trim() || null }, "Inspection recorded");
          else go(`/inspections/${dlg.id}`, { report_shared_on: v.report_shared_on, report_shared_via: v.report_shared_via }, "Report sharing recorded", "put");
          setDlg(null); }}>
          {dlg.mode === "add" ? <>
            <TextInput label="Inspected on" type="date" max={today()} value={v.conducted_on} onChange={(e) => setV({ ...v, conducted_on: e.target.value })} />
            <TextInput label="Who attended" value={v.attendees} onChange={(e) => setV({ ...v, attendees: e.target.value })} maxLength={500} placeholder="Customer, CRM, site engineer" />
            <TextArea label="Notes" value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} rows={3} maxLength={5000} />
            <p className="text-xs text-muted">Record each issue as a snag (source: customer) below.</p></> : <div className="grid grid-cols-2 gap-3">
            <TextInput label="Shared on" type="date" max={today()} value={v.report_shared_on} onChange={(e) => setV({ ...v, report_shared_on: e.target.value })} />
            <SelectInput label="Shared by" value={v.report_shared_via} onChange={(e) => setV({ ...v, report_shared_via: e.target.value })}>{["email", "whatsapp", "hand", "other"].map((x) => <option key={x} value={x}>{x}</option>)}</SelectInput></div>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit">Save</Button></div>
        </form></Modal>}
    </section>
  );
}

export function SnagRegister({ f, canInspect, canRespond, go, upload }: { f: Any; canInspect: boolean; canRespond: boolean; go: Go; upload: (sid: number, file: File, kind: string) => Promise<void> }) {
  const [dlg, setDlg] = useState<null | { mode: "add" } | { mode: "fixed" | "reopen" | "dispute"; s: Any }>(null);
  const [v, setV] = useState({ description: "", location: "", category: "other", severity: "minor", source: "internal", owner_id: "", due_on: "", inspection_id: "", note: "" });
  const [photo, setPhoto] = useState<File | null>(null);
  const open = (d: NonNullable<typeof dlg>) => { setV({ description: "", location: "", category: "other", severity: "minor", source: "internal", owner_id: "", due_on: "", inspection_id: "", note: "" }); setPhoto(null); setDlg(d); };
  return (
    <section aria-label="Snag register" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <div className="mb-2 flex items-center justify-between"><h3 className="font-semibold">Snag register</h3>{(canInspect || canRespond) && <Button variant="ghost" onClick={() => open({ mode: "add" })}>Add snag</Button>}</div>
      {f.snags.length === 0 ? <p className="text-xs text-muted">No snags recorded.</p> : <ul className="space-y-2">{f.snags.map((s: Any) => (
        <li key={s.id} className={cx("rounded-lg p-3 ring-1", s.status === "closed" ? "bg-paper ring-line" : s.overdue ? "bg-danger-soft ring-danger/30" : "bg-white ring-line")}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="font-medium">SNG-{String(s.id).padStart(5, "0")} · {s.description} <Badge tone={SEV[s.severity as keyof typeof SEV]}>{s.severity}</Badge> <Badge tone="muted">{s.category}</Badge>{s.source === "customer" && <> <Badge tone="neutral">raised by customer</Badge></>}</p>
              <p className="text-xs text-muted">{s.location ?? "—"} · reported {formatDateTime(s.reported_on)} · {s.owner ?? "—"} · fix by {s.due_on}{s.overdue && <span className="text-danger"> · overdue</span>}</p>
              <p className="text-xs"><b>{STATUS[s.status as keyof typeof STATUS]}</b>{s.rectification && ` · rectification: ${s.rectification}`}{s.verified_at && ` · verified ${formatDateTime(s.verified_at)}`}{s.closed_at && ` · closed ${formatDateTime(s.closed_at)}`}</p>
              {s.customer_response && <p className="text-xs">Customer {s.customer_response}{s.customer_note ? `: ${s.customer_note}` : ""}</p>}
              {s.reopen_reason && <p className="text-xs text-danger">Reopened {s.reopened_count}×: {s.reopen_reason}</p>}
              {s.evidence.length > 0 && <p className="mt-0.5 flex flex-wrap gap-2 text-xs">{s.evidence.map((e: Any) => <a key={e.id} href={e.url} target="_blank" rel="noopener" className="text-forest-800 underline">{e.kind === "completion" ? "Completion" : "Issue"}: {e.file_name}</a>)}</p>}
            </div>
            <div className="flex flex-wrap gap-1">
              {canInspect && s.status === "open" && <Button variant="ghost" onClick={() => { setV({ ...v, note: "" }); setPhoto(null); setDlg({ mode: "fixed", s }); }}>Fixed…</Button>}
              {canInspect && s.status === "fixed" && <Button variant="ghost" onClick={() => go(`/snags/${s.id}`, { status: "verified" }, "Repair verified")}>Verify</Button>}
              {canRespond && s.status === "verified" && <><Button variant="ghost" onClick={() => go(`/snags/${s.id}/customer`, { response: "accepted" }, "Customer accepted the repair")}>Customer accepted</Button>
                <Button variant="ghost" onClick={() => { setV({ ...v, note: "" }); setDlg({ mode: "dispute", s }); }}>Customer disputes</Button></>}
              {canInspect && s.status !== "open" && <Button variant="ghost" onClick={() => { setV({ ...v, note: "" }); setDlg({ mode: "reopen", s }); }}>Reopen</Button>}
            </div>
          </div>
        </li>))}</ul>}
      {dlg && <Modal title={dlg.mode === "add" ? "Add a snag" : dlg.mode === "fixed" ? "Mark fixed" : dlg.mode === "reopen" ? "Reopen the snag" : "Customer disputes the repair"} onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
          if (dlg.mode === "add") go("/snags", { description: v.description.trim(), location: v.location.trim() || null, category: v.category, severity: v.severity, source: v.source,
            owner_id: Number(v.owner_id), due_on: v.due_on, inspection_id: v.inspection_id ? Number(v.inspection_id) : null }, "Snag added");
          else if (dlg.mode === "fixed") { const id = dlg.s.id; const note = v.note.trim();
            void (photo ? upload(id, photo, "completion") : Promise.resolve()).then(() => go(`/snags/${id}`, { status: "fixed", note }, "Marked fixed")); }
          else if (dlg.mode === "reopen") go(`/snags/${dlg.s.id}`, { status: "reopen", note: v.note.trim() }, "Snag reopened");
          else go(`/snags/${dlg.s.id}/customer`, { response: "disputed", note: v.note.trim() }, "Dispute recorded; the snag is open again");
          setDlg(null); }}>
          {dlg.mode === "add" ? <>
            <TextArea label="What needs fixing" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} rows={2} maxLength={2000} />
            <div className="grid grid-cols-2 gap-3">
              <TextInput label="Where in the unit" value={v.location} onChange={(e) => setV({ ...v, location: e.target.value })} maxLength={120} placeholder="e.g. Master bathroom" />
              <SelectInput label="Category" value={v.category} onChange={(e) => setV({ ...v, category: e.target.value })}>{["civil", "electrical", "plumbing", "finishing", "fittings", "other"].map((x) => <option key={x} value={x}>{x}</option>)}</SelectInput>
              <SelectInput label="Severity" value={v.severity} onChange={(e) => setV({ ...v, severity: e.target.value })}><option value="minor">Minor</option><option value="major">Major</option><option value="critical">Critical (safety)</option></SelectInput>
              <SelectInput label="Raised by" value={v.source} onChange={(e) => setV({ ...v, source: e.target.value })}><option value="internal">Our team</option><option value="customer">The customer</option></SelectInput>
              <SelectInput label="Rectification owner" value={v.owner_id} onChange={(e) => setV({ ...v, owner_id: e.target.value })}><option value="">Choose</option>{f.owners.map((u: Any) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</SelectInput>
              <TextInput label="Fix by" type="date" min={today()} value={v.due_on} onChange={(e) => setV({ ...v, due_on: e.target.value })} />
              {f.inspections.length > 0 && <SelectInput label="Found at inspection" value={v.inspection_id} onChange={(e) => setV({ ...v, inspection_id: e.target.value })}><option value="">—</option>
                {f.inspections.map((i: Any) => <option key={i.id} value={i.id}>{i.conducted_on ?? `#${i.id}`}</option>)}</SelectInput>}
            </div>
            <p className="text-xs text-muted">Major and critical snags need a completion photo before they can be marked fixed. Customer snags close when the customer accepts the repair.</p></> : <>
            {dlg.mode === "fixed" && <div className="space-y-1.5"><label htmlFor="snag-photo" className="block text-sm font-medium">Completion photo{dlg.s.severity !== "minor" ? " (required)" : " (optional)"}</label>
              <input id="snag-photo" type="file" accept=".jpg,.jpeg,.png,.pdf" onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" /></div>}
            <TextArea label={dlg.mode === "fixed" ? "Rectification details" : dlg.mode === "reopen" ? "Reason for reopening" : "What does the customer dispute?"} value={v.note} onChange={(e) => setV({ ...v, note: e.target.value })} rows={2} maxLength={1000} /></>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button>
            <Button type="submit" disabled={dlg.mode === "add" ? v.description.trim().length < 3 || !v.owner_id || !v.due_on : v.note.trim().length < 3 || (dlg.mode === "fixed" && dlg.s.severity !== "minor" && !photo && !dlg.s.evidence.some((e: Any) => e.kind === "completion"))}>Save</Button></div>
        </form></Modal>}
    </section>
  );
}

const HANDOVER_FIELDS: [string, string, "check" | "number" | "text"][] = [
  ["identity_verified", "Customer identity verified", "check"], ["authorisation", "Taking possession as (self / power of attorney)", "text"], ["keys_count", "Keys handed over (number)", "number"],
  ["access_cards", "Access cards (number)", "number"], ["remotes", "Remotes (number)", "number"], ["parking", "Parking allocation and access details", "text"],
  ["meter_ids", "Meter identifiers and readings", "text"], ["utilities", "Utility transfer or activation", "text"], ["fm_contacts", "Maintenance and facility-management contacts", "text"],
  ["emergency_contacts", "Emergency contacts given", "text"], ["manuals_given", "Warranty and operating manuals given", "check"], ["house_rules_given", "House rules and maintenance instructions given", "check"],
  ["photos_note", "Photographs or evidence (note)", "text"], ["customer_acknowledged", "Customer acknowledged the handover", "check"],
];

export function Handover({ f, can, go }: { f: Any; can: boolean; go: Go }) {
  const [h, setH] = useState<Record<string, Any>>(f.handover ?? {});
  const [date, setDate] = useState(today());
  const done = !!f.handover_completed_at;
  const missing = ["identity_verified", "customer_acknowledged", "keys_count", "signed_checklist_document_id"].filter((k) => !h[k]);
  return (
    <section aria-label="Possession handover" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <h3 className="mb-2 font-semibold">Possession handover{done && <> <Badge tone="neutral">Completed {f.actual_possession_on}</Badge></>}</h3>
      {!done && !f.gate.open && <Alert>The handover can be completed once the possession gate is open and the appointment is scheduled. You can fill the checklist now.</Alert>}
      <fieldset disabled={!can || done} className="mt-2 grid gap-2 sm:grid-cols-2">
        {HANDOVER_FIELDS.map(([k, l, t]) => t === "check"
          ? <label key={k} className="flex min-h-9 items-center gap-2"><input type="checkbox" className="size-4 accent-forest-900" checked={!!h[k]} onChange={(e) => setH({ ...h, [k]: e.target.checked })} />{l}</label>
          : <TextInput key={k} label={l} type={t === "number" ? "number" : "text"} min={0} value={h[k] ?? ""} onChange={(e) => setH({ ...h, [k]: t === "number" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value })} />)}
        <SelectInput label="Signed handover checklist (from 09 Possession & Handover)" value={h.signed_checklist_document_id ?? ""} onChange={(e) => setH({ ...h, signed_checklist_document_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">Choose the uploaded document</option>{f.possession_documents.map((d: Any) => <option key={d.id} value={d.id}>{d.title}</option>)}</SelectInput>
      </fieldset>
      {can && !done && <div className="mt-3 flex flex-wrap items-end gap-2">
        <Button variant="secondary" onClick={() => go("/handover", { items: h }, "Handover checklist saved", "put")}>Save checklist</Button>
        <div className="w-44"><TextInput label="Actual possession date" type="date" max={today()} value={date} onChange={(e) => setDate(e.target.value)} /></div>
        <Button disabled={missing.length > 0 || !f.gate.open} onClick={() => go("/handover/complete", { actual_possession_on: date }, "Handover completed")}>Complete handover</Button>
        {missing.length > 0 && <span className="text-xs text-muted">Save the checklist with identity, keys, acknowledgement and the signed checklist first.</span>}
      </div>}
    </section>
  );
}
