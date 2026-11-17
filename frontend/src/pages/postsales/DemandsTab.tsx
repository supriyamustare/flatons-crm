import { useState } from "react";
import type { FormEvent } from "react";
import { FileText, Plus } from "lucide-react";
import { Alert, Badge, Button, Modal, SelectInput, TextArea, cx } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { DEMAND_STATUS, ISSUE_LABELS, useDemandAction, useDemands } from "../../hooks/useDemands";
import type { Demand, IssueMethod } from "../../hooks/useDemands";
import { inr } from "../../hooks/useLedger";
import { errorMessage } from "../../lib/api";

export function DemandsTab({ caseId }: { caseId: number }) {
  const q = useDemands(caseId); const act = useDemandAction(caseId); const toast = useToast();
  const [open, setOpen] = useState<null | { kind: "issue" | "return" | "cancel"; d: Demand }>(null);
  const [method, setMethod] = useState<IssueMethod>("email"); const [reason, setReason] = useState(""); const [reissue, setReissue] = useState(true);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const data = q.data;
  const done = (msg: string) => ({ onSuccess: () => { toast(msg); setOpen(null); setReason(""); } });
  const tone = (s: Demand["status"]) => (s === "issued" || s === "approved" ? "neutral" : s === "cancelled" ? "muted" : "gold") as "neutral" | "gold" | "muted";
  return (
    <section role="tabpanel" aria-label="Demands" className="space-y-4">
      {data.readiness && !data.readiness.ready && <Alert>Demand letters need the project’s details first: {data.readiness.missing.join(", ")}. An admin adds them under Projects → Legal &amp; bank details.</Alert>}
      {!data.ledger_approved && <p className="rounded-xl bg-white p-4 text-sm text-muted ring-1 ring-line">Demands are raised once the ledger is approved.</p>}
      {act.isError && <Alert>{errorMessage(act.error)}</Alert>}
      {data.can_create.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-xl bg-white p-3 text-sm ring-1 ring-line">
          <span className="text-muted">Demanded stages without a demand:</span>
          {data.can_create.map((s) => <Button key={s.seq} variant="ghost" loading={act.isPending} onClick={() => act.mutate({ body: { stage_seq: s.seq } }, { onSuccess: () => toast(`Draft demand created for ${s.name}`) })}>
            <Plus className="size-4" aria-hidden />{s.name} ({inr(s.outstanding)})</Button>)}
        </div>
      )}
      {data.demands.length === 0 ? <p className="rounded-xl border border-dashed border-line bg-white px-6 py-8 text-center text-sm text-muted">No demands yet. They’re drafted when a construction milestone is verified.</p> : (
        <ul className="space-y-3">
          {data.demands.map((d) => (
            <li key={d.id} className={cx("rounded-xl bg-white p-4 ring-1 ring-line", d.status === "cancelled" && "opacity-70")}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-semibold">{d.demand_no} · {d.stage_name} <Badge tone={tone(d.status)}>{DEMAND_STATUS[d.status]}</Badge>
                    {d.status === "issued" && <> <Badge tone={d.payment === "overdue" ? "gold" : "neutral"}>{d.payment === "paid" ? "Paid" : d.payment === "overdue" ? "Overdue" : d.payment === "part paid" ? "Part paid" : "Unpaid"}</Badge></>}</p>
                  <p className="text-sm">Total due <b>{inr(d.total_due)}</b> by <b>{d.due_date}</b> <span className="text-muted">(this stage {inr(d.stage_amount)}{d.previous_dues ? ` + earlier dues ${inr(d.previous_dues)}` : ""})</span></p>
                  <p className="text-xs text-muted">Demanded {d.demanded_on}{d.supersedes ? ` · replaces ${d.supersedes}` : ""}{d.submitted_by ? ` · submitted by ${d.submitted_by.full_name}` : ""}{d.approved_by ? ` · approved by ${d.approved_by.full_name}` : ""}{d.issued_by ? ` · issued by ${d.issued_by.full_name} (${ISSUE_LABELS[d.issue_method!]})` : ""}</p>
                  {d.note && d.status === "draft" && <p className="text-xs text-danger">Returned: {d.note}</p>}
                  {d.cancel_reason && <p className="text-xs text-danger">Cancelled: {d.cancel_reason}</p>}
                </div>
                <div className="flex flex-wrap gap-2">
                  <a href={`/demand-letter/${caseId}/${d.id}`} target="_blank" rel="noopener" className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-sm ring-1 ring-line hover:bg-forest-50"><FileText className="size-4" aria-hidden />Letter</a>
                  {d.can_submit && <Button loading={act.isPending} disabled={!data.readiness?.ready} onClick={() => act.mutate({ path: `/${d.id}/submit` }, { onSuccess: () => toast(`${d.demand_no} sent for approval`) })}>Submit for approval</Button>}
                  {d.can_approve && <><Button loading={act.isPending} onClick={() => act.mutate({ path: `/${d.id}/approve` }, { onSuccess: () => toast(`${d.demand_no} approved`) })}>Approve</Button>
                    <Button variant="secondary" onClick={() => setOpen({ kind: "return", d })}>Return</Button></>}
                  {d.status === "pending_approval" && !d.can_approve && <span className="self-center text-xs text-muted">Waiting for a finance approver</span>}
                  {d.can_issue && <Button onClick={() => setOpen({ kind: "issue", d })}>Mark issued</Button>}
                  {d.can_cancel && <Button variant="ghost" onClick={() => setOpen({ kind: "cancel", d })}>Cancel…</Button>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
      {open?.kind === "issue" && (
        <Modal title={`Issue ${open.d.demand_no}`} onClose={() => setOpen(null)}>
          <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault(); act.mutate({ path: `/${open.d.id}/issue`, body: { method } }, done(`${open.d.demand_no} issued`)); }}>
            <p className="text-sm">Print or save the letter, send it to the customer, then record how it was sent.</p>
            <SelectInput label="Sent by" value={method} onChange={(e) => setMethod(e.target.value as IssueMethod)}>
              {(Object.keys(ISSUE_LABELS) as IssueMethod[]).map((k) => <option key={k} value={k}>{ISSUE_LABELS[k]}</option>)}</SelectInput>
            <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(null)}>Cancel</Button><Button type="submit" loading={act.isPending}>Mark issued</Button></div>
          </form>
        </Modal>
      )}
      {(open?.kind === "return" || open?.kind === "cancel") && (
        <Modal title={open.kind === "return" ? `Return ${open.d.demand_no}` : `Cancel ${open.d.demand_no}`} onClose={() => setOpen(null)}>
          <form className="space-y-3" onSubmit={(e: FormEvent) => { e.preventDefault();
            act.mutate(open.kind === "return" ? { path: `/${open.d.id}/return`, body: { reason: reason.trim() } } : { path: `/${open.d.id}/cancel`, body: { reason: reason.trim(), reissue } },
              done(open.kind === "return" ? `${open.d.demand_no} returned to finance` : reissue ? `${open.d.demand_no} cancelled; a new version is drafted` : `${open.d.demand_no} cancelled`)); }}>
            <TextArea label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} maxLength={500} autoFocus />
            {open.kind === "cancel" && <label className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" className="size-4 accent-forest-900" checked={reissue} onChange={(e) => setReissue(e.target.checked)} />Draft a corrected new version</label>}
            {open.kind === "cancel" && <p className="text-xs text-muted">The cancelled demand stays on record; nothing is overwritten.</p>}
            <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setOpen(null)}>Back</Button>
              <Button type="submit" variant={open.kind === "cancel" ? "danger" : "primary"} loading={act.isPending} disabled={reason.trim().length < 3}>{open.kind === "return" ? "Return" : "Cancel demand"}</Button></div>
          </form>
        </Modal>
      )}
    </section>
  );
}
