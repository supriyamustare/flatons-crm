"""The OCR tab: own contribution required vs the home loan, stage by stage."""

from datetime import UTC, date, datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import select

from app.core.deps import DbSession, require_role
from app.models.funding import FundingPlan
from app.models.ledger import Ledger
from app.models.loan import Loan
from app.models.payment import FundSource, Receipt, ReceiptStatus
from app.models.postsales import PostSalesCase
from app.models.user import POSTSALES_ROLES, Role, User
from app.schemas.common import PlainText
from app.services import ledger as ledger_svc
from app.services import payments
from app.services import postsales as cases
from app.services.audit import log_audit
from app.services.notifications import notify

router = APIRouter(prefix="/post-sales/cases/{case_id}/ocr", tags=["ocr"])
Viewer = Annotated[User, Depends(require_role(*POSTSALES_ROLES))]
MAKERS = (Role.admin, Role.crm_manager, Role.postsales_exec, Role.finance)
CHECKERS = (Role.admin, Role.finance_approver)
IST = timezone(timedelta(hours=5, minutes=30))


class PlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    own_amount: Annotated[int, Field(gt=0, le=10_000_000_000)]
    note: Annotated[PlainText, StringConstraints(max_length=500)] | None = None
    reason: Annotated[PlainText, StringConstraints(max_length=500)] | None = (
        None  # required when changing an approved plan
    )


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


async def _case(db: DbSession, case_id: int) -> PostSalesCase:
    case = await db.get(PostSalesCase, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


async def state(db: DbSession, case: PostSalesCase, user: User) -> dict:
    t = today()
    plan = await db.get(FundingPlan, case.id)
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    loan = await db.scalar(select(Loan).where(Loan.case_id == case.id, Loan.closed_at.is_(None)))
    receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
    own_r = [r for r in receipts if r.source == FundSource.own]
    received_own = sum(r.amount for r in own_r if r.status == ReceiptStatus.confirmed)
    pending_own = sum(r.amount for r in own_r if r.status == ReceiptStatus.recorded)
    total = ledger_svc.totals(ledger).total_payable if ledger else None
    sanctioned = loan.sanctioned_amount if loan and loan.sanctioned_amount else None
    out = {
        "plan": None,
        "total_payable": total,
        "charges_own": None,
        "loan_needed": None,
        "sanctioned": sanctioned,
        "lender": loan.lender if loan else None,
        "shortfall": 0,
        "own_required": None,
        "received_own": received_own,
        "pending_own": pending_own,
        "remaining_own": None,
        "own_due_now": 0,
        "own_overdue": 0,
        "stages": [],
        "receipts": [
            {
                "receipt_no": f"RCT-{r.id:05d}",
                "date": r.received_on,
                "amount": r.amount,
                "mode": r.mode.value,
                "status": r.status.value,
            }
            for r in sorted(own_r, key=lambda x: (x.received_on, x.id))
            if r.status in (ReceiptStatus.confirmed, ReceiptStatus.recorded)
        ],
        "warnings": [],
        "can_edit": user.role in MAKERS,
        "can_approve": False,
    }
    if plan is None:
        if total is None:
            out["warnings"].append(
                "Generate the ledger first: the own contribution is worked out against the total payable."
            )
        return out
    users = {
        u.id: u.full_name
        for u in await db.scalars(
            select(User).where(
                User.id.in_([x for x in (plan.entered_by_id, plan.approved_by_id) if x])
            )
        )
    }
    out["plan"] = {
        "own_amount": plan.own_amount,
        "note": plan.note,
        "status": plan.status,
        "entered_by": users.get(plan.entered_by_id),
        "approved_by": users.get(plan.approved_by_id),
        "approved_at": plan.approved_at,
        "history": plan.history,
    }
    out["can_approve"] = (
        plan.status == "draft" and user.role in CHECKERS and plan.entered_by_id != user.id
    )
    if total is None:
        out["warnings"].append(
            "Generate the ledger to see the loan needed and the stage-by-stage split."
        )
        return out
    t_ = ledger_svc.totals(ledger)
    funded = t_.schedule_amount + t_.schedule_gst  # agreement value + GST: what the bank can fund
    out["charges_own"] = max(
        0, total - funded
    )  # stamp duty, registration and other charges: paid by the customer, not the loan
    loan_needed = max(0, funded - plan.own_amount)
    shortfall = max(0, loan_needed - sanctioned) if sanctioned is not None else 0
    own_required = (
        plan.own_amount + shortfall
    )  # if the bank approves less, the customer pays the difference
    out.update(
        {
            "loan_needed": loan_needed,
            "shortfall": shortfall,
            "own_required": own_required,
            "remaining_own": max(0, own_required - received_own),
        }
    )
    if sanctioned is not None and shortfall:
        out["warnings"].append(
            f"The bank approved Rs {sanctioned:,} but the loan needed is Rs {loan_needed:,}: the customer must pay the Rs {shortfall:,} difference from own funds."
        )
    if sanctioned is not None and sanctioned > loan_needed:
        out["warnings"].append(
            f"The bank approved Rs {sanctioned:,}, more than the Rs {loan_needed:,} needed under this plan: check the own contribution amount."
        )
    if plan.status != "approved":
        out["warnings"].append("This plan is waiting for a finance approver.")
    # Stage split: the customer's own share is paid first, from the earliest stages; the loan pays the rest
    paid = payments.position(ledger, receipts)["paid_by_stage"]
    left = own_required
    for i in ledger.schedule:
        amt = i.amount + i.gst
        own_part = min(amt, left)
        left -= own_part
        due = ledger_svc.is_due(i, t)
        own_paid = min(own_part, paid.get(i.seq, 0))
        own_open = own_part - own_paid if due else 0
        out["stages"].append(
            {
                "stage": i.name,
                "amount": amt,
                "own_part": own_part,
                "loan_part": amt - own_part,
                "due_date": i.due_date,
                "demanded": due,
                "own_outstanding": own_open,
                "overdue": bool(own_open and i.due_date and i.due_date < t),
            }
        )
        out["own_due_now"] += own_open
        out["own_overdue"] += own_open if i.due_date and i.due_date < t else 0
    return out


@router.get("")
async def get_ocr(case_id: int, user: Viewer, db: DbSession) -> dict:
    return await state(db, await _case(db, case_id), user)


@router.put("")
async def set_plan(
    case_id: int, body: PlanIn, request: Request, user: Viewer, db: DbSession
) -> dict:
    """Set or change the own contribution (a fixed amount). Changing an approved plan needs a reason and a new approval."""
    if user.role not in MAKERS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Post-sales, CRM managers or finance set the own contribution",
        )
    case = await _case(db, case_id)
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    if ledger is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Generate the ledger first")
    t_ = ledger_svc.totals(ledger)
    funded = t_.schedule_amount + t_.schedule_gst
    if body.own_amount > funded:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"The own contribution can't be more than the agreement value with GST (Rs {funded:,})",
        )
    plan = await db.get(FundingPlan, case.id)
    if plan is None:
        plan = FundingPlan(
            case_id=case.id,
            own_amount=body.own_amount,
            note=body.note,
            status="draft",
            entered_by_id=user.id,
            history=[],
        )
        db.add(plan)
    else:
        if plan.status == "approved":
            if not (body.reason or "").strip() or len(body.reason.strip()) < 3:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "Give the reason for changing the approved own contribution",
                )
            plan.history = [
                *plan.history,
                {
                    "own_amount": plan.own_amount,
                    "approved_at": plan.approved_at.isoformat() if plan.approved_at else None,
                    "changed_by": user.full_name,
                    "changed_at": datetime.now(UTC).isoformat(),
                    "reason": body.reason.strip(),
                },
            ]
        (
            plan.own_amount,
            plan.note,
            plan.status,
            plan.entered_by_id,
            plan.approved_by_id,
            plan.approved_at,
        ) = body.own_amount, body.note, "draft", user.id, None, None
    cases.event(db, case, "ocr_set", user, {"own_amount": body.own_amount, "reason": body.reason})
    log_audit(
        db,
        action="ocr.set",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"own_amount": body.own_amount, "reason": body.reason},
        request=request,
    )
    for uid in await db.scalars(
        select(User.id).where(
            User.is_active.is_(True), User.role == Role.finance_approver, User.id != user.id
        )
    ):
        notify(
            db,
            user_id=uid,
            type="ocr_approval",
            title=f"Own contribution to approve: {case.booking.lead.name}",
            body=f"Rs {body.own_amount:,}",
            link=f"/post-sales/{case.id}?tab=ocr",
        )
    await db.commit()
    return await state(db, case, user)


@router.post("/approve")
async def approve(case_id: int, request: Request, user: Viewer, db: DbSession) -> dict:
    if user.role not in CHECKERS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "A finance approver approves the own contribution"
        )
    case = await _case(db, case_id)
    plan = await db.get(FundingPlan, case.id)
    if plan is None or plan.status != "draft":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Nothing is waiting for approval"
        )
    if plan.entered_by_id == user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The person who entered the own contribution can't approve it",
        )
    plan.status, plan.approved_by_id, plan.approved_at = "approved", user.id, datetime.now(UTC)
    cases.event(db, case, "ocr_approved", user, {"own_amount": plan.own_amount})
    log_audit(
        db,
        action="ocr.approved",
        entity_type="postsales_case",
        entity_id=case.id,
        actor=user,
        details={"own_amount": plan.own_amount},
        request=request,
    )
    await db.commit()
    return await state(db, case, user)
