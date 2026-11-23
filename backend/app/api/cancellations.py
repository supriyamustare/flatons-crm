from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.crypto import decrypt, encrypt
from app.core.deps import DbSession, require_role
from app.models.cancellation import Cancellation
from app.models.case_document import CaseDocument
from app.models.demand import Demand, DemandStatus
from app.models.ledger import Ledger
from app.models.payment import Receipt, ReceiptStatus
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.ticket import Ticket, TicketStatus
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.services import bookings as booking_svc
from app.services import payments
from app.services import postsales as cases
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales/cases/{case_id}/cancellation", tags=["cancellation"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
IST = timezone(timedelta(hours=5, minutes=30))
REASONS = {
    "customer_request": "Customer request",
    "financial_difficulty": "Customer's financial difficulty",
    "loan_rejected": "Home loan rejected",
    "payment_default": "Payment default (termination)",
    "project_delay": "Project delay",
    "transfer_or_change": "Unit change or transfer",
    "other": "Other",
}
Txt = Annotated[PlainText, StringConstraints(min_length=3, max_length=2000)]


def now() -> datetime:
    return datetime.now(UTC)


def today() -> date:
    return now().astimezone(IST).date()


class RequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    initiated_by: Literal["customer", "developer"]
    reason_code: Literal[
        "customer_request",
        "financial_difficulty",
        "loan_rejected",
        "payment_default",
        "project_delay",
        "transfer_or_change",
        "other",
    ]
    reason: Txt
    request_date: date | None = None
    effective_date: date | None = None
    supporting_document_ids: Annotated[list[int], Field(max_length=20)] = []


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Txt
    contract_clause: Annotated[PlainText, StringConstraints(max_length=200)] | None = None


class Deduction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Annotated[PlainText, StringConstraints(min_length=2, max_length=200)]
    amount: Annotated[int, Field(gt=0, le=1_000_000_000)]
    basis: Annotated[
        PlainText, StringConstraints(min_length=3, max_length=500)
    ]  # clause / calculation


class SettlementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deductions: Annotated[list[Deduction], Field(max_length=30)] = []
    note: Annotated[PlainText, StringConstraints(max_length=2000)] | None = None


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: Annotated[PlainText, StringConstraints(max_length=1000)] | None = None


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=1000)]


class CommunicatedIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: date
    via: Literal["email", "courier", "hand", "whatsapp", "portal"]


class BankIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payee: Annotated[PlainText, StringConstraints(min_length=2, max_length=150)]
    bank: Annotated[PlainText, StringConstraints(min_length=2, max_length=150)]
    account_number: Annotated[str, StringConstraints(pattern=r"^[0-9]{9,18}$")]
    ifsc: Annotated[str, StringConstraints(pattern=r"^[A-Z]{4}0[A-Z0-9]{6}$")]
    method: Literal["cancelled_cheque", "bank_letter", "penny_drop", "passbook"]


class PaymentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paid_on: date
    amount: Annotated[int, Field(ge=0, le=1_000_000_000)]
    utr: Annotated[PlainText, StringConstraints(min_length=4, max_length=60)]


def code(c: Cancellation) -> str:
    return f"CXL-{c.id:05d}"


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _live(db: DbSession, case_id: int) -> Cancellation:
    c = await db.scalar(
        select(Cancellation).where(
            Cancellation.case_id == case_id, Cancellation.status.notin_(["withdrawn", "rejected"])
        )
    )
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No cancellation in progress on this case")
    return c


def _who(ok: bool, msg: str) -> None:
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)


def _stage(c: Cancellation, *allowed: str) -> None:
    if c.status not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Not possible while the cancellation is {c.status.replace('_', ' ')}",
        )


async def position(db: DbSession, case: PostSalesCase) -> dict:
    """What has actually been received, and what's outstanding or disputed (step 5's check)."""
    receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
    confirmed = [r for r in receipts if r.status == ReceiptStatus.confirmed]
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    open_demands = list(
        await db.scalars(
            select(Demand).where(Demand.case_id == case.id, Demand.status == DemandStatus.issued)
        )
    )
    paid = payments.position(ledger, receipts)["paid_by_stage"] if ledger else {}
    outstanding = 0
    if ledger:
        for d in open_demands:
            item = next((i for i in ledger.schedule if i.seq == d.stage_seq), None)
            outstanding += max(
                0, (item.amount + item.gst - paid.get(d.stage_seq, 0)) if item else 0
            )
    disputes = list(
        await db.scalars(
            select(Ticket).where(Ticket.case_id == case.id, Ticket.status != TicketStatus.closed)
        )
    )
    return {
        "received": sum(r.amount for r in confirmed),
        "received_own": sum(r.amount for r in confirmed if r.source.value == "own"),
        "loan_disbursed": sum(r.amount for r in confirmed if r.source.value == "loan"),
        "unconfirmed_receipts": sum(1 for r in receipts if r.status == ReceiptStatus.recorded),
        "outstanding_demands": outstanding,
        "open_tickets": [f"TKT-{t.id:05d}" for t in disputes],
    }


def _out(c: Cancellation | None, user: User, pos: dict, history: list[dict]) -> dict:
    r = user.role
    base = {
        "reasons": REASONS,
        "history": history,
        "position": pos,
        "can_request": c is None and r in (Role.admin, Role.crm_manager, Role.postsales_exec),
    }
    if c is None:
        return {"cancellation": None, **base}
    s = c.status
    approvals = {a["kind"]: a for a in c.approvals or []}
    prepared_by = (c.settlement or {}).get("prepared_by_id")
    bank = dict(c.refund_bank or {})
    if bank.get("account_enc"):
        acct = decrypt(bank.pop("account_enc")) or ""
        bank["account_masked"] = "••••" + acct[-4:]
    refund = (c.settlement or {}).get("refund", 0)
    pay = c.refund_payment or {}
    can = {
        "legal_review": s in ("requested", "reviewed")
        and not c.legal_review
        and r in (Role.admin, Role.legal),
        "commercial_review": s in ("requested", "reviewed")
        and not c.commercial_review
        and r in (Role.admin, Role.crm_manager),
        "settlement": s in ("reviewed", "settlement_proposed")
        and not approvals
        and r in (Role.admin, Role.finance),
        "approve_finance": s == "settlement_proposed"
        and "finance" not in approvals
        and r in (Role.admin, Role.finance_approver)
        and prepared_by != user.id,
        "approve_management": s == "settlement_proposed"
        and "management" not in approvals
        and r in (Role.admin, Role.management)
        and prepared_by != user.id
        and approvals.get("finance", {}).get("by") != user.id,
        "reject": s == "settlement_proposed"
        and r in (Role.admin, Role.finance_approver, Role.management),
        "communicate": s == "approved" and r in (Role.admin, Role.crm_manager, Role.postsales_exec),
        "bank": s in ("approved", "communicated")
        and refund > 0
        and not bank.get("verified_by")
        and r in (Role.admin, Role.finance),
        "verify_bank": bool(bank)
        and not bank.get("verified_by")
        and r in (Role.admin, Role.finance_approver)
        and bank.get("entered_by") != user.id,
        "pay": bool(bank.get("verified_by")) and not pay and r in (Role.admin, Role.finance),
        "reconcile": bool(pay)
        and not pay.get("reconciled_by")
        and r in (Role.admin, Role.finance_approver)
        and pay.get("processed_by") != user.id,
        "release": s in ("approved", "communicated")
        and not c.release
        and r in (Role.admin, Role.crm_manager),
        "close": not c.closed_at
        and bool(c.release)
        and (refund <= 0 or bool(pay.get("reconciled_by")))
        and bool(c.communication)
        and r in (Role.admin, Role.crm_manager),
        "withdraw": s in ("requested", "reviewed", "settlement_proposed")
        and r in (Role.admin, Role.crm_manager),
    }
    return {
        "cancellation": {
            "id": c.id,
            "number": code(c),
            "status": s,
            "initiated_by": c.initiated_by,
            "reason_code": c.reason_code,
            "reason_label": REASONS[c.reason_code],
            "reason": c.reason,
            "request_date": c.request_date,
            "effective_date": c.effective_date,
            "contract_clause": c.contract_clause,
            "supporting_document_ids": c.supporting_document_ids,
            "legal_review": c.legal_review,
            "commercial_review": c.commercial_review,
            "settlement": c.settlement,
            "approvals": c.approvals,
            "communication": c.communication,
            "refund_bank": bank or None,
            "refund_payment": c.refund_payment,
            "release": c.release,
            "end_reason": c.end_reason,
            "closed_at": c.closed_at,
            "can": can,
        },
        **base,
    }


async def state(db: DbSession, case: PostSalesCase, user: User) -> dict:
    c = await db.scalar(
        select(Cancellation).where(
            Cancellation.case_id == case.id, Cancellation.status.notin_(["withdrawn", "rejected"])
        )
    )
    past = list(
        await db.scalars(
            select(Cancellation)
            .where(
                Cancellation.case_id == case.id, Cancellation.status.in_(["withdrawn", "rejected"])
            )
            .order_by(Cancellation.id.desc())
        )
    )
    history = [
        {
            "number": code(x),
            "status": x.status,
            "reason": x.end_reason,
            "request_date": x.request_date,
        }
        for x in past
    ]
    return _out(c, user, await position(db, case), history)


def _log(
    db: DbSession,
    case: PostSalesCase,
    user: User,
    action: str,
    c: Cancellation,
    request: Request,
    details: dict | None = None,
) -> None:
    d = {"cancellation": code(c), **(details or {})}
    cases.event(db, case, action, user, d)
    log_audit(
        db,
        action=action.replace("cancellation_", "cancellation."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=d,
        request=request,
    )


async def _done(db: DbSession, case: PostSalesCase, user: User) -> dict:
    await db.commit()
    return await state(db, case, user)


def _stamp(user: User, note: str | None = None) -> dict:
    return {
        "by": user.id,
        "by_name": user.full_name,
        "at": now().isoformat(),
        **({"note": note} if note is not None else {}),
    }


@router.get("")
async def get_state(case_id: int, user: Viewer, db: DbSession) -> dict:
    return await state(db, await _case(db, case_id), user)


@router.post("", status_code=status.HTTP_201_CREATED)
async def request_cancellation(
    case_id: int, body: RequestIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(
        user.role in (Role.admin, Role.crm_manager, Role.postsales_exec),
        "Post-sales, CRM managers or admins record a cancellation request",
    )
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only an accepted case can be cancelled here"
        )
    if await db.scalar(
        select(Cancellation.id).where(
            Cancellation.case_id == case_id, Cancellation.status.notin_(["withdrawn", "rejected"])
        )
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "A cancellation is already in progress")
    rd = body.request_date or today()
    if rd > today() or (body.effective_date and body.effective_date < rd):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Check the dates: the request can't be in the future, and the effective date can't be before it",
        )
    for did in body.supporting_document_ids:
        d = await db.get(CaseDocument, did)
        if d is None or d.case_id != case.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Attach supporting documents from this customer's folder",
            )
    c = Cancellation(
        case_id=case.id,
        initiated_by=body.initiated_by,
        reason_code=body.reason_code,
        reason=body.reason,
        request_date=rd,
        effective_date=body.effective_date,
        supporting_document_ids=body.supporting_document_ids,
        requested_by_id=user.id,
        approvals=[],
    )
    db.add(c)
    await db.flush()
    _log(
        db,
        case,
        user,
        "cancellation_requested",
        c,
        request,
        {"reason": REASONS[body.reason_code], "by": body.initiated_by},
    )
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True),
            User.role.in_([Role.legal, Role.crm_manager]),
            User.id != user.id,
        )
    ):
        notify(
            db,
            user_id=uid,
            type="cancellation_review",
            title=f"Cancellation to review: {case.booking.lead.name}",
            body=f"{code(c)}: {REASONS[body.reason_code]}",
            link=f"/post-sales/{case.id}?tab=cancellation",
        )
    return await _done(db, case, user)


@router.post("/review/{kind}")
async def review(
    case_id: int,
    kind: Literal["legal", "commercial"],
    body: ReviewIn,
    request: Request,
    user: Viewer,
    db: DbSession,
) -> dict:
    """Step 3: legal and commercial review of the contract terms (both needed)."""
    _who(
        user.role
        in ((Role.admin, Role.legal) if kind == "legal" else (Role.admin, Role.crm_manager)),
        "Legal reviews the contract terms"
        if kind == "legal"
        else "A CRM manager gives the commercial review",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "requested", "reviewed")
    if kind == "legal":
        if c.legal_review:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Legal has already reviewed it"
            )
        if not (body.contract_clause or "").strip():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Cite the applicable contract clause"
            )
        c.legal_review, c.contract_clause = _stamp(user, body.note), body.contract_clause.strip()
    else:
        if c.commercial_review:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "The commercial review is already recorded"
            )
        c.commercial_review = _stamp(user, body.note)
    if c.legal_review and c.commercial_review:
        c.status = "reviewed"
    _log(db, case, user, f"cancellation_{kind}_review", c, request)
    return await _done(db, case, user)


@router.put("/settlement")
async def settlement(
    case_id: int, body: SettlementIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """Steps 4-5: deductions with their basis, checked against what was actually received."""
    _who(user.role in (Role.admin, Role.finance), "Finance calculates the settlement")
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "reviewed", "settlement_proposed")
    if c.approvals:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Approvals have started; reject to change the settlement",
        )
    pos = await position(db, case)
    if pos["unconfirmed_receipts"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{pos['unconfirmed_receipts']} receipt(s) still need confirming or rejecting before the settlement",
        )
    total = sum(d.amount for d in body.deductions)
    c.settlement = {
        "snapshot": pos,
        "deductions": [d.model_dump() for d in body.deductions],
        "total_deductions": total,
        "refund": max(0, pos["received"] - total),
        "balance_due_from_customer": max(0, total - pos["received"]),
        "note": body.note,
        "prepared_by_id": user.id,
        "prepared_by": user.full_name,
        "at": now().isoformat(),
    }
    c.status = "settlement_proposed"
    _log(
        db,
        case,
        user,
        "cancellation_settlement",
        c,
        request,
        {"received": pos["received"], "deductions": total, "refund": c.settlement["refund"]},
    )
    return await _done(db, case, user)


@router.post("/approve/{kind}")
async def approve(
    case_id: int,
    kind: Literal["finance", "management"],
    body: NoteIn,
    request: Request,
    user: Viewer,
    db: DbSession,
) -> dict:
    """Step 6: a finance approver checks the calculation; management approves. Neither may have prepared it."""
    _who(
        user.role
        in (
            (Role.admin, Role.finance_approver)
            if kind == "finance"
            else (Role.admin, Role.management)
        ),
        "A finance approver checks the settlement"
        if kind == "finance"
        else "Management approves the cancellation",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "settlement_proposed")
    done = {a["kind"]: a for a in c.approvals or []}
    if kind in done:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This approval is already recorded"
        )
    if (c.settlement or {}).get("prepared_by_id") == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who prepared the settlement can't approve it"
        )
    if any(a["by"] == user.id for a in done.values()):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The two approvals must come from different people"
        )
    c.approvals = [
        *(c.approvals or []),
        {"kind": kind, **_stamp(user, (body.note or "").strip() or None)},
    ]
    if {a["kind"] for a in c.approvals} >= {"finance", "management"}:
        c.status = "approved"
    _log(db, case, user, f"cancellation_{kind}_approved", c, request)
    return await _done(db, case, user)


@router.post("/reject")
async def reject(
    case_id: int, body: ReasonIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(
        user.role in (Role.admin, Role.finance_approver, Role.management),
        "Finance approvers or management reject the settlement",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "settlement_proposed")
    c.status, c.end_reason = "rejected", body.reason
    _log(db, case, user, "cancellation_rejected", c, request, {"reason": body.reason})
    return await _done(db, case, user)


@router.post("/withdraw")
async def withdraw(
    case_id: int, body: ReasonIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    _who(user.role in (Role.admin, Role.crm_manager), "A CRM manager records the withdrawal")
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "requested", "reviewed", "settlement_proposed")
    c.status, c.end_reason = "withdrawn", body.reason
    _log(db, case, user, "cancellation_withdrawn", c, request, {"reason": body.reason})
    return await _done(db, case, user)


@router.post("/communicated")
async def communicated(
    case_id: int, body: CommunicatedIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """Step 7: the approved settlement (cancellation letter) sent to the customer."""
    _who(
        user.role in (Role.admin, Role.crm_manager, Role.postsales_exec),
        "Post-sales sends the cancellation letter",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "approved")
    if body.on > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The date can't be in the future"
        )
    c.communication, c.status = (
        {"on": body.on.isoformat(), "via": body.via, "by_name": user.full_name},
        "communicated",
    )
    _log(db, case, user, "cancellation_communicated", c, request, {"via": body.via})
    return await _done(db, case, user)


@router.put("/refund-bank")
async def refund_bank(
    case_id: int, body: BankIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """Step 8: the refund account, stored encrypted, verified by a second person."""
    _who(user.role in (Role.admin, Role.finance), "Finance records the refund account")
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "approved", "communicated")
    if (c.settlement or {}).get("refund", 0) <= 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No refund is due")
    if (c.refund_bank or {}).get("verified_by"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The account is already verified"
        )
    c.refund_bank = {
        "payee": body.payee,
        "bank": body.bank,
        "account_enc": encrypt(body.account_number),
        "ifsc": body.ifsc,
        "method": body.method,
        "entered_by": user.id,
        "entered_by_name": user.full_name,
        "entered_at": now().isoformat(),
    }
    _log(
        db,
        case,
        user,
        "cancellation_refund_account",
        c,
        request,
        {"payee": body.payee, "bank": body.bank, "account": "••••" + body.account_number[-4:]},
    )
    return await _done(db, case, user)


@router.post("/refund-bank/verify")
async def verify_bank(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    _who(
        user.role in (Role.admin, Role.finance_approver),
        "A finance approver verifies the refund account",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    b = dict(c.refund_bank or {})
    if not b or b.get("verified_by"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to verify")
    if b.get("entered_by") == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Someone other than the person who entered the account must verify it",
        )
    b.update(
        {
            "verified_by": user.id,
            "verified_by_name": user.full_name,
            "verified_at": now().isoformat(),
        }
    )
    c.refund_bank = b
    _log(db, case, user, "cancellation_refund_account_verified", c, request)
    return await _done(db, case, user)


@router.post("/refund-payment")
async def refund_payment(
    case_id: int, body: PaymentIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """Step 9: the refund paid (maker); a finance approver reconciles it (checker). The amount must be the approved refund."""
    _who(user.role in (Role.admin, Role.finance), "Finance records the refund payment")
    case, c = await _case(db, case_id), await _live(db, case_id)
    if not (c.refund_bank or {}).get("verified_by"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Verify the refund account first"
        )
    if c.refund_payment:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The refund payment is already recorded"
        )
    approved = (c.settlement or {}).get("refund", 0)
    if body.amount != approved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The refund must be the approved Rs {approved:,}",
        )
    if body.paid_on > today():
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The payment date can't be in the future"
        )
    c.refund_payment = {
        "paid_on": body.paid_on.isoformat(),
        "amount": body.amount,
        "utr": body.utr.strip().upper(),
        "processed_by": user.id,
        "processed_by_name": user.full_name,
        "processed_at": now().isoformat(),
    }
    _log(
        db,
        case,
        user,
        "cancellation_refund_paid",
        c,
        request,
        {"amount": body.amount, "utr": body.utr},
    )
    from app.services import comms

    await comms.emit(
        db,
        "refund_processed",
        case,
        {
            "amount": body.amount,
            "paid_on": body.paid_on.strftime("%d %b %Y"),
            "utr": body.utr.strip().upper(),
        },
        c.id,
    )
    return await _done(db, case, user)


@router.post("/refund-payment/reconcile")
async def reconcile(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    _who(
        user.role in (Role.admin, Role.finance_approver), "A finance approver reconciles the refund"
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    p = dict(c.refund_payment or {})
    if not p or p.get("reconciled_by"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing to reconcile")
    if p.get("processed_by") == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Someone other than the person who recorded the payment must reconcile it",
        )
    p.update(
        {
            "reconciled_by": user.id,
            "reconciled_by_name": user.full_name,
            "reconciled_at": now().isoformat(),
        }
    )
    c.refund_payment = p
    _log(db, case, user, "cancellation_refund_reconciled", c, request)
    return await _done(db, case, user)


@router.post("/release")
async def release_unit(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    """Step 11: the unit is released only after the cancellation is approved. The booking is cancelled; nothing is erased."""
    _who(
        user.role in (Role.admin, Role.crm_manager),
        "A CRM manager or admin approves the unit release",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    _stage(c, "approved", "communicated")
    if c.release:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The unit is already released")
    try:
        await booking_svc.cancel(
            db, case.booking, actor=user, reason=f"{code(c)}: {REASONS[c.reason_code]}"
        )
    except booking_svc.BookingRuleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    c.release = _stamp(user)
    _log(
        db,
        case,
        user,
        "cancellation_unit_released",
        c,
        request,
        {"unit": case.booking.unit.unit_no},
    )
    return await _done(db, case, user)


@router.post("/close")
async def close(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    """Step 12: closed once the letter is sent, the unit released and any refund reconciled. The account is archived."""
    _who(
        user.role in (Role.admin, Role.crm_manager),
        "A CRM manager or admin closes the cancellation",
    )
    case, c = await _case(db, case_id), await _live(db, case_id)
    if c.closed_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Already closed")
    refund = (c.settlement or {}).get("refund", 0)
    missing = [
        m
        for ok, m in (
            (c.communication, "the cancellation letter sent"),
            (c.release, "the unit released"),
            (refund <= 0 or (c.refund_payment or {}).get("reconciled_by"), "the refund reconciled"),
        )
        if not ok
    ]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Before closing: " + ", ".join(missing)
        )
    c.status, c.closed_at, c.closed_by_id = "closed", now(), user.id
    _log(db, case, user, "cancellation_closed", c, request)
    return await _done(db, case, user)
