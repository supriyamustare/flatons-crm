"""Construction milestones per project, reported with evidence and verified by someone else."""

import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
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
        CheckConstraint(
            "percent_complete IS NULL OR percent_complete BETWEEN 0 AND 100", name="percent_range"
        ),
        CheckConstraint(
            "delay_reason IS NULL OR revised_expected_on IS NOT NULL", name="delay_has_revised_date"
        ),
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
    # Construction team inputs (progress; none of these can trigger a demand: only verified completion does)
    phase: Mapped[str | None] = mapped_column(String(80))
    building_label: Mapped[str | None] = mapped_column(
        String(80)
    )  # tower / building, for information
    planned_on: Mapped[date | None] = mapped_column(Date)
    percent_complete: Mapped[int | None] = mapped_column(Integer)
    responsible_pm_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    delay_reason: Mapped[str | None] = mapped_column(String(500))
    revised_expected_on: Mapped[date | None] = mapped_column(Date)
    schedule_impact: Mapped[str | None] = mapped_column(
        Text
    )  # impact on demand / possession schedule, if assessed
    impact_recorded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    impact_approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    impact_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evidence: Mapped[list["MilestoneEvidence"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="MilestoneEvidence.id"
    )
    progress: Mapped[list["MilestoneProgress"]] = relationship(
        lazy="selectin", cascade="all, delete-orphan", order_by="MilestoneProgress.id.desc()"
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
    progress_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("milestone_progress.id", ondelete="SET NULL")
    )  # photos from a progress update


class MilestoneProgress(Base):
    """One progress update (history): percentage, dates, delay. Informational only; never triggers a demand."""

    __tablename__ = "milestone_progress"
    __table_args__ = (
        CheckConstraint(
            "percent_complete IS NULL OR percent_complete BETWEEN 0 AND 100", name="percent_range"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    milestone_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("project_milestones.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    percent_complete: Mapped[int | None] = mapped_column(Integer)
    planned_on: Mapped[date | None] = mapped_column(Date)
    revised_expected_on: Mapped[date | None] = mapped_column(Date)
    delay_reason: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(Text)
    by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
