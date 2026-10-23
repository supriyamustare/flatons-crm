from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.models import (
    AuditLog,
    CallLog,
    FollowUpTask,
    LeadActivity,
    LeadStatus,
    Notification,
    Project,
    Role,
    SiteVisit,
    TaskStatus,
)
from app.services.leads import IST
from app.services.notifications import create_daily_digests


def later(**kw) -> str:
    return (datetime.now(UTC) + timedelta(**kw)).isoformat()


async def new_lead(c, name="Anita Desai", mobile="98765 43210", **extra):
    resp = await c.post(
        "/api/leads", json={"name": name, "mobile": mobile, "source": "website", **extra}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["lead"]


@pytest.fixture
async def project(db):
    p = Project(name="Flatons Heights")
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


async def activity_types(db, lead_id):
    rows = await db.scalars(
        select(LeadActivity.type).where(LeadActivity.lead_id == lead_id).order_by(LeadActivity.id)
    )
    return list(rows)


async def lead_status(c, lead_id):
    return (await c.get(f"/api/leads/{lead_id}")).json()["status"]


# ============================ Calls ==========================================


async def test_log_call_records_timeline_and_audit(login_as, db):
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)

    resp = await c.post(
        "/api/calls",
        json={
            "lead_id": lead["id"],
            "outcome": "interested",
            "duration_sec": 245,
            "notes": "Wants 2 BHK",
        },
    )

    assert resp.status_code == 201, resp.text
    call = resp.json()
    assert call["connected"] is True and call["direction"] == "outgoing"
    assert call["user"]["id"] == me.id and call["follow_up_task_id"] is None
    assert "call_logged" in await activity_types(db, lead["id"])
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "call.log"))


async def test_call_with_next_date_creates_follow_up(login_as, db):
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)

    resp = await c.post(
        "/api/calls",
        json={
            "lead_id": lead["id"],
            "outcome": "callback",
            "follow_up_at": later(days=1),
            "follow_up_type": "whatsapp",
        },
    )

    task_id = resp.json()["follow_up_task_id"]
    task = await db.get(FollowUpTask, task_id)
    assert task.status == TaskStatus.pending and task.assigned_to_id == me.id
    assert task.task_type.value == "whatsapp"
    assert task.notes == "After call: Call back later"
    created = await db.scalar(select(LeadActivity).where(LeadActivity.type == "task_created"))
    assert created.details["source"] == "call"


async def test_logging_call_can_close_the_follow_up_it_came_from(login_as, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    task = (
        await c.post(
            "/api/tasks",
            json={"lead_id": lead["id"], "task_type": "call", "due_at": later(hours=1)},
        )
    ).json()

    resp = await c.post(
        "/api/calls",
        json={
            "lead_id": lead["id"],
            "outcome": "no_answer",
            "complete_task_id": task["id"],
            "notes": "Rang twice",
        },
    )

    assert resp.status_code == 201
    assert resp.json()["connected"] is False
    closed = await db.get(FollowUpTask, task["id"])
    assert closed.status == TaskStatus.completed
    assert closed.completion_note == "Call: No answer. Rang twice"
    # The closed task can't be used again
    again = await c.post(
        "/api/calls",
        json={"lead_id": lead["id"], "outcome": "busy", "complete_task_id": task["id"]},
    )
    assert again.status_code == 422


async def test_cannot_close_a_follow_up_from_another_lead(login_as):
    c, _ = await login_as(Role.executive)
    a = await new_lead(c)
    b = await new_lead(c, "Other", "9123456780")
    task = (
        await c.post(
            "/api/tasks", json={"lead_id": b["id"], "task_type": "call", "due_at": later(hours=1)}
        )
    ).json()
    resp = await c.post(
        "/api/calls", json={"lead_id": a["id"], "outcome": "busy", "complete_task_id": task["id"]}
    )
    assert resp.status_code == 422


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("called_at", "future"),
        ("called_at", "too_old"),
        ("follow_up_at", "past"),
        ("duration_sec", -5),
        ("duration_sec", 5 * 3600),
        ("outcome", "maybe"),
    ],
)
async def test_invalid_calls_are_rejected(login_as, field, value):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    value = {"future": later(hours=2), "too_old": later(days=-40), "past": later(hours=-2)}.get(
        value, value
    )
    resp = await c.post("/api/calls", json={"lead_id": lead["id"], "outcome": "busy", field: value})
    assert resp.status_code == 422


async def test_backdated_call_within_30_days_is_allowed(login_as):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    resp = await c.post(
        "/api/calls", json={"lead_id": lead["id"], "outcome": "busy", "called_at": later(days=-2)}
    )
    assert resp.status_code == 201


async def test_call_visibility_and_filters(login_as):
    ravi, ravi_user = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    a = await new_lead(ravi)
    b = await new_lead(kiran, "B", "9123456780")
    for outcome in ("interested", "no_answer", "busy"):
        await ravi.post("/api/calls", json={"lead_id": a["id"], "outcome": outcome})
    await kiran.post("/api/calls", json={"lead_id": b["id"], "outcome": "callback"})

    mine = (await ravi.get("/api/calls")).json()
    assert mine["total"] == 3 and mine["connected"] == 1
    assert (await mgr.get("/api/calls")).json()["total"] == 4
    just_ravi = await mgr.get("/api/calls", params={"user_id": ravi_user.id})
    assert just_ravi.json()["total"] == 3
    busy = await mgr.get("/api/calls", params={"outcome": "busy"})
    assert busy.json()["total"] == 1
    # Kiran can't log calls on Ravi's lead
    assert (
        await kiran.post("/api/calls", json={"lead_id": a["id"], "outcome": "busy"})
    ).status_code == 404


async def test_docs_staff_cannot_use_calls_or_visits(login_as):
    c, _ = await login_as(Role.docs)
    assert (await c.get("/api/calls")).status_code == 403
    assert (await c.get("/api/visits")).status_code == 403


# ============================ Visits =========================================


async def schedule(c, lead_id, project_id, **kw):
    body = {"lead_id": lead_id, "project_id": project_id, "scheduled_at": later(days=2), **kw}
    resp = await c.post("/api/visits", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_today(db, visit_id, hours_ago=1):
    await db.execute(
        update(SiteVisit)
        .where(SiteVisit.id == visit_id)
        .values(scheduled_at=datetime.now(UTC) - timedelta(hours=hours_ago))
    )
    await db.commit()


async def test_scheduling_a_visit_moves_early_lead_to_visit_scheduled(login_as, project, db):
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)

    visit = await schedule(c, lead["id"], project.id, visit_source="channel_partner")

    assert visit["status"] == "scheduled" and visit["host"]["id"] == me.id
    assert visit["visit_source"] == "channel_partner"
    assert visit["project"]["name"] == "Flatons Heights"
    assert await lead_status(c, lead["id"]) == "visit_scheduled"
    change = await db.scalar(select(LeadActivity).where(LeadActivity.type == "status_change"))
    assert (
        change.details["automatic"] is True and change.details["reason"] == "Site visit scheduled"
    )


@pytest.mark.parametrize("status", ["negotiation", "on_hold", "lost"])
async def test_visit_never_moves_later_stage_leads(login_as, project, status):
    c, _ = await login_as(Role.manager)
    lead = await new_lead(c)
    body = {"status": status} | ({"reason": "Budget"} if status == "lost" else {})
    assert (await c.post(f"/api/leads/{lead['id']}/status", json=body)).status_code == 200
    await schedule(c, lead["id"], project.id)
    assert await lead_status(c, lead["id"]) == status


async def test_complete_visit_records_feedback_and_moves_lead(login_as, project, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    visit = await schedule(c, lead["id"], project.id)
    await make_today(db, visit["id"])

    resp = await c.post(
        f"/api/visits/{visit['id']}/complete",
        json={
            "feedback": "Liked the 12th floor unit",
            "interest_level": "hot",
            "next_action": "Send price sheet",
            "follow_up_at": later(days=1),
        },
    )

    assert resp.status_code == 200, resp.text
    done = resp.json()
    assert done["status"] == "completed" and done["interest_level"] == "hot"
    assert await lead_status(c, lead["id"]) == "visit_done"
    types = await activity_types(db, lead["id"])
    assert "visit_completed" in types and types.count("task_created") == 1
    task = await db.scalar(select(FollowUpTask).where(FollowUpTask.lead_id == lead["id"]))
    assert task.notes == "Send price sheet"


async def test_second_completed_visit_makes_lead_a_revisit(login_as, project, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    for _ in range(2):
        v = await schedule(c, lead["id"], project.id)
        await make_today(db, v["id"])
        await c.post(
            f"/api/visits/{v['id']}/complete", json={"feedback": "ok", "interest_level": "warm"}
        )
    assert await lead_status(c, lead["id"]) == "revisit"


async def test_outcome_cannot_be_recorded_before_the_visit_day(login_as, project):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    visit = await schedule(c, lead["id"], project.id)  # in 2 days
    resp = await c.post(
        f"/api/visits/{visit['id']}/complete", json={"feedback": "x", "interest_level": "cold"}
    )
    assert resp.status_code == 422
    assert (await c.post(f"/api/visits/{visit['id']}/no-show", json={})).status_code == 422


async def test_reschedule_no_show_and_cancel(login_as, project, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    v1 = await schedule(c, lead["id"], project.id)
    moved = (
        await c.post(
            f"/api/visits/{v1['id']}/reschedule",
            json={"scheduled_at": later(days=5), "reason": "Rain"},
        )
    ).json()
    assert moved["reschedule_count"] == 1 and moved["status"] == "scheduled"

    await make_today(db, v1["id"])
    no_show = (await c.post(f"/api/visits/{v1['id']}/no-show", json={"note": "Phone off"})).json()
    assert no_show["status"] == "no_show"

    v2 = await schedule(c, lead["id"], project.id)
    assert (await c.post(f"/api/visits/{v2['id']}/cancel", json={})).status_code == 422  # reason
    cancelled = (
        await c.post(f"/api/visits/{v2['id']}/cancel", json={"reason": "Bought elsewhere"})
    ).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["cancellation_reason"] == "Bought elsewhere"
    # Closed visits can't be changed again
    assert (
        await c.post(f"/api/visits/{v2['id']}/reschedule", json={"scheduled_at": later(days=3)})
    ).status_code == 422
    types = await activity_types(db, lead["id"])
    for t in ("visit_rescheduled", "visit_no_show", "visit_cancelled"):
        assert t in types


async def test_visit_needs_a_valid_project_and_future_time(login_as, project, db):
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    past = {"lead_id": lead["id"], "project_id": project.id, "scheduled_at": later(hours=-3)}
    assert (await c.post("/api/visits", json=past)).status_code == 422
    missing = {"lead_id": lead["id"], "project_id": 9999, "scheduled_at": later(days=1)}
    assert (await c.post("/api/visits", json=missing)).status_code == 422
    project.is_active = False
    await db.commit()
    inactive = {"lead_id": lead["id"], "project_id": project.id, "scheduled_at": later(days=1)}
    assert (await c.post("/api/visits", json=inactive)).status_code == 422


async def test_manager_schedules_visit_for_executive_who_is_notified(login_as, project, db):
    mgr, _ = await login_as(Role.manager)
    ravi, ravi_user = await login_as(Role.executive)
    lead = await new_lead(mgr, assigned_to_id=ravi_user.id)

    visit = await schedule(mgr, lead["id"], project.id)  # host defaults to lead owner

    assert visit["host"]["id"] == ravi_user.id
    note = await db.scalar(select(Notification).where(Notification.type == "visit_assigned"))
    assert note.user_id == ravi_user.id and note.link == f"/leads/{lead['id']}"
    # Ravi sees it and can record the outcome
    assert (await ravi.get("/api/visits")).json()["total"] == 1


async def test_visit_views_counts_and_visibility(login_as, project, db):
    ravi, _ = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    a = await new_lead(ravi)
    b = await new_lead(kiran, "B", "9123456780")
    va = await schedule(ravi, a["id"], project.id)
    await schedule(ravi, a["id"], project.id)
    await schedule(kiran, b["id"], project.id)
    await make_today(db, va["id"], hours_ago=5)  # passed, no outcome yet

    page = (await ravi.get("/api/visits", params={"view": "upcoming"})).json()
    assert page["total"] == 2
    assert page["counts"] == {"upcoming": 2, "needs_update": 1}
    assert page["items"][0]["needs_update"] is True
    assert (await mgr.get("/api/visits")).json()["total"] == 3
    assert (
        await kiran.post(f"/api/visits/{va['id']}/cancel", json={"reason": "x"})
    ).status_code == 404
    lead_visits = (await ravi.get(f"/api/leads/{a['id']}/visits")).json()
    assert len(lead_visits) == 2


async def test_digest_mentions_todays_visits(login_as, project, db):
    c, me = await login_as(Role.executive)
    lead = await new_lead(c)
    now = datetime(2026, 10, 23, 8, 0, tzinfo=IST)
    db.add(
        SiteVisit(
            lead_id=lead["id"],
            project_id=project.id,
            host_id=me.id,
            created_by_id=me.id,
            visit_source="walk_in",
            scheduled_at=now + timedelta(hours=3),
        )
    )
    db.add(
        FollowUpTask(
            lead_id=lead["id"],
            assigned_to_id=me.id,
            created_by_id=me.id,
            task_type="call",
            due_at=now - timedelta(hours=2),
        )
    )
    await db.commit()

    assert await create_daily_digests(db, now) == 1
    await db.commit()
    note = await db.scalar(select(Notification).where(Notification.type == "daily_digest"))
    assert note.title == "Your day"
    assert note.body == "1 site visit today, 1 overdue"


async def test_call_and_visit_counts_hit_the_database(login_as, project, db):
    """Sanity check that rows really land where reports (Sprint 8) will read them."""
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    await c.post("/api/calls", json={"lead_id": lead["id"], "outcome": "interested"})
    await schedule(c, lead["id"], project.id)
    assert await db.scalar(select(CallLog.lead_id)) == lead["id"]
    assert (await db.get(SiteVisit, 1)).status.value == "scheduled"
    assert LeadStatus.visit_scheduled.value == await lead_status(c, lead["id"])
