"""Habitat data, unit price and area, cost sheets, customer details on bookings, and lead sources."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.cli_projects import load_projects
from app.models import Lead, Project, Role, Unit
from app.services.cost_sheet import compute
from tests.conftest import new_project

SEED = json.loads(
    (Path(__file__).parent.parent / "app" / "data" / "projects_seed.json").read_text()
)
HABITAT = SEED["projects"][0]["cost_sheet"]
TODAY = datetime.now(UTC).date().isoformat()


def test_cost_sheet_matches_the_developers_sheet():
    """Habitat 'cost sheet' tab: 267.7 sq ft at Rs 14,000."""
    cs = compute(
        project_name="Habitat",
        template=HABITAT,
        overrides=None,
        unit_no="1008",
        unit_label="",
        carpet_sqft=159.31,
        builtup_sqft=267.7,
        rate_psf=14000,
        asking_price=None,
    )
    assert (cs.cost, cs.gst, cs.furnishing, cs.stamp_duty, cs.registration, cs.legal_charges) == (
        3_747_800,
        37_478,
        110_772,
        262_400,
        30_000,
        10_000,
    )
    assert cs.fees_total == 302_400 and cs.grand_total == 3_747_800 + 37_478 + 110_772 + 302_400
    assert [s.name for s in cs.stages][:3] == ["Booking", "Registration", "Plinth"] and len(
        cs.stages
    ) == 17
    assert (cs.stages[0].amount, cs.stages[0].gst, cs.stages[3].amount) == (374_780, 3_748, 187_390)
    assert sum(s.amount for s in cs.stages) == cs.cost and cs.ready and len(cs.notes) == 12


def test_registration_is_capped_and_stamp_duty_rounds_up():
    small = compute(
        project_name="P",
        template=HABITAT,
        overrides=None,
        unit_no="1",
        unit_label="",
        carpet_sqft=None,
        builtup_sqft=100,
        rate_psf=10_001,
        asking_price=None,
    )  # cost 10,00,100
    assert small.registration == 10_001  # 1% under the cap
    assert small.stamp_duty == 70_100  # 70,007 rounded up to the next 100
    missing = compute(
        project_name="P",
        template=HABITAT,
        overrides=None,
        unit_no="1",
        unit_label="",
        carpet_sqft=None,
        builtup_sqft=None,
        rate_psf=None,
        asking_price=None,
    )
    assert (
        not missing.ready
        and set(missing.missing) == {"area", "price"}
        and missing.grand_total == 10_000
    )


async def test_loader_creates_habitat_and_optimids_and_is_safe_to_rerun(db):
    first = await load_projects(db)
    await db.commit()
    assert first == {
        "projects_created": 2,
        "projects_updated": 0,
        "units_created": 214,
        "units_filled": 0,
    }
    habitat = await db.scalar(select(Project).where(Project.name == "Habitat"))
    assert (
        float(habitat.commission_pct) == 3.5 and habitat.cost_sheet["furnishing_per_sqft"] == 413.79
    )
    counts = dict(
        (
            await db.execute(
                text("SELECT unit_type, count(*) FROM units WHERE project_id = :p GROUP BY 1"),
                {"p": habitat.id},
            )
        ).all()
    )
    assert counts == {"studio": 200, "shop": 14}
    room = await db.scalar(select(Unit).where(Unit.project_id == habitat.id, Unit.unit_no == "201"))
    assert (float(room.carpet_sqft), float(room.builtup_sqft)) == (200.32, 290.46)
    room.rate_psf = 15_000  # an admin's own entry must survive a re-run
    await db.commit()
    again = await load_projects(db)
    await db.commit()
    assert again == {
        "projects_created": 0,
        "projects_updated": 0,
        "units_created": 0,
        "units_filled": 0,
    }
    assert float((await db.get(Unit, room.id)).rate_psf) == 15_000
    assert (
        await db.scalar(select(func.count()).select_from(Project).where(Project.name == "Optimids"))
        == 1
    )


@pytest.fixture
async def unit(db, login_as):
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Habitat")
    project.cost_sheet = HABITAT
    project.commission_pct = 3.5
    await db.commit()
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Habitat"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 2, "floor_to": 2, "units_per_floor": 2, "unit_type": "studio"},
    )
    u = await db.scalar(select(Unit).where(Unit.unit_no == "201"))
    return project, u.id


async def test_managers_set_price_and_area_and_the_rate_sets_the_price(login_as, unit):
    _, uid = unit
    mgr, _ = await login_as(Role.manager)
    r = await mgr.patch(
        f"/api/units/{uid}", json={"carpet_sqft": 200.32, "builtup_sqft": 290.46, "rate_psf": 14000}
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_asking_price"] == 4_066_440 and r.json()["rate_psf"] == "14000.00"
    assert (
        await mgr.patch(f"/api/units/{uid}", json={"status": "withdrawn"})
    ).status_code == 403  # status stays admin-only
    assert (await mgr.patch(f"/api/units/{uid}", json={"rate_psf": -1})).status_code == 422
    ex, _ = await login_as(Role.executive)
    assert (await ex.patch(f"/api/units/{uid}", json={"rate_psf": 15000})).status_code == 403


async def test_unit_cost_sheet_edit_and_reset(login_as, unit):
    _, uid = unit
    mgr, _ = await login_as(Role.manager)
    await mgr.patch(f"/api/units/{uid}", json={"carpet_sqft": 200, "builtup_sqft": 290.46})
    cs = (
        await mgr.put(
            f"/api/units/{uid}/cost-sheet",
            json={"rate_psf": 14000, "legal_charges": 15000, "furnishing_per_sqft": 0},
        )
    ).json()
    assert cs["cost"] == 4_066_440 and cs["legal_charges"] == 15_000 and cs["furnishing"] == 0
    assert cs["overrides"] == {"legal_charges": 15000, "furnishing_per_sqft": 0}
    reset = (await mgr.put(f"/api/units/{uid}/cost-sheet", json={})).json()
    assert (
        reset["legal_charges"] == 10_000
        and reset["furnishing"] == round(290.46 * 413.79)
        and reset["cost"] == 4_066_440
    )
    docs, _ = await login_as(Role.docs)
    assert (await docs.get(f"/api/units/{uid}/cost-sheet")).status_code == 200
    assert (await docs.put(f"/api/units/{uid}/cost-sheet", json={})).status_code == 403


async def test_project_template_stages_must_total_100(login_as, unit):
    project, _ = unit
    admin, _ = await login_as(Role.admin)
    t = (await admin.get(f"/api/projects/{project.id}/cost-sheet")).json()
    assert t["developer_name"] == "Avnee Estates" and len(t["stages"]) == 17
    bad = {**t, "stages": [{"name": "Booking", "pct": 10}, {"name": "Rest", "pct": 80}]}
    r = await admin.put(f"/api/projects/{project.id}/cost-sheet", json=bad)
    assert r.status_code == 422 and "100%" in r.text
    ok = {
        **t,
        "rera_number": "P52100012345",
        "stages": [{"name": "Booking", "pct": 20}, {"name": "Rest", "pct": 80}],
    }
    assert (await admin.put(f"/api/projects/{project.id}/cost-sheet", json=ok)).json()[
        "rera_number"
    ] == "P52100012345"
    mgr, _ = await login_as(Role.manager)
    assert (await mgr.put(f"/api/projects/{project.id}/cost-sheet", json=ok)).status_code == 403


async def test_booking_with_customer_details_and_bank_payment(login_as, unit, db):
    _, uid = unit
    mgr, _ = await login_as(Role.manager)
    await mgr.patch(f"/api/units/{uid}", json={"builtup_sqft": 290.46, "carpet_sqft": 200})
    ravi, ravi_user = await login_as(Role.executive)
    lead = (
        await ravi.post(
            "/api/leads",
            json={"name": "Anita Desai", "mobile": "9876543210", "source": "magicbricks"},
        )
    ).json()["lead"]
    body = {
        "lead_id": lead["id"],
        "unit_id": uid,
        "booking_date": TODAY,
        "agreed_price": 4_200_000,
        "booking_amount": 420_000,
        "customer": {
            "applicant_name": "Anita & Rohan Desai",
            "customer_address": "Flat 4, Baner Road, Pune",
            "customer_email": "anita@example.com",
            "payment_preference": "bank",
            "bank_name": "HDFC Bank",
            "banker_name": "Suresh Iyer",
            "banker_phone": "+91 98220 11111",
        },
    }
    b = (await ravi.post("/api/bookings", json=body)).json()
    c = b["customer"]
    assert (
        c["customer_name"],
        c["customer_mobile"],
        c["applicant_name"],
        c["payment_preference"],
        c["bank_name"],
        c["banker_name"],
    ) == ("Anita Desai", "+919876543210", "Anita & Rohan Desai", "bank", "HDFC Bank", "Suresh Iyer")
    # The unit's cost sheet now uses the agreed price and shows the customer
    cs = (await ravi.get(f"/api/units/{uid}/cost-sheet")).json()
    assert (
        cs["cost"] == 4_200_000
        and cs["customer"]["name"] == "Anita Desai"
        and cs["customer"]["bank_name"] == "HDFC Bank"
    )
    # Switching to self payment clears the bank details
    r = await ravi.patch(f"/api/bookings/{b['id']}/customer", json={"payment_preference": "self"})
    assert (
        r.status_code == 200
        and r.json()["customer"]["bank_name"] is None
        and r.json()["customer"]["banker_name"] is None
    )
    assert [h["action"] for h in r.json()["history"]][-1] == "customer_updated"
    # Bank details without bank payment are refused; another executive can't edit
    assert (
        await ravi.patch(f"/api/bookings/{b['id']}/customer", json={"bank_name": "SBI"})
    ).status_code == 422
    kiran, _ = await login_as(Role.executive)
    assert (
        await kiran.patch(f"/api/bookings/{b['id']}/customer", json={"customer_address": "x"})
    ).status_code == 404
    assert (
        await mgr.patch(
            f"/api/bookings/{b['id']}/customer", json={"customer_address": "New address"}
        )
    ).status_code == 200


@pytest.mark.parametrize(
    "source,ok",
    [
        ("99acres", True),
        ("magicbricks", True),
        ("housing", True),
        ("social", True),
        ("google_ads", True),
        ("walk_in", True),
        ("website", False),
    ],
)
async def test_only_the_sources_in_use_for_new_leads(login_as, source, ok):
    c, _ = await login_as(Role.executive)
    r = await c.post("/api/leads", json={"name": "A", "mobile": "9876543210", "source": source})
    assert (r.status_code == 201) is ok


async def test_existing_leads_keep_a_retired_source_but_cant_switch_to_one(login_as, db):
    c, user = await login_as(Role.executive)
    lead = (
        await c.post("/api/leads", json={"name": "A", "mobile": "9876543210", "source": "99acres"})
    ).json()["lead"]
    assert (
        await c.patch(f"/api/leads/{lead['id']}", json={"source": "website"})
    ).status_code == 422
    await db.execute(text("UPDATE leads SET source = 'website' WHERE id = :i"), {"i": lead["id"]})
    await db.commit()
    r = await c.patch(
        f"/api/leads/{lead['id']}", json={"name": "A B", "source": "website"}
    )  # unchanged source is fine
    assert r.status_code == 200 and (await db.get(Lead, lead["id"])).source.value == "website"
    admin, _ = await login_as(Role.admin)
    assert (
        await admin.post("/api/integrations", json={"name": "Site", "kind": "website"})
    ).status_code == 422
    assert (
        await admin.post(
            "/api/campaigns", json={"name": "SMS", "channel": "sms_email", "start_date": TODAY}
        )
    ).status_code == 422
    assert (
        await admin.post(
            "/api/campaigns", json={"name": "Meta Oct", "channel": "social", "start_date": TODAY}
        )
    ).status_code == 201


async def test_blank_template_text_still_builds_a_cost_sheet(login_as, unit):
    project, uid = unit
    admin, _ = await login_as(Role.admin)
    t = (await admin.get(f"/api/projects/{project.id}/cost-sheet")).json()
    assert (
        await admin.put(
            f"/api/projects/{project.id}/cost-sheet",
            json={**t, "rera_number": "", "developer_name": "  "},
        )
    ).status_code == 200
    cs = await admin.get(f"/api/units/{uid}/cost-sheet")
    assert (
        cs.status_code == 200
        and cs.json()["rera_number"] == ""
        and cs.json()["developer_name"] == ""
    )


def test_stage_columns_always_add_up_to_the_totals():
    """290.46 sq ft at Rs 14,000: rounding each stage's GST separately would total Rs 40,660, not Rs 40,664."""
    cs = compute(
        project_name="Habitat",
        template=HABITAT,
        overrides=None,
        unit_no="201",
        unit_label="",
        carpet_sqft=200.32,
        builtup_sqft=290.46,
        rate_psf=14000,
        asking_price=None,
    )
    assert cs.cost == 4_066_440 and cs.gst == 40_664
    assert sum(s.amount for s in cs.stages) == cs.cost and sum(s.gst for s in cs.stages) == cs.gst
    odd = compute(
        project_name="P",
        template={
            **HABITAT,
            "stages": [
                {"name": "A", "pct": 33.33},
                {"name": "B", "pct": 33.33},
                {"name": "C", "pct": 33.34},
            ],
        },
        overrides=None,
        unit_no="1",
        unit_label="",
        carpet_sqft=None,
        builtup_sqft=333.33,
        rate_psf=12345.67,
        asking_price=None,
    )
    assert (
        sum(s.amount for s in odd.stages) == odd.cost and sum(s.gst for s in odd.stages) == odd.gst
    )
