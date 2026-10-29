import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileSignature } from "lucide-react";
import { Alert, Button, Modal, TextInput } from "../ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { api, errorMessage } from "../../lib/api";
import type { Booking } from "../../lib/bookings";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const day = (d: string) => new Date(d + "T00:00:00").toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });

/** Sale agreement: marked done (with its date) by managers and admins; the unit then shows "Agreement done". */
export function AgreementSection({ booking, compact = false }: { booking: Booking; compact?: boolean }) {
  const me = useCurrentUser();
  const qc = useQueryClient();
  const canEdit = (me.role === "admin" || me.role === "manager") && booking.status === "booked";
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(today());
  const refresh = (b: Booking) => {
    qc.setQueryData(["bookings", b.id], b);
    for (const k of [["bookings"], ["inventory"], ["projects"], ["dashboard"], ["cost-sheet"]]) void qc.invalidateQueries({ queryKey: k });
  };
  const mark = useMutation({ mutationFn: async () => (await api.post<Booking>(`/bookings/${booking.id}/agreement`, { agreement_date: date })).data,
    onSuccess: (b) => { refresh(b); setOpen(false); } });
  const undo = useMutation({ mutationFn: async () => (await api.delete<Booking>(`/bookings/${booking.id}/agreement`)).data, onSuccess: refresh });
  const done = booking.agreement_date;
  return (
    <section aria-label="Agreement" className={compact ? "mt-2 border-t border-line pt-2" : "mt-4 rounded-xl bg-white p-5 ring-1 ring-line"}>
      {!compact && <h2 className="mb-2 font-semibold">Agreement</h2>}
      {undo.isError && <Alert>{errorMessage(undo.error)}</Alert>}
      {done ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm"><FileSignature className="mr-1 inline size-4 text-forest-800" aria-hidden /><b>Agreement done</b> on {day(done)}</p>
          {canEdit && <Button variant="ghost" loading={undo.isPending} onClick={() => undo.mutate()}>Undo</Button>}
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm text-muted">Agreement not signed yet.</p>
          {canEdit && <Button variant={compact ? "secondary" : "primary"} onClick={() => setOpen(true)}><FileSignature className="size-4" aria-hidden />Mark agreement done</Button>}
        </div>
      )}
      {open && (
        <Modal title="Mark agreement done" onClose={() => setOpen(false)}>
          <div className="space-y-4">
            {mark.isError && <Alert>{errorMessage(mark.error)}</Alert>}
            <p className="text-sm">Unit {booking.unit.unit_no} at {booking.project.name} will show as <b>Agreement done</b>.</p>
            <TextInput label="Agreement date" type="date" value={date} min={booking.booking_date} max={today()} onChange={(e) => setDate(e.target.value)} />
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
              <Button loading={mark.isPending} disabled={!date} onClick={() => mark.mutate()}>Mark agreement done</Button>
            </div>
          </div>
        </Modal>
      )}
    </section>
  );
}
