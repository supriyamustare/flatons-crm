"""Construction milestones per project, reported with evidence and verified by someone else."""

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class MilestoneStatus(enum.StrEnum):
    planned = "planned"
    reported = "reported"  # reported complete; waiting for verification
    verified = "verified"  # verified; its stages are demanded


class ProjectMilestone(TimestampMixin, Base):
    __tablename__ = "project_milestones"
    __table_args__ = (
        Index("uq_project_milestones_name", "project_id", text("lower(name)"), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(
        String(120), nullable=False
    )  # matches the payment stage's milestone name
    status: Mapped[MilestoneStatus] = mapped_column(
        Enum(
            MilestoneStatus, name="milestone_status", values_callable=lambda e: [m.value for m in e]
        ),
        nullable=False,
        default=MilestoneStatus.planned,
    )
    completed_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    reported_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_reason: Mapped[str | None] = mapped_column(String(500))

    evidence: Mapped[list["MilestoneEvidence"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="MilestoneEvidence.id"
    )


class MilestoneEvidence(Base):
    __tablename__ = "milestone_evidence"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    milestone_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("project_milestones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/milestones
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
