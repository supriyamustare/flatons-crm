import { useState } from "react";
import type { FormEvent } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Badge, Button, ErrorState, Modal, SelectInput, TextArea, TextInput, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
export const MSG_STATUS: Record<string, string> = { queued: "Queued", held: "Held", sent: "Sent", failed: "Failed", skipped: "Not sent" };
const tone = (s: string) => (s === "sent" ? "neutral" : s === "failed" || s === "held" ? "gold" : "muted") as "neutral" | "gold" | "muted";

export function ChannelBanner({ channels }: { channels: Record<string, string | null> }) {
  const off = Object.entries(channels).filter(([, v]) => v);
  if (off.length === 0) return null;
  return <Alert>{off.map(([k, v]) => <span key={k} className="block">{k === "email" ? "Email" : k === "sms" ? "SMS" : "WhatsApp"}: {v}. Messages wait in the outbox (held) until it’s set up.</span>)}</Alert>;
}

function TemplateDialog({ init, events, projects, onClose }: { init: Any; events: Any; projects: Any[]; onClose: () => void }) {
  const qc = useQueryClient(); const toast = useToast();
  const [f, setF] = useState({ event: init.event, channel: init.channel, project_id: init.project_id ? String(init.project_id) : "", subject: init.subject ?? "", body: init.body ?? "",
    mandatory: !!init.mandatory, delay_minutes: String(init.delay_minutes ?? 0), language: init.language ?? "English" });
  const save = useMutation({ mutationFn: async () => { const body = { ...f, project_id: f.project_id ? Number(f.project_id) : null, delay_minutes: Number(f.delay_minutes), subject: f.subject.trim() || null };
    return (init.id && init.status === "draft" ? await api.put(`/comms/templates/${init.id}`, body) : await api.post("/comms/templates", body)).data; },
    onSuccess: (d) => { qc.setQueryData(["comms-templates"], d); toast("Draft saved; someone else approves it before it’s used"); onClose(); } });
  const ev = events[f.event];
  return (
    <Modal title={init.id && init.status === "draft" ? "Edit draft" : "New version"} onClose={onClose}>
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <p className="text-sm"><b>{ev.label}</b> · {f.channel}</p>
        <div className="grid grid-cols-2 gap-3">
          <SelectInput label="Project" value={f.project_id} onChange={(e) => setF({ ...f, project_id: e.target.value })} disabled={!!(init.id && init.status === "draft")}><option value="">Every project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</SelectInput>
          <TextInput label="Language" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })} />
          <TextInput label="Send after (minutes; 0 = immediately)" type="number" min={0} value={f.delay_minutes} onChange={(e) => setF({ ...f, delay_minutes: e.target.value })} />
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={f.mandatory} onChange={(e) => setF({ ...f, mandatory: e.target.checked })} />Mandatory (sent even if the customer opted out of this channel)</label>
        </div>
        {f.channel === "email" && <TextInput label="Subject" value={f.subject} onChange={(e) => setF({ ...f, subject: e.target.value })} />}
        <TextArea label="Message" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} rows={8} />
        <p className="text-xs text-muted">Fields you can use: {ev.fields.map((x: string) => `{${x}}`).join(" ")}. No links: documents are shared through the customer portal, never as open links.</p>
        <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" loading={save.isPending}>Save draft</Button></div>
      </form>
    </Modal>
  );
}

export function CommunicationsPage() {
  const [sp, setSp] = useSearchParams(); const tab = sp.get("tab") === "outbox" ? "outbox" : "templates";
  const qc = useQueryClient(); const toast = useToast();
  const t = useQuery({ queryKey: ["comms-templates"], queryFn: async () => (await api.get<Any>("/comms/templates")).data });
  const [st, setSt] = useState("");
  const out = useQuery({ queryKey: ["comms-outbox", st], enabled: tab === "outbox", queryFn: async () => (await api.get<Any[]>("/comms/messages", { params: st ? { status: st } : {} })).data });
  const [dlg, setDlg] = useState<Any | null>(null); const [prev, setPrev] = useState<Any | null>(null);
  const act = useMutation({ mutationFn: async (path: string) => (await api.post(path)).data, onSuccess: (d, path) => {
    if (path.endsWith("/preview")) { setPrev(d); return; }
    if (path.includes("/messages/")) { void out.refetch(); toast("Queued again"); return; }
    qc.setQueryData(["comms-templates"], d); toast(path.endsWith("/approve") ? "Approved: this version is now used" : "Retired"); } });
  return (
    <div className="space-y-4">
      <h1 className="font-display text-2xl text-forest-900 sm:text-3xl">Communications</h1>
      <div role="tablist" aria-label="Communications" className="flex gap-1.5">{[["templates", "Templates"], ["outbox", "Outbox"]].map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k}
        onClick={() => setSp({ tab: k })} className={cx("min-h-10 rounded-full px-4 text-sm", tab === k ? "bg-forest-900 text-white" : "bg-white ring-1 ring-line hover:bg-forest-50")}>{l}</button>)}</div>
      {t.data && <ChannelBanner channels={t.data.channels} />}
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {t.isError && <ErrorState message={errorMessage(t.error, "Couldn’t load templates.")} onRetry={() => void t.refetch()} />}
      {tab === "templates" && t.data && <ul className="space-y-3">{Object.entries(t.data.events as Record<string, Any>).map(([ev, meta]) => {
        const rows = (t.data.templates as Any[]).filter((x) => x.event === ev && x.status !== "retired");
        return <li key={ev} className="rounded-xl bg-white p-4 text-sm ring-1 ring-line" aria-label={meta.label}>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><h2 className="font-semibold">{meta.label}</h2>
            <span className="flex gap-1.5">{(["email", "sms", "whatsapp"] as const).map((ch) => <Button key={ch} variant="ghost" onClick={() => setDlg({ event: ev, channel: ch, ...(rows.find((r) => r.channel === ch && r.status === "approved") ?? {}), id: undefined, status: undefined })}>New {ch} version</Button>)}</span></div>
          {rows.length === 0 ? <p className="text-xs text-muted">No template: nothing is sent for this event.</p> : <ul className="space-y-2">{rows.map((x) => <li key={x.id} className="rounded-lg bg-paper p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs"><Badge tone={x.status === "approved" ? "neutral" : "gold"}>{x.status === "approved" ? "In use" : "Draft"}</Badge> {x.channel} · v{x.version}{x.project_id ? ` · project only` : ""}{x.mandatory ? " · mandatory" : ""}{x.delay_minutes ? ` · after ${x.delay_minutes} min` : ""} · {x.author}{x.approved_by ? `, approved by ${x.approved_by}` : ""}</p>
              <span className="flex flex-wrap gap-1.5">
                <Button variant="ghost" onClick={() => act.mutate(`/comms/templates/${x.id}/preview`)}>Preview</Button>
                {x.can_edit && <Button variant="ghost" onClick={() => setDlg(x)}>Edit</Button>}
                {x.can_approve && <Button onClick={() => act.mutate(`/comms/templates/${x.id}/approve`)}>Approve</Button>}
                {x.status === "draft" && !x.can_approve && <span className="self-center text-xs text-muted">Someone other than the author approves</span>}
                {x.status === "approved" && <Button variant="ghost" onClick={() => act.mutate(`/comms/templates/${x.id}/retire`)}>Retire</Button>}
              </span></div>
            {x.subject && <p className="mt-1 text-xs font-medium">{x.subject}</p>}<p className="mt-1 whitespace-pre-wrap text-xs">{x.body}</p></li>)}</ul>}
        </li>; })}</ul>}
      {tab === "outbox" && <>
        <div className="w-48"><SelectInput label="Status" value={st} onChange={(e) => setSt(e.target.value)}><option value="">All</option>{Object.entries(MSG_STATUS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</SelectInput></div>
        <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line"><table className="w-full min-w-[760px] text-sm"><caption className="sr-only">Outbox</caption>
          <thead className="text-xs text-muted"><tr>{["When", "Event", "Channel", "To", "Status", "Reason", ""].map((h) => <th key={h} scope="col" className="px-3 py-2 text-left font-normal">{h}</th>)}</tr></thead>
          <tbody>{(out.data ?? []).map((m) => <tr key={m.id} className="border-t border-line align-top"><td className="px-3 py-2 text-xs">{formatDateTime(m.sent_at ?? m.created_at)}</td><td className="px-3 py-2">{m.event_label}<span className="block text-xs text-muted">{m.subject}</span></td>
            <td className="px-3 py-2">{m.channel}</td><td className="px-3 py-2">{m.recipient ?? "—"}</td><td className="px-3 py-2"><Badge tone={tone(m.status)}>{MSG_STATUS[m.status]}</Badge>{m.attempts > 1 && <span className="block text-xs text-muted">{m.attempts} attempts</span>}</td>
            <td className="px-3 py-2 text-xs">{m.reason ?? ""}</td><td className="px-3 py-2">{["failed", "held"].includes(m.status) && <Button variant="ghost" onClick={() => act.mutate(`/comms/messages/${m.id}/retry`)}>Retry</Button>}</td></tr>)}
            {out.data?.length === 0 && <tr><td colSpan={7} className="px-3 py-6 text-center text-muted">No messages.</td></tr>}</tbody></table></div>
      </>}
      {dlg && t.data && <TemplateDialog init={dlg} events={t.data.events} projects={t.data.projects} onClose={() => setDlg(null)} />}
      {prev && <Modal title="Preview (sample data)" onClose={() => setPrev(null)}><div className="space-y-2 text-sm">{prev.subject && <p className="font-semibold">{prev.subject}</p>}<p className="whitespace-pre-wrap">{prev.body}</p></div></Modal>}
    </div>
  );
}
