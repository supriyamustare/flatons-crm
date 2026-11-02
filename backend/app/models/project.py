import enum
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Identity,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class Developer(TimestampMixin, Base):
    """The builder behind a developer project. Legal details are added in Sprint 10."""

    __tablename__ = "developers"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)


class ProjectType(enum.StrEnum):
    developer = "developer"  # Flatons sells a developer's new project
    resale = "resale"  # Flatons sells existing homes on behalf of owners


class ProjectStatus(enum.StrEnum):
    pre_launch = "pre_launch"
    under_construction = "under_construction"
    ready_to_move = "ready_to_move"
    sold_out = "sold_out"


class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    __table_args__ = (
        # The Flatons/Developer distinction lives in the data, not just the UI:
        # developer projects must name their developer; resale listings must not have one.
        CheckConstraint(
            "commission_pct IS NULL OR (commission_pct >= 0 AND commission_pct <= 100)",
            name="commission_pct_range",
        ),
        CheckConstraint(
            "(project_type = 'developer' AND developer_id IS NOT NULL)"
            " OR (project_type = 'resale' AND developer_id IS NULL)",
            name="developer_matches_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    project_type: Mapped[ProjectType] = mapped_column(
        _enum(ProjectType, "project_type"), nullable=False, server_default="developer"
    )
    developer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("developers.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[ProjectStatus] = mapped_column(
        _enum(ProjectStatus, "project_status"), nullable=False, server_default="under_construction"
    )
    location: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Flatons' commission (or brokerage) as a % of the deal value, for estimated revenue
    commission_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    developer: Mapped[Developer | None] = relationship(lazy="selectin")
