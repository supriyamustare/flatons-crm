import { useQuery } from "@tanstack/react-query";
import { Alert, Badge } from "../../components/ui";
import { ChannelBanner, MSG_STATUS } from "../comms/CommunicationsPage";
import { api, errorMessage, formatDateTime } from "../../lib/api";

/* eslint-disable @typescript-eslint/no-explicit-any */
export function CommunicationsTab({ caseId }: { caseId: number }) {
  const q = useQuery({ queryKey: ["case-comms", caseId], queryFn: async () => (await api.get<any>(`/post-sales/cases/${caseId}/communications`)).data });
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const { messages, preferences: p, channels } = q.data;
  return (
    <section role="tabpanel" aria-label="Communications" className="space-y-4">
      <ChannelBanner channels={channels} />
      <section aria-label="Preferences" className="rounded-xl bg-white p-4 text-sm ring-1 ring-line">
        <h3 className="mb-1 font-semibold">Consent and channels</h3>
        {!p ? <p className="text-muted">No customer profile yet.</p> : <ul className="space-y-0.5">
          <li>Electronic communication consent: {p.consent_electronic_at ? <b>given {formatDateTime(p.consent_electronic_at)}</b> : <span className="text-danger">not recorded: messages go by letter</span>}</li>
          <li>Email {p.email ?? "—"}: {p.contact_email ? "yes" : "opted out"} · SMS {p.mobile ?? "—"}: {p.contact_sms ? "yes" : "opted out"} · WhatsApp: {p.contact_whatsapp ? "opted in" : "not opted in"}</li>
          <li className="text-xs text-muted">Change these on the Customer tab. Mandatory notices (such as demands) still go to a channel the customer opted out of, if they consented to electronic communication.</li></ul>}
      </section>
      <section aria-label="Message history" className="space-y-2">
        <h3 className="font-semibold">Messages sent to the customer</h3>
        {messages.length === 0 ? <p className="rounded-xl border border-dashed border-line bg-white px-6 py-6 text-center text-sm text-muted">No messages yet.</p> :
          <ul className="space-y-2">{messages.map((m: any) => <li key={m.id} className="rounded-xl bg-white p-3 text-sm ring-1 ring-line">
            <p className="flex flex-wrap items-center gap-2"><b>{m.event_label}</b> <Badge tone={m.status === "sent" ? "neutral" : m.status === "skipped" ? "muted" : "gold"}>{MSG_STATUS[m.status]}</Badge>
              <span className="text-xs text-muted">{m.channel} to {m.recipient ?? "—"} · {formatDateTime(m.sent_at ?? m.created_at)} · template v{m.template_version}</span></p>
            {m.reason && <p className="text-xs text-muted">{m.reason}</p>}
            <details className="mt-1 text-xs"><summary className="cursor-pointer text-forest-800">Message</summary>{m.subject && <p className="mt-1 font-medium">{m.subject}</p>}<p className="whitespace-pre-wrap">{m.body}</p></details>
          </li>)}</ul>}
      </section>
    </section>
  );
}
