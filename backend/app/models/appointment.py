"""Post-sales appointments: signing, registration, inspections, possession, defects, document collection, visits."""

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
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class AppointmentKind(enum.StrEnum):
    agreement_signing = "agreement_signing"
    registration = "registration"
    site_visit = "site_visit"
    inspection = "inspection"  # customer inspection
    possession = "possession"  # possession handover
    defect_inspection = "defect_inspection"
    document_collection = "document_collection"
    other = "other"


class AppointmentStatus(enum.StrEnum):
    scheduled = "scheduled"
    attended = "attended"
    no_show = "no_show"  # customer didn't come: a follow-up is created
    cancelled = "cancelled"
    rescheduled = "rescheduled"  # replaced by a new appointment (kept for history)


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("duration_min BETWEEN 15 AND 480", name="duration_range"),
        CheckConstraint(
            "status NOT IN ('cancelled', 'rescheduled') OR status_reason IS NOT NULL",
            name="reason_for_cancel_or_reschedule",
        ),
        Index("ix_appointments_owner_start", "owner_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[AppointmentKind] = mapped_column(
        _enum(AppointmentKind, "appointment_kind"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    duration_min: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    location: Mapped[str | None] = mapped_column(String(300))
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    required_docs: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[AppointmentStatus] = mapped_column(
        _enum(AppointmentStatus, "appointment_status"),
        nullable=False,
        default=AppointmentStatus.scheduled,
    )
    status_reason: Mapped[str | None] = mapped_column(String(500))  # cancel / reschedule reason
    confirmed_on: Mapped[date | None] = mapped_column(Date)  # customer confirmed
    confirmed_via: Mapped[str | None] = mapped_column(String(30))
    outcome: Mapped[str | None] = mapped_column(Text)
    follow_up_on: Mapped[date | None] = mapped_column(
        Date, index=True
    )  # set automatically when missed
    rescheduled_from_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL")
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    reminders_sent: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # {"tomorrow": "2026-11-19", ...}
