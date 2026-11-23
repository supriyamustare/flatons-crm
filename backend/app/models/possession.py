"""Pre-possession: financial, document and unit-readiness checklists, finance clearance, and the possession gate."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    String,
    Text,
    func,
    text,
)
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
    gate_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # legal eligibility for possession
    # Stage 14: the handover itself
    handover: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    handover_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handover_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    actual_possession_on: Mapped[date | None] = mapped_column(Date)
    after_sales_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )  # transferred to the service team


class Inspection(Base):
    """A customer inspection of the unit (Stage 13)."""

    __tablename__ = "possession_inspections"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("possession_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    appointment_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("appointments.id", ondelete="SET NULL")
    )
    conducted_on: Mapped[date | None] = mapped_column(Date)
    attendees: Mapped[str | None] = mapped_column(String(500))
    notes: Mapped[str | None] = mapped_column(Text)
    report_shared_on: Mapped[date | None] = mapped_column(Date)
    report_shared_via: Mapped[str | None] = mapped_column(String(30))
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
    )  # open / fixed / verified / closed
    inspection_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("possession_inspections.id", ondelete="SET NULL")
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", server_default=text("'internal'")
    )  # internal / customer
    category: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other", server_default=text("'other'")
    )  # civil, electrical, plumbing, finishing, fittings, other
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="minor", server_default=text("'minor'")
    )  # minor / major / critical
    rectification: Mapped[str | None] = mapped_column(Text)
    fixed_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_response: Mapped[str | None] = mapped_column(String(10))  # accepted / disputed
    customer_note: Mapped[str | None] = mapped_column(String(1000))
    reopen_reason: Mapped[str | None] = mapped_column(String(1000))
    reopened_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    escalated_on: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(1000))
    raised_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SnagEvidence(Base):
    __tablename__ = "possession_snag_evidence"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    snag_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("possession_snags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)  # issue / completion
    file_path: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # under FILE_STORAGE_PATH/snags
    file_name: Mapped[str] = mapped_column(String(150), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    uploaded_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
