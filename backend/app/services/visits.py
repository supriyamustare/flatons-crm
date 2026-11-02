"""Site visit rules: visibility, the list views, and automatic lead status changes."""

from datetime import UTC, datetime, time, timedelta

from fastapi import Request
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import Lead, LeadStatus
from app.models.user import User
from app.models.visit import SiteVisit, VisitStatus
from app.schemas.visit import VisitOut, VisitQuery, VisitView
from app.services.audit import log_audit
from app.services.leads import IST, MANAGERS, add_activity
from app.services.notifications import ist_day_bounds

# A scheduled visit whose time passed this long ago without an outcome is flagged.
NEEDS_UPDATE_AFTER = timedelta(hours=3)

# Statuses a visit may move a lead forward from. Later stages (negotiation, on hold,
# booked, lost, junk) are never changed automatically.
EARLY_STAGES = {
    LeadStatus.new,
    LeadStatus.not_reachable,
    LeadStatus.contacted,
    LeadStatus.qualified,
    LeadStatus.follow_up,
}


class VisitRuleError(ValueError):
    """A business rule was broken; the message is shown to the user."""


def visible_visits(user: User) -> Select[tuple[SiteVisit]]:
    """Executives see visits they host or on leads assigned to them."""
    stmt = (
        select(SiteVisit).join(Lead, Lead.id == SiteVisit.lead_id).where(Lead.deleted_at.is_(None))
    )
    if user.role not in MANAGERS:
        stmt = stmt.where(or_(SiteVisit.host_id == user.id, Lead.assigned_to_id == user.id))
    return stmt


def can_act_on(user: User, visit: SiteVisit) -> bool:
    return user.role in MANAGERS or visit.host_id == user.id or visit.lead.assigned_to_id == user.id


def require_scheduled(visit: SiteVisit) -> None:
    if visit.status != VisitStatus.scheduled:
        raise VisitRuleError(f"This visit is already {visit.status.value.replace('_', ' ')}")


def require_visit_day_reached(visit: SiteVisit, now: datetime | None = None) -> None:
    """Outcomes (completed, no-show) can be recorded from the day of the visit onwards."""
    now = now or datetime.now(UTC)
    _, day_end = ist_day_bounds(now)
    if visit.scheduled_at >= day_end:
        raise VisitRuleError("You can record how the visit went on or after the visit day")


def to_out(visit: SiteVisit, now: datetime | None = None) -> VisitOut:
    now = now or datetime.now(UTC)
    out = VisitOut.model_validate(visit)
    out.needs_update = (
        visit.status == VisitStatus.scheduled and visit.scheduled_at < now - NEEDS_UPDATE_AFTER
    )
    return out


def _view_filter(view: VisitView):
    if view == "upcoming":
        return SiteVisit.status == VisitStatus.scheduled
    if view == "completed":
        return SiteVisit.status == VisitStatus.completed
    if view == "missed":
        return SiteVisit.status.in_([VisitStatus.no_show, VisitStatus.cancelled])
    return True


def _scoped(user: User, q: VisitQuery) -> Select[tuple[SiteVisit]]:
    stmt = visible_visits(user)
    if q.mine:
        stmt = stmt.where(SiteVisit.host_id == user.id)
    elif q.host_id is not None and user.role in MANAGERS:
        stmt = stmt.where(SiteVisit.host_id == q.host_id)
    if q.project_id is not None:
        stmt = stmt.where(SiteVisit.project_id == q.project_id)
    if q.date_from:
        stmt = stmt.where(SiteVisit.scheduled_at >= datetime.combine(q.date_from, time.min, IST))
    if q.date_to:
        end = datetime.combine(q.date_to + timedelta(days=1), time.min, IST)
        stmt = stmt.where(SiteVisit.scheduled_at < end)
    return stmt


async def _count(db: AsyncSession, stmt: Select) -> int:
    return await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


async def search_visits(
    db: AsyncSession, user: User, q: VisitQuery, now: datetime | None = None
) -> tuple[list[SiteVisit], int, int, int]:
    """Returns (items, total, upcoming_count, needs_update_count)."""
    now = now or datetime.now(UTC)
    base = _scoped(user, q)
    stmt = base.where(_view_filter(q.view))
    total = await _count(db, stmt)
    if q.view == "upcoming":
        stmt = stmt.order_by(SiteVisit.scheduled_at.asc(), SiteVisit.id.asc())
    else:
        stmt = stmt.order_by(SiteVisit.scheduled_at.desc(), SiteVisit.id.desc())
    items = list(await db.scalars(stmt.offset((q.page - 1) * q.page_size).limit(q.page_size)))

    upcoming = await _count(db, base.where(SiteVisit.status == VisitStatus.scheduled))
    needs_update = await _count(
        db,
        base.where(
            SiteVisit.status == VisitStatus.scheduled,
            SiteVisit.scheduled_at < now - NEEDS_UPDATE_AFTER,
        ),
    )
    return items, total, upcoming, needs_update


async def visits_for_lead(db: AsyncSession, lead_id: int) -> list[SiteVisit]:
    result = await db.scalars(
        select(SiteVisit)
        .where(SiteVisit.lead_id == lead_id)
        .order_by((SiteVisit.status != VisitStatus.scheduled).asc(), SiteVisit.scheduled_at.desc())
    )
    return list(result)


async def advance_lead_status(
    db: AsyncSession,
    lead: Lead,
    *,
    event: str,
    actor: User,
    request: Request | None = None,
) -> LeadStatus | None:
    """Move the lead forward after a visit is scheduled or completed. Returns the new status,
    or None if nothing changed. Recorded in the timeline and audit log as automatic."""
    old = lead.status
    new: LeadStatus | None = None
    if event == "scheduled" and old in EARLY_STAGES:
        new = LeadStatus.visit_scheduled
    elif event == "completed":
        earlier_visits = await db.scalar(
            select(func.count())
            .select_from(SiteVisit)
            .where(SiteVisit.lead_id == lead.id, SiteVisit.status == VisitStatus.completed)
        )
        # The visit being completed is already flushed as completed, so >1 means a revisit.
        if old in EARLY_STAGES | {LeadStatus.visit_scheduled}:
            new = LeadStatus.revisit if (earlier_visits or 0) > 1 else LeadStatus.visit_done
        elif old in {LeadStatus.visit_done, LeadStatus.revisit}:
            new = LeadStatus.revisit
    if new is None or new == old:
        return None

    lead.status = new
    lead.lost_reason = None
    reason = "Site visit scheduled" if event == "scheduled" else "Site visit completed"
    details = {"from": old.value, "to": new.value, "automatic": True, "reason": reason}
    add_activity(db, lead, actor=actor, type="status_change", details=details)
    log_audit(
        db,
        action="lead.status_change",
        entity_type="lead",
        entity_id=lead.id,
        actor=actor,
        details=details,
        request=request,
    )
    return new
