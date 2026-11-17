from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.models import Notification, PostSalesCase, Role
from app.models.demand import Demand
from app.models.followup import PaymentFollowUp
from app.services.followups import run_reminders
from tests import test_ledger
from tests.test_demands import BANK, LEGAL, approved_ledger, project_id, report
from tests.test_ledger import TODAY

case = test_ledger.case
PLINTH = 322_500 + 3_225


async def issued_demand(login_as, db, case_id):
    """Approved ledger, Plinth verified, demand approved and issued; returns (finance client, approver client, demand)."""
    fin, chk = await approved_ledger(login_as, case_id)
    pid = await project_id(db, case_id)
    admin, _ = await login_as(Role.admin)
    await admin.put(f"/api/projects/{pid}/legal", json=LEGAL)
    await admin.put(f"/api/projects/{pid}/bank", json=BANK)
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid)).json()
    await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    d = (await fin.get(f"/api/post-sales/cases/{case_id}/demands")).json()["demands"][0]
    await fin.post(f"/api/post-sales/cases/{case_id}/demands/{d['id']}/submit")
    await chk.post(f"/api/post-sales/cases/{case_id}/demands/{d['id']}/approve")
    await crm.post(
        f"/api/post-sales/cases/{case_id}/demands/{d['id']}/issue", json={"method": "email"}
    )
    return fin, chk, await db.get(Demand, d["id"])


async def test_logging_follow_ups_and_promise_rules(login_as, case):
    pse, _ = await login_as(Role.postsales_exec)
    r = await pse.post(
        f"/api/post-sales/cases/{case}/follow-ups",
        json={
            "channel": "call",
            "outcome": "reached",
            "note": "Will check with bank",
            "next_follow_up_on": (TODAY + timedelta(days=3)).isoformat(),
        },
    )
    assert (
        r.status_code == 201
        and r.json()["items"][0]["next_follow_up_on"] == (TODAY + timedelta(days=3)).isoformat()
    )
    for bad, msg in (
        ({"outcome": "promised"}, "needs the amount and the date"),
        (
            {
                "outcome": "promised",
                "promise_amount": 100,
                "promise_date": (TODAY - timedelta(days=1)).isoformat(),
            },
            "within the next 90 days",
        ),
        ({"outcome": "reached", "promise_amount": 100}, "Choose 'Promised to pay'"),
        (
            {"outcome": "reached", "next_follow_up_on": (TODAY + timedelta(days=90)).isoformat()},
            "within the next 60 days",
        ),
        (
            {"outcome": "reached", "contacted_on": (TODAY + timedelta(days=1)).isoformat()},
            "within the last 30 days",
        ),
    ):
        r = await pse.post(
            f"/api/post-sales/cases/{case}/follow-ups", json={"channel": "call", **bad}
        )
        assert r.status_code == 422 and msg in r.text, (bad, r.text)
    for role, code in ((Role.finance, 201), (Role.legal, 403), (Role.auditor, 403)):
        c, _ = await login_as(role)
        assert (
            await c.post(
                f"/api/post-sales/cases/{case}/follow-ups",
                json={"channel": "note", "outcome": "other"},
            )
        ).status_code == code, role
    aud, _ = await login_as(Role.auditor)
    assert (await aud.get(f"/api/post-sales/cases/{case}/follow-ups")).status_code == 200


async def test_promise_kept_and_broken(login_as, db, case):
    fin, chk, d = await issued_demand(login_as, db, case)
    pse, pse_user = await login_as(Role.postsales_exec)
    c = await db.get(PostSalesCase, case)
    c.owner_id = pse_user.id
    await db.commit()
    data = (
        await pse.post(
            f"/api/post-sales/cases/{case}/follow-ups",
            json={
                "channel": "call",
                "outcome": "promised",
                "demand_id": d.id,
                "promise_amount": 100_000,
                "promise_date": (TODAY + timedelta(days=2)).isoformat(),
            },
        )
    ).json()
    assert (
        data["items"][0]["promise_status"] == "open"
        and data["items"][0]["demand_no"] == f"DMD-{d.id:05d}"
    )
    # A confirmed receipt of Rs 1,00,000 keeps the promise
    rid = (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts",
            json={
                "amount": 100_000,
                "received_on": TODAY.isoformat(),
                "mode": "neft",
                "reference": "UTR-P1",
            },
        )
    ).json()["receipts"][0]["id"]
    assert (await pse.get(f"/api/post-sales/cases/{case}/follow-ups")).json()["items"][0][
        "promise_status"
    ] == "open"  # not confirmed yet
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    assert (await pse.get(f"/api/post-sales/cases/{case}/follow-ups")).json()["items"][0][
        "promise_status"
    ] == "kept"
    # Another promise, then its date passes with nothing paid: broken, alerted once to the owner and CRM managers
    fu = PaymentFollowUp(
        case_id=case,
        channel="call",
        outcome="promised",
        contacted_on=TODAY - timedelta(days=10),
        promise_date=TODAY - timedelta(days=1),
        promise_amount=50_000,
        by_id=pse_user.id,
    )
    db.add(fu)
    await db.commit()
    _, crm = await login_as(Role.crm_manager)
    counts = await run_reminders(db, TODAY)
    await db.commit()
    assert counts["broken_promises"] >= 2  # owner + CRM managers
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == crm.id, Notification.type == "promise_broken"
        )
    )
    # a day later (past the 20-hour duplicate window): still only once
    await db.execute(
        update(Notification)
        .where(Notification.type == "promise_broken")
        .values(created_at=func.now() - timedelta(days=2))
    )
    await db.commit()
    again = await run_reminders(db, TODAY + timedelta(days=1))
    assert again["broken_promises"] == 0  # only once
    due = (await pse.get("/api/post-sales/follow-ups/due")).json()
    assert any(x["reason"] == "Promise broken" and x["amount"] == 50_000 for x in due)


@pytest.mark.parametrize(
    "offset,kind,escalated",
    [
        (-3, "demand_due_soon", False),
        (0, "demand_due_today", False),
        (1, "demand_overdue", False),
        (7, "demand_overdue", False),
        (15, "demand_overdue", True),
        (30, "demand_overdue", True),
    ],
)
async def test_daily_reminders_follow_the_schedule(login_as, db, case, offset, kind, escalated):
    _, _, d = await issued_demand(login_as, db, case)
    _, owner = await login_as(Role.postsales_exec)
    _, crm = await login_as(Role.crm_manager)
    c = await db.get(PostSalesCase, case)
    c.owner_id = owner.id
    await db.commit()
    day = d.due_date + timedelta(days=offset)
    await run_reminders(db, day)
    await db.commit()
    to_owner = await db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == kind)
    )
    assert to_owner is not None and f"DMD-{d.id:05d}" in to_owner.body
    to_crm = await db.scalar(
        select(Notification.id).where(Notification.user_id == crm.id, Notification.type == kind)
    )
    assert (to_crm is not None) is escalated
    assert (await run_reminders(db, day))[
        {"demand_due_soon": "due_soon", "demand_due_today": "due_today"}.get(kind, "overdue")
    ] == 0  # not twice a day


async def test_no_reminders_on_other_days_or_once_paid(login_as, db, case):
    fin, chk, d = await issued_demand(login_as, db, case)
    _, owner = await login_as(Role.postsales_exec)
    c = await db.get(PostSalesCase, case)
    c.owner_id = owner.id
    await db.commit()
    counts = await run_reminders(db, d.due_date + timedelta(days=2))
    assert counts["due_soon"] == counts["due_today"] == counts["overdue"] == 0
    rid = (
        await fin.post(
            f"/api/post-sales/cases/{case}/receipts",
            json={
                "amount": PLINTH,
                "received_on": TODAY.isoformat(),
                "mode": "neft",
                "reference": "UTR-ALL",
                "matches": [{"stage_seq": d.stage_seq, "amount": PLINTH}],
            },
        )
    ).json()["receipts"][0]["id"]
    await chk.post(f"/api/post-sales/cases/{case}/receipts/{rid}/confirm")
    counts = await run_reminders(db, d.due_date + timedelta(days=7))
    assert counts["overdue"] == 0  # paid: no reminder


async def test_follow_up_due_today_reminds_and_lists(login_as, db, case):
    pse, user = await login_as(Role.postsales_exec)
    await pse.post(
        f"/api/post-sales/cases/{case}/follow-ups",
        json={
            "channel": "call",
            "outcome": "not_reachable",
            "note": "Try after 6 pm",
            "next_follow_up_on": TODAY.isoformat(),
        },
    )
    counts = await run_reminders(db, TODAY)
    await db.commit()
    assert counts["follow_ups_due"] == 1
    n = await db.scalar(
        select(Notification).where(
            Notification.user_id == user.id, Notification.type == "payment_follow_up_due"
        )
    )
    assert n.body == "Try after 6 pm"
    due = (await pse.get("/api/post-sales/follow-ups/due")).json()
    assert [x["reason"] for x in due] == ["Follow-up due"]


async def test_money_received_before_the_promise_doesnt_keep_it(login_as, db, case):
    fin, chk, d = await issued_demand(login_as, db, case)
    rid = (await chk.get(f"/api/post-sales/cases/{case}/receipts")).json()["receipts"][0]["id"]
    await chk.post(
        f"/api/post-sales/cases/{case}/receipts/{rid}/confirm"
    )  # Rs 3,22,500 confirmed today, before the promise
    pse, _ = await login_as(Role.postsales_exec)
    data = (
        await pse.post(
            f"/api/post-sales/cases/{case}/follow-ups",
            json={
                "channel": "call",
                "outcome": "promised",
                "promise_amount": 100_000,
                "promise_date": (TODAY + timedelta(days=2)).isoformat(),
            },
        )
    ).json()
    assert data["items"][0]["promise_status"] == "open"
