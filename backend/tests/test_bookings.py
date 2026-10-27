import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select, text, update

from app.models import (
    BookingEvent,
    Lead,
    LeadActivity,
    LeadStatus,
    Notification,
    Role,
    Unit,
    UnitStatus,
)
from app.schemas.dashboard import DashboardQuery
from app.services.dashboard import build_dashboard
from tests.conftest import new_project

TODAY = datetime.now(UTC).date().isoformat()


@pytest.fixture
async def flats(db, login_as):
    """A project at 2% commission with one building, 2 floors x 2 units (101, 102, 201, 202)."""
    admin, _ = await login_as(Role.admin)
    project = await new_project(db, "Green Meadows")
    project.commission_pct = 2
    await db.commit()
    b = (await admin.post(f"/api/projects/{project.id}/buildings", json={"name": "A Wing"})).json()
    await admin.post(
        f"/api/buildings/{b['id']}/generate",
        json={
            "floor_to": 2,
            "units_per_floor": 2,
            "unit_type": "2bhk",
            "carpet_sqft": 680,
            "builtup_sqft": 890,
            "base_price": 7_000_000,
        },
    )
    units = {u.unit_no: u.id for u in await db.scalars(select(Unit))}
    return project, units


async def new_lead(c, name="Anita Desai", mobile="9876543210"):
    return (
        await c.post("/api/leads", json={"name": name, "mobile": mobile, "source": "website"})
    ).json()["lead"]


def booking_body(lead_id, unit_id, **kw):
    return {
        "lead_id": lead_id,
        "unit_id": unit_id,
        "booking_date": TODAY,
        "agreed_price": 7_200_000,
        "booking_amount": 200_000,
        "payment_mode": "cheque",
        "payment_reference": "CHQ 004512",
        **kw,
    }


async def test_executive_books_a_flat_and_managers_are_notified(login_as, db, flats):
    project, units = flats
    _, manager = await login_as(Role.manager)
    _, admin2 = await login_as(Role.admin)
    ravi, ravi_user = await login_as(Role.executive)
    manager_id, admin2_id, ravi_id = manager.id, admin2.id, ravi_user.id
    lead = await new_lead(ravi)

    r = await ravi.post(
        "/api/bookings",
        json=booking_body(lead["id"], units["201"], channel_partner="Square Realty"),
    )

    assert r.status_code == 201, r.text
    b = r.json()
    assert b["booking_code"].startswith("BKG-") and b["status"] == "booked"
    assert (
        b["unit"]["unit_no"],
        b["unit"]["building"],
        b["unit"]["floor_number"],
        b["project"]["name"],
    ) == ("201", "A Wing", 2, "Green Meadows")
    assert (b["agreed_price"], b["booking_amount"], b["balance"]) == (7_200_000, 200_000, 7_000_000)
    assert b["commission_expected"] == 144_000  # 2% of ₹72 L
    assert b["sales_exec"]["id"] == ravi_id and b["recorded_by"]["id"] == ravi_id
    assert [h["action"] for h in b["history"]] == ["created"]
    db.expire_all()
    assert (await db.get(Unit, units["201"])).status == UnitStatus.booked
    lead_row = await db.get(Lead, lead["id"])
    assert lead_row.status == LeadStatus.booked and lead_row.project_id == project.id
    notified = set(
        await db.scalars(select(Notification.user_id).where(Notification.type == "booking"))
    )
    assert {manager_id, admin2_id} <= notified and ravi_id not in notified
    note = await db.scalar(
        select(Notification).where(
            Notification.user_id == manager_id, Notification.type == "booking"
        )
    )
    assert (
        "unit 201" in note.body
        and "₹7,200,000" in note.body
        and note.link == f"/bookings/{b['id']}"
    )
    assert await db.scalar(select(LeadActivity.id).where(LeadActivity.type == "booked"))


async def test_five_people_booking_the_same_flat_at_once_only_one_wins(login_as, flats):
    _, units = flats
    clients = []
    for i in range(5):
        c, _ = await login_as(Role.executive)
        clients.append((c, await new_lead(c, f"Buyer {i}", f"98765432{i}1")))
    results = await asyncio.gather(
        *(
            c.post("/api/bookings", json=booking_body(lead["id"], units["101"]))
            for c, lead in clients
        )
    )
    codes = sorted(r.status_code for r in results)
    assert codes == [201, 409, 409, 409, 409], codes


async def test_flat_and_lead_rules(login_as, db, flats):
    _, units = flats
    ravi, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    a = await new_lead(ravi)
    b = await new_lead(ravi, "Rahul", "9123456780")
    assert (
        await ravi.post("/api/bookings", json=booking_body(a["id"], units["101"]))
    ).status_code == 201
    # Same flat again, and same lead again
    assert (
        await ravi.post("/api/bookings", json=booking_body(b["id"], units["101"]))
    ).status_code == 409
    assert (
        await ravi.post("/api/bookings", json=booking_body(a["id"], units["102"]))
    ).status_code == 409
    # Held for someone else
    other = await new_lead(mgr, "Priya", "9988776655")
    await mgr.patch(f"/api/units/{units['202']}/hold", json={"lead_id": other["id"]})
    held = await ravi.post("/api/bookings", json=booking_body(b["id"], units["202"]))
    assert held.status_code == 409 and "on hold for another" in held.json()["detail"]
    # ...but the customer it's held for can book it, and the hold is cleared
    assert (
        await mgr.post("/api/bookings", json=booking_body(other["id"], units["202"]))
    ).status_code == 201
    db.expire_all()
    u = await db.get(Unit, units["202"])
    assert u.status == UnitStatus.booked and u.held_by_id is None


@pytest.mark.parametrize(
    "change",
    [
        {"booking_amount": 9_000_000},
        {"agreed_price": 0},
        {"booking_date": (date.today() + timedelta(days=3)).isoformat()},
        {"booking_date": "2020-01-01"},
        {"payment_mode": "barter"},
    ],
)
async def test_invalid_bookings_rejected(login_as, flats, change):
    _, units = flats
    c, _ = await login_as(Role.executive)
    lead = await new_lead(c)
    assert (
        await c.post("/api/bookings", json=booking_body(lead["id"], units["101"], **change))
    ).status_code == 422


async def test_executive_cannot_book_someone_elses_lead_and_docs_cannot_book(login_as, flats):
    _, units = flats
    ravi, _ = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    docs, _ = await login_as(Role.docs)
    lead = await new_lead(ravi)
    assert (
        await kiran.post("/api/bookings", json=booking_body(lead["id"], units["101"]))
    ).status_code == 404
    assert (
        await docs.post("/api/bookings", json=booking_body(lead["id"], units["101"]))
    ).status_code == 403


async def test_cancel_releases_the_flat_and_reopens_the_lead(login_as, db, flats):
    _, units = flats
    ravi, ravi_user = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    lead = await new_lead(ravi)
    bid = (await ravi.post("/api/bookings", json=booking_body(lead["id"], units["101"]))).json()[
        "id"
    ]
    assert (
        await ravi.post(f"/api/bookings/{bid}/cancel", json={"reason": "Loan not approved"})
    ).status_code == 403
    assert (
        await mgr.post(f"/api/bookings/{bid}/cancel", json={"reason": "x"})
    ).status_code == 422  # too short

    r = await mgr.post(f"/api/bookings/{bid}/cancel", json={"reason": "Loan not approved"})

    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["cancellation_reason"] == "Loan not approved"
    db.expire_all()
    assert (await db.get(Unit, units["101"])).status == UnitStatus.available
    assert (await db.get(Lead, lead["id"])).status == LeadStatus.negotiation
    assert await db.scalar(
        select(Notification.id).where(
            Notification.user_id == ravi_user.id, Notification.type == "booking_cancelled"
        )
    )
    # The flat can be booked again, and the lead can book again
    assert (
        await ravi.post("/api/bookings", json=booking_body(lead["id"], units["101"]))
    ).status_code == 201
    assert (
        await mgr.post(f"/api/bookings/{bid}/cancel", json={"reason": "again"})
    ).status_code == 422


async def test_managers_edit_details_and_record_commission_received(login_as, db, flats):
    _, units = flats
    ravi, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    lead = await new_lead(ravi)
    bid = (await ravi.post("/api/bookings", json=booking_body(lead["id"], units["101"]))).json()[
        "id"
    ]
    assert (
        await ravi.patch(f"/api/bookings/{bid}", json={"booking_amount": 300_000})
    ).status_code == 403

    r = await mgr.patch(
        f"/api/bookings/{bid}", json={"agreed_price": 7_500_000, "booking_amount": 500_000}
    )
    assert (
        r.json()["commission_expected"] == 150_000 and r.json()["balance"] == 7_000_000
    )  # recalculated from new price
    r = await mgr.patch(f"/api/bookings/{bid}", json={"commission_received": 75_000})
    assert r.json()["commission_received"] == 75_000
    actions = [h["action"] for h in r.json()["history"]]
    assert actions == ["created", "edited", "commission_received"]
    edited = await db.scalar(select(BookingEvent).where(BookingEvent.action == "edited"))
    assert edited.details["agreed_price"] == {"from": "7200000", "to": "7500000"}
    assert (
        await mgr.patch(f"/api/bookings/{bid}", json={"booking_amount": 9_000_000})
    ).status_code == 422


async def test_list_visibility_totals_and_missing_details(login_as, db, flats):
    _, units = flats
    ravi, ravi_user = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    docs, _ = await login_as(Role.docs)
    await ravi.post("/api/bookings", json=booking_body((await new_lead(ravi))["id"], units["101"]))
    await kiran.post(
        "/api/bookings",
        json=booking_body(
            (await new_lead(kiran, "K", "9123456780"))["id"], units["102"], agreed_price=8_000_000
        ),
    )
    # A lead marked Booked by status only (as before bookings existed)
    old = await new_lead(ravi, "Old Booking", "9000000001")
    await db.execute(update(Lead).where(Lead.id == old["id"]).values(status="booked"))
    await db.commit()

    team = (await mgr.get("/api/bookings")).json()
    assert team["total"] == 2 and team["totals"]["agreed_value"] == 15_200_000
    assert team["totals"]["commission_expected"] == 144_000 + 160_000
    assert [m["name"] for m in team["missing_details"]] == ["Old Booking"]
    mine = (await ravi.get("/api/bookings")).json()
    assert mine["total"] == 1 and mine["items"][0]["sales_exec"]["id"] == ravi_user.id
    assert [m["name"] for m in mine["missing_details"]] == ["Old Booking"]
    assert (await kiran.get("/api/bookings")).json()["missing_details"] == []
    assert (await docs.get("/api/bookings")).json()[
        "total"
    ] == 2  # documents staff need to see all bookings
    # Filling in the details removes it from "missing"
    assert (
        await ravi.post("/api/bookings", json=booking_body(old["id"], units["201"]))
    ).status_code == 201
    assert (await mgr.get("/api/bookings")).json()["missing_details"] == []


async def test_csv_export_is_for_managers(login_as, flats):
    _, units = flats
    ravi, _ = await login_as(Role.executive)
    mgr, _ = await login_as(Role.manager)
    await ravi.post("/api/bookings", json=booking_body((await new_lead(ravi))["id"], units["101"]))
    assert (await ravi.get("/api/bookings/export")).status_code == 403
    r = await mgr.get("/api/bookings/export")
    body = r.content.decode("utf-8")
    assert (
        body.startswith("\ufeff")
        and "Agreed price" in body
        and "Anita Desai" in body
        and "7200000" in body
    )


async def test_dashboard_revenue_uses_the_real_agreed_price(login_as, db, flats):
    """Deal value says ₹60 L, booking says ₹72 L: revenue must be 2% of ₹72 L."""
    _, units = flats
    ravi, _ = await login_as(Role.executive)
    admin = await db.scalar(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1"))
    lead = await new_lead(ravi)
    await db.execute(update(Lead).where(Lead.id == lead["id"]).values(estimated_value=6_000_000))
    await db.commit()
    await ravi.post("/api/bookings", json=booking_body(lead["id"], units["101"]))
    from app.models import User

    biz = (
        await build_dashboard(
            db, await db.get(User, admin), DashboardQuery(range="today"), mine=False
        )
    ).business
    assert biz.leads_booked == 1 and biz.revenue == 144_000 and biz.unvalued_bookings == 0
