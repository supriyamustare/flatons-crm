"""Follow-up task rules: who sees which tasks, the four views, and status changes."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import FollowUpTask, TaskStatus
from app.models.user import User
from app.schemas.task import TaskCounts, TaskOut, TaskQuery, TaskView
from app.services.leads import MANAGERS
from app.services.notifications import ist_day_bounds

# A follow-up can't be set in the past; a few minutes' grace covers slow typing and clocks.
PAST_GRACE = timedelta(minutes=5)


class TaskRuleError(ValueError):
    """A business rule was broken; the message is shown to the user."""


def visible_tasks(user: User) -> Select[tuple[FollowUpTask]]:
    """Executives see tasks assigned to them; managers and admins see all."""
    stmt = select(FollowUpTask)
    if user.role not in MANAGERS:
        stmt = stmt.where(FollowUpTask.assigned_to_id == user.id)
    return stmt


def can_act_on(user: User, task: FollowUpTask) -> bool:
    return user.role in MANAGERS or task.assigned_to_id == user.id


def check_due_at(due_at: datetime, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if due_at < now - PAST_GRACE:
        raise TaskRuleError("Choose a time in the future")


def _view_filter(view: TaskView, now: datetime):
    _, day_end = ist_day_bounds(now)
    pending = FollowUpTask.status == TaskStatus.pending
    if view == "overdue":
        return and_(pending, FollowUpTask.due_at < now)
    if view == "today":
        # Everything still open that's due before midnight, including today's overdue ones.
        day_start, _ = ist_day_bounds(now)
        return and_(pending, FollowUpTask.due_at >= day_start, FollowUpTask.due_at < day_end)
    if view == "upcoming":
        return and_(pending, FollowUpTask.due_at >= day_end)
    return FollowUpTask.status == TaskStatus.completed


def _scoped(user: User, q: TaskQuery) -> Select[tuple[FollowUpTask]]:
    stmt = visible_tasks(user)
    if q.mine:
        stmt = stmt.where(FollowUpTask.assigned_to_id == user.id)
    elif q.assigned_to_id is not None and user.role in MANAGERS:
        stmt = stmt.where(FollowUpTask.assigned_to_id == q.assigned_to_id)
    if q.task_type is not None:
        stmt = stmt.where(FollowUpTask.task_type == q.task_type)
    return stmt


async def search_tasks(
    db: AsyncSession, user: User, q: TaskQuery, now: datetime | None = None
) -> tuple[list[FollowUpTask], int, TaskCounts]:
    now = now or datetime.now(UTC)
    base = _scoped(user, q)

    stmt = base.where(_view_filter(q.view, now))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if q.view == "completed":
        stmt = stmt.order_by(FollowUpTask.completed_at.desc(), FollowUpTask.id.desc())
    else:
        stmt = stmt.order_by(FollowUpTask.due_at.asc(), FollowUpTask.id.asc())
    items = list(await db.scalars(stmt.offset((q.page - 1) * q.page_size).limit(q.page_size)))

    counts = TaskCounts(
        today=await _count(db, base, "today", now),
        overdue=await _count(db, base, "overdue", now),
        upcoming=await _count(db, base, "upcoming", now),
    )
    return items, total, counts


async def _count(db: AsyncSession, base: Select, view: TaskView, now: datetime) -> int:
    stmt = base.where(_view_filter(view, now))
    return await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


def to_out(task: FollowUpTask, now: datetime | None = None) -> TaskOut:
    now = now or datetime.now(UTC)
    out = TaskOut.model_validate(task)
    out.is_overdue = task.status == TaskStatus.pending and task.due_at < now
    return out


async def tasks_for_lead(db: AsyncSession, lead_id: int) -> list[FollowUpTask]:
    """Open tasks first (soonest due), then the rest (most recent first)."""
    result = await db.scalars(
        select(FollowUpTask)
        .where(FollowUpTask.lead_id == lead_id)
        .order_by(
            (FollowUpTask.status != TaskStatus.pending).asc(),
            FollowUpTask.due_at.asc(),
            FollowUpTask.id.desc(),
        )
    )
    return list(result)


def require_pending(task: FollowUpTask) -> None:
    if task.status != TaskStatus.pending:
        raise TaskRuleError(f"This follow-up is already {task.status.value}")


def assignee_label(user: User | None) -> str:
    return user.full_name if user else "nobody"
