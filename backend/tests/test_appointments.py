from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Notification, PostSalesCase, Role
from app.models.agreement import Agreement, AgreementStatus
from app.models.appointment import Appointment
from app.models.visit import SiteVisit
from app.services.appointments import IST
from app.services.followups import run_reminders
from tests import test_ledger

case = test_ledger.case


def at(days=1, hour=11):
    d = datetime.now(IST).date() + timedelta(days=days)
    return datetime(d.year, d.month, d.day, hour, 0, tzinfo=IST)


async def book(c, case_id, when=None, **kw):
    return await c.post(
        f"/api/post-sales/cases/{case_id}/appointments",
        json={
            "kind": "inspection",
            "starts_at": (when or at()).isoformat(),
            "location": "Habitat site office",
            "required_docs": "ID proof",
            **kw,
        },
    )


async def test_scheduling_rules_and_double_booking(login_as, db, case):
    pse, me = await login_as(Role.postsales_exec)
    assert (
        await book(pse, case, when=datetime.now(UTC) - timedelta(hours=2))
    ).status_code == 422  # in the past
    _, fin = await login_as(Role.finance)
    assert (
        await book(pse, case, owner_id=fin.id)
    ).status_code == 422  # finance doesn't own appointments
    r = await book(pse, case)
    assert (
        r.status_code == 201
        and r.json()["items"][0]["owner"]["id"]
        == (await db.get(PostSalesCase, case)).owner_id  # the case owner by default
        and r.json()["items"][0]["apt_no"].startswith("APT-")
    )
    r = await book(pse, case, when=at(hour=11) + timedelta(minutes=30), kind="document_collection")
    assert r.status_code == 409 and "already has customer inspection" in r.text
    assert (
        await book(
            pse,
            case,
            when=at(hour=11) + timedelta(minutes=30),
            kind="document_collection",
            allow_clash=True,
        )
    ).status_code == 201
    assert (
        await book(pse, case, when=at(hour=13), kind="document_collection")
    ).status_code == 201  # after both: fine
    _, site = await login_as(Role.site)
    await book(pse, case, when=at(days=2), owner_id=site.id)
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == site.id, Notification.type == "appointment_assigned"
        )
    )
    fin_c, _ = await login_as(Role.finance)
    assert (await fin_c.get(f"/api/post-sales/cases/{case}/appointments")).status_code == 200
    assert (await book(fin_c, case, when=at(days=3))).status_code == 403


async def test_confirm_reschedule_cancel(login_as, case):
    pse, _ = await login_as(Role.postsales_exec)
    a = (await book(pse, case)).json()["items"][0]
    s = (await pse.post(f"/api/appointments/{a['id']}/confirm", json={"via": "whatsapp"})).json()[
        "items"
    ][0]
    assert s["confirmed_via"] == "whatsapp" and s["confirmed_on"]
    r = await pse.post(
        f"/api/appointments/{a['id']}/reschedule",
        json={"starts_at": at(days=3).isoformat(), "reason": "no"},
    )
    assert r.status_code == 422
    items = (
        await pse.post(
            f"/api/appointments/{a['id']}/reschedule",
            json={"starts_at": at(days=3).isoformat(), "reason": "Customer travelling"},
        )
    ).json()["items"]
    new, old = items[0], items[1]
    assert (old["status"], old["status_reason"]) == ("rescheduled", "Customer travelling")
    assert (
        new["rescheduled_from"] == a["apt_no"]
        and new["confirmed_on"] is None
        and new["status"] == "scheduled"
    )  # confirm again
    assert (
        await pse.post(f"/api/appointments/{new['id']}/cancel", json={"reason": "x"})
    ).status_code == 422
    items = (
        await pse.post(
            f"/api/appointments/{new['id']}/cancel", json={"reason": "Inspection not needed"}
        )
    ).json()["items"]
    assert items[0]["status"] == "cancelled"


async def test_attendance_and_missed_follow_up(login_as, db, case):
    pse, me = await login_as(Role.postsales_exec)
    a = (await book(pse, case)).json()["items"][0]
    assert (
        await pse.post(
            f"/api/appointments/{a['id']}/attendance", json={"attended": True, "outcome": "ok"}
        )
    ).status_code == 422  # not yet time
    row = await db.get(Appointment, a["id"])
    row.starts_at = datetime.now(UTC) - timedelta(hours=1)
    await db.commit()
    assert (
        await pse.post(f"/api/appointments/{a['id']}/attendance", json={"attended": True})
    ).status_code == 422  # outcome needed
    s = (
        await pse.post(
            f"/api/appointments/{a['id']}/attendance",
            json={"attended": False, "outcome": "Phone switched off"},
        )
    ).json()["items"][0]
    tomorrow = (datetime.now(IST).date() + timedelta(days=1)).isoformat()
    assert (s["status"], s["follow_up_on"]) == ("no_show", tomorrow)
    owner_id = (await db.get(PostSalesCase, case)).owner_id
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == owner_id, Notification.type == "appointment_missed"
        )
    )
    row = await db.get(Appointment, a["id"])
    row.follow_up_on = datetime.now(IST).date()
    await db.commit()
    crm, _ = await login_as(Role.crm_manager)  # sees every missed appointment (the owner does too)
    due = (await crm.get("/api/post-sales/follow-ups/due")).json()
    assert any(x["reason"] == "Missed appointment" for x in due)
    await pse.post(
        f"/api/appointments/{a['id']}/reschedule",
        json={"starts_at": at(days=2).isoformat(), "reason": "Customer called back"},
    )
    assert not any(
        x["reason"] == "Missed appointment"
        for x in (await crm.get("/api/post-sales/follow-ups/due")).json()
    )


async def test_the_calendar_combines_everything_by_role(login_as, db, case):
    pse, _ = await login_as(Role.postsales_exec)
    await book(pse, case, when=at(days=1))
    c = await db.get(PostSalesCase, case)
    db.add(
        Agreement(
            case_id=case,
            status=AgreementStatus.execution_prep,
            appointment_at=at(days=2, hour=15),
            sro_office="Haveli 1",
        )
    )
    ex, ex_user = await login_as(Role.executive)
    db.add(
        SiteVisit(
            lead_id=c.booking.lead_id,
            project_id=c.booking.project_id,
            host_id=ex_user.id,
            scheduled_at=at(days=1, hour=16),
            visit_source="walk_in",
        )
    )
    await db.commit()
    start = datetime.now(IST).date().isoformat()
    items = (await pse.get(f"/api/calendar?start={start}&days=7")).json()
    assert {(i["source"], i["kind"]) for i in items} == {
        ("appointment", "inspection"),
        ("agreement", "registration"),
    }  # post-sales: no sales visits
    assert items[0]["link"].endswith("?tab=appointments") and items[1]["link"].endswith(
        "?tab=agreement"
    )
    items = (await ex.get(f"/api/calendar?start={start}&days=7")).json()
    assert [i["source"] for i in items] == ["sales_visit"] and items[0]["link"].startswith(
        "/leads/"
    )
    admin, _ = await login_as(Role.admin)
    assert {
        i["source"] for i in (await admin.get(f"/api/calendar?start={start}&days=7")).json()
    } == {"appointment", "agreement", "sales_visit"}
    # "Mine": this executive owns none of them (the case owner does)
    assert (await pse.get(f"/api/calendar?start={start}&days=7&mine=true")).json() == []


async def test_daily_appointment_reminders(login_as, db, case):
    pse, me = await login_as(Role.postsales_exec)
    today = datetime.now(IST).date()
    ids = [
        (await book(pse, case, when=at(days=d, hour=h), allow_clash=True)).json()["items"][0]["id"]
        for d, h in ((1, 10), (0, 23), (1, 14))
    ]
    past = await db.get(Appointment, ids[2])
    past.starts_at = datetime.now(UTC) - timedelta(days=1)  # yesterday, attendance not recorded
    await db.commit()
    counts = await run_reminders(db, today)
    await db.commit()
    assert (
        counts["appointments_tomorrow"],
        counts["appointments_today"],
        counts["attendance_missing"],
    ) == (1, 1, 1)
    owner_id = (await db.get(PostSalesCase, case)).owner_id
    kinds = set(await db.scalars(select(Notification.type).where(Notification.user_id == owner_id)))
    assert {"appointment_tomorrow", "appointment_today", "appointment_attendance_missing"} <= kinds
    again = await run_reminders(db, today)
    assert (
        again["appointments_tomorrow"],
        again["appointments_today"],
        again["attendance_missing"],
    ) == (0, 0, 0)  # once each
