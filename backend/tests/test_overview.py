"""The dashboard overview: every figure reconciled with plain SQL on the demo dataset."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.demo import DEMO_DOMAIN, seed_demo
from app.models import Booking, Lead, Role, Unit, UnitStatus, User
from app.services.overview import build_overview

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 27, 14, 0, tzinfo=IST).astimezone(UTC)  # a Tuesday
TODAY = NOW.astimezone(IST).date()
WEEK0, MONTH0 = TODAY - timedelta(days=TODAY.weekday()), TODAY.replace(day=1)


def at(d: date) -> datetime:
    return datetime.combine(d, time.min, IST)


@pytest.fixture
async def data(db, make_user):
    admin = await make_user(Role.admin)
    await seed_demo(db, password="demo-pass-123", leads=60, now=NOW)
    await db.commit()
    # Turn a few booked demo leads into real bookings, so sales figures aren't empty
    booked = list(await db.scalars(select(Lead).where(Lead.status == "booked").limit(3)))
    units = list(await db.scalars(select(Unit).where(Unit.status == UnitStatus.available).limit(3)))
    for i, (lead, unit) in enumerate(zip(booked, units, strict=False)):
        db.add(
            Booking(
                lead_id=lead.id,
                unit_id=unit.id,
                project_id=unit.project_id,
                booking_date=TODAY - timedelta(days=i * 3),
                agreed_price=7_000_000 + i * 500_000,
                booking_amount=200_000,
                sales_exec_id=lead.assigned_to_id,
            )
        )
        unit.status = UnitStatus.booked
    await db.commit()
    ravi = await db.scalar(select(User).where(User.email == f"ravi.kumar{DEMO_DOMAIN}"))
    return admin, ravi


async def one(db, sql, **p):
    return int(
        (
            await db.execute(
                text(sql),
                {
                    "now": NOW,
                    "today": at(TODAY),
                    "tomorrow": at(TODAY + timedelta(days=1)),
                    "w0": at(WEEK0),
                    "m0": at(MONTH0),
                    "w0d": WEEK0,
                    "m0d": MONTH0,
                    "tod": TODAY,
                    **p,
                },
            )
        ).scalar_one()
        or 0
    )


@pytest.mark.parametrize("who", ["team", "person"])
async def test_overview_reconciles_with_database(db, data, who):
    admin, ravi = data
    pid = ravi.id if who == "person" else None
    o = await build_overview(db, admin, person_id=pid, tab="fresh", now=NOW)
    L = "l.deleted_at IS NULL" + (" AND l.assigned_to_id = :pid" if pid else "")
    V = "l.deleted_at IS NULL" + (" AND v.host_id = :pid" if pid else "")
    T = "l.deleted_at IS NULL AND t.status = 'pending'" + (
        " AND t.assigned_to_id = :pid" if pid else ""
    )
    B = "b.status = 'booked'" + (" AND b.sales_exec_id = :pid" if pid else "")
    p = {"pid": pid}

    assert o.in_closing == await one(
        db, f"SELECT count(*) FROM leads l WHERE {L} AND status = 'negotiation'", **p
    )
    assert o.fresh_waiting == await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND status = 'new' AND NOT EXISTS (SELECT 1 FROM call_logs c WHERE c.lead_id = l.id)",
        **p,
    )
    assert o.followups_due == await one(
        db,
        f"SELECT count(*) FROM follow_up_tasks t JOIN leads l ON l.id = t.lead_id WHERE {T} AND t.due_at < :tomorrow",
        **p,
    )
    assert o.followups_overdue == await one(
        db,
        f"SELECT count(*) FROM follow_up_tasks t JOIN leads l ON l.id = t.lead_id WHERE {T} AND t.due_at < :now",
        **p,
    )
    assert o.visits_today == await one(
        db,
        f"SELECT count(*) FROM site_visits v JOIN leads l ON l.id = v.lead_id WHERE {V} AND v.status = 'scheduled' AND v.scheduled_at >= :today AND v.scheduled_at < :tomorrow",
        **p,
    )
    for key, start in (("week", "w0"), ("month", "m0")):
        assert getattr(o.visits_completed, key) == await one(
            db,
            f"SELECT count(*) FROM site_visits v JOIN leads l ON l.id = v.lead_id WHERE {V} AND v.status = 'completed' AND v.scheduled_at >= :{start} AND v.scheduled_at < :tomorrow",
            **p,
        )
        assert getattr(o.sales_closed, key) == await one(
            db, f"SELECT count(*) FROM bookings b WHERE {B} AND b.booking_date >= :{start}d", **p
        )
        assert getattr(o.sales_revenue, key) == await one(
            db,
            f"SELECT COALESCE(sum(agreed_price), 0) FROM bookings b WHERE {B} AND b.booking_date >= :{start}d",
            **p,
        )
    perf = o.performance
    assert perf.enquiries.month == await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND l.created_at >= :m0 AND l.created_at < :tomorrow",
        **p,
    )
    assert perf.sales.month == o.sales_closed.month
    assert len(perf.enquiries.daily) == 30 and perf.enquiries.daily[-1] == await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND l.created_at >= :today AND l.created_at < :tomorrow",
        **p,
    )
    if pid:
        assert (
            perf.spend is None
            and perf.cost_per_sale is None
            and o.scope == "person"
            and o.person.id == ravi.id
        )
    else:
        spend = await one(
            db,
            "SELECT COALESCE(sum(amount), 0) FROM expenses WHERE spent_on >= :m0d AND spent_on <= :tod",
        )
        assert perf.spend.month == spend
        assert perf.cost_per_sale == (round(spend / perf.sales.month) if perf.sales.month else None)

    reengage = await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND status NOT IN ('booked','lost','junk') AND last_activity_at < :stale",
        stale=NOW - timedelta(days=7),
        **p,
    )
    assert o.tab_counts["reengage"] == reengage
    assert o.tab_counts["closing"] == o.in_closing and o.tab_counts["fresh"] == o.fresh_waiting
    assert len(o.leads) == min(10, o.fresh_waiting)

    m = o.this_month
    assert m.new_leads == perf.enquiries.month
    open_leads = await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND status NOT IN ('booked','lost','junk')",
        **p,
    )
    assert m.active == await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND status NOT IN ('booked','lost','junk') AND last_activity_at >= :m0",
        **p,
    )
    assert m.active_rate == (round(m.active / open_leads, 4) if open_leads else None)
    won = await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND status = 'booked' AND status_changed_at >= :m0",
        **p,
    )
    lost = await one(
        db,
        f"SELECT count(*) FROM leads l WHERE {L} AND status IN ('lost','junk') AND status_changed_at >= :m0",
        **p,
    )
    assert m.win_rate == (round(won / (won + lost), 4) if won + lost else None)


async def test_dataset_is_not_vacuous(db, data):
    admin, _ = data
    o = await build_overview(db, admin, person_id=None, tab="fresh", now=NOW)
    assert (
        o.in_closing
        and o.fresh_waiting
        and o.followups_due
        and o.sales_closed.month
        and o.sales_revenue.month
    )
    assert o.performance.enquiries.month and o.performance.spend.month and o.tab_counts["reengage"]


@pytest.mark.parametrize("tab", ["fresh", "today", "visit", "closing", "reengage"])
async def test_each_tab_lists_its_leads(db, data, tab):
    admin, _ = data
    o = await build_overview(db, admin, person_id=None, tab=tab, now=NOW)
    assert o.tab == tab and len(o.leads) == min(10, o.tab_counts[tab])
    if tab in ("today", "visit"):
        assert all(lead.next_at for lead in o.leads)
    if tab == "visit":
        assert all(lead.next_action == "Site visit" for lead in o.leads)


async def test_change_vs_last_month(db, make_user):
    """5 enquiries so far this month vs 2 by the same day last month = +150%; none last month = None ("new")."""
    admin = await make_user(Role.admin)
    for i, when in enumerate(
        [NOW - timedelta(days=d) for d in (0, 1, 2, 3, 4)]
        + [NOW - timedelta(days=30), NOW - timedelta(days=31)]
        + [NOW - timedelta(days=28)]  # 29 Sep: after the same day last month
    ):
        db.add(
            Lead(
                lead_code=f"C-{i}",
                name=f"L{i}",
                mobile=f"+91900000000{i}",
                source="website",
                status="new",
                created_by_id=admin.id,
                created_at=when,
            )
        )
    await db.commit()
    o = await build_overview(db, admin, person_id=None, tab="fresh", now=NOW)
    assert (
        o.performance.enquiries.month,
        o.performance.enquiries.last_month,
        o.performance.enquiries.change_pct,
    ) == (5, 2, 150.0)
    assert o.performance.site_visits.change_pct is None


async def test_executives_always_see_their_own(login_as):
    ex, ex_user = await login_as(Role.executive)
    r = await ex.get("/api/dashboard/overview", params={"person_id": 999999})
    assert (
        r.status_code == 200
        and r.json()["scope"] == "person"
        and r.json()["person"]["id"] == ex_user.id
    )
    assert r.json()["people"] == [] and r.json()["performance"]["spend"] is None
    docs, _ = await login_as(Role.docs)
    assert (await docs.get("/api/dashboard/overview")).status_code == 403
    mgr, _ = await login_as(Role.manager)
    team = (await mgr.get("/api/dashboard/overview")).json()
    assert team["scope"] == "team" and {p["id"] for p in team["people"]} >= {ex_user.id}
