from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text, update

from app.demo import DEMO_DOMAIN, seed_demo
from app.models import AuditLog, Lead, LeadStatus, PipelineStage, Role, User
from app.schemas.pipeline import PipelineQuery
from app.services.pipeline import build_board, build_forecast
from tests.conftest import new_project

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 26, 11, 0, tzinfo=IST).astimezone(UTC)
OPEN_SQL = (
    "('new','not_reachable','contacted','qualified','follow_up',"
    "'visit_scheduled','visit_done','revisit','negotiation','on_hold')"
)
VALUE = "COALESCE(l.estimated_value, l.budget_max, l.budget_min)"


@pytest.fixture
async def dataset(db, make_user):
    admin = await make_user(Role.admin)
    await seed_demo(db, password="demo-pass-123", leads=60, now=NOW)
    await db.commit()
    gone = await db.scalar(select(Lead.id).order_by(Lead.id))
    await db.execute(update(Lead).where(Lead.id == gone).values(deleted_at=NOW))
    # A few leads with no value at all, so "missing value" is exercised
    await db.execute(
        update(Lead)
        .where(Lead.id.in_(select(Lead.id).order_by(Lead.id.desc()).limit(3)))
        .values(estimated_value=None, budget_min=None, budget_max=None)
    )
    await db.commit()
    ravi = await db.scalar(select(User).where(User.email == f"ravi.kumar{DEMO_DOMAIN}"))
    return admin, ravi


async def sql_rows(db, user_id=None):
    mine = "AND l.assigned_to_id = :u" if user_id else ""
    rows = await db.execute(
        text(f"""
        SELECT l.status,
               count(*),
               COALESCE(sum({VALUE}), 0),
               count(*) FILTER (WHERE l.status IN {OPEN_SQL} AND l.last_activity_at < :stale),
               count(*) FILTER (WHERE {VALUE} IS NULL),
               ps.probability_pct
        FROM leads l JOIN pipeline_stages ps ON ps.stage = l.status
        WHERE l.deleted_at IS NULL {mine}
        GROUP BY l.status, ps.probability_pct"""),
        {"u": user_id, "stale": NOW - timedelta(days=7)},
    )
    return {r[0]: r[1:] for r in rows}


@pytest.mark.parametrize("mine", [False, True], ids=["team", "executive"])
async def test_board_reconciles_with_database(db, dataset, mine):
    admin, ravi = dataset
    user = ravi if mine else admin
    board = await build_board(db, user, PipelineQuery(include_closed=True, per_stage=200), now=NOW)
    want = await sql_rows(db, ravi.id if mine else None)

    assert {c.stage.value for c in board.stages if c.count} == set(want)
    for col in board.stages:
        n, value, stale, missing, pct = want.get(col.stage.value, (0, 0, 0, 0, col.probability_pct))
        assert (col.count, col.value, col.stale_count, col.missing_value_count) == (
            n,
            value,
            stale,
            missing,
        ), col.stage
        assert col.weighted_value == round(value * pct / 100)
        assert len(col.cards) == n and not col.has_more
    open_rows = [v for k, v in want.items() if k not in ("booked", "lost", "junk")]
    t = board.totals
    assert t.open_count == sum(r[0] for r in open_rows)
    assert t.open_value == sum(r[1] for r in open_rows)
    assert t.weighted_value == sum(round(r[1] * r[4] / 100) for r in open_rows)
    assert t.stale_count == sum(r[2] for r in open_rows)
    assert (t.booked_count, t.booked_value) == want.get("booked", (0, 0))[:2]
    if not mine:
        assert sum(c.count for c in board.stages) == 59  # 60 seeded, 1 deleted


async def test_dataset_is_not_vacuous(db, dataset):
    admin, _ = dataset
    t = (await build_board(db, admin, PipelineQuery(), now=NOW)).totals
    assert (
        t.open_count
        and t.open_value
        and t.weighted_value
        and t.stale_count
        and t.missing_value_count
    )
    assert t.booked_count and t.booked_value


async def test_cards_show_days_in_stage_and_stale_flag(db, dataset):
    admin, _ = dataset
    board = await build_board(db, admin, PipelineQuery(per_stage=200), now=NOW)
    for col in board.stages:
        assert [c.days_in_stage for c in col.cards] == sorted(
            (c.days_in_stage for c in col.cards), reverse=True
        )
        for c in col.cards:
            lead = await db.get(Lead, c.id)
            assert c.days_in_stage == (NOW - lead.status_changed_at).days
            assert c.stale == (
                lead.status.value in OPEN_SQL and lead.last_activity_at < NOW - timedelta(days=7)
            )
    lost_junk = {c.stage for c in board.stages} & {LeadStatus.lost, LeadStatus.junk}
    assert not lost_junk  # hidden unless include_closed


async def test_forecast_reconciles_with_database(db, dataset):
    admin, _ = dataset
    fc = await build_forecast(db, admin, PipelineQuery(), now=NOW)

    def q(group_col):
        return text(f"""
            SELECT {group_col}, count(*), COALESCE(sum(COALESCE({VALUE}, 0)), 0),
                   round(COALESCE(sum(COALESCE({VALUE}, 0) * ps.probability_pct), 0) / 100.0)
            FROM leads l JOIN pipeline_stages ps ON ps.stage = l.status
            WHERE l.deleted_at IS NULL AND l.status IN {OPEN_SQL}
            GROUP BY {group_col}""")

    by_proj = {r[0]: (r[1], int(r[2]), int(r[3])) for r in await db.execute(q("l.project_id"))}
    by_exec = {r[0]: (r[1], int(r[2]), int(r[3])) for r in await db.execute(q("l.assigned_to_id"))}
    assert {
        (f.project.id if f.project else None): (f.count, f.value, f.weighted_value)
        for f in fc.by_project
    } == by_proj
    assert {
        (f.user.id if f.user else None): (f.count, f.value, f.weighted_value)
        for f in fc.by_executive
    } == by_exec
    assert fc.total.count == sum(v[0] for v in by_proj.values())
    weights = [f.weighted_value for f in fc.by_project]
    assert weights == sorted(weights, reverse=True)


async def test_changing_a_probability_changes_the_weighted_value(login_as, db, dataset):
    c, _ = await login_as(Role.admin)
    before = (await c.get("/api/pipeline")).json()["stages"]
    nego = next(s for s in before if s["stage"] == "negotiation")
    assert nego["value"] > 0

    r = await c.patch(
        "/api/pipeline/stages", json={"stages": [{"stage": "negotiation", "probability_pct": 90}]}
    )

    assert r.status_code == 200
    after = next(
        s for s in (await c.get("/api/pipeline")).json()["stages"] if s["stage"] == "negotiation"
    )
    assert after["probability_pct"] == 90 and after["weighted_value"] == round(nego["value"] * 0.9)
    entry = await db.scalar(select(AuditLog).where(AuditLog.action == "pipeline.probabilities"))
    assert entry.details == {"negotiation": {"from": 70, "to": 90}}


@pytest.mark.parametrize(
    "stages",
    [
        [{"stage": "negotiation", "probability_pct": 101}],
        [{"stage": "booked", "probability_pct": 80}],
        [{"stage": "lost", "probability_pct": 5}],
        [
            {"stage": "qualified", "probability_pct": 20},
            {"stage": "qualified", "probability_pct": 30},
        ],
        [],
    ],
)
async def test_invalid_probabilities_rejected(login_as, stages):
    c, _ = await login_as(Role.admin)
    assert (await c.patch("/api/pipeline/stages", json={"stages": stages})).status_code == 422


@pytest.mark.parametrize("role", [Role.manager, Role.executive])
async def test_only_admin_edits_probabilities(login_as, role):
    c, _ = await login_as(role)
    assert (await c.get("/api/pipeline/stages")).status_code == 200
    assert (
        await c.patch(
            "/api/pipeline/stages", json={"stages": [{"stage": "new", "probability_pct": 9}]}
        )
    ).status_code == 403


async def test_docs_staff_have_no_pipeline(login_as):
    c, _ = await login_as(Role.docs)
    for path in ("/api/pipeline", "/api/pipeline/forecast", "/api/pipeline/aged"):
        assert (await c.get(path)).status_code == 403


async def test_executive_sees_only_own_leads_even_with_filters(login_as, make_user):
    ravi, ravi_user = await login_as(Role.executive)
    kiran, _ = await login_as(Role.executive)
    await ravi.post("/api/leads", json={"name": "A", "mobile": "9876543210", "source": "website"})
    await kiran.post("/api/leads", json={"name": "B", "mobile": "9123456780", "source": "website"})
    board = (await ravi.get("/api/pipeline")).json()
    assert board["totals"]["open_count"] == 1
    other = (await ravi.get("/api/pipeline", params={"assigned_to_id": 999})).json()
    assert other["totals"]["open_count"] == 1  # filter can't widen an executive's view


async def test_moving_a_card_stamps_days_in_stage_and_keeps_the_rules(login_as, db):
    c, _ = await login_as(Role.executive)
    lead = (
        await c.post("/api/leads", json={"name": "A", "mobile": "9876543210", "source": "website"})
    ).json()["lead"]
    await db.execute(
        update(Lead)
        .where(Lead.id == lead["id"])
        .values(status_changed_at=datetime.now(UTC) - timedelta(days=10))
    )
    await db.commit()
    card = (await c.get("/api/pipeline")).json()["stages"][0]["cards"][0]
    assert card["days_in_stage"] == 10

    moved = await c.patch(f"/api/leads/{lead['id']}/pipeline", json={"status": "qualified"})

    assert moved.status_code == 200 and moved.json()["status"] == "qualified"
    col = next(
        s for s in (await c.get("/api/pipeline")).json()["stages"] if s["stage"] == "qualified"
    )
    assert col["cards"][0]["days_in_stage"] == 0
    # Same rules as the status button
    assert (
        await c.patch(f"/api/leads/{lead['id']}/pipeline", json={"status": "lost"})
    ).status_code == 422
    booked = await c.patch(f"/api/leads/{lead['id']}/pipeline", json={"status": "booked"})
    assert booked.status_code == 422 and "manager" in booked.json()["detail"].lower()


async def test_automatic_status_change_from_a_visit_also_stamps(login_as, db):
    c, _ = await login_as(Role.executive)
    project = await new_project(db)
    lead = (
        await c.post("/api/leads", json={"name": "A", "mobile": "9876543210", "source": "website"})
    ).json()["lead"]
    await db.execute(
        update(Lead)
        .where(Lead.id == lead["id"])
        .values(status_changed_at=datetime.now(UTC) - timedelta(days=4))
    )
    await db.commit()
    when = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    await c.post(
        "/api/visits", json={"lead_id": lead["id"], "project_id": project.id, "scheduled_at": when}
    )
    db.expire_all()
    refreshed = await db.get(Lead, lead["id"])
    assert refreshed.status == LeadStatus.visit_scheduled
    assert datetime.now(UTC) - refreshed.status_changed_at < timedelta(minutes=1)


async def test_per_stage_limit_and_stale_filter(login_as, db):
    c, _ = await login_as(Role.manager)
    for i in range(4):
        await c.post(
            "/api/leads", json={"name": f"L{i}", "mobile": f"98765432{i}0", "source": "website"}
        )
    board = (await c.get("/api/pipeline", params={"per_stage": 2})).json()
    new_col = next(s for s in board["stages"] if s["stage"] == "new")
    assert new_col["count"] == 4 and len(new_col["cards"]) == 2 and new_col["has_more"] is True

    old = await db.scalar(select(Lead.id).order_by(Lead.id))
    await db.execute(
        update(Lead)
        .where(Lead.id == old)
        .values(last_activity_at=datetime.now(UTC) - timedelta(days=9))
    )
    await db.commit()
    aged = (await c.get("/api/pipeline/aged")).json()
    assert [a["id"] for a in aged] == [old] and aged[0]["stale"] is True
    stale_board = (await c.get("/api/pipeline", params={"stale_only": True})).json()
    assert stale_board["totals"]["open_count"] == 1


async def test_default_probabilities_present(db):
    rows = dict(
        (await db.execute(select(PipelineStage.stage, PipelineStage.probability_pct))).all()
    )
    assert len(rows) == 13 and rows[LeadStatus.booked] == 100 and rows[LeadStatus.negotiation] == 70


async def test_missing_stage_rows_fall_back_to_defaults(login_as, db):
    """If a stage has no saved row, its default is used (and saving creates the row)."""
    c, _ = await login_as(Role.admin)
    await db.execute(text("DELETE FROM pipeline_stages WHERE stage = 'qualified'"))
    await db.commit()
    stages = {
        s["stage"]: s["probability_pct"] for s in (await c.get("/api/pipeline/stages")).json()
    }
    assert stages["qualified"] == 20 and len(stages) == 13
    saved = await c.patch(
        "/api/pipeline/stages", json={"stages": [{"stage": "qualified", "probability_pct": 25}]}
    )
    assert {s["stage"]: s["probability_pct"] for s in saved.json()}["qualified"] == 25


async def test_closed_leads_are_never_stale(login_as, db):
    """A booked, lost or junk lead going quiet is expected, not a problem to flag."""
    mgr, _ = await login_as(Role.manager)
    long_ago = datetime.now(UTC) - timedelta(days=30)
    ids = {}
    for i, status in enumerate(["booked", "lost", "contacted"]):
        lead = (
            await mgr.post(
                "/api/leads", json={"name": status, "mobile": f"98765432{i}1", "source": "website"}
            )
        ).json()["lead"]
        ids[status] = lead["id"]
        await db.execute(
            update(Lead)
            .where(Lead.id == lead["id"])
            .values(
                status=status,
                last_activity_at=long_ago,
                lost_reason="x" if status == "lost" else None,
            )
        )
    await db.commit()

    board = (await mgr.get("/api/pipeline", params={"include_closed": True})).json()

    stale = {c["name"]: c["stale"] for s in board["stages"] for c in s["cards"]}
    assert stale == {"booked": False, "lost": False, "contacted": True}
    assert board["totals"]["stale_count"] == 1
