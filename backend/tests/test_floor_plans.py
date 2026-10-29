"""Agreement done (shown instead of Sold) and floor plans."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Floor, FloorPlan, Role, Unit, UnitStatus
from app.services.insights import build_insights
from app.services.receipts import receipts_dir
from tests.conftest import new_project

TODAY = datetime.now(UTC).date()
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%plan\n"


@pytest.fixture
async def site(db, login_as):
    """Habitat with floors 1-2, two units per floor: 101 and 201 are studios, 102 and 202 shops."""
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Habitat")
    await db.commit()
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Habitat"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 1, "floor_to": 2, "units_per_floor": 2, "unit_type": "studio"},
    )
    for no in ("102", "202"):
        u = await db.scalar(select(Unit).where(Unit.unit_no == no))
        u.unit_type = "shop"
    await db.commit()
    units = {u.unit_no: u.id for u in await db.scalars(select(Unit))}
    floors = {f.number: f.id for f in await db.scalars(select(Floor))}
    return project, units, floors


async def book(c, db, unit_id, name="Anita", mobile="9876543210"):
    lead = (
        await c.post("/api/leads", json={"name": name, "mobile": mobile, "source": "99acres"})
    ).json()["lead"]
    r = await c.post(
        "/api/bookings",
        json={
            "lead_id": lead["id"],
            "unit_id": unit_id,
            "booking_date": TODAY.isoformat(),
            "agreed_price": 4_000_000,
            "booking_amount": 0,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------- agreement done


async def test_mark_agreement_done_and_undo(login_as, db, site):
    _, units, _ = site
    ravi, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    b = await book(ravi, db, units["101"])
    assert (
        await ravi.post(
            f"/api/bookings/{b['id']}/agreement", json={"agreement_date": TODAY.isoformat()}
        )
    ).status_code == 403

    r = await mgr.post(
        f"/api/bookings/{b['id']}/agreement", json={"agreement_date": TODAY.isoformat()}
    )

    assert r.status_code == 200 and r.json()["agreement_date"] == TODAY.isoformat()
    assert r.json()["history"][-1]["action"] == "agreement_done"
    db.expire_all()
    assert (await db.get(Unit, units["101"])).status == UnitStatus.sold  # shown as "Agreement done"
    undo = await mgr.delete(f"/api/bookings/{b['id']}/agreement")
    assert undo.status_code == 200 and undo.json()["agreement_date"] is None
    db.expire_all()
    assert (await db.get(Unit, units["101"])).status == UnitStatus.booked


@pytest.mark.parametrize(
    "delta,ok", [(0, True), (1, False), (-1, False)], ids=["today", "future", "before booking"]
)
async def test_agreement_date_rules(login_as, db, site, delta, ok):
    _, units, _ = site
    mgr, _ = await login_as(Role.manager)
    b = await book(mgr, db, units["101"])
    r = await mgr.post(
        f"/api/bookings/{b['id']}/agreement",
        json={"agreement_date": (TODAY + timedelta(days=delta)).isoformat()},
    )
    assert (r.status_code == 200) is ok


async def test_cancelling_after_agreement_frees_the_flat(login_as, db, site):
    _, units, _ = site
    mgr, _ = await login_as(Role.manager)
    b = await book(mgr, db, units["101"])
    await mgr.post(f"/api/bookings/{b['id']}/agreement", json={"agreement_date": TODAY.isoformat()})
    assert (
        await mgr.post(f"/api/bookings/{b['id']}/cancel", json={"reason": "Agreement cancelled"})
    ).status_code == 200
    db.expire_all()
    assert (await db.get(Unit, units["101"])).status == UnitStatus.available
    assert (
        await mgr.post(
            f"/api/bookings/{b['id']}/agreement", json={"agreement_date": TODAY.isoformat()}
        )
    ).status_code == 422


async def test_dashboard_counts_agreement_done_and_booked_separately(login_as, db, site):
    project, units, _ = site
    mgr, manager = await login_as(Role.manager)
    a = await book(mgr, db, units["101"])
    await book(mgr, db, units["201"], "Rahul", "9123456780")
    await mgr.post(f"/api/bookings/{a['id']}/agreement", json={"agreement_date": TODAY.isoformat()})
    ins = await build_insights(db, manager, person_id=None)
    p = next(x for x in ins.projects if x.id == project.id)
    assert (p.agreement_done, p.booked, p.sold, p.available, p.total) == (1, 1, 2, 2, 4)


# ---------------------------------------------------------------- floor plans


async def upload(c, project_id, title, content=PNG, name="plan.png", **form):
    return await c.post(
        f"/api/projects/{project_id}/floor-plans",
        data={"title": title, **{k: str(v) for k, v in form.items()}},
        files={"file": (name, content, "application/octet-stream")},
    )


async def test_floor_plans_match_units(login_as, site):
    project, units, floors = site
    mgr, _ = await login_as(Role.manager)
    master = (await upload(mgr, project.id, "Site master plan", PDF, "master.pdf")).json()
    assert master["applies_to"] == "Whole project" and master["file_type"] == "application/pdf"
    floor2 = (await upload(mgr, project.id, "Floor 2 layout", floor_id=floors[2])).json()
    assert floor2["applies_to"] == "Floor 2"
    shop = (await upload(mgr, project.id, "Shop plan", unit_type="shop")).json()
    assert shop["applies_to"] == "Shop units"

    async def titles(no):
        return [p["title"] for p in (await mgr.get(f"/api/units/{units[no]}/floor-plans")).json()]

    assert await titles("201") == ["Floor 2 layout"]  # its floor
    assert set(await titles("202")) == {"Floor 2 layout", "Shop plan"}  # its floor and its type
    assert await titles("102") == ["Shop plan"]  # its type
    assert await titles("101") == ["Site master plan"]  # nothing specific: whole-project plans
    docs, _ = await login_as(Role.docs)
    f = await docs.get(f"/api/floor-plans/{master['id']}/file")
    assert (
        f.status_code == 200
        and f.content == PDF
        and f.headers["content-disposition"].startswith("inline")
    )
    assert len(await titles("201")) == 1


async def test_floor_plan_rules(login_as, db, site):
    project, _, floors = site
    mgr, _ = await login_as(Role.manager)
    ex, _ = await login_as(Role.executive)
    assert (await upload(ex, project.id, "X")).status_code == 403
    assert (
        await upload(mgr, project.id, "Both", floor_id=floors[1], unit_type="shop")
    ).status_code == 422
    assert (
        await upload(mgr, project.id, "Program", b"MZ\x90\x00 not a plan", "plan.pdf")
    ).status_code == 422
    assert (
        await upload(
            mgr, project.id, "Too big", b"%PDF-" + b"0" * (15 * 1024 * 1024 + 10), "big.pdf"
        )
    ).status_code == 422
    other = await new_project(db, "Elsewhere")
    await db.commit()
    assert (await upload(mgr, other.id, "Wrong floor", floor_id=floors[1])).status_code == 422
    plan = (await upload(mgr, project.id, "Keep")).json()
    stored = await db.scalar(select(FloorPlan.file_path).where(FloorPlan.id == plan["id"]))
    assert (receipts_dir("floor_plans") / stored).exists()
    assert (await ex.delete(f"/api/floor-plans/{plan['id']}")).status_code == 403
    assert (await mgr.delete(f"/api/floor-plans/{plan['id']}")).status_code == 204
    assert not (receipts_dir("floor_plans") / stored).exists()
