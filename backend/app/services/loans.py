"""Loan stage (worked out from what's recorded) and the daily loan reminders."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.loan import Disbursement, DisbursementStatus, Loan, VerificationState
from app.models.payment import Receipt, ReceiptStatus
from app.models.postsales import PostSalesCase
from app.models.user import Role, User

STAGES = [
    "details_captured",
    "documents_requested",
    "documents_submitted",
    "bank_review",
    "disbursement_requested",
    "disbursement_awaited",
    "funds_received",
    "reconciled",
]
LABELS = {
    "details_captured": "Loan details captured",
    "documents_requested": "Documents requested",
    "documents_submitted": "Documents submitted",
    "bank_review": "Bank review",
    "disbursement_requested": "Disbursement requested",
    "disbursement_awaited": "Disbursement awaited",
    "funds_received": "Funds received",
    "reconciled": "Reconciled",
}
SANCTION_WARNING_DAYS = 15


def disbursement_state(d: Disbursement, receipts: dict[int, Receipt]) -> str:
    if d.status == DisbursementStatus.received:
        r = receipts.get(d.receipt_id) if d.receipt_id else None
        return (
            "reconciled"
            if r is not None and r.status == ReceiptStatus.confirmed
            else "funds_received"
        )
    return {
        DisbursementStatus.requested: "disbursement_requested",
        DisbursementStatus.awaited: "disbursement_awaited",
    }.get(d.status, "cancelled")


def stage(loan: Loan, receipts: dict[int, Receipt]) -> str:
    live = [d for d in loan.disbursements if d.status != DisbursementStatus.cancelled]
    if live:
        return disbursement_state(
            live[-1], receipts
        )  # the latest disbursement shows where things stand
    if (
        loan.technical_status != VerificationState.not_started
        or loan.legal_status != VerificationState.not_started
        or loan.sanctioned_amount
    ):
        return "bank_review"
    if loan.doc_requests:
        return (
            "documents_submitted"
            if all(r.submitted_on for r in loan.doc_requests)
            else "documents_requested"
        )
    return "details_captured"


def is_delayed(d: Disbursement, today: date) -> bool:
    return (
        d.status in (DisbursementStatus.requested, DisbursementStatus.awaited)
        and d.expected_date is not None
        and d.expected_date < today
    )


async def run_loan_reminders(db: AsyncSession, today: date, send) -> dict:
    """`send(user_ids, type=, title=, body=, link=)` is the shared once-a-day notifier from the payment reminders."""
    counts = {"loan_delays": 0, "loan_follow_ups": 0, "sanction_expiring": 0}
    crm = list(
        await db.scalars(
            select(User.id).where(User.is_active.is_(True), User.role == Role.crm_manager)
        )
    )
    for loan in await db.scalars(select(Loan).where(Loan.closed_at.is_(None))):
        case = await db.get(PostSalesCase, loan.case_id)
        if case is None:
            continue
        who = [loan.owner_id or case.owner_id] if (loan.owner_id or case.owner_id) else crm
        name, link = case.booking.lead.name, f"/post-sales/{case.id}"
        for d in loan.disbursements:
            if is_delayed(d, today) and d.delay_notified_on != today:
                days = (today - d.expected_date).days
                counts["loan_delays"] += await send(
                    who + (crm if days >= 7 else []),
                    type="loan_disbursement_delayed",
                    title=f"Loan disbursement delayed {days} day{'s' if days > 1 else ''}: {name}",
                    body=f"{loan.lender}: Rs {d.expected_amount:,} expected {d.expected_date.isoformat()}"
                    + (f" ({d.delay_reason})" if d.delay_reason else ""),
                    link=link,
                )
                d.delay_notified_on = today
        if loan.next_follow_up_on == today:
            counts["loan_follow_ups"] += await send(
                who,
                type="loan_follow_up_due",
                title=f"Loan follow-up today: {name}",
                body=loan.lender,
                link=link,
            )
        if (
            loan.sanction_valid_until
            and today <= loan.sanction_valid_until <= today + timedelta(days=SANCTION_WARNING_DAYS)
            and (loan.sanction_valid_until - today).days in (SANCTION_WARNING_DAYS, 7, 1)
        ):
            counts["sanction_expiring"] += await send(
                who,
                type="loan_sanction_expiring",
                title=f"Loan sanction expires {loan.sanction_valid_until.isoformat()}: {name}",
                body=f"{loan.lender}: renew the sanction or complete disbursement",
                link=link,
            )
    return counts
