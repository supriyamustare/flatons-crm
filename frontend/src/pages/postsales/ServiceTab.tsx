import { useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, TextInput } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { useCurrentUser } from "../../hooks/useAuth";
import { STATUS, slaBadge, useTickets } from "../../hooks/useTickets";
import type { TicketDetail } from "../../hooks/useTickets";
import { api, errorMessage, formatDateTime } from "../../lib/api";

const NO_RAISE = ["auditor", "management"];

export function ServiceTab({ caseId }: { caseId: number }) {
  const me = useCurrentUser(); const q = useTickets({ view: "all", case_id: caseId });
  const qc = useQueryClient(); const toast = useToast(); const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ category: "payment", subcategory: "", title: "", description: "", priority: "normal", channel: "phone" });
  const [files, setFiles] = useState<File[]>([]);
  const raise = useMutation({
    mutationFn: async () => { const fd = new FormData(); for (const [k, v] of Object.entries(f)) if (v.trim()) fd.append(k, v.trim()); files.forEach((x) => fd.append("attachments", x));
      return (await api.post<TicketDetail>(`/post-sales/cases/${caseId}/tickets`, fd)).data; },
    onSuccess: (t) => { void qc.invalidateQueries({ queryKey: ["tickets"] }); toast(`${t.ticket_no} raised`); setOpen(false); navigate(`/service/${t.id}`); },
  });
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  return (
    <section role="tabpanel" aria-label="Service" className="space-y-3">
      {!NO_RAISE.includes(me.role) && <div className="flex justify-end"><Button onClick={() => setOpen(true)}><Plus className="size-4" aria-hidden />Raise ticket</Button></div>}
      {q.data && q.data.items.length === 0 && <p className="rounded-xl border border-dashed border-line bg-white px-6 py-8 text-center text-sm text-muted">No requests or complaints yet.</p>}
      <ul className="space-y-2">{q.data?.items.map((t) => { const b = slaBadge(t.sla, t.status === "closed"); return (
        <li key={t.id} className="rounded-xl bg-white p-3 text-sm ring-1 ring-line">
          <Link to={`/service/${t.id}`} className="font-semibold text-forest-900 underline">{t.ticket_no}: {t.title}</Link>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-muted">{t.category_label} · {STATUS[t.status]} · raised {formatDateTime(t.created_at)}{b && <Badge tone={b.tone}>{b.text}</Badge>}</p>
        </li>); })}</ul>
      {open && q.data && <Modal title="Raise a ticket" onClose={() => setOpen(false)}>
        <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); raise.mutate(); }}>
          {raise.isError && <Alert>{errorMessage(raise.error)}</Alert>}
          <div className="grid grid-cols-2 gap-3">
            <SelectInput label="Category" value={f.category} onChange={set("category")}>{Object.entries(q.data.categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</SelectInput>
            <TextInput label="Subcategory (optional)" value={f.subcategory} onChange={set("subcategory")} maxLength={120} />
            <SelectInput label="Priority" value={f.priority} onChange={set("priority")} hint="Urgent: safety-related, e.g. a dangerous defect">
              {[["urgent", "Urgent"], ["high", "High"], ["normal", "Normal"], ["low", "Low"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectInput>
            <SelectInput label="Received by" value={f.channel} onChange={set("channel")}>{[["phone", "Phone"], ["email", "Email"], ["whatsapp", "WhatsApp"], ["walk_in", "Walk-in"], ["letter", "Letter"], ["other", "Other"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}</SelectInput>
          </div>
          <TextInput label="Title" value={f.title} onChange={set("title")} maxLength={200} />
          <TextArea label="The customer’s issue or request" value={f.description} onChange={set("description")} rows={4} maxLength={5000} />
          <div className="space-y-1.5"><label htmlFor="tk-att" className="block text-sm font-medium">Attachments (optional)</label>
            <input id="tk-att" type="file" multiple accept=".pdf,.jpg,.jpeg,.png" onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 10))} className="block w-full text-sm file:mr-3 file:min-h-10 file:rounded-lg file:border-0 file:bg-forest-50 file:px-3" /></div>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" loading={raise.isPending} disabled={f.title.trim().length < 3 || f.description.trim().length < 5}>Raise ticket</Button></div>
        </form></Modal>}
    </section>
  );
}
