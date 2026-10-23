from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification
from app.models.task import FollowUpTask, TaskStatus
from app.models.user import User
from app.services.leads import IST


def notify(
    db: AsyncSession,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
) -> Notification:
    """Queue an in-app notification (saved with the caller's commit)."""
    n = Notification(user_id=user_id, type=type, title=title, body=body, link=link)
    db.add(n)
    return n


async def list_for_user(
    db: AsyncSession, user: User, limit: int = 20
) -> tuple[list[Notification], int]:
    items = await db.scalars(
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    unread = await db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
    )
    return list(items), unread or 0


async def mark_all_read(db: AsyncSession, user: User) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )


def ist_day_bounds(now: datetime) -> tuple[datetime, datetime]:
    """Start of today and start of tomorrow in India time, as aware datetimes."""
    today = now.astimezone(IST).date()
    start = datetime.combine(today, time.min, IST)
    return start, start + timedelta(days=1)


async def create_daily_digests(db: AsyncSession, now: datetime | None = None) -> int:
    """One "your follow-ups today" notification per person who has any due today or overdue.
    Skips people with nothing due, and never sends twice on the same day. Returns how many."""
    now = now or datetime.now(UTC)
    day_start, day_end = ist_day_bounds(now)

    pending = (
        select(FollowUpTask.assigned_to_id.label("user_id"), FollowUpTask.due_at)
        .join(User, User.id == FollowUpTask.assigned_to_id)
        .where(FollowUpTask.status == TaskStatus.pending, User.is_active.is_(True))
        .subquery()
    )
    rows = await db.execute(
        select(
            pending.c.user_id,
            func.count().filter(pending.c.due_at < now).label("overdue"),
            func.count().filter(pending.c.due_at >= now, pending.c.due_at < day_end).label("today"),
        ).group_by(pending.c.user_id)
    )

    already = set(
        await db.scalars(
            select(Notification.user_id).where(
                Notification.type == "daily_digest", Notification.created_at >= day_start
            )
        )
    )

    created = 0
    for user_id, overdue, today in rows:
        if (overdue == 0 and today == 0) or user_id in already:
            continue
        parts = []
        if today:
            parts.append(f"{today} due later today")
        if overdue:
            parts.append(f"{overdue} overdue")
        notify(
            db,
            user_id=user_id,
            type="daily_digest",
            title="Your follow-ups for today",
            body=", ".join(parts).capitalize(),
            link="/follow-ups",
        )
        created += 1
    return created
