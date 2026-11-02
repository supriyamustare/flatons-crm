"""Reports. Every rate is None ("N/A") when its denominator is zero, never 0%.
Periods are whole days in India time. Deleted leads, and their calls and visits, never count."""

from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import CONNECTED_OUTCOMES, CallLog
from app.models.lead import Lead, LeadStatus
from app.models.marketing import Campaign, Expense
from app.models.project import Project
from app.models.user import Role, User
from app.models.visit import SiteVisit, VisitSource, VisitStatus
from app.schemas.project import ProjectBrief
from app.schemas.report import (
    CallDay,
    CallRow,
    CallsReport,
    CampaignRow,
    CampaignsReport,
    ConversionReport,
    Funnel,
    FunnelByPerson,
    FunnelByProject,
    ReportQuery,
    StaffReport,
    StaffRow,
    VisitByPerson,
    VisitByProject,
    VisitBySource,
    VisitCounts,
    VisitsReport,
)
from app.schemas.user import UserBrief
from app.services.leads import IST, MANAGERS


def rate(n: int, d: int) -> float | None:
    return round(n / d, 4) if d else None


def per(amount: int, d: int) -> int | None:
    return round(amount / d) if d else None


def resolve(q: ReportQuery, now: datetime | None = None) -> tuple[date, date]:
    today = (now or datetime.now(UTC)).astimezone(IST).date()
    return {
        "today": (today, today),
        "7d": (today - timedelta(days=6), today),
        "30d": (today - timedelta(days=29), today),
    }.get(q.range) or (q.date_from, q.date_to)


def bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return datetime.combine(start, time.min, IST), datetime.combine(
        end + timedelta(days=1), time.min, IST
    )


def person_filter(user: User, q: ReportQuery) -> tuple[int | None, str]:
    """Executives always see only themselves; managers/admins may pick a person."""
    if user.role not in MANAGERS:
        return user.id, "mine"
    return (q.user_id, "person") if q.user_id else (None, "team")


async def _users(db: AsyncSession, ids) -> dict[int, User]:
    ids = [i for i in ids if i]
    return {u.id: u for u in await db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


async def _projects(db: AsyncSession, ids) -> dict[int, Project]:
    ids = [i for i in ids if i]
    return (
        {p.id: p for p in await db.scalars(select(Project).where(Project.id.in_(ids)))}
        if ids
        else {}
    )


def _brief(u: User | None) -> UserBrief | None:
    return UserBrief.model_validate(u) if u else None


LIVE_LEAD = Lead.deleted_at.is_(None)


# ------------------------------------------------------------------ calls
CALL_DEFS = {
    "Calls": "Calls logged in the period (incoming and outgoing).",
    "Connected": "Calls where the customer answered: Interested, Call back later or Not interested.",
    "Connection rate": "Connected ÷ calls. N/A when there were no calls.",
    "Talk time": "Total recorded duration of connected calls, in minutes.",
}


async def calls_report(
    db: AsyncSession, user: User, q: ReportQuery, now: datetime | None = None
) -> CallsReport:
    start, end = resolve(q, now)
    ps, pe = bounds(start, end)
    who, scope = person_filter(user, q)
    base = (
        select(CallLog)
        .join(Lead, Lead.id == CallLog.lead_id)
        .where(LIVE_LEAD, CallLog.called_at >= ps, CallLog.called_at < pe)
    )
    if who:
        base = base.where(CallLog.user_id == who)
    if q.project_id:
        base = base.where(Lead.project_id == q.project_id)
    c = base.subquery()
    conn = c.c.outcome.in_([o.value for o in CONNECTED_OUTCOMES])
    rows = (
        await db.execute(
            select(
                c.c.user_id,
                func.count(),
                func.count().filter(conn),
                func.coalesce(func.sum(c.c.duration_sec).filter(conn), 0),
            ).group_by(c.c.user_id)
        )
    ).all()
    users = await _users(db, [r[0] for r in rows])
    out = sorted(
        (
            CallRow(
                user=_brief(users.get(uid)),
                calls=n,
                connected=k,
                connection_rate=rate(k, n),
                talk_minutes=round(sec / 60),
            )
            for uid, n, k, sec in rows
        ),
        key=lambda r: -r.calls,
    )
    n, k = sum(r.calls for r in out), sum(r.connected for r in out)
    totals = CallRow(
        user=None,
        calls=n,
        connected=k,
        connection_rate=rate(k, n),
        talk_minutes=sum(r.talk_minutes for r in out),
    )
    day = func.date(func.timezone("Asia/Kolkata", c.c.called_at))
    per_day = {
        d: (n, k)
        for d, n, k in await db.execute(
            select(day, func.count(), func.count().filter(conn)).group_by(day)
        )
    }
    by_day = [
        CallDay(
            day=start + timedelta(days=i),
            calls=per_day.get(start + timedelta(days=i), (0, 0))[0],
            connected=per_day.get(start + timedelta(days=i), (0, 0))[1],
        )
        for i in range((end - start).days + 1)
    ]
    return CallsReport(
        date_from=start,
        date_to=end,
        scope=scope,
        definitions=CALL_DEFS,
        rows=out,
        totals=totals,
        by_day=by_day,
    )


# ------------------------------------------------------------------ visits
VISIT_DEFS = {
    "Visits": "Site visits dated in the period, whatever happened to them.",
    "Completed / No-show / Cancelled": "Recorded outcome of those visits.",
    "Awaiting outcome": "Still scheduled: in the future, or nobody has recorded what happened.",
    "Completion rate": "Completed ÷ (completed + no-show): of visits that were due and resolved, how many happened. N/A when there were none.",
}


def _visit_counts(total: int, done: int, no_show: int, cancelled: int, scheduled: int) -> dict:
    return {
        "visits": total,
        "completed": done,
        "no_show": no_show,
        "cancelled": cancelled,
        "scheduled": scheduled,
        "completion_rate": rate(done, done + no_show),
    }


async def visits_report(
    db: AsyncSession, user: User, q: ReportQuery, now: datetime | None = None
) -> VisitsReport:
    start, end = resolve(q, now)
    ps, pe = bounds(start, end)
    who, scope = person_filter(user, q)
    base = (
        select(SiteVisit)
        .join(Lead, Lead.id == SiteVisit.lead_id)
        .where(LIVE_LEAD, SiteVisit.scheduled_at >= ps, SiteVisit.scheduled_at < pe)
    )
    if who:
        base = base.where(SiteVisit.host_id == who)
    if q.project_id:
        base = base.where(SiteVisit.project_id == q.project_id)
    v = base.subquery()
    st = v.c.status

    def counts(col):
        return select(
            col,
            func.count(),
            func.count().filter(st == VisitStatus.completed.value),
            func.count().filter(st == VisitStatus.no_show.value),
            func.count().filter(st == VisitStatus.cancelled.value),
            func.count().filter(st == VisitStatus.scheduled.value),
        ).group_by(col)

    by_proj = (await db.execute(counts(v.c.project_id))).all()
    by_src = (await db.execute(counts(v.c.visit_source))).all()
    by_host = (await db.execute(counts(v.c.host_id))).all()
    projects = await _projects(db, [r[0] for r in by_proj])
    users = await _users(db, [r[0] for r in by_host])
    t = [sum(r[i] for r in by_proj) for i in range(1, 6)]
    return VisitsReport(
        date_from=start,
        date_to=end,
        scope=scope,
        definitions=VISIT_DEFS,
        by_project=sorted(
            (
                VisitByProject(
                    project=ProjectBrief.model_validate(projects[r[0]]), **_visit_counts(*r[1:])
                )
                for r in by_proj
            ),
            key=lambda x: -x.visits,
        ),
        by_source=sorted(
            (VisitBySource(source=VisitSource(r[0]), **_visit_counts(*r[1:])) for r in by_src),
            key=lambda x: -x.visits,
        ),
        by_person=sorted(
            (VisitByPerson(user=_brief(users.get(r[0])), **_visit_counts(*r[1:])) for r in by_host),
            key=lambda x: -x.visits,
        ),
        totals=VisitCounts(**_visit_counts(*t)),
    )


# ------------------------------------------------------------------ conversion
CONVERSION_DEFS = {
    "Leads": "Leads created in the period (the group followed through the funnel).",
    "Visited": "Of those, leads with at least one completed site visit (at any time).",
    "Booked": "Of those, leads now in Booked status. (Sprint 11's bookings module will make this the booking record.)",
    "Visit rate": "Visited ÷ leads.",
    "Visit to booking": "Leads both visited and booked ÷ visited.",
    "Conversion rate": "Booked ÷ leads. Every rate is N/A when its denominator is zero.",
}


def _cohort(user: User, q: ReportQuery, ps: datetime, pe: datetime) -> Select:
    who, _ = person_filter(user, q)
    stmt = select(
        Lead.id, Lead.assigned_to_id, Lead.project_id, Lead.campaign_id, Lead.status
    ).where(LIVE_LEAD, Lead.created_at >= ps, Lead.created_at < pe)
    if who:
        stmt = stmt.where(Lead.assigned_to_id == who)
    if q.project_id:
        stmt = stmt.where(Lead.project_id == q.project_id)
    return stmt


def _visited_flag(lead_id_col):
    return exists().where(
        SiteVisit.lead_id == lead_id_col, SiteVisit.status == VisitStatus.completed
    )


def _funnel(leads: int, visited: int, booked: int, both: int) -> dict:
    return {
        "leads": leads,
        "visited": visited,
        "booked": booked,
        "booked_after_visit": both,
        "visit_rate": rate(visited, leads),
        "visit_to_booking_rate": rate(both, visited),
        "conversion_rate": rate(booked, leads),
    }


async def conversion_report(
    db: AsyncSession, user: User, q: ReportQuery, now: datetime | None = None
) -> ConversionReport:
    start, end = resolve(q, now)
    ps, pe = bounds(start, end)
    _, scope = person_filter(user, q)
    cohort = _cohort(user, q, ps, pe).subquery()
    visited = _visited_flag(cohort.c.id)
    booked = cohort.c.status == LeadStatus.booked.value

    def grouped(col):
        return select(
            col,
            func.count(),
            func.count().filter(visited),
            func.count().filter(booked),
            func.count().filter(and_(visited, booked)),
        ).group_by(col)

    by_user = (await db.execute(grouped(cohort.c.assigned_to_id))).all()
    by_proj = (await db.execute(grouped(cohort.c.project_id))).all()
    users = await _users(db, [r[0] for r in by_user])
    projects = await _projects(db, [r[0] for r in by_proj])
    t = [sum(r[i] for r in by_user) for i in range(1, 5)]
    return ConversionReport(
        date_from=start,
        date_to=end,
        scope=scope,
        definitions=CONVERSION_DEFS,
        totals=Funnel(**_funnel(*t)),
        by_person=sorted(
            (FunnelByPerson(user=_brief(users.get(r[0])), **_funnel(*r[1:])) for r in by_user),
            key=lambda x: -x.leads,
        ),
        by_project=sorted(
            (
                FunnelByProject(
                    project=ProjectBrief.model_validate(projects[r[0]]) if r[0] else None,
                    **_funnel(*r[1:]),
                )
                for r in by_proj
            ),
            key=lambda x: -x.leads,
        ),
    )


# ------------------------------------------------------------------ campaigns
CAMPAIGN_DEFS = {
    "Spend": "Expenses dated in the period.",
    "Leads": "Leads created in the period that are attributed to the campaign.",
    "Visited / Booked": "Of those leads, how many had a completed site visit / are now booked.",
    "Cost per lead": "Spend ÷ leads attributed to this campaign (not all leads). N/A when no leads.",
    "Cost per visit / booking": "Spend ÷ visited / booked leads. N/A when zero.",
}


def _campaign_row(cid, name, channel, spend, leads, visited, booked) -> CampaignRow:
    return CampaignRow(
        campaign_id=cid,
        name=name,
        channel=channel,
        spend=spend,
        leads=leads,
        visited=visited,
        booked=booked,
        cost_per_lead=per(spend, leads),
        cost_per_visit=per(spend, visited),
        cost_per_booking=per(spend, booked),
    )


async def campaigns_report(
    db: AsyncSession, user: User, q: ReportQuery, now: datetime | None = None
) -> CampaignsReport:
    start, end = resolve(q, now)
    ps, pe = bounds(start, end)
    camp_filter = [Campaign.project_id == q.project_id] if q.project_id else []
    spend = dict(
        (
            await db.execute(
                select(Expense.campaign_id, func.sum(Expense.amount))
                .join(Campaign)
                .where(Expense.spent_on >= start, Expense.spent_on <= end, *camp_filter)
                .group_by(Expense.campaign_id)
            )
        ).all()
    )
    cohort = _cohort(
        user, q.model_copy(update={"user_id": None, "project_id": None}), ps, pe
    ).subquery()
    visited = _visited_flag(cohort.c.id)
    booked = cohort.c.status == LeadStatus.booked.value
    lead_rows = {
        r[0]: r[1:]
        for r in await db.execute(
            select(
                cohort.c.campaign_id,
                func.count(),
                func.count().filter(visited),
                func.count().filter(booked),
            ).group_by(cohort.c.campaign_id)
        )
    }
    unattributed = lead_rows.pop(None, (0, 0, 0))[0]
    ids = set(spend) | set(lead_rows)
    campaigns = (
        {
            c.id: c
            for c in await db.scalars(select(Campaign).where(Campaign.id.in_(ids), *camp_filter))
        }
        if ids
        else {}
    )
    rows = sorted(
        (
            _campaign_row(
                c.id, c.name, c.channel, int(spend.get(c.id, 0)), *lead_rows.get(c.id, (0, 0, 0))
            )
            for c in campaigns.values()
        ),
        key=lambda r: (-r.spend, -r.leads),
    )
    totals = _campaign_row(
        None,
        "All campaigns",
        None,
        sum(r.spend for r in rows),
        sum(r.leads for r in rows),
        sum(r.visited for r in rows),
        sum(r.booked for r in rows),
    )
    return CampaignsReport(
        date_from=start,
        date_to=end,
        scope="team",
        definitions=CAMPAIGN_DEFS,
        rows=rows,
        totals=totals,
        unattributed_leads=unattributed,
    )


# ------------------------------------------------------------------ staff
STAFF_DEFS = {
    "Leads": "Leads assigned to the person and created in the period.",
    "Calls / Connected": "Calls the person logged in the period / of those, answered.",
    "Visits completed": "Completed site visits the person hosted, dated in the period.",
    "Bookings": "Leads assigned to the person that moved to Booked during the period.",
    "Lead to booking": "Bookings ÷ leads. A rough rate: bookings may come from leads created earlier. N/A when no leads.",
}


async def staff_report(
    db: AsyncSession, user: User, q: ReportQuery, now: datetime | None = None
) -> StaffReport:
    start, end = resolve(q, now)
    ps, pe = bounds(start, end)
    who, scope = person_filter(user, q)
    proj = [Lead.project_id == q.project_id] if q.project_id else []
    people_q = select(User).where(
        User.is_active.is_(True), User.role.in_([Role.admin, Role.manager, Role.executive])
    )
    if who:
        people_q = select(User).where(User.id == who)
    people = list(await db.scalars(people_q.order_by(User.full_name)))
    ids = [p.id for p in people]

    async def by_user(stmt) -> dict:
        return {r[0]: r[1:] for r in await db.execute(stmt)}

    leads = await by_user(
        select(Lead.assigned_to_id, func.count())
        .where(
            LIVE_LEAD,
            Lead.created_at >= ps,
            Lead.created_at < pe,
            Lead.assigned_to_id.in_(ids),
            *proj,
        )
        .group_by(Lead.assigned_to_id)
    )
    conn = CallLog.outcome.in_(list(CONNECTED_OUTCOMES))
    calls = await by_user(
        select(CallLog.user_id, func.count(), func.count().filter(conn))
        .join(Lead, Lead.id == CallLog.lead_id)
        .where(
            LIVE_LEAD,
            CallLog.called_at >= ps,
            CallLog.called_at < pe,
            CallLog.user_id.in_(ids),
            *proj,
        )
        .group_by(CallLog.user_id)
    )
    visits = await by_user(
        select(SiteVisit.host_id, func.count())
        .join(Lead, Lead.id == SiteVisit.lead_id)
        .where(
            LIVE_LEAD,
            SiteVisit.status == VisitStatus.completed,
            SiteVisit.scheduled_at >= ps,
            SiteVisit.scheduled_at < pe,
            SiteVisit.host_id.in_(ids),
            *([SiteVisit.project_id == q.project_id] if q.project_id else []),
        )
        .group_by(SiteVisit.host_id)
    )
    bookings = await by_user(
        select(Lead.assigned_to_id, func.count())
        .where(
            LIVE_LEAD,
            Lead.status == LeadStatus.booked,
            Lead.status_changed_at >= ps,
            Lead.status_changed_at < pe,
            Lead.assigned_to_id.in_(ids),
            *proj,
        )
        .group_by(Lead.assigned_to_id)
    )

    rows = []
    for p in people:
        n_leads = leads.get(p.id, (0,))[0]
        n_calls, n_conn = calls.get(p.id, (0, 0))
        n_book = bookings.get(p.id, (0,))[0]
        row = StaffRow(
            user=_brief(p),
            leads=n_leads,
            calls=n_calls,
            connected=n_conn,
            connection_rate=rate(n_conn, n_calls),
            visits_completed=visits.get(p.id, (0,))[0],
            bookings=n_book,
            lead_to_booking_rate=rate(n_book, n_leads),
        )
        # Leave out people with nothing at all, unless it's a single person's report
        if (
            who
            or any((row.leads, row.calls, row.visits_completed, row.bookings))
            or p.role == Role.executive
        ):
            rows.append(row)
    rows.sort(key=lambda r: (-r.bookings, -r.leads, r.user.full_name))
    tl, tc, tk, tb = (
        sum(getattr(r, f) for r in rows) for f in ("leads", "calls", "connected", "bookings")
    )
    totals = StaffRow(
        user=UserBrief(id=0, full_name="Everyone", role=Role.executive),
        leads=tl,
        calls=tc,
        connected=tk,
        connection_rate=rate(tk, tc),
        visits_completed=sum(r.visits_completed for r in rows),
        bookings=tb,
        lead_to_booking_rate=rate(tb, tl),
    )
    return StaffReport(
        date_from=start, date_to=end, scope=scope, definitions=STAFF_DEFS, rows=rows, totals=totals
    )
