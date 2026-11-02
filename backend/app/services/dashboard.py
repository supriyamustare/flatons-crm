"""Dashboard figures. Definitions are documented on schemas.dashboard.Kpis."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import CONNECTED_OUTCOMES, CallLog
from app.models.lead import Lead, LeadActivity, LeadStatus
from app.models.marketing import Expense
from app.models.project import Project
from app.models.task import FollowUpTask, TaskStatus
from app.models.user import User
from app.models.visit import SiteVisit, VisitStatus
from app.schemas.dashboard import ActivityFeedItem, Business, Dashboard, DashboardQuery, Kpis
from app.schemas.user import UserBrief
from app.services import tasks as task_svc
from app.services import visits as visit_svc
from app.services.leads import IST
from app.services.notifications import ist_day_bounds


def resolve_range(q: DashboardQuery, now: datetime) -> tuple[date, date]:
    today = now.astimezone(IST).date()
    if q.range == "today":
        return today, today
    if q.range == "7d":
        return today - timedelta(days=6), today
    if q.range == "30d":
        return today - timedelta(days=29), today
    assert q.date_from and q.date_to
    return q.date_from, q.date_to


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min, IST),
        datetime.combine(end + timedelta(days=1), time.min, IST),
    )


async def _count(db: AsyncSession, stmt: Select) -> int:
    return await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


async def build_dashboard(
    db: AsyncSession, user: User, q: DashboardQuery, *, mine: bool, now: datetime | None = None
) -> Dashboard:
    now = now or datetime.now(UTC)
    start, end = resolve_range(q, now)
    p_start, p_end = _bounds(start, end)
    day_start, day_end = ist_day_bounds(now)

    # --- scopes (same rules as the list pages, so numbers match what people can open) ---
    leads = select(Lead).where(Lead.deleted_at.is_(None))
    tasks = (
        select(FollowUpTask)
        .join(Lead, Lead.id == FollowUpTask.lead_id)
        .where(Lead.deleted_at.is_(None), FollowUpTask.status == TaskStatus.pending)
    )
    calls = select(CallLog).join(Lead, Lead.id == CallLog.lead_id).where(Lead.deleted_at.is_(None))
    visits = visit_svc.visible_visits(user)
    activities = (
        select(LeadActivity, Lead)
        .join(Lead, Lead.id == LeadActivity.lead_id)
        .where(Lead.deleted_at.is_(None))
    )
    if mine:
        leads = leads.where(Lead.assigned_to_id == user.id)
        tasks = tasks.where(FollowUpTask.assigned_to_id == user.id)
        calls = calls.where(CallLog.user_id == user.id)
        visits = visits.where(or_(SiteVisit.host_id == user.id, Lead.assigned_to_id == user.id))
        activities = activities.where(Lead.assigned_to_id == user.id)

    calls_in_period = calls.where(CallLog.called_at >= p_start, CallLog.called_at < p_end)
    visits_in_period = visits.where(
        SiteVisit.scheduled_at >= p_start, SiteVisit.scheduled_at < p_end
    )
    n_calls = await _count(db, calls_in_period)
    n_connected = await _count(
        db, calls_in_period.where(CallLog.outcome.in_(list(CONNECTED_OUTCOMES)))
    )

    kpis = Kpis(
        total_leads=await _count(db, leads),
        new_leads=await _count(
            db, leads.where(Lead.created_at >= p_start, Lead.created_at < p_end)
        ),
        follow_ups_today=await _count(
            db, tasks.where(FollowUpTask.due_at >= day_start, FollowUpTask.due_at < day_end)
        ),
        overdue_follow_ups=await _count(db, tasks.where(FollowUpTask.due_at < now)),
        visits_scheduled=await _count(
            db, visits_in_period.where(SiteVisit.status != VisitStatus.cancelled)
        ),
        visits_completed=await _count(
            db, visits_in_period.where(SiteVisit.status == VisitStatus.completed)
        ),
        calls=n_calls,
        calls_connected=n_connected,
        connection_rate=round(n_connected / n_calls, 4) if n_calls else None,
    )

    by_status_sub = leads.subquery()
    rows = await db.execute(
        select(by_status_sub.c.status, func.count()).group_by(by_status_sub.c.status)
    )
    leads_by_status = {s: 0 for s in LeadStatus}
    for status_value, n in rows:
        leads_by_status[LeadStatus(status_value)] = n

    overdue = list(
        await db.scalars(
            tasks.where(FollowUpTask.due_at < now).order_by(FollowUpTask.due_at.asc()).limit(5)
        )
    )
    stale_visits = list(
        await db.scalars(
            visits.where(
                SiteVisit.status == VisitStatus.scheduled,
                SiteVisit.scheduled_at < now - visit_svc.NEEDS_UPDATE_AFTER,
            )
            .order_by(SiteVisit.scheduled_at.asc())
            .limit(5)
        )
    )
    feed_rows = (
        await db.execute(
            activities.order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc()).limit(15)
        )
    ).all()
    feed = [
        ActivityFeedItem(
            id=a.id,
            type=a.type,
            note=a.note,
            details=a.details,
            actor=UserBrief.model_validate(a.actor) if a.actor else None,
            lead_id=lead.id,
            lead_name=lead.name,
            lead_code=lead.lead_code,
            created_at=a.created_at,
        )
        for a, lead in feed_rows
    ]

    return Dashboard(
        scope="mine" if mine else "team",
        date_from=start,
        date_to=end,
        kpis=kpis,
        leads_by_status=leads_by_status,
        overdue=[task_svc.to_out(t, now) for t in overdue],
        visits_needing_update=[visit_svc.to_out(v, now) for v in stale_visits],
        activity=feed,
        business=None if mine else await _business(db, start, end, p_start, p_end),
    )


async def _business(
    db: AsyncSession, start: date, end: date, p_start: datetime, p_end: datetime
) -> Business:
    """Company figures for the Team view. Definitions are on schemas.dashboard.Business."""
    live = Lead.deleted_at.is_(None)
    generated = (
        await db.scalar(
            select(func.count())
            .select_from(Lead)
            .where(live, Lead.created_at >= p_start, Lead.created_at < p_end)
        )
        or 0
    )
    deal_value = func.coalesce(Lead.estimated_value, Lead.budget_max, Lead.budget_min)
    # Revenue is computed in whole rupees per lead, then summed (no fractional paise)
    commission = func.round(deal_value * Project.commission_pct / 100)
    booked = (
        select(Lead.id, commission.label("commission"))
        .outerjoin(Project, Project.id == Lead.project_id)
        .where(
            live,
            Lead.status == LeadStatus.booked,
            Lead.status_changed_at >= p_start,
            Lead.status_changed_at < p_end,
        )
        .subquery()
    )
    n_booked, revenue, unvalued = (
        await db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(booked.c.commission), 0),
                func.count().filter(booked.c.commission.is_(None)),
            )
        )
    ).one()
    expense = (
        await db.scalar(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.spent_on >= start, Expense.spent_on <= end
            )
        )
        or 0
    )
    revenue = int(revenue)
    return Business(
        leads_generated=generated,
        leads_booked=n_booked,
        booking_rate=round(n_booked / generated, 4) if generated else None,
        revenue=revenue,
        expense=int(expense),
        profit=revenue - int(expense),
        unvalued_bookings=unvalued,
    )
