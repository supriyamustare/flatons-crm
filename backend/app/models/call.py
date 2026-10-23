import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.lead import Lead
from app.models.user import User


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


class CallOutcome(enum.StrEnum):
    # Connected: the customer answered
    interested = "interested"
    callback = "callback"
    not_interested = "not_interested"
    # Not connected
    no_answer = "no_answer"
    busy = "busy"
    unreachable = "unreachable"
    wrong_number = "wrong_number"


CONNECTED_OUTCOMES = {CallOutcome.interested, CallOutcome.callback, CallOutcome.not_interested}


class CallDirection(enum.StrEnum):
    outgoing = "outgoing"
    incoming = "incoming"


class CallLog(Base):
    __tablename__ = "call_logs"
    __table_args__ = (
        Index("ix_call_logs_user_called_at", "user_id", "called_at"),
        Index("ix_call_logs_lead_id", "lead_id"),
        Index("ix_call_logs_called_at", "called_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    # Who made or took the call
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    direction: Mapped[CallDirection] = mapped_column(
        _enum(CallDirection, "call_direction"), nullable=False, default=CallDirection.outgoing
    )
    outcome: Mapped[CallOutcome] = mapped_column(_enum(CallOutcome, "call_outcome"), nullable=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)
    called_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Follow-up created from this call (when a next date was set)
    follow_up_task_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("follow_up_tasks.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    lead: Mapped[Lead] = relationship(lazy="selectin")
    user: Mapped[User | None] = relationship(lazy="selectin")
