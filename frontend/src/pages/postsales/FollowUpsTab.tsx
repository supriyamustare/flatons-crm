import { useState } from "react";
import type { FormEvent } from "react";
import { Alert, Badge, Button, SelectInput, TextArea, TextInput } from "../../components/ui";
import { useToast } from "../../components/Toast";
import { CHANNELS, OUTCOMES, useAddFollowUp, useFollowUps } from "../../hooks/useFollowUps";
import type { Channel, Outcome } from "../../hooks/useFollowUps";
import { inr } from "../../hooks/useLedger";
import { errorMessage, formatDateTime } from "../../lib/api";

const today = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
const PROMISE_TONE = { open: "gold", kept: "neutral", broken: "muted" } as const;
const PROMISE_LABEL = { open: "Promise open", kept: "Promise kept", broken: "Promise broken" } as const;

export function FollowUpsTab({ caseId }: { caseId: number }) {
  const q = useFollowUps(caseId); const add = useAddFollowUp(caseId); const toast = useToast();
  const blank = { channel: "call" as Channel, outcome: "reached" as Outcome, note: "", demand_id: "", contacted_on: today(), promise_amount: "", promise_date: "", next_follow_up_on: "" };
  const [f, setF] = useState(blank);
  if (q.isPending) return <div className="h-40 animate-pulse rounded-xl bg-white" />;
  if (q.isError) return <Alert>{errorMessage(q.error)}</Alert>;
  const d = q.data;
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const promised = f.outcome === "promised";
  const amount = Math.round(Number(f.promise_amount.replace(/[,₹\s]/g, "")) || 0);
  const ok = !promised || (amount > 0 && f.promise_date);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate({ channel: f.channel, outcome: f.outcome, note: f.note.trim() || null, demand_id: f.demand_id ? Number(f.demand_id) : null, contacted_on: f.contacted_on,
      promise_amount: promised ? amount : null, promise_date: promised ? f.promise_date : null, next_follow_up_on: f.next_follow_up_on || null },
      { onSuccess: () => { toast(promised ? `Promise of ${inr(amount)} by ${f.promise_date} recorded` : "Follow-up logged"); setF({ ...blank, contacted_on: today() }); } });
  };
  return (
    <section role="tabpanel" aria-label="Follow-ups" className="grid gap-4 lg:grid-cols-[2fr_3fr]">
      {d.can_write && (
        <form onSubmit={submit} aria-label="Log a follow-up" className="space-y-3 self-start rounded-xl bg-white p-4 ring-1 ring-line">
          <h3 className="font-semibold">Log a follow-up</h3>
          {d.outstanding > 0 && <p className="text-sm text-muted">Currently demanded and unpaid: <b className="text-ink">{inr(d.outstanding)}</b></p>}
          {add.isError && <Alert>{errorMessage(add.error)}</Alert>}
          <div className="grid grid-cols-2 gap-3">
            <SelectInput label="How" value={f.channel} onChange={set("channel")}>{(Object.keys(CHANNELS) as Channel[]).map((c) => <option key={c} value={c}>{CHANNELS[c]}</option>)}</SelectInput>
            <SelectInput label="Outcome" value={f.outcome} onChange={set("outcome")}>{(Object.keys(OUTCOMES) as Outcome[]).map((o) => <option key={o} value={o}>{OUTCOMES[o]}</option>)}</SelectInput>
            <TextInput label="Contacted on" type="date" value={f.contacted_on} max={today()} onChange={set("contacted_on")} />
            {d.demands.length > 0 && <SelectInput label="About demand (optional)" value={f.demand_id} onChange={set("demand_id")}><option value="">—</option>
              {d.demands.map((x) => <option key={x.id} value={x.id}>{x.demand_no} · {x.stage_name}</option>)}</SelectInput>}
          </div>
          {promised && <div className="grid grid-cols-2 gap-3 rounded-lg bg-gold-100/50 p-3">
            <TextInput label="Promised amount (₹)" inputMode="numeric" value={f.promise_amount} onChange={set("promise_amount")} />
            <TextInput label="Promised by" type="date" value={f.promise_date} min={today()} onChange={set("promise_date")} /></div>}
          <TextArea label="Note" value={f.note} onChange={set("note")} rows={3} maxLength={2000} placeholder="What was said" />
          <TextInput label="Next follow-up (optional)" type="date" value={f.next_follow_up_on} min={today()} onChange={set("next_follow_up_on")} hint="You’ll get a reminder that morning" />
          <div className="flex justify-end"><Button type="submit" loading={add.isPending} disabled={!ok}>Save follow-up</Button></div>
        </form>
      )}
      <div className={d.can_write ? "" : "lg:col-span-2"}>
        {d.items.length === 0 ? <p className="rounded-xl border border-dashed border-line bg-white px-6 py-8 text-center text-sm text-muted">No follow-ups yet.</p> : (
          <ol className="space-y-2" aria-label="Follow-up history">
            {d.items.map((x) => (
              <li key={x.id} className="rounded-xl bg-white p-3 text-sm ring-1 ring-line">
                <p className="font-medium">{CHANNELS[x.channel]} · {OUTCOMES[x.outcome]} {x.promise_status && <Badge tone={PROMISE_TONE[x.promise_status]}>{PROMISE_LABEL[x.promise_status]}</Badge>}</p>
                {x.promise_amount && <p>Promised {inr(x.promise_amount)} by {x.promise_date}</p>}
                {x.note && <p className="mt-1 whitespace-pre-wrap">{x.note}</p>}
                <p className="mt-1 text-xs text-muted">{x.contacted_on}{x.demand_no ? ` · ${x.demand_no}` : ""}{x.next_follow_up_on ? ` · next follow-up ${x.next_follow_up_on}` : ""} · {x.by?.full_name ?? "—"}, {formatDateTime(x.created_at)}</p>
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
