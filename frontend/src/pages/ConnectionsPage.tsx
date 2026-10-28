import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, PlugZap, Plus } from "lucide-react";
import { Alert, Badge, Button, ErrorState, Modal, PageHeader, SelectInput, TextInput, cx } from "../components/ui";
import { useProjects } from "../hooks/useLeads";
import { useCampaigns } from "../hooks/useMarketing";
import { api, errorMessage, formatDateTime } from "../lib/api";

type Kind = "website" | "99acres" | "magicbricks" | "housing" | "facebook" | "google_ads";
interface Connection {
  id: number; name: string; kind: Kind; is_active: boolean; default_campaign_id: number | null; default_project_id: number | null;
  received_count: number; last_received_at: string | null; facebook_ready: boolean; path: string; created_at: string;
}
interface InboundEvent { id: number; received_at: string; external_id: string | null; status: string; lead_id: number | null; error: string | null; payload: Record<string, unknown> }

const KINDS: Kind[] = ["99acres", "magicbricks", "housing", "facebook", "google_ads"];
const KIND_LABELS: Record<Kind, string> = {
  website: "Website enquiry form", "99acres": "99acres", magicbricks: "MagicBricks", housing: "Housing.com",
  facebook: "Meta ads (Facebook / Instagram)", google_ads: "Google Ads lead form",
};
const STATUS_TONE: Record<string, "neutral" | "gold" | "muted"> = { created: "neutral", merged: "gold", test: "muted", duplicate: "muted", pending: "gold", rejected: "muted", failed: "muted" };
const STATUS_LABELS: Record<string, string> = {
  created: "New lead", merged: "Added to existing lead", duplicate: "Repeat delivery (ignored)", test: "Test", pending: "Fetching details",
  rejected: "Not used", failed: "Error",
};

const fullUrl = (path: string) => `${window.location.origin}${path}`;

function CopyField({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <p className="text-sm font-medium">{label}</p>
      <div className="mt-1 flex items-stretch gap-2">
        <code className="min-w-0 flex-1 overflow-x-auto rounded-lg bg-paper px-3 py-2 text-xs whitespace-nowrap">{value}</code>
        <Button type="button" variant="secondary" aria-label={`Copy ${label.toLowerCase()}`}
          onClick={() => { void navigator.clipboard?.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />}
        </Button>
      </div>
    </div>
  );
}

function Instructions({ kind }: { kind: Kind }): ReactNode {
  const steps: Record<Kind, ReactNode[]> = {
    website: [
      "Have your web developer send each enquiry from the website’s server (not from the visitor’s browser) as a JSON POST to the address above.",
      <>Put the key in a header called <code>X-Flatons-Key</code>. Fields: <code>name</code>, <code>mobile</code>, and optionally <code>email</code>, <code>city</code>, <code>message</code>, <code>project</code>.</>,
    ],
    "99acres": portalSteps("99acres"), magicbricks: portalSteps("MagicBricks"), housing: portalSteps("Housing.com"),
    google_ads: [
      "In Google Ads, open the lead form asset → Lead delivery → Webhook integration.",
      "Paste the address above as the Webhook URL and the key as the Key, then press Send test data. It should show here as Test.",
    ],
    facebook: [
      "In your Meta app (developers.facebook.com) → Webhooks → Page, subscribe to the leadgen field.",
      "Use the address above as the Callback URL and the key as the Verify token.",
      "Connect your Facebook page to the app. Test with Meta’s Lead Ads Testing Tool; the lead should appear in New enquiries.",
    ],
  };
  return <ol className="list-decimal space-y-1.5 pl-5 text-sm">{steps[kind].map((s, i) => <li key={i}>{s}</li>)}</ol>;
}

function portalSteps(name: string): ReactNode[] {
  return [
    `Ask your ${name} account manager to push leads to a CRM web address (“lead push” or “CRM integration”).`,
    <>Give them the address above with the key added at the end: <code>?key=…</code> (shown in the full address below).</>,
    "Once their first lead arrives, check it under Activity. If a field (such as the phone number) wasn’t picked up, the raw contents shown there tell us what to adjust.",
  ];
}

function CreatedDialog({ conn, secret, onClose }: { conn: Connection; secret: string; onClose: () => void }) {
  const [test, setTest] = useState<string | null>(null);
  const portal = ["99acres", "magicbricks", "housing"].includes(conn.kind);
  const sendTest = useMutation({
    mutationFn: async () => (await api.post(`${conn.path.replace(/^\/api/, "")}?test=true`,
      { name: "Test enquiry", mobile: "9876543210", message: "Checking the connection" }, { headers: { "X-Flatons-Key": secret } })).data,
    onSuccess: (d) => setTest(String(d.detail ?? d.status)),
  });
  return (
    <Modal title={`${conn.name} is ready`} onClose={onClose}>
      <div className="space-y-4">
        <Alert tone="success">Copy the key now. For security it won’t be shown again (you can make a new one later).</Alert>
        <CopyField label="Address" value={fullUrl(conn.path)} />
        <CopyField label={conn.kind === "facebook" ? "Verify token (key)" : "Key"} value={secret} />
        {portal && <CopyField label="Full address for the portal" value={`${fullUrl(conn.path)}?key=${secret}`} />}
        <div><p className="mb-1 text-sm font-medium">Setting it up</p><Instructions kind={conn.kind} /></div>
        {!window.location.protocol.startsWith("https") && (
          <p className="rounded-lg bg-gold-100 p-3 text-sm">This server isn’t on HTTPS yet. Platforms will only send leads to an <b>https://</b> address, so finish the domain setup before connecting them.</p>
        )}
        {conn.kind !== "facebook" && conn.kind !== "google_ads" && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" loading={sendTest.isPending} onClick={() => sendTest.mutate()}>Send test enquiry</Button>
            {test && <span className="text-sm text-forest-800" role="status">{test}</span>}
            {sendTest.isError && <span className="text-sm text-danger">{errorMessage(sendTest.error)}</span>}
          </div>
        )}
        <div className="flex justify-end"><Button onClick={onClose}>Done</Button></div>
      </div>
    </Modal>
  );
}

function NewConnectionDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (c: Connection, secret: string) => void }) {
  const qc = useQueryClient();
  const campaigns = useCampaigns();
  const projects = useProjects();
  const [kind, setKind] = useState<Kind>("99acres");
  const [name, setName] = useState("");
  const [campaign, setCampaign] = useState("");
  const [project, setProject] = useState("");
  const [appSecret, setAppSecret] = useState("");
  const [pageToken, setPageToken] = useState("");
  const create = useMutation({
    mutationFn: async () => (await api.post<{ integration: Connection; secret: string }>("/integrations", {
      name: name.trim() || KIND_LABELS[kind], kind,
      default_campaign_id: campaign ? Number(campaign) : null, default_project_id: project ? Number(project) : null,
      ...(kind === "facebook" ? { fb_app_secret: appSecret.trim(), fb_page_token: pageToken.trim() } : {}),
    })).data,
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["integrations"] }); onCreated(d.integration, d.secret); },
  });
  const fbOk = kind !== "facebook" || (appSecret.trim().length >= 10 && pageToken.trim().length >= 10);
  return (
    <Modal title="New connection" onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
        <SelectInput label="Where enquiries come from" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
          {KINDS.map((k) => <option key={k} value={k}>{KIND_LABELS[k]}</option>)}
        </SelectInput>
        <TextInput label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder={KIND_LABELS[kind]} maxLength={100} />
        <SelectInput label="Campaign for these leads (optional)" value={campaign} onChange={(e) => setCampaign(e.target.value)}
          hint="Counts these leads towards that campaign’s cost per lead">
          <option value="">None</option>{campaigns.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </SelectInput>
        <SelectInput label="Project for these leads (optional)" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">None</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>
        {kind === "facebook" && (<>
          <TextInput label="Facebook app secret" type="password" autoComplete="off" value={appSecret} onChange={(e) => setAppSecret(e.target.value)}
            hint="Meta app → Settings → Basic. Stored encrypted." />
          <TextInput label="Page access token" type="password" autoComplete="off" value={pageToken} onChange={(e) => setPageToken(e.target.value)}
            hint="A long-lived token with leads_retrieval permission. Stored encrypted." />
        </>)}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending} disabled={!fbOk}>Create connection</Button>
        </div>
      </form>
    </Modal>
  );
}

function Activity({ conn }: { conn: Connection }) {
  const events = useQuery({
    queryKey: ["integrations", conn.id, "events"],
    queryFn: async () => (await api.get<InboundEvent[]>(`/integrations/${conn.id}/events`)).data,
    refetchInterval: 30_000,
  });
  if (events.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (events.isError) return <p className="text-sm text-danger">{errorMessage(events.error)}</p>;
  if (!events.data.length) return <p className="text-sm text-muted">Nothing received yet.</p>;
  return (
    <ul className="divide-y divide-line text-sm">
      {events.data.map((e) => (
        <li key={e.id} className="py-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATUS_TONE[e.status] ?? "muted"}>{STATUS_LABELS[e.status] ?? e.status}</Badge>
            <span className="text-muted">{formatDateTime(e.received_at)}</span>
            {e.lead_id && <a className="text-forest-800 underline" href={`/leads/${e.lead_id}`}>Open lead</a>}
          </div>
          {e.error && <p className="mt-1 text-muted">{e.error}</p>}
          <details className="mt-1"><summary className="cursor-pointer text-xs text-muted">What was received</summary>
            <pre className="mt-1 max-h-48 overflow-auto rounded-lg bg-paper p-2 text-xs">{JSON.stringify(e.payload, null, 2)}</pre></details>
        </li>
      ))}
    </ul>
  );
}

export function ConnectionsPage() {
  const qc = useQueryClient();
  const conns = useQuery({ queryKey: ["integrations"], queryFn: async () => (await api.get<Connection[]>("/integrations")).data });
  const [adding, setAdding] = useState(false);
  const [created, setCreated] = useState<{ conn: Connection; secret: string } | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [confirmRotate, setConfirmRotate] = useState<number | null>(null);
  const toggle = useMutation({
    mutationFn: async (c: Connection) => { await api.patch(`/integrations/${c.id}`, { is_active: !c.is_active }); },
    onSettled: () => qc.invalidateQueries({ queryKey: ["integrations"] }),
  });
  const rotate = useMutation({
    mutationFn: async (id: number) => (await api.post<{ integration: Connection; secret: string }>(`/integrations/${id}/rotate`)).data,
    onSuccess: (d) => { setConfirmRotate(null); setCreated({ conn: d.integration, secret: d.secret }); },
  });

  return (
    <>
      <PageHeader title="Connections" description="Websites, portals and ad platforms that send enquiries straight into the CRM."
        action={<Button onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden />New connection</Button>} />
      {conns.isError && <ErrorState message={errorMessage(conns.error)} onRetry={() => void conns.refetch()} />}
      {conns.isSuccess && conns.data.length === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <PlugZap className="mx-auto size-8 text-forest-700" aria-hidden />
          <p className="mt-2 font-display text-xl text-forest-900">No connections yet</p>
          <p className="mt-1 text-sm text-muted">Add one for each place enquiries come from: your website, 99acres, MagicBricks, Housing.com, Facebook or Google Ads.</p>
        </div>
      )}
      <ul className="space-y-3">
        {conns.data?.map((c) => (
          <li key={c.id} className={cx("rounded-xl bg-white p-4 ring-1", c.is_active ? "ring-line" : "opacity-70 ring-line")}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="font-medium">{c.name} {!c.is_active && <Badge tone="muted">Switched off</Badge>}</p>
                <p className="text-sm text-muted">{KIND_LABELS[c.kind]} · {c.received_count} received{c.last_received_at ? ` · last ${formatDateTime(c.last_received_at)}` : ""}</p>
                <code className="mt-1 block text-xs break-all text-muted">{fullUrl(c.path)}</code>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="secondary" aria-expanded={open === c.id} onClick={() => setOpen(open === c.id ? null : c.id)}>Activity</Button>
                <Button variant="ghost" onClick={() => toggle.mutate(c)}>{c.is_active ? "Switch off" : "Switch on"}</Button>
                {confirmRotate === c.id ? (
                  <>
                    <Button variant="danger" loading={rotate.isPending} onClick={() => rotate.mutate(c.id)}>Make new key</Button>
                    <Button variant="secondary" onClick={() => setConfirmRotate(null)}>Keep</Button>
                  </>
                ) : <Button variant="ghost" onClick={() => setConfirmRotate(c.id)}>New key</Button>}
              </div>
            </div>
            {confirmRotate === c.id && <p className="mt-2 text-sm text-gold-600">The old key stops working immediately; the platform must be updated with the new one.</p>}
            {open === c.id && <div className="mt-3 border-t border-line pt-3"><Activity conn={c} /></div>}
          </li>
        ))}
      </ul>
      {adding && <NewConnectionDialog onClose={() => setAdding(false)} onCreated={(conn, secret) => { setAdding(false); setCreated({ conn, secret }); }} />}
      {created && <CreatedDialog conn={created.conn} secret={created.secret} onClose={() => setCreated(null)} />}
    </>
  );
}
