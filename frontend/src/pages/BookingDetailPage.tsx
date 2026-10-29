import { PREFERENCE_LABELS } from "../components/bookings/CustomerFields";
import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft } from "lucide-react";
import { Alert, Badge, Button, ErrorState, Modal, PageHeader, SelectInput, TextArea, TextInput } from "../components/ui";
import { useCurrentUser } from "../hooks/useAuth";
import { useBooking, useCancelBooking, useUpdateBooking } from "../hooks/useBookings";
import { errorMessage, formatDateTime } from "../lib/api";
import { HISTORY_LABELS, PAYMENT_LABELS, PAYMENT_MODES } from "../lib/bookings";
import type { Booking, PaymentMode } from "../lib/bookings";
import { UNIT_TYPE_LABELS } from "../lib/inventory";
import { formatMobile, formatRupees } from "../lib/leads";

const day = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });

function Card({ title, children }: { title: string; children: ReactNode }) {
  return <section className="rounded-xl bg-white p-5 ring-1 ring-line"><h2 className="mb-3 font-semibold">{title}</h2><dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">{children}</dl></section>;
}
function Row({ label, children }: { label: string; children: ReactNode }) {
  return <div><dt className="text-xs text-muted">{label}</dt><dd className="font-medium">{children ?? <span className="font-normal text-muted">—</span>}</dd></div>;
}

function EditDialog({ b, onClose }: { b: Booking; onClose: () => void }) {
  const save = useUpdateBooking();
  const [price, setPrice] = useState(String(b.agreed_price));
  const [paid, setPaid] = useState(String(b.booking_amount));
  const [date, setDate] = useState(b.booking_date);
  const [mode, setMode] = useState<PaymentMode | "">(b.payment_mode ?? "");
  const [ref, setRef] = useState(b.payment_reference ?? "");
  const [partner, setPartner] = useState(b.channel_partner ?? "");
  const [received, setReceived] = useState(String(b.commission_received));
  const [notes, setNotes] = useState(b.notes ?? "");
  const n = (v: string) => Math.round(Number(v.replace(/,/g, "")));
  const ok = n(price) > 0 && n(paid) >= 0 && n(paid) <= n(price) && n(received) >= 0;
  return (
    <Modal title={`Edit ${b.booking_code}`} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate({ id: b.id, agreed_price: n(price), booking_amount: n(paid), booking_date: date, payment_mode: mode || null,
          payment_reference: ref.trim() || null, channel_partner: partner.trim() || null, commission_received: n(received), notes: notes.trim() || null },
          { onSuccess: onClose });
      }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Agreed price (₹)" inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value)} hint={n(price) > 0 ? formatRupees(n(price)) : undefined} />
          <TextInput label="Booking amount (₹)" inputMode="numeric" value={paid} onChange={(e) => setPaid(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <TextInput label="Booking date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <SelectInput label="Payment mode" value={mode} onChange={(e) => setMode(e.target.value as PaymentMode | "")}>
            <option value="">Not recorded</option>{PAYMENT_MODES.map((m) => <option key={m} value={m}>{PAYMENT_LABELS[m]}</option>)}
          </SelectInput>
        </div>
        <TextInput label="Payment reference" value={ref} onChange={(e) => setRef(e.target.value)} maxLength={100} />
        <TextInput label="Channel partner" value={partner} onChange={(e) => setPartner(e.target.value)} maxLength={150} />
        <TextInput label="Commission received (₹)" inputMode="numeric" value={received} onChange={(e) => setReceived(e.target.value)}
          hint={b.commission_expected !== null ? `Expected ${formatRupees(b.commission_expected)} (recalculated if the price changes)` : undefined} />
        <TextArea label="Notes" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={5000} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending} disabled={!ok}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}

function CancelDialog({ b, onClose }: { b: Booking; onClose: () => void }) {
  const cancel = useCancelBooking();
  const [reason, setReason] = useState("");
  return (
    <Modal title={`Cancel ${b.booking_code}?`} onClose={onClose}>
      <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); cancel.mutate({ id: b.id, reason: reason.trim() }, { onSuccess: onClose }); }}>
        <p className="text-sm">Unit {b.unit.unit_no} at {b.project.name} becomes available again, and {b.lead.name} moves back to Negotiation.</p>
        {cancel.isError && <Alert>{errorMessage(cancel.error)}</Alert>}
        <TextInput label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus maxLength={255} placeholder="e.g. Loan not approved" />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Keep booking</Button>
          <Button type="submit" variant="danger" loading={cancel.isPending} disabled={reason.trim().length < 3}>Cancel booking</Button>
        </div>
      </form>
    </Modal>
  );
}

export function BookingDetailPage() {
  const id = Number(useParams().bookingId);
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const booking = useBooking(id);
  const [dialog, setDialog] = useState<"edit" | "cancel" | null>(null);
  if (booking.isPending) return <div className="h-64 animate-pulse rounded-xl bg-white" />;
  if (booking.isError) return <ErrorState message={errorMessage(booking.error, "Couldn’t load this booking.")} onRetry={() => void booking.refetch()} />;
  const b = booking.data;
  const live = b.status === "booked";
  return (
    <>
      <Link to="/bookings" className="mb-3 inline-flex items-center gap-1 text-sm text-forest-800 hover:underline"><ArrowLeft className="size-4" aria-hidden />All bookings</Link>
      <PageHeader title={`${b.booking_code}: ${b.lead.name}`}
        description={`${b.project.name} · ${b.unit.building ? `${b.unit.building} · ` : ""}Unit ${b.unit.unit_no} · booked ${day(b.booking_date)}`}
        action={isManager && live ? (
          <div className="flex gap-2">
            <a href={`/cost-sheet/${b.unit.id}`} target="_blank" rel="noopener" className="inline-flex min-h-11 items-center rounded-lg bg-white px-4 text-sm font-medium ring-1 ring-line hover:bg-forest-50">Print cost sheet</a>
            <Button variant="secondary" onClick={() => setDialog("edit")}>Edit details</Button>
            <Button variant="danger" onClick={() => setDialog("cancel")}>Cancel booking</Button>
          </div>) : undefined} />
      {!live && <div className="mb-4"><Alert>Cancelled {b.cancelled_at ? formatDateTime(b.cancelled_at) : ""}: {b.cancellation_reason}</Alert></div>}
      <div className="mb-4 flex items-center gap-2">{live ? <Badge tone="gold">Booked</Badge> : <Badge tone="muted">Cancelled</Badge>}</div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Customer">
          <Row label="Name"><Link to={`/leads/${b.lead.id}`} className="text-forest-800 underline">{b.lead.name}</Link></Row>
          <Row label="Lead ID">{b.lead.lead_code}</Row>
          <Row label="Mobile"><a href={`tel:${b.lead.mobile}`} className="hover:underline">{formatMobile(b.lead.mobile)}</a></Row>
          <Row label="Email">{b.lead.email}</Row>
          <Row label="City">{b.lead.city}</Row>
        </Card>
        <Card title="Flat">
          <Row label="Project">{b.project.name}</Row>
          <Row label="Building / floor">{[b.unit.building, b.unit.floor_number !== null ? `Floor ${b.unit.floor_number}` : null].filter(Boolean).join(", ") || null}</Row>
          <Row label="Unit">{b.unit.unit_no} · {UNIT_TYPE_LABELS[b.unit.unit_type]}</Row>
          <Row label="Carpet / built-up">{b.unit.carpet_sqft ? `${Number(b.unit.carpet_sqft)} / ${b.unit.builtup_sqft ? Number(b.unit.builtup_sqft) : "—"} sq ft` : null}</Row>
          {b.unit.address_note && <Row label="Address">{b.unit.address_note}</Row>}
        </Card>
        <Card title="Deal and payment">
          <Row label="Agreed price">{formatRupees(b.agreed_price)}</Row>
          <Row label="Booking amount paid">{formatRupees(b.booking_amount)}</Row>
          <Row label="Balance">{formatRupees(b.balance)}</Row>
          <Row label="Booking date">{day(b.booking_date)}</Row>
          <Row label="Payment mode">{b.payment_mode ? PAYMENT_LABELS[b.payment_mode] : null}</Row>
          <Row label="Reference">{b.payment_reference}</Row>
        </Card>
        <Card title="Customer and payment">
          <Row label="Name">{b.customer.customer_name}</Row>
          <Row label="Applicant name">{b.customer.applicant_name}</Row>
          <Row label="Mobile">{b.customer.customer_mobile ? formatMobile(b.customer.customer_mobile) : null}</Row>
          <Row label="Email ID">{b.customer.customer_email}</Row>
          <Row label="Address">{b.customer.customer_address}</Row>
          <Row label="Payment preference">{b.customer.payment_preference ? PREFERENCE_LABELS[b.customer.payment_preference] : "Not decided"}</Row>
          {b.customer.payment_preference === "bank" && (<>
            <Row label="Bank">{b.customer.bank_name}</Row>
            <Row label="Banker contact">{[b.customer.banker_name, b.customer.banker_phone].filter(Boolean).join(" · ") || null}</Row>
          </>)}
        </Card>
        <Card title="People and commission">
          <Row label="Handled by">{b.sales_exec?.full_name}</Row>
          <Row label="Recorded by">{b.recorded_by?.full_name}</Row>
          <Row label="Channel partner">{b.partner
            ? <Link to={`/channel-partners/${b.partner.id}`} className="text-forest-800 underline">{b.partner.name}{b.partner.company_name ? ` (${b.partner.company_name})` : ""}</Link>
            : b.channel_partner}</Row>
          <Row label="Commission expected">{b.commission_expected !== null ? `${formatRupees(b.commission_expected)}${b.commission_pct ? ` (${Number(b.commission_pct)}%)` : ""}` : "Project has no commission % set"}</Row>
          <Row label="Commission received">{formatRupees(b.commission_received)}</Row>
        </Card>
      </div>
      {b.notes && <section className="mt-4 rounded-xl bg-white p-5 ring-1 ring-line"><h2 className="mb-2 font-semibold">Notes</h2><p className="text-sm whitespace-pre-wrap">{b.notes}</p></section>}
      <section className="mt-4 rounded-xl bg-white p-5 ring-1 ring-line" aria-labelledby="hist-h">
        <h2 id="hist-h" className="mb-3 font-semibold">History</h2>
        <ol className="space-y-2 text-sm">
          {b.history.map((h, i) => (
            <li key={i}><b>{HISTORY_LABELS[h.action] ?? h.action}</b>{h.action === "cancelled" && h.details?.reason ? `: ${String(h.details.reason)}` : ""}
              <span className="block text-xs text-muted">{h.actor?.full_name ?? "System"}, {formatDateTime(h.at)}</span></li>
          ))}
        </ol>
      </section>
      {dialog === "edit" && <EditDialog b={b} onClose={() => setDialog(null)} />}
      {dialog === "cancel" && <CancelDialog b={b} onClose={() => setDialog(null)} />}
    </>
  );
}
