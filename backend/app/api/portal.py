"""The customer portal API (/api/portal). Customers only ever see their own cases: anything else is 'not found'."""

import asyncio
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.deps import DbSession
from app.models.aftersales import FacilityHandover
from app.models.case_document import Approval, CaseDocument, Visibility
from app.models.comms import CommMessage
from app.models.inventory import Building, Floor
from app.models.portal import CustomerAccount, PortalCode, PortalSession
from app.models.postsales import CoApplicant, CustomerProfile, KycDocument, PostSalesCase
from app.models.project_update import ProjectUpdate, ProjectUpdatePhoto, UpdateStatus
from app.models.ticket import Priority, Team, Ticket, TicketCategory, TicketEvent
from app.models.user import Role, User
from app.schemas.common import PlainText
from app.services import case_documents as doc_svc
from app.services import comms
from app.services import portal as svc
from app.services import receipts as files
from app.services import tickets as ticket_svc
from app.services.audit import log_audit

router = APIRouter(prefix="/portal", tags=["customer portal"])
COOKIE = "portal_session"
CODE_MINUTES, CODE_TRIES, CODE_REQUESTS = 10, 5, 3
IDLE_MINUTES, MAX_HOURS = 60, 8
GENERIC = "If this email belongs to a registered customer, we've sent a sign-in code to it."


def now() -> datetime:
    return datetime.now(UTC)


def _hash(*parts: str) -> str:
    return hashlib.sha256(("|".join(parts) + "|" + get_settings().secret_key).encode()).hexdigest()


def enabled() -> tuple[bool, str | None]:
    s = get_settings()
    if not s.portal_enabled:
        return False, "The customer portal isn't switched on yet."
    if s.is_production and not s.secure_cookies:
        return False, "The customer portal needs HTTPS before it can be used."
    return True, None


def _require_enabled() -> None:
    ok, why = enabled()
    if not ok:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, why)


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            to_lower=True,
            min_length=5,
            max_length=254,
            pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        ),
    ]


class VerifyIn(RequestIn):
    code: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[0-9]{6}$")]


async def current_account(
    request: Request, db: DbSession, portal_session: Annotated[str | None, Cookie()] = None
) -> tuple[CustomerAccount, PortalSession]:
    _require_enabled()
    if not portal_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in")
    s = await db.get(PortalSession, hashlib.sha256(portal_session.encode()).hexdigest())
    t = now()
    if (
        s is None
        or s.revoked_at
        or s.expires_at <= t
        or s.last_seen_at + timedelta(minutes=IDLE_MINUTES) <= t
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Your session has ended. Please sign in again"
        )
    a = await db.get(CustomerAccount, s.account_id)
    if a is None or a.disabled_at:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Please sign in")
    s.last_seen_at = t
    await db.commit()
    return a, s


Account = Annotated[tuple[CustomerAccount, PortalSession], Depends(current_account)]


async def my_case(case_id: int, acct: Account, db: DbSession) -> PostSalesCase:
    """The case, only if it belongs to the signed-in customer (otherwise 'not found', never 'forbidden')."""
    for c in await svc.cases_for(db, acct[0].email):
        if c.id == case_id:
            return c
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


MyCase = Annotated[PostSalesCase, Depends(my_case)]


@router.get("/status")
async def portal_status() -> dict:
    ok, why = enabled()
    return {"enabled": ok, "reason": why}


@router.post("/auth/request")
async def request_code(body: RequestIn, request: Request, db: DbSession) -> dict:
    """Always the same answer, so nobody can find out which emails are customers."""
    _require_enabled()
    if not await svc.cases_for(db, body.email):
        return {"message": GENERIC}
    recent = await db.scalar(
        select(func.count())
        .select_from(PortalCode)
        .where(
            PortalCode.email == body.email, PortalCode.created_at > now() - timedelta(minutes=15)
        )
    )
    if recent >= CODE_REQUESTS:
        log_audit(
            db,
            action="portal.code_limited",
            entity_type="customer_account",
            details={"email": body.email},
            request=request,
        )
        await db.commit()
        return {"message": GENERIC}
    code = f"{secrets.randbelow(10**6):06d}"
    db.add(
        PortalCode(
            email=body.email,
            code_hash=_hash(body.email, code),
            expires_at=now() + timedelta(minutes=CODE_MINUTES),
            ip=request.client.host if request.client else None,
        )
    )
    blocked = (
        comms.channel_ready("email") if comms.SENDERS.get("email") is comms._send_email else None
    )
    sent = False
    if not blocked:
        try:
            await asyncio.to_thread(
                comms.SENDERS["email"],
                body.email,
                "Your sign-in code",
                f"Your sign-in code for the customer portal is {code}.\n\nIt expires in {CODE_MINUTES} minutes. If you didn't ask for it, you can ignore this email.",
            )
            sent = True
        except Exception as exc:  # noqa: BLE001 - recorded for staff, never shown to the visitor
            blocked = f"{type(exc).__name__}: {exc}"[:300]
    log_audit(
        db,
        action="portal.code_sent" if sent else "portal.code_not_sent",
        entity_type="customer_account",
        details={"email": body.email, "reason": blocked},
        request=request,
    )
    await db.commit()
    return {"message": GENERIC}


@router.post("/auth/verify")
async def verify_code(body: VerifyIn, request: Request, response: Response, db: DbSession) -> dict:
    _require_enabled()
    bad = HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "That code isn't right or has expired. Please request a new one",
    )
    pc = await db.scalar(
        select(PortalCode)
        .where(PortalCode.email == body.email, PortalCode.used_at.is_(None))
        .order_by(PortalCode.id.desc())
    )
    if pc is None or pc.expires_at <= now() or pc.attempts >= CODE_TRIES:
        raise bad
    if not hmac.compare_digest(pc.code_hash, _hash(body.email, body.code)):
        pc.attempts += 1
        log_audit(
            db,
            action="portal.code_wrong",
            entity_type="customer_account",
            details={"email": body.email, "attempts": pc.attempts},
            request=request,
        )
        await db.commit()
        raise bad
    if not await svc.cases_for(db, body.email):
        raise bad
    pc.used_at = now()
    acct = await db.scalar(select(CustomerAccount).where(CustomerAccount.email == body.email))
    if acct is None:
        acct = CustomerAccount(email=body.email)
        db.add(acct)
        await db.flush()
    if acct.disabled_at:
        raise bad
    acct.last_login_at = now()
    token = secrets.token_urlsafe(32)
    db.add(
        PortalSession(
            id=hashlib.sha256(token.encode()).hexdigest(),
            account_id=acct.id,
            last_seen_at=now(),
            expires_at=now() + timedelta(hours=MAX_HOURS),
            user_agent=(request.headers.get("user-agent") or "")[:300],
            ip=request.client.host if request.client else None,
        )
    )
    log_audit(
        db,
        action="portal.signed_in",
        entity_type="customer_account",
        entity_id=acct.id,
        details={"email": body.email},
        request=request,
    )
    await db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=MAX_HOURS * 3600,
        httponly=True,
        secure=get_settings().secure_cookies,
        samesite="strict",
        path="/api/portal",
    )
    return {"ok": True}


@router.post("/auth/logout")
async def logout(
    response: Response, db: DbSession, portal_session: Annotated[str | None, Cookie()] = None
) -> dict:
    if portal_session:
        s = await db.get(PortalSession, hashlib.sha256(portal_session.encode()).hexdigest())
        if s and not s.revoked_at:
            s.revoked_at = now()
            await db.commit()
    response.delete_cookie(COOKIE, path="/api/portal")
    return {"ok": True}


@router.get("/me")
async def me(acct: Account, db: DbSession) -> dict:
    cs = await svc.cases_for(db, acct[0].email)
    out = []
    for c in cs:
        b = c.booking
        bld = await db.get(Building, b.unit.building_id) if b.unit.building_id else None
        out.append(
            {
                "case_id": c.id,
                "project": b.project.name,
                "tower": bld.name if bld else None,
                "unit": b.unit.unit_no,
                "status": "Cancelled" if c.status.value == "cancelled" else "Booked",
            }
        )
    p = (
        await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == cs[0].id))
        if cs
        else None
    )
    return {
        "email": acct[0].email,
        "name": (
            p.legal_name
            if p and p.legal_name
            else (cs[0].booking.customer_name or cs[0].booking.lead.name)
            if cs
            else None
        ),
        "units": out,
    }


@router.get("/sessions")
async def sessions(acct: Account, db: DbSession) -> list[dict]:
    rows = await db.scalars(
        select(PortalSession)
        .where(
            PortalSession.account_id == acct[0].id,
            PortalSession.revoked_at.is_(None),
            PortalSession.expires_at > now(),
        )
        .order_by(PortalSession.last_seen_at.desc())
    )
    return [
        {
            "started": s.created_at,
            "last_seen": s.last_seen_at,
            "device": s.user_agent,
            "this_device": s.id == acct[1].id,
        }
        for s in rows
    ]


@router.post("/sessions/sign-out-others")
async def sign_out_others(acct: Account, request: Request, db: DbSession) -> dict:
    n = 0
    for s in await db.scalars(
        select(PortalSession).where(
            PortalSession.account_id == acct[0].id,
            PortalSession.revoked_at.is_(None),
            PortalSession.id != acct[1].id,
        )
    ):
        s.revoked_at = now()
        n += 1
    log_audit(
        db,
        action="portal.signed_out_others",
        entity_type="customer_account",
        entity_id=acct[0].id,
        details={"sessions": n},
        request=request,
    )
    await db.commit()
    return {"signed_out": n}


async def _property(db, case: PostSalesCase) -> dict:
    b = case.booking
    u = b.unit
    bld = await db.get(Building, u.building_id) if u.building_id else None
    fl = await db.get(Floor, u.floor_id) if u.floor_id else None
    p = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case.id))
    co = list(await db.scalars(select(CoApplicant).where(CoApplicant.case_id == case.id)))
    from app.models.possession import PossessionFile

    pf = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case.id))
    return {
        "project": b.project.name,
        "tower": bld.name if bld else None,
        "floor": fl.number if fl else None,
        "unit": u.unit_no,
        "type": u.unit_type.value,
        "carpet_sqft": float(u.carpet_sqft) if u.carpet_sqft else None,
        "booking_date": b.booking_date,
        "booking_ref": f"BKG-{b.id:05d}",
        "case_ref": f"PSC-{case.id:05d}",
        "status": "Cancelled" if case.status.value == "cancelled" else "Booked",
        "owners": [
            {
                "name": (p.legal_name if p and p.legal_name else b.customer_name or b.lead.name),
                "share": float(p.ownership_pct) if p and p.ownership_pct else None,
            }
        ]
        + [
            {
                "name": c.name,
                "share": float(c.ownership_pct) if getattr(c, "ownership_pct", None) else None,
            }
            for c in co
        ],
        "parking": (pf.handover or {}).get("parking") if pf else None,
    }


@router.get("/cases/{case_id}/dashboard")
async def dashboard(case: MyCase, db: DbSession) -> dict:
    pay = await svc.payments_view(db, case)
    prop = await _property(db, case)
    actions = []
    if pay["next_due"]:
        actions.append(
            f"{pay['next_due']['status']}: Rs {comms.money(pay['next_due']['amount'])} for {pay['next_due']['stage']}"
            + (
                f", due {pay['next_due']['due_date']:%d %b %Y}"
                if pay["next_due"]["due_date"]
                else ""
            )
        )
    kyc = list(
        await db.scalars(
            select(KycDocument).where(
                KycDocument.case_id == case.id, KycDocument.status == "rejected"
            )
        )
    )
    if kyc:
        actions.append(
            "Some KYC documents need to be shared again: please contact your relationship executive"
        )
    ag = await svc.agreement_view(db, case)
    if ag["status"] == "Shared with you for review":
        actions.append("Your agreement draft is ready for your review")
    from app.models.appointment import Appointment, AppointmentStatus

    appt = await db.scalar(
        select(Appointment)
        .where(
            Appointment.case_id == case.id,
            Appointment.status == AppointmentStatus.scheduled,
            Appointment.starts_at > now(),
        )
        .order_by(Appointment.starts_at)
    )
    return {
        "property": prop,
        "payments": {
            k: pay.get(k)
            for k in (
                "headline",
                "total_paid",
                "total_consideration",
                "outstanding",
                "pending_reconciliation",
                "next_due",
                "next_milestone",
            )
        },
        "agreement": ag["status"],
        "next_appointment": {
            "what": ticket_svc.LABELS.get(appt.kind, None)
            or appt.kind.value.replace("_", " ").capitalize(),
            "when": appt.starts_at,
            "where": appt.location,
        }
        if appt
        else None,
        "pending_actions": actions,
    }


@router.get("/cases/{case_id}/property")
async def prop(case: MyCase, db: DbSession) -> dict:
    return await _property(db, case)


@router.get("/cases/{case_id}/payments")
async def pay(case: MyCase, db: DbSession) -> dict:
    return await svc.payments_view(db, case)


def _visible(d: CaseDocument) -> bool:
    return d.approval == Approval.released and d.visibility == Visibility.customer


@router.get("/cases/{case_id}/documents")
async def documents(case: MyCase, db: DbSession) -> list[dict]:
    rows = await db.scalars(
        select(CaseDocument)
        .where(
            CaseDocument.case_id == case.id,
            CaseDocument.approval == Approval.released,
            CaseDocument.visibility == Visibility.customer,
        )
        .order_by(CaseDocument.category, CaseDocument.id.desc())
    )
    return [
        {
            "id": d.id,
            "title": d.title,
            "type": d.doc_type,
            "category": doc_svc.LABELS.get(d.category, d.category.value),
            "date": d.doc_date,
            "released_at": d.released_at,
        }
        for d in rows
    ]


@router.get("/cases/{case_id}/documents/{did}/file")
async def document_file(
    did: int, case: MyCase, acct: Account, request: Request, db: DbSession
) -> FileResponse:
    """Signed-in, own case, released and customer-visible only; every download is logged."""
    d = await db.get(CaseDocument, did)
    if d is None or d.case_id != case.id or not _visible(d):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = files.receipt_file(d.file_path, "case_docs")  # same store the staff download uses
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file isn't available")
    log_audit(
        db,
        action="portal.document_downloaded",
        entity_type="case_document",
        entity_id=d.id,
        details={"email": acct[0].email, "case": case.id},
        request=request,
    )
    await db.commit()
    return FileResponse(
        path,
        media_type=d.file_type,
        headers={
            "Content-Disposition": f'attachment; filename="{d.file_name}"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/cases/{case_id}/agreement")
async def agreement(case: MyCase, db: DbSession) -> dict:
    return await svc.agreement_view(db, case)


@router.get("/cases/{case_id}/updates")
async def updates(case: MyCase, db: DbSession) -> list[dict]:
    rows = await db.scalars(
        select(ProjectUpdate)
        .where(
            ProjectUpdate.project_id == case.booking.project_id,
            ProjectUpdate.status == UpdateStatus.published,
        )
        .order_by(ProjectUpdate.published_at.desc())
    )
    return [
        {
            "id": u.id,
            "title": u.title,
            "body": u.body,
            "published_at": u.published_at,
            "corrected": bool(u.corrections),
            "photos": [
                {
                    "id": p.id,
                    "name": p.file_name,
                    "url": f"/api/portal/cases/{case.id}/updates/photos/{p.id}",
                }
                for p in u.photos
            ],
        }
        for u in rows
    ]


@router.get("/cases/{case_id}/updates/photos/{pid}")
async def update_photo(pid: int, case: MyCase, db: DbSession) -> FileResponse:
    p = await db.get(ProjectUpdatePhoto, pid)
    u = await db.get(ProjectUpdate, p.update_id) if p else None
    if (
        p is None
        or u is None
        or u.project_id != case.booking.project_id
        or u.status != UpdateStatus.published
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path = files.receipt_file(p.file_path, "project_updates")
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return FileResponse(
        path, media_type=p.file_type, headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get("/cases/{case_id}/notifications")
async def notifications(case: MyCase, db: DbSession) -> list[dict]:
    rows = await db.scalars(
        select(CommMessage)
        .where(CommMessage.case_id == case.id, CommMessage.status == "sent")
        .order_by(CommMessage.sent_at.desc())
        .limit(100)
    )
    return [
        {
            "what": comms.EVENTS.get(m.event, {}).get("label", m.event),
            "subject": m.subject,
            "body": m.body,
            "channel": m.channel,
            "at": m.sent_at,
        }
        for m in rows
    ]


class ChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: Literal[
        "mobile", "email", "correspondence_address", "contact_preferences", "name", "other"
    ]
    new_value: Annotated[PlainText, StringConstraints(min_length=2, max_length=500)]
    note: Annotated[PlainText, StringConstraints(max_length=1000)] | None = None


@router.get("/cases/{case_id}/profile")
async def profile(case: MyCase, db: DbSession) -> dict:
    p = await db.scalar(select(CustomerProfile).where(CustomerProfile.case_id == case.id))
    return {
        "name": p.legal_name,
        "email": p.email,
        "mobile": p.mobile,
        "correspondence_address": p.correspondence_address,
        "preferred_language": p.preferred_language,
        "contact": {"email": p.contact_email, "sms": p.contact_sms, "whatsapp": p.contact_whatsapp},
        "note": "To change any of these, send a change request; your relationship executive verifies it before it's updated.",
    }


@router.post("/cases/{case_id}/profile/change-request", status_code=status.HTTP_201_CREATED)
async def change_request(
    body: ChangeIn, case: MyCase, acct: Account, request: Request, db: DbSession
) -> dict:
    """A profile change is never applied directly: it becomes a request for the CRM team to verify."""
    cfg = await ticket_svc.get_settings(db)
    t = Ticket(
        case_id=case.id,
        category=TicketCategory.kyc,
        subcategory="Profile change request",
        title=f"Profile change: {body.field.replace('_', ' ')}",
        description=f"Requested change to {body.field.replace('_', ' ')}: {body.new_value}"
        + (f"\nNote: {body.note}" if body.note else ""),
        channel="portal",
        priority=Priority.normal,
        team=Team(cfg["categories"]["kyc"]["team"]),
        events=[],
    )
    ticket_svc.set_targets(t, ticket_svc.now(), cfg)
    db.add(t)
    await db.flush()
    t.events.append(
        TicketEvent(
            kind="raised",
            internal=False,
            text_=t.description,
            data={"channel": "portal", "by_customer": acct[0].email},
        )
    )
    log_audit(
        db,
        action="portal.change_requested",
        entity_type="ticket",
        entity_id=t.id,
        details={"email": acct[0].email, "field": body.field},
        request=request,
    )
    from app.services.notifications import notify

    for uid in (
        [case.owner_id]
        if case.owner_id
        else list(
            await db.scalars(
                select(User.id).where(User.is_active.is_(True), User.role == Role.crm_manager)
            )
        )
    ):
        notify(
            db,
            user_id=uid,
            type="portal_change_request",
            title=f"Portal change request: {case.booking.lead.name}",
            body=t.title,
            link=f"/service/{t.id}",
        )
    await db.commit()
    return {
        "request_no": f"TKT-{t.id:05d}",
        "message": "Thank you. Your relationship executive will verify the change and update your details.",
    }


@router.get("/cases/{case_id}/help")
async def help_centre(case: MyCase, db: DbSession) -> dict:
    owner = await db.get(User, case.owner_id) if case.owner_id else None
    managers = list(
        await db.scalars(
            select(User)
            .where(User.is_active.is_(True), User.role == Role.crm_manager)
            .order_by(User.full_name)
            .limit(3)
        )
    )
    fm = await db.get(FacilityHandover, case.booking.project_id)
    return {
        "relationship_executive": {"name": owner.full_name, "email": owner.email}
        if owner
        else None,
        "escalation": [{"name": m.full_name, "email": m.email} for m in managers],
        "escalation_note": "If a request isn't resolved within its promised time, or you're unhappy with a response, write to the CRM manager listed here.",
        "maintenance_contacts": (fm.data or {}).get("maintenance_contacts") if fm else None,
        "faqs": [
            {
                "q": "How do I pay?",
                "a": "Use the bank details on your demand letter, then tell your relationship executive the payment reference so we can confirm it quickly.",
            },
            {
                "q": "When will my receipt appear?",
                "a": "As soon as our finance team confirms the payment with the bank. Until then it shows as 'Payment received - reconciliation pending'.",
            },
            {
                "q": "How do I get a copy of a document?",
                "a": "Released documents are under My Documents. If something is missing, raise a request.",
            },
            {
                "q": "How do I change my contact details?",
                "a": "Go to My Profile and send a change request; we verify it before updating.",
            },
        ],
    }
