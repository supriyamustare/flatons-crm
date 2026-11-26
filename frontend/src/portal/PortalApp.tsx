import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import axios from "axios";
import { BrowserRouter, Link, NavLink, Navigate, Route, Routes, useNavigate, useParams } from "react-router";
import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Badge, Button, TextArea, TextInput, SelectInput, cx } from "../components/ui";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Any = any;
/** The portal's own client: only /api/portal, no staff sign-in logic. */
export const papi = axios.create({ baseURL: "/api/portal", withCredentials: true });
const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: (n, e: Any) => e?.response?.status !== 401 && e?.response?.status !== 404 && n < 2, staleTime: 30_000 } } });
const inr = (n: number | null | undefined) => (n == null ? "—" : `₹ ${Math.round(n).toLocaleString("en-IN")}`);
const fdate = (d?: string | null) => (d ? new Date(d.length === 10 ? `${d}T00:00:00` : d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—");
const msg = (e: Any, fallback = "Something went wrong. Please try again.") => e?.response?.data?.detail && typeof e.response.data.detail === "string" ? e.response.data.detail : fallback;
const STATUS_TONE: Record<string, "neutral" | "gold" | "muted"> = { "Payment confirmed": "neutral", "No payment currently due": "neutral", "Upcoming payment": "muted",
  "Payment due": "gold", "Overdue payment": "gold", "Payment received - reconciliation pending": "muted", "Payment under clarification": "gold", "Refund under process": "muted", "Not yet demanded": "muted" };
const human = (s: string) => s.replace(" - ", " — ");
const MENU = [["", "Home"], ["payments", "My Payments"], ["documents", "My Documents"], ["agreement", "My Agreement"], ["property", "My Property"], ["updates", "Project Updates"],
  ["notifications", "Notifications"], ["profile", "My Profile"], ["help", "Help Centre"], ["security", "Security"]] as const;

function useMe() {
  return useQuery({ queryKey: ["portal-me"], queryFn: async () => (await papi.get<Any>("/me")).data });
}

function SignIn() {
  const st = useQuery({ queryKey: ["portal-status"], queryFn: async () => (await papi.get<Any>("/status")).data });
  const [email, setEmail] = useState(""); const [code, setCode] = useState(""); const [sent, setSent] = useState<string | null>(null);
  const nav = useNavigate(); const client = useQueryClient();
  const req = useMutation({ mutationFn: async () => (await papi.post("/auth/request", { email })).data, onSuccess: (d) => setSent(d.message) });
  const ver = useMutation({ mutationFn: async () => (await papi.post("/auth/verify", { email, code })).data, onSuccess: () => { void client.invalidateQueries(); nav("/portal", { replace: true }); } });
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-5 py-10">
      <p className="font-display text-3xl text-forest-900">Flatons</p>
      <h1 className="mt-1 text-xl font-semibold">Customer portal</h1>
      <p className="mt-1 text-sm text-muted">See your payments, documents and updates for your home.</p>
      {st.data && !st.data.enabled ? <div className="mt-6"><Alert>{st.data.reason}</Alert></div> : !sent ? (
        <form className="mt-6 space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); req.mutate(); }}>
          {req.isError && <Alert>{msg(req.error)}</Alert>}
          <TextInput label="Your email address" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <p className="text-xs text-muted">Use the email address you gave us. We’ll send you a one-time code.</p>
          <Button type="submit" loading={req.isPending} disabled={!/^\S+@\S+\.\S+$/.test(email)} className="w-full justify-center">Send me a code</Button>
        </form>) : (
        <form className="mt-6 space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); ver.mutate(); }}>
          <p className="rounded-lg bg-forest-50 p-3 text-sm">{sent}</p>
          {ver.isError && <Alert>{msg(ver.error)}</Alert>}
          <TextInput label="6-digit code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          <Button type="submit" loading={ver.isPending} disabled={code.length !== 6} className="w-full justify-center">Sign in</Button>
          <button type="button" className="text-sm text-forest-800 underline" onClick={() => { setSent(null); setCode(""); }}>Use a different email or send a new code</button>
        </form>)}
    </main>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const me = useMe(); const { caseId } = useParams(); const nav = useNavigate(); const client = useQueryClient();
  const [open, setOpen] = useState(false);
  useEffect(() => { if (me.data && !caseId && me.data.units[0]) nav(`/portal/${me.data.units[0].case_id}`, { replace: true }); }, [me.data, caseId, nav]);
  if (me.isError) return <Navigate to="/portal/sign-in" replace />;
  if (!me.data) return <div className="p-8 text-muted">Loading…</div>;
  const unit = me.data.units.find((u: Any) => String(u.case_id) === caseId) ?? me.data.units[0];
  const logout = async () => { await papi.post("/auth/logout"); client.clear(); nav("/portal/sign-in", { replace: true }); };
  return (
    <div className="min-h-screen bg-paper">
      <header className="sticky top-0 z-20 border-b border-line bg-white/95 backdrop-blur" style={{ paddingTop: "env(safe-area-inset-top)" }}>
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <Link to={`/portal/${unit?.case_id ?? ""}`} className="font-display text-xl text-forest-900">Flatons</Link>
          <div className="flex items-center gap-2">
            {me.data.units.length > 1 && <label className="sr-only" htmlFor="unit-switch">Your unit</label>}
            {me.data.units.length > 1 && <select id="unit-switch" className="min-h-10 rounded-lg border border-line bg-white px-2 text-sm" value={unit.case_id}
              onChange={(e) => nav(`/portal/${e.target.value}`)}>{me.data.units.map((u: Any) => <option key={u.case_id} value={u.case_id}>{u.project} · {u.unit}</option>)}</select>}
            <button type="button" className="min-h-10 rounded-lg px-3 text-sm ring-1 ring-line md:hidden" aria-expanded={open} aria-controls="portal-menu" onClick={() => setOpen(!open)}>Menu</button>
            <button type="button" className="hidden min-h-10 rounded-lg px-3 text-sm ring-1 ring-line md:block" onClick={() => void logout()}>Sign out</button>
          </div>
        </div>
      </header>
      <div className="mx-auto grid max-w-5xl gap-6 px-4 py-6 md:grid-cols-[13rem_1fr]">
        <nav id="portal-menu" aria-label="Portal" className={cx("md:block", open ? "block" : "hidden")}>
          <ul className="space-y-1">{MENU.map(([path, label]) => <li key={path}><NavLink end to={`/portal/${unit.case_id}${path ? `/${path}` : ""}`} onClick={() => setOpen(false)}
            className={({ isActive }) => cx("block rounded-lg px-3 py-2 text-sm", isActive ? "bg-forest-900 text-white" : "hover:bg-white")}>{label}</NavLink></li>)}
            <li className="md:hidden"><button type="button" className="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-white" onClick={() => void logout()}>Sign out</button></li></ul>
        </nav>
        <main className="min-w-0 space-y-4">{children}</main>
      </div>
    </div>
  );
}

function useCaseData(path: string) {
  const { caseId } = useParams();
  return useQuery({ queryKey: ["portal", caseId, path], enabled: !!caseId, queryFn: async () => (await papi.get<Any>(`/cases/${caseId}/${path}`)).data });
}
const Card = ({ title, children, className }: { title?: string; children: ReactNode; className?: string }) =>
  <section aria-label={title} className={cx("rounded-2xl bg-white p-5 ring-1 ring-line", className)}>{title && <h2 className="mb-3 text-base font-semibold">{title}</h2>}{children}</section>;
function Loading({ q }: { q: Any }) {
  if (q.isError) return <Alert>{msg(q.error, "We couldn’t load this. Please try again.")}</Alert>;
  return <div className="h-40 animate-pulse rounded-2xl bg-white" />;
}

function Home() {
  const q = useCaseData("dashboard"); const { caseId } = useParams();
  if (!q.data) return <Loading q={q} />;
  const d = q.data; const p = d.property; const pay = d.payments;
  return <>
    <h1 className="font-display text-2xl text-forest-900">Welcome</h1>
    <Card title="My Property" className="bg-forest-900 text-white ring-0">
      <p className="text-lg font-semibold">{p.project}{p.tower ? ` · ${p.tower}` : ""} · Unit {p.unit}</p>
      <p className="mt-1"><Badge tone="gold">{p.status}</Badge></p>
      <dl className="mt-4 grid grid-cols-2 gap-4">
        <div><dt className="text-xs text-white/70">Total paid</dt><dd className="text-2xl font-semibold tabular-nums">{inr(pay.total_paid)}</dd></div>
        <div><dt className="text-xs text-white/70">Next payment due</dt><dd className="text-2xl font-semibold tabular-nums">{pay.next_due ? inr(pay.next_due.amount) : "—"}</dd>
          <dd className="text-xs text-white/80">{pay.next_due ? `${pay.next_due.stage}${pay.next_due.due_date ? `, ${fdate(pay.next_due.due_date)}` : ""}` : human(pay.headline)}</dd></div>
      </dl>
    </Card>
    <Card title="Payment status"><p><Badge tone={STATUS_TONE[pay.headline] ?? "muted"}>{human(pay.headline)}</Badge></p>
      {pay.pending_reconciliation > 0 && <p className="mt-2 text-sm text-muted">{inr(pay.pending_reconciliation)} received and waiting to be confirmed with the bank.</p>}
      {pay.next_milestone && <p className="mt-2 text-sm text-muted">Next construction milestone: {pay.next_milestone}</p>}</Card>
    {d.pending_actions.length > 0 && <Card title="Needs your attention"><ul className="list-disc space-y-1 pl-5 text-sm">{d.pending_actions.map((a: string, i: number) => <li key={i}>{human(a)}</li>)}</ul></Card>}
    <div className="grid gap-4 sm:grid-cols-2">
      <Link to={`/portal/${caseId}/documents`} className="rounded-2xl bg-white p-5 ring-1 ring-line hover:ring-forest-700"><p className="font-semibold">My Documents</p><p className="text-sm text-muted">Agreements, demands, receipts</p></Link>
      <Link to={`/portal/${caseId}/help`} className="rounded-2xl bg-white p-5 ring-1 ring-line hover:ring-forest-700"><p className="font-semibold">Help &amp; Requests</p><p className="text-sm text-muted">Contacts and how to reach us</p></Link>
    </div>
    <div className="grid gap-4 sm:grid-cols-2">
      <Card title="Agreement"><p className="text-sm">{d.agreement}</p></Card>
      <Card title="Next appointment"><p className="text-sm">{d.next_appointment ? `${d.next_appointment.what}, ${new Date(d.next_appointment.when).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}${d.next_appointment.where ? ` at ${d.next_appointment.where}` : ""}` : "None scheduled"}</p></Card>
    </div>
  </>;
}

function Payments() {
  const q = useCaseData("payments"); const { caseId } = useParams();
  if (!q.data) return <Loading q={q} />;
  const p = q.data;
  return <>
    <h1 className="font-display text-2xl text-forest-900">My Payments</h1>
    <Card><p><Badge tone={STATUS_TONE[p.headline] ?? "muted"}>{human(p.headline)}</Badge></p>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">{([["Total cost", p.total_consideration], ["Paid (confirmed)", p.total_paid], ["Received, being confirmed", p.pending_reconciliation], ["Balance", p.outstanding]] as const)
        .map(([l, v]) => <div key={l}><dt className="text-xs text-muted">{l}</dt><dd className="font-semibold tabular-nums">{inr(v as number)}</dd></div>)}</dl></Card>
    <Card title="Payment schedule"><div className="overflow-x-auto"><table className="w-full min-w-[560px] text-sm"><caption className="sr-only">Payment schedule</caption>
      <thead className="text-xs text-muted"><tr>{["Stage", "Amount", "Paid", "Due date", "Status"].map((h) => <th key={h} scope="col" className="py-1 text-left font-normal">{h}</th>)}</tr></thead>
      <tbody>{p.stages.map((s: Any) => <tr key={s.stage} className="border-t border-line"><th scope="row" className="py-2 text-left font-normal">{s.stage}</th><td className="tabular-nums">{inr(s.amount)}</td>
        <td className="tabular-nums">{inr(s.paid)}</td><td>{s.due_date ? fdate(s.due_date) : "—"}</td><td><Badge tone={STATUS_TONE[s.status] ?? "muted"}>{human(s.status)}</Badge></td></tr>)}</tbody></table></div>
      <p className="mt-2 text-xs text-muted">A payment is shown as overdue only after its due date has passed. Payments you’ve made show as “being confirmed” until our finance team matches them with the bank.</p></Card>
    <Card title="Receipts">{p.receipts.length === 0 ? <p className="text-sm text-muted">No payments yet.</p> : <ul className="divide-y divide-line text-sm">{p.receipts.map((r: Any) =>
      <li key={r.receipt_no} className="flex flex-wrap items-center justify-between gap-2 py-2"><span>{r.receipt_no} · {fdate(r.date)} · {r.mode.toUpperCase()}</span><span className="flex items-center gap-2 tabular-nums">{inr(r.amount)} <Badge tone={STATUS_TONE[r.status] ?? "muted"}>{human(r.status)}</Badge></span></li>)}</ul>}
      <p className="mt-2 text-xs text-muted">For a statement of account, ask under <Link to={`/portal/${caseId}/help`} className="underline">Help Centre</Link>.</p></Card>
  </>;
}

function Documents() {
  const q = useCaseData("documents"); const { caseId } = useParams();
  if (!q.data) return <Loading q={q} />;
  return <><h1 className="font-display text-2xl text-forest-900">My Documents</h1>
    <Card>{q.data.length === 0 ? <p className="text-sm text-muted">Documents we share with you will appear here.</p> : <ul className="divide-y divide-line text-sm">{q.data.map((d: Any) =>
      <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span><b>{d.title}</b><span className="block text-xs text-muted">{d.category}{d.date ? ` · ${fdate(d.date)}` : ""}</span></span>
        <a href={`/api/portal/cases/${caseId}/documents/${d.id}/file`} className="inline-flex min-h-10 items-center rounded-lg px-3 ring-1 ring-line hover:bg-forest-50">Download</a></li>)}</ul>}
      <p className="mt-3 text-xs text-muted">Downloads are only available while you’re signed in.</p></Card></>;
}

function Agreement() {
  const q = useCaseData("agreement"); const { caseId } = useParams();
  if (!q.data) return <Loading q={q} />;
  const a = q.data;
  return <><h1 className="font-display text-2xl text-forest-900">My Agreement</h1><Card><dl className="space-y-2 text-sm">
    <div><dt className="text-xs text-muted">Status</dt><dd className="font-semibold">{a.status}</dd></div>
    {a.registration_no && <div><dt className="text-xs text-muted">Registration</dt><dd>{a.registration_no}, {fdate(a.registered_on)}</dd></div>}
    {a.final_document_id && <div><a href={`/api/portal/cases/${caseId}/documents/${a.final_document_id}/file`} className="inline-flex min-h-10 items-center rounded-lg px-3 ring-1 ring-line hover:bg-forest-50">Download the registered agreement</a></div>}
  </dl></Card></>;
}

function Property() {
  const q = useCaseData("property");
  if (!q.data) return <Loading q={q} />;
  const p = q.data;
  return <><h1 className="font-display text-2xl text-forest-900">My Property</h1><Card><dl className="grid gap-3 text-sm sm:grid-cols-2">
    {([["Project", p.project], ["Tower", p.tower], ["Floor", p.floor], ["Unit", p.unit], ["Type", p.type?.toUpperCase()], ["Carpet area", p.carpet_sqft ? `${p.carpet_sqft} sq ft` : null],
      ["Booked on", fdate(p.booking_date)], ["Booking reference", p.booking_ref], ["Parking", p.parking ?? "Allotted at possession"]] as const)
      .map(([l, v]) => <div key={l}><dt className="text-xs text-muted">{l}</dt><dd className="font-medium">{v ?? "—"}</dd></div>)}
    <div className="sm:col-span-2"><dt className="text-xs text-muted">Owners</dt><dd>{p.owners.map((o: Any) => `${o.name}${o.share ? ` (${o.share}%)` : ""}`).join(", ")}</dd></div>
  </dl></Card></>;
}

function Updates() {
  const q = useCaseData("updates");
  if (!q.data) return <Loading q={q} />;
  return <><h1 className="font-display text-2xl text-forest-900">Project Updates</h1>
    {q.data.length === 0 ? <Card><p className="text-sm text-muted">No updates yet.</p></Card> : q.data.map((u: Any) => <Card key={u.id} title={u.title}>
      <p className="text-xs text-muted">{fdate(u.published_at)}{u.corrected ? " · corrected" : ""}</p><p className="mt-2 whitespace-pre-wrap text-sm">{u.body}</p>
      {u.photos.length > 0 && <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">{u.photos.map((p: Any) => <img key={p.id} src={p.url} alt={`${u.title}: ${p.name}`} className="aspect-video w-full rounded-lg object-cover" loading="lazy" />)}</div>}
    </Card>)}</>;
}

function Notifications() {
  const q = useCaseData("notifications");
  if (!q.data) return <Loading q={q} />;
  return <><h1 className="font-display text-2xl text-forest-900">Notifications</h1><Card>{q.data.length === 0 ? <p className="text-sm text-muted">Messages we send you will appear here.</p> :
    <ul className="divide-y divide-line text-sm">{q.data.map((m: Any, i: number) => <li key={i} className="py-2"><p className="font-medium">{m.subject ?? m.what}</p><p className="text-xs text-muted">{fdate(m.at)} · {m.channel}</p>
      <details className="mt-1 text-xs"><summary className="cursor-pointer text-forest-800">Read</summary><p className="mt-1 whitespace-pre-wrap">{m.body}</p></details></li>)}</ul>}</Card></>;
}

function Profile() {
  const q = useCaseData("profile"); const { caseId } = useParams();
  const [f, setF] = useState({ field: "mobile", new_value: "", note: "" }); const [done, setDone] = useState<string | null>(null);
  const send = useMutation({ mutationFn: async () => (await papi.post(`/cases/${caseId}/profile/change-request`, { ...f, note: f.note || null })).data, onSuccess: (d) => { setDone(`${d.message} Reference ${d.request_no}.`); setF({ field: "mobile", new_value: "", note: "" }); } });
  if (!q.data) return <Loading q={q} />;
  const p = q.data;
  return <><h1 className="font-display text-2xl text-forest-900">My Profile</h1>
    <Card><dl className="grid gap-3 text-sm sm:grid-cols-2">{([["Name", p.name], ["Email", p.email], ["Mobile", p.mobile], ["Address for letters", p.correspondence_address]] as const)
      .map(([l, v]) => <div key={l}><dt className="text-xs text-muted">{l}</dt><dd className="font-medium">{v ?? "—"}</dd></div>)}
      <div className="sm:col-span-2"><dt className="text-xs text-muted">We may contact you by</dt><dd>{[p.contact.email && "email", p.contact.sms && "SMS", p.contact.whatsapp && "WhatsApp"].filter(Boolean).join(", ") || "—"}</dd></div></dl></Card>
    <Card title="Request a change"><p className="mb-3 text-sm text-muted">{p.note}</p>
      {done && <p className="mb-3 rounded-lg bg-forest-50 p-3 text-sm">{done}</p>}{send.isError && <Alert>{msg(send.error)}</Alert>}
      <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); send.mutate(); }}>
        <SelectInput label="What should change?" value={f.field} onChange={(e) => setF({ ...f, field: e.target.value })}>
          {[["mobile", "Mobile number"], ["email", "Email address"], ["correspondence_address", "Address for letters"], ["contact_preferences", "How we contact you"], ["name", "Name"], ["other", "Something else"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectInput>
        <TextInput label="New details" value={f.new_value} onChange={(e) => setF({ ...f, new_value: e.target.value })} maxLength={500} />
        <TextArea label="Note (optional)" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} rows={2} maxLength={1000} />
        <Button type="submit" loading={send.isPending} disabled={f.new_value.trim().length < 2}>Send request</Button>
      </form></Card></>;
}

function Help() {
  const q = useCaseData("help");
  if (!q.data) return <Loading q={q} />;
  const h = q.data;
  return <><h1 className="font-display text-2xl text-forest-900">Help Centre</h1>
    <Card title="Your relationship executive">{h.relationship_executive ? <p className="text-sm">{h.relationship_executive.name} · <a className="underline" href={`mailto:${h.relationship_executive.email}`}>{h.relationship_executive.email}</a></p> : <p className="text-sm text-muted">Being assigned.</p>}</Card>
    <Card title="If you need to escalate"><p className="mb-2 text-sm text-muted">{h.escalation_note}</p><ul className="text-sm">{h.escalation.map((m: Any) => <li key={m.email}>{m.name} · <a className="underline" href={`mailto:${m.email}`}>{m.email}</a></li>)}</ul></Card>
    {h.maintenance_contacts && <Card title="Maintenance"><p className="text-sm">{h.maintenance_contacts}</p></Card>}
    <Card title="Frequently asked questions"><dl className="space-y-3 text-sm">{h.faqs.map((f: Any) => <div key={f.q}><dt className="font-medium">{f.q}</dt><dd className="text-muted">{human(f.a)}</dd></div>)}</dl></Card></>;
}

function Security() {
  const q = useQuery({ queryKey: ["portal-sessions"], queryFn: async () => (await papi.get<Any[]>("/sessions")).data });
  const out = useMutation({ mutationFn: async () => (await papi.post("/sessions/sign-out-others")).data, onSuccess: () => void q.refetch() });
  if (!q.data) return <Loading q={q} />;
  return <><h1 className="font-display text-2xl text-forest-900">Security</h1>
    <Card title="Where you’re signed in"><ul className="divide-y divide-line text-sm">{q.data.map((s: Any, i: number) => <li key={i} className="py-2"><p className="font-medium">{s.this_device ? "This device" : "Another device"}</p>
      <p className="text-xs text-muted">{(s.device ?? "").slice(0, 80)} · last active {new Date(s.last_seen).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</p></li>)}</ul>
      {q.data.length > 1 && <Button variant="secondary" className="mt-3" loading={out.isPending} onClick={() => out.mutate()}>Sign out everywhere else</Button>}
      <p className="mt-3 text-xs text-muted">You’re signed out automatically after an hour without activity. Lost access to your email? Contact your relationship executive to update it.</p></Card></>;
}

export function PortalApp() {
  const [qc] = useState(newClient); // a fresh cache each time the portal starts: no data carried over between customers
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/portal/sign-in" element={<SignIn />} />
          <Route path="/portal" element={<Shell><div /></Shell>} />
          {MENU.map(([path]) => <Route key={path} path={`/portal/:caseId${path ? `/${path}` : ""}`}
            element={<Shell>{{ "": <Home />, payments: <Payments />, documents: <Documents />, agreement: <Agreement />, property: <Property />, updates: <Updates />,
              notifications: <Notifications />, profile: <Profile />, help: <Help />, security: <Security /> }[path]}</Shell>} />)}
          <Route path="*" element={<Navigate to="/portal" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
