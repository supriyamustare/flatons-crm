from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import FollowUpTask, LeadActivity, Notification, Role, TaskStatus
from app.schemas.task import TaskQuery
from app.services.leads import IST
from app.services.notifications import create_daily_digests
from app.services.tasks import search_tasks
from app.tasks.digest import run_daily_digest


def later(**kw) -> str:
    return (datetime.now(UTC) + timedelta(**kw)).isoformat()


async def new_lead(c, name="Anita Desai", mobile="98765 43210"):
    resp = await c.post("/api/leads", json={"name": name, "mobile": mobile, "source": "99acres"})
    assert resp.status_code == 201, resp.text
    return resp.json()["lead"]


async def new_task(c, lead_id, **kw):
    body = {"lead_id": lead_id, "task_type": "call", "due_at": later(hours=2), **kw}
    resp = await c.post("/api/tasks", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_overdue(db, task_id, hours=3):
    await db.execute(
        update(FollowUpTask)
        .where(FollowUpTask.id == task_id)
        .values(due_at=datetime.now(UTC) - timedelta(hours=hours))
    )
    await db.commit()


# ---- Create ---------------------------------------------------------------


async def test_executive_creates_follow_up_on_own_lead(login_as, db):
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)

    task = await new_task(c, lead["id"], task_type="whatsapp", notes="Send brochure")

    assert task["assigned_to"]["id"] == me.id
    assert task["status"] == "pending" and task["is_overdue"] is False
    assert task["lead"]["lead_code"] == lead["lead_code"]
    entry = await db.scalar(select(LeadActivity).where(LeadActivity.type == "task_created"))
    assert entry.lead_id == lead["id"] and entry.note == "Send brochure"


async def test_follow_up_cannot_be_in_the_past(login_as):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    resp = await c.post(
        "/api/tasks", json={"lead_id": lead["id"], "task_type": "call", "due_at": later(hours=-2)}
    )
    assert resp.status_code == 422
    assert resp.json()["detail"] == "Choose a time in the future"


async def test_due_time_must_include_timezone(login_as):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    naive = (datetime.now() + timedelta(days=1)).replace(microsecond=0).isoformat()
    resp = await c.post(
        "/api/tasks", json={"lead_id": lead["id"], "task_type": "call", "due_at": naive}
    )
    assert resp.status_code == 422


async def test_executive_cannot_add_follow_up_to_someone_elses_lead(login_as):
    ravi, _ = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    lead = await new_lead(ravi)
    resp = await kiran.post(
        "/api/tasks", json={"lead_id": lead["id"], "task_type": "call", "due_at": later(hours=1)}
    )
    assert resp.status_code == 404


async def test_executive_cannot_assign_follow_up_to_others(login_as):
    c, me = await login_as(Role.executive)
    _, other = await login_as(Role.executive)
    lead = await new_lead(c)
    task = await new_task(c, lead["id"], assigned_to_id=other.id)
    assert task["assigned_to"]["id"] == me.id  # silently kept with the executive


async def test_manager_assigns_follow_up_and_assignee_is_notified(login_as, db):
    mgr, manager = await login_as(Role.manager)
    _, exec_user = await login_as(Role.executive)
    lead = await new_lead(mgr)

    task = await new_task(mgr, lead["id"], assigned_to_id=exec_user.id, task_type="meeting")

    assert task["assigned_to"]["id"] == exec_user.id
    note = await db.scalar(select(Notification).where(Notification.user_id == exec_user.id))
    assert note.type == "task_assigned"
    assert note.title == "Meeting with Anita Desai"
    assert note.link == f"/leads/{lead['id']}"
    assert manager.full_name in note.body


async def test_manager_task_defaults_to_lead_owner(login_as):
    mgr, _ = await login_as(Role.manager)
    _, exec_user = await login_as(Role.executive)
    resp = await mgr.post(
        "/api/leads",
        json={
            "name": "Owned Lead",
            "mobile": "9123456780",
            "source": "walk_in",
            "assigned_to_id": exec_user.id,
        },
    )
    lead = resp.json()["lead"]
    task = await new_task(mgr, lead["id"])
    assert task["assigned_to"]["id"] == exec_user.id


async def test_docs_staff_have_no_follow_ups(login_as):
    c, _ = await login_as(Role.docs)
    assert (await c.get("/api/tasks")).status_code == 403
    assert (await c.post("/api/tasks", json={})).status_code == 403


# ---- Views ----------------------------------------------------------------


async def test_views_split_tasks_by_due_time(login_as, db):
    """Fixed 'now' (2026-10-23 15:00 IST) so the test never depends on the clock."""
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)
    now = datetime(2026, 10, 23, 15, 0, tzinfo=IST)
    times = {
        "yesterday": now - timedelta(days=1),
        "this_morning": now.replace(hour=10),  # today AND overdue
        "tonight": now.replace(hour=19),
        "tomorrow": now + timedelta(days=1),
    }
    ids = {}
    for key, due in times.items():
        t = FollowUpTask(
            lead_id=lead["id"],
            assigned_to_id=me.id,
            created_by_id=me.id,
            task_type="call",
            due_at=due,
        )
        db.add(t)
        await db.flush()
        ids[key] = t.id
    done = FollowUpTask(
        lead_id=lead["id"],
        assigned_to_id=me.id,
        created_by_id=me.id,
        task_type="call",
        due_at=now - timedelta(hours=1),
        status=TaskStatus.completed,
        completed_at=now,
    )
    db.add(done)
    await db.commit()

    async def view(name):
        items, total, counts = await search_tasks(db, me, TaskQuery(view=name), now)
        return [i.id for i in items], counts

    today, counts = await view("today")
    overdue, _ = await view("overdue")
    upcoming, _ = await view("upcoming")
    completed, _ = await view("completed")

    assert today == [ids["this_morning"], ids["tonight"]]
    assert overdue == [ids["yesterday"], ids["this_morning"]]
    assert upcoming == [ids["tomorrow"]]
    assert completed == [done.id]
    assert counts.model_dump() == {"today": 2, "overdue": 2, "upcoming": 1}


async def test_executive_sees_only_own_tasks_manager_sees_all(login_as):
    ravi, ravi_user = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    await new_task(ravi, (await new_lead(ravi))["id"], due_at=later(days=3))
    await new_task(kiran, (await new_lead(kiran, "B", "9123456789"))["id"], due_at=later(days=3))

    def count(resp):
        return resp.json()["total"]

    assert count(await ravi.get("/api/tasks", params={"view": "upcoming"})) == 1
    assert count(await mgr.get("/api/tasks", params={"view": "upcoming"})) == 2
    only_ravi = await mgr.get(
        "/api/tasks", params={"view": "upcoming", "assigned_to_id": ravi_user.id}
    )
    assert count(only_ravi) == 1
    # An executive can't widen their view with assigned_to_id
    other = await ravi.get("/api/tasks", params={"view": "upcoming", "assigned_to_id": 999})
    assert count(other) == 1


async def test_overdue_flag_in_api(login_as, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    task = await new_task(c, lead["id"])
    await make_overdue(db, task["id"])

    resp = await c.get("/api/tasks", params={"view": "overdue"})

    assert resp.json()["items"][0]["is_overdue"] is True
    assert resp.json()["counts"]["overdue"] == 1


# ---- Complete & reschedule ------------------------------------------------


async def test_complete_logs_activity_and_moves_to_completed(login_as, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    task = await new_task(c, lead["id"])

    resp = await c.post(
        f"/api/tasks/{task['id']}/complete",
        json={"completion_note": "Spoke to customer, visiting Sunday"},
    )

    assert resp.status_code == 200
    assert resp.json()["status"] == "completed" and resp.json()["completed_at"]
    entry = await db.scalar(select(LeadActivity).where(LeadActivity.type == "task_completed"))
    assert entry.note == "Spoke to customer, visiting Sunday"
    listing = await c.get("/api/tasks", params={"view": "completed"})
    assert [t["id"] for t in listing.json()["items"]] == [task["id"]]
    # Can't complete twice
    again = await c.post(f"/api/tasks/{task['id']}/complete", json={"completion_note": "x"})
    assert again.status_code == 422


async def test_completion_needs_a_note(login_as):
    c, _ = await login_as(Role.executive)
    task = await new_task(c, (await new_lead(c))["id"])
    resp = await c.post(f"/api/tasks/{task['id']}/complete", json={"completion_note": "  "})
    assert resp.status_code == 422


async def test_reschedule_keeps_the_chain(login_as, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    first = await new_task(c, lead["id"], notes="Discuss price")

    r1 = await c.post(
        f"/api/tasks/{first['id']}/reschedule",
        json={"due_at": later(days=1), "reason": "Customer travelling"},
    )
    second = r1.json()
    r2 = await c.post(f"/api/tasks/{second['id']}/reschedule", json={"due_at": later(days=2)})
    third = r2.json()

    assert r1.status_code == 201 and r2.status_code == 201
    assert second["rescheduled_from_id"] == first["id"]
    assert third["rescheduled_from_id"] == second["id"]
    assert second["reschedule_reason"] == "Customer travelling"
    assert third["notes"] == "Discuss price"  # carried forward
    old = await db.get(FollowUpTask, first["id"])
    assert old.status == TaskStatus.rescheduled
    entries = list(
        await db.scalars(
            select(LeadActivity)
            .where(LeadActivity.type == "task_rescheduled")
            .order_by(LeadActivity.id)
        )
    )
    assert len(entries) == 2 and entries[0].note == "Customer travelling"
    # Only the latest task is still open
    lead_tasks = (await c.get(f"/api/leads/{lead['id']}/tasks")).json()
    assert [t["status"] for t in lead_tasks].count("pending") == 1
    assert lead_tasks[0]["id"] == third["id"]


async def test_cannot_reschedule_into_the_past(login_as):
    c, _ = await login_as(Role.executive)
    task = await new_task(c, (await new_lead(c))["id"])
    resp = await c.post(f"/api/tasks/{task['id']}/reschedule", json={"due_at": later(days=-1)})
    assert resp.status_code == 422


async def test_others_cannot_act_on_my_task(login_as):
    ravi, _ = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    task = await new_task(ravi, (await new_lead(ravi))["id"])

    assert (
        await kiran.post(f"/api/tasks/{task['id']}/complete", json={"completion_note": "x"})
    ).status_code == 404
    # Managers can step in
    assert (
        await mgr.post(
            f"/api/tasks/{task['id']}/complete", json={"completion_note": "Done by manager"}
        )
    ).status_code == 200


@pytest.mark.parametrize("action", ["complete", "reschedule"])
async def test_actions_update_lead_last_activity(login_as, db, action):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    task = await new_task(c, lead["id"])
    before = (await c.get(f"/api/leads/{lead['id']}")).json()["last_activity_at"]
    body = {"completion_note": "ok"} if action == "complete" else {"due_at": later(days=1)}
    await c.post(f"/api/tasks/{task['id']}/{action}", json=body)
    after = (await c.get(f"/api/leads/{lead['id']}")).json()["last_activity_at"]
    assert after > before


# ---- Notifications --------------------------------------------------------


async def test_lead_reassignment_notifies_new_owner(login_as):
    mgr, _ = await login_as(Role.manager)
    ravi, ravi_user = await login_as(Role.executive)
    lead = await new_lead(mgr)

    await mgr.post(f"/api/leads/{lead['id']}/assign", json={"assigned_to_id": ravi_user.id})

    data = (await ravi.get("/api/notifications")).json()
    assert data["unread_count"] == 1
    assert data["items"][0]["type"] == "lead_assigned"
    assert data["items"][0]["link"] == f"/leads/{lead['id']}"


async def test_mark_read_and_read_all(login_as, db):
    c, me = await login_as(Role.executive)
    _, other = await login_as(Role.executive)
    for i in range(3):
        db.add(Notification(user_id=me.id, type="test", title=f"N{i}"))
    db.add(Notification(user_id=other.id, type="test", title="Not yours"))
    await db.commit()
    data = (await c.get("/api/notifications")).json()
    assert data["unread_count"] == 3 and len(data["items"]) == 3

    first = data["items"][0]["id"]
    assert (await c.patch(f"/api/notifications/{first}/read")).json()["read_at"]
    assert (await c.get("/api/notifications")).json()["unread_count"] == 2

    others = await db.scalar(select(Notification.id).where(Notification.user_id == other.id))
    assert (await c.patch(f"/api/notifications/{others}/read")).status_code == 404

    assert (await c.post("/api/notifications/read-all")).status_code == 204
    assert (await c.get("/api/notifications")).json()["unread_count"] == 0


async def test_daily_digest(login_as, make_user, db):
    """One digest per person with something due; nothing for empty days; never twice a day."""
    c, busy = await login_as(Role.executive)
    idle = await make_user(Role.executive)
    lead = await new_lead(c)
    now = datetime(2026, 10, 23, 8, 0, tzinfo=IST)
    for due in (
        now - timedelta(days=1),
        now + timedelta(hours=3),
        now + timedelta(hours=5),
        now + timedelta(days=2),
    ):
        db.add(
            FollowUpTask(
                lead_id=lead["id"],
                assigned_to_id=busy.id,
                created_by_id=busy.id,
                task_type="call",
                due_at=due,
            )
        )
    await db.commit()

    assert await create_daily_digests(db, now) == 1
    await db.commit()
    note = await db.scalar(select(Notification).where(Notification.type == "daily_digest"))
    assert note.user_id == busy.id
    assert note.body == "2 follow-ups due later today, 1 overdue"
    assert note.link == "/follow-ups"
    assert await db.scalar(select(Notification).where(Notification.user_id == idle.id)) is None

    # Running again the same day creates nothing new.
    assert await create_daily_digests(db, now + timedelta(hours=1)) == 0


async def test_celery_digest_job_runs_end_to_end(login_as, db):
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)
    db.add(
        FollowUpTask(
            lead_id=lead["id"],
            assigned_to_id=me.id,
            created_by_id=me.id,
            task_type="call",
            due_at=datetime.now(UTC) - timedelta(hours=1),
        )
    )
    await db.commit()

    assert await run_daily_digest() == 1


def test_digest_is_scheduled_for_8am_india_time():
    from app.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["daily-follow-up-digest"]
    assert entry["task"] == "followups.daily_digest"
    assert entry["schedule"].hour == {8} and entry["schedule"].minute == {0}
    assert celery_app.conf.timezone == "Asia/Kolkata"
