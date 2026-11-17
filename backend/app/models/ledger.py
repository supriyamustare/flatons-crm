"""The customer's financial ledger for a booking: charge heads, payment schedule and funding (own vs loan)."""

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
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class LedgerStatus(enum.StrEnum):
    draft = "draft"  # finance is preparing it
    pending_approval = "pending_approval"  # submitted; waiting for a finance approver
    approved = "approved"  # locked; changes need the approver to reopen it


class ChargeHead(enum.StrEnum):
    # Agreement value
    base_price = "base_price"
    floor_rise = "floor_rise"
    plc = "plc"  # preferred location charge
    parking = "parking"
    amenities = "amenities"
    discount = "discount"  # entered as a negative amount
    # Tax
    gst = "gst"
    # Statutory (paid at registration)
    stamp_duty = "stamp_duty"
    registration = "registration"
    # Other charges (outside the payment plan)
    legal = "legal"
    furnishing = "furnishing"
    maintenance_deposit = "maintenance_deposit"
    society_formation = "society_formation"
    other = "other"


AGREEMENT_HEADS = (
    ChargeHead.base_price,
    ChargeHead.floor_rise,
    ChargeHead.plc,
    ChargeHead.parking,
    ChargeHead.amenities,
    ChargeHead.discount,
)
STATUTORY_HEADS = (ChargeHead.stamp_duty, ChargeHead.registration)
OTHER_HEADS = (
    ChargeHead.legal,
    ChargeHead.furnishing,
    ChargeHead.maintenance_deposit,
    ChargeHead.society_formation,
    ChargeHead.other,
)


class TriggerType(enum.StrEnum):
    on_booking = "on_booking"  # due on the booking date
    on_date = "on_date"  # due on a fixed date
    on_milestone = "on_milestone"  # due when a construction milestone is reached (Sprint 4)


class Ledger(TimestampMixin, Base):
    __tablename__ = "ledgers"
    __table_args__ = (
        CheckConstraint("loan_sanctioned >= 0", name="loan_not_negative"),
        CheckConstraint("gst_pct >= 0 AND gst_pct <= 100", name="gst_pct_range"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    status: Mapped[LedgerStatus] = mapped_column(
        _enum(LedgerStatus, "ledger_status"), nullable=False, default=LedgerStatus.draft
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    gst_pct: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=1)
    loan_sanctioned: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)  # rupees
    lender: Mapped[str | None] = mapped_column(String(150))
    loan_reference: Mapped[str | None] = mapped_column(String(80))
    submitted_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(String(500))  # last return / reopen reason

    charges: Mapped[list["LedgerCharge"]] = relationship(
        lazy="selectin", order_by="LedgerCharge.sort_order", cascade="all, delete-orphan"
    )
    schedule: Mapped[list["ScheduleItem"]] = relationship(
        lazy="selectin", order_by="ScheduleItem.seq", cascade="all, delete-orphan"
    )


class LedgerCharge(Base):
    __tablename__ = "ledger_charges"
    __table_args__ = (
        CheckConstraint(
            "(head = 'discount' AND amount < 0) OR (head <> 'discount' AND amount > 0)",
            name="sign_matches_head",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ledger_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ledgers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    head: Mapped[ChargeHead] = mapped_column(_enum(ChargeHead, "charge_head"), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )  # rupees; negative only for discounts
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class ScheduleItem(Base):
    __tablename__ = "ledger_schedule_items"
    __table_args__ = (
        CheckConstraint("amount >= 0 AND gst >= 0", name="amounts_not_negative"),
        CheckConstraint(
            "trigger_type <> 'on_date' OR due_date IS NOT NULL", name="date_trigger_has_date"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ledger_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ledgers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # excluding GST
    gst: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    trigger_type: Mapped[TriggerType] = mapped_column(
        _enum(TriggerType, "trigger_type"), nullable=False
    )
    due_date: Mapped[date | None] = mapped_column(
        Date
    )  # set for booking/date triggers; for milestones once reached
    # When the stage was demanded (booking date, the fixed date, or when its milestone was verified)
    demanded_on: Mapped[date | None] = mapped_column(Date)
    milestone: Mapped[str | None] = mapped_column(String(120))
