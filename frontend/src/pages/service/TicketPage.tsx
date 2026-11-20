import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, Lock, Paperclip } from "lucide-react";
import { Alert, Badge, Button, ErrorState, Modal, SelectInput, TextArea, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { CLOSURE, STATUS, slaBadge, useTicket, useTicketAction } from "../../hooks/useTickets";
import { errorMessage, formatDateTime } from "../../lib/api";

type Dlg = null | "ack" | "wait" | "note" | "message" | "propose" | "confirm" | "close" | "reopen" | "assign" | "attach";
const KIND: Record<string, string> = { escalated: "Escalated", raised: "Raised", status: "Status", note: "Internal note", message_in: "From the customer", message_out: "To the customer", assigned: "Assigned",
  attachment: "Attachment", resolution: "Resolution proposed", confirmed: "Customer confirmed", not_confirmed: "Customer not satisfied", closed: "Closed", reopened: "Reopened" };

export function TicketPage() {
  const id = Number(useParams().ticketId);
  const q = useTicket(id); const act = useTicketAction(id); const toast = useToast();
  const [dlg, setDlg] = useState<Dlg>(null);
  const [f, setF] = useState({ text: "", status: "waiting_customer", direction: "out", channel: "phone", confirmed: "yes", csat: "5", reason: "resolved", owner: "", purpose: "evidence" });
  const [file, setFile] = useState<File | null>(null);
  if (q.isPending) return <div className="h-64 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <ErrorState message={errorMessage(q.error, "Couldn’t load this ticket.")} onRetry={() => void q.refetch()} />;
  const t = q.data; const can = t.can; const s = t.sla; const closed = t.status === "closed"; const b = slaBadge(s, closed);
  const open = (d: Dlg, preset: Partial<typeof f> = {}) => { act.reset(); setF({ ...f, text: "", ...preset }); setFile(null); setDlg(d); };
  const go = (path: string, body: unknown, msg: string) => act.mutate({ path, body }, { onSuccess: () => { toast(msg); setDlg(null); } });
  const submit = (e: FormEvent) => {
    e.preventDefault(); const text = f.text.trim();
    if (dlg === "ack") go("/acknowledge", { text }, "Acknowledged: first response recorded");
    if (dlg === "wait") go("/status", { status: f.status, note: text || null }, f.status === "in_progress" ? "Back in progress" : "Marked as waiting");
    if (dlg === "note") go("/notes", { text }, "Internal note added");
    if (dlg === "message") go("/messages", { text, direction: f.direction, channel: f.channel }, "Added to the customer log");
    if (dlg === "propose") go("/propose", { text }, "Resolution proposed");
    if (dlg === "confirm") go("/confirmation", { confirmed: f.confirmed === "yes", csat: f.confirmed === "yes" ? Number(f.csat) : null, comment: text || null }, f.confirmed === "yes" ? "Customer confirmation recorded" : "Back in progress");
    if (dlg === "close") go("/close", { closure_reason: f.reason, note: text || null }, "Ticket closed");
    if (dlg === "reopen") go("/reopen", { reason: text }, "Ticket reopened");
    if (dlg === "assign") go("/assign", { owner_id: Number(f.owner) }, "Ticket assigned");
    if (dlg === "attach" && file) { const fd = new FormData(); fd.append("file", file); fd.append("purpose", f.purpose); go("/attachments", fd, "File attached"); }
  };
  const needText = ["ack", "note", "message", "propose", "reopen"].includes(dlg ?? "") || (dlg === "wait" && f.status !== "in_progress") || (dlg === "confirm" && f.confirmed === "no") || (dlg === "close" && f.reason !== "resolved");
  const ok = (!needText || f.text.trim().length >= (dlg === "reopen" ? 3 : 2)) && (dlg !== "assign" || !!f.owner) && (dlg !== "attach" || !!file);
  return (
    <div className="space-y-4">
      <Link to="/service" className="inline-flex items-center gap-1 text-sm text-forest-800 hover:underline"><ArrowLeft className="size-4" aria-hidden />All tickets</Link>
      <div>
        <h1 className="font-display text-2xl text-forest-900">{t.ticket_no}: {t.title}</h1>
        <p className="text-sm text-muted"><Link to={`/post-sales/${t.case_id}`} className="underline">{t.customer} ({t.case_code})</Link> · unit {t.unit} · {t.category_label}{t.subcategory ? ` / ${t.subcategory}` : ""} · via {t.channel}</p>
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-sm"><Badge tone={closed ? "muted" : "neutral"}>{STATUS[t.status]}</Badge><Badge tone={t.priority === "urgent" || t.priority === "high" ? "gold" : "muted"}>{t.priority}</Badge>
          {b && <Badge tone={b.tone}>{b.text}</Badge>}<span className="text-muted">{t.team_label} · owner {t.owner?.full_name ?? "unassigned"}</span>{t.reopened_count > 0 && <span className="text-muted">· reopened {t.reopened_count}×</span>}</p>
      </div>
      <section aria-label="Service level" className="grid gap-2 rounded-xl bg-white p-4 text-sm ring-1 ring-line sm:grid-cols-4">
        <div><p className="text-xs text-muted">First response due</p><p className={cx(s.response_breached && "text-danger")}>{formatDateTime(s.response_due_at)}</p>
          <p className="text-xs">{s.first_response_at ? `Responded ${formatDateTime(s.first_response_at)}` : "Not yet responded"}</p></div>
        <div><p className="text-xs text-muted">Resolution due</p><p className={cx(s.resolution_breached && "text-danger")}>{formatDateTime(s.resolution_due_at)}</p>{s.paused && <p className="text-xs">Paused while waiting</p>}</div>
        <div><p className="text-xs text-muted">Time paused</p><p>Customer {s.paused_hours_customer} h · third party {s.paused_hours_external} h</p></div>
        <div><p className="text-xs text-muted">Satisfaction</p><p>{t.csat ? `${t.csat} / 5` : "—"}{t.closure_reason ? ` · closed: ${CLOSURE[t.closure_reason]}` : ""}</p></div>
      </section>
      {act.isError && !dlg && <Alert>{errorMessage(act.error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        {can.assign && <Button variant="secondary" onClick={() => open("assign", { owner: String(t.owner?.id ?? "") })}>{t.owner ? "Reassign" : "Assign"}</Button>}
        {can.acknowledge && <Button onClick={() => open("ack")}>Acknowledge (first response)</Button>}
        {can.work && <Button variant="secondary" onClick={() => open("wait", { status: t.status === "in_progress" ? "waiting_customer" : "in_progress" })}>Change status</Button>}
        {can.propose && <Button onClick={() => open("propose")}>Propose resolution</Button>}
        {can.confirm && <Button onClick={() => open("confirm")}>Customer response</Button>}
        {can.message && <Button variant="ghost" onClick={() => open("message")}>Log customer message</Button>}
        {can.note && <Button variant="ghost" onClick={() => open("note")}><Lock className="size-4" aria-hidden />Internal note</Button>}
        {can.note && <Button variant="ghost" onClick={() => open("attach")}><Paperclip className="size-4" aria-hidden />Attach</Button>}
        {can.close && <Button variant="ghost" onClick={() => open("close", { reason: t.status === "resolution_proposed" ? "resolved" : "duplicate" })}>Close…</Button>}
        {can.reopen && <Button variant="secondary" onClick={() => open("reopen")}>Reopen</Button>}
      </div>
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <section aria-label="Timeline" className="rounded-xl bg-white p-4 ring-1 ring-line">
          <h2 className="mb-2 font-semibold">Timeline</h2>
          <ol className="space-y-3">{t.timeline.map((e) => (
            <li key={e.id} className={cx("rounded-lg p-3 text-sm", e.internal ? "bg-gold-100/50 ring-1 ring-gold-300" : "bg-paper")}>
              <p className="text-xs text-muted">{e.internal && <><Lock className="mr-1 inline size-3" aria-hidden /><b>Internal</b> · </>}{KIND[e.kind] ?? e.kind}
                {e.kind === "status" && e.data ? `: ${STATUS[String(e.data.to)] ?? e.data.to}` : ""}{e.kind === "closed" && e.data ? `: ${CLOSURE[String(e.data.reason)]}` : ""}
                {typeof e.data?.channel === "string" ? ` (${e.data.channel})` : ""}{typeof e.data?.csat === "number" ? ` · ${e.data.csat}/5` : ""} · {e.by?.full_name ?? "System"}, {formatDateTime(e.at)}</p>
              {e.text && <p className="mt-1 whitespace-pre-wrap">{e.text}</p>}
            </li>))}</ol>
        </section>
        <aside className="space-y-3">
          <section aria-label="Description" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h2 className="mb-1 font-semibold">Customer’s issue</h2><p className="whitespace-pre-wrap">{t.description}</p></section>
          {t.resolution && <section aria-label="Resolution" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h2 className="mb-1 font-semibold">Resolution</h2><p className="whitespace-pre-wrap">{t.resolution}</p>
            {t.needs_confirmation && <p className="mt-1 text-xs text-muted">{t.customer_confirmed ? "Confirmed by the customer" : "Needs the customer’s confirmation before closing as resolved"}</p>}</section>}
          {(t.escalations?.length ?? 0) > 0 && <section aria-label="Escalations" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h2 className="mb-1 font-semibold">Escalations</h2>
            <ol className="space-y-1.5">{t.escalations!.map((e, i) => <li key={i}><Badge tone="gold">Level {e.level}</Badge> {e.rule}<span className="block text-xs text-muted">{formatDateTime(e.at)} · told {e.recipients.join(", ") || "nobody available"}</span></li>)}</ol></section>}
          {t.attachments.length > 0 && <section aria-label="Attachments" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line"><h2 className="mb-1 font-semibold">Attachments</h2>
            <ul>{t.attachments.map((a) => <li key={a.id}><a href={a.url} target="_blank" rel="noopener" className="text-forest-800 underline">{a.file_name}</a> <span className="text-xs text-muted">{a.purpose}</span></li>)}</ul></section>}
        </aside>
      </div>
      {dlg && <Modal title={{ ack: "Acknowledge the customer", wait: "Change status", note: "Internal note", message: "Log a customer message", propose: "Propose the resolution",
        confirm: "Customer’s response", close: "Close the ticket", reopen: "Reopen the ticket", assign: "Assign the ticket", attach: "Attach a file" }[dlg]} onClose={() => setDlg(null)}>
        <form className="space-y-3" onSubmit={submit}>
          {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
          {dlg === "assign" && <SelectInput label="Owner" value={f.owner} onChange={(e) => setF({ ...f, owner: e.target.value })}><option value="">Choose a person</option>
            {(t.owners ?? []).map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</SelectInput>}
          {dlg === "wait" && <SelectInput label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            {["in_progress", "waiting_customer", "waiting_internal", "waiting_external"].filter((x) => x !== t.status).map((x) => <option key={x} value={x}>{STATUS[x]}</option>)}</SelectInput>}
          {dlg === "wait" && f.status !== "in_progress" && f.status !== "waiting_internal" && <p className="text-xs text-muted">The resolution target is paused while waiting; the paused time is recorded.</p>}
          {dlg === "message" && <div className="grid grid-cols-2 gap-3">
            <SelectInput label="Direction" value={f.direction} onChange={(e) => setF({ ...f, direction: e.target.value })}><option value="out">To the customer</option><option value="in">From the customer</option></SelectInput>
            <SelectInput label="Channel" value={f.channel} onChange={(e) => setF({ ...f, channel: e.target.value })}>{["phone", "email", "whatsapp", "sms", "visit", "letter"].map((c) => <option key={c} value={c}>{c}</option>)}</SelectInput></div>}
          {dlg === "confirm" && <>
            <fieldset className="flex gap-4 text-sm"><legend className="mb-1 font-medium">Is the customer satisfied with the resolution?</legend>
              {[["yes", "Yes, confirmed"], ["no", "No, still an issue"]].map(([v, l]) => <label key={v} className="flex min-h-9 items-center gap-2"><input type="radio" name="cf" checked={f.confirmed === v} onChange={() => setF({ ...f, confirmed: v })} className="accent-forest-900" />{l}</label>)}</fieldset>
            {f.confirmed === "yes" && <SelectInput label="Satisfaction (1–5)" value={f.csat} onChange={(e) => setF({ ...f, csat: e.target.value })}>{[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n}</option>)}</SelectInput>}
          </>}
          {dlg === "close" && <SelectInput label="Closure reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })}>{Object.entries(CLOSURE).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</SelectInput>}
          {dlg === "attach" && <><SelectInput label="Purpose" value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })}><option value="evidence">Customer’s evidence</option><option value="resolution">Resolution evidence</option></SelectInput>
            <div className="space-y-1.5"><label htmlFor="tk-file" className="block text-sm font-medium">File</label>
              <input id="tk-file" type="file" accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" /></div></>}
          {dlg !== "assign" && dlg !== "attach" && <TextArea label={{ ack: "Message to the customer", wait: "What or who is it waiting for?", note: "Note (only staff see this)", message: "Message",
            propose: "Action taken", confirm: f.confirmed === "yes" ? "Customer’s comment (optional)" : "What’s still wrong?", close: "Note" + (f.reason === "resolved" ? " (optional)" : ""), reopen: "Reason for reopening" }[dlg]}
            value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} rows={3} maxLength={5000} autoFocus />}
          {dlg === "reopen" && <p className="text-xs text-muted">Within {t.reopen_days} days of closing anyone on the team can reopen; after that a CRM manager does.</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setDlg(null)}>Cancel</Button><Button type="submit" loading={act.isPending} disabled={!ok}>Save</Button></div>
        </form></Modal>}
    </div>
  );
}
