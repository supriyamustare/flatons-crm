from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.models import AuditLog, Lead, Role, Unit
from tests.conftest import new_project

TODAY = datetime.now(UTC).date().isoformat()
PARTNER = {
    "name": "Amit Shah",
    "company_name": "Square Realty",
    "mobile": "98200 11111",
    "email": "amit@square.in",
    "rera_number": "a52100012345",
}


async def add_partner(c, **kw):
    r = await c.post("/api/channel-partners", json={**PARTNER, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_executives_can_add_partners_and_details_are_cleaned(login_as, db):
    ex, _ = await login_as(Role.executive)
    p = await add_partner(ex)
    assert (p["name"], p["company_name"], p["mobile"], p["email"], p["rera_number"]) == (
        "Amit Shah",
        "Square Realty",
        "+919820011111",
        "amit@square.in",
        "A52100012345",
    )
    assert (p["leads"], p["bookings"], p["is_active"]) == (0, 0, True)
    assert await db.scalar(select(AuditLog.id).where(AuditLog.action == "channel_partner.create"))
    docs, _ = await login_as(Role.docs)
    assert (await docs.get("/api/channel-partners")).status_code == 403


@pytest.mark.parametrize(
    "dup",
    [
        {"mobile": "+91 98200-11111", "rera_number": None},
        {"mobile": "9000000001", "rera_number": "A52100012345"},
    ],
    ids=["same mobile", "same RERA (any case)"],
)
async def test_no_duplicate_partners(login_as, dup):
    ex, _ = await login_as(Role.executive)
    await add_partner(ex)
    r = await ex.post("/api/channel-partners", json={**PARTNER, **dup})
    assert r.status_code == 409


@pytest.mark.parametrize(
    "bad", [{"name": ""}, {"mobile": "123"}, {"email": "not-an-email"}, {"rera_number": "<b>x</b>"}]
)
async def test_invalid_partner_details_rejected(login_as, bad):
    ex, _ = await login_as(Role.executive)
    assert (await ex.post("/api/channel-partners", json={**PARTNER, **bad})).status_code == 422


async def test_editing_and_deactivating_is_for_managers(login_as):
    ex, _ = await login_as(Role.executive)
    p = await add_partner(ex)
    assert (
        await ex.patch(f"/api/channel-partners/{p['id']}", json={"company_name": "X"})
    ).status_code == 403
    mgr, _ = await login_as(Role.manager)
    r = await mgr.patch(
        f"/api/channel-partners/{p['id']}",
        json={"company_name": "Square Realty LLP", "is_active": False},
    )
    assert (
        r.status_code == 200
        and r.json()["company_name"] == "Square Realty LLP"
        and r.json()["is_active"] is False
    )
    assert [x["id"] for x in (await mgr.get("/api/channel-partners")).json()] == []
    assert [
        x["id"]
        for x in (await mgr.get("/api/channel-partners", params={"include_inactive": True})).json()
    ] == [p["id"]]


async def test_search_by_name_company_or_rera(login_as):
    mgr, _ = await login_as(Role.manager)
    await add_partner(mgr)
    await add_partner(
        mgr,
        name="Neha Joshi",
        company_name="Prime Homes",
        mobile="9000000002",
        rera_number="P5210099",
    )
    for q, want in (
        ("amit", ["Amit Shah"]),
        ("prime", ["Neha Joshi"]),
        ("P52100", ["Neha Joshi"]),
        ("", ["Amit Shah", "Neha Joshi"]),
    ):
        assert [
            x["name"] for x in (await mgr.get("/api/channel-partners", params={"q": q})).json()
        ] == want


async def test_lead_partner_rules(login_as, db):
    ex, _ = await login_as(Role.executive)
    p = await add_partner(ex)
    ok = await ex.post(
        "/api/leads",
        json={
            "name": "Anita",
            "mobile": "9876543210",
            "source": "channel_partner",
            "channel_partner_id": p["id"],
        },
    )
    assert ok.status_code == 201 and ok.json()["lead"]["channel_partner"] == {
        "id": p["id"],
        "name": "Amit Shah",
        "company_name": "Square Realty",
    }
    wrong = await ex.post(
        "/api/leads",
        json={
            "name": "B",
            "mobile": "9123456780",
            "source": "99acres",
            "channel_partner_id": p["id"],
        },
    )
    assert (
        wrong.status_code == 422 and "only be set when the source is Channel partner" in wrong.text
    )
    missing = await ex.post(
        "/api/leads",
        json={
            "name": "C",
            "mobile": "9123456781",
            "source": "channel_partner",
            "channel_partner_id": 9999,
        },
    )
    assert missing.status_code == 422
    # Switching the lead to another source clears its partner
    lead_id = ok.json()["lead"]["id"]
    r = await ex.patch(f"/api/leads/{lead_id}", json={"source": "walk_in"})
    assert r.status_code == 200 and r.json()["channel_partner"] is None
    assert (await db.get(Lead, lead_id)).channel_partner_id is None


async def test_customers_tab_with_bookings_and_visibility(login_as, db):
    admin, _ = await login_as(Role.admin)
    ravi, _ = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    p = await add_partner(ravi)
    project = await new_project(db, "Habitat")
    await db.commit()
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "Habitat"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={"floor_from": 2, "floor_to": 2, "units_per_floor": 1, "unit_type": "studio"},
    )
    unit_id = await db.scalar(select(Unit.id))
    body = {"source": "channel_partner", "channel_partner_id": p["id"]}
    a = (
        await ravi.post("/api/leads", json={**body, "name": "Anita", "mobile": "9876543210"})
    ).json()["lead"]
    await kiran.post(
        "/api/leads", json={**body, "name": "Kiran's customer", "mobile": "9123456780"}
    )
    await ravi.post(
        "/api/leads", json={"name": "Not via partner", "mobile": "9000000009", "source": "walk_in"}
    )
    booking = (
        await ravi.post(
            "/api/bookings",
            json={
                "lead_id": a["id"],
                "unit_id": unit_id,
                "booking_date": TODAY,
                "agreed_price": 4_200_000,
                "booking_amount": 0,
            },
        )
    ).json()
    assert booking["partner"] == {
        "id": p["id"],
        "name": "Amit Shah",
        "company_name": "Square Realty",
    }

    team = (await mgr.get(f"/api/channel-partners/{p['id']}/customers")).json()
    assert team["total"] == 2 and {c["name"] for c in team["items"]} == {
        "Anita",
        "Kiran's customer",
    }
    anita = next(c for c in team["items"] if c["name"] == "Anita")
    assert (anita["booking_code"], anita["unit_no"], anita["agreed_price"], anita["status"]) == (
        booking["booking_code"],
        "201",
        4_200_000,
        "booked",
    )
    summary = (await mgr.get(f"/api/channel-partners/{p['id']}")).json()
    assert (summary["leads"], summary["bookings"], summary["booked_value"]) == (2, 1, 4_200_000)
    # Executives see only their own customers
    mine = (await ravi.get(f"/api/channel-partners/{p['id']}/customers")).json()
    assert [c["name"] for c in mine["items"]] == ["Anita"]
    assert (await ravi.get(f"/api/channel-partners/{p['id']}")).json()["leads"] == 1
