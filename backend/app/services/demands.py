"""Milestone verification -> stages demanded -> draft demands; demand amounts; the demand letter."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import decrypt
from app.models.booking import Booking, BookingStatus
from app.models.demand import Demand
from app.models.ledger import Ledger, LedgerStatus, TriggerType
from app.models.milestone import ProjectMilestone
from app.models.payment import Receipt
from app.models.postsales import CaseStatus, CustomerProfile, PostSalesCase
from app.models.project import Project
from app.models.project_legal import ProjectBank, ProjectLegal
from app.models.user import User
from app.services import ledger as ledger_svc
from app.services import payments
from app.services import postsales as cases
from app.services.cost_sheet import merged


def due_days(project: Project) -> int:
    return int(merged(project.cost_sheet, None).get("demand_due_days", 15))


def milestone_names(project: Project) -> list[str]:
    """The project's construction milestones: its payment stages after the first (booking) one."""
    stages = merged(project.cost_sheet, None)["stages"] if project.cost_sheet else []
    return [s["name"] for s in stages[1:]]


async def receipts_for(db: AsyncSession, case_id: int) -> list[Receipt]:
    return list(await db.scalars(select(Receipt).where(Receipt.case_id == case_id)))


def amounts(
    ledger: Ledger, receipts: list[Receipt], stage_seq: int, today: date
) -> tuple[int, int]:
    """(this stage still unpaid incl. GST, earlier demanded stages still unpaid)."""
    paid = payments.position(ledger, receipts)["paid_by_stage"]
    unpaid = {i.seq: max(0, i.amount + i.gst - paid.get(i.seq, 0)) for i in ledger.schedule}
    earlier = sum(
        unpaid[i.seq]
        for i in ledger.schedule
        if i.seq != stage_seq and ledger_svc.is_due(i, today) and i.seq < stage_seq
    )
    return unpaid.get(stage_seq, 0), earlier


async def new_demand(
    db: AsyncSession,
    case: PostSalesCase,
    ledger: Ledger,
    seq: int,
    actor: User | None,
    today: date,
    milestone_id: int | None = None,
    version: int = 1,
    supersedes: int | None = None,
) -> Demand | None:
    item = next((i for i in ledger.schedule if i.seq == seq), None)
    if item is None or item.demanded_on is None:
        return None
    stage, earlier = amounts(ledger, await receipts_for(db, case.id), seq, today)
    d = Demand(
        case_id=case.id,
        stage_seq=seq,
        stage_name=item.name,
        stage_amount=stage,
        previous_dues=earlier,
        total_due=stage + earlier,
        demanded_on=item.demanded_on,
        due_date=item.due_date or item.demanded_on,
        prepared_by_id=actor.id if actor else None,
        milestone_id=milestone_id,
        version=version,
        supersedes_id=supersedes,
    )
    db.add(d)
    await db.flush()
    cases.event(
        db,
        case,
        "demand_created",
        actor,
        {"demand": code(d), "stage": item.name, "total_due": d.total_due},
    )
    return d


def code(d: Demand) -> str:
    return f"DMD-{d.id:05d}" + (f" v{d.version}" if d.version > 1 else "")


async def apply_milestone(
    db: AsyncSession, milestone: ProjectMilestone, project: Project, actor: User, today: date
) -> dict:
    """Every live booking in the project: stages for this milestone become demanded today, due after the project's
    payment period. A draft demand is created where the ledger is approved."""
    due = today + timedelta(days=due_days(project))
    summary = {"cases": 0, "demands": 0, "ledgers_not_approved": 0}
    rows = await db.execute(
        select(PostSalesCase, Ledger)
        .join(Booking, Booking.id == PostSalesCase.booking_id)
        .join(Ledger, Ledger.case_id == PostSalesCase.id)
        .where(
            Booking.project_id == project.id,
            Booking.status == BookingStatus.booked,
            PostSalesCase.status == CaseStatus.accepted,
        )
    )
    name = milestone.name.strip().lower()
    for case, ledger in rows.all():
        hit = [
            i
            for i in ledger.schedule
            if i.trigger_type == TriggerType.on_milestone
            and (i.milestone or "").strip().lower() == name
            and i.demanded_on is None
        ]
        if not hit:
            continue
        summary["cases"] += 1
        for i in hit:
            i.demanded_on, i.due_date = today, due
        cases.event(
            db,
            case,
            "milestone_reached",
            actor,
            {"milestone": milestone.name, "due_date": due.isoformat()},
        )
        if ledger.status == LedgerStatus.approved:
            for i in hit:
                if await new_demand(
                    db, case, ledger, i.seq, actor, today, milestone_id=milestone.id
                ):
                    summary["demands"] += 1
        else:
            summary["ledgers_not_approved"] += 1
    return summary


async def letter(db: AsyncSession, demand: Demand, case: PostSalesCase, ledger: Ledger) -> dict:
    """Everything the demand letter shows. The bank account number is stored encrypted."""
    b = case.booking
    project = await db.get(Project, b.project_id)
    legal = await db.get(ProjectLegal, project.id)
    bank = await db.get(ProjectBank, project.id)
    profile = await db.get(CustomerProfile, case.id)
    item = next((i for i in ledger.schedule if i.seq == demand.stage_seq), None)
    notes = [
        n
        for n in merged(project.cost_sheet, None).get("notes", [])
        if "interest" in n.lower() or "delay" in n.lower()
    ]
    return {
        "demand_no": code(demand),
        "case_code": cases.code(case),
        "booking_code": f"BKG-{b.id:05d}",
        "customer": (profile.legal_name if profile and profile.legal_name else None)
        or b.customer_name
        or b.lead.name,
        "co_applicants": b.applicant_name,
        "address": (profile.correspondence_address if profile else None) or b.customer_address,
        "project": project.name,
        "unit_no": b.unit.unit_no,
        "agreed_price": b.agreed_price,
        "stage": demand.stage_name,
        "stage_base": item.amount if item else None,
        "stage_gst": item.gst if item else None,
        "stage_amount": demand.stage_amount,
        "previous_dues": demand.previous_dues,
        "total_due": demand.total_due,
        "demanded_on": demand.demanded_on.isoformat(),
        "due_date": demand.due_date.isoformat(),
        "developer": {
            "name": legal.developer_legal_name if legal else None,
            "rera": legal.rera_number if legal else None,
            "address": legal.registered_address if legal else None,
            "gstin": legal.gstin if legal else None,
            "signatory": legal.signatory_name if legal else None,
            "designation": legal.signatory_designation if legal else None,
        },
        "bank": {
            "name": bank.bank_name if bank else None,
            "holder": bank.account_holder_name if bank else None,
            "account_enc": bank.account_number_enc if bank else None,
            "ifsc": bank.ifsc if bank else None,
            "branch": bank.branch if bank else None,
        },
        "notes": notes,
    }


def readable(snapshot: dict) -> dict:
    """The letter for display: decrypt the account number."""
    out = {**snapshot, "bank": {**snapshot.get("bank", {})}}
    enc = out["bank"].pop("account_enc", None)
    out["bank"]["account"] = decrypt(enc) if enc else None
    return out
