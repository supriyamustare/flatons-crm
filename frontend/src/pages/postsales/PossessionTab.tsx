import { useState } from "react";
import type { FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, ShieldAlert, X } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { inr } from "../../hooks/useLedger";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const CONDITIONS = { legal: "Legal and statutory readiness", documents: "Possession documents", finance: "Finance clearance", readiness: "Unit readiness approved",
  internal: "Internal approval (CRM manager)", communication: "Customer informed (possession letter released)" } as const;

function Mark({ ok, excepted }: { ok: boolean; excepted?: boolean }) {
  if (ok) return <Check className="size-4 shrink-0 text-forest-700" aria-label="met" />;
  if (excepted) return <ShieldAlert className="size-4 shrink-0 text-gold-700" aria-label="covered by an exception" />;
  return <X className="size-4 shrink-0 text-danger" aria-label="not yet" />;
}

export function PossessionTab({ caseId }: { caseId: number }) {
  const key = ["possession", caseId];
  const q = useQuery({ queryKey: key, queryFn: async () => (await api.get<Any>(`/post-sales/cases/${caseId}/possession`)).data });
  const qc = useQueryClient(); const toast = useToast();
  const act = useMutation({
    mutationFn: async ({ path, body, method = "post" }: { path: string; body?: unknown; method?: "post" | "put" }) =>
      (method === "put" ? await api.put(`/post-sales/cases/${caseId}/possession${path}`, body) : await api.post(`/post-sales/cases/${caseId}/possession${path}`, body)).data,
    onSuccess: (d) => qc.setQueryData(key, d),
  });
  const [dlg, setDlg] = useState<null | "start" | "exception" | "clear" | "return" | "snag" | "doc_na" | "issue">(null);
  const [item, setItem] = useState("");
  const [text, setText] = useState(""); const [scope, setScope] = useState<string[]>([]);
  const [snag, setSnag] = useState({ description: "", location: "", owner_id: "", due_on: "" });
  const go = (path: string, body: unknown, msg: string, method: "post" | "put" = "post") => act.mutate({ path, body, method }, { onSuccess: () => { toast(msg); setDlg(null); setText(""); } });
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const s = q.data; const f = s.file;
  if (!f) return (
    <section role="tabpanel" aria-label="Possession" className="space-y-3 rounded-xl bg-white p-4 text-sm ring-1 ring-line">
      <p>Pre-possession starts once the project’s <b>{s.trigger ?? "possession"}</b> milestone is verified: {s.trigger_reached ? <Badge tone="neutral">Verified</Badge> : <Badge tone="gold">Not yet</Badge>}</p>
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {s.can_start && <Button onClick={() => (s.trigger_reached ? go("/start", {}, "Pre-possession file opened") : setDlg("start"))}>Start pre-possession</Button>}
      {dlg === "start" && <Modal title="Start before the milestone" onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); go("/start", { reason: text.trim() }, "Pre-possession file opened"); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          <p className="text-sm">The {s.trigger} milestone isn’t verified yet. Only an admin can start early, with a reason.</p>
          <TextArea label="Reason" value={text} onChange={(e) => setText(e.target.value)} rows={2} maxLength={500} />
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={text.trim().length < 10}>Start</Button></div>
        </form></Modal>}
    </section>
  );
  const fin = f.financial; const can = f.can; const g = f.gate;
  const setDoc = (item: string, status: string, note?: string) => go("/documents", { items: [{ item, status, note: note || null }] }, "Document checklist updated", "put");
  const setReady = (item: string, status: string, note?: string) => go("/readiness", { items: [{ item, status, note: note || null }] }, "Inspection updated", "put");
  return (
    <section role="tabpanel" aria-label="Possession" className="space-y-4">
      {act.isError && !dlg && <Alert>{errorMessage(act.error)}</Alert>}
      <section aria-label="Possession gate" className={cx("rounded-xl p-4 ring-1", g.open ? "bg-forest-50 ring-forest-100" : "bg-white ring-line")}>
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">Possession gate: {g.open ? "possession can be scheduled" : "not yet"}</h3>
          {can.exception && <Button variant="ghost" onClick={() => { setScope(g.conditions.filter((c: Any) => !c.met).map((c: Any) => c.key)); setText(""); setDlg("exception"); }}>Record exception…</Button>}</div>
        <ul className="mt-2 grid gap-1.5 text-sm sm:grid-cols-2">{g.conditions.map((c: Any) => <li key={c.key} className="flex items-start gap-2"><Mark ok={c.met} excepted={c.excepted} />
          <span>{c.label}{c.excepted && <span className="text-xs text-muted"> (exception)</span>}{c.key === "legal" && g.detail.legal && <span className="block text-xs text-muted">{g.detail.legal}</span>}</span></li>)}</ul>
        {f.exception && <p className="mt-2 text-xs">Exception by <b>{f.exception.by_name}</b>, {formatDateTime(f.exception.at)}: {f.exception.reason}. Covers: {f.exception.scope.map((k: keyof typeof CONDITIONS) => CONDITIONS[k]).join(", ")}.</p>}
        {g.open && <p className="mt-2 text-xs">Schedule it under <b>Appointments → Schedule → Possession handover</b>.</p>}
      </section>

      <section aria-label="Financial checklist" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <h3 className="mb-2 font-semibold">A. Finance</h3>
        {!fin.has_ledger ? <p className="text-muted">No ledger yet.</p> : <>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">{([["Total payable", inr(fin.total_payable)], ["Received", inr(fin.received)], ["Outstanding", inr(fin.outstanding)], ["Overdue", inr(fin.overdue)],
            ["Demanded, not yet due", inr(fin.demanded_not_yet_due)], ["Other charges outstanding", inr(fin.other_charges_outstanding)], ["Unallocated payments", inr(fin.unallocated)], ["Loan not yet disbursed", inr(fin.loan_not_disbursed)]] as const)
            .map(([l, v]) => <div key={l} className="rounded-lg bg-paper p-2"><dt className="text-xs text-muted">{l}</dt><dd className="font-semibold tabular-nums">{v}</dd></div>)}</dl>
          <ul className="mt-3 space-y-1">
            <li className="flex gap-2"><Mark ok={fin.final_demand_raised} />Final contractual demand raised{fin.not_yet_demanded.length > 0 && <span className="text-xs text-muted"> (not yet demanded: {fin.not_yet_demanded.join(", ")})</span>}</li>
            <li className="flex gap-2"><Mark ok={fin.unconfirmed_receipts === 0} />All receipts confirmed{fin.unconfirmed_receipts > 0 && <span className="text-xs text-muted"> ({fin.unconfirmed_receipts} waiting, {inr(fin.pending_amount)})</span>}</li>
            <li className="flex gap-2"><Mark ok={fin.open_disputes.length === 0} />No open payment disputes{fin.open_disputes.length > 0 && <span className="text-xs text-muted"> ({fin.open_disputes.join(", ")})</span>}</li>
            <li className="flex gap-2"><Mark ok={!!f.finance.taxes_confirmed} />Taxes, deposits and statutory amounts confirmed</li>
            <li className="flex gap-2"><Mark ok={!!f.finance.payment_confirmed} />Payment confirmation recorded</li>
          </ul>
          {can.finance && !f.clearance.cleared_at && <form className="mt-3 grid gap-2 sm:grid-cols-2" onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const fd = new FormData(e.currentTarget);
            go("/finance", { charges_note: String(fd.get("charges") || "") || null, adjustments_note: String(fd.get("adj") || "") || null, taxes_confirmed: fd.get("taxes") === "on", payment_confirmed: fd.get("paid") === "on" }, "Finance checklist saved", "put"); }}>
            <TextInput label="Authorised charges added" name="charges" defaultValue={f.finance.charges_note ?? ""} maxLength={1000} />
            <TextInput label="Credits, waivers, adjustments applied" name="adj" defaultValue={f.finance.adjustments_note ?? ""} maxLength={1000} />
            <label className="flex min-h-9 items-center gap-2"><input type="checkbox" name="taxes" defaultChecked={!!f.finance.taxes_confirmed} className="size-4 accent-forest-900" />Taxes, deposits and statutory amounts confirmed</label>
            <label className="flex min-h-9 items-center gap-2"><input type="checkbox" name="paid" defaultChecked={!!f.finance.payment_confirmed} className="size-4 accent-forest-900" />Payment confirmation recorded</label>
            <div className="sm:col-span-2 flex flex-wrap gap-2"><Button type="submit" variant="secondary" loading={act.isPending}>Save</Button>
              {can.request_clearance && <Button type="button" onClick={() => go("/finance/request-clearance", undefined, "Clearance requested from a finance approver")}>Request finance clearance</Button>}</div>
          </form>}
          <p className="mt-2 text-xs">{f.clearance.cleared_at ? <>Cleared by <b>{f.clearance.cleared_by}</b>, {formatDateTime(f.clearance.cleared_at)}{f.clearance.note ? `: ${f.clearance.note}` : ""}</>
            : f.clearance.requested_at ? <>Clearance requested by {f.clearance.requested_by}, {formatDateTime(f.clearance.requested_at)} (outstanding then {inr(f.clearance.snapshot.outstanding)})</>
            : f.clearance.returned_reason ? <span className="text-danger">Clearance returned: {f.clearance.returned_reason}</span> : "Finance clearance not yet requested."}</p>
          {can.clear && <div className="mt-2 flex gap-2"><Button onClick={() => { setText(""); setDlg("clear"); }}>Give finance clearance</Button><Button variant="secondary" onClick={() => { setText(""); setDlg("return"); }}>Return</Button></div>}
        </>}
      </section>

      <section aria-label="Document checklist" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <h3 className="mb-2 font-semibold">B. Documents</h3>
        <ul className="divide-y divide-line">{f.documents.map((d: Any) => <li key={d.item} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
          <span className="flex items-start gap-2">{d.status === "not_applicable" ? <Minus className="size-4 text-muted" aria-label="not applicable" /> : <Mark ok={d.status === "available"} />}
            <span>{d.item}{d.note && <span className="block text-xs text-muted">{d.note}</span>}</span></span>
          {can.documents && <span className="flex gap-1">{d.status !== "available" && <Button variant="ghost" onClick={() => setDoc(d.item, "available")}>Available</Button>}
            {d.status !== "not_applicable" && <Button variant="ghost" onClick={() => { setItem(d.item); setText(""); setDlg("doc_na"); }}>Not applicable</Button>}
            {d.status !== "pending" && <Button variant="ghost" onClick={() => setDoc(d.item, "pending")}>Pending</Button>}</span>}
        </li>)}</ul>
      </section>

      <section aria-label="Unit readiness" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">C. Unit readiness</h3>
          {f.readiness_approved_at ? <Badge tone="neutral">Approved by {f.readiness_approved_by}</Badge> : can.approve_readiness && <Button disabled={f.readiness_blockers.length > 0} onClick={() => go("/readiness/approve", undefined, "Unit readiness approved")}>Approve readiness</Button>}</div>
        {!f.readiness_approved_at && f.readiness_blockers.length > 0 && <p className="mb-2 text-xs text-muted">Before approval: {f.readiness_blockers.join("; ")}.</p>}
        <ul className="divide-y divide-line">{f.readiness.map((r: Any) => <li key={r.item} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
          <span className="flex items-start gap-2"><Mark ok={r.status === "ok"} /><span>{r.item}{r.note && <span className="block text-xs text-danger">{r.note}</span>}</span></span>
          {can.inspect && !f.readiness_approved_at && <span className="flex gap-1">{r.status !== "ok" && <Button variant="ghost" onClick={() => setReady(r.item, "ok")}>OK</Button>}
            {r.status !== "issue" && <Button variant="ghost" onClick={() => { setItem(r.item); setText(""); setDlg("issue"); }}>Issue</Button>}</span>}
        </li>)}</ul>
        {can.inspect && !f.readiness_approved_at && <form className="mt-3 grid max-w-md grid-cols-2 gap-2" onSubmit={(e: FormEvent<HTMLFormElement>) => { e.preventDefault(); const fd = new FormData(e.currentTarget);
          go("/readiness", { items: [], meters: { Electricity: String(fd.get("el") || ""), Water: String(fd.get("wa") || "") } }, "Meter readings saved", "put"); }}>
          <TextInput label="Electricity meter reading" name="el" defaultValue={f.meters.Electricity ?? ""} maxLength={60} />
          <TextInput label="Water meter reading" name="wa" defaultValue={f.meters.Water ?? ""} maxLength={60} />
          <Button type="submit" variant="secondary" className="col-span-2 justify-self-start">Save readings</Button></form>}
        {!can.inspect && Object.keys(f.meters).length > 0 && <p className="mt-2 text-xs">Meters: {Object.entries(f.meters).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>}
        <div className="mt-4 flex items-center justify-between"><h4 className="font-medium">Snag list</h4>{can.inspect && <Button variant="ghost" onClick={() => { setSnag({ description: "", location: "", owner_id: "", due_on: "" }); setDlg("snag"); }}>Add snag</Button>}</div>
        <ul className="mt-1 space-y-1.5">{f.snags.map((x: Any) => <li key={x.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-paper p-2">
          <span>{x.description}{x.location ? ` (${x.location})` : ""}<span className="block text-xs text-muted">{x.owner ?? "—"} · due {x.due_on}{x.overdue && <span className="text-danger"> · overdue</span>}{x.note ? ` · ${x.note}` : ""}</span></span>
          <span className="flex items-center gap-1"><Badge tone={x.status === "verified" ? "neutral" : x.status === "fixed" ? "muted" : "gold"}>{x.status === "open" ? "Open" : x.status === "fixed" ? "Fixed" : "Verified"}</Badge>
            {can.inspect && x.status === "open" && <Button variant="ghost" onClick={() => go(`/snags/${x.id}`, { status: "fixed" }, "Marked fixed")}>Fixed</Button>}
            {can.inspect && x.status === "fixed" && <Button variant="ghost" onClick={() => go(`/snags/${x.id}`, { status: "verified" }, "Snag verified")}>Verify</Button>}</span></li>)}
          {f.snags.length === 0 && <li className="text-xs text-muted">No snags recorded.</li>}</ul>
        <p className="mt-2 text-xs text-muted">Inspection evidence: {f.evidence_count} file(s) in Documents → 09 Possession &amp; Handover.</p>
      </section>

      <section aria-label="Internal approval" className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <span>Internal approval: {f.internal_approved_at ? <b>{f.internal_approved_by}, {formatDateTime(f.internal_approved_at)}</b> : "not yet"}</span>
        {can.internal && <Button variant="secondary" onClick={() => go("/internal-approval", undefined, "Internal approval recorded")}>Give internal approval</Button>}
      </section>

      {dlg && dlg !== "start" && <Modal title={{ exception: "Record an exception", clear: "Give finance clearance", return: "Return the clearance request", snag: "Add a snag", doc_na: `Not applicable: ${item}`, issue: `Issue: ${item}` }[dlg]} onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
          if (dlg === "exception") go("/exception", { reason: text.trim(), scope }, "Exception recorded");
          if (dlg === "clear") go("/finance/clear", { note: text.trim() || null }, "Finance clearance given");
          if (dlg === "return") go("/finance/return", { reason: text.trim() }, "Returned to finance");
          if (dlg === "doc_na") setDoc(item, "not_applicable", text.trim());
          if (dlg === "issue") setReady(item, "issue", text.trim());
          if (dlg === "snag") go("/snags", { description: snag.description.trim(), location: snag.location.trim() || null, owner_id: Number(snag.owner_id), due_on: snag.due_on }, "Snag added"); }}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          {dlg === "exception" && <fieldset className="space-y-1 text-sm"><legend className="mb-1 font-medium">Conditions this exception covers</legend>
            {Object.entries(CONDITIONS).map(([k, l]) => <label key={k} className="flex min-h-8 items-center gap-2"><input type="checkbox" className="size-4 accent-forest-900" checked={scope.includes(k)}
              onChange={() => setScope(scope.includes(k) ? scope.filter((x) => x !== k) : [...scope, k])} />{l}</label>)}</fieldset>}
          {dlg === "clear" && fin.outstanding > 0 && <p className="text-sm">{inr(f.clearance.snapshot?.outstanding ?? fin.outstanding)} is still outstanding: explain why clearance is given.</p>}
          {dlg === "snag" ? <>
            <TextArea label="What needs fixing" value={snag.description} onChange={(e) => setSnag({ ...snag, description: e.target.value })} rows={2} maxLength={2000} />
            <div className="grid grid-cols-2 gap-3">
              <TextInput label="Where" value={snag.location} onChange={(e) => setSnag({ ...snag, location: e.target.value })} maxLength={120} />
              <TextInput label="Fix by" type="date" min={today()} value={snag.due_on} onChange={(e) => setSnag({ ...snag, due_on: e.target.value })} />
              <SelectInput label="Rectification owner" value={snag.owner_id} onChange={(e) => setSnag({ ...snag, owner_id: e.target.value })}><option value="">Choose</option>
                {f.owners.map((u: Any) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</SelectInput>
            </div></> : <TextArea label={dlg === "exception" ? "Reason (who approved it and why)" : dlg === "return" ? "What needs correcting?" : dlg === "doc_na" ? "Why doesn’t it apply?" : dlg === "issue" ? "What’s the issue?" : "Note"} value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={1000} />}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button>
            <Button type="submit" loading={act.isPending} disabled={dlg === "exception" ? text.trim().length < 10 || scope.length === 0 : dlg === "return" || dlg === "doc_na" || dlg === "issue" ? text.trim().length < 3 : dlg === "snag" ? snag.description.trim().length < 3 || !snag.owner_id || !snag.due_on : false}>Save</Button></div>
        </form></Modal>}
    </section>
  );
}
