import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.inventory import Unit
from app.models.lead import Lead
from app.models.project import Project
from app.models.user import User


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class BookingStatus(enum.StrEnum):
    booked = "booked"
    cancelled = "cancelled"


class PaymentMode(enum.StrEnum):
    cheque = "cheque"
    bank_transfer = "bank_transfer"  # NEFT / RTGS / IMPS
    upi = "upi"
    card = "card"
    cash = "cash"
    other = "other"


class PaymentPreference(enum.StrEnum):
    self_funded = "self"  # customer pays from own funds
    bank_loan = "bank"  # home loan from a bank


class Booking(TimestampMixin, Base):
    """A flat (unit) booked for a lead. Amounts are whole rupees."""

    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("agreed_price > 0", name="agreed_price_positive"),
        CheckConstraint(
            "booking_amount >= 0 AND booking_amount <= agreed_price", name="booking_amount_range"
        ),
        CheckConstraint("commission_received >= 0", name="commission_received_positive"),
        CheckConstraint(
            "(status = 'cancelled') = (cancelled_at IS NOT NULL)", name="cancel_fields_match"
        ),
        # At most one live booking per lead and per unit; cancelled ones are history
        Index(
            "uq_bookings_live_lead",
            "lead_id",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        Index(
            "uq_bookings_live_unit",
            "unit_id",
            unique=True,
            postgresql_where=text("status = 'booked'"),
        ),
        Index("ix_bookings_booking_date", "booking_date"),
        Index("ix_bookings_sales_exec_id", "sales_exec_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="RESTRICT"), nullable=False
    )
    unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[BookingStatus] = mapped_column(
        _enum(BookingStatus, "booking_status"), nullable=False, default=BookingStatus.booked
    )
    booking_date: Mapped[date] = mapped_column(Date, nullable=False)
    agreed_price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    booking_amount: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    payment_mode: Mapped[PaymentMode | None] = mapped_column(_enum(PaymentMode, "payment_mode"))
    payment_reference: Mapped[str | None] = mapped_column(String(100))
    channel_partner: Mapped[str | None] = mapped_column(String(150))
    channel_partner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("channel_partners.id", ondelete="SET NULL"), index=True
    )
    # Flatons' commission: expected is worked out from the project's % (editable); received is entered later
    commission_expected: Mapped[int | None] = mapped_column(BigInteger)
    commission_received: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default=text("0")
    )
    notes: Mapped[str | None] = mapped_column(Text)
    # Customer details for the agreement (snapshot; defaults from the lead)
    customer_name: Mapped[str | None] = mapped_column(String(150))
    applicant_name: Mapped[str | None] = mapped_column(
        String(150)
    )  # name on the agreement / co-applicant
    customer_mobile: Mapped[str | None] = mapped_column(String(20))
    customer_email: Mapped[str | None] = mapped_column(String(254))
    customer_address: Mapped[str | None] = mapped_column(String(500))
    payment_preference: Mapped[PaymentPreference | None] = mapped_column(
        _enum(PaymentPreference, "payment_preference")
    )
    bank_name: Mapped[str | None] = mapped_column(String(150))
    banker_name: Mapped[str | None] = mapped_column(String(150))  # contact person at the bank
    banker_phone: Mapped[str | None] = mapped_column(String(20))
    sales_exec_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    recorded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancellation_reason: Mapped[str | None] = mapped_column(String(255))

    lead: Mapped[Lead] = relationship(lazy="selectin")
    unit: Mapped[Unit] = relationship(lazy="selectin")
    project: Mapped[Project] = relationship(lazy="selectin")
    sales_exec: Mapped[User | None] = relationship(foreign_keys=[sales_exec_id], lazy="selectin")
    recorded_by: Mapped[User | None] = relationship(foreign_keys=[recorded_by_id], lazy="selectin")


class BookingEvent(Base):
    """History of a booking: created, edited, cancelled, commission received."""

    __tablename__ = "booking_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    booking_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    actor: Mapped[User | None] = relationship(lazy="selectin")
