import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.user import User


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class UnitType(enum.StrEnum):
    bhk1 = "1bhk"
    bhk2 = "2bhk"
    bhk3 = "3bhk"
    bhk4 = "4bhk"
    studio = "studio"
    shop = "shop"
    office = "office"


class UnitStatus(enum.StrEnum):
    available = "available"
    on_hold = "on_hold"
    booked = "booked"  # set by the bookings module (Sprint 11)
    sold = "sold"
    withdrawn = "withdrawn"


class Building(TimestampMixin, Base):
    __tablename__ = "buildings"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_buildings_project_name"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )


class Floor(Base):
    __tablename__ = "floors"
    __table_args__ = (UniqueConstraint("building_id", "number", name="uq_floors_building_number"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    building_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("buildings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 0 = ground, negative = basement, positive = upper floors
    number: Mapped[int] = mapped_column(Integer, nullable=False)


class Unit(TimestampMixin, Base):
    """A flat, shop or office. Developer-project units sit on a floor; resale units belong to
    the project directly (no building grid)."""

    __tablename__ = "units"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "building_id", "unit_no", name="uq_units_project_building_unit_no"
        ),
        Index("ix_units_project_status", "project_id", "status"),
        CheckConstraint("carpet_sqft IS NULL OR carpet_sqft > 0", name="carpet_positive"),
        CheckConstraint("builtup_sqft IS NULL OR builtup_sqft > 0", name="builtup_positive"),
        CheckConstraint(
            "carpet_sqft IS NULL OR builtup_sqft IS NULL OR builtup_sqft >= carpet_sqft",
            name="builtup_at_least_carpet",
        ),
        CheckConstraint("base_price IS NULL OR base_price >= 0", name="base_price_not_negative"),
        CheckConstraint(
            "current_asking_price IS NULL OR current_asking_price >= 0", name="asking_not_negative"
        ),
        # A hold always has a holder and an expiry; anything else never does.
        CheckConstraint(
            "(status = 'on_hold') = (held_by_id IS NOT NULL AND hold_expires_at IS NOT NULL)",
            name="hold_fields_match_status",
        ),
        CheckConstraint(
            "(floor_id IS NULL) = (building_id IS NULL)", name="floor_and_building_together"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Kept alongside floor_id so unit numbers can be unique per building and queries stay simple
    building_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("buildings.id", ondelete="CASCADE")
    )
    floor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("floors.id", ondelete="CASCADE"), index=True
    )
    unit_no: Mapped[str] = mapped_column(String(20), nullable=False)
    unit_type: Mapped[UnitType] = mapped_column(_enum(UnitType, "unit_type"), nullable=False)
    carpet_sqft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    builtup_sqft: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    base_price: Mapped[int | None] = mapped_column(BigInteger)  # rupees
    current_asking_price: Mapped[int | None] = mapped_column(BigInteger)  # rupees
    # For resale units: where it is, e.g. "Wing B, 7th floor"
    address_note: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[UnitStatus] = mapped_column(
        _enum(UnitStatus, "unit_status"), nullable=False, default=UnitStatus.available
    )

    held_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    held_for_lead_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="SET NULL")
    )
    held_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hold_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    hold_note: Mapped[str | None] = mapped_column(String(255))
    # Linked by the bookings module in Sprint 11
    booking_id: Mapped[int | None] = mapped_column(BigInteger)

    held_by: Mapped[User | None] = relationship(foreign_keys=[held_by_id], lazy="selectin")
