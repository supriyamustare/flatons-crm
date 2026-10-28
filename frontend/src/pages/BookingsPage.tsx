import { useState } from "react";
import { Link } from "react-router";
import { Download } from "lucide-react";
import { BookFlatDialog } from "../components/bookings/BookFlatDialog";
import { Badge, Button, ErrorState, PageHeader, SelectInput, TextInput, cx } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { bookingsExportUrl, useBookings } from "../hooks/useBookings";
import type { BookingQuery } from "../hooks/useBookings";
import { useAssignableUsers, useProjects } from "../hooks/useLeads";
import { errorMessage, formatDateTime } from "../lib/api";
import type { BookingStatus, MissingDetails } from "../lib/bookings";
import { UNIT_TYPE_LABELS } from "../lib/inventory";
import { formatMobile, formatRupees } from "../lib/leads";

const day = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });

function Total({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-white p-4 ring-1 ring-line"><p className="text-sm text-muted">{label}</p><p className="font-display text-2xl text-forest-900">{value}</p></div>;
}

export function BookingsPage() {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const canBook = me.role !== "docs";
  const projects = useProjects();
  const people = useAssignableUsers(isManager);
  const [q, setQ] = useState<BookingQuery>({ status: "booked", page: 1 });
  const [filling, setFilling] = useState<MissingDetails | null>(null);
  const set = (patch: Partial<BookingQuery>) => setQ({ ...q, ...patch, page: 1 });
  const list = useBookings(q);
  const d = list.data;

  return (
    <>
      <PageHeader title="Bookings" description={me.role === "executive" ? "Flats you have booked" : "Every flat booked, with the customer, price and who handled it"}
        action={isManager && d ? (
          <a href={bookingsExportUrl(q)} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-white px-4 text-sm font-medium ring-1 ring-line hover:bg-forest-50">
            <Download className="size-4" aria-hidden />Download CSV</a>) : undefined} />

      {d && d.missing_details.length > 0 && (
        <section aria-labelledby="missing-h" className="mb-5 rounded-xl border border-gold-300 bg-gold-100/50 p-4">
          <h2 id="missing-h" className="font-semibold">Details missing ({d.missing_details.length})</h2>
          <p className="mb-3 text-sm text-muted">These leads are marked Booked but have no flat or price recorded. Add the booking details.</p>
          <ul className="space-y-2">
            {d.missing_details.map((m) => (
              <li key={m.lead_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 ring-1 ring-line">
                <div>
                  <Link to={`/leads/${m.lead_id}`} className="font-medium text-forest-900 hover:underline">{m.name}</Link>
                  <span className="block text-xs text-muted">{m.lead_code} · {m.project?.name ?? "No project"} · {m.assigned_to?.full_name ?? "Unassigned"} · booked {formatDateTime(m.booked_since)}</span>
                </div>
                {canBook && <Button variant="secondary" onClick={() => setFilling(m)}>Add booking details</Button>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {d && (
        <section aria-label="Totals" className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Total label={q.status === "cancelled" ? "Cancelled bookings" : "Bookings"} value={String(d.totals.count)} />
          <Total label="Total agreed value" value={formatRupees(d.totals.agreed_value)} />
          <Total label="Booking amounts received" value={formatRupees(d.totals.booking_amount)} />
          <Total label="Commission received / expected" value={`${formatRupees(d.totals.commission_received)} / ${formatRupees(d.totals.commission_expected)}`} />
        </section>
      )}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="w-full sm:w-40"><SelectInput label="Status" value={q.status ?? ""} onChange={(e) => set({ status: e.target.value as BookingStatus | "" })}>
          <option value="booked">Booked</option><option value="cancelled">Cancelled</option><option value="">All</option>
        </SelectInput></div>
        <div className="w-full sm:w-52"><SelectInput label="Project" value={q.project_id ?? ""} onChange={(e) => set({ project_id: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">All projects</option>{projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput></div>
        {isManager && <div className="w-full sm:w-52"><SelectInput label="Handled by" value={q.sales_exec_id ?? ""} onChange={(e) => set({ sales_exec_id: e.target.value ? Number(e.target.value) : undefined })}>
          <option value="">Everyone</option>{people.data?.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
        </SelectInput></div>}
        <div className="w-[calc(50%-0.375rem)] sm:w-40"><TextInput label="Booked from" type="date" value={q.date_from ?? ""} onChange={(e) => set({ date_from: e.target.value || undefined })} /></div>
        <div className="w-[calc(50%-0.375rem)] sm:w-40"><TextInput label="Booked to" type="date" value={q.date_to ?? ""} onChange={(e) => set({ date_to: e.target.value || undefined })} /></div>
      </div>

      {list.isPending && <div className="h-48 animate-pulse rounded-xl bg-white" />}
      {list.isError && <ErrorState message={errorMessage(list.error, "Couldn’t load bookings.")} onRetry={() => void list.refetch()} />}
      {d && d.items.length === 0 && (
        <p className="rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center text-muted">
          No bookings match these filters.{canBook && " Record one from a lead’s page with Book a flat."}
        </p>
      )}
      {d && d.items.length > 0 && (
        <div className={cx(list.isPlaceholderData && "opacity-60")}>
          <ul className="space-y-2 md:hidden">
            {d.items.map((b) => (
              <li key={b.id}><Link to={`/bookings/${b.id}`} className="block rounded-xl bg-white p-4 ring-1 ring-line">
                <div className="flex items-start justify-between gap-2">
                  <div><p className="font-medium text-forest-900">{b.lead.name}</p>
                    <p className="text-sm text-muted">{b.project.name} · {b.unit.building ? `${b.unit.building}, ` : ""}Unit {b.unit.unit_no}</p></div>
                  {b.status === "cancelled" ? <Badge tone="muted">Cancelled</Badge> : <Badge tone="gold">Booked</Badge>}
                </div>
                <p className="mt-2 text-sm"><b>{formatRupees(b.agreed_price)}</b> · {day(b.booking_date)} · {b.sales_exec?.full_name ?? "—"}</p>
              </Link></li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto rounded-xl bg-white ring-1 ring-line md:block">
            <table className="w-full text-sm">
              <caption className="sr-only">Bookings</caption>
              <thead className="text-xs text-muted"><tr>
                {["Booking", "Customer", "Flat", "Agreed price", "Paid", "Booked on", "Handled by", "Status"].map((h, i) => (
                  <th key={h} scope="col" className={cx("px-3 py-2 font-normal whitespace-nowrap", i >= 3 && i <= 4 ? "text-right" : "text-left")}>{h}</th>))}
              </tr></thead>
              <tbody>{d.items.map((b) => (
                <tr key={b.id} className="border-t border-line">
                  <th scope="row" className="px-3 py-2.5 text-left font-normal"><Link to={`/bookings/${b.id}`} className="font-medium text-forest-900 hover:underline">{b.booking_code}</Link></th>
                  <td className="px-3 py-2.5">{b.lead.name}<span className="block text-xs text-muted">{formatMobile(b.lead.mobile)}</span></td>
                  <td className="px-3 py-2.5">{b.project.name}<span className="block text-xs text-muted">{b.unit.building ? `${b.unit.building} · ` : ""}{b.unit.floor_number !== null ? `Floor ${b.unit.floor_number} · ` : ""}Unit {b.unit.unit_no} · {UNIT_TYPE_LABELS[b.unit.unit_type]}</span></td>
                  <td className="px-3 py-2.5 text-right font-medium tabular-nums">{formatRupees(b.agreed_price)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{formatRupees(b.booking_amount)}</td>
                  <td className="px-3 py-2.5 whitespace-nowrap">{day(b.booking_date)}</td>
                  <td className="px-3 py-2.5">{b.sales_exec?.full_name ?? "—"}</td>
                  <td className="px-3 py-2.5">{b.status === "cancelled" ? <Badge tone="muted">Cancelled</Badge> : <Badge tone="gold">Booked</Badge>}</td>
                </tr>))}</tbody>
            </table>
          </div>
          {d.total > d.page_size && (
            <div className="mt-4 flex items-center justify-between text-sm text-muted">
              <span>{(d.page - 1) * d.page_size + 1}–{Math.min(d.page * d.page_size, d.total)} of {d.total}</span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={d.page === 1} onClick={() => setQ({ ...q, page: d.page - 1 })}>Previous</Button>
                <Button variant="secondary" disabled={d.page * d.page_size >= d.total} onClick={() => setQ({ ...q, page: d.page + 1 })}>Next</Button>
              </div>
            </div>
          )}
        </div>
      )}
      {filling && <BookFlatDialog lead={{ id: filling.lead_id, name: filling.name, project: filling.project, assigned_to: filling.assigned_to }} onClose={() => setFilling(null)} />}
    </>
  );
}
