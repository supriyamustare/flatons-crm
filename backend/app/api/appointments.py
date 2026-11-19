from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.appointment import Appointment, AppointmentKind, AppointmentStatus
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import appointments as svc
from app.services import postsales as cases
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(tags=["appointments"])
CalendarViewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES, *svc.SALES_VIEW))]
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
SCHEDULERS = (
    Role.admin,
    Role.crm_manager,
    Role.postsales_exec,
    Role.legal,
    Role.site,
    Role.project_manager,
    Role.service,
    Role.after_sales,
)
Scheduler = Annotated[User, Depends(require_role(*SCHEDULERS))]
IST = timezone(timedelta(hours=5, minutes=30))
Txt = Annotated[PlainText, StringConstraints(max_length=2000)]


class AppointmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: AppointmentKind
    title: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    starts_at: datetime
    duration_min: Annotated[int, Field(ge=15, le=480)] = 60
    location: Annotated[PlainText, StringConstraints(max_length=300)] | None = None
    owner_id: int | None = None
    required_docs: Txt | None = None
    notes: Txt | None = None
    allow_clash: bool = False


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    via: Literal["call", "email", "sms", "whatsapp", "in_person", "portal"]


class RescheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]
    duration_min: Annotated[int, Field(ge=15, le=480)] | None = None
    location: Annotated[PlainText, StringConstraints(max_length=300)] | None = None
    allow_clash: bool = False


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class AttendanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attended: bool
    outcome: Txt | None = None


class AppointmentOut(BaseModel):
    id: int
    apt_no: str
    kind: AppointmentKind
    label: str
    title: str | None
    starts_at: datetime
    duration_min: int
    location: str | None
    owner: UserBrief | None
    required_docs: str | None
    notes: str | None
    status: AppointmentStatus
    status_reason: str | None
    confirmed_on: date | None
    confirmed_via: str | None
    outcome: str | None
    follow_up_on: date | None
    rescheduled_from: str | None
    can_act: bool


class CaseAppointments(BaseModel):
    items: list[AppointmentOut]
    owners: list[UserBrief]
    can_schedule: bool
    kinds: dict[str, str]


def now() -> datetime:
    return datetime.now(UTC)


def code(a: Appointment) -> str:
    return f"APT-{a.id:05d}"


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _owners(db: DbSession) -> list[User]:
    return list(
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.role.in_(list(SCHEDULERS)))
            .order_by(User.full_name)
        )
    )


async def list_for(db: DbSession, case: PostSalesCase, user: User) -> CaseAppointments:
    rows = list(
        await db.scalars(
            select(Appointment)
            .where(Appointment.case_id == case.id)
            .order_by(Appointment.starts_at.desc(), Appointment.id.desc())
        )
    )
    users = {u.id: u for u in await _owners(db)} | {
        u.id: u
        for u in await db.scalars(
            select(User).where(User.id.in_({a.owner_id for a in rows if a.owner_id}))
        )
    }
    codes = {a.id: code(a) for a in rows}
    can = user.role in SCHEDULERS and case.status == CaseStatus.accepted
    return CaseAppointments(
        items=[
            AppointmentOut(
                id=a.id,
                apt_no=codes[a.id],
                kind=a.kind,
                label=svc.LABELS[a.kind],
                title=a.title,
                starts_at=a.starts_at,
                duration_min=a.duration_min,
                location=a.location,
                owner=UserBrief.model_validate(users[a.owner_id]) if a.owner_id in users else None,
                required_docs=a.required_docs,
                notes=a.notes,
                status=a.status,
                status_reason=a.status_reason,
                confirmed_on=a.confirmed_on,
                confirmed_via=a.confirmed_via,
                outcome=a.outcome,
                follow_up_on=a.follow_up_on,
                rescheduled_from=codes.get(a.rescheduled_from_id)
                if a.rescheduled_from_id
                else None,
                can_act=can
                and a.status in (AppointmentStatus.scheduled, AppointmentStatus.no_show),
            )
            for a in rows
        ],
        owners=[UserBrief.model_validate(u) for u in await _owners(db)],
        can_schedule=can,
        kinds={k.value: v for k, v in svc.LABELS.items()},
    )


def _log(
    db: DbSession,
    case: PostSalesCase,
    user: User,
    action: str,
    a: Appointment,
    request: Request,
    extra: dict | None = None,
) -> None:
    details = {
        "appointment": code(a),
        "kind": svc.LABELS[a.kind],
        "at": a.starts_at.astimezone(IST).strftime("%d %b %Y, %I:%M %p"),
        **(extra or {}),
    }
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=action.replace("appointment_", "appointment."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


async def _check_time_and_owner(
    db: DbSession,
    owner_id: int | None,
    starts_at: datetime,
    minutes: int,
    allow: bool,
    exclude: int | None = None,
) -> None:
    if starts_at.tzinfo is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the time with its time zone"
        )
    if starts_at < now() - timedelta(minutes=5):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The appointment time has already passed"
        )
    if starts_at > now() + timedelta(days=366):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Schedule within the next year")
    if owner_id is not None:
        u = await db.get(User, owner_id)
        if u is None or not u.is_active or u.role not in SCHEDULERS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Choose an active post-sales person as the owner",
            )
    clash = await svc.clashes(db, owner_id, starts_at, minutes, exclude)
    if clash and not allow:
        c = clash[0]
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The owner already has {svc.LABELS[c.kind].lower()} {code(c)} at {c.starts_at.astimezone(IST):%I:%M %p}. Choose another time, or confirm the double booking.",
        )


@router.get("/calendar")
async def get_calendar(
    user: CalendarViewer,
    db: DbSession,
    start: date | None = None,
    days: Annotated[int, Query(ge=1, le=42)] = 7,
    mine: bool = False,
) -> list[dict]:
    """Everything on the calendar: appointments, registration appointments from agreements, and (for sales) site visits."""
    return await svc.calendar(db, user, start or datetime.now(IST).date(), days, mine)


@router.get("/post-sales/cases/{case_id}/appointments", response_model=CaseAppointments)
async def case_appointments(case_id: int, user: Viewer, db: DbSession) -> CaseAppointments:
    return await list_for(db, await _case(db, case_id), user)


@router.post(
    "/post-sales/cases/{case_id}/appointments",
    response_model=CaseAppointments,
    status_code=status.HTTP_201_CREATED,
)
async def schedule(
    case_id: int, body: AppointmentIn, request: Request, user: Scheduler, db: DbSession
) -> CaseAppointments:
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Appointments are for accepted cases"
        )
    owner = body.owner_id or case.owner_id or user.id
    await _check_time_and_owner(db, owner, body.starts_at, body.duration_min, body.allow_clash)
    a = Appointment(
        case_id=case.id,
        created_by_id=user.id,
        **body.model_dump(exclude={"allow_clash", "owner_id"}),
        owner_id=owner,
    )
    db.add(a)
    await db.flush()
    _log(db, case, user, "appointment_scheduled", a, request)
    if owner != user.id:
        notify(
            db,
            user_id=owner,
            type="appointment_assigned",
            title=f"{svc.LABELS[a.kind]}: {case.booking.lead.name}",
            body=f"{a.starts_at.astimezone(IST):%d %b, %I:%M %p}"
            + (f" at {a.location}" if a.location else ""),
            link=f"/post-sales/{case.id}?tab=appointments",
        )
    await db.commit()
    return await list_for(db, case, user)


async def _apt(db: DbSession, aid: int) -> tuple[Appointment, PostSalesCase]:
    a = await db.get(Appointment, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found")
    return a, await _case(db, a.case_id)


@router.post("/appointments/{aid}/confirm", response_model=CaseAppointments)
async def confirm(
    aid: int, body: ConfirmIn, request: Request, user: Scheduler, db: DbSession
) -> CaseAppointments:
    a, case = await _apt(db, aid)
    if a.status != AppointmentStatus.scheduled:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a scheduled appointment can be confirmed"
        )
    a.confirmed_on, a.confirmed_via = datetime.now(IST).date(), body.via
    _log(db, case, user, "appointment_confirmed", a, request, {"via": body.via})
    await db.commit()
    return await list_for(db, case, user)


@router.post("/appointments/{aid}/reschedule", response_model=CaseAppointments)
async def reschedule(
    aid: int, body: RescheduleIn, request: Request, user: Scheduler, db: DbSession
) -> CaseAppointments:
    """The old appointment is kept (with the reason); a new one takes its place. Confirmation is needed again."""
    a, case = await _apt(db, aid)
    if a.status not in (AppointmentStatus.scheduled, AppointmentStatus.no_show):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a scheduled or missed appointment can be rescheduled",
        )
    minutes = body.duration_min or a.duration_min
    await _check_time_and_owner(
        db, a.owner_id, body.starts_at, minutes, body.allow_clash, exclude=a.id
    )
    was_missed = a.status == AppointmentStatus.no_show
    if not was_missed:
        a.status, a.status_reason = AppointmentStatus.rescheduled, body.reason
    a.follow_up_on = None
    new = Appointment(
        case_id=case.id,
        kind=a.kind,
        title=a.title,
        starts_at=body.starts_at,
        duration_min=minutes,
        location=body.location or a.location,
        owner_id=a.owner_id,
        required_docs=a.required_docs,
        notes=a.notes,
        rescheduled_from_id=a.id,
        created_by_id=user.id,
    )
    db.add(new)
    await db.flush()
    _log(
        db,
        case,
        user,
        "appointment_rescheduled",
        new,
        request,
        {"from": code(a), "reason": body.reason},
    )
    await db.commit()
    return await list_for(db, case, user)


@router.post("/appointments/{aid}/cancel", response_model=CaseAppointments)
async def cancel(
    aid: int, body: ReasonIn, request: Request, user: Scheduler, db: DbSession
) -> CaseAppointments:
    a, case = await _apt(db, aid)
    if a.status != AppointmentStatus.scheduled:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a scheduled appointment can be cancelled"
        )
    a.status, a.status_reason = AppointmentStatus.cancelled, body.reason
    _log(db, case, user, "appointment_cancelled", a, request, {"reason": body.reason})
    await db.commit()
    return await list_for(db, case, user)


@router.post("/appointments/{aid}/attendance", response_model=CaseAppointments)
async def attendance(
    aid: int, body: AttendanceIn, request: Request, user: Scheduler, db: DbSession
) -> CaseAppointments:
    """Attended (with the outcome), or a no-show, which creates a follow-up for the next day."""
    a, case = await _apt(db, aid)
    if a.status != AppointmentStatus.scheduled:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Attendance can only be recorded for a scheduled appointment",
        )
    if a.starts_at > now():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Record attendance once the appointment time has come",
        )
    if body.attended:
        if not (body.outcome or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Write the outcome of the appointment"
            )
        a.status, a.outcome = AppointmentStatus.attended, body.outcome.strip()
        _log(db, case, user, "appointment_attended", a, request)
    else:
        a.status, a.outcome = AppointmentStatus.no_show, (body.outcome or "").strip() or None
        a.follow_up_on = datetime.now(IST).date() + timedelta(days=1)
        _log(
            db,
            case,
            user,
            "appointment_missed",
            a,
            request,
            {"follow_up_on": a.follow_up_on.isoformat()},
        )
        who = a.owner_id or case.owner_id
        if who:
            notify(
                db,
                user_id=who,
                type="appointment_missed",
                title=f"Missed {svc.LABELS[a.kind].lower()}: {case.booking.lead.name}",
                body=f"Follow up on {a.follow_up_on:%d %b} and reschedule",
                link=f"/post-sales/{case.id}?tab=appointments",
            )
    await db.commit()
    return await list_for(db, case, user)
