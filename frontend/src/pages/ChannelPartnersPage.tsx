import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, Pencil, Plus, Search } from "lucide-react";
import { Alert, Badge, Button, ErrorState, Modal, PageHeader, TextArea, TextInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useChannelPartner, useChannelPartners, usePartnerCustomers, useSavePartner } from "../hooks/useChannelPartners";
import type { ChannelPartner } from "../hooks/useChannelPartners";
import { errorMessage, formatDateTime } from "../lib/api";
import { STATUS_LABELS, formatMobile, formatRupees } from "../lib/leads";

function PartnerDialog({ partner, onClose, onSaved }: { partner?: ChannelPartner; onClose: () => void; onSaved?: (p: ChannelPartner) => void }) {
  const save = useSavePartner();
  const [f, setF] = useState({
    name: partner?.name ?? "", company_name: partner?.company_name ?? "", mobile: partner?.mobile ?? "", email: partner?.email ?? "",
    rera_number: partner?.rera_number ?? "", notes: partner?.notes ?? "",
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const v = (x: string) => x.trim() || null;
  return (
    <Modal title={partner ? `Edit ${partner.name}` : "Add channel partner"} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate({ id: partner?.id, name: f.name.trim(), company_name: v(f.company_name), mobile: f.mobile.trim(), email: v(f.email),
          rera_number: v(f.rera_number), notes: v(f.notes) }, { onSuccess: (p) => { onSaved?.(p); onClose(); } });
      }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <TextInput label="Name" value={f.name} onChange={set("name")} maxLength={150} autoFocus />
          <TextInput label="Company name" value={f.company_name} onChange={set("company_name")} maxLength={150} />
          <TextInput label="Mobile number" type="tel" value={f.mobile} onChange={set("mobile")} maxLength={20} />
          <TextInput label="Email (optional)" type="email" value={f.email} onChange={set("email")} maxLength={254} />
        </div>
        <TextInput label="RERA number (optional)" value={f.rera_number} onChange={set("rera_number")} maxLength={50} placeholder="e.g. A52100012345" />
        <TextArea label="Notes (optional)" value={f.notes} onChange={set("notes")} rows={2} maxLength={5000} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!f.name.trim() || f.mobile.trim().length < 10}>{partner ? "Save" : "Add partner"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export function ChannelPartnersPage() {
  const me = useCurrentUser();
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [adding, setAdding] = useState(false);
  useEffect(() => { const t = setTimeout(() => setTerm(q.trim()), 250); return () => clearTimeout(t); }, [q]);
  const list = useChannelPartners(term, showInactive);
  const isManager = me.role === "admin" || me.role === "manager";
  return (
    <>
      <PageHeader title="Channel partners" description="Brokers and agencies who bring customers, and the customers they brought."
        action={<Button onClick={() => setAdding(true)}><Plus className="size-4" aria-hidden />Add partner</Button>} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted" aria-hidden />
          <label htmlFor="cp-search" className="sr-only">Search by name, company or RERA number</label>
          <input id="cp-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, company or RERA number"
            className="min-h-11 w-full rounded-lg border border-line bg-white pl-9 text-sm" />
        </div>
        {isManager && <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />Show inactive</label>}
      </div>
      {list.isPending && <div className="h-40 animate-pulse rounded-xl bg-white" />}
      {list.isError && <ErrorState message={errorMessage(list.error)} onRetry={() => void list.refetch()} />}
      {list.data && list.data.length === 0 && (
        <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">{term ? "No partner matches that search." : "No channel partners yet. Add your first one."}</p>
      )}
      {list.data && list.data.length > 0 && (<>
        <ul className="space-y-2 md:hidden">
          {list.data.map((p) => (
            <li key={p.id}><Link to={`/channel-partners/${p.id}`} className="block rounded-xl bg-white p-4 ring-1 ring-line">
              <p className="font-medium text-forest-900">{p.name} {!p.is_active && <Badge tone="muted">Inactive</Badge>}</p>
              <p className="text-sm text-muted">{p.company_name ?? "—"}{p.rera_number ? ` · RERA ${p.rera_number}` : ""}</p>
              <p className="mt-1 text-sm">{formatMobile(p.mobile)} · {p.leads} customers · {p.bookings} booked</p>
            </Link></li>
          ))}
        </ul>
        <div className="hidden overflow-x-auto rounded-xl bg-white ring-1 ring-line md:block">
          <table className="w-full text-sm">
            <caption className="sr-only">Channel partners</caption>
            <thead className="text-xs text-muted"><tr>
              {["Name", "Company", "Contact", "RERA number", "Customers", "Booked"].map((h, i) => <th key={h} scope="col" className={cx("px-4 py-2 font-normal", i >= 4 ? "text-right" : "text-left")}>{h}</th>)}
            </tr></thead>
            <tbody>{list.data.map((p) => (
              <tr key={p.id} className="cursor-pointer border-t border-line hover:bg-paper" onClick={() => navigate(`/channel-partners/${p.id}`)}>
                <th scope="row" className="px-4 py-3 text-left font-normal"><Link to={`/channel-partners/${p.id}`} className="font-medium text-forest-900 hover:underline">{p.name}</Link>
                  {!p.is_active && <> <Badge tone="muted">Inactive</Badge></>}</th>
                <td className="px-4 py-3">{p.company_name ?? "—"}</td>
                <td className="px-4 py-3">{formatMobile(p.mobile)}{p.email && <span className="block text-xs text-muted">{p.email}</span>}</td>
                <td className="px-4 py-3">{p.rera_number ?? "—"}</td>
                <td className="px-4 py-3 text-right tabular-nums">{p.leads}</td>
                <td className="px-4 py-3 text-right tabular-nums">{p.bookings}{p.booked_value > 0 && <span className="block text-xs text-muted">{formatRupees(p.booked_value)}</span>}</td>
              </tr>))}</tbody>
          </table>
        </div>
      </>)}
      {adding && <PartnerDialog onClose={() => setAdding(false)} onSaved={(p) => navigate(`/channel-partners/${p.id}`)} />}
    </>
  );
}

export function ChannelPartnerDetailPage() {
  const id = Number(useParams().partnerId);
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const partner = useChannelPartner(id);
  const customers = usePartnerCustomers(id);
  const save = useSavePartner();
  const [tab, setTab] = useState<"details" | "customers">("details");
  const [editing, setEditing] = useState(false);
  if (partner.isPending) return <div className="h-64 animate-pulse rounded-xl bg-white" />;
  if (partner.isError) return <ErrorState message={errorMessage(partner.error, "Couldn’t load this partner.")} onRetry={() => void partner.refetch()} />;
  const p = partner.data;
  const row = (label: string, value: React.ReactNode) => <div><dt className="text-xs text-muted">{label}</dt><dd className="font-medium">{value ?? <span className="font-normal text-muted">—</span>}</dd></div>;
  return (
    <>
      <Link to="/channel-partners" className="mb-3 inline-flex items-center gap-1 text-sm text-forest-800 hover:underline"><ArrowLeft className="size-4" aria-hidden />All channel partners</Link>
      <PageHeader title={p.name} description={[p.company_name, p.rera_number ? `RERA ${p.rera_number}` : null].filter(Boolean).join(" · ") || "Channel partner"}
        action={isManager ? <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="size-4" aria-hidden />Edit</Button> : undefined} />
      {!p.is_active && <div className="mb-4"><Alert>This partner is inactive and can’t be chosen on new leads.</Alert></div>}
      <div role="tablist" aria-label="Channel partner" className="mb-5 flex gap-1 rounded-xl bg-white p-1 ring-1 ring-line sm:max-w-md">
        {([["details", "Partner details"], ["customers", `Customers (${p.leads})`]] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={cx("min-h-11 flex-1 rounded-lg text-sm", tab === k ? "bg-forest-900 text-white" : "hover:bg-forest-50")}>{label}</button>
        ))}
      </div>
      {tab === "details" && (
        <section role="tabpanel" aria-label="Partner details" className="rounded-xl bg-white p-5 ring-1 ring-line">
          <dl className="grid grid-cols-1 gap-4 text-sm sm:grid-cols-2">
            {row("Name", p.name)}
            {row("Company name", p.company_name)}
            {row("Mobile", <a href={`tel:${p.mobile}`} className="hover:underline">{formatMobile(p.mobile)}</a>)}
            {row("Email", p.email ? <a href={`mailto:${p.email}`} className="hover:underline">{p.email}</a> : null)}
            {row("RERA number", p.rera_number)}
            {row("Customers brought", `${p.leads} · ${p.bookings} booked${p.booked_value ? ` (${formatRupees(p.booked_value)})` : ""}`)}
          </dl>
          {p.notes && <p className="mt-4 text-sm whitespace-pre-wrap">{p.notes}</p>}
          {isManager && (
            <div className="mt-5 border-t border-line pt-4">
              {save.isError && <div className="mb-2"><Alert>{errorMessage(save.error)}</Alert></div>}
              <Button variant={p.is_active ? "ghost" : "secondary"} loading={save.isPending} onClick={() => save.mutate({ id: p.id, is_active: !p.is_active })}>
                {p.is_active ? "Mark inactive" : "Make active again"}</Button>
            </div>
          )}
        </section>
      )}
      {tab === "customers" && (
        <section role="tabpanel" aria-label="Customers">
          {customers.isPending && <div className="h-40 animate-pulse rounded-xl bg-white" />}
          {customers.isError && <ErrorState message={errorMessage(customers.error)} onRetry={() => void customers.refetch()} />}
          {customers.data && customers.data.items.length === 0 && (
            <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">
              No customers yet. Choose this partner on a lead whose source is Channel partner.
            </p>
          )}
          {customers.data && customers.data.items.length > 0 && (
            <div className="overflow-x-auto rounded-xl bg-white ring-1 ring-line">
              <table className="w-full min-w-[720px] text-sm">
                <caption className="sr-only">Customers brought by {p.name}</caption>
                <thead className="text-xs text-muted"><tr>
                  {["Customer", "Mobile", "Project", "Status", "Handled by", "Booking"].map((h) => <th key={h} scope="col" className="px-4 py-2 text-left font-normal">{h}</th>)}
                </tr></thead>
                <tbody>{customers.data.items.map((c) => (
                  <tr key={c.lead_id} className="border-t border-line">
                    <th scope="row" className="px-4 py-3 text-left font-normal"><Link to={`/leads/${c.lead_id}`} className="font-medium text-forest-900 hover:underline">{c.name}</Link>
                      <span className="block text-xs text-muted">{c.lead_code} · added {formatDateTime(c.created_at)}</span></th>
                    <td className="px-4 py-3 whitespace-nowrap"><a href={`tel:${c.mobile}`} className="hover:underline">{formatMobile(c.mobile)}</a></td>
                    <td className="px-4 py-3">{c.project ?? "—"}</td>
                    <td className="px-4 py-3"><Badge tone={c.status === "booked" ? "gold" : "neutral"}>{STATUS_LABELS[c.status]}</Badge></td>
                    <td className="px-4 py-3">{c.owner?.full_name ?? "Unassigned"}</td>
                    <td className="px-4 py-3">{c.booking_id
                      ? <><Link to={`/bookings/${c.booking_id}`} className="font-medium text-forest-800 hover:underline">{c.booking_code}</Link>
                          <span className="block text-xs text-muted">{c.booked_project} · Unit {c.unit_no} · {formatRupees(c.agreed_price ?? 0)}</span></>
                      : <span className="text-muted">—</span>}</td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {editing && <PartnerDialog partner={p} onClose={() => setEditing(false)} />}
    </>
  );
}
