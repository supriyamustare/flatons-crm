"""Customer portal rules: who may see which case, the plain-language payment statuses, and the dashboard summary.

Payment statuses (the specification's list): No payment currently due, Upcoming payment, Payment due, Overdue payment,
Payment received - reconciliation pending, Payment confirmed, Payment under clarification, Refund under process.
"Overdue" is used only after the demand's contractual due date has passed with an amount still unpaid after confirmed
receipts (the same rule the ledger uses).
"""

from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models.agreement import Agreement, AgreementStatus
from app.models.cancellation import Cancellation
from app.models.ledger import Ledger
from app.models.payment import Receipt, ReceiptStatus
from app.models.postsales import CaseStatus, CustomerProfile, PostSalesCase
from app.models.ticket import Ticket, TicketCategory, TicketStatus
from app.services import ledger as ledger_svc
from app.services import payments

IST = timezone(timedelta(hours=5, minutes=30))
NONE_DUE, UPCOMING, DUE, OVERDUE = (
    "No payment currently due",
    "Upcoming payment",
    "Payment due",
    "Overdue payment",
)
PENDING, CONFIRMED, CLARIFY, REFUND = (
    "Payment received - reconciliation pending",
    "Payment confirmed",
    "Payment under clarification",
    "Refund under process",
)
NOT_YET = "Not yet demanded"
CLARIFY_CATEGORIES = (TicketCategory.payment, TicketCategory.demand, TicketCategory.receipt)
AGREEMENT_LABELS = {
    "initiated": "Being prepared",
    "data_verified": "Being prepared",
    "drafted": "Draft being reviewed internally",
    "internal_review": "Draft being reviewed internally",
    "changes_requested": "Draft being revised",
    "customer_review": "Shared with you for review",
    "execution_prep": "Preparing for signing and registration",
    "registered": "Registered",
    "final_uploaded": "Registered",
    "cancelled": "Cancelled",
}


def today() -> date:
    return datetime.now(UTC).astimezone(IST).date()


async def cases_for(db, email: str) -> list[PostSalesCase]:
    """Accepted cases whose customer profile has this email and recorded portal consent."""
    q = (
        select(PostSalesCase)
        .join(CustomerProfile, CustomerProfile.case_id == PostSalesCase.id)
        .where(
            func.lower(CustomerProfile.email) == email.lower(),
            CustomerProfile.consent_portal_at.is_not(None),
            PostSalesCase.status.in_([CaseStatus.accepted, CaseStatus.cancelled]),
        )
        .order_by(PostSalesCase.id)
    )
    return list(await db.scalars(q))


async def payments_view(db, case: PostSalesCase) -> dict:
    t = today()
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case.id))
    receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == case.id)))
    pending_amount = sum(r.amount for r in receipts if r.status == ReceiptStatus.recorded)
    clarify = bool(
        await db.scalar(
            select(Ticket.id).where(
                Ticket.case_id == case.id,
                Ticket.status != TicketStatus.closed,
                Ticket.category.in_(CLARIFY_CATEGORIES),
            )
        )
    )
    cancel = await db.scalar(
        select(Cancellation).where(
            Cancellation.case_id == case.id, Cancellation.status.notin_(["withdrawn", "rejected"])
        )
    )
    refund_pending = bool(
        cancel
        and (cancel.settlement or {}).get("refund", 0) > 0
        and not (cancel.refund_payment or {}).get("reconciled_by")
    )
    shown_receipts = [
        {
            "receipt_no": f"RCT-{r.id:05d}",
            "date": r.received_on,
            "amount": r.amount,
            "mode": r.mode.value,
            "status": CONFIRMED
            if r.status == ReceiptStatus.confirmed
            else PENDING
            if r.status == ReceiptStatus.recorded
            else CLARIFY,
        }
        for r in sorted(receipts, key=lambda x: (x.received_on, x.id))
        if r.status in (ReceiptStatus.confirmed, ReceiptStatus.recorded, ReceiptStatus.bounced)
    ]
    if ledger is None:
        return {
            "has_schedule": False,
            "receipts": shown_receipts,
            "headline": REFUND if refund_pending else NONE_DUE,
            "total_paid": sum(r.amount for r in receipts if r.status == ReceiptStatus.confirmed),
            "pending_reconciliation": pending_amount,
            "stages": [],
            "next_due": None,
        }
    pos = payments.position(ledger, receipts)
    bal = ledger_svc.balances(
        ledger,
        received_own=pos["received_own"],
        loan_disbursed=pos["loan_disbursed"],
        today=t,
        paid_by_stage=pos["paid_by_stage"],
        paid_other=pos["paid_other"],
        pending=pos["pending"],
    )
    paid, left_pending, stages = pos["paid_by_stage"], pending_amount, []
    for i in ledger.schedule:
        total = i.amount + i.gst
        got = paid.get(i.seq, 0)
        outstanding = max(0, total - got)
        if not ledger_svc.is_due(i, t):
            status = NOT_YET if outstanding else CONFIRMED
        elif outstanding == 0:
            status = CONFIRMED
        elif (
            left_pending > 0
        ):  # a payment received applies here but isn't confirmed yet: not 'due' until it is
            status, left_pending = PENDING, max(0, left_pending - outstanding)
        elif clarify:
            status = CLARIFY
        elif i.due_date and i.due_date < t:
            status = OVERDUE
        elif i.due_date and i.due_date == t:
            status = DUE
        else:
            status = UPCOMING
        stages.append(
            {
                "stage": i.name,
                "amount": total,
                "paid": got,
                "outstanding": outstanding,
                "demanded_on": i.demanded_on,
                "due_date": i.due_date,
                "status": status,
            }
        )
    order = [REFUND, OVERDUE, DUE, CLARIFY, PENDING, UPCOMING]
    present = {s["status"] for s in stages} | ({REFUND} if refund_pending else set())
    headline = next((s for s in order if s in present), NONE_DUE)
    due = [s for s in stages if s["status"] in (OVERDUE, DUE, UPCOMING, CLARIFY)]
    next_due = min(due, key=lambda s: s["due_date"] or t) if due else None
    upcoming_milestone = next((s["stage"] for s in stages if s["status"] == NOT_YET), None)
    return {
        "has_schedule": True,
        "headline": headline,
        "total_consideration": ledger_svc.totals(ledger).total_payable,
        "total_paid": bal.received,
        "pending_reconciliation": pending_amount,
        "outstanding": bal.total_outstanding,
        "stages": stages,
        "receipts": shown_receipts,
        "next_due": {
            "stage": next_due["stage"],
            "amount": next_due["outstanding"],
            "due_date": next_due["due_date"],
            "status": next_due["status"],
        }
        if next_due
        else None,
        "next_milestone": upcoming_milestone,
    }


async def agreement_view(db, case: PostSalesCase) -> dict:
    a = await db.scalar(
        select(Agreement)
        .where(Agreement.case_id == case.id, Agreement.status != AgreementStatus.cancelled)
        .order_by(Agreement.id.desc())
    )
    if a is None:
        return {
            "status": "Not started yet",
            "registration_no": None,
            "registered_on": None,
            "final_document_id": None,
        }
    from app.models.case_document import Approval, CaseDocument, Visibility

    final = None
    if a.final_document_id:
        d = await db.get(CaseDocument, a.final_document_id)
        final = (
            d.id
            if d and d.approval == Approval.released and d.visibility == Visibility.customer
            else None
        )
    return {
        "status": AGREEMENT_LABELS.get(a.status.value, a.status.value),
        "registration_no": a.registration_no
        if a.status.value in ("registered", "final_uploaded")
        else None,
        "registered_on": a.registered_on,
        "final_document_id": final,
    }
