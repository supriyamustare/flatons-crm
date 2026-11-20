"""Customer-facing project updates: written, approved by someone else, published, and kept (corrections logged)."""

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class UpdateStatus(enum.StrEnum):
    draft = "draft"  # being written, or returned for changes
    pending_approval = "pending_approval"
    published = "published"  # visible to customers (portal); never deleted


class ProjectUpdate(TimestampMixin, Base):
    __tablename__ = "project_updates"
    __table_args__ = (
        CheckConstraint(
            "(status = 'published') = (published_at IS NOT NULL)", name="published_has_date"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    milestone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("project_milestones.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[UpdateStatus] = mapped_column(
        Enum(UpdateStatus, name="update_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=UpdateStatus.pending_approval,
    )
    author_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    returned_reason: Mapped[str | None] = mapped_column(String(500))
    published_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    photos: Mapped[list["ProjectUpdatePhoto"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ProjectUpdatePhoto.id"
    )
    corrections: Mapped[list["ProjectUpdateCorrection"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="ProjectUpdateCorrection.id"
    )


class ProjectUpdatePhoto(Base):
    __tablename__ = "project_update_photos"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    update_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_updates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/project_updates
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)


class ProjectUpdateCorrection(Base):
    """The wording before a correction to a published update, with who corrected it, when and why."""

    __tablename__ = "project_update_corrections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    update_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project_updates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    previous_title: Mapped[str] = mapped_column(String(200), nullable=False)
    previous_body: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
