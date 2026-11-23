"""Promises to pay and the daily payment reminders.

A promise is **kept** when confirmed receipts recorded after the promise was made, and dated no later than the
promise date, add up to the promised amount; **broken** once the promise date has passed without that; **open** until then.

Daily reminders (run at 09:00 India time) go to the case owner, or to CRM managers if the case has no owner:
issued demands due in 3 days or today, and overdue by 1, 7, 15 and 30 days (CRM managers too from 15 days);
broken promises (owner and CRM managers, once); follow-ups due today (whoever logged it, or the owner)."""

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demand import Demand, DemandStatus
from app.models.followup import FollowUpOutcome, PaymentFollowUp
from app.models.ledger import Ledger
from app.models.notification import Notification
from app.models.payment import Receipt, ReceiptStatus
from app.models.postsales import PostSalesCase
from app.models.user import Role, User
from app.services import payments
from app.services import postsales as cases
from app.services.notifications import notify

OVERDUE_STEPS = (1, 7, 15, 30)
ESCALATE_FROM = 15


def promise_status(fu: PaymentFollowUp, receipts: list[Receipt], today: date) -> str | None:
    if fu.outcome != FollowUpOutcome.promised:
        return None
    paid = sum(
        r.amount
        for r in receipts
        if r.status == ReceiptStatus.confirmed
        and r.received_on <= fu.promise_date
        # only money recorded after the promise was made counts towards keeping it
        and (fu.created_at is None or r.created_at >= fu.created_at)
    )
    if paid >= fu.promise_amount:
        return "kept"
    return "broken" if fu.promise_date < today else "open"


async def _crm_managers(db: AsyncSession) -> list[int]:
    return list(
        await db.scalars(
            select(User.id).where(User.is_active.is_(True), User.role == Role.crm_manager)
        )
    )


async def _send(
    db: AsyncSession,
    sent: set,
    user_ids,
    *,
    type: str,
    title: str,
    body: str,
    link: str,
    today: date,
) -> int:
    """Notify each user once for the same message within 20 hours (safe if the job runs twice)."""
    n = 0
    start = datetime.now(UTC) - timedelta(
        hours=20
    )  # a second run the same morning sends nothing; tomorrow's run still does
    for uid in {u for u in user_ids if u}:
        key = (uid, type, link, title)
        if key in sent:
            continue
        sent.add(key)
        if await db.scalar(
            select(Notification.id).where(
                Notification.user_id == uid,
                Notification.type == type,
                Notification.link == link,
                Notification.title == title,
                Notification.created_at >= start,
            )
        ):
            continue
        notify(db, user_id=uid, type=type, title=title, body=body, link=link)
        n += 1
    return n


async def run_reminders(db: AsyncSession, today: date) -> dict:
    counts = {
        "due_soon": 0,
        "due_today": 0,
        "overdue": 0,
        "broken_promises": 0,
        "follow_ups_due": 0,
    }
    sent: set = set()
    crm = await _crm_managers(db)
    issued = list(await db.scalars(select(Demand).where(Demand.status == DemandStatus.issued)))
    for d in issued:
        case = await db.get(PostSalesCase, d.case_id)
        ledger = await db.scalar(select(Ledger).where(Ledger.case_id == d.case_id))
        if case is None or ledger is None:
            continue
        receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == d.case_id)))
        paid = payments.position(ledger, receipts)["paid_by_stage"].get(d.stage_seq, 0)
        item = next((i for i in ledger.schedule if i.seq == d.stage_seq), None)
        unpaid = max(0, (item.amount + item.gst - paid) if item else 0)
        if unpaid <= 0:
            continue
        who = [case.owner_id] if case.owner_id else crm
        name, link, code = (
            case.booking.lead.name,
            f"/post-sales/{case.id}?tab=demands",
            f"DMD-{d.id:05d}",
        )
        days = (today - d.due_date).days
        if days == -3:
            counts["due_soon"] += await _send(
                db,
                sent,
                who,
                type="demand_due_soon",
                title=f"Payment due in 3 days: {name}",
                body=f"{code} {d.stage_name}: Rs {unpaid:,} due {d.due_date.isoformat()}",
                link=link,
                today=today,
            )
        elif days == 0:
            counts["due_today"] += await _send(
                db,
                sent,
                who,
                type="demand_due_today",
                title=f"Payment due today: {name}",
                body=f"{code} {d.stage_name}: Rs {unpaid:,}",
                link=link,
                today=today,
            )
        elif days in OVERDUE_STEPS:
            targets = who + (crm if days >= ESCALATE_FROM else [])
            counts["overdue"] += await _send(
                db,
                sent,
                targets,
                type="demand_overdue",
                title=f"Overdue {days} day{'s' if days > 1 else ''}: {name}",
                body=f"{code} {d.stage_name}: Rs {unpaid:,} was due {d.due_date.isoformat()}",
                link=link,
                today=today,
            )
    # Broken promises (once each) and follow-ups due today
    for fu in await db.scalars(
        select(PaymentFollowUp).where(
            PaymentFollowUp.outcome == FollowUpOutcome.promised,
            PaymentFollowUp.promise_date < today,
            PaymentFollowUp.broken_notified_at.is_(None),
        )
    ):
        receipts = list(await db.scalars(select(Receipt).where(Receipt.case_id == fu.case_id)))
        status = promise_status(fu, receipts, today)
        case = await db.get(PostSalesCase, fu.case_id)
        if status == "broken" and case is not None:
            counts["broken_promises"] += await _send(
                db,
                sent,
                [case.owner_id, fu.by_id, *crm],
                type="promise_broken",
                title=f"Promise to pay broken: {case.booking.lead.name}",
                body=f"Rs {fu.promise_amount:,} was promised by {fu.promise_date.isoformat()}",
                link=f"/post-sales/{case.id}?tab=followups",
                today=today,
            )
            fu.broken_notified_at = datetime.now(UTC)
            cases.event(
                db,
                case,
                "promise_broken",
                None,
                {"amount": fu.promise_amount, "promise_date": fu.promise_date.isoformat()},
            )
        elif status == "kept":
            fu.broken_notified_at = datetime.now(UTC)  # settled; nothing more to check
    for fu in await db.scalars(
        select(PaymentFollowUp).where(PaymentFollowUp.next_follow_up_on == today)
    ):
        case = await db.get(PostSalesCase, fu.case_id)
        if case is not None:
            counts["follow_ups_due"] += await _send(
                db,
                sent,
                [fu.by_id or case.owner_id],
                type="payment_follow_up_due",
                title=f"Follow up today: {case.booking.lead.name}",
                body=(fu.note or "")[:200],
                link=f"/post-sales/{case.id}?tab=followups",
                today=today,
            )
    from app.services.loans import run_loan_reminders

    async def send(user_ids, *, type: str, title: str, body: str, link: str) -> int:
        return await _send(
            db, sent, user_ids, type=type, title=title, body=body, link=link, today=today
        )

    counts |= await run_loan_reminders(db, today, send)
    from app.services.appointments import run_appointment_reminders

    counts |= await run_appointment_reminders(db, today, send)
    from app.services.possession import run_snag_reminders

    counts |= await run_snag_reminders(db, today, send)
    return counts
