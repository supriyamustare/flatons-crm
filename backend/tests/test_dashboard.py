"""Phase 1 gate: dashboard counts must reconcile with the underlying records (≥50 leads).

Expected values are computed with plain SQL written independently of the app's query code."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text, update

from app.demo import DEMO_DOMAIN, remove_demo, seed_demo
from app.models import Lead, Project, Role, User
from app.schemas.dashboard import DashboardQuery
from app.services.dashboard import build_dashboard

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 23, 11, 30, tzinfo=IST).astimezone(UTC)
CONNECTED = "('interested','callback','not_interested')"


def period(q: DashboardQuery) -> tuple[datetime, datetime]:
    today = NOW.astimezone(IST).date()
    start, end = {
        "today": (today, today),
        "7d": (today - timedelta(days=6), today),
        "30d": (today - timedelta(days=29), today),
        "custom": (q.date_from, q.date_to),
    }[q.range]
    return (
        datetime.combine(start, time.min, IST),
        datetime.combine(end + timedelta(days=1), time.min, IST),
    )


async def expected(db, q: DashboardQuery, user_id: int | None) -> dict:
    ps, pe = period(q)
    ds = datetime.combine(NOW.astimezone(IST).date(), time.min, IST)
    de = ds + timedelta(days=1)
    p = {"ps": ps, "pe": pe, "ds": ds, "de": de, "now": NOW, "u": user_id}
    mine_lead = "AND l.assigned_to_id = :u" if user_id else ""
    mine_task = "AND t.assigned_to_id = :u" if user_id else ""
    mine_call = "AND c.user_id = :u" if user_id else ""
    mine_visit = "AND (v.host_id = :u OR l.assigned_to_id = :u)" if user_id else ""

    async def one(sql: str) -> int:
        return (await db.execute(text(sql), p)).scalar_one()

    leads = f"FROM leads l WHERE l.deleted_at IS NULL {mine_lead}"
    tasks = (
        "FROM follow_up_tasks t JOIN leads l ON l.id = t.lead_id "
        f"WHERE l.deleted_at IS NULL AND t.status = 'pending' {mine_task}"
    )
    calls = (
        "FROM call_logs c JOIN leads l ON l.id = c.lead_id WHERE l.deleted_at IS NULL "
        f"AND c.called_at >= :ps AND c.called_at < :pe {mine_call}"
    )
    visits = (
        "FROM site_visits v JOIN leads l ON l.id = v.lead_id WHERE l.deleted_at IS NULL "
        f"AND v.scheduled_at >= :ps AND v.scheduled_at < :pe {mine_visit}"
    )
    n_calls = await one(f"SELECT count(*) {calls}")
    n_conn = await one(f"SELECT count(*) {calls} AND c.outcome IN {CONNECTED}")
    by_status = dict(
        (await db.execute(text(f"SELECT l.status, count(*) {leads} GROUP BY l.status"), p)).all()
    )
    return {
        "kpis": {
            "total_leads": await one(f"SELECT count(*) {leads}"),
            "new_leads": await one(
                f"SELECT count(*) {leads} AND l.created_at >= :ps AND l.created_at < :pe"
            ),
            "follow_ups_today": await one(
                f"SELECT count(*) {tasks} AND t.due_at >= :ds AND t.due_at < :de"
            ),
            "overdue_follow_ups": await one(f"SELECT count(*) {tasks} AND t.due_at < :now"),
            "visits_scheduled": await one(f"SELECT count(*) {visits} AND v.status <> 'cancelled'"),
            "visits_completed": await one(f"SELECT count(*) {visits} AND v.status = 'completed'"),
            "calls": n_calls,
            "calls_connected": n_conn,
            "connection_rate": round(n_conn / n_calls, 4) if n_calls else None,
        },
        "by_status": by_status,
    }


@pytest.fixture
async def dataset(db, make_user):
    admin = await make_user(Role.admin)
    counts = await seed_demo(db, password="demo-pass-123", leads=60, now=NOW)
    await db.commit()
    # One soft-deleted lead must disappear from every figure.
    first = await db.scalar(select(Lead).where(Lead.assigned_to_id.is_not(None)).order_by(Lead.id))
    await db.execute(update(Lead).where(Lead.id == first.id).values(deleted_at=NOW))
    await db.commit()
    ravi = await db.scalar(select(User).where(User.email == f"ravi.kumar{DEMO_DOMAIN}"))
    return admin, ravi, counts


QUERIES = [
    DashboardQuery(range="today"),
    DashboardQuery(range="7d"),
    DashboardQuery(range="30d"),
    DashboardQuery(range="custom", date_from=date(2026, 9, 1), date_to=date(2026, 10, 15)),
]


@pytest.mark.parametrize("q", QUERIES, ids=lambda q: q.range)
async def test_team_dashboard_reconciles_with_database(db, dataset, q):
    admin, _, counts = dataset
    assert counts["leads"] >= 50

    dash = await build_dashboard(db, admin, q, mine=False, now=NOW)
    want = await expected(db, q, None)

    assert dash.kpis.model_dump() == want["kpis"]
    assert {k.value: v for k, v in dash.leads_by_status.items() if v} == want["by_status"]
    assert sum(dash.leads_by_status.values()) == dash.kpis.total_leads == 59


@pytest.mark.parametrize("q", QUERIES, ids=lambda q: q.range)
async def test_executive_dashboard_reconciles_with_database(db, dataset, q):
    _, ravi, _ = dataset
    dash = await build_dashboard(db, ravi, q, mine=True, now=NOW)
    want = await expected(db, q, ravi.id)
    assert dash.kpis.model_dump() == want["kpis"]
    assert {k.value: v for k, v in dash.leads_by_status.items() if v} == want["by_status"]
    assert 0 < dash.kpis.total_leads < 59  # really scoped


async def test_dataset_exercises_every_figure(db, dataset):
    """Guard against a vacuous pass: the seeded data must make each KPI non-zero."""
    admin, _, _ = dataset
    dash = await build_dashboard(db, admin, DashboardQuery(range="30d"), mine=False, now=NOW)
    for name, value in dash.kpis.model_dump().items():
        assert value, f"{name} is zero/None in the test dataset"


async def test_alerts_and_feed_are_scoped(db, dataset):
    admin, ravi, _ = dataset
    team = await build_dashboard(db, admin, DashboardQuery(), mine=False, now=NOW)
    mine = await build_dashboard(db, ravi, DashboardQuery(), mine=True, now=NOW)
    assert 0 < len(team.overdue) <= 5
    assert all(t.assigned_to.id == ravi.id for t in mine.overdue)
    assert all(t.due_at < NOW for t in team.overdue)
    assert [t.due_at for t in team.overdue] == sorted(t.due_at for t in team.overdue)
    assert len(team.activity) == 15
    ravi_leads = set(await db.scalars(select(Lead.id).where(Lead.assigned_to_id == ravi.id)))
    assert all(a.lead_id in ravi_leads for a in mine.activity)


async def test_dashboard_endpoints_and_permissions(login_as):
    admin, _ = await login_as(Role.admin)
    mgr, _ = await login_as(Role.manager)
    ex, _ = await login_as(Role.executive)
    docs, _ = await login_as(Role.docs)

    r = await admin.get("/api/dashboard/admin", params={"range": "30d"})
    assert r.status_code == 200 and r.json()["scope"] == "team"
    assert set(r.json()["kpis"]) >= {"total_leads", "new_leads", "connection_rate"}
    assert r.json()["kpis"]["connection_rate"] is None  # no calls: N/A, not 0
    assert (await mgr.get("/api/dashboard/admin")).status_code == 200
    assert (await ex.get("/api/dashboard/admin")).status_code == 403
    assert (await ex.get("/api/dashboard/executive")).json()["scope"] == "mine"
    assert (await docs.get("/api/dashboard/executive")).status_code == 403
    assert (await docs.get("/api/dashboard/admin")).status_code == 403


@pytest.mark.parametrize(
    "params",
    [
        {"range": "custom"},
        {"range": "custom", "date_from": "2026-10-10", "date_to": "2026-10-01"},
        {"range": "custom", "date_from": "2024-01-01", "date_to": "2026-01-01"},
        {"range": "yesterday"},
    ],
)
async def test_invalid_ranges_are_rejected(login_as, params):
    c, _ = await login_as(Role.admin)
    assert (await c.get("/api/dashboard/admin", params=params)).status_code == 422


async def test_remove_demo_leaves_real_data_alone(db, make_user):
    real_user = await make_user(Role.executive)
    db.add(Project(name="Real Project"))
    db.add(
        Lead(
            lead_code="LEAD-REAL-1",
            name="Real Customer",
            mobile="+919812345678",
            source="website",
            created_by_id=real_user.id,
        )
    )
    await db.commit()
    await seed_demo(db, password="demo-pass-123", leads=10, now=NOW)
    await db.commit()

    await remove_demo(db)
    await db.commit()

    assert await db.scalar(select(Lead.name)) == "Real Customer"
    assert list(await db.scalars(select(Project.name))) == ["Real Project"]
    assert list(await db.scalars(select(User.id))) == [real_user.id]
