"""Payment follow-ups: each contact with the customer about money owed, and any promise to pay."""

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
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class FollowUpChannel(enum.StrEnum):
    call = "call"
    email = "email"
    sms = "sms"
    whatsapp = "whatsapp"
    visit = "visit"
    letter = "letter"
    note = "note"  # internal note, no contact


class FollowUpOutcome(enum.StrEnum):
    reached = "reached"
    not_reachable = "not_reachable"
    promised = "promised"  # promised to pay (with a date and amount)
    disputed = "disputed"
    says_paid = "says_paid"  # customer says they've already paid
    other = "other"


class PaymentFollowUp(Base):
    __tablename__ = "payment_follow_ups"
    __table_args__ = (
        CheckConstraint(
            "(outcome = 'promised') = (promise_date IS NOT NULL AND promise_amount IS NOT NULL)",
            name="promise_complete",
        ),
        CheckConstraint("promise_amount IS NULL OR promise_amount > 0", name="promise_positive"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("postsales_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    demand_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("demands.id", ondelete="SET NULL")
    )
    channel: Mapped[FollowUpChannel] = mapped_column(
        _enum(FollowUpChannel, "follow_up_channel"), nullable=False
    )
    outcome: Mapped[FollowUpOutcome] = mapped_column(
        _enum(FollowUpOutcome, "follow_up_outcome"), nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)
    contacted_on: Mapped[date] = mapped_column(Date, nullable=False)
    promise_date: Mapped[date | None] = mapped_column(Date)
    promise_amount: Mapped[int | None] = mapped_column(BigInteger)
    next_follow_up_on: Mapped[date | None] = mapped_column(Date, index=True)
    broken_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # so a broken promise alerts once
    by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
