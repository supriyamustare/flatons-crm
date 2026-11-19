from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select

from app.core.deps import DbSession, require_role
from app.models.case_document import CaseDocument, DocCategory
from app.models.ledger import Ledger
from app.models.loan import (
    Disbursement,
    DisbursementStatus,
    Loan,
    LoanDocRequest,
    VerificationState,
)
from app.models.payment import LIVE, FundSource, Receipt, ReceiptMode
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.user import LEDGER_MAKERS, LEDGER_VIEWERS, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import loans as svc
from app.services import postsales as cases
from app.services.audit import log_audit

router = APIRouter(prefix="/post-sales/cases/{case_id}/loan", tags=["home loan"])
Viewer = Annotated[
    User, Depends(require_role(*LEDGER_VIEWERS))
]  # loan data stays with the people who see the ledger
EDITORS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.finance)
Editor = Annotated[User, Depends(require_role(*EDITORS))]
Maker = Annotated[
    User, Depends(require_role(*LEDGER_MAKERS))
]  # recording funds received creates a receipt
IST = timezone(timedelta(hours=5, minutes=30))
Text = Annotated[PlainText, StringConstraints(max_length=200)]
Money = Annotated[int, Field(gt=0, le=1_000_000_000)]


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class LoanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lender: Annotated[PlainText, StringConstraints(min_length=2, max_length=150)]
    application_no: Annotated[PlainText, StringConstraints(max_length=80)] | None = None
    consent_on: date | None = None
    applied_amount: Money | None = None
    sanctioned_amount: Money | None = None
    sanction_date: date | None = None
    sanction_valid_until: date | None = None
    rm_name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    rm_phone: (
        Annotated[PlainText, StringConstraints(max_length=20, pattern=r"^[0-9+()\- ]{6,20}$")]
        | None
    ) = None
    rm_email: (
        Annotated[
            PlainText,
            StringConstraints(max_length=254, pattern=r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$"),
        ]
        | None
    ) = None
    technical_status: VerificationState = VerificationState.not_started
    legal_status: VerificationState = VerificationState.not_started
    pending_conditions: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None
    owner_id: int | None = None
    next_follow_up_on: date | None = None

    @model_validator(mode="after")
    def _rules(self) -> "LoanIn":
        t = today()
        if self.consent_on and self.consent_on > t:
            raise ValueError("The consent date can't be in the future")
        if self.sanctioned_amount and not self.sanction_date:
            raise ValueError("Enter the sanction date with the sanctioned amount")
        if self.sanction_date and self.sanction_date > t:
            raise ValueError("The sanction date can't be in the future")
        if (
            self.sanction_valid_until
            and self.sanction_date
            and self.sanction_valid_until < self.sanction_date
        ):
            raise ValueError("The sanction can't expire before it was given")
        if (
            self.applied_amount
            and self.sanctioned_amount
            and self.sanctioned_amount > self.applied_amount
        ):
            raise ValueError("The sanctioned amount can't be more than the amount applied for")
        return self


class DocRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[PlainText, StringConstraints(min_length=2, max_length=200)]
    requested_on: date | None = None
    note: Annotated[PlainText, StringConstraints(max_length=500)] | None = None


class SubmittedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submitted_on: date | None = None
    case_document_id: int | None = None


class DisbursementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_no: Annotated[PlainText, StringConstraints(max_length=80)] | None = None
    request_date: date | None = None
    for_stage: Annotated[PlainText, StringConstraints(max_length=120)] | None = None
    expected_amount: Money
    expected_date: date | None = None


class DisbursementUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["awaited", "cancelled"] | None = None
    expected_date: date | None = None
    delay_reason: Annotated[PlainText, StringConstraints(max_length=500)] | None = None


class ReceivedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actual_date: date
    actual_amount: Money
    utr: Annotated[PlainText, StringConstraints(min_length=4, max_length=60)]
    mode: Literal["neft", "rtgs", "imps", "cheque", "dd", "other"] = "neft"


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class LoanState(BaseModel):
    loan: dict | None
    history: list[dict]
    stage: str | None
    stages: list[dict]
    doc_requests: list[dict]
    disbursements: list[dict]
    ledger_loan: int
    warnings: list[str]
    owners: list[UserBrief]
    can_edit: bool
    can_record_funds: bool


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _live(db: DbSession, case_id: int) -> Loan | None:
    return await db.scalar(select(Loan).where(Loan.case_id == case_id, Loan.closed_at.is_(None)))


def _row(loan: Loan) -> dict:
    keys = (
        "id",
        "lender",
        "application_no",
        "consent_on",
        "applied_amount",
        "sanctioned_amount",
        "sanction_date",
        "sanction_valid_until",
        "rm_name",
        "rm_phone",
        "rm_email",
        "technical_status",
        "legal_status",
        "pending_conditions",
        "owner_id",
        "next_follow_up_on",
        "closed_at",
        "close_reason",
    )
    return {k: getattr(loan, k) for k in keys}


async def state(db: DbSession, case: PostSalesCase, user: User) -> LoanState:
    loan = await _live(db, case.id)
    closed = list(
        await db.scalars(
            select(Loan)
            .where(Loan.case_id == case.id, Loan.closed_at.is_not(None))
            .order_by(Loan.id.desc())
        )
    )
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    owners = [
        UserBrief.model_validate(u)
        for u in await db.scalars(
            select(User)
            .where(
                User.is_active.is_(True),
                User.role.in_([Role.postsales_exec, Role.crm_manager, Role.finance]),
            )
            .order_by(User.full_name)
        )
    ]
    base = {
        "history": [_row(x) for x in closed],
        "ledger_loan": ledger.loan_sanctioned if ledger else 0,
        "owners": owners,
        "can_edit": user.role in EDITORS and case.status == CaseStatus.accepted,
        "can_record_funds": user.role in LEDGER_MAKERS,
    }
    if loan is None:
        return LoanState(
            loan=None, stage=None, stages=[], doc_requests=[], disbursements=[], warnings=[], **base
        )
    receipts = {
        r.id: r for r in await db.scalars(select(Receipt).where(Receipt.case_id == case.id))
    }
    t = today()
    st = svc.stage(loan, receipts)
    idx = svc.STAGES.index(st) if st in svc.STAGES else 0
    warnings = []
    if not loan.consent_on:
        warnings.append("Record the customer's consent before coordinating with the bank")
    if loan.sanctioned_amount and ledger and ledger.loan_sanctioned != loan.sanctioned_amount:
        warnings.append(
            f"The ledger's loan is Rs {ledger.loan_sanctioned:,} but Rs {loan.sanctioned_amount:,} is sanctioned; update the ledger's funding"
        )
    if loan.sanction_valid_until and loan.sanction_valid_until < t:
        warnings.append(
            f"The sanction expired on {loan.sanction_valid_until.isoformat()}; renewal needed"
        )
    elif loan.sanction_valid_until and loan.sanction_valid_until <= t + timedelta(
        days=svc.SANCTION_WARNING_DAYS
    ):
        warnings.append(f"The sanction expires on {loan.sanction_valid_until.isoformat()}")
    disb = []
    for d in loan.disbursements:
        r = receipts.get(d.receipt_id) if d.receipt_id else None
        disb.append(
            {
                k: getattr(d, k)
                for k in (
                    "id",
                    "request_no",
                    "request_date",
                    "for_stage",
                    "expected_amount",
                    "expected_date",
                    "status",
                    "delay_reason",
                    "actual_date",
                    "actual_amount",
                    "utr",
                    "receipt_id",
                )
            }
            | {
                "state": svc.disbursement_state(d, receipts),
                "delayed": svc.is_delayed(d, t),
                "receipt_no": f"RCT-{r.id:05d}" if r else None,
                "receipt_status": r.status.value if r else None,
            }
        )
    received = sum(
        d.actual_amount or 0 for d in loan.disbursements if d.status == DisbursementStatus.received
    )
    if loan.sanctioned_amount and received > loan.sanctioned_amount:
        warnings.append("More has been received than was sanctioned; check the disbursements")
    return LoanState(
        loan=_row(loan)
        | {
            "received_total": received,
            "remaining": max(0, (loan.sanctioned_amount or 0) - received),
        },
        stage=st,
        stages=[
            {"key": k, "label": svc.LABELS[k], "done": i < idx, "current": i == idx}
            for i, k in enumerate(svc.STAGES)
        ],
        doc_requests=[
            {
                k: getattr(r, k)
                for k in ("id", "name", "requested_on", "note", "submitted_on", "case_document_id")
            }
            for r in loan.doc_requests
        ],
        disbursements=disb,
        warnings=warnings,
        **base,
    )


def _log(
    db: DbSession, case: PostSalesCase, user: User, action: str, request: Request, details: dict
) -> None:
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=action.replace("loan_", "loan."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


async def _owner_ok(db: DbSession, owner_id: int | None) -> None:
    if owner_id is not None:
        u = await db.get(User, owner_id)
        if (
            u is None
            or not u.is_active
            or u.role not in (Role.postsales_exec, Role.crm_manager, Role.finance)
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Choose an active post-sales, CRM or finance person as the follow-up owner",
            )


def _consented(loan: Loan) -> None:
    if not loan.consent_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Record the customer's consent before coordinating with the bank",
        )


@router.get("", response_model=LoanState)
async def get_loan(case_id: int, user: Viewer, db: DbSession) -> LoanState:
    return await state(db, await _case(db, case_id), user)


@router.post("", response_model=LoanState, status_code=status.HTTP_201_CREATED)
async def create(
    case_id: int, body: LoanIn, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Accept the handover first")
    if await _live(db, case_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This case already has an open loan")
    await _owner_ok(db, body.owner_id)
    loan = Loan(
        case_id=case.id,
        **body.model_dump(),
        consent_recorded_by_id=user.id if body.consent_on else None,
    )
    db.add(loan)
    await db.flush()
    _log(
        db,
        case,
        user,
        "loan_created",
        request,
        {"lender": loan.lender, "applied": loan.applied_amount},
    )
    await db.commit()
    return await state(db, case, user)


@router.put("", response_model=LoanState)
async def update(
    case_id: int, body: LoanIn, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    loan = await _live(db, case_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open loan on this case")
    await _owner_ok(db, body.owner_id)
    before = {k: str(v) for k, v in _row(loan).items()}
    if body.consent_on and not loan.consent_on:
        loan.consent_recorded_by_id = user.id
    for k, v in body.model_dump().items():
        setattr(loan, k, v)
    changed = {
        k: {"from": before[k], "to": str(getattr(loan, k))}
        for k in LoanIn.model_fields
        if before.get(k) != str(getattr(loan, k))
    }
    _log(db, case, user, "loan_updated", request, {"changed": list(changed)})
    await db.commit()
    return await state(db, case, user)


@router.post("/doc-requests", response_model=LoanState, status_code=status.HTTP_201_CREATED)
async def add_doc_request(
    case_id: int, body: DocRequestIn, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    loan = await _live(db, case_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open loan on this case")
    _consented(loan)
    if body.requested_on and body.requested_on > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The request date can't be in the future"
        )
    loan.doc_requests.append(
        LoanDocRequest(name=body.name, requested_on=body.requested_on or today(), note=body.note)
    )
    _log(db, case, user, "loan_document_requested", request, {"document": body.name})
    await db.commit()
    return await state(db, case, user)


@router.post("/doc-requests/{rid}/submitted", response_model=LoanState)
async def doc_submitted(
    case_id: int, rid: int, body: SubmittedIn, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    r = await db.get(LoanDocRequest, rid)
    loan = await _live(db, case_id)
    if r is None or loan is None or r.loan_id != loan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    if body.case_document_id is not None:
        doc = await db.get(CaseDocument, body.case_document_id)
        if doc is None or doc.case_id != case.id or doc.category != DocCategory.loan:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Link a document from this customer's 06 Home Loan & Bank folder",
            )
    when = body.submitted_on or today()
    if when > today() or when < r.requested_on:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The submitted date must be between the request date and today",
        )
    r.submitted_on, r.submitted_by_id, r.case_document_id = when, user.id, body.case_document_id
    _log(db, case, user, "loan_document_submitted", request, {"document": r.name})
    await db.commit()
    return await state(db, case, user)


@router.post("/disbursements", response_model=LoanState, status_code=status.HTTP_201_CREATED)
async def request_disbursement(
    case_id: int, body: DisbursementIn, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    loan = await _live(db, case_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open loan on this case")
    _consented(loan)
    if not loan.sanctioned_amount:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Record the sanction before requesting a disbursement",
        )
    asked = sum(
        d.expected_amount for d in loan.disbursements if d.status != DisbursementStatus.cancelled
    )
    if asked + body.expected_amount > loan.sanctioned_amount:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"That would request more than the sanctioned Rs {loan.sanctioned_amount:,} (Rs {asked:,} already requested)",
        )
    if body.request_date and body.request_date > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The request date can't be in the future"
        )
    loan.disbursements.append(
        Disbursement(
            request_no=body.request_no,
            request_date=body.request_date or today(),
            for_stage=body.for_stage,
            expected_amount=body.expected_amount,
            expected_date=body.expected_date,
        )
    )
    _log(
        db,
        case,
        user,
        "loan_disbursement_requested",
        request,
        {"amount": body.expected_amount, "for": body.for_stage},
    )
    await db.commit()
    return await state(db, case, user)


async def _disb(db: DbSession, case_id: int, did: int) -> tuple[Loan, Disbursement]:
    loan = await _live(db, case_id)
    d = await db.get(Disbursement, did)
    if loan is None or d is None or d.loan_id != loan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Disbursement not found")
    return loan, d


@router.put("/disbursements/{did}", response_model=LoanState)
async def update_disbursement(
    case_id: int, did: int, body: DisbursementUpdate, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    _, d = await _disb(db, case_id, did)
    if d.status in (DisbursementStatus.received, DisbursementStatus.cancelled):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This disbursement is already received or cancelled",
        )
    if body.status == "cancelled" and not body.delay_reason:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Give a reason for cancelling the request"
        )
    if body.status:
        d.status = DisbursementStatus(body.status)
    if body.expected_date:
        d.expected_date = body.expected_date
    if body.delay_reason is not None:
        d.delay_reason = body.delay_reason
    _log(
        db,
        case,
        user,
        "loan_disbursement_updated",
        request,
        {
            "status": d.status.value,
            "expected": d.expected_date.isoformat() if d.expected_date else None,
            "reason": d.delay_reason,
        },
    )
    await db.commit()
    return await state(db, case, user)


@router.post("/disbursements/{did}/received", response_model=LoanState)
async def funds_received(
    case_id: int, did: int, body: ReceivedIn, request: Request, user: Maker, db: DbSession
) -> LoanState:
    """Record the money arriving: creates a loan receipt that a finance approver confirms in Receipts. Demands aren't
    marked paid by this; only the confirmed, matched receipt counts."""
    case = await _case(db, case_id)
    loan, d = await _disb(db, case_id, did)
    if d.status not in (DisbursementStatus.requested, DisbursementStatus.awaited):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a requested or awaited disbursement can be received",
        )
    if body.actual_date > today() or body.actual_date < d.request_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The date received must be between the request date and today",
        )
    utr = body.utr.strip().upper()
    mode = ReceiptMode(body.mode)
    if await db.scalar(
        select(Receipt.id).where(
            Receipt.mode == mode, func.upper(Receipt.reference) == utr, Receipt.status.in_(LIVE)
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A receipt with reference {utr} is already recorded"
        )
    if not await db.scalar(select(Ledger.id).where(Ledger.case_id == case.id)):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Generate the ledger first, so the money can be matched",
        )
    r = Receipt(
        case_id=case.id,
        amount=body.actual_amount,
        received_on=body.actual_date,
        mode=mode,
        source=FundSource.loan,
        payer_name=loan.lender,
        reference=utr,
        bank_name=loan.lender,
        notes=f"Loan disbursement{(' ' + d.request_no) if d.request_no else ''}{(' for ' + d.for_stage) if d.for_stage else ''}",
        recorded_by_id=user.id,
    )
    db.add(r)
    await db.flush()
    d.status, d.actual_date, d.actual_amount, d.utr, d.receipt_id = (
        DisbursementStatus.received,
        body.actual_date,
        body.actual_amount,
        utr,
        r.id,
    )
    _log(
        db,
        case,
        user,
        "loan_funds_received",
        request,
        {"amount": body.actual_amount, "utr": utr, "receipt": f"RCT-{r.id:05d}"},
    )
    cases.event(
        db,
        case,
        "receipt_recorded",
        user,
        {"receipt": f"RCT-{r.id:05d}", "amount": r.amount, "mode": r.mode.value, "source": "loan"},
    )
    await db.commit()
    return await state(db, case, user)


@router.post("/close", response_model=LoanState)
async def close(
    case_id: int, body: ReasonIn, request: Request, user: Editor, db: DbSession
) -> LoanState:
    case = await _case(db, case_id)
    loan = await _live(db, case_id)
    if loan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open loan on this case")
    loan.closed_at, loan.close_reason = datetime.now(UTC), body.reason
    _log(db, case, user, "loan_closed", request, {"reason": body.reason})
    await db.commit()
    return await state(db, case, user)
