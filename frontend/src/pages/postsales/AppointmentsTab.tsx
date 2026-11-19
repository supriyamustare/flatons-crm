import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { STATUS, fmtDay, fmtTime, istIso, useAptAction, useCaseApts } from "../../hooks/useAppointments";
import type { Apt, CaseApts } from "../../hooks/useAppointments";
import { errorMessage } from "../../lib/api";

const isClash = (e: unknown) => (e as { response?: { status?: number } })?.response?.status === 409;
const nowLocal = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 16);

function ScheduleDialog({ d, caseId, onClose }: { d: CaseApts; caseId: number; onClose: () => void }) {
  const act = useAptAction(caseId); const toast = useToast();
  const [f, setF] = useState({ kind: "inspection", title: "", when: "", duration_min: "60", location: "", owner_id: "", required_docs: "", notes: "" });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const send = (allow_clash = false) => act.mutate({ path: `/post-sales/cases/${caseId}/appointments`, body: { kind: f.kind, title: f.title.trim() || null, starts_at: istIso(f.when),
    duration_min: Number(f.duration_min), location: f.location.trim() || null, owner_id: f.owner_id ? Number(f.owner_id) : null, required_docs: f.required_docs.trim() || null,
    notes: f.notes.trim() || null, allow_clash } }, { onSuccess: () => { toast(`${d.kinds[f.kind]} scheduled`); onClose(); } });
  return (
    <Modal title="Schedule an appointment" onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); send(); }}>
        {act.isError && <Alert>{errorMessage(act.error)}{isClash(act.error) && <> <button type="button" className="font-semibold underline" onClick={() => send(true)}>Book anyway</button></>}</Alert>}
        <div className="grid grid-cols-2 gap-3">
          <SelectInput label="Kind" value={f.kind} onChange={set("kind")}>{Object.entries(d.kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</SelectInput>
          <TextInput label="When" type="datetime-local" min={nowLocal()} value={f.when} onChange={set("when")} />
          <SelectInput label="Duration" value={f.duration_min} onChange={set("duration_min")}>{[["30", "30 min"], ["60", "1 hour"], ["90", "1½ hours"], ["120", "2 hours"], ["180", "3 hours"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectInput>
          <SelectInput label="Owner" value={f.owner_id} onChange={set("owner_id")} hint="Defaults to the case owner"><option value="">Case owner</option>{d.owners.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</SelectInput>
        </div>
        <TextInput label="Location" value={f.location} onChange={set("location")} maxLength={300} placeholder="e.g. Habitat site office, Kharadi" />
        <TextArea label="Documents to bring" value={f.required_docs} onChange={set("required_docs")} rows={2} maxLength={2000} placeholder="e.g. Original PAN and Aadhaar, two photographs" />
        <TextArea label="Notes (optional)" value={f.notes} onChange={set("notes")} rows={2} maxLength={2000} />
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={!f.when}>Schedule</Button></div>
      </form>
    </Modal>
  );
}

function AptCard({ a, caseId }: { a: Apt; caseId: number }) {
  const act = useAptAction(caseId); const toast = useToast();
  const [open, setOpen] = useState<null | "confirm" | "reschedule" | "cancel" | "attendance">(null);
  const [f, setF] = useState({ via: "call", when: "", reason: "", attended: "yes", outcome: "" });
  const go = (path: string, body: unknown, msg: string) => act.mutate({ path, body }, { onSuccess: () => { toast(msg); setOpen(null); } });
  const past = new Date(a.starts_at).getTime() <= Date.now();
  const tone = a.status === "no_show" ? "gold" : a.status === "scheduled" ? (a.confirmed_on ? "neutral" : "gold") : "muted";
  return (
    <li className={cx("rounded-xl bg-white p-4 ring-1 ring-line", ["cancelled", "rescheduled"].includes(a.status) && "opacity-70")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-semibold">{a.label}{a.title ? `: ${a.title}` : ""} <span className="font-normal text-muted">({a.apt_no})</span></p>
          <p className="text-sm">{fmtDay(a.starts_at)}, {fmtTime(a.starts_at)} · {a.duration_min} min{a.location ? ` · ${a.location}` : ""}</p>
          <p className="mt-0.5 flex flex-wrap gap-1"><Badge tone={tone as "neutral" | "gold" | "muted"}>{a.status === "scheduled" ? (a.confirmed_on ? `Confirmed by ${a.confirmed_via}` : "Not yet confirmed") : STATUS[a.status]}</Badge>
            {a.owner && <span className="text-xs text-muted">Owner: {a.owner.full_name}</span>}{a.rescheduled_from && <span className="text-xs text-muted">· replaces {a.rescheduled_from}</span>}</p>
          {a.required_docs && <p className="mt-1 text-xs">Bring: {a.required_docs}</p>}
          {a.status_reason && <p className="mt-1 text-xs text-muted">{STATUS[a.status]}: {a.status_reason}</p>}
          {a.outcome && <p className="mt-1 text-xs">Outcome: {a.outcome}</p>}
          {a.status === "no_show" && a.follow_up_on && <p className="mt-1 text-xs text-danger">Follow up on {a.follow_up_on} and reschedule</p>}
        </div>
        {a.can_act && <div className="flex flex-wrap gap-1.5">
          {a.status === "scheduled" && !a.confirmed_on && <Button variant="secondary" onClick={() => setOpen("confirm")}>Customer confirmed</Button>}
          {a.status === "scheduled" && past && <Button onClick={() => setOpen("attendance")}>Record attendance</Button>}
          <Button variant="ghost" onClick={() => setOpen("reschedule")}>Reschedule</Button>
          {a.status === "scheduled" && <Button variant="ghost" onClick={() => setOpen("cancel")}>Cancel</Button>}
        </div>}
      </div>
      {open && <Modal title={{ confirm: "Customer confirmed", reschedule: "Reschedule", cancel: "Cancel the appointment", attendance: "Record attendance" }[open]} onClose={() => setOpen(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
          if (open === "confirm") go(`/appointments/${a.id}/confirm`, { via: f.via }, "Confirmation recorded");
          if (open === "cancel") go(`/appointments/${a.id}/cancel`, { reason: f.reason.trim() }, "Appointment cancelled");
          if (open === "reschedule") go(`/appointments/${a.id}/reschedule`, { starts_at: istIso(f.when), reason: f.reason.trim() }, "Appointment rescheduled");
          if (open === "attendance") go(`/appointments/${a.id}/attendance`, { attended: f.attended === "yes", outcome: f.outcome.trim() || null }, f.attended === "yes" ? "Attendance recorded" : "Marked as missed; a follow-up is set for tomorrow"); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          {open === "confirm" && <SelectInput label="Confirmed by" value={f.via} onChange={(e) => setF({ ...f, via: e.target.value })}>{[["call", "Phone call"], ["whatsapp", "WhatsApp"], ["email", "Email"], ["sms", "SMS"], ["in_person", "In person"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectInput>}
          {open === "reschedule" && <TextInput label="New date and time" type="datetime-local" min={nowLocal()} value={f.when} onChange={(e) => setF({ ...f, when: e.target.value })} />}
          {(open === "reschedule" || open === "cancel") && <TextArea label="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} rows={2} maxLength={500} />}
          {open === "attendance" && <>
            <fieldset className="flex gap-4 text-sm"><legend className="mb-1 font-medium">Did the customer attend?</legend>
              {[["yes", "Attended"], ["no", "Didn’t come"]].map(([v, l]) => <label key={v} className="flex min-h-9 items-center gap-2"><input type="radio" name="att" value={v} checked={f.attended === v} onChange={() => setF({ ...f, attended: v })} className="accent-forest-900" />{l}</label>)}</fieldset>
            <TextArea label={f.attended === "yes" ? "Outcome" : "Note (optional)"} value={f.outcome} onChange={(e) => setF({ ...f, outcome: e.target.value })} rows={3} maxLength={2000} />
            {f.attended === "no" && <p className="text-xs text-muted">A follow-up will be set for tomorrow, until it’s rescheduled.</p>}
          </>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(null)}>Back</Button>
            <Button type="submit" loading={act.isPending} disabled={(open === "reschedule" && (!f.when || f.reason.trim().length < 3)) || (open === "cancel" && f.reason.trim().length < 3) || (open === "attendance" && f.attended === "yes" && !f.outcome.trim())}>Save</Button></div>
        </form></Modal>}
    </li>
  );
}

export function AppointmentsTab({ caseId }: { caseId: number }) {
  const q = useCaseApts(caseId); const [open, setOpen] = useState(false);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const d = q.data;
  return (
    <section role="tabpanel" aria-label="Appointments" className="space-y-3">
      {d.can_schedule && <div className="flex justify-end"><Button onClick={() => setOpen(true)}><Plus className="size-4" aria-hidden />Schedule</Button></div>}
      {d.items.length === 0 ? <p className="rounded-xl border border-dashed border-line bg-white px-6 py-8 text-center text-sm text-muted">No appointments yet.</p>
        : <ul className="space-y-3">{d.items.map((a) => <AptCard key={a.id} a={a} caseId={caseId} />)}</ul>}
      {open && <ScheduleDialog d={d} caseId={caseId} onClose={() => setOpen(false)} />}
    </section>
  );
}
