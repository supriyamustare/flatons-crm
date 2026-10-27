import enum
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.base import NO_VALUE

from app.models.base import Base, TimestampMixin
from app.models.project import Project
from app.models.user import User


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class LeadStatus(enum.StrEnum):
    new = "new"
    not_reachable = "not_reachable"
    contacted = "contacted"
    qualified = "qualified"
    follow_up = "follow_up"
    visit_scheduled = "visit_scheduled"
    visit_done = "visit_done"
    revisit = "revisit"
    negotiation = "negotiation"
    on_hold = "on_hold"
    booked = "booked"
    lost = "lost"
    junk = "junk"


# Statuses that need a reason, and statuses only managers/admins may set or leave.
REASON_REQUIRED = {LeadStatus.lost, LeadStatus.junk}
MANAGER_ONLY = {LeadStatus.booked}


class LeadSource(enum.StrEnum):
    website = "website"
    acres_99 = "99acres"
    magicbricks = "magicbricks"
    housing = "housing"
    social = "social"
    google_ads = "google_ads"
    walk_in = "walk_in"
    referral = "referral"
    channel_partner = "channel_partner"
    print = "print"
    other = "other"


class Configuration(enum.StrEnum):
    bhk1 = "1bhk"
    bhk2 = "2bhk"
    bhk3 = "3bhk"
    bhk4 = "4bhk"
    studio = "studio"
    shop = "shop"
    office = "office"
    plot = "plot"


class Purpose(enum.StrEnum):
    self_use = "self_use"
    investment = "investment"


class BuyingTimeline(enum.StrEnum):
    immediate = "immediate"
    within_3_months = "within_3_months"
    within_6_months = "within_6_months"
    beyond_6_months = "beyond_6_months"


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_mobile", "mobile"),
        Index("ix_leads_alt_mobile", "alt_mobile"),
        Index("ix_leads_email_lower", text("lower(email)")),
        Index("ix_leads_status", "status"),
        Index("ix_leads_assigned_to_id", "assigned_to_id"),
        Index("ix_leads_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    mobile: Mapped[str] = mapped_column(String(16), nullable=False)
    alt_mobile: Mapped[str | None] = mapped_column(String(16))
    email: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))

    source: Mapped[LeadSource] = mapped_column(_pg_enum(LeadSource, "lead_source"), nullable=False)
    sub_source: Mapped[str | None] = mapped_column(String(150))

    project_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="SET NULL")
    )
    configuration: Mapped[Configuration | None] = mapped_column(
        _pg_enum(Configuration, "lead_configuration")
    )
    budget_min: Mapped[int | None] = mapped_column(BigInteger)  # rupees
    budget_max: Mapped[int | None] = mapped_column(BigInteger)
    purpose: Mapped[Purpose | None] = mapped_column(_pg_enum(Purpose, "lead_purpose"))
    timeline: Mapped[BuyingTimeline | None] = mapped_column(
        _pg_enum(BuyingTimeline, "lead_timeline")
    )

    assigned_to_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[LeadStatus] = mapped_column(
        _pg_enum(LeadStatus, "lead_status"), nullable=False, default=LeadStatus.new
    )
    # When the lead entered its current status; maintained automatically (see below).
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    lost_reason: Mapped[str | None] = mapped_column(String(255))
    estimated_value: Mapped[int | None] = mapped_column(BigInteger)  # rupees
    # Marketing campaign this lead came from (for cost per lead)
    campaign_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    remarks: Mapped[str | None] = mapped_column(Text)

    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    assigned_to: Mapped[User | None] = relationship(foreign_keys=[assigned_to_id], lazy="selectin")
    created_by: Mapped[User | None] = relationship(foreign_keys=[created_by_id], lazy="selectin")
    project: Mapped[Project | None] = relationship(lazy="selectin")
    campaign: Mapped["Campaign | None"] = relationship("Campaign", lazy="selectin")  # noqa: F821


class LeadActivity(Base):
    """Timeline entry on a lead. `type` is a plain string so later sprints can add
    call, visit and task entries without a database enum change."""

    __tablename__ = "lead_activities"
    __table_args__ = (Index("ix_lead_activities_lead_id_created_at", "lead_id", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    actor: Mapped[User | None] = relationship(lazy="selectin")


class LeadCodeCounter(Base):
    """One row per day (IST); incremented atomically to build LEAD-YYYYMMDD-NNNN."""

    __tablename__ = "lead_code_counters"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False)


@event.listens_for(Lead.status, "set")
def _stamp_status_change(target: Lead, value, oldvalue, initiator) -> None:
    """Whenever a lead's status actually changes, by hand, by a site visit or later by a booking,
    record when. Pipeline "days in stage" depends on this, so it lives here rather than in each
    place that changes the status."""
    if oldvalue is not NO_VALUE and value != oldvalue:
        target.status_changed_at = datetime.now(UTC)
