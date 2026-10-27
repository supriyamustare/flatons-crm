"""The dashboard overview (summary, tiles, week/month strip, performance, leads tabs, this month).
Definitions are on schemas.overview.Overview. Dates are India time; weeks start on Monday."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingStatus
from app.models.call import CallLog
from app.models.lead import Lead, LeadStatus
from app.models.marketing import Expense
from app.models.task import FollowUpTask, TaskStatus
from app.models.user import Role, User
from app.models.visit import SiteVisit, VisitStatus
from app.schemas.overview import (
    LeadTab,
    Overview,
    OverviewLead,
    Performance,
    ThisMonth,
    Trend,
    WeekMonth,
)
from app.schemas.user import UserBrief
from app.services.leads import IST

CLOSED = (LeadStatus.booked, LeadStatus.lost, LeadStatus.junk)
QUALIFIED_OR_LATER = (
    LeadStatus.qualified,
    LeadStatus.follow_up,
    LeadStatus.visit_scheduled,
    LeadStatus.visit_done,
    LeadStatus.revisit,
    LeadStatus.negotiation,
    LeadStatus.on_hold,
    LeadStatus.booked,
)
STALE = timedelta(days=7)


def _at(d: date) -> datetime:
    return datetime.combine(d, time.min, IST)


def _pct(now_v: int, before: int) -> float | None:
    return round((now_v - before) / before * 100, 1) if before else None


async def build_overview(
    db: AsyncSession,
    user: User,
    *,
    person_id: int | None,
    tab: LeadTab,
    now: datetime | None = None,
) -> Overview:
    now = now or datetime.now(UTC)
    today = now.astimezone(IST).date()
    week0, month0 = today - timedelta(days=today.weekday()), today.replace(day=1)
    tomorrow = today + timedelta(days=1)
    last_month0 = (month0 - timedelta(days=1)).replace(day=1)
    # Same number of days into last month, so the comparison is fair mid-month
    last_month_end = min(last_month0 + timedelta(days=today.day), month0)

    if user.role == Role.executive:
        person_id = user.id
    person = await db.get(User, person_id) if person_id else None
    if person_id and person is None:
        person_id = None
    mine = person_id is not None

    live = Lead.deleted_at.is_(None)
    lead_scope = [live] + ([Lead.assigned_to_id == person_id] if mine else [])

    async def count(stmt) -> int:
        return int(await db.scalar(stmt) or 0)

    def leads_where(*cond) -> Select:
        return select(func.count()).select_from(Lead).where(*lead_scope, *cond)

    # ---- summary and tiles
    no_call = ~exists().where(CallLog.lead_id == Lead.id)
    in_closing = await count(leads_where(Lead.status == LeadStatus.negotiation))
    fresh = await count(leads_where(Lead.status == LeadStatus.new, no_call))
    task_scope = [FollowUpTask.status == TaskStatus.pending] + (
        [FollowUpTask.assigned_to_id == person_id] if mine else []
    )
    task_base = (
        select(func.count())
        .select_from(FollowUpTask)
        .join(Lead, Lead.id == FollowUpTask.lead_id)
        .where(live, *task_scope)
    )
    due = await count(task_base.where(FollowUpTask.due_at < _at(tomorrow)))
    overdue = await count(task_base.where(FollowUpTask.due_at < now))
    visit_scope = [live] + ([SiteVisit.host_id == person_id] if mine else [])
    visit_base = (
        select(func.count())
        .select_from(SiteVisit)
        .join(Lead, Lead.id == SiteVisit.lead_id)
        .where(*visit_scope)
    )
    visits_today = await count(
        visit_base.where(
            SiteVisit.status == VisitStatus.scheduled,
            SiteVisit.scheduled_at >= _at(today),
            SiteVisit.scheduled_at < _at(tomorrow),
        )
    )

    # ---- week / month strip
    async def visits_done(start: date) -> int:
        return await count(
            visit_base.where(
                SiteVisit.status == VisitStatus.completed,
                SiteVisit.scheduled_at >= _at(start),
                SiteVisit.scheduled_at < _at(tomorrow),
            )
        )

    booking_scope = [Booking.status == BookingStatus.booked] + (
        [Booking.sales_exec_id == person_id] if mine else []
    )

    async def bookings(start: date, end: date = tomorrow) -> tuple[int, int]:
        n, value = (
            await db.execute(
                select(func.count(), func.coalesce(func.sum(Booking.agreed_price), 0)).where(
                    *booking_scope, Booking.booking_date >= start, Booking.booking_date < end
                )
            )
        ).one()
        return int(n), int(value)

    wk, mo = await bookings(week0), await bookings(month0)

    # ---- performance trends (month to date vs same days last month, and 30 daily points)
    start30 = today - timedelta(days=29)

    async def trend(col, stmt: Select, is_date: bool = False) -> Trend:
        """Counts per day from the start of last month (or 30 days ago, if earlier) to today."""
        lo = min(start30, last_month0)
        sub = stmt.where(
            col >= (lo if is_date else _at(lo)), col < (tomorrow if is_date else _at(tomorrow))
        ).subquery()
        dcol = sub.c[col.key]
        day = dcol if is_date else func.date(func.timezone("Asia/Kolkata", dcol))
        rows = dict((await db.execute(select(day, func.count()).group_by(day))).all())
        month_v = sum(v for d, v in rows.items() if d >= month0)
        last_v = sum(v for d, v in rows.items() if last_month0 <= d < last_month_end)
        return Trend(
            month=month_v,
            last_month=last_v,
            change_pct=_pct(month_v, last_v),
            daily=[rows.get(start30 + timedelta(days=i), 0) for i in range(30)],
        )

    enq = await trend(Lead.created_at, select(Lead.created_at).where(*lead_scope))
    sv = await trend(
        SiteVisit.scheduled_at,
        select(SiteVisit.scheduled_at)
        .join(Lead, Lead.id == SiteVisit.lead_id)
        .where(*visit_scope, SiteVisit.status == VisitStatus.completed),
    )
    sales = await trend(
        Booking.booking_date, select(Booking.booking_date).where(*booking_scope), is_date=True
    )
    calls = await trend(
        CallLog.called_at,
        select(CallLog.called_at)
        .join(Lead, Lead.id == CallLog.lead_id)
        .where(live, *([CallLog.user_id == person_id] if mine else [])),
    )
    spend = cps = None
    if not mine:
        spend_rows = dict(
            (
                await db.execute(
                    select(Expense.spent_on, func.sum(Expense.amount))
                    .where(
                        Expense.spent_on >= min(start30, last_month0), Expense.spent_on < tomorrow
                    )
                    .group_by(Expense.spent_on)
                )
            ).all()
        )
        sm = int(sum(v for d, v in spend_rows.items() if d >= month0))
        sl = int(sum(v for d, v in spend_rows.items() if last_month0 <= d < last_month_end))
        spend = Trend(
            month=sm,
            last_month=sl,
            change_pct=_pct(sm, sl),
            daily=[int(spend_rows.get(start30 + timedelta(days=i), 0)) for i in range(30)],
        )
        cps = round(sm / sales.month) if sales.month else None

    # ---- leads overview tabs
    next_task = (
        select(func.min(FollowUpTask.due_at))
        .where(FollowUpTask.lead_id == Lead.id, FollowUpTask.status == TaskStatus.pending)
        .scalar_subquery()
    )
    next_visit = (
        select(func.min(SiteVisit.scheduled_at))
        .where(
            SiteVisit.lead_id == Lead.id,
            SiteVisit.status == VisitStatus.scheduled,
            SiteVisit.scheduled_at >= now,
        )
        .scalar_subquery()
    )
    task_today = exists().where(
        FollowUpTask.lead_id == Lead.id,
        FollowUpTask.status == TaskStatus.pending,
        FollowUpTask.due_at < _at(tomorrow),
    )
    visit_ahead = exists().where(
        SiteVisit.lead_id == Lead.id,
        SiteVisit.status == VisitStatus.scheduled,
        SiteVisit.scheduled_at >= now,
    )
    tabs: dict[LeadTab, tuple] = {
        "fresh": ((Lead.status == LeadStatus.new, no_call), Lead.created_at.desc()),
        "today": ((task_today,), next_task.asc()),
        "visit": ((visit_ahead,), next_visit.asc()),
        "closing": ((Lead.status == LeadStatus.negotiation,), Lead.last_activity_at.asc()),
        "reengage": (
            (Lead.status.notin_(CLOSED), Lead.last_activity_at < now - STALE),
            Lead.last_activity_at.asc(),
        ),
    }
    tab_counts = {k: await count(leads_where(*cond)) for k, (cond, _) in tabs.items()}
    cond, order = tabs[tab]
    rows = await db.execute(
        select(Lead, next_task, next_visit)
        .where(*lead_scope, *cond)
        .order_by(order, Lead.id)
        .limit(10)
    )
    leads = []
    for lead, t_at, v_at in rows:
        # Each tab shows the time that matters for it; elsewhere, whichever comes first
        if tab == "visit":
            nxt = v_at
        elif tab == "today":
            nxt = t_at
        else:
            nxt = min([x for x in (t_at, v_at) if x], default=None)
        leads.append(
            OverviewLead(
                id=lead.id,
                lead_code=lead.lead_code,
                name=lead.name,
                mobile=lead.mobile,
                source=lead.source,
                status=lead.status,
                city=lead.city,
                next_at=nxt,
                next_action=None if nxt is None else ("Site visit" if nxt == v_at else "Follow-up"),
                owner=UserBrief.model_validate(lead.assigned_to) if lead.assigned_to else None,
            )
        )

    # ---- this month
    m_start = _at(month0)
    new_leads = await count(leads_where(Lead.created_at >= m_start))
    open_leads = await count(leads_where(Lead.status.notin_(CLOSED)))
    active = await count(leads_where(Lead.status.notin_(CLOSED), Lead.last_activity_at >= m_start))
    qualified = await count(
        leads_where(Lead.created_at >= m_start, Lead.status.in_(QUALIFIED_OR_LATER))
    )
    unassigned = await count(
        select(func.count())
        .select_from(Lead)
        .where(live, Lead.assigned_to_id.is_(None), Lead.status.notin_(CLOSED))
    )
    won = await count(
        leads_where(Lead.status == LeadStatus.booked, Lead.status_changed_at >= m_start)
    )
    lost = await count(
        leads_where(
            Lead.status.in_([LeadStatus.lost, LeadStatus.junk]), Lead.status_changed_at >= m_start
        )
    )

    people = (
        []
        if user.role == Role.executive
        else [
            UserBrief.model_validate(u)
            for u in await db.scalars(
                select(User)
                .where(
                    User.is_active.is_(True),
                    User.role.in_([Role.admin, Role.manager, Role.executive]),
                )
                .order_by(User.role != Role.executive, User.full_name)
            )
        ]
    )
    return Overview(
        scope="person" if mine else "team",
        person=UserBrief.model_validate(person) if mine else None,
        today=today,
        in_closing=in_closing,
        fresh_waiting=fresh,
        followups_due=due,
        followups_overdue=overdue,
        visits_today=visits_today,
        visits_completed=WeekMonth(week=await visits_done(week0), month=await visits_done(month0)),
        sales_closed=WeekMonth(week=wk[0], month=mo[0]),
        sales_revenue=WeekMonth(week=wk[1], month=mo[1]),
        performance=Performance(
            enquiries=enq, site_visits=sv, sales=sales, calls=calls, spend=spend, cost_per_sale=cps
        ),
        tab_counts=tab_counts,
        tab=tab,
        leads=leads,
        this_month=ThisMonth(
            new_leads=new_leads,
            active=active,
            qualified=qualified,
            unassigned=unassigned,
            active_rate=round(active / open_leads, 4) if open_leads else None,
            win_rate=round(won / (won + lost), 4) if won + lost else None,
        ),
        people=people,
    )
