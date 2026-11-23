"""Pre-possession rules: the trigger, the project's checklists, the financial position, and the possession gate."""

from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.agreement import Agreement, AgreementStatus
from app.models.case_document import Approval, CaseDocument, DocCategory
from app.models.ledger import Ledger, LedgerStatus
from app.models.milestone import MilestoneStatus, ProjectMilestone
from app.models.payment import Receipt, ReceiptStatus
from app.models.possession import Inspection, PossessionFile, Snag
from app.models.postsales import PostSalesCase
from app.models.project import Project
from app.models.ticket import Ticket, TicketCategory, TicketStatus
from app.services import doc_readiness, payments
from app.services import ledger as ledger_svc
from app.services.cost_sheet import merged

IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_DOCUMENTS = [
    "Executed agreement",
    "Approved final statement of account",
    "Relevant receipts and tax records",
    "Project or unit completion documents",
    "Occupancy or completion certificate",
    "Registration documents",
    "Final demand and supporting details",
    "Possession letter to the customer",
    "Customer identification and authorisation",
]
DEFAULT_READINESS = [
    "Unit number and configuration verified",
    "Internal finishing inspected",
    "Doors, windows and hardware checked",
    "Electrical points and fixtures checked",
    "Plumbing and sanitary fixtures checked",
    "Water supply and drainage tested",
    "Meters installed and readings recorded",
    "Safety and access systems checked",
    "Common-area access and parking allocation verified",
]
DISPUTE_CATEGORIES = (
    TicketCategory.payment,
    TicketCategory.receipt,
    TicketCategory.demand,
    TicketCategory.refund,
)
CONDITIONS = {
    "legal": "Legal and statutory readiness",
    "documents": "Possession documents",
    "finance": "Finance clearance",
    "readiness": "Unit readiness approved",
    "internal": "Internal approval (CRM manager)",
    "communication": "Customer informed (possession letter released)",
    "inspection": "Customer inspection done; no open major or critical snags",
}


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


def project_rules(project: Project) -> dict:
    t = merged(project.cost_sheet, None)
    stages = [s["name"] for s in t.get("stages", [])]
    return {
        "trigger": t.get("possession_trigger") or (stages[-1] if stages else None),
        "documents": list(t.get("possession_documents") or DEFAULT_DOCUMENTS),
        "readiness": list(t.get("readiness_items") or DEFAULT_READINESS),
    }


async def trigger_reached(db, project: Project) -> tuple[str | None, bool]:
    name = project_rules(project)["trigger"]
    if not name:
        return None, False
    m = await db.scalar(
        select(ProjectMilestone).where(
            ProjectMilestone.project_id == project.id,
            func.lower(ProjectMilestone.name) == name.lower(),
        )
    )
    return name, bool(m and m.status == MilestoneStatus.verified)


async def financial(db, case: PostSalesCase) -> dict:
    """A. Figures worked out from the ledger and receipts; confirmations come from finance."""
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
    if ledger is None:
        return {"has_ledger": False}
    t = today()
    pos = payments.position(ledger, receipts)
    bal = ledger_svc.balances(
        ledger,
        received_own=pos["received_own"],
        loan_disbursed=pos["loan_disbursed"],
        today=t,
        paid_by_stage=pos["paid_by_stage"],
        paid_other=pos["paid_other"],
        pending=pos["pending"],
    )
    paid = pos["paid_by_stage"]
    undemanded = [i.name for i in ledger.schedule if not ledger_svc.is_due(i, t)]
    not_yet_due = sum(
        max(0, i.amount + i.gst - paid.get(i.seq, 0))
        for i in ledger.schedule
        if ledger_svc.is_due(i, t) and (i.due_date is None or i.due_date >= t)
    )
    disputes = list(
        await db.scalars(
            select(Ticket).where(
                Ticket.case_id == case.id,
                Ticket.status != TicketStatus.closed,
                Ticket.category.in_(DISPUTE_CATEGORIES),
            )
        )
    )
    return {
        "has_ledger": True,
        "ledger_approved": ledger.status == LedgerStatus.approved,
        "total_payable": ledger_svc.totals(ledger).total_payable,
        "received": bal.received,
        "outstanding": bal.total_outstanding,
        "overdue": bal.overdue,
        "demanded_not_yet_due": not_yet_due,
        "not_yet_demanded": [*undemanded],
        "other_charges_outstanding": bal.other_charges,
        "unallocated": bal.unapplied,
        "unconfirmed_receipts": sum(1 for r in receipts if r.status == ReceiptStatus.recorded),
        "pending_amount": bal.pending_confirmation,
        "loan_not_disbursed": bal.loan_not_disbursed,
        "open_disputes": [f"TKT-{d.id:05d}" for d in disputes],
        "final_demand_raised": bool(ledger.schedule)
        and ledger_svc.is_due(
            max(ledger.schedule, key=lambda i: i.seq), t
        ),  # the last stage is demanded
    }


async def gate(
    db, case: PostSalesCase, f: PossessionFile | None, project: Project, rules: dict
) -> dict:
    """D. Each condition met or not, and whether an exception covers it."""
    readiness = await doc_readiness.check(db, project)
    agreement = await db.scalar(
        select(Agreement).where(
            Agreement.case_id == case.id, Agreement.status != AgreementStatus.cancelled
        )
    )
    agreement_done = agreement is not None and agreement.status in (
        AgreementStatus.registered,
        AgreementStatus.final_uploaded,
    )
    docs = (f.documents if f else {}) or {}
    docs_ok = all(
        docs.get(d, {}).get("status") in ("available", "not_applicable") for d in rules["documents"]
    )
    letter = await db.scalar(
        select(CaseDocument.id).where(
            CaseDocument.case_id == case.id,
            CaseDocument.category == DocCategory.possession,
            CaseDocument.approval == Approval.released,
        )
    )
    inspected = bool(f) and bool(
        await db.scalar(
            select(Inspection.id).where(
                Inspection.file_id == f.id, Inspection.conducted_on.is_not(None)
            )
        )
    )
    serious_open = bool(f) and bool(
        await db.scalar(
            select(Snag.id).where(
                Snag.file_id == f.id,
                Snag.status != "closed",
                Snag.severity.in_(["major", "critical"]),
            )
        )
    )
    met = {
        "legal": bool(readiness.ready and agreement_done),
        "documents": docs_ok,
        "finance": bool(f and f.cleared_at),
        "readiness": bool(f and f.readiness_approved_at),
        "internal": bool(f and f.internal_approved_at),
        "communication": letter is not None,
        "inspection": inspected and not serious_open,
    }
    scope = set((f.exception or {}).get("scope", [])) if f else set()
    items = [
        {"key": k, "label": CONDITIONS[k], "met": met[k], "excepted": (not met[k]) and k in scope}
        for k in CONDITIONS
    ]
    return {
        "conditions": items,
        "open": all(i["met"] or i["excepted"] for i in items),
        "detail": {
            "legal": None
            if met["legal"]
            else (
                "Agreement not yet registered"
                if not agreement_done
                else "Project legal details incomplete"
            )
        },
    }


async def possession_allowed(db, case: PostSalesCase) -> tuple[bool, list[str]]:
    f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case.id))
    project = await db.get(Project, case.booking.project_id)
    g = await gate(db, case, f, project, project_rules(project))
    return g["open"], [c["label"] for c in g["conditions"] if not (c["met"] or c["excepted"])]


async def open_snags(db, f: PossessionFile) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Snag)
            .where(Snag.file_id == f.id, Snag.status != "closed")
        )
        or 0
    )


async def evidence_count(db, case: PostSalesCase) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(CaseDocument)
            .where(
                CaseDocument.case_id == case.id,
                CaseDocument.category == DocCategory.possession,
                CaseDocument.approval.notin_([Approval.rejected, Approval.withdrawn]),
            )
        )
        or 0
    )


STATUS_ORDER = [
    "not_ready",
    "readiness_in_progress",
    "financial_clearance_pending",
    "legal_clearance_pending",
    "inspection_pending",
    "snag_rectification",
    "ready_for_possession",
    "appointment_scheduled",
    "handover_completed",
]
STATUS_LABELS = {
    "not_ready": "Not ready",
    "readiness_in_progress": "Readiness in progress",
    "financial_clearance_pending": "Financial clearance pending",
    "legal_clearance_pending": "Legal clearance pending",
    "inspection_pending": "Inspection pending",
    "snag_rectification": "Snag rectification",
    "ready_for_possession": "Ready for possession",
    "appointment_scheduled": "Appointment scheduled",
    "handover_completed": "Handover completed",
}


async def possession_status(
    db, case: PostSalesCase, f: PossessionFile | None, g: dict | None
) -> dict:
    """The headline status plus everything still pending (steps run in parallel, so several can be pending at once)."""
    from app.models.appointment import Appointment, AppointmentKind, AppointmentStatus

    if f is None:
        return {"status": "not_ready", "label": STATUS_LABELS["not_ready"], "pending": []}
    if f.handover_completed_at:
        return {
            "status": "handover_completed",
            "label": STATUS_LABELS["handover_completed"],
            "pending": [],
        }
    met = {c["key"]: c["met"] or c["excepted"] for c in g["conditions"]}
    pending = []
    if not met["finance"]:
        pending.append("financial_clearance_pending")
    if not met["legal"]:
        pending.append("legal_clearance_pending")
    open_snags = (
        await db.scalar(
            select(func.count())
            .select_from(Snag)
            .where(Snag.file_id == f.id, Snag.status != "closed")
        )
        or 0
    )
    inspected = bool(
        await db.scalar(
            select(Inspection.id).where(
                Inspection.file_id == f.id, Inspection.conducted_on.is_not(None)
            )
        )
    )
    if not inspected:
        pending.append("inspection_pending")
    if open_snags:
        pending.append("snag_rectification")
    if not g["open"]:
        return {
            "status": "readiness_in_progress",
            "label": STATUS_LABELS["readiness_in_progress"],
            "pending": [{"key": k, "label": STATUS_LABELS[k]} for k in pending],
        }
    appt = await db.scalar(
        select(Appointment.id).where(
            Appointment.case_id == case.id,
            Appointment.kind == AppointmentKind.possession,
            Appointment.status.in_([AppointmentStatus.scheduled, AppointmentStatus.attended]),
        )
    )
    key = "appointment_scheduled" if appt else "ready_for_possession"
    return {
        "status": key,
        "label": STATUS_LABELS[key],
        "pending": [{"key": k, "label": STATUS_LABELS[k]} for k in pending],
    }


async def key_dates(db, case: PostSalesCase, f: PossessionFile | None, project: Project) -> dict:
    """The final rule: construction completion, possession offer, legal eligibility and actual possession are kept apart."""
    trigger, _ = await trigger_reached(db, project)
    m = (
        await db.scalar(
            select(ProjectMilestone).where(
                ProjectMilestone.project_id == project.id,
                func.lower(ProjectMilestone.name) == (trigger or "").lower(),
            )
        )
        if trigger
        else None
    )
    letter = await db.scalar(
        select(CaseDocument)
        .where(
            CaseDocument.case_id == case.id,
            CaseDocument.category == DocCategory.possession,
            CaseDocument.approval == Approval.released,
        )
        .order_by(CaseDocument.released_at)
    )
    return {
        "construction_completed": m.completed_on
        if m and m.status == MilestoneStatus.verified
        else None,
        "possession_offered": letter.released_at.astimezone(IST).date()
        if letter and letter.released_at
        else None,
        "legally_eligible": f.gate_opened_at.astimezone(IST).date()
        if f and f.gate_opened_at
        else None,
        "actual_possession": f.actual_possession_on if f else None,
    }


async def run_snag_reminders(db, today_: date, send) -> dict:
    """Daily: overdue snags to their owner; critical ones to CRM managers too (once a day each)."""
    from app.models.user import Role, User

    crm = list(
        await db.scalars(
            select(User.id).where(User.is_active.is_(True), User.role == Role.crm_manager)
        )
    )
    n = 0
    for s in await db.scalars(
        select(Snag).where(
            Snag.status.in_(["open", "fixed"]),
            Snag.due_on < today_,
            (Snag.escalated_on.is_(None)) | (Snag.escalated_on < today_),
        )
    ):
        f = await db.get(PossessionFile, s.file_id)
        case = await db.get(PostSalesCase, f.case_id)
        who = [s.owner_id] + (crm if s.severity == "critical" else [])
        n += await send(
            who,
            type="snag_overdue",
            title=f"Overdue {s.severity} snag: {case.booking.lead.name}",
            body=f"{s.description[:120]} (due {s.due_on.isoformat()})",
            link=f"/post-sales/{case.id}?tab=possession",
        )
        s.escalated_on = today_
    return {"snags_overdue": n}
