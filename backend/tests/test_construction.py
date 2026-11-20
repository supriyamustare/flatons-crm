from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, Role
from app.models.demand import Demand
from app.models.ledger import Ledger
from tests import test_ledger
from tests.test_demands import PNG, approved_ledger, project_id, report
from tests.test_ledger import TODAY

case = test_ledger.case


async def progress(c, pid, **form):
    files = form.pop("files", None)
    data = {"name": "Plinth", **{k: str(v) for k, v in form.items()}}
    return await c.post(f"/api/projects/{pid}/milestones/progress", data=data, files=files)


async def test_progress_is_history_and_delays_need_both_parts(login_as, db, case):
    pid = await project_id(db, case)
    pm, pm_user = await login_as(Role.project_manager)
    _, crm = await login_as(Role.crm_manager)
    r = await progress(
        pm,
        pid,
        percent_complete=40,
        planned_on=(TODAY + timedelta(days=30)).isoformat(),
        phase="Phase 1",
        building_label="Habitat",
        responsible_pm_id=pm_user.id,
        note="Shuttering done",
    )
    m = r.json()
    assert r.status_code == 200 and (
        m["percent_complete"],
        m["phase"],
        m["responsible_pm"]["id"],
        len(m["progress"]),
    ) == (40, "Phase 1", pm_user.id, 1)
    assert (
        await progress(pm, pid, delay_reason="Heavy rain")
    ).status_code == 422  # needs the revised date
    assert (
        await progress(pm, pid, revised_expected_on=(TODAY + timedelta(days=45)).isoformat())
    ).status_code == 422  # needs the reason
    assert (await progress(pm, pid, percent_complete=101)).status_code == 422
    assert (await progress(pm, pid)).status_code == 422  # nothing entered
    m = (
        await progress(
            pm,
            pid,
            percent_complete=55,
            delay_reason="Heavy rain",
            revised_expected_on=(TODAY + timedelta(days=45)).isoformat(),
            files=[("files", ("rain.png", PNG + b"\x09" * 30, "image/png"))],
        )
    ).json()
    assert (m["delay_reason"], m["percent_complete"], len(m["progress"])) == ("Heavy rain", 55, 2)
    assert (
        m["progress"][0]["photos"] and m["evidence"] == []
    )  # progress photos aren't completion evidence
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == crm.id, Notification.type == "milestone_delayed"
        )
    )
    ex, _ = await login_as(Role.executive)
    assert (await progress(ex, pid, percent_complete=10)).status_code == 403


async def test_progress_never_triggers_a_demand(login_as, db, case):
    """The specification's rule: a percentage or a photograph must not independently trigger a customer demand."""
    await approved_ledger(login_as, case)
    pid = await project_id(db, case)
    pm, _ = await login_as(Role.project_manager)
    await progress(
        pm,
        pid,
        percent_complete=100,
        note="Plinth complete",
        files=[("files", ("done.png", PNG + b"\x0a" * 30, "image/png"))],
    )
    assert await db.scalar(select(Demand.id)) is None
    ledger = await db.scalar(select(Ledger).where(Ledger.case_id == case))
    await db.refresh(ledger)
    assert next(i for i in ledger.schedule if i.name == "Plinth").demanded_on is None
    # Only verified completion does
    site, _ = await login_as(Role.site)
    crm, _ = await login_as(Role.crm_manager)
    m = (await report(site, pid)).json()
    await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/verify")
    assert await db.scalar(select(Demand.id)) is not None


async def test_schedule_impact_needs_someone_elses_approval(login_as, db, case):
    pid = await project_id(db, case)
    pm, _ = await login_as(Role.project_manager)
    m = (
        await progress(
            pm,
            pid,
            delay_reason="Steel shortage",
            revised_expected_on=(TODAY + timedelta(days=60)).isoformat(),
        )
    ).json()
    crm, _ = await login_as(Role.crm_manager)
    r = await crm.post(
        f"/api/projects/{pid}/milestones/{m['id']}/impact",
        json={"impact": "Plinth demand moves by about 2 months; possession unchanged"},
    )
    assert (
        r.json()["schedule_impact"].startswith("Plinth demand")
        and r.json()["can_approve_impact"] is False
    )  # recorded it
    assert (
        await crm.post(f"/api/projects/{pid}/milestones/{m['id']}/impact/approve")
    ).status_code == 403
    crm2, _ = await login_as(Role.crm_manager)
    r = await crm2.post(f"/api/projects/{pid}/milestones/{m['id']}/impact/approve")
    assert r.status_code == 200 and r.json()["impact_approved_by"] is not None
    assert (
        await crm2.post(f"/api/projects/{pid}/milestones/{m['id']}/impact/approve")
    ).status_code == 422


async def write(c, pid, **form):
    files = form.pop("photos", None)
    return await c.post(
        f"/api/projects/{pid}/updates",
        data={
            "title": "Plinth work under way",
            "body": "The plinth slab is being cast this month.",
            **form,
        },
        files=files,
    )


async def test_customer_updates_are_approved_published_and_corrections_kept(login_as, db, case):
    pid = await project_id(db, case)
    pm, _ = await login_as(Role.project_manager)
    crm, crm_user = await login_as(Role.crm_manager)
    items = (
        await write(pm, pid, photos=[("photos", ("site.png", PNG + b"\x0b" * 30, "image/png"))])
    ).json()
    u = items[0]
    assert (u["status"], len(u["photos"]), u["can_publish"]) == ("pending_approval", 1, False)
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == crm_user.id, Notification.type == "project_update_approval"
        )
    )
    crm_own = (await write(crm, pid, title="CRM's own update")).json()[0]
    assert (
        await crm.post(f"/api/project-updates/{crm_own['id']}/publish")
    ).status_code == 403  # never the author
    # Returned, edited, published
    r = (
        await crm.post(
            f"/api/project-updates/{u['id']}/return",
            json={"reason": "Add the expected completion month"},
        )
    ).json()
    assert next(x for x in r if x["id"] == u["id"])["status"] == "draft"
    await pm.put(
        f"/api/project-updates/{u['id']}",
        json={
            "title": "Plinth work under way",
            "body": "The plinth slab is being cast; completion expected in January.",
        },
    )
    r = (await crm.post(f"/api/project-updates/{u['id']}/publish")).json()
    pub = next(x for x in r if x["id"] == u["id"])
    assert pub["status"] == "published" and pub["published_at"]
    # Published: corrected, not edited; the earlier wording is kept
    assert (
        await pm.put(
            f"/api/project-updates/{u['id']}",
            json={"title": "x x x", "body": "changed after publishing"},
        )
    ).status_code == 422
    r = (
        await crm.post(
            f"/api/project-updates/{u['id']}/correct",
            json={
                "title": "Plinth work under way",
                "body": "The plinth slab is being cast; completion expected in February.",
                "reason": "Revised date from the site",
            },
        )
    ).json()
    c = next(x for x in r if x["id"] == u["id"])
    assert (
        "February" in c["body"]
        and c["corrections"][0]["previous_body"].endswith("January.")
        and c["corrections"][0]["reason"] == "Revised date from the site"
    )
    site, _ = await login_as(Role.site)
    assert (await write(site, pid)).status_code == 403
    legal, _ = await login_as(Role.legal)
    assert (await legal.get(f"/api/projects/{pid}/updates")).status_code == 200
    assert (await write(pm, pid, body="<script>x</script> longer text")).status_code == 422


async def test_the_reporting_project_manager_becomes_responsible(login_as, db, case):
    pid = await project_id(db, case)
    pm, pm_user = await login_as(Role.project_manager)
    m = (await progress(pm, pid, name="1st Slab", percent_complete=10)).json()
    assert m["responsible_pm"]["id"] == pm_user.id
    site, _ = await login_as(Role.site)
    m = (await progress(site, pid, name="2nd Slab", percent_complete=5)).json()
    assert m["responsible_pm"] is None  # site staff don't become the responsible PM
