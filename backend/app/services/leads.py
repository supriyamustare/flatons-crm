"""Lead business rules: who can see/edit what, status rules, IDs, duplicates, search."""

import re
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lead import (
    MANAGER_ONLY,
    REASON_REQUIRED,
    Lead,
    LeadActivity,
    LeadCodeCounter,
    LeadStatus,
)
from app.models.user import Role, User
from app.schemas.lead import DuplicateOut, LeadSearch

IST = ZoneInfo("Asia/Kolkata")
MANAGERS = {Role.admin, Role.manager}


class LeadRuleError(ValueError):
    """A business rule was broken; the message is shown to the user."""


# ---- Visibility & permissions --------------------------------------------


def visible_leads(user: User) -> Select[tuple[Lead]]:
    """Leads this user may see: executives see their own; everyone else sees all."""
    stmt = select(Lead).where(Lead.deleted_at.is_(None))
    if user.role == Role.executive:
        stmt = stmt.where(Lead.assigned_to_id == user.id)
    return stmt


def can_view(user: User, lead: Lead) -> bool:
    if lead.deleted_at is not None:
        return False
    return user.role != Role.executive or lead.assigned_to_id == user.id


def can_edit(user: User, lead: Lead) -> bool:
    if user.role in MANAGERS:
        return True
    return user.role == Role.executive and lead.assigned_to_id == user.id


async def get_visible_lead(db: AsyncSession, user: User, lead_id: int) -> Lead | None:
    return await db.scalar(visible_leads(user).where(Lead.id == lead_id))


# ---- Lead code -----------------------------------------------------------


async def next_lead_code(db: AsyncSession, now: datetime | None = None) -> str:
    """LEAD-YYYYMMDD-NNNN, numbered per day in IST. Safe under concurrent inserts."""
    today = (now or datetime.now(UTC)).astimezone(IST).date()
    stmt = (
        insert(LeadCodeCounter)
        .values(day=today, last_value=1)
        .on_conflict_do_update(
            index_elements=[LeadCodeCounter.day],
            set_={"last_value": LeadCodeCounter.last_value + 1},
        )
        .returning(LeadCodeCounter.last_value)
    )
    n = (await db.execute(stmt)).scalar_one()
    return f"LEAD-{today:%Y%m%d}-{n:04d}"


# ---- Activities ----------------------------------------------------------


def add_activity(
    db: AsyncSession,
    lead: Lead,
    *,
    actor: User | None,
    type: str,
    note: str | None = None,
    details: dict[str, Any] | None = None,
) -> LeadActivity:
    activity = LeadActivity(
        lead_id=lead.id,
        actor_id=actor.id if actor else None,
        type=type,
        note=note,
        details=details,
    )
    db.add(activity)
    lead.last_activity_at = datetime.now(UTC)
    return activity


async def list_activities(db: AsyncSession, lead_id: int) -> list[LeadActivity]:
    result = await db.scalars(
        select(LeadActivity)
        .where(LeadActivity.lead_id == lead_id)
        .order_by(LeadActivity.created_at.desc(), LeadActivity.id.desc())
    )
    return list(result)


# ---- Status rules --------------------------------------------------------


def check_status_change(user: User, lead: Lead, new: LeadStatus, reason: str | None) -> None:
    """Raise LeadRuleError if this status change isn't allowed."""
    old = lead.status
    if new == old:
        raise LeadRuleError("The lead already has this status")
    if (new in MANAGER_ONLY or old in MANAGER_ONLY) and user.role not in MANAGERS:
        raise LeadRuleError(
            "Only a manager or admin can mark a lead as Booked or change it from Booked"
        )
    if new in REASON_REQUIRED and not (reason and reason.strip()):
        label = "lost" if new == LeadStatus.lost else "junk"
        raise LeadRuleError(f"Give a reason when marking a lead as {label}")


# ---- Assignment ----------------------------------------------------------


async def get_assignable_user(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise LeadRuleError("That user doesn't exist or is deactivated")
    if user.role not in {Role.executive, Role.manager}:
        raise LeadRuleError("Leads can only be assigned to executives or managers")
    return user


async def list_assignable_users(db: AsyncSession) -> list[User]:
    result = await db.scalars(
        select(User)
        .where(User.is_active.is_(True), User.role.in_([Role.executive, Role.manager]))
        .order_by(User.full_name)
    )
    return list(result)


# ---- Duplicates ----------------------------------------------------------


async def find_duplicates(
    db: AsyncSession,
    viewer: User,
    *,
    mobiles: list[str],
    email: str | None,
    exclude_id: int | None = None,
) -> list[DuplicateOut]:
    """Existing leads sharing a phone number (either field) or email. Warns, never blocks."""
    mobiles = [m for m in mobiles if m]
    conditions = []
    if mobiles:
        conditions += [Lead.mobile.in_(mobiles), Lead.alt_mobile.in_(mobiles)]
    if email:
        conditions.append(func.lower(Lead.email) == email.lower())
    if not conditions:
        return []

    stmt = select(Lead).where(Lead.deleted_at.is_(None), or_(*conditions))
    if exclude_id is not None:
        stmt = stmt.where(Lead.id != exclude_id)
    leads = await db.scalars(stmt.order_by(Lead.created_at.desc()).limit(5))

    out = []
    for lead in leads:
        matched: list = []
        if mobiles and (lead.mobile in mobiles or lead.alt_mobile in mobiles):
            matched.append("mobile")
        if email and lead.email and lead.email.lower() == email.lower():
            matched.append("email")
        out.append(
            DuplicateOut(
                id=lead.id,
                lead_code=lead.lead_code,
                name=lead.name,
                status=lead.status,
                assigned_to_name=lead.assigned_to.full_name if lead.assigned_to else None,
                matched_on=matched,
                can_view=can_view(viewer, lead),
            )
        )
    return out


# ---- Search --------------------------------------------------------------


def _like(term: str) -> str:
    return "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


SORT_COLUMNS = {
    "created_at": Lead.created_at,
    "updated_at": Lead.updated_at,
    "last_activity_at": Lead.last_activity_at,
    "name": func.lower(Lead.name),
}


async def search_leads(db: AsyncSession, user: User, f: LeadSearch) -> tuple[list[Lead], int]:
    stmt = visible_leads(user)

    if f.q:
        text_match = or_(
            Lead.name.ilike(_like(f.q)),
            Lead.lead_code.ilike(_like(f.q)),
            Lead.email.ilike(_like(f.q)),
        )
        digits = re.sub(r"\D", "", f.q)
        if len(digits) >= 3:
            text_match = or_(
                text_match,
                Lead.mobile.like(_like(digits)),
                Lead.alt_mobile.like(_like(digits)),
            )
        stmt = stmt.where(text_match)
    if f.statuses:
        stmt = stmt.where(Lead.status.in_(f.statuses))
    if f.sources:
        stmt = stmt.where(Lead.source.in_(f.sources))
    if f.project_id is not None:
        stmt = stmt.where(Lead.project_id == f.project_id)
    if f.unassigned:
        stmt = stmt.where(Lead.assigned_to_id.is_(None))
    elif f.assigned_to_id is not None:
        stmt = stmt.where(Lead.assigned_to_id == f.assigned_to_id)
    if f.created_from:
        stmt = stmt.where(Lead.created_at >= datetime.combine(f.created_from, time.min, IST))
    if f.created_to:
        end = datetime.combine(f.created_to + timedelta(days=1), time.min, IST)
        stmt = stmt.where(Lead.created_at < end)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    column = SORT_COLUMNS[f.sort]
    ordering = column.asc() if f.order == "asc" else column.desc()
    stmt = (
        stmt.order_by(ordering, Lead.id.desc())
        .offset((f.page - 1) * f.page_size)
        .limit(f.page_size)
    )
    return list(await db.scalars(stmt)), total
