import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { ArrowLeft, ArrowRightLeft, Pencil, Phone, StickyNote, Trash2, UserRoundCog } from "lucide-react";
import { DuplicateBanner, StatusBadge } from "../../components/leads/LeadBits";
import { AssignDialog, DeleteDialog, NoteDialog, StatusDialog } from "../../components/leads/LeadDialogs";
import { Button, ErrorState, Spinner } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useLead } from "../../hooks/useLeads";
import { errorMessage, formatDateTime } from "../../lib/api";
import {
  CONFIG_LABELS, FIELD_LABELS, PURPOSE_LABELS, SOURCE_LABELS, STATUS_LABELS, TIMELINE_LABELS,
  formatBudget, formatMobile, formatRupees,
} from "../../lib/leads";
import type { Activity, Duplicate, LeadDetail, LeadStatus } from "../../lib/leads";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{children ?? "—"}</dd>
    </div>
  );
}

function describe(a: Activity): ReactNode {
  const d = a.details ?? {};
  switch (a.type) {
    case "created": {
      const dups = d.possible_duplicates as string[] | undefined;
      return <>Created the lead{dups?.length ? <> (possible duplicate of {dups.join(", ")})</> : null}</>;
    }
    case "status_change":
      return (
        <>
          Changed status from <b>{STATUS_LABELS[d.from as LeadStatus]}</b> to <b>{STATUS_LABELS[d.to as LeadStatus]}</b>
          {d.reason ? <>: {String(d.reason)}</> : null}
        </>
      );
    case "assignment": {
      const to = d.to as { name: string } | null;
      const from = d.from as { name: string } | null;
      if (!to) return <>Unassigned the lead{from ? <> from {from.name}</> : null}</>;
      return from ? <>Reassigned from {from.name} to <b>{to.name}</b></> : <>Assigned to <b>{to.name}</b></>;
    }
    case "updated": {
      const fields = Object.keys((d.changes as Record<string, unknown>) ?? {}).map((k) => FIELD_LABELS[k] ?? k);
      return <>Updated {fields.join(", ")}</>;
    }
    case "note":
      return <>Added a note</>;
    default:
      return a.type;
  }
}

function Timeline({ activities }: { activities: Activity[] }) {
  return (
    <ol className="relative space-y-5 border-l border-line pl-5">
      {activities.map((a) => (
        <li key={a.id} className="relative">
          <span className={`absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-white ${a.type === "note" ? "bg-gold-500" : "bg-forest-700"}`} aria-hidden />
          <p className="text-sm text-ink">{describe(a)}</p>
          {a.note && <p className="mt-1 rounded-lg bg-paper px-3 py-2 text-sm whitespace-pre-wrap text-ink">{a.note}</p>}
          <p className="mt-1 text-xs text-muted">
            {a.actor?.full_name ?? "System"}, {formatDateTime(a.created_at)}
          </p>
        </li>
      ))}
    </ol>
  );
}

type DialogKind = "status" | "note" | "assign" | "delete";

function LeadView({ lead }: { lead: LeadDetail }) {
  const me = useCurrentUser();
  const navigate = useNavigate();
  const duplicates = (useLocation().state as { duplicates?: Duplicate[] } | null)?.duplicates ?? [];
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const isManager = me.role === "admin" || me.role === "manager";

  return (
    <>
      <Link to="/leads" className="mb-4 inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> All leads
      </Link>

      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs text-muted">{lead.lead_code}</p>
          <h1 className="font-display text-3xl text-forest-900">{lead.name}</h1>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
            <StatusBadge status={lead.status} />
            {lead.lost_reason && <span>{lead.lost_reason}</span>}
          </div>
        </div>
      </div>

      <div className="mb-6 flex flex-wrap gap-2">
        <a href={`tel:${lead.mobile}`} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white hover:bg-forest-800">
          <Phone className="size-4" aria-hidden /> Call
        </a>
        {lead.can_edit && (
          <>
            <Button variant="secondary" onClick={() => setDialog("status")}><ArrowRightLeft className="size-4" aria-hidden />Change status</Button>
            <Button variant="secondary" onClick={() => setDialog("note")}><StickyNote className="size-4" aria-hidden />Add note</Button>
            <Link to={`/leads/${lead.id}/edit`} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-white px-4 text-sm font-medium ring-1 ring-line hover:bg-forest-50">
              <Pencil className="size-4" aria-hidden /> Edit
            </Link>
          </>
        )}
        {isManager && <Button variant="secondary" onClick={() => setDialog("assign")}><UserRoundCog className="size-4" aria-hidden />Assign</Button>}
        {me.role === "admin" && <Button variant="ghost" className="text-danger" onClick={() => setDialog("delete")}><Trash2 className="size-4" aria-hidden />Delete</Button>}
      </div>

      {duplicates.length > 0 && <div className="mb-6"><DuplicateBanner duplicates={duplicates} /></div>}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-6">
          <section className="rounded-xl border border-line bg-white px-5 py-3">
            <h2 className="pt-2 pb-1 font-semibold">Contact</h2>
            <dl className="divide-y divide-line">
              <Row label="Mobile"><a href={`tel:${lead.mobile}`} className="text-forest-800 underline">{formatMobile(lead.mobile)}</a></Row>
              <Row label="Alternate">{lead.alt_mobile ? formatMobile(lead.alt_mobile) : null}</Row>
              <Row label="Email">{lead.email}</Row>
              <Row label="City">{lead.city}</Row>
            </dl>
          </section>
          <section className="rounded-xl border border-line bg-white px-5 py-3">
            <h2 className="pt-2 pb-1 font-semibold">Requirement</h2>
            <dl className="divide-y divide-line">
              <Row label="Project">{lead.project?.name}</Row>
              <Row label="Configuration">{lead.configuration ? CONFIG_LABELS[lead.configuration] : null}</Row>
              <Row label="Budget">{formatBudget(lead.budget_min, lead.budget_max)}</Row>
              <Row label="Purpose">{lead.purpose ? PURPOSE_LABELS[lead.purpose] : null}</Row>
              <Row label="Buying">{lead.timeline ? TIMELINE_LABELS[lead.timeline] : null}</Row>
            </dl>
          </section>
          <section className="rounded-xl border border-line bg-white px-5 py-3">
            <h2 className="pt-2 pb-1 font-semibold">Sales</h2>
            <dl className="divide-y divide-line">
              <Row label="Assigned to">{lead.assigned_to?.full_name ?? "Unassigned"}</Row>
              <Row label="Source">{SOURCE_LABELS[lead.source]}{lead.sub_source ? `, ${lead.sub_source}` : ""}</Row>
              <Row label="Estimated value">{lead.estimated_value !== null ? formatRupees(lead.estimated_value) : null}</Row>
              <Row label="Created">{formatDateTime(lead.created_at)}{lead.created_by ? ` by ${lead.created_by.full_name}` : ""}</Row>
              <Row label="Remarks">{lead.remarks ? <span className="whitespace-pre-wrap">{lead.remarks}</span> : null}</Row>
            </dl>
          </section>
        </div>

        <section className="rounded-xl border border-line bg-white p-5">
          <h2 className="mb-4 font-semibold">Activity</h2>
          <Timeline activities={lead.activities} />
        </section>
      </div>

      {dialog === "status" && <StatusDialog lead={lead} onClose={() => setDialog(null)} />}
      {dialog === "note" && <NoteDialog lead={lead} onClose={() => setDialog(null)} />}
      {dialog === "assign" && <AssignDialog lead={lead} onClose={() => setDialog(null)} />}
      {dialog === "delete" && <DeleteDialog lead={lead} onClose={() => setDialog(null)} onDeleted={() => navigate("/leads")} />}
    </>
  );
}

export function LeadDetailPage() {
  const id = Number(useParams().id);
  const lead = useLead(id);
  if (lead.isPending) return <Spinner />;
  if (lead.isError) {
    return <ErrorState message={errorMessage(lead.error, "Couldn’t load this lead.")} onRetry={() => void lead.refetch()} />;
  }
  return <LeadView lead={lead.data} />;
}
