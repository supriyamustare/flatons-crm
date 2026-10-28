"""Dashboard insights: projects, lead status, first contact, schedule, 12-month trend, sources,
recent bookings. Definitions are on schemas.insights.Insights. Dates are India time."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import case, exists, func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking, BookingStatus
from app.models.call import CallLog
from app.models.inventory import Unit, UnitStatus
from app.models.lead import Lead, LeadStatus
from app.models.project import Project
from app.models.task import FollowUpTask, TaskStatus
from app.models.user import Role, User
from app.models.visit import SiteVisit, VisitStatus
from app.schemas.insights import (
    Insights,
    MonthPoint,
    OwnerCount,
    ProjectStock,
    RecentBooking,
    Scheduled,
    SourceRow,
    StatusSlice,
)
from app.schemas.user import UserBrief
from app.services.bookings import code as booking_code
from app.services.leads import IST

CLOSED = (LeadStatus.booked, LeadStatus.lost, LeadStatus.junk)


def _at(d: date) -> datetime:
    return datetime.combine(d, time.min, IST)


def _month_add(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


async def build_insights(
    db: AsyncSession, user: User, *, person_id: int | None, now: datetime | None = None
) -> Insights:
    now = now or datetime.now(UTC)
    today = now.astimezone(IST).date()
    month0 = today.replace(day=1)
    if user.role == Role.executive:
        person_id = user.id
    mine = person_id is not None
    live = Lead.deleted_at.is_(None)
    scope = [live] + ([Lead.assigned_to_id == person_id] if mine else [])

    # ---- projects (company-wide inventory)
    sold = func.count().filter(Unit.status.in_([UnitStatus.sold, UnitStatus.booked]))
    blocked = func.count().filter(Unit.status == UnitStatus.on_hold)
    avail = func.count().filter(Unit.status == UnitStatus.available)
    price = func.coalesce(Unit.current_asking_price, Unit.base_price)
    for_sale = Unit.status.in_([UnitStatus.available, UnitStatus.on_hold])
    stock = {
        r[0]: r[1:]
        for r in await db.execute(
            select(
                Unit.project_id,
                sold,
                blocked,
                avail,
                func.min(price).filter(for_sale),
                func.max(price).filter(for_sale),
                func.array_agg(func.distinct(Unit.unit_type)),
            )
            .where(Unit.status != UnitStatus.withdrawn)
            .group_by(Unit.project_id)
        )
    }
    month_bookings = {
        r[0]: (r[1], r[2])
        for r in await db.execute(
            select(
                Booking.project_id, func.count(), func.coalesce(func.sum(Booking.agreed_price), 0)
            )
            .where(Booking.status == BookingStatus.booked, Booking.booking_date >= month0)
            .group_by(Booking.project_id)
        )
    }
    projects = []
    for p in await db.scalars(
        select(Project).where(Project.is_active.is_(True)).order_by(Project.name)
    ):
        s, b, a, lo, hi, types = stock.get(p.id, (0, 0, 0, None, None, []))
        total = s + b + a
        nb, val = month_bookings.get(p.id, (0, 0))
        projects.append(
            ProjectStock(
                id=p.id,
                name=p.name,
                location=p.location,
                project_type=p.project_type.value,
                unit_types=sorted(t for t in (types or []) if t is not None),
                price_min=lo,
                price_max=hi,
                sold=s,
                blocked=b,
                available=a,
                total=total,
                sold_pct=round(s / total * 100, 1) if total else None,
                bookings_this_month=nb,
                booked_value_this_month=int(val),
            )
        )
    projects.sort(key=lambda x: (-(x.total > 0), -(x.sold_pct or 0), x.name))

    # ---- lead status split
    week_ago = now - timedelta(days=7)
    slice_case = case(
        (Lead.status == LeadStatus.booked, "booked"),
        (Lead.status.in_([LeadStatus.lost, LeadStatus.junk]), "dead"),
        (Lead.assigned_to_id.is_(None), "unassigned"),
        (Lead.last_activity_at >= week_ago, "working"),
        else_="quiet",
    )
    counts = dict(
        (
            await db.execute(select(slice_case, func.count()).where(*scope).group_by(slice_case))
        ).all()
    )
    order = ["working", "quiet", "unassigned", "booked", "dead"]
    lead_status = [StatusSlice(key=k, count=counts.get(k, 0)) for k in order]

    # ---- waiting for first contact, by owner
    no_call = ~exists().where(CallLog.lead_id == Lead.id)
    rows = (
        await db.execute(
            select(Lead.assigned_to_id, func.count())
            .where(*scope, Lead.status == LeadStatus.new, no_call)
            .group_by(Lead.assigned_to_id)
        )
    ).all()
    owners = {
        u.id: u
        for u in await db.scalars(select(User).where(User.id.in_([r[0] for r in rows if r[0]])))
    }
    waiting = sorted(
        (
            OwnerCount(user=UserBrief.model_validate(owners[r[0]]) if r[0] else None, count=r[1])
            for r in rows
        ),
        key=lambda x: -x.count,
    )

    # ---- scheduled, next 30 days
    end30 = now + timedelta(days=30)
    visits = (
        await db.scalar(
            select(func.count())
            .select_from(SiteVisit)
            .join(Lead, Lead.id == SiteVisit.lead_id)
            .where(
                live,
                SiteVisit.status == VisitStatus.scheduled,
                SiteVisit.scheduled_at >= now,
                SiteVisit.scheduled_at < end30,
                *([SiteVisit.host_id == person_id] if mine else []),
            )
        )
        or 0
    )
    tasks = (
        await db.execute(
            select(FollowUpTask.task_type, func.count())
            .join(Lead, Lead.id == FollowUpTask.lead_id)
            .where(
                live,
                FollowUpTask.status == TaskStatus.pending,
                FollowUpTask.due_at < end30,
                *([FollowUpTask.assigned_to_id == person_id] if mine else []),
            )
            .group_by(FollowUpTask.task_type)
        )
    ).all()
    scheduled = [Scheduled(key="site_visit", count=visits)] + sorted(
        (Scheduled(key=t.value, count=n) for t, n in tasks), key=lambda x: -x.count
    )

    # ---- 12 months of leads and deals
    first = _month_add(month0, -11)
    month_of = lambda col: func.date_trunc("month", func.timezone("Asia/Kolkata", col))  # noqa: E731
    leads_m = {
        r[0].date(): r[1]
        for r in await db.execute(
            select(month_of(Lead.created_at).label("m"), func.count())
            .where(*scope, Lead.created_at >= _at(first))
            .group_by("m")
        )
    }
    b_scope = [Booking.status == BookingStatus.booked] + (
        [Booking.sales_exec_id == person_id] if mine else []
    )
    deals_q = union_all(
        select(func.date_trunc("month", Booking.booking_date).label("m")).where(
            *b_scope, Booking.booking_date >= first
        ),
        select(month_of(Lead.status_changed_at).label("m")).where(
            *scope,
            Lead.status == LeadStatus.booked,
            Lead.status_changed_at >= _at(first),
            ~exists().where(Booking.lead_id == Lead.id, Booking.status == BookingStatus.booked),
        ),
    ).subquery()
    deals_m = {
        r[0].date(): r[1]
        for r in await db.execute(select(deals_q.c.m, func.count()).group_by(deals_q.c.m))
    }
    months = [
        MonthPoint(month=m, leads=leads_m.get(m, 0), deals=deals_m.get(m, 0))
        for m in (_month_add(first, i) for i in range(12))
    ]

    # ---- sources, last 12 months
    src = (
        await db.execute(
            select(Lead.source, func.count(), func.count().filter(Lead.status == LeadStatus.booked))
            .where(*scope, Lead.created_at >= _at(first))
            .group_by(Lead.source)
        )
    ).all()
    sources = sorted(
        (
            SourceRow(source=s, leads=n, sales=k, conversion=round(k / n * 100, 1) if n else None)
            for s, n, k in src
        ),
        key=lambda x: (-x.leads, x.source.value),
    )

    # ---- first response this month (median minutes to first call)
    first_call = (
        select(CallLog.lead_id, func.min(CallLog.called_at).label("fc"))
        .group_by(CallLog.lead_id)
        .subquery()
    )
    gap = func.extract("epoch", first_call.c.fc - Lead.created_at) / 60
    resp = (
        await db.execute(
            select(
                func.percentile_cont(0.5).within_group(gap),
                func.count(),
                func.count().filter(gap <= 24 * 60),
            )
            .join(first_call, first_call.c.lead_id == Lead.id)
            .where(*scope, Lead.created_at >= _at(month0), first_call.c.fc >= Lead.created_at)
        )
    ).one()
    median, called, within_day = resp
    first_response = round(float(median)) if median is not None else None

    # ---- recent bookings
    recent = [
        RecentBooking(
            id=b.id,
            booking_code=booking_code(b),
            customer=b.lead.name,
            project=b.project.name,
            unit_no=b.unit.unit_no,
            agreed_price=b.agreed_price,
            booking_date=b.booking_date,
            sales_exec=UserBrief.model_validate(b.sales_exec) if b.sales_exec else None,
        )
        for b in await db.scalars(
            select(Booking)
            .where(*b_scope)
            .order_by(Booking.booking_date.desc(), Booking.id.desc())
            .limit(6)
        )
    ]
    return Insights(
        projects=projects,
        lead_status=lead_status,
        total_leads=sum(s.count for s in lead_status),
        waiting_by_owner=waiting,
        scheduled_30d=scheduled,
        months=months,
        sources=sources,
        first_response_min=first_response,
        contacted_within_day_pct=round(within_day / called * 100, 1) if called else None,
        recent_bookings=recent,
    )
