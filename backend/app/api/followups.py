from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import or_, select

from app.core.deps import DbSession, require_role
from app.models.demand import Demand
from app.models.followup import FollowUpChannel, FollowUpOutcome, PaymentFollowUp
from app.models.ledger import Ledger
from app.models.payment import Receipt
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.user import LEDGER_VIEWERS, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import followups as svc
from app.services import ledger as ledger_svc
from app.services import payments
from app.services import postsales as cases
from app.services.audit import log_audit

router = APIRouter(tags=["payment follow-ups"])
Viewer = Annotated[User, Depends(require_role(*LEDGER_VIEWERS))]
WRITERS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.finance)
Writer = Annotated[User, Depends(require_role(*WRITERS))]
IST = timezone(timedelta(hours=5, minutes=30))


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class FollowUpIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: FollowUpChannel
    outcome: FollowUpOutcome
    note: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None
    demand_id: int | None = None
    contacted_on: date | None = None  # defaults to today
    promise_date: date | None = None
    promise_amount: Annotated[int, Field(gt=0, le=1_000_000_000)] | None = None
    next_follow_up_on: date | None = None

    @model_validator(mode="after")
    def _rules(self) -> "FollowUpIn":
        t = today()
        self.contacted_on = self.contacted_on or t
        if self.contacted_on > t or self.contacted_on < t - timedelta(days=30):
            raise ValueError("The contact date must be within the last 30 days")
        if self.outcome == FollowUpOutcome.promised:
            if not self.promise_date or not self.promise_amount:
                raise ValueError("A promise to pay needs the amount and the date")
            if not (t <= self.promise_date <= t + timedelta(days=90)):
                raise ValueError("The promised date must be within the next 90 days")
        elif self.promise_date or self.promise_amount:
            raise ValueError("Choose 'Promised to pay' to record a promise")
        if self.next_follow_up_on and not (t <= self.next_follow_up_on <= t + timedelta(days=60)):
            raise ValueError("The next follow-up must be within the next 60 days")
        return self


class FollowUpOut(BaseModel):
    id: int
    channel: FollowUpChannel
    outcome: FollowUpOutcome
    note: str | None
    demand_id: int | None
    demand_no: str | None
    contacted_on: date
    promise_date: date | None
    promise_amount: int | None
    promise_status: str | None  # open / kept / broken
    next_follow_up_on: date | None
    by: UserBrief | None
    created_at: datetime


class FollowUpsOut(BaseModel):
    items: list[FollowUpOut]
    outstanding: int  # what's demanded and unpaid now (for promise amounts)
    demands: list[dict]  # issued demands to link to: {"id", "demand_no", "stage_name"}
    can_write: bool


class DueItem(BaseModel):
    case_id: int
    case_code: str
    customer: str
    reason: str  # "Follow-up due" / "Promise due today" / "Promise broken"
    on: date
    amount: int | None


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _summary(db: DbSession, case: PostSalesCase, user: User) -> FollowUpsOut:
    t = today()
    receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
    rows = list(
        await db.scalars(
            select(PaymentFollowUp)
            .where(PaymentFollowUp.case_id == case.id)
            .order_by(PaymentFollowUp.created_at.desc(), PaymentFollowUp.id.desc())
        )
    )
    demands = {d.id: d for d in await db.scalars(select(Demand).where(Demand.case_id == case.id))}
    ids = {r.by_id for r in rows if r.by_id}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    outstanding = 0
    if ledger is not None:
        pos = payments.position(ledger, receipts)
        outstanding = ledger_svc.balances(
            ledger,
            received_own=pos["received_own"],
            loan_disbursed=pos["loan_disbursed"],
            today=t,
            paid_by_stage=pos["paid_by_stage"],
            paid_other=pos["paid_other"],
        ).currently_demanded
    code = lambda d: f"DMD-{d.id:05d}" + (f" v{d.version}" if d.version > 1 else "")  # noqa: E731
    return FollowUpsOut(
        items=[
            FollowUpOut(
                id=r.id,
                channel=r.channel,
                outcome=r.outcome,
                note=r.note,
                demand_id=r.demand_id,
                demand_no=code(demands[r.demand_id]) if r.demand_id in demands else None,
                contacted_on=r.contacted_on,
                promise_date=r.promise_date,
                promise_amount=r.promise_amount,
                promise_status=svc.promise_status(r, receipts, t),
                next_follow_up_on=r.next_follow_up_on,
                by=UserBrief.model_validate(users[r.by_id]) if r.by_id in users else None,
                created_at=r.created_at,
            )
            for r in rows
        ],
        outstanding=outstanding,
        demands=[
            {"id": d.id, "demand_no": code(d), "stage_name": d.stage_name}
            for d in demands.values()
            if d.status.value == "issued"
        ],
        can_write=user.role in WRITERS and case.status == CaseStatus.accepted,
    )


@router.get("/post-sales/cases/{case_id}/follow-ups", response_model=FollowUpsOut)
async def list_follow_ups(case_id: int, user: Viewer, db: DbSession) -> FollowUpsOut:
    return await _summary(db, await _case(db, case_id), user)


@router.post(
    "/post-sales/cases/{case_id}/follow-ups",
    response_model=FollowUpsOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_follow_up(
    case_id: int, body: FollowUpIn, request: Request, user: Writer, db: DbSession
) -> FollowUpsOut:
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Follow-ups are for accepted cases"
        )
    if body.demand_id is not None:
        d = await db.get(Demand, body.demand_id)
        if d is None or d.case_id != case.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That demand isn't on this case"
            )
    fu = PaymentFollowUp(case_id=case.id, by_id=user.id, **body.model_dump())
    db.add(fu)
    await db.flush()
    details = {"channel": fu.channel.value, "outcome": fu.outcome.value}
    if fu.promise_amount:
        details |= {"amount": fu.promise_amount, "promise_date": fu.promise_date.isoformat()}
    cases.event(db, case, "payment_follow_up", user, details)
    log_audit(
        db,
        action="followup.logged",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )
    await db.commit()
    return await _summary(db, case, user)


@router.get("/post-sales/follow-ups/due", response_model=list[DueItem])
async def my_due(user: Viewer, db: DbSession) -> list[DueItem]:
    """For the home page: follow-ups due (today or missed) and promises due today or broken, on cases I own or logged."""
    t = today()
    q = (
        select(PaymentFollowUp, PostSalesCase)
        .join(PostSalesCase, PostSalesCase.id == PaymentFollowUp.case_id)
        .where(
            PostSalesCase.status == CaseStatus.accepted,
            or_(
                PaymentFollowUp.next_follow_up_on <= t,
                PaymentFollowUp.outcome == FollowUpOutcome.promised,
            ),
        )
    )
    if user.role not in (Role.admin, Role.crm_manager):
        q = q.where(or_(PostSalesCase.owner_id == user.id, PaymentFollowUp.by_id == user.id))
    out, latest_next = [], {}
    rows = (await db.execute(q.order_by(PaymentFollowUp.created_at))).all()
    for fu, case in rows:  # only the latest planned follow-up per case counts
        if fu.next_follow_up_on:
            latest_next[case.id] = (fu, case)
    for fu, case in latest_next.values():
        if fu.next_follow_up_on <= t:
            out.append(
                DueItem(
                    case_id=case.id,
                    case_code=cases.code(case),
                    customer=case.booking.lead.name,
                    reason="Follow-up due",
                    on=fu.next_follow_up_on,
                    amount=None,
                )
            )
    for fu, case in rows:
        if fu.outcome == FollowUpOutcome.promised and fu.promise_date <= t:
            receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
            st = svc.promise_status(fu, receipts, t)
            if st in ("open", "broken"):
                out.append(
                    DueItem(
                        case_id=case.id,
                        case_code=cases.code(case),
                        customer=case.booking.lead.name,
                        reason="Promise due today" if st == "open" else "Promise broken",
                        on=fu.promise_date,
                        amount=fu.promise_amount,
                    )
                )
    # Missed appointments waiting for a follow-up (until rescheduled)
    from app.models.appointment import Appointment, AppointmentStatus

    q2 = (
        select(Appointment, PostSalesCase)
        .join(PostSalesCase, PostSalesCase.id == Appointment.case_id)
        .where(
            Appointment.status == AppointmentStatus.no_show,
            Appointment.follow_up_on.is_not(None),
            Appointment.follow_up_on <= t,
        )
    )
    if user.role not in (Role.admin, Role.crm_manager):
        q2 = q2.where(or_(Appointment.owner_id == user.id, PostSalesCase.owner_id == user.id))
    for a, case in (await db.execute(q2)).all():
        out.append(
            DueItem(
                case_id=case.id,
                case_code=cases.code(case),
                customer=case.booking.lead.name,
                reason="Missed appointment",
                on=a.follow_up_on,
                amount=None,
            )
        )
    return sorted(out, key=lambda x: x.on)
