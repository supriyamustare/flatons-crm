import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.lead import Lead
from app.models.project import Project
from app.models.user import User


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class VisitStatus(enum.StrEnum):
    scheduled = "scheduled"
    completed = "completed"
    no_show = "no_show"
    cancelled = "cancelled"


class VisitSource(enum.StrEnum):
    """How this visit came about; separate from where the lead first came from."""

    sales_follow_up = "sales_follow_up"
    walk_in = "walk_in"
    channel_partner = "channel_partner"
    referral = "referral"
    event = "event"
    other = "other"


class InterestLevel(enum.StrEnum):
    hot = "hot"
    warm = "warm"
    cold = "cold"


class SiteVisit(TimestampMixin, Base):
    __tablename__ = "site_visits"
    __table_args__ = (
        Index("ix_site_visits_status_scheduled_at", "status", "scheduled_at"),
        Index("ix_site_visits_lead_id", "lead_id"),
        Index("ix_site_visits_host_id", "host_id"),
        Index("ix_site_visits_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    # The salesperson showing the site
    host_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    visit_source: Mapped[VisitSource] = mapped_column(
        _enum(VisitSource, "visit_source"), nullable=False
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[VisitStatus] = mapped_column(
        _enum(VisitStatus, "visit_status"), nullable=False, default=VisitStatus.scheduled
    )
    notes: Mapped[str | None] = mapped_column(Text)
    reschedule_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )

    # Filled in after the visit
    feedback: Mapped[str | None] = mapped_column(Text)
    interest_level: Mapped[InterestLevel | None] = mapped_column(
        _enum(InterestLevel, "interest_level")
    )
    next_action: Mapped[str | None] = mapped_column(String(255))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))

    lead: Mapped[Lead] = relationship(lazy="selectin")
    project: Mapped[Project] = relationship(lazy="selectin")
    host: Mapped[User | None] = relationship(foreign_keys=[host_id], lazy="selectin")
