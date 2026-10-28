import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";
import { Alert, Button, Modal, SelectInput, TextArea, TextInput } from "../ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useCreateBooking } from "../../hooks/useBookings";
import { useInventory } from "../../hooks/useInventory";
import { useAssignableUsers, useProjects } from "../../hooks/useLeads";
import { api, errorMessage } from "../../lib/api";
import { PAYMENT_LABELS, PAYMENT_MODES } from "../../lib/bookings";
import type { PaymentMode } from "../../lib/bookings";
import { UNIT_TYPE_LABELS } from "../../lib/inventory";
import type { Unit } from "../../lib/inventory";
import { formatMobile, formatRupees } from "../../lib/leads";
import { CustomerFields, customerPayload, emptyCustomer } from "./CustomerFields";
import type { CustomerForm } from "./CustomerFields";

type BookableUnit = Unit & { building?: string };

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

/** Record a booking: pick an available flat from the project's inventory and enter the deal. */
type LeadPick = { id: number; name: string; mobile?: string; email?: string | null; project?: { id: number } | null; assigned_to?: { id: number } | null };

/** Search open leads by name, phone or lead ID (POST body, so phone numbers stay out of URLs). */
function LeadPicker({ onPick }: { onPick: (l: LeadPick) => void }) {
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  useEffect(() => { const t = setTimeout(() => setTerm(q.trim()), 300); return () => clearTimeout(t); }, [q]);
  const found = useQuery({
    queryKey: ["leads", "pick", term],
    queryFn: async () => (await api.post<{ items: (LeadPick & { lead_code: string; status: string })[] }>("/leads/search", { q: term, page_size: 8 })).data.items,
    enabled: term.length >= 2,
  });
  return (
    <div className="space-y-2">
      <TextInput label="Customer (lead)" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name, mobile or lead ID" autoFocus />
      {term.length >= 2 && found.data && (found.data.length === 0
        ? <p className="text-sm text-muted">No matching lead. Add the customer under Leads first.</p>
        : <ul className="divide-y divide-line rounded-lg ring-1 ring-line">
            {found.data.filter((l) => l.status !== "booked").map((l) => (
              <li key={l.id}><button type="button" onClick={() => onPick(l)} className="block w-full px-3 py-2 text-left text-sm hover:bg-paper">
                <b>{l.name}</b> <span className="text-xs text-muted">{l.lead_code}{l.mobile ? ` · ${formatMobile(l.mobile)}` : ""}</span>
              </button></li>
            ))}
          </ul>)}
    </div>
  );
}

export function BookFlatDialog({ lead: givenLead, unit: givenUnit, onClose }: {
  lead?: LeadPick;
  unit?: Unit;
  onClose: () => void;
}) {
  const [picked, setPicked] = useState<LeadPick | null>(givenLead ?? null);
  const lead = picked ?? { id: 0, name: "", project: null, assigned_to: null };
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const navigate = useNavigate();
  const projects = useProjects();
  const people = useAssignableUsers(isManager);
  const create = useCreateBooking();
  const [projectId, setProjectId] = useState(givenUnit ? String(givenUnit.project_id) : givenLead?.project ? String(givenLead.project.id) : "");
  const inventory = useInventory(Number(projectId) || 0);
  const [unitId, setUnitId] = useState(givenUnit ? String(givenUnit.id) : "");
  const [cust, setCust] = useState<CustomerForm>(emptyCustomer({ customer_name: givenLead?.name ?? null, customer_mobile: givenLead?.mobile ?? null, customer_email: givenLead?.email ?? null }));
  const [price, setPrice] = useState("");
  const [paid, setPaid] = useState("");
  const [date, setDate] = useState(today());
  const [mode, setMode] = useState<PaymentMode | "">("");
  const [ref, setRef] = useState("");
  const [partner, setPartner] = useState("");
  const [notes, setNotes] = useState("");
  const [handler, setHandler] = useState(givenLead?.assigned_to ? String(givenLead.assigned_to.id) : "");

  // Flats that can be booked: available, or on hold for this customer (or with an expired hold)
  const units = useMemo((): BookableUnit[] => {
    const inv = inventory.data;
    if (!inv) return [];
    const all: BookableUnit[] = [...inv.buildings.flatMap((b) => b.floors.flatMap((f) => f.units.map((u) => ({ ...u, building: b.name })))), ...inv.listings];
    return all.filter((u) => u.status === "available" || (u.status === "on_hold" && (u.hold_expired || u.held_for?.id === lead.id)));
  }, [inventory.data, lead.id]);
  const unit = givenUnit ?? units.find((u) => String(u.id) === unitId);
  const rupees = (v: string) => Math.round(Number(v.replace(/,/g, "")));
  const priceOk = rupees(price) > 0;
  const paidOk = paid.trim() === "" || (rupees(paid) >= 0 && rupees(paid) <= rupees(price));
  const pct = inventory.data?.project.commission_pct ? Number(inventory.data.project.commission_pct) : null;

  useEffect(() => {
    const ask = givenUnit?.current_asking_price ?? givenUnit?.base_price;
    if (givenUnit && ask) setPrice((p) => p || String(ask));
  }, [givenUnit]);

  function pickLead(l: LeadPick) {
    setPicked(l);
    setCust((c) => ({ ...c, customer_name: c.customer_name || l.name, customer_mobile: c.customer_mobile || l.mobile || "", customer_email: c.customer_email || l.email || "" }));
    if (l.assigned_to) setHandler(String(l.assigned_to.id));
  }

  function pick(id: string) {
    setUnitId(id);
    const u = units.find((x) => String(x.id) === id);
    const ask = u?.current_asking_price ?? u?.base_price;
    if (u && ask && !price) setPrice(String(ask));
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    create.mutate({
      lead_id: lead.id, unit_id: Number(unitId), booking_date: date, agreed_price: rupees(price), booking_amount: paid.trim() ? rupees(paid) : 0,
      payment_mode: mode || undefined, payment_reference: ref.trim() || undefined, channel_partner: partner.trim() || undefined,
      notes: notes.trim() || undefined, sales_exec_id: isManager && handler ? Number(handler) : undefined,
      customer: customerPayload(cust),
    }, { onSuccess: (b) => { onClose(); navigate(`/bookings/${b.id}`); } });
  }

  return (
    <Modal title={givenUnit ? `Book unit ${givenUnit.unit_no}` : `Book a flat for ${lead.name}`} onClose={onClose}>
      <form className="space-y-4" noValidate onSubmit={submit}>
        {create.isError && <Alert>{errorMessage(create.error)}</Alert>}
        {!givenLead && (picked
          ? <p className="rounded-lg bg-paper px-3 py-2 text-sm">Customer: <b>{picked.name}</b> <button type="button" className="ml-2 text-forest-800 underline" onClick={() => setPicked(null)}>Change</button></p>
          : <LeadPicker onPick={pickLead} />)}
        {!givenUnit && <SelectInput label="Project" value={projectId} onChange={(e) => { setProjectId(e.target.value); setUnitId(""); }}>
          <option value="" disabled>Choose a project</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </SelectInput>}
        {projectId && !givenUnit && (
          <SelectInput label="Flat" value={unitId} onChange={(e) => pick(e.target.value)}
            hint={inventory.isSuccess && units.length === 0 ? "No flats available to book in this project" : "Only flats that can be booked are listed"}>
            <option value="" disabled>{inventory.isPending ? "Loading flats…" : "Choose a flat"}</option>
            {units.map((u) => (
              <option key={u.id} value={u.id}>
                {[u.building, u.floor_number !== null ? `Floor ${u.floor_number}` : null, `Unit ${u.unit_no}`, UNIT_TYPE_LABELS[u.unit_type],
                  u.carpet_sqft ? `${Number(u.carpet_sqft)} sq ft` : null, u.status === "on_hold" ? "on hold for this customer" : null].filter(Boolean).join(" · ")}
              </option>
            ))}
          </SelectInput>
        )}
        {unit && (<>
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Agreed price (₹)" inputMode="numeric" value={price} onChange={(e) => setPrice(e.target.value)}
              hint={priceOk ? formatRupees(rupees(price)) : "Enter the final agreed price"} />
            <TextInput label="Booking amount paid (₹)" inputMode="numeric" value={paid} onChange={(e) => setPaid(e.target.value)}
              hint={!paidOk ? "Can’t be more than the agreed price" : paid ? formatRupees(rupees(paid)) : "Token / booking amount"} />
          </div>
          {priceOk && paidOk && (
            <p className="rounded-lg bg-paper px-3 py-2 text-sm">
              Balance {formatRupees(rupees(price) - (paid ? rupees(paid) : 0))}
              {pct !== null && <> · Flatons commission ({pct}%) ≈ <b>{formatRupees(Math.round((rupees(price) * pct) / 100))}</b></>}
            </p>
          )}
          <div className="grid grid-cols-2 gap-3">
            <TextInput label="Booking date" type="date" value={date} max={today()} onChange={(e) => setDate(e.target.value)} />
            <SelectInput label="Payment mode" value={mode} onChange={(e) => setMode(e.target.value as PaymentMode | "")}>
              <option value="">Not recorded</option>{PAYMENT_MODES.map((m) => <option key={m} value={m}>{PAYMENT_LABELS[m]}</option>)}
            </SelectInput>
          </div>
          <TextInput label="Payment reference (optional)" value={ref} onChange={(e) => setRef(e.target.value)} maxLength={100} placeholder="e.g. cheque no., UTR" />
          <TextInput label="Channel partner (optional)" value={partner} onChange={(e) => setPartner(e.target.value)} maxLength={150} />
          {isManager && (
            <SelectInput label="Handled by" value={handler} onChange={(e) => setHandler(e.target.value)}>
              <option value="">Me</option>{people.data?.filter((p) => p.id !== me.id).map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
            </SelectInput>
          )}
          <TextArea label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={5000} />
          <CustomerFields f={cust} set={(patch) => setCust({ ...cust, ...patch })} />
        </>)}
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" loading={create.isPending} disabled={!unit || !lead.id || !priceOk || !paidOk || !date}>Record booking</Button>
        </div>
      </form>
    </Modal>
  );
}
