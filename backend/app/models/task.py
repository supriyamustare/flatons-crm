import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.lead import Lead
from app.models.user import User


class TaskType(enum.StrEnum):
    call = "call"
    whatsapp = "whatsapp"
    meeting = "meeting"
    site_visit = "site_visit"
    email = "email"
    other = "other"


class TaskStatus(enum.StrEnum):
    pending = "pending"
    completed = "completed"
    # Replaced by a new task with a later due time; the new task points back here.
    rescheduled = "rescheduled"
    cancelled = "cancelled"


class FollowUpTask(TimestampMixin, Base):
    """A follow-up on a lead. "Overdue" is not stored: it's pending with due_at in the past."""

    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        Index("ix_follow_up_tasks_assignee_status_due", "assigned_to_id", "status", "due_at"),
        Index("ix_follow_up_tasks_lead_id", "lead_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    assigned_to_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="task_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TaskStatus.pending,
    )
    notes: Mapped[str | None] = mapped_column(Text)
    completion_note: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    rescheduled_from_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("follow_up_tasks.id", ondelete="SET NULL"), index=True
    )
    reschedule_reason: Mapped[str | None] = mapped_column(String(255))

    lead: Mapped[Lead] = relationship(lazy="selectin")
    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id], lazy="selectin")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy="selectin")
