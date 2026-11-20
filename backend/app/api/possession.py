from datetime import UTC, date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.case_document import CaseDocument
from app.models.possession import PossessionFile, Snag
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.project import Project
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import possession as svc
from app.services import postsales as cases
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


class SnagUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "fixed", "verified"]
    note: Note | None = None


class ExceptionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=10, max_length=1000)]
    scope: Annotated[
        list[Literal["legal", "documents", "finance", "readiness", "internal", "communication"]],
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
    open_snags = sum(1 for s in snags if s.status != "verified")
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
                "overdue": s.status == "open" and s.due_on is not None and s.due_on < svc.today(),
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
    _who(user.role in INSPECTORS, "The site, project or after-sales team records snags")
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
    db.add(
        Snag(
            file_id=f.id,
            description=body.description,
            location=body.location,
            owner_id=owner.id,
            due_on=body.due_on,
            raised_by_id=user.id,
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
        {"snag": body.description[:80], "owner": owner.full_name, "due": body.due_on.isoformat()},
    )
    if owner.id != user.id:
        notify(
            db,
            user_id=owner.id,
            type="snag_assigned",
            title=f"Snag to fix by {body.due_on:%d %b}: {case.booking.lead.name}",
            body=body.description[:200],
            link=f"/post-sales/{case.id}?tab=possession",
        )
    return await _done(db, case, user)


@router.post("/snags/{sid}")
async def update_snag(
    case_id: int, sid: int, body: SnagUpdate, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in INSPECTORS, "The site, project or after-sales team updates snags")
    case, f = await _case(db, case_id), await _file(db, case_id)
    s = await db.get(Snag, sid)
    if s is None or s.file_id != f.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Snag not found")
    if body.status == "verified" and (s.status != "fixed" or s.owner_id == user.id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A snag is verified after it's fixed, by someone other than the person who fixed it",
        )
    s.status, s.note = body.status, (body.note or "").strip() or s.note
    s.closed_at = now() if body.status == "verified" else None
    _log(
        db,
        case,
        user,
        "possession_snag_updated",
        request,
        {"snag": s.description[:80], "status": body.status},
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
