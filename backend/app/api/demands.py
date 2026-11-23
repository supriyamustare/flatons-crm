from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.demand import Demand, DemandStatus, IssueMethod
from app.models.ledger import Ledger, LedgerStatus
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.project import Project
from app.models.user import LEDGER_CHECKERS, LEDGER_MAKERS, LEDGER_VIEWERS, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import demands as svc
from app.services import doc_readiness, payments
from app.services import ledger as ledger_svc
from app.services import postsales as cases
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales/cases/{case_id}/demands", tags=["demands"])
Viewer = Annotated[User, Depends(require_role(*LEDGER_VIEWERS))]
Maker = Annotated[User, Depends(require_role(*LEDGER_MAKERS))]
Checker = Annotated[User, Depends(require_role(*LEDGER_CHECKERS))]
ISSUERS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.finance)
Issuer = Annotated[User, Depends(require_role(*ISSUERS))]
IST = timezone(timedelta(hours=5, minutes=30))


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class StageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_seq: int


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class CancelIn(ReasonIn):
    reissue: bool = True  # issue a corrected new version straight away


class IssueIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: IssueMethod


class DemandOut(BaseModel):
    id: int
    demand_no: str
    version: int
    stage_seq: int
    stage_name: str
    stage_amount: int
    previous_dues: int
    total_due: int
    demanded_on: date
    due_date: date
    status: DemandStatus
    payment: str  # unpaid / part paid / paid / overdue (for issued demands, from receipts now)
    outstanding_now: int
    note: str | None
    cancel_reason: str | None
    issue_method: IssueMethod | None
    prepared_by: UserBrief | None
    submitted_by: UserBrief | None
    approved_by: UserBrief | None
    issued_by: UserBrief | None
    issued_at: datetime | None
    supersedes: str | None
    can_submit: bool = False
    can_approve: bool = False
    can_issue: bool = False
    can_cancel: bool = False


class DemandsOut(BaseModel):
    demands: list[DemandOut]
    can_create: list[dict]  # demanded stages without a live demand: {"seq", "name", "outstanding"}
    readiness: doc_readiness.Readiness | None = None
    ledger_approved: bool = False


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _ledger(db: DbSession, case_id: int) -> Ledger | None:
    return await db.scalar(select(Ledger).where(Ledger.case_id == case_id))


async def summary(db: DbSession, case: PostSalesCase, user: User) -> DemandsOut:
    ledger = await _ledger(db, case.id)
    project = await db.get(Project, case.booking.project_id)
    readiness = await doc_readiness.check(db, project)
    if ledger is None:
        return DemandsOut(demands=[], can_create=[], readiness=readiness)
    await db.refresh(ledger)
    t = today()
    receipts = await svc.receipts_for(db, case.id)
    paid = payments.position(ledger, receipts)["paid_by_stage"]
    rows = list(
        await db.scalars(select(Demand).where(Demand.case_id == case.id).order_by(Demand.id.desc()))
    )
    ids = {
        x
        for d in rows
        for x in (d.prepared_by_id, d.submitted_by_id, d.approved_by_id, d.issued_by_id)
        if x
    }
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    brief = lambda uid: UserBrief.model_validate(users[uid]) if uid in users else None  # noqa: E731
    codes = {d.id: svc.code(d) for d in rows}
    out = []
    for d in rows:
        item = next((i for i in ledger.schedule if i.seq == d.stage_seq), None)
        stage_out = max(0, (item.amount + item.gst - paid.get(d.stage_seq, 0)) if item else 0)
        if d.status != DemandStatus.issued:
            pay = "—"
        elif stage_out == 0:
            pay = "paid"
        elif d.due_date < t:
            pay = "overdue"
        else:
            pay = "part paid" if stage_out < d.stage_amount else "unpaid"
        out.append(
            DemandOut(
                id=d.id,
                demand_no=codes[d.id],
                version=d.version,
                stage_seq=d.stage_seq,
                stage_name=d.stage_name,
                stage_amount=d.stage_amount,
                previous_dues=d.previous_dues,
                total_due=d.total_due,
                demanded_on=d.demanded_on,
                due_date=d.due_date,
                status=d.status,
                payment=pay,
                outstanding_now=stage_out,
                note=d.note,
                cancel_reason=d.cancel_reason,
                issue_method=d.issue_method,
                prepared_by=brief(d.prepared_by_id),
                submitted_by=brief(d.submitted_by_id),
                approved_by=brief(d.approved_by_id),
                issued_by=brief(d.issued_by_id),
                issued_at=d.issued_at,
                supersedes=codes.get(d.supersedes_id) if d.supersedes_id else None,
                can_submit=user.role in LEDGER_MAKERS and d.status == DemandStatus.draft,
                can_approve=user.role in LEDGER_CHECKERS
                and d.status == DemandStatus.pending_approval
                and d.submitted_by_id != user.id,
                can_issue=user.role in ISSUERS and d.status == DemandStatus.approved,
                can_cancel=user.role in LEDGER_CHECKERS
                and d.status
                in (
                    DemandStatus.draft,
                    DemandStatus.pending_approval,
                    DemandStatus.approved,
                    DemandStatus.issued,
                ),
            )
        )
    live = {d.stage_seq for d in rows if d.status != DemandStatus.cancelled}
    creatable = (
        [
            {
                "seq": i.seq,
                "name": i.name,
                "outstanding": max(0, i.amount + i.gst - paid.get(i.seq, 0)),
            }
            for i in sorted(ledger.schedule, key=lambda x: x.seq)
            if ledger_svc.is_due(i, t)
            and i.seq not in live
            and i.amount + i.gst - paid.get(i.seq, 0) > 0
        ]
        if user.role in LEDGER_MAKERS and ledger.status == LedgerStatus.approved
        else []
    )
    return DemandsOut(
        demands=out,
        can_create=creatable,
        readiness=readiness,
        ledger_approved=ledger.status == LedgerStatus.approved,
    )


async def _demand(db: DbSession, case_id: int, did: int) -> Demand:
    d = await db.get(Demand, did)
    if d is None or d.case_id != case_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demand not found")
    return d


def _log(
    db: DbSession, case: PostSalesCase, user: User, action: str, request: Request, details: dict
) -> None:
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=action.replace("demand_", "demand."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


@router.get("", response_model=DemandsOut)
async def list_demands(case_id: int, user: Viewer, db: DbSession) -> DemandsOut:
    return await summary(db, await _case(db, case_id), user)


@router.post("", response_model=DemandsOut, status_code=status.HTTP_201_CREATED)
async def create(
    case_id: int, body: StageIn, request: Request, user: Maker, db: DbSession
) -> DemandsOut:
    """A draft demand for a stage that is already demanded (e.g. the booking stage, or a date stage)."""
    case = await _case(db, case_id)
    ledger = await _ledger(db, case_id)
    if (
        case.status != CaseStatus.accepted
        or ledger is None
        or ledger.status != LedgerStatus.approved
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Demands need an approved ledger"
        )
    if await db.scalar(
        select(Demand.id).where(
            Demand.case_id == case_id,
            Demand.stage_seq == body.stage_seq,
            Demand.status != DemandStatus.cancelled,
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "This stage already has a demand")
    item = next((i for i in ledger.schedule if i.seq == body.stage_seq), None)
    if item is None or not ledger_svc.is_due(item, today()):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "That stage isn't demanded yet (its milestone hasn't been verified)",
        )
    await svc.new_demand(db, case, ledger, body.stage_seq, user, today())
    await db.commit()
    return await summary(db, case, user)


@router.post("/{did}/submit", response_model=DemandsOut)
async def submit(
    case_id: int, did: int, request: Request, user: Maker, db: DbSession
) -> DemandsOut:
    case = await _case(db, case_id)
    d = await _demand(db, case_id, did)
    if d.status != DemandStatus.draft:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a draft demand can be submitted"
        )
    project = await db.get(Project, case.booking.project_id)
    try:
        await doc_readiness.require_ready(db, project)
    except doc_readiness.NotReady as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    ledger = await _ledger(db, case_id)
    d.stage_amount, d.previous_dues = svc.amounts(
        ledger, await svc.receipts_for(db, case_id), d.stage_seq, today()
    )
    d.total_due = d.stage_amount + d.previous_dues
    if d.total_due <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Nothing is due on this stage any more; cancel the demand instead",
        )
    d.status, d.submitted_by_id, d.submitted_at, d.note = (
        DemandStatus.pending_approval,
        user.id,
        datetime.now(UTC),
        None,
    )
    _log(
        db,
        case,
        user,
        "demand_submitted",
        request,
        {"demand": svc.code(d), "total_due": d.total_due},
    )
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.finance_approver, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="demand_approval",
            title=f"Demand to approve: {case.booking.lead.name}",
            body=f"{svc.code(d)}: {d.stage_name}, Rs {d.total_due:,}",
            link=f"/post-sales/{case.id}?tab=demands",
        )
    await db.commit()
    return await summary(db, case, user)


@router.post("/{did}/approve", response_model=DemandsOut)
async def approve(
    case_id: int, did: int, request: Request, user: Checker, db: DbSession
) -> DemandsOut:
    case = await _case(db, case_id)
    d = await _demand(db, case_id, did)
    if d.status != DemandStatus.pending_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a demand waiting for approval can be approved",
        )
    if d.submitted_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who submitted a demand can't approve it"
        )
    d.status, d.approved_by_id, d.approved_at = DemandStatus.approved, user.id, datetime.now(UTC)
    d.letter = await svc.letter(db, d, case, await _ledger(db, case_id))  # frozen from here on
    _log(
        db,
        case,
        user,
        "demand_approved",
        request,
        {"demand": svc.code(d), "total_due": d.total_due},
    )
    await db.commit()
    return await summary(db, case, user)


@router.post("/{did}/return", response_model=DemandsOut)
async def return_demand(
    case_id: int, did: int, body: ReasonIn, request: Request, user: Checker, db: DbSession
) -> DemandsOut:
    case = await _case(db, case_id)
    d = await _demand(db, case_id, did)
    if d.status != DemandStatus.pending_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a demand waiting for approval can be returned",
        )
    d.status, d.note = DemandStatus.draft, body.reason
    _log(db, case, user, "demand_returned", request, {"demand": svc.code(d), "reason": body.reason})
    await db.commit()
    return await summary(db, case, user)


@router.post("/{did}/issue", response_model=DemandsOut)
async def issue(
    case_id: int, did: int, body: IssueIn, request: Request, user: Issuer, db: DbSession
) -> DemandsOut:
    case = await _case(db, case_id)
    d = await _demand(db, case_id, did)
    if d.status != DemandStatus.approved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only an approved demand can be issued"
        )
    d.status, d.issued_by_id, d.issued_at, d.issue_method = (
        DemandStatus.issued,
        user.id,
        datetime.now(UTC),
        body.method,
    )
    _log(
        db,
        case,
        user,
        "demand_issued",
        request,
        {"demand": svc.code(d), "method": body.method.value},
    )
    from app.services import comms

    await comms.emit(
        db,
        "demand_issued",
        case,
        {"stage": d.stage_name, "amount": d.total_due, "due_date": d.due_date.strftime("%d %b %Y")},
        d.id,
    )
    await db.commit()
    return await summary(db, case, user)


@router.post("/{did}/cancel", response_model=DemandsOut)
async def cancel(
    case_id: int, did: int, body: CancelIn, request: Request, user: Checker, db: DbSession
) -> DemandsOut:
    """Cancel (with a reason) and, by default, start a corrected new version. Nothing is overwritten."""
    case = await _case(db, case_id)
    d = await _demand(db, case_id, did)
    if d.status == DemandStatus.cancelled:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This demand is already cancelled"
        )
    d.status, d.cancel_reason, d.cancelled_by_id, d.cancelled_at = (
        DemandStatus.cancelled,
        body.reason,
        user.id,
        datetime.now(UTC),
    )
    await db.flush()
    details = {"demand": svc.code(d), "reason": body.reason}
    if body.reissue:
        new = await svc.new_demand(
            db,
            case,
            await _ledger(db, case_id),
            d.stage_seq,
            user,
            today(),
            milestone_id=d.milestone_id,
            version=d.version + 1,
            supersedes=d.id,
        )
        if new:
            details["new_version"] = svc.code(new)
    _log(db, case, user, "demand_cancelled", request, details)
    await db.commit()
    return await summary(db, case, user)


@router.get("/{did}/letter")
async def letter(case_id: int, did: int, request: Request, user: Viewer, db: DbSession) -> dict:
    """The letter: frozen once approved; a live draft before that (shown with a DRAFT mark)."""
    case = await _case(db, case_id)
    d = await _demand(db, case_id, did)
    snap = d.letter or await svc.letter(db, d, case, await _ledger(db, case_id))
    log_audit(
        db,
        action="demand.letter_viewed",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"demand": svc.code(d)},
        request=request,
    )
    await db.commit()
    return {
        **svc.readable(snap),
        "status": d.status.value,
        "draft": d.status in (DemandStatus.draft, DemandStatus.pending_approval),
        "cancelled": d.status == DemandStatus.cancelled,
        "cancel_reason": d.cancel_reason,
        "version": d.version,
    }
