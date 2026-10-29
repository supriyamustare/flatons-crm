import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Pencil, Printer, UserPlus } from "lucide-react";
import { Alert, Button, Modal, TextInput } from "../ui";
import { AgreementSection } from "../bookings/AgreementSection";
import { BookFlatDialog } from "../bookings/BookFlatDialog";
import { CustomerFields, PREFERENCE_LABELS, customerPayload, emptyCustomer } from "../bookings/CustomerFields";
import type { CustomerForm } from "../bookings/CustomerFields";
import { useCurrentUser } from "../../hooks/useAuth";
import { useBooking, useUpdateCustomer } from "../../hooks/useBookings";
import { api, errorMessage } from "../../lib/api";
import type { Unit } from "../../lib/inventory";
import { formatMobile, formatRupees } from "../../lib/leads";

export interface CostSheet {
  ready: boolean; missing: string[]; project: string; developer_name: string; site_address: string; rera_number: string;
  unit_no: string; unit_label: string; carpet_sqft: number | null; chargeable_sqft: number | null; rate_psf: number | null;
  cost: number; gst_pct: number; gst: number; stages: { name: string; pct: number; amount: number; gst: number }[];
  furnishing_per_sqft: number; furnishing: number; stamp_duty_pct: number; stamp_duty: number; registration_pct: number;
  registration_cap: number; registration: number; legal_charges: number; other_charges_label: string; other_charges: number;
  fees_total: number; grand_total: number; notes: string[]; signatory: string; overrides: Record<string, number | string>;
  customer: { name: string; applicant_name: string | null; mobile: string | null; email: string | null; address: string | null;
    booking_code: string; booking_date: string; payment_preference: "self" | "bank" | null; bank_name: string | null } | null;
}

export function useCostSheet(unitId: number, enabled = true) {
  return useQuery({ queryKey: ["cost-sheet", unitId], queryFn: async () => (await api.get<CostSheet>(`/units/${unitId}/cost-sheet`)).data, enabled });
}

function useInvalidateUnit() {
  const qc = useQueryClient();
  return () => { for (const k of [["inventory"], ["projects"], ["cost-sheet"], ["dashboard"]]) void qc.invalidateQueries({ queryKey: k }); };
}

const num = (v: string) => Number(v.replace(/,/g, ""));

/** Price and area, entered by hand (admins and managers). Rate x saleable area gives the asking price. */
export function PriceAndArea({ unit }: { unit: Unit }) {
  const me = useCurrentUser();
  const canEdit = me.role === "admin" || me.role === "manager";
  const refresh = useInvalidateUnit();
  const [editing, setEditing] = useState(false);
  const [carpet, setCarpet] = useState(""); const [saleable, setSaleable] = useState(""); const [rate, setRate] = useState("");
  useEffect(() => {
    setEditing(false);
    setCarpet(unit.carpet_sqft ? String(Number(unit.carpet_sqft)) : "");
    setSaleable(unit.builtup_sqft ? String(Number(unit.builtup_sqft)) : "");
    setRate(unit.rate_psf ? String(Number(unit.rate_psf)) : "");
  }, [unit]);
  const save = useMutation({
    mutationFn: async () => (await api.patch(`/units/${unit.id}`, {
      carpet_sqft: carpet ? num(carpet) : null, builtup_sqft: saleable ? num(saleable) : null, rate_psf: rate ? num(rate) : null,
    })).data,
    onSuccess: () => { setEditing(false); refresh(); },
  });
  const area = num(saleable) || num(carpet);
  const total = num(rate) > 0 && area > 0 ? Math.round(num(rate) * area) : null;
  const ok = (!carpet || num(carpet) > 0) && (!saleable || num(saleable) > 0) && (!rate || num(rate) > 0) && (!carpet || !saleable || num(saleable) >= num(carpet));

  if (!editing) {
    return (
      <section aria-labelledby="pa-h" className="mt-4 rounded-lg bg-paper p-3">
        <div className="flex items-center justify-between"><h3 id="pa-h" className="text-sm font-semibold">Price and area</h3>
          {canEdit && <Button variant="ghost" onClick={() => setEditing(true)}><Pencil className="size-4" aria-hidden />Edit</Button>}</div>
        <dl className="mt-1 grid grid-cols-2 gap-2 text-sm">
          <div><dt className="text-xs text-muted">Carpet area</dt><dd>{unit.carpet_sqft ? `${Number(unit.carpet_sqft)} sq ft` : "—"}</dd></div>
          <div><dt className="text-xs text-muted">Saleable area</dt><dd>{unit.builtup_sqft ? `${Number(unit.builtup_sqft)} sq ft` : "—"}</dd></div>
          <div><dt className="text-xs text-muted">Rate</dt><dd>{unit.rate_psf ? `${formatRupees(Number(unit.rate_psf))} / sq ft` : "—"}</dd></div>
          <div><dt className="text-xs text-muted">Price</dt><dd className="font-semibold">{unit.current_asking_price ? formatRupees(unit.current_asking_price) : "Not set"}</dd></div>
        </dl>
      </section>
    );
  }
  return (
    <form className="mt-4 space-y-3 rounded-lg bg-paper p-3" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate(); }}>
      <h3 className="text-sm font-semibold">Price and area</h3>
      {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
      <div className="grid grid-cols-2 gap-3">
        <TextInput label="Carpet area (sq ft)" inputMode="decimal" value={carpet} onChange={(e) => setCarpet(e.target.value)} />
        <TextInput label="Saleable area (sq ft)" inputMode="decimal" value={saleable} onChange={(e) => setSaleable(e.target.value)} hint="Charged area on the cost sheet" />
      </div>
      <TextInput label="Rate per sq ft (₹)" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)}
        hint={total ? `Price: ${formatRupees(total)} (rate × ${saleable ? "saleable" : "carpet"} area)` : "Price = rate × saleable area"} />
      {carpet && saleable && num(saleable) < num(carpet) && <p className="text-sm text-danger">Saleable area can’t be smaller than carpet area.</p>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={() => setEditing(false)}>Cancel</Button>
        <Button type="submit" loading={save.isPending} disabled={!ok}>Save</Button>
      </div>
    </form>
  );
}

function CustomerDialog({ bookingId, initial, onClose }: { bookingId: number; initial: CustomerForm; onClose: () => void }) {
  const save = useUpdateCustomer();
  const refresh = useInvalidateUnit();
  const [f, setF] = useState(initial);
  return (
    <Modal title="Customer and payment" onClose={onClose}>
      <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate({ id: bookingId, ...customerPayload(f) }, { onSuccess: () => { refresh(); onClose(); } }); }}>
        {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
        <CustomerFields f={f} set={(patch) => setF({ ...f, ...patch })} />
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={save.isPending}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}

/** Who the unit is booked for: customer details and payment preference. */
export function UnitCustomer({ unit }: { unit: Unit }) {
  const me = useCurrentUser();
  const booking = useBooking(unit.booking_id ?? 0);
  const enabled = Boolean(unit.booking_id);
  const [editing, setEditing] = useState(false);
  const [booking_, setBooking] = useState(false);
  const canBook = me.role !== "docs" && (unit.status === "available" || (unit.status === "on_hold" && (unit.hold_expired || unit.held_for)));
  if (!enabled) {
    return (
      <section aria-labelledby="cust-h" className="mt-4 rounded-lg bg-paper p-3">
        <h3 id="cust-h" className="text-sm font-semibold">Customer</h3>
        <p className="mt-1 text-sm text-muted">{unit.status === "booked" ? "Booked before booking records existed." : "Not booked yet."}</p>
        {canBook && <Button className="mt-2 w-full" onClick={() => setBooking(true)}><UserPlus className="size-4" aria-hidden />Book this unit</Button>}
        {booking_ && <BookFlatDialog unit={unit} onClose={() => setBooking(false)} />}
      </section>
    );
  }
  const b = booking.data;
  const c = b?.customer;
  const canEdit = b && b.status === "booked" && (me.role === "admin" || me.role === "manager" || b.sales_exec?.id === me.id);
  return (
    <section aria-labelledby="cust-h" className="mt-4 rounded-lg bg-paper p-3">
      <div className="flex items-center justify-between">
        <h3 id="cust-h" className="text-sm font-semibold">Customer</h3>
        {canEdit && <Button variant="ghost" onClick={() => setEditing(true)}><Pencil className="size-4" aria-hidden />Edit</Button>}
      </div>
      {booking.isPending && <p className="text-sm text-muted">Loading…</p>}
      {c && (
        <dl className="mt-1 space-y-1.5 text-sm">
          <div><dt className="text-xs text-muted">Name</dt><dd className="font-medium">{c.customer_name}</dd></div>
          <div><dt className="text-xs text-muted">Applicant name</dt><dd>{c.applicant_name ?? "—"}</dd></div>
          <div className="grid grid-cols-2 gap-2">
            <div><dt className="text-xs text-muted">Mobile</dt><dd>{c.customer_mobile ? <a href={`tel:${c.customer_mobile}`} className="hover:underline">{formatMobile(c.customer_mobile)}</a> : "—"}</dd></div>
            <div><dt className="text-xs text-muted">Email ID</dt><dd className="break-all">{c.customer_email ?? "—"}</dd></div>
          </div>
          <div><dt className="text-xs text-muted">Address</dt><dd className="whitespace-pre-wrap">{c.customer_address ?? "—"}</dd></div>
          <div className="border-t border-line pt-1.5"><dt className="text-xs text-muted">Payment preference</dt>
            <dd className="font-medium">{c.payment_preference ? PREFERENCE_LABELS[c.payment_preference] : "Not decided"}</dd></div>
          {c.payment_preference === "bank" && (
            <div className="rounded-md bg-white p-2 ring-1 ring-line">
              <dt className="sr-only">Bank</dt>
              <dd>{c.bank_name ?? "Bank not recorded"}</dd>
              <dd className="text-xs text-muted">Contact: {c.banker_name ?? "—"}{c.banker_phone ? ` · ${c.banker_phone}` : ""}</dd>
            </div>
          )}
          {b && <dd className="pt-1"><Link to={`/bookings/${b.id}`} className="text-sm font-medium text-forest-800 underline">View booking {b.booking_code}</Link></dd>}
        </dl>
      )}
      {b && b.status === "booked" && <AgreementSection booking={b} compact />}
      {editing && b && c && <CustomerDialog bookingId={b.id} initial={emptyCustomer(c)} onClose={() => setEditing(false)} />}
    </section>
  );
}

const OVERRIDE_FIELDS: { key: string; label: string; hint?: string }[] = [
  { key: "chargeable_sqft", label: "Chargeable area (sq ft)", hint: "Leave empty to use the saleable area" },
  { key: "furnishing_per_sqft", label: "Furnishing (₹ per sq ft)" },
  { key: "gst_pct", label: "GST (%)" },
  { key: "stamp_duty_pct", label: "Stamp duty (%)" },
  { key: "registration_pct", label: "Registration (%)" },
  { key: "registration_cap", label: "Registration maximum (₹)" },
  { key: "legal_charges", label: "Legal charges (₹)" },
  { key: "other_charges", label: "Other charges (₹)" },
];

/** This unit's cost sheet numbers; empty fields use the project's values. */
export function CostSheetEditDialog({ unit, onClose }: { unit: Unit; onClose: () => void }) {
  const sheet = useCostSheet(unit.id);
  const refresh = useInvalidateUnit();
  const [values, setValues] = useState<Record<string, string> | null>(null);
  const [label, setLabel] = useState("");
  const [rate, setRate] = useState("");
  useEffect(() => {
    if (sheet.data && values === null) {
      setValues(Object.fromEntries(OVERRIDE_FIELDS.map((f) => [f.key, sheet.data.overrides[f.key] !== undefined ? String(sheet.data.overrides[f.key]) : ""])));
      setLabel(String(sheet.data.overrides.other_charges_label ?? ""));
      setRate(unit.rate_psf ? String(Number(unit.rate_psf)) : "");
    }
  }, [sheet.data, values, unit.rate_psf]);
  const save = useMutation({
    mutationFn: async (body: Record<string, unknown>) => (await api.put<CostSheet>(`/units/${unit.id}/cost-sheet`, body)).data,
    onSuccess: () => { refresh(); onClose(); },
  });
  const project = sheet.data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = { rate_psf: rate ? num(rate) : null };
    for (const f of OVERRIDE_FIELDS) if (values?.[f.key]) body[f.key] = num(values[f.key]);
    if (label.trim()) body.other_charges_label = label.trim();
    save.mutate(body);
  };
  return (
    <Modal title={`Edit cost sheet: unit ${unit.unit_no}`} onClose={onClose}>
      {!values ? <p className="text-sm text-muted">Loading…</p> : (
        <form className="space-y-4" onSubmit={submit}>
          {save.isError && <Alert>{errorMessage(save.error)}</Alert>}
          <TextInput label="Rate per sq ft (₹)" inputMode="decimal" value={rate} onChange={(e) => setRate(e.target.value)} />
          <p className="text-xs text-muted">Leave a field empty to use the project’s value (shown as the placeholder).</p>
          <div className="grid grid-cols-2 gap-3">
            {OVERRIDE_FIELDS.map((f) => {
              const def = project ? ({ chargeable_sqft: "", furnishing_per_sqft: project.furnishing_per_sqft, gst_pct: project.gst_pct, stamp_duty_pct: project.stamp_duty_pct,
                registration_pct: project.registration_pct, registration_cap: project.registration_cap, legal_charges: project.legal_charges, other_charges: 0 } as Record<string, unknown>)[f.key] : "";
              return <TextInput key={f.key} label={f.label} inputMode="decimal" value={values[f.key]} placeholder={def === "" ? "" : String(def)}
                hint={f.hint} onChange={(e) => setValues({ ...values, [f.key]: e.target.value })} />;
            })}
          </div>
          <TextInput label="Name for other charges" value={label} onChange={(e) => setLabel(e.target.value)} maxLength={80} placeholder="e.g. Parking, club membership" />
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-between">
            <Button type="button" variant="ghost" onClick={() => save.mutate({})}>Use project values</Button>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
              <Button type="submit" loading={save.isPending}>Save cost sheet</Button>
            </div>
          </div>
        </form>
      )}
    </Modal>
  );
}

/** Print and edit buttons for the unit's cost sheet. */
export function CostSheetButtons({ unit }: { unit: Unit }) {
  const me = useCurrentUser();
  const canEdit = me.role === "admin" || me.role === "manager";
  const [editing, setEditing] = useState(false);
  return (
    <section aria-label="Cost sheet" className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
      <a href={`/cost-sheet/${unit.id}`} target="_blank" rel="noopener"
        className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white hover:bg-forest-800">
        <Printer className="size-4" aria-hidden />Print cost sheet
      </a>
      {canEdit && <Button variant="secondary" onClick={() => setEditing(true)}><FileSpreadsheet className="size-4" aria-hidden />Edit cost sheet</Button>}
      {editing && <CostSheetEditDialog unit={unit} onClose={() => setEditing(false)} />}
    </section>
  );
}
