"""Pipeline board and forecast.

Deal value = estimated value, else the top of the budget, else the bottom; leads with none of
these count as "missing value". Weighted value = deal value x the stage's probability.
Open = every stage except Booked, Lost and Junk.
"""

from datetime import UTC, datetime, time, timedelta

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.lead import Lead, LeadStatus
from app.models.pipeline import DEFAULT_PROBABILITIES, PipelineStage
from app.models.project import Project
from app.models.user import User
from app.schemas.pipeline import (
    ExecutiveForecast,
    Forecast,
    ForecastRow,
    PipelineBoard,
    PipelineCard,
    PipelineQuery,
    PipelineTotals,
    ProjectForecast,
    StageColumn,
)
from app.schemas.project import ProjectBrief
from app.schemas.user import UserBrief
from app.services.leads import IST, MANAGERS, visible_leads

STALE_AFTER = timedelta(days=7)
CLOSED = (LeadStatus.booked, LeadStatus.lost, LeadStatus.junk)
OPEN = tuple(s for s in LeadStatus if s not in CLOSED)


def _value(cols):
    return func.coalesce(cols.estimated_value, cols.budget_max, cols.budget_min)


def is_stale(status: LeadStatus, last_activity_at: datetime, now: datetime) -> bool:
    return status in OPEN and last_activity_at < now - STALE_AFTER


def _scoped(user: User, q: PipelineQuery, now: datetime) -> Select:
    stmt = visible_leads(user)
    if q.mine:
        stmt = stmt.where(Lead.assigned_to_id == user.id)
    elif q.assigned_to_id is not None and user.role in MANAGERS:
        stmt = stmt.where(Lead.assigned_to_id == q.assigned_to_id)
    if q.project_id is not None:
        stmt = stmt.where(Lead.project_id == q.project_id)
    if q.created_from:
        stmt = stmt.where(Lead.created_at >= datetime.combine(q.created_from, time.min, IST))
    if q.created_to:
        end = datetime.combine(q.created_to + timedelta(days=1), time.min, IST)
        stmt = stmt.where(Lead.created_at < end)
    if q.stale_only:
        stmt = stmt.where(Lead.status.in_(OPEN), Lead.last_activity_at < now - STALE_AFTER)
    return stmt


async def probabilities(db: AsyncSession) -> dict[LeadStatus, int]:
    """Saved probabilities, falling back to the defaults for any stage without a saved row."""
    rows = await db.execute(select(PipelineStage.stage, PipelineStage.probability_pct))
    return {**DEFAULT_PROBABILITIES, **dict(rows.all())}


def _card(lead: Lead, now: datetime) -> PipelineCard:
    value = next(
        (v for v in (lead.estimated_value, lead.budget_max, lead.budget_min) if v is not None), None
    )
    return PipelineCard(
        id=lead.id,
        lead_code=lead.lead_code,
        name=lead.name,
        status=lead.status,
        project=ProjectBrief.model_validate(lead.project) if lead.project else None,
        budget_min=lead.budget_min,
        budget_max=lead.budget_max,
        deal_value=value,
        assigned_to=UserBrief.model_validate(lead.assigned_to) if lead.assigned_to else None,
        days_in_stage=max(0, (now - lead.status_changed_at).days),
        stale=is_stale(lead.status, lead.last_activity_at, now),
        last_activity_at=lead.last_activity_at,
    )


async def build_board(
    db: AsyncSession, user: User, q: PipelineQuery, now: datetime | None = None
) -> PipelineBoard:
    now = now or datetime.now(UTC)
    probs = await probabilities(db)
    base = _scoped(user, q, now).subquery()
    c = base.c
    agg = await db.execute(
        select(
            c.status,
            func.count(),
            func.coalesce(func.sum(_value(c)), 0),
            func.count().filter(and_(c.status.in_(OPEN), c.last_activity_at < now - STALE_AFTER)),
            func.count().filter(_value(c).is_(None)),
        ).group_by(c.status)
    )
    stats = {LeadStatus(s): (n, int(v), stale, missing) for s, n, v, stale, missing in agg}
    empty = (0, 0, 0, 0)

    hidden = () if q.include_closed else (LeadStatus.lost, LeadStatus.junk)
    shown = [s for s in LeadStatus if s not in hidden]
    # Top N cards per stage, longest in the stage first (those are the ones getting stuck)
    ranked = (
        _scoped(user, q, now)
        .where(Lead.status.in_(shown))
        .add_columns(
            func.row_number()
            .over(partition_by=Lead.status, order_by=(Lead.status_changed_at.asc(), Lead.id.asc()))
            .label("rn")
        )
        .subquery()
    )
    lead_row = aliased(Lead, ranked)
    rows = await db.execute(
        select(lead_row).where(ranked.c.rn <= q.per_stage).order_by(ranked.c.status, ranked.c.rn)
    )
    cards: dict[LeadStatus, list[PipelineCard]] = {s: [] for s in shown}
    for (lead,) in rows:
        cards[lead.status].append(_card(lead, now))

    columns = []
    for s in shown:
        n, value, stale, missing = stats.get(s, empty)
        columns.append(
            StageColumn(
                stage=s,
                probability_pct=probs[s],
                count=n,
                value=value,
                weighted_value=round(value * probs[s] / 100),
                stale_count=stale,
                missing_value_count=missing,
                cards=cards[s],
                has_more=n > len(cards[s]),
            )
        )

    def total(statuses, idx: int) -> int:
        return sum(stats.get(s, empty)[idx] for s in statuses)

    totals = PipelineTotals(
        open_count=total(OPEN, 0),
        open_value=total(OPEN, 1),
        weighted_value=sum(round(stats.get(s, empty)[1] * probs[s] / 100) for s in OPEN),
        booked_count=total([LeadStatus.booked], 0),
        booked_value=total([LeadStatus.booked], 1),
        stale_count=total(OPEN, 2),
        missing_value_count=total(OPEN, 3),
    )
    return PipelineBoard(stale_after_days=STALE_AFTER.days, stages=columns, totals=totals)


async def build_forecast(
    db: AsyncSession, user: User, q: PipelineQuery, now: datetime | None = None
) -> Forecast:
    """Weighted value of open deals, by project and by executive."""
    now = now or datetime.now(UTC)
    probs = await probabilities(db)
    open_leads = _scoped(user, q, now).where(Lead.status.in_(OPEN)).subquery()
    c = open_leads.c
    value = func.coalesce(_value(c), 0)

    async def rows_by(col) -> list[tuple]:
        """[(group key, count, value, weighted value)], each stage weighted by its probability."""
        raw = await db.execute(
            select(col, c.status, func.count(), func.coalesce(func.sum(value), 0)).group_by(
                col, c.status
            )
        )
        acc: dict = {}
        for key, status, n, v in raw:
            cnt, tv, tw = acc.get(key, (0, 0, 0.0))
            acc[key] = (cnt + n, tv + int(v), tw + int(v) * probs[LeadStatus(status)] / 100)
        return [(k, cnt, tv, round(tw)) for k, (cnt, tv, tw) in acc.items()]

    by_proj = await rows_by(c.project_id)
    by_exec = await rows_by(c.assigned_to_id)
    project_ids = [r[0] for r in by_proj if r[0]]
    user_ids = [r[0] for r in by_exec if r[0]]
    projects = {
        p.id: p for p in await db.scalars(select(Project).where(Project.id.in_(project_ids)))
    }
    users = {u.id: u for u in await db.scalars(select(User).where(User.id.in_(user_ids)))}

    by_project = sorted(
        (
            ProjectForecast(
                project=ProjectBrief.model_validate(projects[k]) if k else None,
                count=n,
                value=v,
                weighted_value=w,
            )
            for k, n, v, w in by_proj
        ),
        key=lambda f: -f.weighted_value,
    )
    by_executive = sorted(
        (
            ExecutiveForecast(
                user=UserBrief.model_validate(users[k]) if k else None,
                count=n,
                value=v,
                weighted_value=w,
            )
            for k, n, v, w in by_exec
        ),
        key=lambda f: -f.weighted_value,
    )
    total = ForecastRow(
        count=sum(f.count for f in by_project),
        value=sum(f.value for f in by_project),
        weighted_value=sum(f.weighted_value for f in by_project),
    )
    return Forecast(by_project=by_project, by_executive=by_executive, total=total)
