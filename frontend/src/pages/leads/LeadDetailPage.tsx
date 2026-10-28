import { BookFlatDialog } from "../../components/bookings/BookFlatDialog";
import { useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { ArrowLeft, ArrowRightLeft, BadgeIndianRupee, CalendarPlus, MapPin, Pencil, Phone, PhoneCall, StickyNote, Trash2, UserRoundCog } from "lucide-react";
import { describeActivity } from "../../components/leads/ActivityText";
import { DuplicateBanner, StatusBadge } from "../../components/leads/LeadBits";
import { AssignDialog, DeleteDialog, NoteDialog, StatusDialog } from "../../components/leads/LeadDialogs";
import { LogCallDialog } from "../../components/calls/LogCallDialog";
import { CompleteTaskDialog, NewTaskDialog, RescheduleDialog } from "../../components/tasks/TaskDialogs";
import { ScheduleVisitDialog, VisitOutcomeDialog } from "../../components/visits/VisitDialogs";
import { VisitItem } from "../../components/visits/VisitItem";
import { TaskItem } from "../../components/tasks/TaskItem";
import { Button, ErrorState, Spinner } from "../../components/ui";
import { useCurrentUser } from "../../hooks/useAuth";
import { useLead } from "../../hooks/useLeads";
import { useLeadTasks } from "../../hooks/useTasks";
import { useLeadVisits } from "../../hooks/useVisits";
import type { Visit } from "../../lib/visits";
import type { Task } from "../../lib/tasks";
import { errorMessage, formatDateTime } from "../../lib/api";
import {
  CONFIG_LABELS, PURPOSE_LABELS, SOURCE_LABELS, TIMELINE_LABELS,
  formatBudget, formatMobile, formatRupees,
} from "../../lib/leads";
import type { Activity, Duplicate, LeadDetail } from "../../lib/leads";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8.5rem_1fr] gap-3 py-2 text-sm">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words text-ink">{children ?? "—"}</dd>
    </div>
  );
}


/** Open follow-ups first, then a short history. */
function LeadFollowUps({ leadId, canAdd, onAdd }: { leadId: number; canAdd: boolean; onAdd: () => void }) {
  const me = useCurrentUser();
  const isManager = me.role === "admin" || me.role === "manager";
  const tasks = useLeadTasks(leadId);
  const [acting, setActing] = useState<{ kind: "done" | "move" | "call"; task: Task } | null>(null);
  const open = tasks.data?.filter((t) => t.status === "pending") ?? [];
  const recentDone = tasks.data?.filter((t) => t.status === "completed").slice(0, 3) ?? [];

  return (
    <section className="rounded-xl border border-line bg-white p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">Follow-ups</h2>
        {canAdd && <Button variant="ghost" onClick={onAdd}><CalendarPlus className="size-4" aria-hidden />Add</Button>}
      </div>
      {tasks.isPending && <div className="h-16 animate-pulse rounded-lg bg-paper" />}
      {tasks.isError && <p className="text-sm text-danger">{errorMessage(tasks.error, "Couldn’t load follow-ups.")}</p>}
      {tasks.isSuccess && open.length === 0 && (
        <p className="text-sm text-muted">No follow-up planned.{canAdd ? " Add one so this lead doesn’t go cold." : ""}</p>
      )}
      {open.length > 0 && (
        <ul className="space-y-2">
          {open.map((t) => (
            <TaskItem key={t.id} task={t} showLead={false} showAssignee
              canAct={isManager || t.assigned_to?.id === me.id}
              onComplete={() => setActing({ kind: "done", task: t })}
              onReschedule={() => setActing({ kind: "move", task: t })}
              onCall={() => setActing({ kind: "call", task: t })} />
          ))}
        </ul>
      )}
      {recentDone.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">Recently completed ({recentDone.length})</summary>
          <ul className="mt-2 space-y-2">
            {recentDone.map((t) => (
              <TaskItem key={t.id} task={t} showLead={false} canAct={false} onComplete={() => {}} onReschedule={() => {}} />
            ))}
          </ul>
        </details>
      )}
      {acting?.kind === "done" && <CompleteTaskDialog task={acting.task} onClose={() => setActing(null)} />}
      {acting?.kind === "move" && <RescheduleDialog task={acting.task} onClose={() => setActing(null)} />}
      {acting?.kind === "call" && <LogCallDialog lead={acting.task.lead} task={acting.task} onClose={() => setActing(null)} />}
    </section>
  );
}

function LeadVisits({ leadId, canAdd, onAdd }: { leadId: number; canAdd: boolean; onAdd: () => void }) {
  const visits = useLeadVisits(leadId);
  const [updating, setUpdating] = useState<Visit | null>(null);
  const list = visits.data ?? [];
  return (
    <section className="rounded-xl border border-line bg-white p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold">Site visits</h2>
        {canAdd && <Button variant="ghost" onClick={onAdd}><MapPin className="size-4" aria-hidden />Schedule</Button>}
      </div>
      {visits.isPending && <div className="h-16 animate-pulse rounded-lg bg-paper" />}
      {visits.isError && <p className="text-sm text-danger">{errorMessage(visits.error, "Couldn’t load visits.")}</p>}
      {visits.isSuccess && list.length === 0 && <p className="text-sm text-muted">No site visits yet.</p>}
      {list.length > 0 && (
        <ul className="space-y-2">
          {list.slice(0, 4).map((v) => (
            <VisitItem key={v.id} visit={v} showLead={false} canAct={canAdd} onUpdate={() => setUpdating(v)} />
          ))}
        </ul>
      )}
      {updating && <VisitOutcomeDialog visit={updating} onClose={() => setUpdating(null)} />}
    </section>
  );
}

function Timeline({ activities }: { activities: Activity[] }) {
  return (
    <ol className="relative space-y-5 border-l border-line pl-5">
      {activities.map((a) => (
        <li key={a.id} className="relative">
          <span className={`absolute top-1.5 -left-[25px] size-2.5 rounded-full ring-4 ring-white ${a.type === "note" ? "bg-gold-500" : "bg-forest-700"}`} aria-hidden />
          <p className="text-sm text-ink">{describeActivity(a)}</p>
          {a.note && <p className="mt-1 rounded-lg bg-paper px-3 py-2 text-sm whitespace-pre-wrap text-ink">{a.note}</p>}
          <p className="mt-1 text-xs text-muted">
            {a.actor?.full_name ?? "System"}, {formatDateTime(a.created_at)}
          </p>
        </li>
      ))}
    </ol>
  );
}

type DialogKind = "status" | "note" | "task" | "call" | "visit" | "assign" | "delete";

function LeadView({ lead }: { lead: LeadDetail }) {
  const me = useCurrentUser();
  const navigate = useNavigate();
  const duplicates = (useLocation().state as { duplicates?: Duplicate[] } | null)?.duplicates ?? [];
  const [dialog, setDialog] = useState<DialogKind | null>(null);
  const [booking, setBooking] = useState(false);
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
        <a href={`tel:${lead.mobile}`} onClick={() => lead.can_edit && setDialog("call")}
          className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-forest-900 px-4 text-sm font-medium text-white hover:bg-forest-800">
          <Phone className="size-4" aria-hidden /> Call
        </a>
        {lead.can_edit && (
          <>
            <Button variant="secondary" onClick={() => setDialog("status")}><ArrowRightLeft className="size-4" aria-hidden />Change status</Button>
            <Button variant="secondary" onClick={() => setDialog("call")}><PhoneCall className="size-4" aria-hidden />Log call</Button>
            <Button variant="secondary" onClick={() => setDialog("visit")}><MapPin className="size-4" aria-hidden />Site visit</Button>
            <Button variant="secondary" onClick={() => setDialog("task")}><CalendarPlus className="size-4" aria-hidden />Follow-up</Button>
            <Button variant="secondary" onClick={() => setDialog("note")}><StickyNote className="size-4" aria-hidden />Add note</Button>
            {!lead.booking && lead.status !== "lost" && lead.status !== "junk" && me.role !== "docs" && (
              <Button onClick={() => setBooking(true)}><BadgeIndianRupee className="size-4" aria-hidden />Book a flat</Button>
            )}
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
          {lead.booking && (
            <Link to={`/bookings/${lead.booking.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-gold-300 bg-gold-100/60 px-5 py-3 hover:bg-gold-100">
              <span><b>Booked:</b> {lead.booking.project}, unit {lead.booking.unit_no} for {formatRupees(lead.booking.agreed_price)}</span>
              <span className="text-sm font-medium text-forest-800">{lead.booking.booking_code} →</span>
            </Link>
          )}
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
              <Row label="Campaign">{lead.campaign?.name}</Row>
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

        <div className="space-y-6">
          <LeadFollowUps leadId={lead.id} canAdd={lead.can_edit} onAdd={() => setDialog("task")} />
          <LeadVisits leadId={lead.id} canAdd={lead.can_edit} onAdd={() => setDialog("visit")} />
          <section className="rounded-xl border border-line bg-white p-5">
            <h2 className="mb-4 font-semibold">Activity</h2>
            <Timeline activities={lead.activities} />
          </section>
        </div>
      </div>

      {dialog === "status" && <StatusDialog lead={lead} onClose={() => setDialog(null)} />}
      {booking && <BookFlatDialog lead={lead} onClose={() => setBooking(false)} />}
      {dialog === "note" && <NoteDialog lead={lead} onClose={() => setDialog(null)} />}
      {dialog === "call" && <LogCallDialog lead={lead} onClose={() => setDialog(null)} />}
      {dialog === "visit" && (
        <ScheduleVisitDialog lead={{ id: lead.id, name: lead.name, project_id: lead.project?.id, assigned_to_id: lead.assigned_to?.id }}
          onClose={() => setDialog(null)} />
      )}
      {dialog === "task" && (
        <NewTaskDialog lead={{ id: lead.id, name: lead.name, assigned_to_id: lead.assigned_to?.id }} onClose={() => setDialog(null)} />
      )}
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
