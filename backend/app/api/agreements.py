from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.agreement import Agreement, AgreementStatus
from app.models.case_document import Approval, CaseDocument, DocCategory
from app.models.ledger import ChargeHead, Ledger
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import agreements as svc
from app.services import postsales as cases
from app.services import receipts as files
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales/cases/{case_id}/agreement", tags=["agreement"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
WORKERS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.legal)  # run the workflow
DRAFTERS = (Role.admin, Role.crm_manager, Role.legal)
Worker = Annotated[User, Depends(require_role(*WORKERS))]
Drafter = Annotated[User, Depends(require_role(*DRAFTERS))]
Reviewer = Annotated[User, Depends(require_role(Role.admin, Role.legal, Role.finance_approver))]
IST = timezone(timedelta(hours=5, minutes=30))
S = AgreementStatus


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=1000)]


class ShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["email", "hand", "courier", "whatsapp", "portal", "other"]
    shared_on: date | None = None


class ExecutionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stamp_duty_amount: Annotated[int, Field(ge=0, le=100_000_000)] | None = None
    stamp_duty_paid_on: date | None = None
    stamp_duty_ref: Annotated[PlainText, StringConstraints(max_length=80)] | None = None
    registration_fee_amount: Annotated[int, Field(ge=0, le=10_000_000)] | None = None
    registration_fee_paid_on: date | None = None
    registration_fee_ref: Annotated[PlainText, StringConstraints(max_length=80)] | None = None
    appointment_at: datetime | None = None
    sro_office: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    id_docs_ready: bool = False
    signing_note: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executed_on: date
    registration_no: Annotated[PlainText, StringConstraints(min_length=3, max_length=80)]
    registered_on: date
    sro_office: Annotated[PlainText, StringConstraints(max_length=150)] | None = None


class AgreementOut(BaseModel):
    id: int
    agreement_no: str
    status: str  # stored status, or "completed" once the final document is released to the customer
    version: int
    draft: dict | None
    legal_approved_by: UserBrief | None
    legal_approved_at: datetime | None
    finance_approved_by: UserBrief | None
    finance_approved_at: datetime | None
    changes_note: str | None
    shared_on: date | None
    share_method: str | None
    customer_accepted_on: date | None
    stamp_duty_amount: int | None
    stamp_duty_paid_on: date | None
    stamp_duty_ref: str | None
    registration_fee_amount: int | None
    registration_fee_paid_on: date | None
    registration_fee_ref: str | None
    appointment_at: datetime | None
    sro_office: str | None
    id_docs_ready: bool
    signing_note: str | None
    executed_on: date | None
    registration_no: str | None
    registered_on: date | None
    final_document: dict | None
    cancel_reason: str | None
    drafted_by_id: int | None
    registration: dict | None = None


class StateOut(BaseModel):
    agreement: AgreementOut | None
    history: list[AgreementOut]  # cancelled agreements
    conditions: list[dict]
    checks: list[dict]
    can: dict[str, bool]


def code(a: Agreement) -> str:
    return f"AGR-{a.id:05d}"


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _live(db: DbSession, case_id: int) -> Agreement | None:
    return await db.scalar(
        select(Agreement).where(Agreement.case_id == case_id, Agreement.status != S.cancelled)
    )


def _need(a: Agreement | None, *allowed: S) -> Agreement:
    if a is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Start the agreement first")
    if a.status not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Not possible while the agreement is {a.status.value.replace('_', ' ')}",
        )
    return a


async def _out(db: DbSession, a: Agreement) -> AgreementOut:
    ids = {x for x in (a.legal_approved_by_id, a.finance_approved_by_id) if x}
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    brief = lambda uid: UserBrief.model_validate(users[uid]) if uid in users else None  # noqa: E731
    doc = await db.get(CaseDocument, a.final_document_id) if a.final_document_id else None
    shown = (
        "completed"
        if doc and doc.approval == Approval.released and a.status == S.final_uploaded
        else a.status.value
    )
    return AgreementOut(
        **{
            k: getattr(a, k)
            for k in (
                "id",
                "version",
                "draft",
                "legal_approved_at",
                "finance_approved_at",
                "changes_note",
                "shared_on",
                "share_method",
                "customer_accepted_on",
                "stamp_duty_amount",
                "stamp_duty_paid_on",
                "stamp_duty_ref",
                "registration_fee_amount",
                "registration_fee_paid_on",
                "registration_fee_ref",
                "appointment_at",
                "sro_office",
                "id_docs_ready",
                "signing_note",
                "executed_on",
                "registration_no",
                "registered_on",
                "cancel_reason",
                "drafted_by_id",
                "registration",
            )
        },
        agreement_no=code(a),
        status=shown,
        legal_approved_by=brief(a.legal_approved_by_id),
        finance_approved_by=brief(a.finance_approved_by_id),
        final_document={
            "id": doc.id,
            "doc_no": f"DOC-{doc.id:05d}",
            "approval": doc.approval.value,
            "url": f"/api/post-sales/documents/{doc.id}/file",
        }
        if doc
        else None,
    )


async def state(db: DbSession, case: PostSalesCase, user: User) -> StateOut:
    a = await _live(db, case.id)
    old = list(
        await db.scalars(
            select(Agreement)
            .where(Agreement.case_id == case.id, Agreement.status == S.cancelled)
            .order_by(Agreement.id.desc())
        )
    )
    conds, chks = await svc.conditions(db, case), await svc.checks(db, case)
    st = a.status if a else None
    r = user.role
    can = {
        "initiate": a is None
        and r in WORKERS
        and case.status == CaseStatus.accepted
        and all(c["ok"] for c in conds),
        "verify": st == S.initiated and r in WORKERS and all(c["ok"] for c in chks),
        "generate": st in (S.data_verified, S.changes_requested)
        and r in DRAFTERS
        and all(c["ok"] for c in chks),
        "submit": st == S.drafted and r in DRAFTERS,
        "approve_legal": st == S.internal_review
        and r in (Role.admin, Role.legal)
        and not a.legal_approved_by_id
        and a.drafted_by_id != user.id,
        "approve_finance": st == S.internal_review
        and r in (Role.admin, Role.finance_approver)
        and not a.finance_approved_by_id
        and a.drafted_by_id != user.id,
        "request_changes": st in (S.internal_review, S.customer_review)
        and r in (*WORKERS, Role.finance_approver),
        "share": st == S.internal_review
        and bool(a.legal_approved_by_id and a.finance_approved_by_id)
        and r in WORKERS,
        "customer_accept": st == S.customer_review and r in WORKERS,
        "prepare": st == S.execution_prep and r in WORKERS,
        "register": st == S.execution_prep and r in DRAFTERS,
        "upload_final": st == S.registered and r in DRAFTERS,
        "cancel": a is not None
        and st not in (S.final_uploaded,)
        and r in (Role.admin, Role.crm_manager, Role.legal),
    }
    return StateOut(
        agreement=await _out(db, a) if a else None,
        history=[await _out(db, x) for x in old],
        conditions=conds,
        checks=chks,
        can=can,
    )


def _log(
    db: DbSession,
    case: PostSalesCase,
    user: User,
    action: str,
    a: Agreement,
    request: Request,
    extra: dict | None = None,
) -> None:
    details = {"agreement": code(a), **(extra or {})}
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=action.replace("agreement_", "agreement."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


async def _done(db: DbSession, case: PostSalesCase, user: User) -> StateOut:
    await db.commit()
    return await state(db, case, user)


@router.get("", response_model=StateOut)
async def get_state(case_id: int, user: Viewer, db: DbSession) -> StateOut:
    return await state(db, await _case(db, case_id), user)


@router.post("/initiate", response_model=StateOut, status_code=status.HTTP_201_CREATED)
async def initiate(case_id: int, request: Request, user: Worker, db: DbSession) -> StateOut:
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Accept the handover first")
    if await _live(db, case_id):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This case already has an agreement in progress"
        )
    unmet = [c["item"] for c in await svc.conditions(db, case) if not c["ok"]]
    if unmet:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Not ready for the agreement: " + "; ".join(unmet),
        )
    a = Agreement(case_id=case.id, initiated_by_id=user.id)
    db.add(a)
    await db.flush()
    _log(db, case, user, "agreement_initiated", a, request)
    return await _done(db, case, user)


@router.post("/verify", response_model=StateOut)
async def verify(case_id: int, request: Request, user: Worker, db: DbSession) -> StateOut:
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.initiated)
    bad = [
        c["item"] + (f" ({c['detail']})" if c.get("detail") else "")
        for c in await svc.checks(db, case)
        if not c["ok"]
    ]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Fix these first: " + "; ".join(bad)
        )
    a.status, a.verified_by_id = S.data_verified, user.id
    _log(db, case, user, "agreement_verified", a, request)
    return await _done(db, case, user)


@router.post("/generate", response_model=StateOut)
async def generate(case_id: int, request: Request, user: Drafter, db: DbSession) -> StateOut:
    """Fill the approved template from the master data; each draft is a new version (approvals start over)."""
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.data_verified, S.changes_requested)
    bad = [c["item"] for c in await svc.checks(db, case) if not c["ok"]]
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Fix these first: " + "; ".join(bad)
        )
    a.version += 1
    a.draft = await svc.build_draft(db, case, code(a), a.version, today())
    a.status, a.drafted_by_id = S.drafted, user.id
    a.legal_approved_by_id = a.legal_approved_at = a.finance_approved_by_id = (
        a.finance_approved_at
    ) = None
    a.shared_on = a.share_method = None
    _log(db, case, user, "agreement_drafted", a, request, {"version": a.version})
    return await _done(db, case, user)


@router.post("/submit", response_model=StateOut)
async def submit(case_id: int, request: Request, user: Drafter, db: DbSession) -> StateOut:
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.drafted)
    a.status, a.changes_note = S.internal_review, None
    _log(db, case, user, "agreement_submitted", a, request, {"version": a.version})
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True),
            User.role.in_([Role.legal, Role.finance_approver]),
            User.id != user.id,
        )
    ):
        notify(
            db,
            user_id=uid,
            type="agreement_review",
            title=f"Agreement to review: {case.booking.lead.name}",
            body=f"{code(a)} draft version {a.version}",
            link=f"/post-sales/{case.id}?tab=agreement",
        )
    return await _done(db, case, user)


@router.post("/approve", response_model=StateOut)
async def approve(case_id: int, request: Request, user: Reviewer, db: DbSession) -> StateOut:
    """Legal and finance each approve (an admin can give either, not both); never the person who drafted it."""
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.internal_review)
    if a.drafted_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who drafted the agreement can't approve it"
        )
    now = datetime.now(UTC)
    if user.role == Role.legal or (
        user.role == Role.admin
        and not a.legal_approved_by_id
        and a.finance_approved_by_id != user.id
    ):
        if a.legal_approved_by_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Legal has already approved this version"
            )
        a.legal_approved_by_id, a.legal_approved_at, side = user.id, now, "legal"
    elif user.role in (Role.finance_approver, Role.admin):
        if a.finance_approved_by_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Finance has already approved this version"
            )
        if a.legal_approved_by_id == user.id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Legal and finance approvals must come from different people",
            )
        a.finance_approved_by_id, a.finance_approved_at, side = user.id, now, "finance"
    _log(db, case, user, "agreement_approved", a, request, {"by": side, "version": a.version})
    return await _done(db, case, user)


@router.post("/request-changes", response_model=StateOut)
async def request_changes(
    case_id: int, body: ReasonIn, request: Request, user: Viewer, db: DbSession
) -> StateOut:
    """Internal reviewers, or the customer (recorded by staff), ask for changes: back to drafting."""
    case = await _case(db, case_id)
    if user.role not in (*WORKERS, Role.finance_approver):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't request changes")
    a = _need(await _live(db, case_id), S.internal_review, S.customer_review)
    who = "customer" if a.status == S.customer_review else "internal"
    a.status, a.changes_note = S.changes_requested, body.reason
    _log(
        db,
        case,
        user,
        "agreement_changes_requested",
        a,
        request,
        {"by": who, "reason": body.reason},
    )
    return await _done(db, case, user)


@router.post("/share", response_model=StateOut)
async def share(
    case_id: int, body: ShareIn, request: Request, user: Worker, db: DbSession
) -> StateOut:
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.internal_review)
    if not (a.legal_approved_by_id and a.finance_approved_by_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Legal and finance must both approve before the customer sees the draft",
        )
    a.status, a.shared_on, a.share_method = (
        S.customer_review,
        body.shared_on or today(),
        body.method,
    )
    _log(
        db,
        case,
        user,
        "agreement_shared",
        a,
        request,
        {"method": body.method, "version": a.version},
    )
    return await _done(db, case, user)


@router.post("/customer-accepted", response_model=StateOut)
async def customer_accepted(
    case_id: int, request: Request, user: Worker, db: DbSession
) -> StateOut:
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.customer_review)
    a.status, a.customer_accepted_on = S.execution_prep, today()
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    if ledger and a.stamp_duty_amount is None:  # start from the ledger's statutory charges
        a.stamp_duty_amount = (
            sum(c.amount for c in ledger.charges if c.head == ChargeHead.stamp_duty) or None
        )
        a.registration_fee_amount = (
            sum(c.amount for c in ledger.charges if c.head == ChargeHead.registration) or None
        )
    _log(db, case, user, "agreement_customer_accepted", a, request, {"version": a.version})
    return await _done(db, case, user)


@router.put("/execution", response_model=StateOut)
async def execution(
    case_id: int, body: ExecutionIn, request: Request, user: Worker, db: DbSession
) -> StateOut:
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.execution_prep)
    t = today()
    for d in (body.stamp_duty_paid_on, body.registration_fee_paid_on):
        if d and d > t:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "A payment date can't be in the future"
            )
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    _log(
        db,
        case,
        user,
        "agreement_execution_updated",
        a,
        request,
        {
            "stamp_duty_paid": bool(a.stamp_duty_paid_on),
            "registration_fee_paid": bool(a.registration_fee_paid_on),
            "appointment": a.appointment_at.isoformat() if a.appointment_at else None,
        },
    )
    return await _done(db, case, user)


@router.post("/register", response_model=StateOut)
async def register(
    case_id: int, body: RegisterIn, request: Request, user: Drafter, db: DbSession
) -> StateOut:
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.execution_prep)
    missing = [
        label
        for ok, label in (
            (a.stamp_duty_paid_on, "stamp duty paid"),
            (a.registration_fee_paid_on, "registration fee paid"),
            (a.appointment_at, "registration appointment"),
            (a.id_docs_ready, "identity documents ready"),
        )
        if not ok
    ]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Before registering, record: " + ", ".join(missing),
        )
    t = today()
    if body.executed_on > t or body.registered_on > t or body.registered_on < body.executed_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Check the dates: not in the future, and registration on or after execution",
        )
    a.status, a.executed_on, a.registration_no, a.registered_on = (
        S.registered,
        body.executed_on,
        body.registration_no.strip(),
        body.registered_on,
    )
    a.sro_office = body.sro_office or a.sro_office
    _log(
        db,
        case,
        user,
        "agreement_registered",
        a,
        request,
        {"registration_no": a.registration_no, "registered_on": a.registered_on.isoformat()},
    )
    return await _done(db, case, user)


@router.post("/final", response_model=StateOut)
async def upload_final(
    case_id: int,
    request: Request,
    user: Drafter,
    db: DbSession,
    file: Annotated[UploadFile, File()],
) -> StateOut:
    """The signed, registered agreement goes into folder 03, linked to the agreement, for review and release."""
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.registered)
    data = await file.read()
    await file.seek(0)
    digest = cases.sha256(data)
    if await db.scalar(
        select(CaseDocument.id).where(
            CaseDocument.case_id == case.id, CaseDocument.sha256 == digest
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This exact file is already in the customer's folder"
        )
    try:
        stored, name, mime = await files.save_receipt(
            file, folder="case_docs", max_mb=20, what="Documents"
        )
    except files.ReceiptError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    doc = CaseDocument(
        case_id=case.id,
        category=DocCategory.agreements,
        doc_type="Registered sale agreement",
        title=f"Registered sale agreement ({code(a)})",
        doc_number=a.registration_no,
        doc_date=a.registered_on,
        linked_ref=code(a),
        file_path=stored,
        file_name=name,
        file_type=mime,
        file_size=len(data),
        sha256=digest,
        uploaded_by_id=user.id,
    )
    db.add(doc)
    await db.flush()
    a.status, a.final_document_id = S.final_uploaded, doc.id
    _log(db, case, user, "agreement_final_uploaded", a, request, {"document": f"DOC-{doc.id:05d}"})
    cases.event(
        db,
        case,
        "document_uploaded",
        user,
        {"document": f"DOC-{doc.id:05d}", "category": "agreements", "title": doc.title},
    )
    return await _done(db, case, user)


@router.post("/cancel", response_model=StateOut)
async def cancel(
    case_id: int, body: ReasonIn, request: Request, user: Viewer, db: DbSession
) -> StateOut:
    case = await _case(db, case_id)
    if user.role not in (Role.admin, Role.crm_manager, Role.legal):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only legal, a CRM manager or an admin can cancel an agreement",
        )
    a = await _live(db, case_id)
    if a is None or a.status == S.final_uploaded:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "There's no agreement in progress to cancel"
        )
    a.status, a.cancel_reason = S.cancelled, body.reason
    _log(db, case, user, "agreement_cancelled", a, request, {"reason": body.reason})
    return await _done(db, case, user)


class RegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    signatories: Annotated[PlainText, StringConstraints(max_length=1000)] | None = (
        None  # parties and authorised signatories present
    )
    documents: dict[
        Annotated[PlainText, StringConstraints(max_length=120)], bool
    ] = {}  # registration document checklist
    receipt_ref: Annotated[PlainText, StringConstraints(max_length=80)] | None = (
        None  # sub-registrar receipt / reference
    )
    original_custody: Literal["customer", "developer", "lender"] | None = (
        None  # who holds the original registered deed
    )
    custody_note: Annotated[PlainText, StringConstraints(max_length=500)] | None = None
    delivered_on: date | None = None  # deed or copy delivered to / collected by the customer
    delivered_via: Literal["hand", "courier", "collected", "lender"] | None = None
    customer_acknowledged: bool = False


@router.put("/registration", response_model=StateOut)
async def registration_details(
    case_id: int, body: RegistrationIn, request: Request, user: Drafter, db: DbSession
) -> StateOut:
    """Stage 14: the rest of the registration record once the agreement is registered."""
    case = await _case(db, case_id)
    a = _need(await _live(db, case_id), S.registered, S.final_uploaded)
    if body.delivered_on and body.delivered_on > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The delivery date can't be in the future"
        )
    if body.delivered_on and not body.delivered_via:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Say how the deed was delivered")
    if body.customer_acknowledged and not body.delivered_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Record the delivery before the customer's acknowledgement",
        )
    if body.original_custody in ("developer", "lender") and not (body.custody_note or "").strip():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Note why the original is held and where"
        )
    a.registration = {
        **body.model_dump(mode="json"),
        "by": user.full_name,
        "at": datetime.now(UTC).isoformat(),
    }
    _log(
        db,
        case,
        user,
        "agreement_registration_details",
        a,
        request,
        {
            "custody": body.original_custody,
            "delivered_on": body.delivered_on.isoformat() if body.delivered_on else None,
        },
    )
    return await _done(db, case, user)
