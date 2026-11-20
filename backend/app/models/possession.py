"""Pre-possession: financial, document and unit-readiness checklists, finance clearance, and the possession gate."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Identity, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PossessionFile(TimestampMixin, Base):
    __tablename__ = "possession_files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("postsales_cases.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    started_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    start_reason: Mapped[str | None] = mapped_column(
        String(500)
    )  # when started before the trigger milestone
    # A. finance (confirmations by finance; figures are worked out from the ledger)
    finance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    clearance_requested_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    clearance_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clearance_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB
    )  # the figures when clearance was requested
    cleared_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    clearance_note: Mapped[str | None] = mapped_column(String(1000))
    clearance_returned_reason: Mapped[str | None] = mapped_column(String(1000))
    # B. documents and C. readiness: {item: {"status", "note", "document_id", "by", "at"}}
    documents: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    readiness: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    meters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    readiness_approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    readiness_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    internal_approved_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    internal_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # D. an authorised exception: {"by", "by_name", "at", "reason", "scope": [conditions]}
    exception: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Snag(Base):
    __tablename__ = "possession_snags"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("possession_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str | None] = mapped_column(String(120))
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )  # rectification owner
    due_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open"
    )  # open / fixed / verified
    note: Mapped[str | None] = mapped_column(String(1000))
    raised_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
