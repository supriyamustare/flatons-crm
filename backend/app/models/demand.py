"""Demands: a request to the customer to pay a stage (plus any earlier dues), approved before it's issued.

An approved demand's letter is frozen (letter snapshot). A correction cancels it and issues a new version."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DemandStatus(enum.StrEnum):
    draft = "draft"
    pending_approval = "pending_approval"
    approved = "approved"
    issued = "issued"
    cancelled = "cancelled"


class IssueMethod(enum.StrEnum):
    email = "email"
    hand = "hand"  # handed over
    courier = "courier"
    whatsapp = "whatsapp"
    other = "other"


class Demand(TimestampMixin, Base):
    __tablename__ = "demands"
    __table_args__ = (
        CheckConstraint(
            "stage_amount >= 0 AND previous_dues >= 0 AND total_due >= 0",
            name="amounts_not_negative",
        ),
        CheckConstraint(
            "(status = 'cancelled') = (cancel_reason IS NOT NULL)", name="cancel_needs_reason"
        ),
        # one live demand per stage of a case (cancelled ones are kept as history)
        Index(
            "uq_demands_live_stage",
            "case_id",
            "stage_seq",
            unique=True,
            postgresql_where=text("status <> 'cancelled'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    stage_seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_name: Mapped[str] = mapped_column(String(120), nullable=False)
    stage_amount: Mapped[int] = mapped_column(
        BigInteger, nullable=False
    )  # this stage still unpaid, incl. GST
    previous_dues: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )  # earlier demanded stages still unpaid
    total_due: Mapped[int] = mapped_column(BigInteger, nullable=False)
    demanded_on: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[DemandStatus] = mapped_column(
        Enum(DemandStatus, name="demand_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=DemandStatus.draft,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supersedes_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("demands.id", ondelete="SET NULL")
    )
    milestone_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("project_milestones.id", ondelete="SET NULL")
    )
    prepared_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issue_method: Mapped[IssueMethod | None] = mapped_column(
        Enum(IssueMethod, name="issue_method", values_callable=lambda e: [m.value for m in e])
    )
    cancelled_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))
    note: Mapped[str | None] = mapped_column(String(500))  # last return reason
    # Frozen at approval: everything the letter shows (the bank account number is kept encrypted)
    letter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
