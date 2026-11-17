import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.deps import DbSession, require_role
from app.models.ledger import ChargeHead, Ledger
from app.models.payment import (
    BOUNCEABLE,
    Allocation,
    FundSource,
    Receipt,
    ReceiptMode,
    ReceiptStatus,
)
from app.models.postsales import PostSalesCase
from app.models.user import LEDGER_CHECKERS, LEDGER_MAKERS, LEDGER_VIEWERS, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import ledger as ledger_svc
from app.services import payments as svc
from app.services import postsales as cases
from app.services.audit import log_audit

router = APIRouter(prefix="/post-sales/cases/{case_id}/receipts", tags=["receipts"])
Viewer = Annotated[User, Depends(require_role(*LEDGER_VIEWERS))]
Maker = Annotated[User, Depends(require_role(*LEDGER_MAKERS))]
Checker = Annotated[User, Depends(require_role(*LEDGER_CHECKERS))]
IST = timezone(timedelta(hours=5, minutes=30))
CASH_LIMIT = 200_000  # Income-tax Act s.269ST: no cash receipt of Rs 2 lakh or more


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


class MatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage_seq: int | None = None
    charge_head: ChargeHead | None = None
    amount: Annotated[int, Field(gt=0, le=1_000_000_000)]

    @model_validator(mode="after")
    def _one(self) -> "MatchIn":
        if (self.stage_seq is None) == (self.charge_head is None):
            raise ValueError("Match each amount to either a stage or a charge")
        return self


class ReceiptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount: Annotated[int, Field(gt=0, le=1_000_000_000)]
    received_on: date
    mode: ReceiptMode
    source: FundSource = FundSource.own
    payer_name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    reference: Annotated[PlainText, StringConstraints(max_length=60)] | None = None
    bank_name: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    notes: Annotated[PlainText, StringConstraints(max_length=500)] | None = None
    matches: Annotated[list[MatchIn], Field(max_length=60)] | None = (
        None  # leave out to match oldest stages first
    )

    @model_validator(mode="after")
    def _rules(self) -> "ReceiptIn":
        if self.reference:
            self.reference = self.reference.strip().upper()
        if self.mode != ReceiptMode.cash and not self.reference:
            raise ValueError("Enter the cheque number, UTR or transaction reference")
        if (
            self.mode != ReceiptMode.cash
            and self.reference
            and re.sub(r"[^A-Z]", "", self.reference) in ("CASH", "BYCASH", "CASHPAYMENT", "INCASH")
        ):
            raise ValueError("This looks like a cash payment; choose Cash as the mode")
        if self.mode == ReceiptMode.cash and self.amount >= CASH_LIMIT:
            raise ValueError(
                "Cash of Rs 2,00,000 or more can't be accepted (Income-tax Act, section 269ST)"
            )
        if self.received_on > today():
            raise ValueError("The receipt date can't be in the future")
        return self


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    stage_seq: int | None
    charge_head: ChargeHead | None
    amount: int


class ReceiptOut(BaseModel):
    id: int
    receipt_no: str
    amount: int
    received_on: date
    mode: ReceiptMode
    source: FundSource
    payer_name: str | None
    reference: str | None
    bank_name: str | None
    notes: str | None
    from_booking: bool
    status: ReceiptStatus
    matched: int
    unapplied: int
    matches: list[MatchOut]
    recorded_by: UserBrief | None
    recorded_at: datetime
    confirmed_by: UserBrief | None
    confirmed_at: datetime | None
    void_reason: str | None
    voided_at: datetime | None
    can_match: bool = False
    can_confirm: bool = False
    can_bounce: bool = False
    can_reverse: bool = False


class StageRow(BaseModel):
    seq: int
    name: str
    due: str
    total: int
    paid: int
    outstanding: int
    is_due: bool


class HeadRow(BaseModel):
    head: ChargeHead
    label: str
    total: int
    paid: int
    outstanding: int


class ReceiptsOut(BaseModel):
    ledger_exists: bool
    receipts: list[ReceiptOut] = []
    stages: list[StageRow] = []
    other_charges: list[HeadRow] = []
    balances: ledger_svc.Balances | None = None
    can_record: bool = False


def rno(r: Receipt) -> str:
    return f"RCT-{r.id:05d}"


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _load(db: DbSession, case_id: int) -> tuple[Ledger | None, list[Receipt]]:
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case_id))
    receipts = list(
        await db.scalars(
            select(Receipt)
            .where(Receipt.case_id == case_id)
            .order_by(Receipt.received_on, Receipt.id)
        )
    )
    return ledger, receipts


async def summary(db: DbSession, case: PostSalesCase, user: User) -> ReceiptsOut:
    ledger, receipts = await _load(db, case.id)
    if ledger is None:
        return ReceiptsOut(ledger_exists=False)
    await db.refresh(ledger)
    pos = svc.position(ledger, receipts)
    t = today()
    users = {
        u.id: u
        for u in await db.scalars(
            select(User).where(
                User.id.in_(
                    {x for r in receipts for x in (r.recorded_by_id, r.confirmed_by_id) if x}
                )
            )
        )
    }
    brief = lambda uid: UserBrief.model_validate(users[uid]) if uid in users else None  # noqa: E731
    is_maker, is_checker = user.role in LEDGER_MAKERS, user.role in LEDGER_CHECKERS
    out = []
    for r in reversed(receipts):  # newest first
        matched = sum(a.amount for a in r.allocations)
        out.append(
            ReceiptOut(
                id=r.id,
                receipt_no=rno(r),
                amount=r.amount,
                received_on=r.received_on,
                mode=r.mode,
                source=r.source,
                payer_name=r.payer_name,
                reference=r.reference,
                bank_name=r.bank_name,
                notes=r.notes,
                from_booking=r.from_booking,
                status=r.status,
                matched=matched,
                unapplied=r.amount - matched if r.status == ReceiptStatus.confirmed else 0,
                matches=[MatchOut.model_validate(a) for a in r.allocations],
                recorded_by=brief(r.recorded_by_id),
                recorded_at=r.created_at,
                confirmed_by=brief(r.confirmed_by_id),
                confirmed_at=r.confirmed_at,
                void_reason=r.void_reason,
                voided_at=r.voided_at,
                can_match=is_maker and r.status == ReceiptStatus.recorded,
                can_confirm=is_checker
                and r.status == ReceiptStatus.recorded
                and r.recorded_by_id != user.id,
                can_bounce=is_checker
                and r.mode in BOUNCEABLE
                and r.status in (ReceiptStatus.recorded, ReceiptStatus.confirmed),
                can_reverse=is_checker
                and r.status in (ReceiptStatus.recorded, ReceiptStatus.confirmed),
            )
        )
    stages = []
    for i in sorted(ledger.schedule, key=lambda x: x.seq):
        paid = min(pos["paid_by_stage"].get(i.seq, 0), i.amount + i.gst)
        stages.append(
            StageRow(
                seq=i.seq,
                name=i.name,
                due=i.due_date.isoformat() if i.due_date else f"Milestone: {i.milestone}",
                total=i.amount + i.gst,
                paid=paid,
                outstanding=i.amount + i.gst - paid,
                is_due=ledger_svc.is_due(i, t),
            )
        )
    heads = [
        HeadRow(
            head=h,
            label=ledger_svc.HEAD_LABELS[h],
            total=tot,
            paid=pos["paid_by_head"].get(h, 0),
            outstanding=tot - pos["paid_by_head"].get(h, 0),
        )
        for h, tot in svc.head_totals(ledger).items()
    ]
    bal = ledger_svc.balances(
        ledger,
        received_own=pos["received_own"],
        loan_disbursed=pos["loan_disbursed"],
        today=t,
        paid_by_stage=pos["paid_by_stage"],
        paid_other=pos["paid_other"],
        pending=pos["pending"],
    )
    return ReceiptsOut(
        ledger_exists=True,
        receipts=out,
        stages=stages,
        other_charges=heads,
        balances=bal,
        can_record=is_maker,
    )


def _matches(
    ledger: Ledger,
    receipts: list[Receipt],
    amount: int,
    matches: list[MatchIn] | None,
    exclude_id: int | None,
) -> list[Allocation]:
    if matches is None:
        pairs = svc.auto_match(ledger, receipts, amount, exclude_id)
        return [Allocation(stage_seq=s, amount=a) for s, a in pairs]
    try:
        svc.check_match(
            ledger,
            receipts,
            amount,
            [(m.stage_seq, m.amount) for m in matches if m.stage_seq is not None],
            [(m.charge_head, m.amount) for m in matches if m.charge_head is not None],
            exclude_id,
        )
    except svc.MatchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return [
        Allocation(stage_seq=m.stage_seq, charge_head=m.charge_head, amount=m.amount)
        for m in matches
    ]


def _log(
    db: DbSession, case: PostSalesCase, user: User, action: str, request: Request, details: dict
) -> None:
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=action.replace("receipt_", "receipt."),
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


@router.get("", response_model=ReceiptsOut)
async def list_receipts(case_id: int, user: Viewer, db: DbSession) -> ReceiptsOut:
    return await summary(db, await _case(db, case_id), user)


@router.post("", response_model=ReceiptsOut, status_code=status.HTTP_201_CREATED)
async def record(
    case_id: int, body: ReceiptIn, request: Request, user: Maker, db: DbSession
) -> ReceiptsOut:
    case = await _case(db, case_id)
    ledger, receipts = await _load(db, case_id)
    if ledger is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Generate the ledger first")
    if body.received_on < case.booking.booking_date - timedelta(days=60):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The receipt date is long before the booking date; check it",
        )
    if body.source == FundSource.loan and not ledger.loan_sanctioned:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Record the sanctioned loan on the ledger before loan disbursements",
        )
    if body.reference and await db.scalar(
        select(Receipt.id).where(
            Receipt.mode == body.mode,
            func.upper(Receipt.reference) == body.reference,
            Receipt.status.in_([ReceiptStatus.recorded, ReceiptStatus.confirmed]),
        )
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A receipt with {body.mode.value.upper()} reference {body.reference} is already recorded",
        )
    r = Receipt(case_id=case.id, recorded_by_id=user.id, **body.model_dump(exclude={"matches"}))
    r.allocations = _matches(ledger, receipts, body.amount, body.matches, None)
    db.add(r)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That reference is already recorded"
        ) from None
    _log(
        db,
        case,
        user,
        "receipt_recorded",
        request,
        {"receipt": rno(r), "amount": r.amount, "mode": r.mode.value, "source": r.source.value},
    )
    await db.commit()
    return await summary(db, case, user)


async def _receipt(db: DbSession, case_id: int, rid: int) -> Receipt:
    r = await db.get(Receipt, rid)
    if r is None or r.case_id != case_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    return r


@router.put("/{rid}/matches", response_model=ReceiptsOut)
async def rematch(
    case_id: int,
    rid: int,
    body: Annotated[list[MatchIn], Field(max_length=60)],
    request: Request,
    user: Maker,
    db: DbSession,
) -> ReceiptsOut:
    """Change how a receipt is matched (only before it's confirmed). An empty list leaves it all unapplied."""
    case = await _case(db, case_id)
    r = await _receipt(db, case_id, rid)
    if r.status != ReceiptStatus.recorded:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a receipt waiting for confirmation can be re-matched",
        )
    ledger, receipts = await _load(db, case_id)
    r.allocations = _matches(ledger, receipts, r.amount, body, r.id)
    _log(
        db,
        case,
        user,
        "receipt_matched",
        request,
        {"receipt": rno(r), "matched": sum(m.amount for m in body)},
    )
    await db.commit()
    return await summary(db, case, user)


@router.post("/{rid}/confirm", response_model=ReceiptsOut)
async def confirm(
    case_id: int, rid: int, request: Request, user: Checker, db: DbSession
) -> ReceiptsOut:
    case = await _case(db, case_id)
    r = await _receipt(db, case_id, rid)
    if r.status != ReceiptStatus.recorded:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a receipt waiting for confirmation can be confirmed",
        )
    if r.recorded_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who recorded a receipt can't confirm it"
        )
    r.status, r.confirmed_by_id, r.confirmed_at = (
        ReceiptStatus.confirmed,
        user.id,
        datetime.now(UTC),
    )
    _log(db, case, user, "receipt_confirmed", request, {"receipt": rno(r), "amount": r.amount})
    await db.commit()
    return await summary(db, case, user)


async def _void(
    db: DbSession,
    case_id: int,
    rid: int,
    user: User,
    request: Request,
    reason: str,
    to: ReceiptStatus,
) -> ReceiptsOut:
    case = await _case(db, case_id)
    r = await _receipt(db, case_id, rid)
    if to == ReceiptStatus.bounced:
        if r.mode not in BOUNCEABLE:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Only cheques and demand drafts can bounce; reverse other receipts",
            )
        if r.status not in (ReceiptStatus.recorded, ReceiptStatus.confirmed):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "This receipt is already bounced or reversed"
            )
    elif r.status not in (ReceiptStatus.recorded, ReceiptStatus.confirmed):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This receipt is already bounced, reversed or rejected",
        )
    was = r.status
    r.status, r.void_reason, r.voided_by_id, r.voided_at = to, reason, user.id, datetime.now(UTC)
    _log(
        db,
        case,
        user,
        f"receipt_{to.value}",
        request,
        {"receipt": rno(r), "amount": r.amount, "was": was.value, "reason": reason},
    )
    await db.commit()
    return await summary(db, case, user)


@router.post("/{rid}/bounce", response_model=ReceiptsOut)
async def bounce(
    case_id: int, rid: int, body: ReasonIn, request: Request, user: Checker, db: DbSession
) -> ReceiptsOut:
    """Cheque or DD returned unpaid. The receipt stays on record; it no longer counts."""
    return await _void(db, case_id, rid, user, request, body.reason, ReceiptStatus.bounced)


@router.post("/{rid}/reverse", response_model=ReceiptsOut)
async def reverse(
    case_id: int, rid: int, body: ReasonIn, request: Request, user: Checker, db: DbSession
) -> ReceiptsOut:
    """A receipt entered in error: rejected before confirmation, or reversed after. It stays on record and no longer counts."""
    return await _void(db, case_id, rid, user, request, body.reason, ReceiptStatus.reversed)
