from datetime import date, timedelta
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.ticket import (
    ClosureReason,
    Priority,
    Team,
    Ticket,
    TicketAttachment,
    TicketCategory,
    TicketEvent,
    TicketStatus,
)
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import postsales as cases
from app.services import receipts as files
from app.services import tickets as svc
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(tags=["customer service"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
AGENTS = tuple(r for r in POSTSALES_ROLES if r not in (Role.auditor, Role.management))
Agent = Annotated[User, Depends(require_role(*AGENTS))]
Manager = Annotated[User, Depends(require_role(Role.admin, Role.crm_manager))]
FOLDER = "tickets"
S = TicketStatus
Txt = Annotated[PlainText, StringConstraints(min_length=2, max_length=5000)]
WORK = (S.in_progress, S.waiting_customer, S.waiting_internal, S.waiting_external)


class AssignIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    owner_id: int
    team: Team | None = None


class StatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["in_progress", "waiting_customer", "waiting_internal", "waiting_external"]
    note: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: Txt


class MessageIn(TextIn):
    direction: Literal["in", "out"]  # from the customer / to the customer
    channel: Literal["phone", "email", "whatsapp", "sms", "visit", "letter", "portal"] = "phone"


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool
    csat: Annotated[int, Field(ge=1, le=5)] | None = None
    comment: Annotated[PlainText, StringConstraints(max_length=1000)] | None = None


class CloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    closure_reason: ClosureReason
    note: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=1000)]


def code(t: Ticket) -> str:
    return f"TKT-{t.id:05d}"


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _ticket(db: DbSession, tid: int) -> Ticket:
    t = await db.get(Ticket, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ticket not found")
    return t


def summary(t: Ticket, case: PostSalesCase, users: dict, pct: int = 25) -> dict:
    return {
        "id": t.id,
        "ticket_no": code(t),
        "case_id": case.id,
        "case_code": cases.code(case),
        "customer": case.booking.lead.name,
        "unit": f"{case.booking.unit.unit_no}",
        "category": t.category.value,
        "category_label": svc.LABELS[t.category],
        "subcategory": t.subcategory,
        "title": t.title,
        "priority": t.priority.value,
        "team": t.team.value,
        "team_label": svc.TEAM_LABELS[t.team],
        "status": t.status.value,
        "owner": users.get(t.owner_id),
        "created_at": t.created_at,
        "closed_at": t.closed_at,
        "closure_reason": t.closure_reason.value if t.closure_reason else None,
        "reopened_count": t.reopened_count,
        "csat": t.csat,
        "sla": svc.sla(t, None, pct),
    }


async def _users(db: DbSession, ids: set) -> dict:
    ids = {i for i in ids if i}
    return (
        {
            u.id: UserBrief.model_validate(u).model_dump()
            for u in await db.scalars(select(User).where(User.id.in_(ids)))
        }
        if ids
        else {}
    )


async def detail(db: DbSession, t: Ticket, user: User) -> dict:
    await db.refresh(t)
    cfg = await svc.get_settings(db)
    case = await _case(db, t.case_id)
    users = await _users(db, {t.owner_id, t.raised_by_id, *(e.by_id for e in t.events)})
    agent = user.role in AGENTS
    closed_ago = (svc.now() - t.closed_at) if t.closed_at else None
    return summary(t, case, users, cfg["at_risk_pct"]) | {
        "description": t.description,
        "channel": t.channel,
        "raised_by": users.get(t.raised_by_id),
        "resolution": t.resolution,
        "resolved_at": t.resolved_at,
        "customer_confirmed": t.customer_confirmed,
        "confirmed_at": t.confirmed_at,
        "csat_comment": t.csat_comment,
        "needs_confirmation": t.needs_confirmation,
        "escalations": [
            {"level": e.level, "rule": e.rule, "recipients": e.recipients, "at": e.at}
            for e in t.escalations
        ],
        "timeline": [
            {
                "id": e.id,
                "kind": e.kind,
                "internal": e.internal,
                "text": e.text_,
                "data": e.data,
                "by": users.get(e.by_id),
                "at": e.at,
            }
            for e in t.events
        ],
        "attachments": [
            {
                "id": a.id,
                "file_name": a.file_name,
                "purpose": a.purpose,
                "url": f"/api/tickets/attachments/{a.id}",
            }
            for a in t.attachments
        ],
        "can": {
            "assign": user.role in (Role.admin, Role.crm_manager) and t.status != S.closed,
            "acknowledge": agent and t.status in (S.raised, S.assigned),
            "work": agent and t.status in (S.acknowledged, *WORK),
            "propose": agent and t.status in (S.acknowledged, *WORK),
            "confirm": agent and t.status == S.resolution_proposed,
            "close": agent and t.status != S.closed,
            "reopen": t.status == S.closed
            and (
                user.role in (Role.admin, Role.crm_manager)
                or (
                    agent
                    and closed_ago is not None
                    and closed_ago <= timedelta(days=int(cfg["reopen_days"]))
                )
            ),
            "note": agent,
            "message": agent and t.status != S.closed,
        },
        "reopen_days": cfg["reopen_days"],
        "owners": [
            UserBrief.model_validate(u).model_dump()
            for u in await db.scalars(
                select(User)
                .where(User.is_active.is_(True), User.role.in_(list(AGENTS)))
                .order_by(User.full_name)
            )
        ]
        if user.role in (Role.admin, Role.crm_manager)
        else [],
    }


def _event(
    t: Ticket,
    user: User | None,
    kind: str,
    text: str | None = None,
    internal: bool = True,
    data: dict | None = None,
) -> None:
    t.events.append(
        TicketEvent(
            kind=kind, text_=text, internal=internal, data=data, by_id=user.id if user else None
        )
    )


def _move(t: Ticket, new: S, user: User, note: str | None = None) -> None:
    old = t.status
    svc.pause_or_resume(t, new, svc.now())
    t.status = new
    _event(t, user, "status", note, data={"from": old.value, "to": new.value})


def _audit(
    db: DbSession, user: User, action: str, t: Ticket, request: Request, details: dict | None = None
) -> None:
    log_audit(
        db,
        action=f"ticket.{action}",
        entity_type="ticket",
        entity_id=t.id,
        actor=user,
        details={"ticket": code(t), **(details or {})},
        request=request,
    )


@router.get("/tickets")
async def list_tickets(
    user: Viewer,
    db: DbSession,
    view: Literal["open", "mine", "at_risk", "breached", "closed", "all"] = "open",
    category: TicketCategory | None = None,
    team: Team | None = None,
    case_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> dict:
    q = select(Ticket)
    if view == "closed":
        q = q.where(Ticket.status == S.closed)
    elif view != "all":
        q = q.where(Ticket.status != S.closed)
    if view == "mine":
        q = q.where(Ticket.owner_id == user.id)
    if category:
        q = q.where(Ticket.category == category)
    if team:
        q = q.where(Ticket.team == team)
    if case_id:
        q = q.where(Ticket.case_id == case_id)
    rows = list(await db.scalars(q.order_by(Ticket.resolution_due_at).limit(limit)))
    users = await _users(db, {t.owner_id for t in rows})
    pct = (await svc.get_settings(db))["at_risk_pct"]
    items = [summary(t, await _case(db, t.case_id), users, pct) for t in rows]
    if view == "at_risk":
        items = [i for i in items if i["sla"]["at_risk"]]
    elif view == "breached":
        items = [
            i
            for i in items
            if i["sla"]["resolution_breached"]
            or (i["sla"]["response_breached"] and not i["sla"]["first_response_at"])
        ]
    return {
        "items": items,
        "categories": {k.value: v for k, v in svc.LABELS.items()},
        "teams": {k.value: v for k, v in svc.TEAM_LABELS.items()},
    }


@router.post("/post-sales/cases/{case_id}/tickets", status_code=status.HTTP_201_CREATED)
async def raise_ticket(
    case_id: int,
    request: Request,
    user: Agent,
    db: DbSession,
    category: Annotated[TicketCategory, Form()],
    title: Annotated[str, Form(min_length=3, max_length=200)],
    description: Annotated[str, Form(min_length=5, max_length=5000)],
    priority: Annotated[Priority, Form()] = Priority.normal,
    subcategory: Annotated[str | None, Form(max_length=120)] = None,
    channel: Annotated[
        Literal["phone", "email", "whatsapp", "walk_in", "letter", "portal", "other"], Form()
    ] = "phone",
    attachments: Annotated[list[UploadFile] | None, File()] = None,
) -> dict:
    """Raise a ticket for the customer of this case; the team comes from the category and the targets from the priority."""
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Tickets are raised on accepted cases"
        )
    for v in (title, description, subcategory):
        if v and ("<" in v or ">" in v):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Text can't contain < or >")
    if attachments and len(attachments) > 10:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Attach up to 10 files")
    stored = []
    try:
        for f in attachments or []:
            stored.append(await files.save_receipt(f, folder=FOLDER, max_mb=15, what="Attachments"))
    except files.ReceiptError as exc:
        for path, _, _ in stored:
            files.delete_receipt(path, FOLDER)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    cfg = await svc.get_settings(db)
    t = Ticket(
        case_id=case.id,
        category=category,
        subcategory=(subcategory or "").strip() or None,
        title=title.strip(),
        description=description.strip(),
        channel=channel,
        priority=priority,
        team=Team(cfg["categories"][category.value]["team"]),
        events=[],  # a new ticket starts with an empty timeline (loaded, so adding to it needs no database read)
        raised_by_id=user.id,
    )
    svc.set_targets(t, svc.now(), cfg)
    t.attachments = [
        TicketAttachment(file_path=p, file_name=n, file_type=m, uploaded_by_id=user.id)
        for p, n, m in stored
    ]
    db.add(t)
    await db.flush()
    _event(
        t,
        user,
        "raised",
        t.description,
        internal=False,
        data={"category": svc.LABELS[category], "priority": priority.value, "channel": channel},
    )
    cases.event(
        db,
        case,
        "ticket_raised",
        user,
        {"ticket": code(t), "category": svc.LABELS[category], "priority": priority.value},
    )
    _audit(db, user, "raised", t, request, {"category": category.value, "priority": priority.value})
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.crm_manager, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="ticket_raised",
            title=f"New {priority.value} ticket: {case.booking.lead.name}",
            body=f"{code(t)} {svc.LABELS[category]}: {t.title}",
            link=f"/service/{t.id}",
        )
    from app.services import comms

    await comms.emit(db, "complaint_created", case, {"ticket_no": code(t), "title": t.title}, t.id)
    await db.commit()
    return await detail(db, t, user)


@router.get("/tickets/{tid}")
async def get_ticket(tid: int, user: Viewer, db: DbSession) -> dict:
    return await detail(db, await _ticket(db, tid), user)


@router.post("/tickets/{tid}/assign")
async def assign(tid: int, body: AssignIn, request: Request, user: Manager, db: DbSession) -> dict:
    t = await _ticket(db, tid)
    if t.status == S.closed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Reopen the ticket first")
    owner = await db.get(User, body.owner_id)
    if owner is None or not owner.is_active or owner.role not in AGENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Choose an active post-sales team member"
        )
    t.owner_id, t.team = owner.id, body.team or t.team
    _event(
        t, user, "assigned", None, data={"owner": owner.full_name, "team": svc.TEAM_LABELS[t.team]}
    )
    if t.status == S.raised:
        _move(t, S.assigned, user)
    _audit(db, user, "assigned", t, request, {"owner": owner.full_name})
    if owner.id != user.id:
        notify(
            db,
            user_id=owner.id,
            type="ticket_assigned",
            title=f"Ticket assigned: {code(t)}",
            body=t.title,
            link=f"/service/{t.id}",
        )
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/acknowledge")
async def acknowledge(tid: int, body: TextIn, request: Request, user: Agent, db: DbSession) -> dict:
    """The first response to the customer (it stops the response clock)."""
    t = await _ticket(db, tid)
    if t.status not in (S.raised, S.assigned):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This ticket is already acknowledged"
        )
    t.acknowledged_at = svc.now()
    if t.owner_id is None:
        t.owner_id = user.id
    _event(t, user, "message_out", body.text, internal=False, data={"first_response": True})
    _move(t, S.acknowledged, user)
    _audit(db, user, "acknowledged", t, request)
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/status")
async def change_status(
    tid: int, body: StatusIn, request: Request, user: Agent, db: DbSession
) -> dict:
    t = await _ticket(db, tid)
    if t.status not in (S.acknowledged, *WORK):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Acknowledge the ticket first"
            if t.status in (S.raised, S.assigned)
            else "Not possible at this stage",
        )
    new = S(body.status)
    if new == t.status:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The ticket is already in that state"
        )
    if new != S.in_progress and not (body.note or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Say what (or who) the ticket is waiting for"
        )
    _move(t, new, user, (body.note or "").strip() or None)
    _audit(db, user, "status", t, request, {"to": new.value})
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/notes")
async def add_note(tid: int, body: TextIn, request: Request, user: Agent, db: DbSession) -> dict:
    """An internal note: never shown to the customer."""
    t = await _ticket(db, tid)
    _event(t, user, "note", body.text, internal=True)
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/messages")
async def add_message(
    tid: int, body: MessageIn, request: Request, user: Agent, db: DbSession
) -> dict:
    """The customer communication log: what was said to or received from the customer."""
    t = await _ticket(db, tid)
    if t.status == S.closed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Reopen the ticket to continue the conversation"
        )
    if body.direction == "out" and t.acknowledged_at is None:
        t.acknowledged_at = svc.now()  # replying is a first response
        if t.status in (S.raised, S.assigned):
            if t.owner_id is None:
                t.owner_id = user.id
            _move(t, S.acknowledged, user)
    _event(
        t,
        user,
        f"message_{body.direction}",
        body.text,
        internal=False,
        data={"channel": body.channel},
    )
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/attachments")
async def attach(
    tid: int,
    request: Request,
    user: Agent,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    purpose: Annotated[Literal["evidence", "resolution"], Form()] = "evidence",
) -> dict:
    t = await _ticket(db, tid)
    try:
        p, n, m = await files.save_receipt(file, folder=FOLDER, max_mb=15, what="Attachments")
    except files.ReceiptError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    t.attachments.append(
        TicketAttachment(
            file_path=p, file_name=n, file_type=m, purpose=purpose, uploaded_by_id=user.id
        )
    )
    _event(t, user, "attachment", n, internal=purpose != "evidence", data={"purpose": purpose})
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/propose")
async def propose(tid: int, body: TextIn, request: Request, user: Agent, db: DbSession) -> dict:
    """The action taken; stops the resolution clock. Categories that need it then wait for the customer's confirmation."""
    t = await _ticket(db, tid)
    if t.status not in (S.acknowledged, *WORK):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Acknowledge the ticket first"
            if t.status in (S.raised, S.assigned)
            else "Not possible at this stage",
        )
    t.resolution, t.resolved_at = body.text, svc.now()
    _move(t, S.resolution_proposed, user)
    _event(t, user, "resolution", body.text, internal=False)
    _audit(db, user, "resolution_proposed", t, request)
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/confirmation")
async def confirmation(
    tid: int, body: ConfirmIn, request: Request, user: Agent, db: DbSession
) -> dict:
    """The customer's response to the resolution: confirmed (with a satisfaction score), or not, which reopens the work."""
    t = await _ticket(db, tid)
    if t.status != S.resolution_proposed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Propose a resolution first")
    if body.confirmed:
        t.customer_confirmed, t.confirmed_at, t.csat, t.csat_comment = (
            True,
            svc.now(),
            body.csat,
            body.comment,
        )
        _event(t, user, "confirmed", body.comment, internal=False, data={"csat": body.csat})
    else:
        if not (body.comment or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Record what the customer says is still wrong",
            )
        t.customer_confirmed, t.resolved_at = False, None
        _event(t, user, "not_confirmed", body.comment, internal=False)
        _move(t, S.in_progress, user)
    _audit(db, user, "confirmation", t, request, {"confirmed": body.confirmed, "csat": body.csat})
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/close")
async def close(tid: int, body: CloseIn, request: Request, user: Agent, db: DbSession) -> dict:
    t = await _ticket(db, tid)
    if t.status == S.closed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Already closed")
    if body.closure_reason == ClosureReason.resolved:
        if t.status != S.resolution_proposed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Propose the resolution before closing it as resolved",
            )
        if t.needs_confirmation and not t.customer_confirmed:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "This category needs the customer's confirmation before closing as resolved",
            )
    elif not (body.note or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Add a note explaining the closure"
        )
    if t.resolved_at is None:
        t.resolved_at = svc.now()
    old = t.status
    svc.pause_or_resume(t, S.closed, svc.now())
    t.status, t.closure_reason, t.closed_at = S.closed, body.closure_reason, svc.now()
    _event(
        t,
        user,
        "closed",
        (body.note or "").strip() or None,
        internal=False,
        data={"from": old.value, "reason": body.closure_reason.value},
    )
    case = await _case(db, t.case_id)
    cases.event(
        db, case, "ticket_closed", user, {"ticket": code(t), "reason": body.closure_reason.value}
    )
    _audit(db, user, "closed", t, request, {"reason": body.closure_reason.value})
    await db.commit()
    return await detail(db, t, user)


@router.post("/tickets/{tid}/reopen")
async def reopen(tid: int, body: ReasonIn, request: Request, user: Agent, db: DbSession) -> dict:
    """Within the reopen period anyone on the team; after it, only a CRM manager or admin (authorised escalation)."""
    t = await _ticket(db, tid)
    if t.status != S.closed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a closed ticket can be reopened"
        )
    cfg = await svc.get_settings(db)
    days = int(cfg["reopen_days"])
    late = (svc.now() - t.closed_at) > timedelta(days=days)
    if late and user.role not in (Role.admin, Role.crm_manager):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"Closed more than {days} days ago: a CRM manager must reopen it",
        )
    previous = {"closed_at": t.closed_at.isoformat(), "reason": t.closure_reason.value}
    t.status, t.closure_reason, t.closed_at, t.resolved_at, t.customer_confirmed, t.confirmed_at = (
        S.in_progress,
        None,
        None,
        None,
        None,
        None,
    )
    t.reopened_count += 1
    t.escalation_level = 0  # escalation starts again for the reopened work
    t.resolution_due_at = svc.now() + timedelta(
        hours=t.resolution_window_h
    )  # a fresh resolution target
    _event(
        t,
        user,
        "reopened",
        body.reason,
        internal=False,
        data={"previous": previous, "authorised_escalation": late},
    )
    _audit(db, user, "reopened", t, request, {"reason": body.reason, "late": late})
    await db.commit()
    return await detail(db, t, user)


@router.get("/tickets/attachments/{aid}")
async def attachment(aid: int, _: Viewer, db: DbSession) -> FileResponse:
    a = await db.get(TicketAttachment, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    path = files.receipt_file(a.file_path, FOLDER)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    return FileResponse(
        path,
        media_type=a.file_type,
        headers={"Content-Disposition": f'inline; filename="{a.file_name}"'},
    )


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_hours: dict[Priority, Annotated[int, Field(ge=1, le=720)]]
    resolution_hours: dict[Priority, Annotated[int, Field(ge=1, le=2160)]]
    at_risk_pct: Annotated[int, Field(ge=5, le=75)] = 25
    reopen_days: Annotated[int, Field(ge=0, le=90)] = 14
    categories: dict[TicketCategory, dict]
    escalation: dict


@router.get("/service/settings")
async def get_service_settings(user: Viewer, db: DbSession) -> dict:
    return {
        **await svc.get_settings(db),
        "labels": {k.value: v for k, v in svc.LABELS.items()},
        "teams": {k.value: v for k, v in svc.TEAM_LABELS.items()},
        "can_edit": user.role == Role.admin,
    }


@router.put("/service/settings")
async def put_service_settings(
    body: SettingsIn,
    request: Request,
    user: Annotated[User, Depends(require_role(Role.admin))],
    db: DbSession,
) -> dict:
    """SLA targets, category rules and escalation recipients. Applies to tickets raised from now on."""
    from app.models.ticket import ServiceSettings

    if (
        set(body.response_hours) != set(Priority)
        or set(body.resolution_hours) != set(Priority)
        or set(body.categories) != set(TicketCategory)
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Give targets for every priority and rules for every category",
        )
    for p in Priority:
        if body.response_hours[p] > body.resolution_hours[p]:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{p.value.capitalize()}: the response target can't be longer than the resolution target",
            )
    cats = {}
    for c, rule in body.categories.items():
        if rule.get("team") not in {t.value for t in Team} or not isinstance(
            rule.get("needs_confirmation"), bool
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{svc.LABELS[c]}: choose a team and whether confirmation is needed",
            )
        cats[c.value] = {"team": rule["team"], "needs_confirmation": rule["needs_confirmation"]}
    esc = body.escalation
    allowed = {r.value for r in POSTSALES_ROLES}
    l2, l3, after = esc.get("level2_roles"), esc.get("level3_roles"), esc.get("level3_after_hours")
    if not (
        isinstance(l2, list)
        and l2
        and set(l2) <= allowed
        and isinstance(l3, list)
        and l3
        and set(l3) <= allowed
        and isinstance(after, int)
        and 1 <= after <= 720
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Escalation needs recipients for levels 2 and 3, and level 3 after 1 to 720 hours",
        )
    data = {
        "response_hours": {p.value: h for p, h in body.response_hours.items()},
        "resolution_hours": {p.value: h for p, h in body.resolution_hours.items()},
        "at_risk_pct": body.at_risk_pct,
        "reopen_days": body.reopen_days,
        "categories": cats,
        "escalation": {"level2_roles": l2, "level3_roles": l3, "level3_after_hours": after},
    }
    row = await db.get(ServiceSettings, 1)
    before = row.data if row else None
    if row is None:
        db.add(ServiceSettings(id=1, data=data, updated_by_id=user.id))
    else:
        row.data, row.updated_by_id = data, user.id
    log_audit(
        db,
        action="service.settings_changed",
        entity_type="service_settings",
        entity_id=1,
        actor=user,
        details={"before": before, "after": data},
        request=request,
    )
    await db.commit()
    return {
        **await svc.get_settings(db),
        "labels": {k.value: v for k, v in svc.LABELS.items()},
        "teams": {k.value: v for k, v in svc.TEAM_LABELS.items()},
        "can_edit": True,
    }


@router.get("/service/reports")
async def service_reports(
    user: Viewer, db: DbSession, start: date | None = None, end: date | None = None
) -> dict:
    """Tickets raised in the period (India time); times in hours; paused time shown separately."""
    from datetime import datetime as dt
    from datetime import timezone as tz

    ist = tz(timedelta(hours=5, minutes=30))
    today = svc.now().astimezone(ist).date()
    end = end or today
    start = start or (end - timedelta(days=29))
    if start > end:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The start date must be before the end date"
        )
    lo = dt.combine(start, dt.min.time(), tzinfo=ist)
    hi = dt.combine(end + timedelta(days=1), dt.min.time(), tzinfo=ist)
    rows = list(
        await db.scalars(select(Ticket).where(Ticket.created_at >= lo, Ticket.created_at < hi))
    )
    cfg = await svc.get_settings(db)
    return {"start": start, "end": end, **svc.report(rows, svc.now(), cfg["at_risk_pct"])}
