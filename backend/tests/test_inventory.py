import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    AuditLog,
    Building,
    Developer,
    LeadActivity,
    Project,
    ProjectType,
    Role,
    Unit,
    UnitStatus,
)
from app.services.inventory import release_expired_holds
from app.tasks.inventory import run_release_expired_holds
from tests.conftest import new_project


async def make_tower(admin, project_id, floors=3, per_floor=4, name="A Wing"):
    b = (await admin.post(f"/api/projects/{project_id}/buildings", json={"name": name})).json()
    r = await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={
            "floor_to": floors,
            "units_per_floor": per_floor,
            "unit_type": "2bhk",
            "carpet_sqft": 680,
            "builtup_sqft": 890,
            "base_price": 7200000,
        },
    )
    assert r.status_code == 201, r.text
    return b


async def unit_id(db, unit_no):
    return await db.scalar(select(Unit.id).where(Unit.unit_no == unit_no))


# ---- The Flatons/Developer rule lives in the database -----------------------


@pytest.mark.parametrize("bad", ["developer_without_developer", "resale_with_developer"])
async def test_database_enforces_developer_rule(db, bad):
    dev = Developer(name="Skyline")
    db.add(dev)
    await db.flush()
    if bad == "developer_without_developer":
        db.add(Project(name="P", project_type=ProjectType.developer))
    else:
        db.add(Project(name="P", project_type=ProjectType.resale, developer_id=dev.id))
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_database_enforces_hold_fields(db):
    project = await new_project(db, resale=True)
    db.add(Unit(project_id=project.id, unit_no="1", unit_type="2bhk", status=UnitStatus.on_hold))
    with pytest.raises(IntegrityError):
        await db.flush()


# ---- Projects ----------------------------------------------------------------


async def test_create_projects_and_developers(login_as):
    admin, _ = await login_as(Role.admin)
    r = await admin.post(
        "/api/projects",
        json={
            "name": "Green Meadows",
            "developer_name": "Skyline Developers",
            "location": "Baner, Pune",
            "status": "pre_launch",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["developer"]["name"] == "Skyline Developers"
    # Typing an existing developer's name (any case) reuses it rather than duplicating
    r2 = await admin.post(
        "/api/projects", json={"name": "Skyline Towers", "developer_name": "skyline developers"}
    )
    assert r2.json()["developer"]["id"] == r.json()["developer"]["id"]
    assert len((await admin.get("/api/developers")).json()) == 1

    resale = await admin.post(
        "/api/projects", json={"name": "Baner resale homes", "project_type": "resale"}
    )
    assert resale.status_code == 201 and resale.json()["developer"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"name": "No developer"},
        {"name": "Resale with dev", "project_type": "resale", "developer_name": "X"},
        {"name": "Both", "developer_id": 1, "developer_name": "X"},
        {"name": "Ghost dev", "developer_id": 999},
    ],
)
async def test_invalid_projects_rejected(login_as, body):
    admin, _ = await login_as(Role.admin)
    assert (await admin.post("/api/projects", json=body)).status_code == 422


async def test_switching_project_type_keeps_the_rule(login_as):
    admin, _ = await login_as(Role.admin)
    p = (await admin.post("/api/projects", json={"name": "P", "developer_name": "D"})).json()
    to_resale = await admin.patch(f"/api/projects/{p['id']}", json={"project_type": "resale"})
    assert to_resale.status_code == 200 and to_resale.json()["developer"] is None
    no_dev = await admin.patch(f"/api/projects/{p['id']}", json={"project_type": "developer"})
    assert no_dev.status_code == 422
    back = await admin.patch(
        f"/api/projects/{p['id']}", json={"project_type": "developer", "developer_name": "D"}
    )
    assert back.status_code == 200 and back.json()["developer"]["name"] == "D"


@pytest.mark.parametrize("role", [Role.manager, Role.executive, Role.docs])
async def test_only_admin_changes_inventory_but_everyone_can_look(login_as, db, role):
    admin, _ = await login_as(Role.admin)
    other, _ = await login_as(role)
    project = await new_project(db)
    b = await make_tower(admin, project.id, floors=1, per_floor=1)
    uid = await unit_id(db, "101")

    assert (
        await other.post("/api/projects", json={"name": "X", "project_type": "resale"})
    ).status_code == 403
    assert (
        await other.post(f"/api/projects/{project.id}/buildings", json={"name": "B"})
    ).status_code == 403
    assert (
        await other.post(
            f"/api/buildings/{b['id']}/generate",
            json={"floor_to": 2, "units_per_floor": 1, "unit_type": "2bhk"},
        )
    ).status_code == 403
    assert (await other.patch(f"/api/units/{uid}", json={"status": "sold"})).status_code == 403
    assert (await other.delete(f"/api/units/{uid}")).status_code == 403
    assert (await other.get(f"/api/projects/{project.id}/inventory")).status_code == 200
    assert (await other.get(f"/api/units/{uid}")).status_code == 200


# ---- Buildings, generator, inventory tree ------------------------------------


async def test_generator_numbers_units_and_builds_the_tree(login_as, db):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db)
    await make_tower(admin, project.id, floors=3, per_floor=4)

    inv = (await admin.get(f"/api/projects/{project.id}/inventory")).json()

    tower = inv["buildings"][0]
    assert [f["number"] for f in tower["floors"]] == [3, 2, 1]  # top floor first
    assert [u["unit_no"] for u in tower["floors"][0]["units"]] == ["301", "302", "303", "304"]
    assert inv["counts"] == {
        "total": 12,
        "available": 12,
        "on_hold": 0,
        "booked": 0,
        "sold": 0,
        "withdrawn": 0,
    }
    unit = tower["floors"][2]["units"][0]
    assert (
        unit["floor_number"] == 1
        and unit["carpet_sqft"] == "680.00"
        and unit["base_price"] == 7200000
    )


async def test_generator_ground_and_basement_and_natural_order(login_as, db):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db)
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Shops"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": -1, "floor_to": 0, "units_per_floor": 2, "unit_type": "shop"},
    )
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 1, "floor_to": 1, "units_per_floor": 12, "unit_type": "office"},
    )
    inv = (await admin.get(f"/api/projects/{project.id}/inventory")).json()
    floors = {
        f["number"]: [u["unit_no"] for u in f["units"]] for f in inv["buildings"][0]["floors"]
    }
    assert floors[-1] == ["B1-01", "B1-02"] and floors[0] == ["G01", "G02"]
    assert floors[1][:3] == ["101", "102", "103"] and floors[1][-1] == "112"


async def test_generator_refuses_clashes_and_silly_sizes(login_as, db):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db)
    b = await make_tower(admin, project.id, floors=2, per_floor=2)
    clash = await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 2, "floor_to": 3, "units_per_floor": 2, "unit_type": "2bhk"},
    )
    assert clash.status_code == 409 and "201" in clash.json()["detail"]
    for body in (
        {"floor_from": 5, "floor_to": 2, "units_per_floor": 2, "unit_type": "2bhk"},
        {"floor_to": 60, "units_per_floor": 20, "unit_type": "2bhk"},
        {
            "floor_to": 2,
            "units_per_floor": 2,
            "unit_type": "2bhk",
            "carpet_sqft": 900,
            "builtup_sqft": 800,
        },
    ):
        assert (
            await admin.post(f"/api/buildings/{b['id']}/generate", json=body)
        ).status_code == 422
    dup = await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "a wing"})
    assert dup.status_code == 409


async def test_resale_listings_have_no_buildings_or_floors(login_as, db):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Baner resale", resale=True)
    assert (
        await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "A"})
    ).status_code == 422
    r = await admin.post(
        f"/api/projects/{project.id}/units",
        json={
            "unit_no": "R-1",
            "unit_type": "3bhk",
            "current_asking_price": 13500000,
            "address_note": "Sai Residency, 7th floor",
        },
    )
    assert r.status_code == 201
    inv = (await admin.get(f"/api/projects/{project.id}/inventory")).json()
    assert inv["buildings"] == [] and [u["unit_no"] for u in inv["listings"]] == ["R-1"]
    assert (
        await admin.post(
            f"/api/projects/{project.id}/units",
            json={"unit_no": "R-2", "unit_type": "2bhk", "floor_id": 1},
        )
    ).status_code == 422


async def test_single_units_need_a_floor_in_the_same_project(login_as, db):
    admin, _ = await login_as(Role.admin)
    p1 = await new_project(db, "One")
    p2 = await new_project(db, "Two")
    b1 = await make_tower(admin, p1.id, floors=1, per_floor=1)
    floor = (await admin.post(f"/api/buildings/{b1['id']}/floors", json={"number": 2})).json()
    ok = await admin.post(
        f"/api/projects/{p1.id}/units",
        json={"unit_no": "201", "unit_type": "2bhk", "floor_id": floor["id"]},
    )
    assert ok.status_code == 201 and ok.json()["floor_number"] == 2
    assert (
        await admin.post(
            f"/api/projects/{p1.id}/units",
            json={"unit_no": "201", "unit_type": "2bhk", "floor_id": floor["id"]},
        )
    ).status_code == 409
    assert (
        await admin.post(f"/api/projects/{p1.id}/units", json={"unit_no": "9", "unit_type": "2bhk"})
    ).status_code == 422
    assert (
        await admin.post(
            f"/api/projects/{p2.id}/units",
            json={"unit_no": "9", "unit_type": "2bhk", "floor_id": floor["id"]},
        )
    ).status_code == 422


# ---- Holds -------------------------------------------------------------------


@pytest.fixture
async def tower(login_as, db):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db)
    await make_tower(admin, project.id, floors=2, per_floor=2)
    return project


async def test_manager_holds_unit_for_a_lead(login_as, db, tower):
    mgr, manager = await login_as(Role.manager)
    lead = (
        await mgr.post(
            "/api/leads", json={"name": "Anita", "mobile": "9876543210", "source": "website"}
        )
    ).json()["lead"]
    uid = await unit_id(db, "101")

    r = await mgr.patch(
        f"/api/units/{uid}/hold",
        json={"hours": 24, "lead_id": lead["id"], "note": "Token tomorrow"},
    )

    assert r.status_code == 200, r.text
    u = r.json()
    assert u["status"] == "on_hold" and u["held_by"]["id"] == manager.id
    assert u["held_for"] == {"id": lead["id"], "name": "Anita", "lead_code": lead["lead_code"]}
    assert u["hold_note"] == "Token tomorrow" and u["hold_expired"] is False
    held = await db.scalar(select(LeadActivity).where(LeadActivity.type == "unit_held"))
    assert held.lead_id == lead["id"] and held.details["unit_no"] == "101"
    assert await db.scalar(select(AuditLog).where(AuditLog.action == "unit.hold"))
    # Holding means it's no longer counted as available
    inv = (await mgr.get(f"/api/projects/{tower.id}/inventory")).json()
    assert inv["counts"]["available"] == 3 and inv["counts"]["on_hold"] == 1


@pytest.mark.parametrize("role", [Role.executive, Role.docs])
async def test_executives_and_docs_cannot_hold(login_as, db, tower, role):
    c, _ = await login_as(role)
    uid = await unit_id(db, "101")
    assert (await c.patch(f"/api/units/{uid}/hold", json={})).status_code == 403
    assert (await c.patch(f"/api/units/{uid}/release")).status_code == 403


async def test_cannot_hold_an_already_held_or_sold_unit(login_as, db, tower):
    a, _ = await login_as(Role.manager)
    b, _ = await login_as(Role.manager)
    admin, _ = await login_as(Role.admin)
    uid = await unit_id(db, "101")
    first = await a.patch(f"/api/units/{uid}/hold", json={})
    second = await b.patch(f"/api/units/{uid}/hold", json={})
    assert first.status_code == 200 and second.status_code == 409
    assert "already on hold by" in second.json()["detail"]

    sold = await unit_id(db, "102")
    await admin.patch(f"/api/units/{sold}", json={"status": "sold"})
    assert (await a.patch(f"/api/units/{sold}/hold", json={})).status_code == 409


async def test_simultaneous_holds_only_one_wins(login_as, db, tower):
    """Two managers press Hold on the same unit at the same instant, each on its own database
    connection. The row lock makes the second wait and then see the first's hold."""
    clients = [(await login_as(Role.manager))[0] for _ in range(5)]
    uid = await unit_id(db, "201")

    results = await asyncio.gather(*(c.patch(f"/api/units/{uid}/hold", json={}) for c in clients))

    codes = sorted(r.status_code for r in results)
    assert codes == [200, 409, 409, 409, 409], codes
    assert (
        await db.scalar(
            select(AuditLog.id).where(AuditLog.action == "unit.hold").limit(2).offset(1)
        )
        is None
    )


@pytest.mark.parametrize(
    "body",
    [
        {"hours": 0},
        {"hours": 400},
        {"hours": 5, "expires_at": "2030-01-01T00:00:00+05:30"},
        {"expires_at": "2020-01-01T00:00:00+05:30"},
    ],
)
async def test_hold_duration_limits(login_as, db, tower, body):
    mgr, _ = await login_as(Role.manager)
    uid = await unit_id(db, "101")
    assert (await mgr.patch(f"/api/units/{uid}/hold", json=body)).status_code == 422


async def test_release_and_rehold(login_as, db, tower):
    mgr, _ = await login_as(Role.manager)
    uid = await unit_id(db, "101")
    assert (await mgr.patch(f"/api/units/{uid}/release")).status_code == 409  # not held
    await mgr.patch(f"/api/units/{uid}/hold", json={})
    released = await mgr.patch(f"/api/units/{uid}/release")
    assert released.status_code == 200 and released.json()["status"] == "available"
    assert released.json()["held_by"] is None and released.json()["hold_expires_at"] is None
    assert (await mgr.patch(f"/api/units/{uid}/hold", json={})).status_code == 200


async def test_expired_holds_show_and_are_released_automatically(login_as, db, tower):
    mgr, _ = await login_as(Role.manager)
    lead = (
        await mgr.post(
            "/api/leads", json={"name": "Anita", "mobile": "9876543210", "source": "website"}
        )
    ).json()["lead"]
    uid = await unit_id(db, "101")
    await mgr.patch(f"/api/units/{uid}/hold", json={"lead_id": lead["id"]})
    await db.execute(
        update(Unit)
        .where(Unit.id == uid)
        .values(hold_expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()

    # Before the job runs, the screen already shows it as expired (gate item 2)
    shown = (await mgr.get(f"/api/units/{uid}")).json()
    assert shown["status"] == "on_hold" and shown["hold_expired"] is True
    # ...and someone else can take it straight away
    other, _ = await login_as(Role.manager)
    assert (await other.patch(f"/api/units/{uid}/hold", json={})).status_code == 200
    await db.execute(
        update(Unit)
        .where(Unit.id == uid)
        .values(hold_expires_at=datetime.now(UTC) - timedelta(minutes=1))
    )
    await db.commit()

    assert await run_release_expired_holds() == 1  # the 5-minute Celery job
    db.expire_all()
    assert (await db.get(Unit, uid)).status == UnitStatus.available
    entry = await db.scalar(
        select(AuditLog).where(AuditLog.action == "unit.release").order_by(AuditLog.id.desc())
    )
    assert entry.actor_id is None and entry.details["reason"] == "expired"
    assert await release_expired_holds(db) == 0  # nothing left


async def test_hold_expiry_job_is_scheduled_every_5_minutes():
    from app.tasks.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["release-expired-unit-holds"]
    assert entry["task"] == "inventory.release_expired_holds"
    assert entry["schedule"].minute == set(range(0, 60, 5))


# ---- Manual status, edits, deletes ------------------------------------------


async def test_admin_status_changes_and_guards(login_as, db, tower):
    admin, _ = await login_as(Role.admin)
    mgr, _ = await login_as(Role.manager)
    uid = await unit_id(db, "101")
    assert (await admin.patch(f"/api/units/{uid}", json={"status": "withdrawn"})).json()[
        "status"
    ] == "withdrawn"
    assert (
        await admin.patch(f"/api/units/{uid}", json={"status": "booked"})
    ).status_code == 422  # Sprint 11 only
    assert (await admin.patch(f"/api/units/{uid}", json={"status": "on_hold"})).status_code == 422
    assert (await admin.patch(f"/api/units/{uid}", json={"status": "available"})).status_code == 200

    await mgr.patch(f"/api/units/{uid}/hold", json={})
    assert (await admin.patch(f"/api/units/{uid}", json={"status": "sold"})).status_code == 409
    assert (await admin.delete(f"/api/units/{uid}")).status_code == 409
    building = await db.scalar(select(Building.id))
    assert (await admin.delete(f"/api/buildings/{building}")).status_code == 409

    assert (
        await admin.patch(f"/api/units/{uid}", json={"carpet_sqft": 950})
    ).status_code == 422  # > built-up 890
    price = await admin.patch(f"/api/units/{uid}", json={"current_asking_price": 7500000})
    assert price.json()["current_asking_price"] == 7500000
    free = await unit_id(db, "202")
    assert (await admin.delete(f"/api/units/{free}")).status_code == 204


async def test_project_list_shows_unit_counts(login_as, db, tower):
    c, _ = await login_as(Role.executive)
    projects = (await c.get("/api/projects")).json()
    assert projects[0]["units"]["total"] == 4 and projects[0]["units"]["available"] == 4
