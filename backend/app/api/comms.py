from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import func, select

from app.core.deps import DbSession, require_role
from app.models.comms import CommMessage, CommTemplate
from app.models.postsales import CustomerProfile, PostSalesCase
from app.models.project import Project
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.services import comms as svc
from app.services.audit import log_audit

router = APIRouter(tags=["communications"])
VIEW = (Role.admin, Role.crm_manager, Role.management, Role.auditor)
EDIT = (Role.admin, Role.crm_manager)
Viewer = Annotated[User, Depends(require_role(*VIEW))]
Editor = Annotated[User, Depends(require_role(*EDIT))]
CaseViewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]


class TemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: str
    channel: Literal["email", "sms", "whatsapp"]
    project_id: int | None = None
    language: Annotated[PlainText, StringConstraints(min_length=2, max_length=30)] = "English"
    subject: Annotated[PlainText, StringConstraints(max_length=200)] | None = None
    body: Annotated[str, StringConstraints(min_length=10, max_length=4000)]
    mandatory: bool = False
    delay_minutes: Annotated[int, Field(ge=0, le=10080)] = 0


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


def t_out(t: CommTemplate, users: dict, user: User) -> dict:
    return {
        "id": t.id,
        "event": t.event,
        "channel": t.channel,
        "project_id": t.project_id,
        "version": t.version,
        "language": t.language,
        "subject": t.subject,
        "body": t.body,
        "mandatory": t.mandatory,
        "delay_minutes": t.delay_minutes,
        "status": t.status,
        "author": users.get(t.author_id, "Starting draft"),
        "approved_by": users.get(t.approved_by_id),
        "approved_at": t.approved_at,
        "created_at": t.created_at,
        "can_edit": t.status == "draft"
        and user.role in EDIT
        and (t.author_id in (None, user.id) or user.role == Role.admin),
        "can_approve": t.status == "draft" and user.role in EDIT and t.author_id != user.id,
    }


async def _users(db: DbSession, ids: set) -> dict:
    ids = {i for i in ids if i}
    return (
        {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(ids)))}
        if ids
        else {}
    )


@router.get("/comms/templates")
async def templates(user: Viewer, db: DbSession) -> dict:
    rows = list(
        await db.scalars(
            select(CommTemplate).order_by(
                CommTemplate.event, CommTemplate.channel, CommTemplate.version.desc()
            )
        )
    )
    users = await _users(db, {x for t in rows for x in (t.author_id, t.approved_by_id)})
    return {
        "events": {
            k: {"label": v["label"], "fields": svc.BASE + v["fields"], "channels": v["channels"]}
            for k, v in svc.EVENTS.items()
        },
        "templates": [t_out(t, users, user) for t in rows],
        "channels": {c: svc.channel_ready(c) for c in ("email", "sms", "whatsapp")},
        "projects": [
            {"id": p.id, "name": p.name}
            for p in await db.scalars(select(Project).order_by(Project.name))
        ],
    }


def _validate(body: TemplateIn) -> None:
    problem = svc.check_template(body.event, body.subject, body.body)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    if body.channel == "email" and not (body.subject or "").strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "An email needs a subject")
    if body.channel == "sms" and len(body.body) > 480:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Keep SMS text under 480 characters"
        )


@router.post("/comms/templates", status_code=status.HTTP_201_CREATED)
async def new_version(body: TemplateIn, request: Request, user: Editor, db: DbSession) -> dict:
    """A new draft version; it sends nothing until someone else approves it."""
    _validate(body)
    v = await db.scalar(
        select(func.max(CommTemplate.version)).where(
            CommTemplate.event == body.event,
            CommTemplate.channel == body.channel,
            CommTemplate.project_id.is_(None)
            if body.project_id is None
            else CommTemplate.project_id == body.project_id,
        )
    )
    t = CommTemplate(**body.model_dump(), version=(v or 0) + 1, author_id=user.id, status="draft")
    db.add(t)
    await db.flush()
    log_audit(
        db,
        action="comms.template_drafted",
        entity_type="comm_template",
        entity_id=t.id,
        actor=user,
        details={"event": body.event, "channel": body.channel, "version": t.version},
        request=request,
    )
    await db.commit()
    return await templates(user, db)


@router.put("/comms/templates/{tid}")
async def edit(tid: int, body: TemplateIn, request: Request, user: Editor, db: DbSession) -> dict:
    t = await db.get(CommTemplate, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    if t.status != "draft":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Approved templates aren't edited: create a new version",
        )
    if (body.event, body.channel, body.project_id) != (t.event, t.channel, t.project_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The event, channel and project can't change; create a new template",
        )
    _validate(body)
    for k in ("language", "subject", "body", "mandatory", "delay_minutes"):
        setattr(t, k, getattr(body, k))
    t.author_id = t.author_id or user.id
    await db.commit()
    return await templates(user, db)


@router.post("/comms/templates/{tid}/approve")
async def approve(tid: int, request: Request, user: Editor, db: DbSession) -> dict:
    """Someone other than the author approves; the previous approved version for the same event, channel and project retires."""
    t = await db.get(CommTemplate, tid)
    if t is None or t.status != "draft":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a draft can be approved")
    if t.author_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Someone other than the author approves the wording"
        )
    problem = svc.check_template(t.event, t.subject, t.body)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, problem)
    for old in await db.scalars(
        select(CommTemplate).where(
            CommTemplate.event == t.event,
            CommTemplate.channel == t.channel,
            CommTemplate.status == "approved",
            CommTemplate.project_id.is_(None)
            if t.project_id is None
            else CommTemplate.project_id == t.project_id,
        )
    ):
        old.status = "retired"
    await db.flush()
    t.status, t.approved_by_id, t.approved_at = "approved", user.id, svc.now()
    log_audit(
        db,
        action="comms.template_approved",
        entity_type="comm_template",
        entity_id=t.id,
        actor=user,
        details={"event": t.event, "channel": t.channel, "version": t.version},
        request=request,
    )
    await db.commit()
    return await templates(user, db)


@router.post("/comms/templates/{tid}/retire")
async def retire(tid: int, request: Request, user: Editor, db: DbSession) -> dict:
    t = await db.get(CommTemplate, tid)
    if t is None or t.status == "retired":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to retire")
    t.status = "retired"
    log_audit(
        db,
        action="comms.template_retired",
        entity_type="comm_template",
        entity_id=t.id,
        actor=user,
        details={"event": t.event, "channel": t.channel},
        request=request,
    )
    await db.commit()
    return await templates(user, db)


@router.post("/comms/templates/{tid}/preview")
async def preview(tid: int, _: Viewer, db: DbSession) -> dict:
    t = await db.get(CommTemplate, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    sample = {
        "customer": "Anita Desai",
        "project": "Habitat",
        "unit": "1114",
        "case_code": "PSC-00004",
        "company": "Avnee Estates LLP",
        "stage": "Plinth",
        "amount": "3,22,500",
        "due_date": "15 Dec 2026",
        "document": "Possession letter",
        "reason": "the PAN copy is not legible",
        "agreement_no": "AGR-00004",
        "registration_no": "HVL1-1114",
        "registered_on": "20 Nov 2026",
        "receipt_no": "RCT-00012",
        "received_on": "18 Nov 2026",
        "ticket_no": "TKT-00031",
        "title": "Seepage in bathroom",
        "when": "28 Nov 2026, 11:00 am",
        "location": "Habitat site office",
        "defect_no": "DEF-00007",
        "description": "Shower mixer leak",
        "paid_on": "21 Nov 2026",
        "utr": "HDFCR0001",
    }
    subject, body = svc.render(t, sample)
    return {"subject": subject, "body": body}


def m_out(m: CommMessage) -> dict:
    return {
        "id": m.id,
        "case_id": m.case_id,
        "event": m.event,
        "event_label": svc.EVENTS.get(m.event, {}).get("label", m.event),
        "channel": m.channel,
        "recipient": m.recipient,
        "subject": m.subject,
        "body": m.body,
        "status": m.status,
        "reason": m.reason,
        "attempts": m.attempts,
        "send_after": m.send_after,
        "sent_at": m.sent_at,
        "created_at": m.created_at,
        "template_version": m.template_version,
    }


@router.get("/comms/messages")
async def messages(
    _: Viewer,
    db: DbSession,
    status_: Annotated[str | None, Field(alias="status")] = None,
    event: str | None = None,
    limit: int = 200,
) -> list[dict]:
    q = select(CommMessage)
    if status_:
        q = q.where(CommMessage.status == status_)
    if event:
        q = q.where(CommMessage.event == event)
    return [
        m_out(m) for m in await db.scalars(q.order_by(CommMessage.id.desc()).limit(min(limit, 500)))
    ]


@router.post("/comms/messages/{mid}/retry")
async def retry(mid: int, request: Request, user: Editor, db: DbSession) -> dict:
    m = await db.get(CommMessage, mid)
    if m is None or m.status not in ("failed", "held"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only a failed or held message can be retried"
        )
    m.status, m.attempts, m.send_after = "queued", 0, svc.now()
    log_audit(
        db,
        action="comms.retry",
        entity_type="comm_message",
        entity_id=m.id,
        actor=user,
        details={"event": m.event, "channel": m.channel},
        request=request,
    )
    await db.commit()
    return m_out(m)


@router.get("/post-sales/cases/{case_id}/communications")
async def case_comms(case_id: int, _: CaseViewer, db: DbSession) -> dict:
    """The customer's communication history and their consent and channel preferences (edited on the Customer tab)."""
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    p = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case_id))
    rows = list(
        await db.scalars(
            select(CommMessage)
            .where(CommMessage.case_id == case_id)
            .order_by(CommMessage.id.desc())
        )
    )
    return {
        "messages": [m_out(m) for m in rows],
        "preferences": None
        if p is None
        else {
            "email": p.email,
            "mobile": p.mobile,
            "contact_email": p.contact_email,
            "contact_sms": p.contact_sms,
            "contact_whatsapp": p.contact_whatsapp,
            "consent_electronic_at": p.consent_electronic_at,
            "preferred_language": p.preferred_language,
        },
        "channels": {c: svc.channel_ready(c) for c in ("email", "sms", "whatsapp")},
    }
