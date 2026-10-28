"""Dashboard insights reconciled with plain SQL on the demo dataset (plus real bookings)."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from app.demo import DEMO_DOMAIN, seed_demo
from app.models import Booking, CallLog, Lead, Role, Unit, UnitStatus, User
from app.services.insights import build_insights

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 27, 14, 0, tzinfo=IST).astimezone(UTC)
TODAY = NOW.astimezone(IST).date()
MONTH0 = TODAY.replace(day=1)
FIRST = date(2025, 11, 1)


def at(d: date) -> datetime:
    return datetime.combine(d, time.min, IST)


@pytest.fixture
async def data(db, make_user):
    admin = await make_user(Role.admin)
    await seed_demo(db, password="demo-pass-123", leads=60, now=NOW)
    await db.commit()
    booked = list(
        await db.scalars(select(Lead).where(Lead.status == "booked").order_by(Lead.id).limit(2))
    )
    units = list(
        await db.scalars(
            select(Unit).where(Unit.status == UnitStatus.available).order_by(Unit.id).limit(2)
        )
    )
    for i, (lead, unit) in enumerate(zip(booked, units, strict=True)):
        db.add(
            Booking(
                lead_id=lead.id,
                unit_id=unit.id,
                project_id=unit.project_id,
                booking_date=TODAY - timedelta(days=40 * i),
                agreed_price=7_000_000,
                booking_amount=0,
                sales_exec_id=lead.assigned_to_id,
            )
        )
        unit.status = UnitStatus.booked
    await db.commit()
    ravi = await db.scalar(select(User).where(User.email == f"ravi.kumar{DEMO_DOMAIN}"))
    return admin, ravi


async def rows(db, sql, **p):
    return (
        await db.execute(
            text(sql),
            {"now": NOW, "m0": at(MONTH0), "m0d": MONTH0, "first": at(FIRST), "firstd": FIRST, **p},
        )
    ).all()


async def test_project_inventory_reconciles(db, data):
    admin, _ = data
    ins = await build_insights(db, admin, person_id=None, now=NOW)
    want = {
        r[0]: r[1:]
        for r in await rows(
            db,
            """SELECT project_id,
        count(*) FILTER (WHERE status IN ('sold','booked')), count(*) FILTER (WHERE status = 'on_hold'),
        count(*) FILTER (WHERE status = 'available') FROM units WHERE status <> 'withdrawn' GROUP BY 1""",
        )
    }
    got = {p.id: (p.sold, p.blocked, p.available) for p in ins.projects if p.total}
    assert got == want and got
    for p in ins.projects:
        if p.total:
            assert p.total == p.sold + p.blocked + p.available and p.sold_pct == round(
                p.sold / p.total * 100, 1
            )
            assert p.unit_types and (p.price_min is None or p.price_min <= p.price_max)
    month = dict(
        (r[0], r[1])
        for r in await rows(
            db,
            "SELECT project_id, count(*) FROM bookings WHERE status='booked' AND booking_date >= :m0d GROUP BY 1",
        )
    )
    assert {p.id: p.bookings_this_month for p in ins.projects if p.bookings_this_month} == month


@pytest.mark.parametrize("who", ["team", "person"])
async def test_lead_status_waiting_months_and_sources_reconcile(db, data, who):
    admin, ravi = data
    pid = ravi.id if who == "person" else None
    ins = await build_insights(db, admin, person_id=pid, now=NOW)
    L = "l.deleted_at IS NULL" + (" AND l.assigned_to_id = :pid" if pid else "")
    p = {"pid": pid}

    status = dict(
        await rows(
            db,
            f"""SELECT CASE WHEN status = 'booked' THEN 'booked' WHEN status IN ('lost','junk') THEN 'dead'
        WHEN assigned_to_id IS NULL THEN 'unassigned' WHEN last_activity_at >= :week THEN 'working' ELSE 'quiet' END, count(*)
        FROM leads l WHERE {L} GROUP BY 1""",
            week=NOW - timedelta(days=7),
            **p,
        )
    )
    assert {s.key: s.count for s in ins.lead_status if s.count} == status
    assert ins.total_leads == sum(status.values())

    waiting = dict(
        await rows(
            db,
            f"""SELECT assigned_to_id, count(*) FROM leads l WHERE {L} AND status = 'new'
        AND NOT EXISTS (SELECT 1 FROM call_logs c WHERE c.lead_id = l.id) GROUP BY 1""",
            **p,
        )
    )
    assert {(w.user.id if w.user else None): w.count for w in ins.waiting_by_owner} == waiting

    leads_m = dict(
        await rows(
            db,
            f"""SELECT date_trunc('month', timezone('Asia/Kolkata', created_at))::date, count(*) FROM leads l
        WHERE {L} AND created_at >= :first GROUP BY 1""",
            **p,
        )
    )
    B = "b.status = 'booked'" + (" AND b.sales_exec_id = :pid" if pid else "")
    deals_m = dict(
        await rows(
            db,
            f"""SELECT m, count(*) FROM (
        SELECT date_trunc('month', b.booking_date)::date AS m FROM bookings b WHERE {B} AND b.booking_date >= :firstd
        UNION ALL
        SELECT date_trunc('month', timezone('Asia/Kolkata', l.status_changed_at))::date FROM leads l WHERE {L} AND l.status = 'booked'
          AND l.status_changed_at >= :first AND NOT EXISTS (SELECT 1 FROM bookings b2 WHERE b2.lead_id = l.id AND b2.status = 'booked')
        ) x GROUP BY m""",
            **p,
        )
    )
    assert len(ins.months) == 12 and ins.months[0].month == FIRST and ins.months[-1].month == MONTH0
    assert {m.month: m.leads for m in ins.months if m.leads} == leads_m
    assert {m.month: m.deals for m in ins.months if m.deals} == deals_m

    src = {
        r[0]: (r[1], r[2])
        for r in await rows(
            db,
            f"""SELECT source, count(*), count(*) FILTER (WHERE status = 'booked')
        FROM leads l WHERE {L} AND created_at >= :first GROUP BY 1""",
            **p,
        )
    }
    assert {s.source.value: (s.leads, s.sales) for s in ins.sources} == src


async def test_nothing_is_vacuous(db, data):
    admin, _ = data
    ins = await build_insights(db, admin, person_id=None, now=NOW)
    assert any(p.sold for p in ins.projects) and any(p.available for p in ins.projects)
    assert sum(m.leads for m in ins.months) and sum(m.deals for m in ins.months)
    assert ins.waiting_by_owner and ins.sources and ins.recent_bookings
    assert ins.scheduled_30d[0].key == "site_visit"


async def test_first_response_median_worked_example(db, make_user):
    """First calls after 30, 90, 600 and 1,500 minutes: median 345; 3 of 4 within 24 hours."""
    admin = await make_user(Role.admin)
    created = NOW - timedelta(days=2)
    for i, minutes in enumerate((30, 90, 600)):
        lead = Lead(
            lead_code=f"F-{i}",
            name=f"L{i}",
            mobile=f"+91900000001{i}",
            source="99acres",
            status="contacted",
            created_by_id=admin.id,
            created_at=created,
        )
        db.add(lead)
        await db.flush()
        db.add(
            CallLog(
                lead_id=lead.id,
                user_id=admin.id,
                outcome="interested",
                called_at=created + timedelta(minutes=minutes),
            )
        )
    late = Lead(
        lead_code="F-9",
        name="Late",
        mobile="+919000000019",
        source="99acres",
        status="contacted",
        created_by_id=admin.id,
        created_at=created,
    )
    db.add(late)
    await db.flush()
    db.add(
        CallLog(
            lead_id=late.id,
            user_id=admin.id,
            outcome="interested",
            called_at=created + timedelta(days=1, hours=1),
        )
    )
    await db.commit()
    ins = await build_insights(db, admin, person_id=None, now=NOW)
    assert ins.first_response_min == 345  # median of 30, 90, 600, 1500 = (90 + 600) / 2
    assert ins.contacted_within_day_pct == 75.0  # 3 of 4 within 24 hours


async def test_executives_get_their_own_and_docs_none(login_as):
    ex, ex_user = await login_as(Role.executive)
    r = await ex.get("/api/dashboard/insights", params={"person_id": 99999})
    assert r.status_code == 200
    docs, _ = await login_as(Role.docs)
    assert (await docs.get("/api/dashboard/insights")).status_code == 403
