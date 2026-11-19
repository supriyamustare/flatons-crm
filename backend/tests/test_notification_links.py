from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, PostSalesCase, Role
from app.services.followups import run_reminders
from tests import test_ledger
from tests.test_followups import issued_demand
from tests.test_ledger import TODAY, generated

case = test_ledger.case


async def links(db, kind):
    return list(await db.scalars(select(Notification.link).where(Notification.type == kind)))


async def test_each_notification_opens_its_tab(login_as, db, case):
    fin, _, _ = await generated(login_as, case)
    _, approver = await login_as(Role.finance_approver)
    await fin.post(f"/api/post-sales/cases/{case}/ledger/submit")
    assert await links(db, "ledger_approval") == [f"/post-sales/{case}?tab=ledger"]
    assert all(
        link.endswith("?tab=handover") for link in await links(db, "handover")
    )  # new handover when booked


async def test_reminders_open_their_tab(login_as, db, case):
    _, _, d = await issued_demand(login_as, db, case)
    pse, owner = await login_as(Role.postsales_exec)
    c = await db.get(PostSalesCase, case)
    c.owner_id = owner.id
    await db.commit()
    await pse.post(
        f"/api/post-sales/cases/{case}/follow-ups",
        json={"channel": "call", "outcome": "reached", "next_follow_up_on": TODAY.isoformat()},
    )
    await pse.post(
        f"/api/post-sales/cases/{case}/loan",
        json={"lender": "HDFC Bank", "next_follow_up_on": TODAY.isoformat()},
    )
    await run_reminders(db, d.due_date + timedelta(days=1))
    await run_reminders(db, TODAY)
    await db.commit()
    assert await links(db, "demand_overdue") == [f"/post-sales/{case}?tab=demands"]
    assert await links(db, "payment_follow_up_due") == [f"/post-sales/{case}?tab=followups"]
    assert await links(db, "loan_follow_up_due") == [f"/post-sales/{case}?tab=loan"]
