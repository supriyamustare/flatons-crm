from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.case_document import CaseDocument, DocCategory
from app.models.possession import Inspection, PossessionFile, Snag, SnagEvidence
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.project import Project
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import possession as svc
from app.services import postsales as cases
from app.services import receipts as files
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales/cases/{case_id}/possession", tags=["possession"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
STARTERS = (Role.admin, Role.crm_manager, Role.postsales_exec)
DOC_KEEPERS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.legal)
INSPECTORS = (Role.admin, Role.project_manager, Role.site, Role.after_sales)
READINESS_APPROVERS = (Role.admin, Role.project_manager)  # the authorised project representative
EXCEPTION_APPROVERS = (Role.admin, Role.crm_manager)
Note = Annotated[PlainText, StringConstraints(max_length=1000)]


class StartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Note | None = None


class FinanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    charges_note: Note | None = None  # authorised charges added (or "none")
    adjustments_note: Note | None = None  # credits, waivers, adjustments applied
    taxes_confirmed: bool = False
    payment_confirmed: bool = False


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=1000)]


class ClearIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Note | None = None


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: Annotated[PlainText, StringConstraints(min_length=1, max_length=200)]
    status: Literal["pending", "available", "not_applicable", "ok", "issue"]
    note: Note | None = None
    document_id: int | None = None


class ReadinessIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: Annotated[list[ItemIn], Field(max_length=60)] = []
    meters: dict[str, Annotated[PlainText, StringConstraints(max_length=60)]] = {}


class SnagIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Annotated[PlainText, StringConstraints(min_length=3, max_length=2000)]
    location: Annotated[PlainText, StringConstraints(max_length=120)] | None = None
    owner_id: int
    due_on: date
    category: Literal["civil", "electrical", "plumbing", "finishing", "fittings", "other"] = "other"
    severity: Literal["minor", "major", "critical"] = "minor"
    source: Literal["internal", "customer"] = "internal"
    inspection_id: int | None = None


class SnagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["fixed", "verified", "reopen"]
    note: Note | None = None  # rectification details when fixed; the reason when reopened


class CustomerResponseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: Literal["accepted", "disputed"]
    note: Note | None = None


class InspectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    appointment_id: int | None = None
    conducted_on: date | None = None
    attendees: Annotated[PlainText, StringConstraints(max_length=500)] | None = None
    notes: Annotated[PlainText, StringConstraints(max_length=5000)] | None = None
    report_shared_on: date | None = None
    report_shared_via: Literal["email", "whatsapp", "hand", "portal", "other"] | None = None


class HandoverIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: dict[
        str, bool | int | Annotated[PlainText, StringConstraints(max_length=500)] | None
    ] = {}


class CompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual_possession_on: date


class ExceptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=10, max_length=1000)]
    scope: Annotated[
        list[
            Literal[
                "legal",
                "documents",
                "finance",
                "readiness",
                "internal",
                "communication",
                "inspection",
            ]
        ],
        Field(min_length=1),
    ]


def now() -> datetime:
    return datetime.now(UTC)


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _file(db: DbSession, case_id: int) -> PossessionFile:
    f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case_id))
    if f is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Start the pre-possession file first"
        )
    return f


def _who(role_ok: bool, msg: str) -> None:
    if not role_ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)


async def state(db: DbSession, case: PostSalesCase, user: User) -> dict:
    project = await db.get(Project, case.booking.project_id)
    rules = svc.project_rules(project)
    trigger, reached = await svc.trigger_reached(db, project)
    f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case.id))
    out: dict = {
        "trigger": trigger,
        "trigger_reached": reached,
        "file": None,
        "can_start": f is None and user.role in STARTERS and case.status == CaseStatus.accepted,
    }
    if f is None:
        return out
    ids = {
        x
        for x in (
            f.clearance_requested_by_id,
            f.cleared_by_id,
            f.readiness_approved_by_id,
            f.internal_approved_by_id,
        )
        if x
    }
    snags = list(await db.scalars(select(Snag).where(Snag.file_id == f.id).order_by(Snag.id)))
    snag_files: dict = {}
    if snags:
        for e in await db.scalars(
            select(SnagEvidence)
            .where(SnagEvidence.snag_id.in_([x.id for x in snags]))
            .order_by(SnagEvidence.id)
        ):
            snag_files.setdefault(e.snag_id, []).append(e)
    ids |= {s.owner_id for s in snags if s.owner_id}
    users = (
        {u.id: u.full_name for u in await db.scalars(select(User).where(User.id.in_(ids)))}
        if ids
        else {}
    )
    fin = await svc.financial(db, case)
    g = await svc.gate(db, case, f, project, rules)
    docs = {
        d.id: f"{d.title} (DOC-{d.id:05d})"
        for d in await db.scalars(select(CaseDocument).where(CaseDocument.case_id == case.id))
    }
    open_snags = sum(1 for s in snags if s.status != "closed")
    pending_items = [i for i in rules["readiness"] if f.readiness.get(i, {}).get("status") != "ok"]
    evidence = await svc.evidence_count(db, case)
    r = user.role
    out["file"] = {
        "started_at": f.created_at,
        "start_reason": f.start_reason,
        "financial": fin,
        "finance": f.finance or {},
        "clearance": {
            "requested_by": users.get(f.clearance_requested_by_id),
            "requested_at": f.clearance_requested_at,
            "snapshot": f.clearance_snapshot,
            "cleared_by": users.get(f.cleared_by_id),
            "cleared_at": f.cleared_at,
            "note": f.clearance_note,
            "returned_reason": f.clearance_returned_reason,
        },
        "documents": [
            {
                "item": d,
                **(f.documents.get(d) or {"status": "pending"}),
                "document": docs.get((f.documents.get(d) or {}).get("document_id")),
            }
            for d in rules["documents"]
        ],
        "readiness": [
            {"item": i, **(f.readiness.get(i) or {"status": "pending"})} for i in rules["readiness"]
        ],
        "meters": f.meters or {},
        "snags": [
            {
                "id": s.id,
                "description": s.description,
                "location": s.location,
                "owner": users.get(s.owner_id),
                "due_on": s.due_on,
                "status": s.status,
                "note": s.note,
                "category": s.category,
                "severity": s.severity,
                "source": s.source,
                "inspection_id": s.inspection_id,
                "rectification": s.rectification,
                "fixed_at": s.fixed_at,
                "verified_at": s.verified_at,
                "customer_response": s.customer_response,
                "customer_note": s.customer_note,
                "reopen_reason": s.reopen_reason,
                "reopened_count": s.reopened_count,
                "closed_at": s.closed_at,
                "reported_on": s.created_at,
                "evidence": [
                    {
                        "id": e.id,
                        "kind": e.kind,
                        "file_name": e.file_name,
                        "url": f"/api/post-sales/possession/snag-evidence/{e.id}",
                    }
                    for e in snag_files.get(s.id, [])
                ],
                "overdue": s.status in ("open", "fixed")
                and s.due_on is not None
                and s.due_on < svc.today(),
            }
            for s in snags
        ],
        "evidence_count": evidence,
        "readiness_approved_by": users.get(f.readiness_approved_by_id),
        "readiness_approved_at": f.readiness_approved_at,
        "readiness_blockers": [
            *(["Items not OK: " + ", ".join(pending_items)] if pending_items else []),
            *([f"{open_snags} snag(s) not verified"] if open_snags else []),
            *(["No inspection evidence in 09 Possession & Handover"] if not evidence else []),
        ],
        "internal_approved_by": users.get(f.internal_approved_by_id),
        "internal_approved_at": f.internal_approved_at,
        "exception": f.exception,
        "gate": g,
        "inspections": [
            {
                "id": i.id,
                "conducted_on": i.conducted_on,
                "attendees": i.attendees,
                "notes": i.notes,
                "report_shared_on": i.report_shared_on,
                "report_shared_via": i.report_shared_via,
                "appointment_id": i.appointment_id,
            }
            for i in await db.scalars(
                select(Inspection).where(Inspection.file_id == f.id).order_by(Inspection.id)
            )
        ],
        "handover": f.handover or {},
        "handover_completed_at": f.handover_completed_at,
        "actual_possession_on": f.actual_possession_on,
        "possession_status": await svc.possession_status(db, case, f, g),
        "dates": await svc.key_dates(db, case, f, project),
        "possession_documents": [
            {"id": d.id, "title": d.title}
            for d in await db.scalars(
                select(CaseDocument).where(
                    CaseDocument.case_id == case.id, CaseDocument.category == DocCategory.possession
                )
            )
        ],
        "can": {
            "finance": r in (Role.admin, Role.finance),
            "request_clearance": r in (Role.admin, Role.finance)
            and not f.cleared_at
            and not f.clearance_requested_at,
            "clear": r in (Role.admin, Role.finance_approver)
            and bool(f.clearance_requested_at)
            and not f.cleared_at
            and f.clearance_requested_by_id != user.id,
            "documents": r in DOC_KEEPERS,
            "inspect": r in INSPECTORS,
            "approve_readiness": r in READINESS_APPROVERS and not f.readiness_approved_at,
            "internal": r in (Role.admin, Role.crm_manager) and not f.internal_approved_at,
            "exception": r in EXCEPTION_APPROVERS and not g["open"],
        },
        "owners": [
            UserBrief.model_validate(u).model_dump()
            for u in await db.scalars(
                select(User)
                .where(User.is_active.is_(True), User.role.in_(list(INSPECTORS)))
                .order_by(User.full_name)
            )
        ],
    }
    return out


def _log(
    db: DbSession,
    case: PostSalesCase,
    user: User,
    action: str,
    request: Request,
    details: dict | None = None,
) -> None:
    cases.event(db, case, action, user, details or {})
    log_audit(
        db,
        action=action.replace("possession_", "possession."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


async def _done(db: DbSession, case: PostSalesCase, user: User) -> dict:
    await db.flush()
    f = await db.scalar(select(PossessionFile).where(PossessionFile.case_id == case.id))
    if f is not None and f.gate_opened_at is None:
        project = await db.get(Project, case.booking.project_id)
        if (await svc.gate(db, case, f, project, svc.project_rules(project)))["open"]:
            f.gate_opened_at = now()  # legal eligibility for possession
    await db.commit()
    return await state(db, case, user)


@router.get("")
async def get_state(case_id: int, user: Viewer, db: DbSession) -> dict:
    return await state(db, await _case(db, case_id), user)


@router.post("/start", status_code=status.HTTP_201_CREATED)
async def start(case_id: int, body: StartIn, request: Request, user: Viewer, db: DbSession) -> dict:
    """Opens the file once the project's possession milestone is verified; an admin can start earlier with a reason."""
    _who(user.role in STARTERS, "Post-sales, CRM managers or admins start the pre-possession file")
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Accept the handover first")
    if await db.scalar(select(PossessionFile.id).where(PossessionFile.case_id == case_id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The pre-possession file is already open")
    trigger, reached = await svc.trigger_reached(db, await db.get(Project, case.booking.project_id))
    reason = (body.reason or "").strip() or None
    if not reached:
        if user.role != Role.admin:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"Pre-possession starts once the {trigger or 'possession'} milestone is verified",
            )
        if not reason or len(reason) < 10:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"The {trigger} milestone isn't verified yet: give the reason for starting early",
            )
    db.add(
        PossessionFile(
            case_id=case.id,
            started_by_id=user.id,
            start_reason=reason if not reached else None,
            finance={},
            documents={},
            readiness={},
            meters={},
        )
    )
    _log(
        db,
        case,
        user,
        "possession_started",
        request,
        {"early": not reached, "reason": reason} if not reached else {},
    )
    return await _done(db, case, user)


@router.put("/finance")
async def put_finance(
    case_id: int, body: FinanceIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in (Role.admin, Role.finance), "Finance confirms these items")
    case, f = await _case(db, case_id), await _file(db, case_id)
    if f.cleared_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Finance clearance is already given"
        )
    f.finance = {**body.model_dump(), "by": user.full_name, "at": now().isoformat()}
    _log(db, case, user, "possession_finance_updated", request, body.model_dump())
    return await _done(db, case, user)


@router.post("/finance/request-clearance")
async def request_clearance(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    """Maker: freezes today's figures for the checker."""
    _who(user.role in (Role.admin, Role.finance), "Finance requests clearance")
    case, f = await _case(db, case_id), await _file(db, case_id)
    fin = await svc.financial(db, case)
    problems = []
    if not fin.get("has_ledger") or not fin.get("ledger_approved"):
        problems.append("the ledger must be approved")
    else:
        if fin["unconfirmed_receipts"]:
            problems.append(
                f"{fin['unconfirmed_receipts']} receipt(s) still waiting for confirmation"
            )
        if fin["open_disputes"]:
            problems.append("open payment disputes: " + ", ".join(fin["open_disputes"]))
    conf = f.finance or {}
    if not (conf.get("taxes_confirmed") and conf.get("payment_confirmed")):
        problems.append("confirm taxes/deposits/statutory amounts and the payment confirmation")
    if problems:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Before requesting clearance: " + "; ".join(problems),
        )
    (
        f.clearance_requested_by_id,
        f.clearance_requested_at,
        f.clearance_snapshot,
        f.clearance_returned_reason,
    ) = user.id, now(), fin, None
    _log(
        db,
        case,
        user,
        "possession_clearance_requested",
        request,
        {"outstanding": fin["outstanding"]},
    )
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.finance_approver, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="possession_clearance",
            title=f"Finance clearance to give: {case.booking.lead.name}",
            body=f"Outstanding Rs {fin['outstanding']:,}",
            link=f"/post-sales/{case.id}?tab=possession",
        )
    return await _done(db, case, user)


@router.post("/finance/clear")
async def clear(case_id: int, body: ClearIn, request: Request, user: Viewer, db: DbSession) -> dict:
    """Checker: someone other than the requester. Clearing with money outstanding needs a note (e.g. payable at possession)."""
    _who(user.role in (Role.admin, Role.finance_approver), "A finance approver gives clearance")
    case, f = await _case(db, case_id), await _file(db, case_id)
    if not f.clearance_requested_at or f.cleared_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing is waiting for clearance"
        )
    if f.clearance_requested_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who requested clearance can't give it"
        )
    outstanding = (f.clearance_snapshot or {}).get("outstanding", 0)
    note = (body.note or "").strip() or None
    if outstanding > 0 and (not note or len(note) < 10):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Rs {outstanding:,} is still outstanding: explain why clearance is given (e.g. payable at possession under the agreement)",
        )
    f.cleared_by_id, f.cleared_at, f.clearance_note = user.id, now(), note
    _log(db, case, user, "possession_cleared", request, {"outstanding": outstanding, "note": note})
    return await _done(db, case, user)


@router.post("/finance/return")
async def return_clearance(
    case_id: int, body: ReasonIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in (Role.admin, Role.finance_approver), "A finance approver returns the request")
    case, f = await _case(db, case_id), await _file(db, case_id)
    if not f.clearance_requested_at or f.cleared_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing is waiting for clearance"
        )
    f.clearance_requested_by_id = f.clearance_requested_at = f.clearance_snapshot = None
    f.clearance_returned_reason = body.reason
    _log(db, case, user, "possession_clearance_returned", request, {"reason": body.reason})
    return await _done(db, case, user)


@router.put("/documents")
async def put_documents(
    case_id: int, body: ReadinessIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in DOC_KEEPERS, "Post-sales, CRM, legal or admin keep the document checklist")
    case, f = await _case(db, case_id), await _file(db, case_id)
    allowed = svc.project_rules(await db.get(Project, case.booking.project_id))["documents"]
    docs = dict(f.documents or {})
    for it in body.items:
        if it.item not in allowed or it.status not in ("pending", "available", "not_applicable"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{it.item}: not a document on this project's checklist, or a wrong status",
            )
        if it.status == "not_applicable" and not (it.note or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"{it.item}: say why it doesn't apply"
            )
        if it.document_id is not None:
            d = await db.get(CaseDocument, it.document_id)
            if d is None or d.case_id != case.id:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"{it.item}: link a document from this customer's folder",
                )
        docs[it.item] = {
            "status": it.status,
            "note": (it.note or "").strip() or None,
            "document_id": it.document_id,
            "by": user.full_name,
            "at": now().isoformat(),
        }
    f.documents = docs
    _log(
        db,
        case,
        user,
        "possession_documents_updated",
        request,
        {"items": [i.item for i in body.items]},
    )
    return await _done(db, case, user)


@router.put("/readiness")
async def put_readiness(
    case_id: int, body: ReadinessIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in INSPECTORS, "The site, project or after-sales team inspects the unit")
    case, f = await _case(db, case_id), await _file(db, case_id)
    if f.readiness_approved_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Readiness is already approved")
    allowed = svc.project_rules(await db.get(Project, case.booking.project_id))["readiness"]
    ready = dict(f.readiness or {})
    for it in body.items:
        if it.item not in allowed or it.status not in ("pending", "ok", "issue"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{it.item}: not on this project's readiness checklist, or a wrong status",
            )
        if it.status == "issue" and not (it.note or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"{it.item}: describe the issue (and raise a snag)",
            )
        ready[it.item] = {
            "status": it.status,
            "note": (it.note or "").strip() or None,
            "by": user.full_name,
            "at": now().isoformat(),
        }
    f.readiness = ready
    if body.meters:
        f.meters = {**(f.meters or {}), **{k: v for k, v in body.meters.items() if v}}
    _log(
        db,
        case,
        user,
        "possession_inspection_updated",
        request,
        {"items": [i.item for i in body.items]},
    )
    return await _done(db, case, user)


@router.post("/snags", status_code=status.HTTP_201_CREATED)
async def add_snag(
    case_id: int, body: SnagIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(
        user.role in INSPECTORS or (body.source == "customer" and user.role in STARTERS),
        "The site, project or after-sales team records snags",
    )
    case, f = await _case(db, case_id), await _file(db, case_id)
    owner = await db.get(User, body.owner_id)
    if owner is None or not owner.is_active or owner.role not in INSPECTORS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Choose a site, project or after-sales person to fix it",
        )
    if body.due_on < svc.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The due date can't be in the past"
        )
    if body.inspection_id is not None:
        ins = await db.get(Inspection, body.inspection_id)
        if ins is None or ins.file_id != f.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That inspection isn't on this case"
            )
    db.add(
        Snag(
            file_id=f.id,
            description=body.description,
            location=body.location,
            owner_id=owner.id,
            due_on=body.due_on,
            raised_by_id=user.id,
            category=body.category,
            severity=body.severity,
            source=body.source,
            inspection_id=body.inspection_id,
        )
    )
    if f.readiness_approved_at:  # a new snag withdraws an earlier readiness approval
        f.readiness_approved_at = f.readiness_approved_by_id = None
    _log(
        db,
        case,
        user,
        "possession_snag_raised",
        request,
        {
            "snag": body.description[:80],
            "owner": owner.full_name,
            "due": body.due_on.isoformat(),
            "severity": body.severity,
        },
    )
    if owner.id != user.id:
        notify(
            db,
            user_id=owner.id,
            type="snag_assigned",
            title=f"{body.severity.capitalize()} snag to fix by {body.due_on:%d %b}: {case.booking.lead.name}",
            body=body.description[:200],
            link=f"/post-sales/{case.id}?tab=possession",
        )
    return await _done(db, case, user)


@router.post("/snags/{sid}")
async def update_snag(
    case_id: int, sid: int, body: SnagUpdate, request: Request, user: Viewer, db: DbSession
) -> dict:
    """Fixed (with rectification details; major/critical need completion evidence) -> verified by someone else
    -> closed (internal snags), or waiting for the customer's acceptance (customer snags). Reopen keeps the reason."""
    _who(user.role in INSPECTORS, "The site, project or after-sales team updates snags")
    case, f = await _case(db, case_id), await _file(db, case_id)
    s = await db.get(Snag, sid)
    if s is None or s.file_id != f.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snag not found")
    note = (body.note or "").strip() or None
    if body.status == "fixed":
        if s.status != "open":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Only an open snag can be marked fixed"
            )
        if not note:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Describe the rectification")
        if s.severity in ("major", "critical") and not await db.scalar(
            select(SnagEvidence.id).where(
                SnagEvidence.snag_id == s.id, SnagEvidence.kind == "completion"
            )
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"A {s.severity} snag needs completion evidence (a photo) before it's marked fixed",
            )
        s.status, s.rectification, s.fixed_by_id, s.fixed_at = "fixed", note, user.id, now()
    elif body.status == "verified":
        if s.status != "fixed" or s.fixed_by_id == user.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A snag is verified after it's fixed, by someone other than the person who fixed it",
            )
        s.verified_by_id, s.verified_at = user.id, now()
        if s.source == "customer":
            s.status = "verified"  # closes when the customer accepts
        else:
            s.status, s.closed_at = "closed", now()
    else:
        if s.status == "open":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The snag is already open")
        if not note:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Give the reason for reopening"
            )
        (
            s.status,
            s.reopen_reason,
            s.reopened_count,
            s.closed_at,
            s.verified_at,
            s.verified_by_id,
        ) = "open", note, s.reopened_count + 1, None, None, None
        if f.readiness_approved_at:
            f.readiness_approved_at = f.readiness_approved_by_id = None
    _log(
        db,
        case,
        user,
        "possession_snag_updated",
        request,
        {"snag": s.description[:80], "status": s.status, "note": note},
    )
    return await _done(db, case, user)


@router.post("/snags/{sid}/customer")
async def customer_response(
    case_id: int, sid: int, body: CustomerResponseIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """The customer accepts the repair (the snag closes) or disputes it (it reopens with the customer's reason)."""
    _who(
        user.role in (*STARTERS, *INSPECTORS),
        "Post-sales or the site team records the customer's response",
    )
    case, f = await _case(db, case_id), await _file(db, case_id)
    s = await db.get(Snag, sid)
    if s is None or s.file_id != f.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snag not found")
    if s.status != "verified":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The customer responds once the repair is verified",
        )
    note = (body.note or "").strip() or None
    s.customer_response, s.customer_note = body.response, note
    if body.response == "accepted":
        s.status, s.closed_at = "closed", now()
    else:
        if not note:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Record what the customer disputes"
            )
        s.status, s.reopen_reason, s.reopened_count, s.verified_at, s.verified_by_id = (
            "open",
            f"Customer dispute: {note}",
            s.reopened_count + 1,
            None,
            None,
        )
    _log(
        db,
        case,
        user,
        "possession_snag_customer",
        request,
        {"snag": s.description[:80], "response": body.response, "note": note},
    )
    return await _done(db, case, user)


@router.post("/snags/{sid}/evidence")
async def snag_evidence(
    case_id: int,
    sid: int,
    request: Request,
    user: Viewer,
    db: DbSession,
    file: Annotated[UploadFile, File()],
    kind: Annotated[Literal["issue", "completion"], Form()] = "issue",
) -> dict:
    _who(user.role in (*STARTERS, *INSPECTORS), "Post-sales or the site team adds snag photos")
    case, f = await _case(db, case_id), await _file(db, case_id)
    s = await db.get(Snag, sid)
    if s is None or s.file_id != f.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snag not found")
    try:
        path, name, mime = await files.save_receipt(file, folder="snags", max_mb=15, what="Photos")
    except files.ReceiptError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    db.add(
        SnagEvidence(
            snag_id=s.id,
            kind=kind,
            file_path=path,
            file_name=name,
            file_type=mime,
            uploaded_by_id=user.id,
        )
    )
    _log(
        db,
        case,
        user,
        "possession_snag_evidence",
        request,
        {"snag": s.description[:80], "kind": kind},
    )
    return await _done(db, case, user)


@router.post("/readiness/approve")
async def approve_readiness(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    _who(
        user.role in READINESS_APPROVERS,
        "A project manager (the authorised project representative) approves readiness",
    )
    case, f = await _case(db, case_id), await _file(db, case_id)
    st = (await state(db, case, user))["file"]
    if st["readiness_blockers"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Not ready: " + "; ".join(st["readiness_blockers"]),
        )
    f.readiness_approved_by_id, f.readiness_approved_at = user.id, now()
    _log(db, case, user, "possession_readiness_approved", request)
    return await _done(db, case, user)


@router.post("/internal-approval")
async def internal_approval(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    _who(user.role in (Role.admin, Role.crm_manager), "A CRM manager gives the internal approval")
    case, f = await _case(db, case_id), await _file(db, case_id)
    f.internal_approved_by_id, f.internal_approved_at = user.id, now()
    _log(db, case, user, "possession_internal_approved", request)
    return await _done(db, case, user)


@router.post("/exception")
async def record_exception(
    case_id: int, body: ExceptionIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """An authorised exception to the gate: approver, reason, date and scope (which conditions) are recorded."""
    _who(user.role in EXCEPTION_APPROVERS, "Only a CRM manager or admin can approve an exception")
    case, f = await _case(db, case_id), await _file(db, case_id)
    f.exception = {
        "by": user.id,
        "by_name": user.full_name,
        "at": now().isoformat(),
        "reason": body.reason,
        "scope": list(dict.fromkeys(body.scope)),
    }
    _log(
        db,
        case,
        user,
        "possession_exception",
        request,
        {"reason": body.reason, "scope": body.scope},
    )
    return await _done(db, case, user)


@router.post("/inspections", status_code=status.HTTP_201_CREATED)
async def add_inspection(
    case_id: int, body: InspectionIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """A customer inspection (usually linked to an Inspection appointment)."""
    _who(user.role in (*STARTERS, *INSPECTORS), "Post-sales or the site team records inspections")
    case, f = await _case(db, case_id), await _file(db, case_id)
    await _check_inspection(db, case, body)
    db.add(Inspection(file_id=f.id, created_by_id=user.id, **body.model_dump()))
    _log(
        db,
        case,
        user,
        "possession_inspection",
        request,
        {"conducted_on": body.conducted_on.isoformat() if body.conducted_on else None},
    )
    return await _done(db, case, user)


@router.put("/inspections/{iid}")
async def update_inspection(
    case_id: int, iid: int, body: InspectionIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in (*STARTERS, *INSPECTORS), "Post-sales or the site team records inspections")
    case, f = await _case(db, case_id), await _file(db, case_id)
    ins = await db.get(Inspection, iid)
    if ins is None or ins.file_id != f.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inspection not found")
    await _check_inspection(db, case, body)
    for k, v in body.model_dump().items():
        if v is not None:
            setattr(ins, k, v)
    _log(
        db,
        case,
        user,
        "possession_inspection",
        request,
        {
            "conducted_on": ins.conducted_on.isoformat() if ins.conducted_on else None,
            "report_shared": ins.report_shared_via,
        },
    )
    return await _done(db, case, user)


async def _check_inspection(db: DbSession, case: PostSalesCase, body: InspectionIn) -> None:
    t = svc.today()
    for d in (body.conducted_on, body.report_shared_on):
        if d and d > t:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Dates can't be in the future"
            )
    if body.report_shared_on and not body.report_shared_via:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say how the report was shared")
    if body.appointment_id is not None:
        from app.models.appointment import Appointment

        a = await db.get(Appointment, body.appointment_id)
        if a is None or a.case_id != case.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "That appointment isn't on this case"
            )


HANDOVER_REQUIRED = (
    "identity_verified",
    "customer_acknowledged",
    "keys_count",
    "signed_checklist_document_id",
)


@router.put("/handover")
async def put_handover(
    case_id: int, body: HandoverIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """The handover checklist: keys, access cards, remotes, parking, meters, utilities, contacts, manuals, rules,
    identity and authorisation, the customer's acknowledgement, the signed checklist and photos."""
    _who(
        user.role in (*STARTERS, Role.site, Role.after_sales),
        "Post-sales, CRM or the site team record the handover",
    )
    case, f = await _case(db, case_id), await _file(db, case_id)
    if f.handover_completed_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The handover is already completed"
        )
    doc_id = body.items.get("signed_checklist_document_id")
    if doc_id is not None:
        d = await db.get(CaseDocument, int(doc_id))
        if d is None or d.case_id != case.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Link the signed checklist from this customer's folder",
            )
    f.handover = {**(f.handover or {}), **body.items}
    _log(db, case, user, "possession_handover_updated", request, {"items": sorted(body.items)})
    return await _done(db, case, user)


@router.post("/handover/complete")
async def complete_handover(
    case_id: int, body: CompleteIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(
        user.role in (Role.admin, Role.crm_manager, Role.postsales_exec),
        "Post-sales or a CRM manager completes the handover",
    )
    case, f = await _case(db, case_id), await _file(db, case_id)
    if f.handover_completed_at:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The handover is already completed"
        )
    project = await db.get(Project, case.booking.project_id)
    g = await svc.gate(db, case, f, project, svc.project_rules(project))
    if not g["open"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The possession gate isn't open")
    from app.models.appointment import Appointment, AppointmentKind, AppointmentStatus

    if not await db.scalar(
        select(Appointment.id).where(
            Appointment.case_id == case.id,
            Appointment.kind == AppointmentKind.possession,
            Appointment.status.in_([AppointmentStatus.scheduled, AppointmentStatus.attended]),
        )
    ):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Schedule the possession handover appointment first",
        )
    h = f.handover or {}
    missing = [k for k in HANDOVER_REQUIRED if not h.get(k)]
    if missing:
        names = {
            "identity_verified": "customer identity verified",
            "customer_acknowledged": "customer's acknowledgement",
            "keys_count": "keys handed over",
            "signed_checklist_document_id": "signed handover checklist (from the folder)",
        }
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Before completing: " + ", ".join(names[k] for k in missing),
        )
    if body.actual_possession_on > svc.today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The possession date can't be in the future"
        )
    f.handover_completed_at, f.handover_by_id, f.actual_possession_on = (
        now(),
        user.id,
        body.actual_possession_on,
    )
    _log(
        db,
        case,
        user,
        "possession_handover_completed",
        request,
        {"actual_possession_on": body.actual_possession_on.isoformat()},
    )
    return await _done(db, case, user)


evidence_router = APIRouter(prefix="/post-sales/possession", tags=["possession"])


@evidence_router.get("/snag-evidence/{eid}")
async def evidence_file(eid: int, _: Viewer, db: DbSession):
    from fastapi.responses import FileResponse

    e = await db.get(SnagEvidence, eid)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    path = files.receipt_file(e.file_path, "snags")
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing")
    return FileResponse(
        path,
        media_type=e.file_type,
        headers={"Content-Disposition": f'inline; filename="{e.file_name}"'},
    )
