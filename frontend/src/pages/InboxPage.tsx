import { useState } from "react";
import { Link } from "react-router";
import { Inbox as InboxIcon, Phone } from "lucide-react";
import { Alert, Badge, Button, ErrorState, PageHeader, cx } from "../components/ui";
import { useAssignFromInbox, useInbox } from "../hooks/useInbox";
import type { InboxItem } from "../hooks/useInbox";
import { useAssignableUsers } from "../hooks/useLeads";
import { errorMessage } from "../lib/api";
import { SOURCE_LABELS, formatMobile } from "../lib/leads";
import type { LeadSource } from "../lib/leads";

function ago(iso: string, now = Date.now()): string {
  const mins = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60_000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

function Row({ item, people, onAssign, busy }: {
  item: InboxItem; people: { id: number; full_name: string }[]; onAssign: (userId: number) => void; busy: boolean;
}) {
  const [who, setWho] = useState("");
  const waiting = Date.now() - new Date(item.created_at).getTime() > 60 * 60_000;
  return (
    <li className={cx("rounded-xl border bg-white p-4", waiting ? "border-gold-300" : "border-line")}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Link to={`/leads/${item.id}`} className="font-medium text-forest-900 hover:underline">{item.name}</Link>
          <p className="text-sm text-muted">
            <Badge>{SOURCE_LABELS[item.source as LeadSource] ?? item.source}</Badge>{" "}
            {item.sub_source && <span>{item.sub_source} · </span>}
            <span className={cx(waiting && "font-medium text-gold-600")}>{ago(item.created_at)}</span>
          </p>
        </div>
        <a href={`tel:${item.mobile}`} className="inline-flex min-h-10 items-center gap-1.5 rounded-lg px-3 text-sm text-forest-800 ring-1 ring-line hover:bg-forest-50">
          <Phone className="size-4" aria-hidden />{formatMobile(item.mobile)}
        </a>
      </div>
      {item.message && <p className="mt-2 rounded-lg bg-paper px-3 py-2 text-sm whitespace-pre-wrap">{item.message}</p>}
      {(item.project || item.campaign) && (
        <p className="mt-1 text-xs text-muted">{[item.project?.name, item.campaign?.name].filter(Boolean).join(" · ")}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <select aria-label={`Assign ${item.name} to`} value={who} onChange={(e) => setWho(e.target.value)}
          className="min-h-11 flex-1 rounded-lg border border-line bg-white px-3 text-sm sm:max-w-64">
          <option value="">Choose a person…</option>
          {people.map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
        </select>
        <Button disabled={!who} loading={busy} onClick={() => onAssign(Number(who))}>Assign</Button>
      </div>
    </li>
  );
}

export function InboxPage() {
  const inbox = useInbox();
  const people = useAssignableUsers(true);
  const assign = useAssignFromInbox();
  const [busyId, setBusyId] = useState<number | null>(null);
  const items = inbox.data?.items ?? [];

  return (
    <>
      <PageHeader title="New enquiries"
        description="Enquiries from your website, portals and ads arrive here. Hand each one to a person; they’re notified straight away." />
      {assign.isError && <div className="mb-4"><Alert>{errorMessage(assign.error, "Couldn’t assign that lead. Try again.")}</Alert></div>}
      {inbox.isPending && <div className="space-y-2">{[0, 1, 2].map((i) => <div key={i} className="h-36 animate-pulse rounded-xl bg-white" />)}</div>}
      {inbox.isError && <ErrorState message={errorMessage(inbox.error, "Couldn’t load new enquiries.")} onRetry={() => void inbox.refetch()} />}
      {inbox.isSuccess && items.length === 0 && (
        <div className="rounded-xl border border-dashed border-line bg-white px-6 py-12 text-center">
          <InboxIcon className="mx-auto size-8 text-forest-700" aria-hidden />
          <p className="mt-2 font-display text-xl text-forest-900">All caught up</p>
          <p className="mt-1 text-sm text-muted">New enquiries will appear here automatically.</p>
        </div>
      )}
      {items.length > 0 && (
        <>
          <p className="mb-3 text-sm text-muted" aria-live="polite">
            {inbox.data!.count} waiting{inbox.data!.count > items.length ? `, showing the newest ${items.length}` : ""}. Waiting more than an hour is highlighted.
          </p>
          <ul className="space-y-2">
            {items.map((item) => (
              <Row key={item.id} item={item} people={people.data ?? []} busy={busyId === item.id && assign.isPending}
                onAssign={(userId) => { setBusyId(item.id); assign.mutate({ leadId: item.id, userId }); }} />
            ))}
          </ul>
        </>
      )}
    </>
  );
}
