from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import func, select

from app.api.cost_sheets import build as build_cost_sheet
from app.core.deps import DbSession, require_role
from app.models.inventory import Unit
from app.models.ledger import (
    ChargeHead,
    Ledger,
    LedgerCharge,
    LedgerStatus,
    ScheduleItem,
    TriggerType,
)
from app.models.payment import LIVE, Allocation, FundSource, Receipt, ReceiptMode
from app.models.postsales import CaseStatus, PostSalesCase
from app.models.user import LEDGER_CHECKERS, LEDGER_MAKERS, LEDGER_VIEWERS, Role, User
from app.schemas.common import PlainText
from app.schemas.user import UserBrief
from app.services import ledger as svc
from app.services import payments
from app.services import postsales as cases
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales/cases/{case_id}/ledger", tags=["ledger"])
Viewer = Annotated[User, Depends(require_role(*LEDGER_VIEWERS))]
Maker = Annotated[User, Depends(require_role(*LEDGER_MAKERS))]
Checker = Annotated[User, Depends(require_role(*LEDGER_CHECKERS))]
IST = timezone(timedelta(hours=5, minutes=30))
Name = Annotated[PlainText, StringConstraints(min_length=1, max_length=120)]
Money = Annotated[int, Field(ge=-1_000_000_000, le=1_000_000_000)]


class ChargeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    head: ChargeHead
    label: Name
    amount: Money

    @model_validator(mode="after")
    def _sign(self) -> "ChargeIn":
        if self.head == ChargeHead.discount and self.amount >= 0:
            raise ValueError("A discount must be a negative amount")
        if self.head != ChargeHead.discount and self.amount <= 0:
            raise ValueError(f"{self.label}: the amount must be more than zero")
        return self


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Name
    amount: Annotated[int, Field(ge=0, le=1_000_000_000)]
    gst: Annotated[int, Field(ge=0, le=100_000_000)] = 0
    trigger_type: TriggerType
    due_date: date | None = None
    milestone: Annotated[PlainText, StringConstraints(max_length=120)] | None = None

    @model_validator(mode="after")
    def _trigger(self) -> "ItemIn":
        if self.trigger_type == TriggerType.on_date and not self.due_date:
            raise ValueError(f"{self.name}: choose the due date")
        if self.trigger_type == TriggerType.on_milestone:
            self.due_date = None  # set when the milestone is verified
        return self


class FundingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    loan_sanctioned: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0
    lender: Annotated[PlainText, StringConstraints(max_length=150)] | None = None
    loan_reference: Annotated[PlainText, StringConstraints(max_length=80)] | None = None


class ReasonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Annotated[PlainText, StringConstraints(min_length=3, max_length=500)]


class ChargeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    head: ChargeHead
    label: str
    amount: int


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seq: int
    name: str
    amount: int
    gst: int
    trigger_type: TriggerType
    due_date: date | None
    milestone: str | None
    is_due: bool = False


class LedgerOut(BaseModel):
    exists: bool
    status: LedgerStatus | None = None
    version: int = 0
    gst_pct: float = 0
    loan_sanctioned: int = 0
    lender: str | None = None
    loan_reference: str | None = None
    note: str | None = None
    submitted_by: UserBrief | None = None
    submitted_at: datetime | None = None
    approved_by: UserBrief | None = None
    approved_at: datetime | None = None
    charges: list[ChargeOut] = []
    schedule: list[ItemOut] = []
    totals: svc.Totals | None = None
    balances: svc.Balances | None = None
    problems: list[str] = []
    can_edit: bool = False
    can_approve: bool = False
    head_labels: dict[str, str] = {}


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def _ledger(db: DbSession, case_id: int) -> Ledger | None:
    return await db.scalar(select(Ledger).where(Ledger.case_id == case_id))


async def _out(db: DbSession, case: PostSalesCase, ledger: Ledger | None, user: User) -> LedgerOut:
    labels = {h.value: lbl for h, lbl in svc.HEAD_LABELS.items()}
    if ledger is None:
        return LedgerOut(
            exists=False,
            can_edit=user.role in LEDGER_MAKERS and case.status == CaseStatus.accepted,
            head_labels=labels,
        )
    await db.refresh(ledger)
    t = today()
    users = {
        u.id: u
        for u in await db.scalars(
            select(User).where(
                User.id.in_([x for x in (ledger.submitted_by_id, ledger.approved_by_id) if x])
            )
        )
    }
    brief = lambda uid: UserBrief.model_validate(users[uid]) if uid in users else None  # noqa: E731
    return LedgerOut(
        exists=True,
        status=ledger.status,
        version=ledger.version,
        gst_pct=float(ledger.gst_pct),
        loan_sanctioned=ledger.loan_sanctioned,
        lender=ledger.lender,
        loan_reference=ledger.loan_reference,
        note=ledger.note,
        submitted_by=brief(ledger.submitted_by_id),
        submitted_at=ledger.submitted_at,
        approved_by=brief(ledger.approved_by_id),
        approved_at=ledger.approved_at,
        charges=[ChargeOut.model_validate(c) for c in ledger.charges],
        schedule=[
            ItemOut.model_validate(i).model_copy(update={"is_due": svc.is_due(i, t)})
            for i in ledger.schedule
        ],
        totals=svc.totals(ledger),
        balances=await _balances(db, ledger, t),
        problems=svc.problems(ledger),
        can_edit=user.role in LEDGER_MAKERS
        and ledger.status == LedgerStatus.draft
        and case.status == CaseStatus.accepted,
        can_approve=user.role in LEDGER_CHECKERS
        and ledger.status == LedgerStatus.pending_approval
        and ledger.submitted_by_id != user.id,
        head_labels=labels,
    )


async def _balances(db: DbSession, ledger: Ledger, t: date) -> svc.Balances:
    receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == ledger.case_id)))
    pos = payments.position(ledger, receipts)
    return svc.balances(
        ledger,
        received_own=pos["received_own"],
        loan_disbursed=pos["loan_disbursed"],
        today=t,
        paid_by_stage=pos["paid_by_stage"],
        paid_other=pos["paid_other"],
        pending=pos["pending"],
    )


async def _live_receipts(db: DbSession, case_id: int) -> list[Receipt]:
    return list(
        await db.scalars(
            select(Receipt).where(Receipt.case_id == case_id, Receipt.status.in_(LIVE))
        )
    )


def _draft(ledger: Ledger | None) -> Ledger:
    if ledger is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Generate the ledger first")
    if ledger.status != LedgerStatus.draft:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Only a draft ledger can be changed; ask a finance approver to reopen it",
        )
    return ledger


def _log(
    db: DbSession,
    case: PostSalesCase,
    user: User,
    action: str,
    request: Request,
    details: dict | None = None,
) -> None:
    cases.event(db, case, action, user, details)
    log_audit(
        db,
        action=f"ledger.{action.removeprefix('ledger_')}",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details=details,
        request=request,
    )


BOOKING_MODES = {
    "cheque": ReceiptMode.cheque,
    "bank_transfer": ReceiptMode.neft,
    "upi": ReceiptMode.upi,
    "card": ReceiptMode.card,
    "cash": ReceiptMode.cash,
    "other": ReceiptMode.other,
}


async def _booking_receipt(db: DbSession, case: PostSalesCase, ledger: Ledger, user: User) -> None:
    """The booking amount taken at booking becomes a receipt that finance must confirm like any other."""
    b = case.booking
    if b.booking_amount <= 0 or await db.scalar(
        select(Receipt.id).where(Receipt.case_id == case.id, Receipt.from_booking.is_(True))
    ):
        return
    mode = BOOKING_MODES.get(b.payment_mode.value if b.payment_mode else "other", ReceiptMode.other)
    note = "Booking amount recorded at booking"
    if mode == ReceiptMode.cash and b.booking_amount >= 200_000:
        mode, note = (
            ReceiptMode.other,
            "Booking amount was recorded as cash of Rs 2 lakh or more; check how it was actually paid",
        )
    reference = (b.payment_reference or "").strip().upper() or (
        None if mode == ReceiptMode.cash else f"BKG-{b.id:05d}"
    )
    if reference and await db.scalar(
        select(Receipt.id).where(
            Receipt.mode == mode,
            func.upper(Receipt.reference) == reference,
            Receipt.status.in_(LIVE),
        )
    ):
        reference = f"BKG-{b.id:05d}"
    r = Receipt(
        case_id=case.id,
        amount=b.booking_amount,
        received_on=b.booking_date,
        mode=mode,
        source=FundSource.own,
        payer_name=b.customer_name or b.lead.name,
        reference=reference,
        notes=note,
        from_booking=True,
        recorded_by_id=user.id,
    )
    r.allocations = [
        Allocation(stage_seq=seq, amount=amt)
        for seq, amt in payments.auto_match(ledger, [], b.booking_amount)
    ]
    db.add(r)


@router.get("", response_model=LedgerOut)
async def get_ledger(case_id: int, user: Viewer, db: DbSession) -> LedgerOut:
    case = await _case(db, case_id)
    return await _out(db, case, await _ledger(db, case_id), user)


@router.post("/generate", response_model=LedgerOut, status_code=status.HTTP_201_CREATED)
async def generate(case_id: int, request: Request, user: Maker, db: DbSession) -> LedgerOut:
    """Build a draft from the unit's cost sheet: agreed price, GST, statutory and other charges, and the project's payment stages."""
    case = await _case(db, case_id)
    if case.status != CaseStatus.accepted:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Accept the handover first")
    ledger = await _ledger(db, case_id)
    if ledger is not None and ledger.status != LedgerStatus.draft:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "This ledger is already submitted or approved"
        )
    sheet = await build_cost_sheet(db, await db.get(Unit, case.booking.unit_id))
    if not sheet.stages:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The project has no payment stages; set them in Cost sheet settings",
        )
    if ledger is None:
        ledger = Ledger(case_id=case.id)
        db.add(ledger)
    ledger.gst_pct = sheet.gst_pct
    if (
        case.booking.payment_preference
        and case.booking.payment_preference.value == "bank"
        and case.booking.bank_name
        and not ledger.lender
    ):
        ledger.lender = case.booking.bank_name
    ledger.charges = [
        LedgerCharge(head=h, label=svc.HEAD_LABELS[h], amount=a, sort_order=i)
        for i, (h, a) in enumerate(
            [
                (ChargeHead.base_price, sheet.cost),
                (ChargeHead.gst, sheet.gst),
                (ChargeHead.stamp_duty, sheet.stamp_duty),
                (ChargeHead.registration, sheet.registration),
                (ChargeHead.legal, sheet.legal_charges),
                (ChargeHead.furnishing, sheet.furnishing),
                (ChargeHead.other, sheet.other_charges),
            ]
        )
        if a > 0
    ]
    items = []
    for n, st in enumerate(sheet.stages):
        first = n == 0
        items.append(
            ScheduleItem(
                seq=n + 1,
                name=st.name,
                amount=st.amount,
                gst=st.gst,
                trigger_type=TriggerType.on_booking if first else TriggerType.on_milestone,
                due_date=case.booking.booking_date if first else None,
                demanded_on=case.booking.booking_date if first else None,
                milestone=None if first else st.name,
            )
        )
    ledger.schedule = items
    await db.flush()
    await _booking_receipt(db, case, ledger, user)
    _log(
        db,
        case,
        user,
        "ledger_generated",
        request,
        {"agreement_value": sheet.cost, "stages": len(items)},
    )
    await db.commit()
    return await _out(db, case, ledger, user)


@router.put("/charges", response_model=LedgerOut)
async def put_charges(
    case_id: int,
    body: Annotated[list[ChargeIn], Field(min_length=1, max_length=30)],
    request: Request,
    user: Maker,
    db: DbSession,
) -> LedgerOut:
    case = await _case(db, case_id)
    ledger = _draft(await _ledger(db, case_id))
    new_totals: dict = {}
    for c in body:
        new_totals[c.head] = new_totals.get(c.head, 0) + c.amount
    try:
        payments.charges_fit(new_totals, await _live_receipts(db, case_id))
    except payments.MatchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    before = {c.label: c.amount for c in ledger.charges}
    ledger.charges = [
        LedgerCharge(head=c.head, label=c.label, amount=c.amount, sort_order=i)
        for i, c in enumerate(body)
    ]
    await db.flush()
    _log(
        db,
        case,
        user,
        "ledger_charges",
        request,
        {"from": before, "to": {c.label: c.amount for c in body}},
    )
    await db.commit()
    return await _out(db, case, ledger, user)


@router.put("/schedule", response_model=LedgerOut)
async def put_schedule(
    case_id: int,
    body: Annotated[list[ItemIn], Field(min_length=1, max_length=60)],
    request: Request,
    user: Maker,
    db: DbSession,
) -> LedgerOut:
    case = await _case(db, case_id)
    ledger = _draft(await _ledger(db, case_id))
    try:
        payments.schedule_fits(
            [(i + 1, x.name, x.amount + x.gst) for i, x in enumerate(body)],
            await _live_receipts(db, case_id),
        )
    except payments.MatchError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    # Keep demand/due dates already set for milestone stages (by milestone name)
    known = {
        (x.milestone or "").strip().lower(): (x.demanded_on, x.due_date)
        for x in ledger.schedule
        if x.trigger_type == TriggerType.on_milestone and x.demanded_on
    }
    items = []
    for n, x in enumerate(body):
        if x.trigger_type == TriggerType.on_booking:
            dem, due = case.booking.booking_date, case.booking.booking_date
        elif x.trigger_type == TriggerType.on_date:
            dem, due = x.due_date, x.due_date
        else:
            dem, due = known.get((x.milestone or "").strip().lower(), (None, None))
        items.append(
            ScheduleItem(
                seq=n + 1,
                name=x.name,
                amount=x.amount,
                gst=x.gst,
                trigger_type=x.trigger_type,
                due_date=due,
                demanded_on=dem,
                milestone=x.milestone if x.trigger_type == TriggerType.on_milestone else None,
            )
        )
    ledger.schedule = items
    await db.flush()
    _log(
        db,
        case,
        user,
        "ledger_schedule",
        request,
        {"stages": len(body), "total": sum(x.amount for x in body)},
    )
    await db.commit()
    return await _out(db, case, ledger, user)


@router.put("/funding", response_model=LedgerOut)
async def put_funding(
    case_id: int, body: FundingIn, request: Request, user: Maker, db: DbSession
) -> LedgerOut:
    case = await _case(db, case_id)
    ledger = _draft(await _ledger(db, case_id))
    ledger.loan_sanctioned, ledger.lender, ledger.loan_reference = (
        body.loan_sanctioned,
        body.lender,
        body.loan_reference,
    )
    _log(db, case, user, "ledger_funding", request, body.model_dump())
    await db.commit()
    return await _out(db, case, ledger, user)


@router.post("/submit", response_model=LedgerOut)
async def submit(case_id: int, request: Request, user: Maker, db: DbSession) -> LedgerOut:
    case = await _case(db, case_id)
    ledger = _draft(await _ledger(db, case_id))
    issues = svc.problems(ledger)
    if issues:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Can't submit yet: " + "; ".join(issues)
        )
    ledger.status, ledger.submitted_by_id, ledger.submitted_at, ledger.note = (
        LedgerStatus.pending_approval,
        user.id,
        datetime.now(UTC),
        None,
    )
    _log(db, case, user, "ledger_submitted", request, {"version": ledger.version})
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.finance_approver, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="ledger_approval",
            title=f"Ledger to approve: {case.booking.lead.name}",
            body=f"{cases.code(case)} ledger (version {ledger.version}) is waiting for approval",
            link=f"/post-sales/{case.id}",
        )
    await db.commit()
    return await _out(db, case, ledger, user)


async def _pending(db: DbSession, case_id: int, user: User) -> Ledger:
    ledger = await _ledger(db, case_id)
    if ledger is None or ledger.status != LedgerStatus.pending_approval:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing is waiting for approval"
        )
    if ledger.submitted_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The person who submitted the ledger can't approve it"
        )
    return ledger


@router.post("/approve", response_model=LedgerOut)
async def approve(case_id: int, request: Request, user: Checker, db: DbSession) -> LedgerOut:
    case = await _case(db, case_id)
    ledger = await _pending(db, case_id, user)
    issues = svc.problems(ledger)
    if issues:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Can't approve: " + "; ".join(issues)
        )
    ledger.status, ledger.approved_by_id, ledger.approved_at = (
        LedgerStatus.approved,
        user.id,
        datetime.now(UTC),
    )
    _log(
        db,
        case,
        user,
        "ledger_approved",
        request,
        {"version": ledger.version, "total_payable": svc.totals(ledger).total_payable},
    )
    if ledger.submitted_by_id:
        notify(
            db,
            user_id=ledger.submitted_by_id,
            type="ledger_approved",
            title=f"Ledger approved: {case.booking.lead.name}",
            body=f"{cases.code(case)} version {ledger.version}",
            link=f"/post-sales/{case.id}",
        )
    await db.commit()
    return await _out(db, case, ledger, user)


@router.post("/return", response_model=LedgerOut)
async def return_ledger(
    case_id: int, body: ReasonIn, request: Request, user: Checker, db: DbSession
) -> LedgerOut:
    case = await _case(db, case_id)
    ledger = await _pending(db, case_id, user)
    ledger.status, ledger.note = LedgerStatus.draft, body.reason
    _log(db, case, user, "ledger_returned", request, {"reason": body.reason})
    if ledger.submitted_by_id:
        notify(
            db,
            user_id=ledger.submitted_by_id,
            type="ledger_returned",
            title=f"Ledger returned: {case.booking.lead.name}",
            body=body.reason,
            link=f"/post-sales/{case.id}",
        )
    await db.commit()
    return await _out(db, case, ledger, user)


@router.post("/reopen", response_model=LedgerOut)
async def reopen(
    case_id: int, body: ReasonIn, request: Request, user: Checker, db: DbSession
) -> LedgerOut:
    """An approved ledger needs changing: back to draft as a new version (the reason is recorded)."""
    case = await _case(db, case_id)
    ledger = await _ledger(db, case_id)
    if ledger is None or ledger.status != LedgerStatus.approved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Only an approved ledger can be reopened"
        )
    ledger.status, ledger.version, ledger.note = LedgerStatus.draft, ledger.version + 1, body.reason
    ledger.approved_by_id = ledger.approved_at = ledger.submitted_by_id = ledger.submitted_at = None
    _log(
        db,
        case,
        user,
        "ledger_reopened",
        request,
        {"reason": body.reason, "new_version": ledger.version},
    )
    await db.commit()
    return await _out(db, case, ledger, user)
